"""Add a lens-candidate CSV to cat.lens, the table TNS-DETECT and LSST-DETECT cross-match against.

    KINDER_ENV_FILE=kinder.env .venv/bin/python scripts/add_lens_csv.py \\
        ~/Downloads/dr1_catalogue_v5_csv/csv/dr1_catalogue_15072_master.csv Euclid-DR1-26Nov12 \\
        --ra-col RA_obj --dec-col DEC_obj --grade-col grade [--prob-col P] [--known candidate] [--dry-run] [--replace]

Like app/vendor/DETECT/function/database/add_lens_catalog.py (Vizier tables), with the table's conventions:
a row within 2" of an existing cat.lens entry gets the new reference appended to that entry's (space separated)
instead of a second row; the rest are inserted with their HEALPix pixel. Existing rows are matched in memory, so
the run is a handful of queries even over a slow link. All in one transaction: --dry-run rolls it back.

A reference that is already in cat.lens stops the run; --replace first removes it (rows that only carry it are
deleted, merged rows lose the tag), so a newer release of the same catalogue can be loaded again.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'app' / 'vendor' / 'DETECT')]

DUPLICATE_ARCSEC = 2.0


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _remove_reference(cur, ref):
    cur.execute("DELETE FROM cat.lens WHERE reference = %s", (ref,))
    deleted = cur.rowcount
    cur.execute("UPDATE cat.lens SET reference = array_to_string(array_remove(string_to_array(reference, ' '), %s), ' ') "
                "WHERE %s = ANY(string_to_array(reference, ' '))", (ref, ref))
    return deleted, cur.rowcount


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('csv')
    ap.add_argument('reference', help='tag for cat.lens.reference (no spaces), e.g. Euclid-DR1-26Nov12')
    ap.add_argument('--ra-col', default='ra')
    ap.add_argument('--dec-col', default='dec')
    ap.add_argument('--grade-col')
    ap.add_argument('--prob-col')
    ap.add_argument('--z-col')
    ap.add_argument('--known', default='candidate', choices=('candidate', 'known', 'unknown'))
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    if not args.reference or ' ' in args.reference:
        ap.error('reference must be one word: cat.lens.reference is a space-separated list')

    import numpy as np
    import pandas as pd
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from psycopg2.extras import execute_values

    from app.db import get_db_connection
    from function.database.healpix_index import healpix_index

    df = pd.read_csv(args.csv, low_memory=False)
    df = df[df[args.ra_col].notna() & df[args.dec_col].notna()]
    print(f'{args.csv}: {len(df)} rows with a position')

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM cat.lens WHERE %s = ANY(string_to_array(reference, ' '))", (args.reference,))
        already = cur.fetchone()[0]
        if already and not args.replace:
            print(f'{args.reference} is already on {already} cat.lens rows; pass --replace to load it again')
            conn.rollback()
            return 1
        if already:
            deleted, untagged = _remove_reference(cur, args.reference)
            print(f'--replace: {deleted} rows deleted, {untagged} merged rows untagged')

        cur.execute("SELECT lens_id, ra, dec, reference FROM cat.lens WHERE ra IS NOT NULL AND dec IS NOT NULL")
        existing = cur.fetchall()
        new_c = SkyCoord(df[args.ra_col].to_numpy(float) * u.deg, df[args.dec_col].to_numpy(float) * u.deg)
        near = np.zeros(len(df), bool)
        merge = {}
        if existing:
            old_c = SkyCoord([r[1] for r in existing] * u.deg, [r[2] for r in existing] * u.deg)
            idx, sep, _ = new_c.match_to_catalog_sky(old_c)
            near = sep.arcsec <= DUPLICATE_ARCSEC
            for i in np.flatnonzero(near):
                lid, _, _, ref = existing[idx[i]]
                merge[lid] = ref
        for lid, ref in merge.items():
            cur.execute("UPDATE cat.lens SET reference = %s WHERE lens_id = %s",
                        (f'{ref or ""} {args.reference}'.strip(), lid))

        # A copied table (scripts/local_db.sh refresh) can carry rows past its id sequence: never hand out a used id.
        cur.execute("SELECT pg_get_serial_sequence('cat.lens', 'lens_id'), (SELECT max(lens_id) FROM cat.lens)")
        seq, max_id = cur.fetchone()
        if seq and max_id:
            cur.execute(f'SELECT last_value FROM {seq}')
            if cur.fetchone()[0] < max_id:
                cur.execute('SELECT setval(%s, %s)', (seq, max_id))
                print(f'{seq} moved up to {max_id}')

        col = lambda name, row: row[name] if name and name in row else None  # noqa: E731
        rows = []
        for (_, row), ra, dec in zip(df[~near].iterrows(), df[args.ra_col][~near], df[args.dec_col][~near]):
            grade = col(args.grade_col, row)
            grade = None if grade is None or (isinstance(grade, float) and math.isnan(grade)) else str(grade).strip()
            rows.append((float(ra), float(dec), _num(col(args.z_col, row)), _num(col(args.prob_col, row)), grade or None,
                         args.known, args.reference, int(healpix_index(float(ra), float(dec)))))
        execute_values(cur, "INSERT INTO cat.lens (ra, dec, z_lens, lens_probability, lens_grade, known, reference, "
                            "healpix_8192) VALUES %s", rows, page_size=1000)
        print(f'{len(rows)} inserted, {int(near.sum())} rows within {DUPLICATE_ARCSEC:g}" of '
              f'{len(merge)} existing entries merged into them')
        if args.dry_run:
            conn.rollback()
            print('dry run: rolled back')
        else:
            conn.commit()
            print('committed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
