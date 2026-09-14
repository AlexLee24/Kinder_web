import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)


class DataFetcher:
    @staticmethod
    def get_cross_match_results(limit: int = 1000, date: str | None = None) -> list:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=extras.RealDictCursor)
                query = (
                    "SELECT match_id AS id, name AS target_name, catalog AS catalog_name, "
                    "separation AS separation_arcsec, is_host, updated_date AS created_at, "
                    "status, flag, redshift AS z, note, run_date, error_message "
                    "FROM transient.cross_matches"
                )
                params = []
                if date:
                    query += " WHERE updated_date::date = %s"
                    params.append(date)
                query += " ORDER BY updated_date DESC"
                if limit and not date:
                    query += " LIMIT %s"
                    params.append(limit)
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            logger.error("get_cross_match_results: %s", e)
            return []

    @staticmethod
    def get_flagged_objects() -> list[list]:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT DISTINCT o.name_prefix, o.name, o.ra, o.dec, "
                    "CASE WHEN o.discovery_date IS NOT NULL THEN "
                    "to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', "
                    "'YYYY-MM-DD HH24:MI:SS') END, "
                    "COALESCE(o.internal_name,'') "
                    "FROM transient.objects o "
                    "JOIN transient.cross_matches c ON c.obj_id = o.obj_id "
                    "WHERE c.flag = TRUE"
                )
                return [list(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_flagged_objects: %s", e)
            return []

    @staticmethod
    def get_target_image(target_name: str) -> bytes | None:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ti.image_data FROM transient.target_images ti "
                    "JOIN transient.objects o ON ti.obj_id = o.obj_id "
                    "WHERE o.name = %s LIMIT 1",
                    (target_name,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error("get_target_image %s: %s", target_name, e)
            return None

    @staticmethod
    def get_photometry(object_name: str) -> list[dict]:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute(
                    "SELECT obj_id FROM transient.objects WHERE name = %s OR name ILIKE %s LIMIT 1",
                    (object_name, object_name),
                )
                obj = cur.fetchone()
                if not obj:
                    return []
                cur.execute(
                    'SELECT phot_id AS id, name AS object_name, "MJD" AS mjd, '
                    'mag AS magnitude, mag_err AS magnitude_error, filter, source AS telescope '
                    'FROM transient.photometry WHERE obj_id = %s ORDER BY "MJD" ASC',
                    (obj[0],),
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_photometry: %s", e)
            return []

    @staticmethod
    def get_followup_targets() -> list[dict]:
        """Fetch transient objects with Follow-up status, including redshift from cross_matches."""
        try:
            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=extras.RealDictCursor)
                cur.execute(
                    "SELECT o.obj_id, o.name_prefix, o.name, o.ra, o.dec, "
                    "o.discovery_date, o.status, o.internal_name, o.last_modified_date, "
                    "MAX(c.redshift) AS redshift "
                    "FROM transient.objects o "
                    "LEFT JOIN transient.cross_matches c ON o.obj_id = c.obj_id "
                    "WHERE o.status = %s "
                    "GROUP BY o.obj_id, o.name_prefix, o.name, o.ra, o.dec, "
                    "o.discovery_date, o.status, o.internal_name, o.last_modified_date "
                    "ORDER BY o.last_modified_date DESC",
                    ("Follow-up",),
                )
                return cur.fetchall()
        except Exception as e:
            logger.error("get_followup_targets: %s", e)
            return []
