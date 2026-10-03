"""cat schema — catalog tables: cat.desi, cat.lens."""

import logging
import math

from psycopg2 import extras
from . import get_db_connection

logger = logging.getLogger(__name__)


def _ra_box_clause(ra: float, dec: float, radius_deg: float) -> tuple[str, list]:
    """RA part of a bounding-box pre-filter, handling the 0/360 wrap.

    Returns (sql, params). Near the poles (or for a box wider than the sky) the
    RA constraint is dropped entirely.
    """
    dec_rad = math.radians(min(abs(dec) + radius_deg, 90.0))
    cos_dec = math.cos(dec_rad)
    if cos_dec < 1e-3:
        return "TRUE", []
    ra_margin = radius_deg / cos_dec
    if ra_margin >= 180.0:
        return "TRUE", []
    ra = ra % 360.0
    lo, hi = ra - ra_margin, ra + ra_margin
    if lo < 0.0:
        return "(ra >= %s OR ra <= %s)", [lo + 360.0, hi]
    if hi > 360.0:
        return "(ra >= %s OR ra <= %s)", [lo, hi - 360.0]
    return "ra BETWEEN %s AND %s", [lo, hi]


# ---------------------------------------------------------------------------
# cat.desi — DESI spectroscopic redshift catalog
# ---------------------------------------------------------------------------

def cone_search_desi(ra: float, dec: float, radius_arcsec: float = 5.0,
                     z_min: float | None = None,
                     z_max: float | None = None) -> list[dict]:
    """Return DESI sources within radius_arcsec of (ra, dec)."""
    radius_deg = radius_arcsec / 3600.0
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
        ra_sql, ra_params = _ra_box_clause(ra, dec, radius_deg)
        where_parts = [ra_sql, "dec BETWEEN %s AND %s"]
        q_params = ra_params + [dec - radius_deg, dec + radius_deg]

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
        ra_sql, ra_params = _ra_box_clause(ra, dec, radius_deg)
        where = f"{ra_sql} AND dec BETWEEN %s AND %s"
        q_params = ra_params + [dec - radius_deg, dec + radius_deg]

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


# ---------------------------------------------------------------------------
# cat.ned — NED cone-search result cache
# ---------------------------------------------------------------------------

def get_ned_cache(object_name: str, radius_arcsec: float) -> dict | None:
    """Return cached NED cone-search result or None if not cached."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT result_count, results, searched_at "
                "FROM cat.ned WHERE object_name = %s AND radius_arcsec = %s",
                (object_name, float(radius_arcsec))
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            'result_count': row['result_count'],
            'results': row['results'],          # already a Python list (psycopg2 JSONB)
            'searched_at': row['searched_at'].isoformat() if row['searched_at'] else None,
            'from_cache': True,
        }
    except Exception as e:
        logger.error("get_ned_cache(%s, %.1f): %s", object_name, radius_arcsec, e)
        return None


def upsert_ned_cache(object_name: str, ra_center: float, dec_center: float,
                     radius_arcsec: float, results: list) -> None:
    """Insert or update the NED cone-search cache for an object+radius pair."""
    import json as _json
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO cat.ned (object_name, ra_center, dec_center, radius_arcsec,
                                     searched_at, result_count, results)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (object_name, radius_arcsec) DO UPDATE
                    SET ra_center     = EXCLUDED.ra_center,
                        dec_center    = EXCLUDED.dec_center,
                        searched_at   = NOW(),
                        result_count  = EXCLUDED.result_count,
                        results       = EXCLUDED.results
            """, (object_name, float(ra_center), float(dec_center),
                  float(radius_arcsec), len(results),
                  _json.dumps(results)))
            conn.commit()
    except Exception as e:
        logger.error("upsert_ned_cache(%s, %.1f): %s", object_name, radius_arcsec, e)
