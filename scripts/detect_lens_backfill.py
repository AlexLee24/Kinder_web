"""Re-run DETECT on recent TNS objects and LSST alerts that sit on a newly added cat.lens catalogue.

    KINDER_ENV_FILE=kinder.env .venv/bin/python scripts/detect_lens_backfill.py Euclid-DR1-26Nov12 --days 30 [--run]

A new catalogue in cat.lens (scripts/add_lens_csv.py) only reaches objects DETECT screens from then on. This finds
what it would have caught in the last ``--days``:

* TNS: transient.objects discovered in the window within the lens radius (10") of one of the catalogue's lenses,
  re-run through DETECT (app/services/detect/detect_pipeline.run_for_names), as the object page's Run does.
* LSST: the ALeRCE LSST objects of ``--classes`` (default SN only) first detected in the window are read again, those near one of the
  catalogue's lenses go through the hourly watch's cross-match and store (app/services/lsst/alerts.process_objects,
  which also keeps an alert the watch had dropped for having no candidate), then DETECT screens them
  (app/services/lsst/detect.screen_alerts) — alerts already stored are re-screened too.

Without --run it only lists what it found. Objects not near the catalogue are left alone: DETECT would give them
the same result as before.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'app' / 'vendor' / 'DETECT')]

RADIUS_ARCSEC = 10.0          # DETECT's LENS_SEARCH_RADIUS_ARCSEC, the LSST watch's lens radius


def _near(ra, dec, lens_coords):
    """Indexes of (ra, dec) within RADIUS_ARCSEC of any lens."""
    import numpy as np
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    if not len(ra):
        return np.array([], int)
    idx, sep, _ = SkyCoord(np.asarray(ra, float) * u.deg, np.asarray(dec, float) * u.deg).match_to_catalog_sky(lens_coords)
    return np.flatnonzero(sep.arcsec <= RADIUS_ARCSEC)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('reference', help='the cat.lens reference to look for, e.g. Euclid-DR1-26Nov12')
    ap.add_argument('--days', type=float, default=30.0)
    ap.add_argument('--run', action='store_true', help='re-run DETECT (default: only list)')
    ap.add_argument('--skip-tns', action='store_true')
    ap.add_argument('--skip-lsst', action='store_true')
    ap.add_argument('--classes', default='SN', help='ALeRCE classes to read again, comma separated (SN,AGN,VS)')
    args = ap.parse_args(argv)

    from astropy import units as u
    from astropy.coordinates import SkyCoord

    from app.db import get_db_connection
    now_mjd = time.time() / 86400.0 + 40587.0
    since = now_mjd - args.days

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ra, dec FROM cat.lens WHERE %s = ANY(string_to_array(reference, ' '))", (args.reference,))
        lenses = cur.fetchall()
        if not lenses:
            print(f'No cat.lens row carries {args.reference}')
            return 1
        lens_coords = SkyCoord([r[0] for r in lenses] * u.deg, [r[1] for r in lenses] * u.deg)
        print(f'{args.reference}: {len(lenses)} lenses; window: last {args.days:g} days (MJD >= {since:.2f})')

        tns = []
        if not args.skip_tns:
            cur.execute("SELECT name, ra, dec FROM transient.objects WHERE discovery_date >= %s "
                        "AND ra IS NOT NULL AND dec IS NOT NULL", (since,))
            rows = cur.fetchall()
            tns = [rows[i][0] for i in _near([r[1] for r in rows], [r[2] for r in rows], lens_coords)]
            print(f'TNS: {len(rows)} objects discovered in the window, {len(tns)} near a lens: {", ".join(tns) or "-"}')

        stored = []
        if not args.skip_lsst:
            cur.execute("SELECT oid, ra, dec FROM transient.lsst_alerts WHERE firstmjd >= %s", (since,))
            rows = cur.fetchall()
            stored = [int(rows[i][0]) for i in _near([r[1] for r in rows], [r[2] for r in rows], lens_coords)]
            print(f'LSST stored: {len(rows)} alerts in the window, {len(stored)} near a lens')

    lsst_items = []
    if not args.skip_lsst:
        from app.services.lsst import alerce_api, alerts
        for cls in [c.strip() for c in args.classes.split(',') if c.strip()]:
            n, t0, kept = 0, time.monotonic(), 0
            batch = []
            for it in alerce_api.iter_new_objects(since, now_mjd + 0.1, cls):
                batch.append(it)
                n += 1
                if len(batch) >= 5000:
                    near = _near([b['meanra'] for b in batch], [b['meandec'] for b in batch], lens_coords)
                    lsst_items += [batch[i] for i in near]
                    kept += len(near)
                    batch = []
                    print(f'  {cls}: {n} read, {kept} near a lens…', flush=True)
            near = _near([b['meanra'] for b in batch], [b['meandec'] for b in batch], lens_coords)
            lsst_items += [batch[i] for i in near]
            kept += len(near)
            print(f'LSST ALeRCE {cls}: {n} objects first detected in the window, {kept} near a lens '
                  f'({time.monotonic() - t0:.0f} s)', flush=True)
        oids = sorted({int(i['oid']) for i in lsst_items} | set(stored))
        print(f'LSST: {len(oids)} alert(s) near a lens: {", ".join(map(str, oids[:50]))}{" …" if len(oids) > 50 else ""}')

    if not args.run:
        print('List only: add --run to re-run DETECT on these')
        return 0

    if tns:
        from app.services.detect import detect_pipeline
        print(f'DETECT on {len(tns)} TNS object(s)…', flush=True)
        print('  ', detect_pipeline.run_for_names(tns, label=f'{args.reference} backfill'))
    if not args.skip_lsst and oids:
        from app.services.lsst import alerts, detect
        print(f'LSST watch cross-match / store for {len(lsst_items)} ALeRCE object(s)…', flush=True)
        alerts.reload_lens_catalog()
        print('  ', alerts.process_objects(lsst_items))
        print(f'DETECT on {len(oids)} LSST alert(s)…', flush=True)
        print('  ', detect.screen_alerts(oids=oids, progress=lambda m: print('   ', m, flush=True),
                                         max_objects=max(len(oids), 1)))
    try:
        from app.blueprints.detect.cache import _soft_invalidate_page_cache
        _soft_invalidate_page_cache()
    except Exception:
        pass
    print('done')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
