"""cat schema — catalog tables: cat.desi, cat.lens."""

import logging
from psycopg2 import extras
from . import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# cat.desi — DESI spectroscopic redshift catalog
# ---------------------------------------------------------------------------

def cone_search_desi(ra: float, dec: float, radius_arcsec: float = 5.0,
                     z_min: float | None = None,
                     z_max: float | None = None) -> list[dict]:
    """Return DESI sources within radius_arcsec of (ra, dec)."""
    radius_deg = radius_arcsec / 3600.0
    params = [ra, dec, ra, radius_deg]
    clauses = [
        "q3c_radial_query(ra, dec, %s, %s, %s)",
        "ABS(ra - %s) < %s",
    ]
    # Use Cartesian pre-filter for speed when q3c is available
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_extension WHERE extname='q3c' LIMIT 1")
            has_q3c = cur.fetchone() is not None
    except Exception:
        has_q3c = False

    if has_q3c:
        where_parts = ["q3c_radial_query(ra, dec, %s, %s, %s)"]
        q_params = [ra, dec, radius_deg]
    else:
        # Fall back to bounding-box filter with latitude correction
        dec_rad = abs(dec) * 3.141592653589793 / 180.0
        import math
        ra_margin = radius_deg / max(math.cos(dec_rad), 0.001)
        where_parts = [
            "ra BETWEEN %s AND %s",
            "dec BETWEEN %s AND %s",
        ]
        q_params = [ra - ra_margin, ra + ra_margin,
                    dec - radius_deg, dec + radius_deg]

    if z_min is not None:
        where_parts.append("redshift >= %s"); q_params.append(z_min)
    if z_max is not None:
        where_parts.append("redshift <= %s"); q_params.append(z_max)

    where = " AND ".join(where_parts)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                f"SELECT desi_target_id, ra, dec, redshift, redshift_err, "
                f"delta_chi_2, zwarn "
                f"FROM cat.desi WHERE {where} LIMIT 50",
                q_params
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("cone_search_desi (%.4f, %.4f): %s", ra, dec, e)
        return []


def search_desi_by_targetid(target_id: int) -> dict | None:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT desi_target_id, ra, dec, redshift, redshift_err, "
                "delta_chi_2, zwarn FROM cat.desi WHERE desi_target_id = %s",
                (target_id,)
            )
            row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("search_desi_by_targetid: %s", e)
        return None


def get_desi_statistics() -> dict:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cat.desi")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM cat.desi WHERE redshift IS NOT NULL")
            with_z = cur.fetchone()[0]
        return {'total': total, 'with_redshift': with_z}
    except Exception as e:
        logger.error("get_desi_statistics: %s", e)
        return {'total': 0, 'with_redshift': 0}


# ---------------------------------------------------------------------------
# cat.lens — gravitational lens catalog
# ---------------------------------------------------------------------------

def cone_search_lens(ra: float, dec: float,
                     radius_arcsec: float = 30.0) -> list[dict]:
    radius_deg = radius_arcsec / 3600.0
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_extension WHERE extname='q3c' LIMIT 1")
            has_q3c = cur.fetchone() is not None
    except Exception:
        has_q3c = False

    if has_q3c:
        where = "q3c_radial_query(ra, dec, %s, %s, %s)"
        q_params = [ra, dec, radius_deg]
    else:
        import math
        dec_rad = abs(dec) * math.pi / 180.0
        ra_margin = radius_deg / max(math.cos(dec_rad), 0.001)
        where = "ra BETWEEN %s AND %s AND dec BETWEEN %s AND %s"
        q_params = [ra - ra_margin, ra + ra_margin,
                    dec - radius_deg, dec + radius_deg]

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                f"SELECT lens_id, ra, dec, z_lens, z_source, "
                f"lens_probability, lens_grade, known, reference "
                f"FROM cat.lens WHERE {where} LIMIT 20",
                q_params
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("cone_search_lens (%.4f, %.4f): %s", ra, dec, e)
        return []


def get_lens_by_id(lens_id: int) -> dict | None:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT lens_id, ra, dec, z_lens, z_source, "
                "lens_probability, lens_grade, known, reference "
                "FROM cat.lens WHERE lens_id = %s",
                (lens_id,)
            )
            row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("get_lens_by_id: %s", e)
        return None


def get_lens_statistics() -> dict:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), known FROM cat.lens GROUP BY known")
            rows = cur.fetchall()
        stats = {'total': 0}
        for count, category in rows:
            stats['total'] += count
            stats[category or 'unknown'] = count
        return stats
    except Exception as e:
        logger.error("get_lens_statistics: %s", e)
        return {'total': 0}
