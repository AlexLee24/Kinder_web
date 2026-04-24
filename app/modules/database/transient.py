"""transient schema — objects, photometry, spectroscopy, cross_matches,
target_images, download_logs, object_views, comments, pin/flag operations.

All SQL targets the 'Kinder' database transient schema.
Return values use backward-compatible column aliases matching legacy tns_objects.
"""

import json
import logging
import re as _re
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2
from psycopg2 import extras

from . import get_db_connection, OBJECT_COMPAT_COLS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_obj_id(cur, name: str) -> int | None:
    """Return obj_id for a given object name (bare name without prefix)."""
    cur.execute(
        "SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1",
        (name,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def _resolve_obj_id_with_prefix(cur, name: str) -> int | None:
    """Try bare name first, then strip common prefixes."""
    cur.execute(
        "SELECT obj_id FROM transient.objects WHERE name = %s OR name ILIKE %s LIMIT 1",
        (name, name)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    # Strip prefix (AT/SN/FRB/TDE …)
    m = _re.match(r'^(?:AT|SN|FRB|TDE|EP)(.+)$', name)
    if m:
        bare = m.group(1)
        cur.execute(
            "SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1",
            (bare,)
        )
        row = cur.fetchone()
        return row[0] if row else None
    return None


def _mjd_update(cur, obj_id: int, mjd: float):
    """Update last_phot_date if new MJD is later."""
    cur.execute(
        "UPDATE transient.objects SET last_phot_date = %s "
        "WHERE obj_id = %s AND (last_phot_date IS NULL OR last_phot_date < %s)",
        (mjd, obj_id, mjd)
    )


# ---------------------------------------------------------------------------
# Kinder ID helpers  (year * 1_000_000 + letter_rank)
# ---------------------------------------------------------------------------

_KINDER_NAME_RE = _re.compile(r'^(\d{4})([a-z]+)$')


def _tns_name_to_kinder_id(name: str) -> int | None:
    """Convert TNS name → internal kinder_id.

    Examples:
      '2024ggi' → 2024_004923   (rank of 'ggi': 7*676+7*26+9 = 4923)
      '2026zzzz' → 2026_475254  (rank of 'zzzz': 26+676+17576+456976)
    Formula: year * 1_000_000 + sum((ord(c)-96) * 26^i
                                    for i,c in enumerate(reversed(suffix)))
    """
    m = _KINDER_NAME_RE.match(name)
    if not m:
        return None
    year   = int(m.group(1))
    suffix = m.group(2)
    rank   = sum((ord(c) - 96) * (26 ** i) for i, c in enumerate(reversed(suffix)))
    return year * 1_000_000 + rank


def sync_kinder_ids() -> int:
    """Compute and write kinder_id for all rows where it is NULL.
    Handles both lowercase multi-letter ('2026aa') and uppercase single-letter ('2026A') names.
    Returns the number of rows updated.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT obj_id, name FROM transient.objects "
                "WHERE kinder_id IS NULL AND name ~ '^[0-9]{4}[a-zA-Z]+$'"
            )
            updates = []
            for obj_id, name in cur.fetchall():
                # _tns_name_to_kinder_id uses lowercase-only regex; handle uppercase here
                kid = _tns_name_to_kinder_id(name) or _tns_name_to_kinder_id(name.lower())
                if kid is not None:
                    updates.append((kid, obj_id))
            if updates:
                extras.execute_batch(
                    cur,
                    "UPDATE transient.objects SET kinder_id = %s WHERE obj_id = %s",
                    updates,
                    page_size=1000,
                )
                conn.commit()
            return len(updates)
    except Exception as e:
        logger.error("sync_kinder_ids: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Download logs
# ---------------------------------------------------------------------------

def log_download_attempt(hour_utc: str = '', filename: str = '') -> int | None:
    """Insert a new download log entry; return log_id."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO transient.download_logs (download_date, obj_import, obj_update, status, filename) "
                "VALUES (now(), 0, 0, 'In Progress', %s) RETURNING log_id",
                (filename,)
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
    except Exception as e:
        logger.error("log_download_attempt: %s", e)
        return None


def update_download_log(log_id: int, status: str,
                        records_imported: int = 0,
                        records_updated: int = 0,
                        error_message: str | None = None):
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.download_logs "
                "SET status=%s, obj_import=%s, obj_update=%s, error_message=%s "
                "WHERE log_id=%s",
                (status, records_imported, records_updated, error_message, log_id)
            )
            conn.commit()
    except Exception as e:
        logger.error("update_download_log: %s", e)


# ---------------------------------------------------------------------------
# TNSObjectDB — photometry, spectroscopy, comments, object views
# ---------------------------------------------------------------------------

class TNSObjectDB:

    @staticmethod
    def add_photometry_point(object_name: str, mjd: float,
                             magnitude=None, magnitude_error=None,
                             filter_name=None, telescope=None) -> int | None:
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                logger.debug("add_photometry_point: no obj_id for %s", object_name)
                cur.close()
                return None
            cur.execute(
                "INSERT INTO transient.photometry "
                "(obj_id, name, \"MJD\", mag, mag_err, filter, source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING "
                "RETURNING phot_id",
                (obj_id, object_name, mjd, magnitude, magnitude_error,
                 filter_name, telescope)
            )
            row = cur.fetchone()
            phot_id = row[0] if row else None
            if phot_id:
                _mjd_update(cur, obj_id, mjd)
            conn.commit()
        return phot_id

    @staticmethod
    def add_photometry_batch(object_name: str, points: list) -> int:
        if not points:
            return 0
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return 0
            inserted = 0
            max_mjd = None
            for p in points:
                cur.execute(
                    "INSERT INTO transient.photometry "
                    "(obj_id, name, \"MJD\", mag, mag_err, filter, source) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING "
                    "RETURNING phot_id",
                    (obj_id, object_name, p['mjd'],
                     p.get('magnitude'), p.get('magnitude_error'),
                     p.get('filter'),
                     p.get('telescope', p.get('source', 'Unknown')))
                )
                if cur.fetchone():
                    inserted += 1
                    if max_mjd is None or p['mjd'] > max_mjd:
                        max_mjd = p['mjd']
            if max_mjd is not None:
                _mjd_update(cur, obj_id, max_mjd)
            conn.commit()
        return inserted

    @staticmethod
    def add_photometry_bulk(photometry_data):
        """Bulk insert: list of (object_name, mjd, magnitude, mag_err, filter, telescope)."""
        if not photometry_data:
            return
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Resolve names to obj_ids in bulk
            names = list({row[0] for row in photometry_data})
            cur.execute(
                "SELECT name, obj_id FROM transient.objects WHERE name = ANY(%s)",
                (names,)
            )
            name_map = {r[0]: r[1] for r in cur.fetchall()}
            rows = []
            for row in photometry_data:
                oid = name_map.get(row[0])
                if oid:
                    rows.append((oid, row[0], row[1], row[2], row[3], row[4], row[5]))
            if rows:
                extras.execute_batch(
                    cur,
                    "INSERT INTO transient.photometry "
                    "(obj_id, name, \"MJD\", mag, mag_err, filter, source) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING",
                    rows,
                    page_size=1000
                )
            conn.commit()

    @staticmethod
    def sync_last_photometry_date(object_name: str):
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return
            cur.execute(
                "SELECT MAX(\"MJD\") FROM transient.photometry WHERE obj_id = %s",
                (obj_id,)
            )
            max_mjd = cur.fetchone()[0]
            cur.execute(
                "UPDATE transient.objects SET last_phot_date = %s WHERE obj_id = %s",
                (max_mjd, obj_id)
            )
            conn.commit()

    @staticmethod
    def get_photometry(object_name: str) -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return []
            cur.execute(
                'SELECT phot_id AS id, name AS object_name, "MJD" AS mjd, '
                'mag AS magnitude, mag_err AS magnitude_error, filter, source AS telescope '
                'FROM transient.photometry WHERE obj_id = %s ORDER BY "MJD" ASC',
                (obj_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def delete_photometry_point(point_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM transient.photometry WHERE phot_id = %s", (point_id,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    @staticmethod
    def add_spectrum_data(object_name: str, wavelength_data, intensity_data,
                          phase=None, telescope=None, spectrum_id=None):
        """spectrum_id serves as source label; phase is stored as part of source tag."""
        if spectrum_id is None:
            spectrum_id = f"{object_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        source_tag = spectrum_id
        mjd = 0.0  # unknown; use placeholder
        rows = [
            (None, object_name, mjd, wl, inten, source_tag)
            for wl, inten in zip(wavelength_data, intensity_data)
        ]
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return spectrum_id
            entries = [(obj_id, object_name, mjd, wl, inten, source_tag) for _, name, mjd, wl, inten, src in rows]
            extras.execute_batch(
                cur,
                "INSERT INTO transient.spectroscopy "
                "(obj_id, name, \"MJD\", wavelength, intensity, source) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                entries,
                page_size=1000
            )
            conn.commit()
        return spectrum_id

    @staticmethod
    def get_spectroscopy(object_name: str) -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return []
            cur.execute(
                'SELECT spec_id AS id, name AS object_name, "MJD", '
                'wavelength, intensity, source AS telescope, '
                'source AS spectrum_id '
                'FROM transient.spectroscopy '
                'WHERE obj_id = %s ORDER BY source, wavelength',
                (obj_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def get_spectrum_list(object_name: str) -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return []
            cur.execute(
                'SELECT source AS spectrum_id, source AS telescope, '
                '"MJD" AS phase, '
                'MIN(wavelength) AS min_wavelength, MAX(wavelength) AS max_wavelength, '
                'COUNT(*) AS point_count, MIN(spec_id) AS observation_date '
                'FROM transient.spectroscopy '
                'WHERE obj_id = %s '
                'GROUP BY source, "MJD" ORDER BY observation_date DESC',
                (obj_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def delete_spectrum(spectrum_id: str) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM transient.spectroscopy WHERE source = %s",
                (spectrum_id,)
            )
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    @staticmethod
    def get_object_details(object_name: str) -> dict | None:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute(
                "SELECT name, ra, dec AS declination, "
                "CASE WHEN discovery_date IS NOT NULL THEN "
                "     to_char(TIMESTAMP '1858-11-17' + discovery_date * INTERVAL '1 day', "
                "             'YYYY-MM-DD HH24:MI:SS') END AS discoverydate, "
                "COALESCE(internal_name,'') || "
                "  CASE WHEN other_name IS NOT NULL THEN ', '||other_name ELSE '' END AS internal_names, "
                "type, redshift, discovery_mag AS discoverymag, discovery_filter AS filter "
                "FROM transient.objects WHERE name = %s",
                (object_name,)
            )
            row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def add_comment(object_name: str, user_email: str, user_name: str,
                    user_picture: str, content: str) -> int | None:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Look up usr_id from email
            cur.execute("SELECT usr_id FROM auth.users WHERE email = %s", (user_email,))
            row = cur.fetchone()
            usr_id = row[0] if row else None
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return None
            cur.execute(
                "INSERT INTO transient.comments (obj_id, name, usr_id, comment) "
                "VALUES (%s,%s,%s,%s) RETURNING comment_id",
                (obj_id, object_name, usr_id, content)
            )
            cid = cur.fetchone()[0]
            conn.commit()
        return cid

    @staticmethod
    def get_comments(object_name: str) -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute(
                "SELECT c.comment_id AS id, c.name AS object_name, "
                "u.email AS user_email, u.name AS user_name, "
                "u.picture_url AS user_picture, "
                "c.comment AS content, c.comment_time AS created_at "
                "FROM transient.comments c "
                "LEFT JOIN auth.users u ON c.usr_id = u.usr_id "
                "WHERE c.name = %s ORDER BY c.comment_time ASC",
                (object_name,)
            )
            out = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get('created_at'):
                    d['created_at'] = d['created_at'].isoformat()
                out.append(d)
        return out

    @staticmethod
    def get_recent_comments(limit: int = 5) -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute(
                "SELECT c.comment_id AS id, c.name AS object_name, "
                "u.email AS user_email, u.name AS user_name, "
                "u.picture_url AS user_picture, c.comment AS content, "
                "c.comment_time AS created_at, "
                "o.name_prefix, o.type, "
                "COALESCE(o.internal_name,'') AS internal_names, "
                "array_to_string(o.tag,', ') AS tags "
                "FROM transient.comments c "
                "LEFT JOIN auth.users u ON c.usr_id = u.usr_id "
                "LEFT JOIN transient.objects o ON c.obj_id = o.obj_id "
                "ORDER BY c.comment_time DESC LIMIT %s",
                (limit,)
            )
            out = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get('created_at'):
                    d['created_at'] = d['created_at'].isoformat()
                out.append(d)
        return out

    @staticmethod
    def get_comment_by_id(comment_id: int) -> dict | None:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute(
                "SELECT c.comment_id AS id, c.name AS object_name, "
                "u.email AS user_email, u.name AS user_name, "
                "u.picture_url AS user_picture, "
                "c.comment AS content, c.comment_time AS created_at "
                "FROM transient.comments c "
                "LEFT JOIN auth.users u ON c.usr_id = u.usr_id "
                "WHERE c.comment_id = %s",
                (comment_id,)
            )
            row = cur.fetchone()
        if row:
            d = dict(row)
            if d.get('created_at'):
                d['created_at'] = d['created_at'].isoformat()
            return d
        return None

    @staticmethod
    def delete_comment(comment_id: int) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM transient.comments WHERE comment_id = %s", (comment_id,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    @staticmethod
    def update_comment(comment_id: int, content: str) -> bool:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.comments SET comment = %s WHERE comment_id = %s",
                (content, comment_id)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated

    @staticmethod
    def log_object_view(object_name: str, user_email: str | None = None):
        m = _re.match(r'^(?:AT|SN)(\d.+)$', object_name)
        canonical = m.group(1) if m else object_name
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                obj_id = _resolve_obj_id(cur, canonical)
                if obj_id is None:
                    return
                # usr_id lookup
                usr_id = None
                if user_email:
                    cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (user_email,))
                    r = cur.fetchone()
                    usr_id = r[0] if r else None
                # Detail row
                cur.execute(
                    "INSERT INTO transient.object_views_detail (obj_id, name, usr_id) "
                    "VALUES (%s,%s,%s)",
                    (obj_id, canonical, usr_id)
                )
                # Aggregated counter
                cur.execute(
                    "INSERT INTO transient.object_views (obj_id, name, counts, last_view) "
                    "VALUES (%s,%s,1,now()) "
                    "ON CONFLICT (obj_id) DO UPDATE "
                    "SET counts = transient.object_views.counts + 1, last_view = now()",
                    (obj_id, canonical)
                )
                conn.commit()
        except Exception as e:
            logger.error("log_object_view %s: %s", canonical, e)

    @staticmethod
    def get_top_viewed_objects(days: int = 30, limit: int = 5,
                               mode: str = '30days') -> list[dict]:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            if mode == 'all':
                cur.execute(
                    "SELECT v.name AS object_name, v.counts AS view_count, "
                    "COALESCE(o.type,'Unknown') AS object_type, "
                    "o.name_prefix, COALESCE(o.internal_name,'') AS internal_names, "
                    "array_to_string(o.tag,', ') AS tags "
                    "FROM transient.object_views v "
                    "LEFT JOIN transient.objects o ON v.obj_id = o.obj_id "
                    "ORDER BY v.counts DESC LIMIT %s",
                    (limit,)
                )
            else:
                cur.execute(
                    "WITH recent AS ("
                    "  SELECT obj_id, COUNT(*) AS view_count "
                    "  FROM transient.object_views_detail "
                    "  WHERE view_time >= now() - (%s || ' days')::interval "
                    "  GROUP BY obj_id ORDER BY view_count DESC LIMIT %s"
                    ") "
                    "SELECT r.view_count, d.name AS object_name, "
                    "COALESCE(o.type,'Unknown') AS object_type, "
                    "o.name_prefix, COALESCE(o.internal_name,'') AS internal_names, "
                    "array_to_string(o.tag,', ') AS tags "
                    "FROM recent r "
                    "JOIN transient.object_views d ON r.obj_id = d.obj_id "
                    "LEFT JOIN transient.objects o ON r.obj_id = o.obj_id "
                    "ORDER BY r.view_count DESC",
                    (days, limit)
                )
            return [dict(r) for r in cur.fetchall()]


# Singleton used by routes
tns_object_db = TNSObjectDB()


# ---------------------------------------------------------------------------
# Object query functions (Marshal / API)
# ---------------------------------------------------------------------------

def _build_where(params, search_term='', object_type='', tag=None,
                 date_from=None, date_to=None,
                 app_mag_min=None, app_mag_max=None,
                 redshift_min=None, redshift_max=None, discoverer=None,
                 brightest_mag_min=None, brightest_mag_max=None,
                 brightest_abs_mag_min=None, brightest_abs_mag_max=None):
    """Build WHERE clause and params list for transient.objects queries."""
    clauses = ['1=1']

    if search_term:
        pat = f'%{search_term}%'
        clauses.append(
            "(o.name ILIKE %s OR o.name_prefix || o.name ILIKE %s "
            " OR o.internal_name ILIKE %s OR o.other_name ILIKE %s)"
        )
        params.extend([pat, pat, pat, pat])

    if object_type:
        types = [t.strip() for t in object_type.split(',') if t.strip()]
        if types:
            conds = []
            for t in types:
                if t == 'AT':
                    conds.append("o.name_prefix = 'AT'")
                elif t == 'Classified':
                    conds.append("o.name_prefix != 'AT'")
                else:
                    conds.append("o.type = %s")
                    params.append(t)
            if conds:
                clauses.append(f"({' OR '.join(conds)})")

    # Status / tag filter
    if tag:
        status_map = {
            'object':   "o.status = 'Inbox'",
            'followup': "o.status = 'Follow-up'",
            'finished': "o.status = 'Finish'",
            'snoozed':  "o.status = 'Snoozed'",
        }
        if tag in status_map:
            clauses.append(status_map[tag])
        elif tag == 'flag':
            clauses.append(
                "EXISTS (SELECT 1 FROM transient.cross_matches c "
                "WHERE c.obj_id = o.obj_id AND c.status = 'Flagged')"
            )

    # Date filter on discovery_date (MJD) — accept both ISO strings and MJD floats
    if date_from:
        clauses.append(
            "o.discovery_date >= (DATE %s - DATE '1858-11-17')"
        )
        params.append(date_from)
    if date_to:
        clauses.append(
            "o.discovery_date <= (DATE %s - DATE '1858-11-17') + 1"
        )
        params.append(date_to)

    if app_mag_min is not None:
        clauses.append("o.discovery_mag >= %s"); params.append(app_mag_min)
    if app_mag_max is not None:
        clauses.append("o.discovery_mag <= %s"); params.append(app_mag_max)
    if redshift_min is not None:
        clauses.append("o.redshift >= %s"); params.append(redshift_min)
    if redshift_max is not None:
        clauses.append("o.redshift <= %s"); params.append(redshift_max)
    if discoverer:
        dpat = f'%{discoverer}%'
        clauses.append(
            "(o.source_group ILIKE %s OR o.report_group ILIKE %s "
            "OR array_to_string(o.reporters,',') ILIKE %s)"
        )
        params.extend([dpat, dpat, dpat])
    if brightest_mag_min is not None:
        clauses.append("o.brightest_mag >= %s"); params.append(brightest_mag_min)
    if brightest_mag_max is not None:
        clauses.append("o.brightest_mag <= %s"); params.append(brightest_mag_max)
    if brightest_abs_mag_min is not None:
        clauses.append("o.brightest_abs_mag >= %s"); params.append(brightest_abs_mag_min)
    if brightest_abs_mag_max is not None:
        clauses.append("o.brightest_abs_mag <= %s"); params.append(brightest_abs_mag_max)

    return ' AND '.join(clauses)


def get_objects_count(object_type=None, search_term='', tag=None,
                      date_from=None, date_to=None,
                      app_mag_min=None, app_mag_max=None,
                      redshift_min=None, redshift_max=None,
                      discoverer=None,
                      brightest_mag_min=None, brightest_mag_max=None,
                      brightest_abs_mag_min=None, brightest_abs_mag_max=None) -> int:
    params = []
    where = _build_where(
        params, search_term=search_term, object_type=object_type or '',
        tag=tag, date_from=date_from, date_to=date_to,
        app_mag_min=app_mag_min, app_mag_max=app_mag_max,
        redshift_min=redshift_min, redshift_max=redshift_max,
        discoverer=discoverer,
        brightest_mag_min=brightest_mag_min, brightest_mag_max=brightest_mag_max,
        brightest_abs_mag_min=brightest_abs_mag_min,
        brightest_abs_mag_max=brightest_abs_mag_max,
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM transient.objects o WHERE {where}", params)
        return cur.fetchone()[0]


def get_tag_statistics() -> dict:
    with get_db_connection() as conn:
        cur = conn.cursor()
        stats = {}
        for label, status in [('object', 'Inbox'), ('followup', 'Follow-up'),
                               ('finished', 'Finish'), ('snoozed', 'Snoozed')]:
            cur.execute(
                "SELECT COUNT(*) FROM transient.objects WHERE status = %s", (status,)
            )
            stats[label] = cur.fetchone()[0]
    return stats


def get_tns_statistics() -> dict:
    with get_db_connection() as conn:
        cur = conn.cursor()
        stats = {}
        cur.execute("SELECT COUNT(*) FROM transient.objects")
        stats['total'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT obj_id) FROM transient.photometry")
        stats['with_photometry'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE type IS NOT NULL AND type != ''")
        stats['classified'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE redshift IS NOT NULL")
        stats['with_redshift'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE status = 'Follow-up'")
        stats['follow'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE status = 'Finish'")
        stats['finished'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE status = 'Snoozed'")
        stats['snoozed'] = cur.fetchone()[0]
    return stats


def search_tns_objects(search_term='', object_type='', limit=100, offset=0,
                       sort_by='discoverydate', sort_order='desc',
                       date_from=None, date_to=None,
                       mag_min=None, mag_max=None,
                       app_mag_min=None, app_mag_max=None,
                       redshift_min=None, redshift_max=None,
                       discoverer=None, tag=None,
                       brightest_mag_min=None, brightest_mag_max=None,
                       brightest_abs_mag_min=None,
                       brightest_abs_mag_max=None) -> list[dict]:
    params = []
    where = _build_where(
        params, search_term=search_term, object_type=object_type,
        tag=tag, date_from=date_from, date_to=date_to,
        app_mag_min=app_mag_min if app_mag_min is not None else mag_min,
        app_mag_max=app_mag_max if app_mag_max is not None else mag_max,
        redshift_min=redshift_min, redshift_max=redshift_max,
        discoverer=discoverer,
        brightest_mag_min=brightest_mag_min, brightest_mag_max=brightest_mag_max,
        brightest_abs_mag_min=brightest_abs_mag_min,
        brightest_abs_mag_max=brightest_abs_mag_max,
    )

    # Sort column mapping (old name → new transient.objects column)
    sort_map = {
        'discoverydate':        'o.discovery_date',
        'lastmodified':         'o.last_modified_date',
        'discoverymag':         'o.discovery_mag',
        'name':                 'o.name',
        'time_received':        'o.received_date',
        'last_photometry_date': 'o.last_phot_date',
        'brightest_mag':        'o.brightest_mag',
        'brightest_abs_mag':    'o.brightest_abs_mag',
        'redshift':             'o.redshift',
    }
    sort_col = sort_map.get(sort_by, 'o.discovery_date')
    direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'

    if sort_by == 'last_photometry_date':
        order_clause = (
            f"ORDER BY COALESCE(o.last_phot_date, o.last_modified_date) "
            f"{direction} NULLS LAST"
        )
    else:
        order_clause = f"ORDER BY {sort_col} {direction} NULLS LAST"

    params.extend([limit, offset])
    query = (
        f"SELECT {OBJECT_COMPAT_COLS} "
        f"FROM transient.objects o "
        f"WHERE {where} "
        f"{order_clause} "
        f"LIMIT %s OFFSET %s"
    )
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_filtered_stats(search_term='', object_type='', tag=None,
                       date_from=None, date_to=None,
                       app_mag_min=None, app_mag_max=None,
                       redshift_min=None, redshift_max=None,
                       discoverer=None) -> dict:
    base_params = []
    where = _build_where(
        base_params, search_term=search_term, object_type=object_type,
        tag=tag, date_from=date_from, date_to=date_to,
        app_mag_min=app_mag_min, app_mag_max=app_mag_max,
        redshift_min=redshift_min, redshift_max=redshift_max,
        discoverer=discoverer,
    )
    stats = {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        for label, extra in [
            ('total',    ''),
            ('object',   "AND o.status = 'Inbox'"),
            ('followup', "AND o.status = 'Follow-up'"),
            ('finished', "AND o.status = 'Finish'"),
            ('snoozed',  "AND o.status = 'Snoozed'"),
        ]:
            q = (f"SELECT COUNT(*) FROM transient.objects o "
                 f"WHERE {where} {extra}")
            cur.execute(q, base_params)
            stats[label] = cur.fetchone()[0]
    return stats


def get_distinct_classifications() -> list[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT type FROM transient.objects "
            "WHERE type IS NOT NULL AND type != '' ORDER BY type"
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Status / flags
# ---------------------------------------------------------------------------

# New status values: 'Inbox', 'Snoozed', 'Follow-up', 'Finish'
_STATUS_MAP = {
    'snoozed':  'Snoozed',
    'finished': 'Finish',
    'followup': 'Follow-up',
    'object':   'Inbox',
    'clear':    'Inbox',
    # also accept new-style directly
    'Snoozed':  'Snoozed',
    'Finish':   'Finish',
    'Follow-up': 'Follow-up',
    'Inbox':    'Inbox',
}


def update_object_status(object_name: str, status: str) -> bool:
    new_status = _STATUS_MAP.get(status)
    if new_status is None:
        return False
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.objects SET status = %s "
                "WHERE name = %s OR name ILIKE %s "
                "OR (COALESCE(name_prefix,'') || name) ILIKE %s",
                (new_status, object_name, object_name, object_name)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_object_status: %s", e)
        return False


def update_object_activity(objid, activity_type=None):
    """No-op; kept for backward compat."""
    return True


def get_auto_snooze_stats() -> dict:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE status = 'Snoozed'")
        s = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transient.objects WHERE status = 'Finish'")
        f = cur.fetchone()[0]
    return {'snoozed_count': s, 'finished_count': f}


# ---------------------------------------------------------------------------
# Cross-match functions
# ---------------------------------------------------------------------------

def get_daily_match_counts() -> list[dict]:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute("""
                WITH dates AS (
                    SELECT generate_series(
                        (SELECT MIN(updated_date::date) FROM transient.cross_matches),
                        (SELECT MAX(updated_date::date) FROM transient.cross_matches),
                        '1 day'::interval
                    )::date AS date
                )
                SELECT d.date,
                       COUNT(DISTINCT c.obj_id) AS unique_targets,
                       COALESCE(BOOL_OR(c.catalog LIKE 'Lens_%'), FALSE) AS has_lens
                FROM dates d
                LEFT JOIN transient.cross_matches c ON d.date = c.updated_date::date
                GROUP BY d.date ORDER BY d.date DESC
            """)
            return [
                {'date': r['date'].strftime('%Y-%m-%d'),
                 'count': r['unique_targets'],
                 'has_lens': r['has_lens']}
                for r in cur.fetchall()
            ]
    except Exception as e:
        logger.error("get_daily_match_counts: %s", e)
        return []


def get_available_dates() -> list[str]:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT updated_date::date AS d "
                "FROM transient.cross_matches ORDER BY d DESC"
            )
            return [r[0].strftime('%Y-%m-%d') for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_available_dates: %s", e)
        return []


def get_cross_match_results(limit: int = 1000, date: str | None = None) -> list:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            # Add flag column if needed (backward compat)
            try:
                cur.execute("SELECT flag FROM transient.cross_matches LIMIT 1")
            except psycopg2.Error:
                conn.rollback()
                cur.execute("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE")
                conn.commit()
            # Map new column names back to old names expected by routes
            query = (
                "SELECT match_id AS id, name AS target_name, catalog AS catalog_name, "
                "separation AS separation_arcsec, is_host, updated_date AS created_at, "
                "status, flag, redshift AS z "
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


def update_cross_match_flag(result_id: int, flag_value: bool) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE"
            )
            cur.execute(
                "UPDATE transient.cross_matches SET flag = %s WHERE match_id = %s",
                (flag_value, result_id)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("update_cross_match_flag: %s", e)
        return False


def get_flagged_objects() -> list[list]:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT o.name_prefix, o.name, o.ra, o.dec, "
                "CASE WHEN o.discovery_date IS NOT NULL THEN "
                "     to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', "
                "             'YYYY-MM-DD HH24:MI:SS') END, "
                "COALESCE(o.internal_name,'') "
                "FROM transient.objects o "
                "JOIN transient.cross_matches c ON c.obj_id = o.obj_id "
                "WHERE c.flag = TRUE"
            )
            return [list(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_flagged_objects: %s", e)
        return []


def save_flag_objects(flag_list: list):
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE"
            )
            count = 0
            for item in flag_list:
                if len(item) < 2:
                    continue
                name = item[1]
                cur.execute(
                    "SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1",
                    (name,)
                )
                row = cur.fetchone()
                if not row:
                    continue
                obj_id = row[0]
                cur.execute(
                    "SELECT match_id FROM transient.cross_matches WHERE obj_id = %s LIMIT 1",
                    (obj_id,)
                )
                if cur.fetchone():
                    cur.execute(
                        "UPDATE transient.cross_matches SET flag = TRUE WHERE obj_id = %s",
                        (obj_id,)
                    )
                else:
                    cur.execute(
                        "INSERT INTO transient.cross_matches "
                        "(obj_id, name, catalog, separation, is_host, flag) "
                        "VALUES (%s,%s,'FLAGGED_LIST',0,FALSE,TRUE)",
                        (obj_id, name)
                    )
                count += 1
            conn.commit()
            logger.info("save_flag_objects: processed %d", count)
    except Exception as e:
        logger.error("save_flag_objects: %s", e)


def save_cross_match_results(results_list: list):
    """Save DETECT pipeline cross-match results.

    Each item: {target_name, catalog_name, match_data dict, separation_arcsec,
                is_host bool, flag bool (optional)}
    """
    if not results_list:
        return
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Bulk name→obj_id lookup
            names = list({r['target_name'] for r in results_list})
            cur.execute(
                "SELECT name, obj_id FROM transient.objects WHERE name = ANY(%s)",
                (names,)
            )
            name_map = {r[0]: r[1] for r in cur.fetchall()}

            for r in results_list:
                obj_id = name_map.get(r['target_name'])
                if obj_id is None:
                    continue
                md = r.get('match_data') or {}
                z = md.get('z') if isinstance(md, dict) else None
                cur.execute(
                    "INSERT INTO transient.cross_matches "
                    "(obj_id, name, catalog, separation, redshift, is_host, updated_date) "
                    "VALUES (%s,%s,%s,%s,%s,%s,now())",
                    (obj_id, r['target_name'],
                     r.get('catalog_name', ''),
                     r.get('separation_arcsec'),
                     z,
                     bool(r.get('is_host', False)))
                )
            conn.commit()
    except Exception as e:
        logger.error("save_cross_match_results: %s", e)


def get_object_flag_status(object_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT EXISTS("
                "  SELECT 1 FROM transient.cross_matches c "
                "  JOIN transient.objects o ON c.obj_id = o.obj_id "
                "  WHERE o.name = %s AND c.flag = TRUE"
                ")",
                (object_name,)
            )
            return cur.fetchone()[0]
    except Exception as e:
        logger.error("get_object_flag_status: %s", e)
        return False


def update_object_flag_by_name(object_name: str, flag_value: bool) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.cross_matches SET flag = %s "
                "WHERE obj_id = (SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1)",
                (flag_value, object_name)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("update_object_flag_by_name: %s", e)
        return False


def set_cross_match_host(match_id: int, target_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.cross_matches SET is_host = FALSE "
                "WHERE obj_id = (SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1)",
                (target_name,)
            )
            cur.execute(
                "UPDATE transient.cross_matches SET is_host = TRUE WHERE match_id = %s",
                (match_id,)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("set_cross_match_host: %s", e)
        return False


def unset_cross_match_host(target_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.cross_matches SET is_host = FALSE "
                "WHERE obj_id = (SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1)",
                (target_name,)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("unset_cross_match_host: %s", e)
        return False


# ---------------------------------------------------------------------------
# Target images
# ---------------------------------------------------------------------------

def save_target_image(target_name: str, image_data: bytes) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, target_name)
            if obj_id is None:
                return False
            cur.execute(
                "SELECT image_id FROM transient.target_images WHERE obj_id = %s LIMIT 1",
                (obj_id,)
            )
            if cur.fetchone():
                cur.execute(
                    "UPDATE transient.target_images SET image_data = %s WHERE obj_id = %s",
                    (image_data, obj_id)
                )
            else:
                cur.execute(
                    "INSERT INTO transient.target_images (obj_id, name, image_data, source) "
                    "VALUES (%s,%s,%s,'DESI')",
                    (obj_id, target_name, image_data)
                )
            conn.commit()
        return True
    except Exception as e:
        logger.error("save_target_image %s: %s", target_name, e)
        return False


def get_target_image(target_name: str) -> bytes | None:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT ti.image_data "
                "FROM transient.target_images ti "
                "JOIN transient.objects o ON ti.obj_id = o.obj_id "
                "WHERE o.name = %s LIMIT 1",
                (target_name,)
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error("get_target_image %s: %s", target_name, e)
        return None


# ---------------------------------------------------------------------------
# Redshift + absolute magnitude
# ---------------------------------------------------------------------------

def update_tns_redshift(target_name: str, redshift_str: str) -> bool:
    try:
        # Extract numeric value
        match = _re.search(r'[-+]?\d*\.?\d+', str(redshift_str))
        if not match:
            return False
        z = float(match.group())
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.objects SET redshift = %s "
                "WHERE name = %s OR name ILIKE %s",
                (z, target_name, target_name)
            )
            conn.commit()
        # Trigger abs mag recalc
        try:
            update_object_abs_mag(target_name)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error("update_tns_redshift %s: %s", target_name, e)
        return False


def update_object_abs_mag(target_name: str) -> bool:
    logger.debug("update_object_abs_mag called for %s", target_name)
    try:
        try:
            from .. import ext_M_calculator
        except ImportError:
            import modules.ext_M_calculator as ext_M_calculator
    except ImportError:
        logger.error("Could not import ext_M_calculator")
        return False

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute(
                "SELECT obj_id, name, name_prefix, redshift, ra, dec, discovery_filter "
                "FROM transient.objects "
                "WHERE name = %s OR name ILIKE %s "
                "OR (COALESCE(name_prefix,'') || name) ILIKE %s LIMIT 1",
                (target_name, target_name, target_name)
            )
            obj = cur.fetchone()
            if not obj:
                return False
            obj = dict(obj)
            obj_id = obj['obj_id']

            # Brightest mag from photometry
            cur.execute(
                "SELECT mag AS magnitude, filter, mag_err AS magnitude_error "
                "FROM transient.photometry "
                "WHERE obj_id = %s AND mag IS NOT NULL "
                "AND mag_err IS NOT NULL AND mag_err > 0 AND mag_err <= 0.3",
                (obj_id,)
            )
            rows = cur.fetchall()
            min_mag = float('inf')
            brightest_filter = None
            for row in rows:
                try:
                    val = float(row['magnitude'])
                    if val < min_mag:
                        min_mag = val
                        brightest_filter = row['filter']
                except Exception:
                    continue

            if min_mag == float('inf'):
                return False
            brightest_mag = min_mag

            cur.execute(
                "UPDATE transient.objects SET brightest_mag = %s WHERE obj_id = %s",
                (brightest_mag, obj_id)
            )
            conn.commit()

            z = obj.get('redshift')
            if z is None or float(z) <= 0:
                return False
            z = float(z)

            filter_name = brightest_filter or obj.get('discovery_filter') or 'r'
            try:
                extinction = ext_M_calculator.get_extinction(obj['ra'], obj['dec'], filter_name)
                if not isinstance(extinction, (int, float)):
                    extinction = 0
            except Exception:
                extinction = 0

            abs_mag = ext_M_calculator.apm_to_abm(brightest_mag, z, extinction)
            if isinstance(abs_mag, (int, float)):
                cur.execute(
                    "UPDATE transient.objects SET brightest_abs_mag = %s WHERE obj_id = %s",
                    (abs_mag, obj_id)
                )
                conn.commit()
                return True
    except Exception as e:
        logger.error("update_object_abs_mag %s: %s", target_name, e)
    return False


# ---------------------------------------------------------------------------
# Pin
# ---------------------------------------------------------------------------

def get_object_pin_status(object_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT pin FROM transient.objects "
                "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
                (object_name, object_name)
            )
            row = cur.fetchone()
            return bool(row and row[0])
    except Exception as e:
        logger.error("get_object_pin_status: %s", e)
        return False


def toggle_object_pin(object_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE transient.objects "
                "SET pin = NOT pin "
                "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s "
                "RETURNING pin",
                (object_name, object_name)
            )
            row = cur.fetchone()
            conn.commit()
            return bool(row and row[0])
    except Exception as e:
        logger.error("toggle_object_pin: %s", e)
        return False


def get_pinned_objects(limit: int = 20) -> list[dict]:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT o.name, o.name_prefix, o.type, "
                "COALESCE(o.internal_name,'') AS internal_names, "
                "array_to_string(o.tag,', ') AS tags, "
                "COALESCE(v.counts, 0) AS view_count "
                "FROM transient.objects o "
                "LEFT JOIN transient.object_views v ON v.obj_id = o.obj_id "
                "WHERE o.pin = TRUE "
                "ORDER BY view_count DESC LIMIT %s",
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_pinned_objects: %s", e)
        return []
