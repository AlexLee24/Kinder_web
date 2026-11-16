"""Give DETECT results made before the Euclid image existed their second review image (Euclid VIS cutout).

    KINDER_ENV_FILE=kinder.env .venv/bin/python scripts/detect_euclid_backfill.py --days 30 [--run] [--redo]

New DETECT runs make the image themselves (app/services/detect/euclid_image.py). This covers what DETECT screened in
the last ``--days``: TNS objects (transient.detect_screen.run_date) without a 'Euclid' row in transient.target_images,
and LSST alerts (transient.lsst_detect_screen.run_date) whose lsst_target_images.euclid_data is empty. Candidates and
the host come from the stored cross-matches, so DETECT itself is not re-run.

Most positions are outside Euclid and are skipped from the cached tile list without asking ESA. Without --run it only
lists the targets near a Euclid tile; --redo also replaces images that already exist.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'app' / 'vendor' / 'DETECT')]


def _tns_targets(cur, days, redo):
    cur.execute(f"""
        SELECT o.name, o.ra, o.dec
          FROM transient.detect_screen s JOIN transient.objects o ON o.obj_id = s.obj_id
         WHERE s.run_date >= now() - %s * INTERVAL '1 day' AND o.ra IS NOT NULL
           AND EXISTS (SELECT 1 FROM transient.cross_matches m WHERE m.obj_id = o.obj_id)
           {'' if redo else "AND NOT EXISTS (SELECT 1 FROM transient.target_images t WHERE t.obj_id = o.obj_id AND t.source = 'Euclid')"}
         ORDER BY s.run_date DESC""", (days,))
    return cur.fetchall()


def _lsst_targets(cur, days, redo):
    cur.execute(f"""
        SELECT s.oid, a.ra, a.dec
          FROM transient.lsst_detect_screen s
          JOIN transient.lsst_alerts a ON a.oid = s.oid
          JOIN transient.lsst_target_images i ON i.oid = s.oid
         WHERE s.run_date >= now() - %s * INTERVAL '1 day' {'' if redo else 'AND i.euclid_data IS NULL'}
         ORDER BY s.run_date DESC""", (days,))
    return cur.fetchall()


def _candidates(cur, table, key, value):
    cur.execute(f"SELECT match_id, catalog, match_ra, match_dec, is_host FROM transient.{table} "
                f"WHERE {key} = %s AND match_ra IS NOT NULL", (value,))
    rows = cur.fetchall()
    cands = [{'ra': float(r[2]), 'dec': float(r[3]), 'crossmatch_uid': f'm{r[0]}', 'catalog_name': r[1] or ''}
             for r in rows]
    host = next((f'm{r[0]}' for r in rows if r[4]), None)
    return cands, host


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--run', action='store_true', help='make and store the images (default: list only)')
    ap.add_argument('--redo', action='store_true', help='also replace existing Euclid images')
    ap.add_argument('--skip-tns', action='store_true')
    ap.add_argument('--skip-lsst', action='store_true')
    args = ap.parse_args()

    from app.db import get_db_connection
    from app.db.transient import save_detect_image
    from app.services.astro import euclid_cutout as ec
    from app.services.detect.euclid_image import SOURCE, build_png
    from app.services.lsst import detect as lsst_detect
    from function.module.cross_match import _estimate_fov_arcsec

    print(f'Euclid tile list: {ec.refresh_tiles()} VIS tiles')
    with get_db_connection() as conn:
        cur = conn.cursor()
        jobs = []
        if not args.skip_tns:
            for name, ra, dec in _tns_targets(cur, args.days, args.redo):
                jobs.append(('TNS', name, name, float(ra), float(dec)))
        if not args.skip_lsst:
            for oid, ra, dec in _lsst_targets(cur, args.days, args.redo):
                jobs.append(('LSST', oid, lsst_detect.target_name(oid), float(ra), float(dec)))
        near = [j for j in jobs if ec.near_tile(j[3], j[4])]
        print(f'{len(jobs)} DETECT target(s) in the last {args.days} d; {len(near)} near a Euclid tile')
        made = 0
        for kind, key, name, ra, dec in near:
            if not args.run:
                print(f'  {kind:4s} {name}  {ra:.5f} {dec:+.5f}')
                continue
            if kind == 'TNS':
                cur.execute("SELECT obj_id FROM transient.objects WHERE name = %s", (name,))
                cands, host = _candidates(cur, 'cross_matches', 'obj_id', cur.fetchone()[0])
            else:
                cands, host = _candidates(cur, 'lsst_detect_matches', 'oid', key)
            t0 = time.monotonic()
            png = build_png(name, ra, dec, _estimate_fov_arcsec(ra, dec, cands), cands, host)
            if png is None:
                print(f'  {kind:4s} {name}: no Euclid pixels ({time.monotonic() - t0:.1f} s)')
                continue
            ok = (save_detect_image(name, SOURCE, png) is not None) if kind == 'TNS' else lsst_detect.save_euclid_image(key, png)
            made += bool(ok)
            print(f'  {kind:4s} {name}: Euclid image {"saved" if ok else "NOT saved"} ({time.monotonic() - t0:.1f} s)')
    if args.run:
        print(f'{made} Euclid image(s) stored')


if __name__ == '__main__':
    main()
