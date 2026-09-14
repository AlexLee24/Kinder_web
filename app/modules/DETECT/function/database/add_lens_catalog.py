"""Add a Vizier lens-candidate table to cat.lens.

    python -m function.database.add_lens_catalog J/A+A/644/A163 HOLISMOKES2 [--grade-col Grade] [--prob-col pCNN] [--z-col z] [--dry-run]

Rows within 2" of an existing cat.lens entry get the new reference appended to
theirs (the table's convention for lenses in several catalogues); the rest are
inserted with the HEALPix index. The first run of this script added HOLISMOKES II
(Canameras et al. 2020, 358 Pan-STARRS candidates), whose PS1J0716+3821 is the
lens of SN 2025wny; its positions are given to 1 s / 1", so the lens can sit
several arcseconds from the true centre.
"""
from __future__ import annotations

import argparse

import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.vizier import Vizier
import astropy.units as u

from function.database import get_db_connection
from function.database.healpix_index import healpix_index, cone_pixels
from function.Legacy_survey_galaxy_model import _approx_sep_arcsec

DUPLICATE_ARCSEC = 2.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vizier", help="Vizier catalogue id, e.g. J/A+A/644/A163")
    ap.add_argument("reference", help="tag for cat.lens.reference, e.g. HOLISMOKES2")
    ap.add_argument("--table", type=int, default=0)
    ap.add_argument("--grade-col", default="Grade")
    ap.add_argument("--prob-col", default="pCNN")
    ap.add_argument("--z-col", default="z")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    t = Vizier(row_limit=-1).get_catalogs(args.vizier)[args.table]
    ra_col = next(c for c in t.colnames if c.upper().startswith("RA"))
    de_col = next(c for c in t.colnames if c.upper().startswith("DE"))
    sexagesimal = t[ra_col].dtype.kind in "SU"
    c = SkyCoord(t[ra_col], t[de_col], unit=(u.hourangle, u.deg) if sexagesimal else (u.deg, u.deg))
    print(f"{args.vizier}: {len(t)} rows, columns {t.colnames}")

    conn = get_db_connection()
    cur = conn.cursor()
    n_new = n_merged = 0
    for row, ra, dec in zip(t, c.ra.deg, c.dec.deg):
        cur.execute("SELECT lens_id, ra, dec, reference FROM cat.lens WHERE healpix_8192 = ANY(%s)", (cone_pixels(ra, dec, DUPLICATE_ARCSEC),))
        near = [r for r in cur.fetchall() if _approx_sep_arcsec(r[1], r[2], ra, dec) <= DUPLICATE_ARCSEC]
        grade = row[args.grade_col] if args.grade_col in t.colnames else None
        prob = row[args.prob_col] if args.prob_col in t.colnames else None
        z = row[args.z_col] if args.z_col in t.colnames else None
        def f(v):
            if v is None or np.ma.is_masked(v):
                return None
            try:
                x = float(v)
            except (TypeError, ValueError):
                return None
            return None if np.isnan(x) else x
        if near:
            lid, _, _, ref = near[0]
            if args.reference not in (ref or "").split():
                cur.execute("UPDATE cat.lens SET reference = %s WHERE lens_id = %s", (f"{ref} {args.reference}".strip(), lid))
                n_merged += 1
            continue
        cur.execute(
            "INSERT INTO cat.lens (ra, dec, z_lens, lens_probability, lens_grade, known, reference, healpix_8192) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (float(ra), float(dec), f(z), f(prob), None if f(grade) is None else f"{f(grade):g}",
             "candidate", args.reference, int(healpix_index(ra, dec))))
        n_new += 1
    print(f"{n_new} inserted, {n_merged} merged into existing entries")
    if args.dry_run:
        conn.rollback(); print("dry run: rolled back")
    else:
        conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
