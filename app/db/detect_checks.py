"""transient.detect_checks: objects a person has looked at on DETECT (TNS-DETECT and LSST-DETECT).

One row per (kind, name) — kind 'tns' (transient.objects name) or 'lsst' ('LSST-<oid>'); no row = not
checked. Ticked by the Check box of the overview's "Highest priority right now", the Check button on a
review card, and every host decision on a card (set host, Follow-up, Done, No host). Shared by the lab:
whoever checked it is in ``checked_by``.
"""
import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

KINDS = ('tns', 'lsst')
_ensured = False


def _ensure(conn, cur):
    """Create the table once per process; committed at once, since a reader's connection goes back
    to the pool with a rollback."""
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transient.detect_checks (
            kind       TEXT NOT NULL,
            name       TEXT NOT NULL,
            checked_by TEXT,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (kind, name)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS detect_checks_recent_idx ON transient.detect_checks (kind, checked_at DESC)")
    conn.commit()
    _ensured = True


def set_checked(kind: str, name: str, checked: bool = True, by: str | None = None) -> bool:
    """Tick (or untick) one object. A repeated tick keeps the first person and time."""
    if kind not in KINDS or not name:
        return False
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            _ensure(conn, cur)
            if checked:
                cur.execute("""
                    INSERT INTO transient.detect_checks (kind, name, checked_by) VALUES (%s, %s, %s)
                    ON CONFLICT (kind, name) DO NOTHING
                """, (kind, name, by))
            else:
                cur.execute("DELETE FROM transient.detect_checks WHERE kind = %s AND name = %s", (kind, name))
            conn.commit()
        return True
    except Exception as e:
        logger.error('detect_checks.set_checked(%s, %s): %s', kind, name, e)
        return False


def checked_names(kind: str, names) -> dict[str, dict]:
    """{name: {'checked_by', 'checked_at'}} for those of ``names`` that are checked."""
    names = [n for n in (names or []) if n]
    if kind not in KINDS or not names:
        return {}
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            _ensure(conn, cur)
            cur.execute("""
                SELECT name, checked_by, checked_at FROM transient.detect_checks
                 WHERE kind = %s AND name = ANY(%s)
            """, (kind, names))
            return {r['name']: {'checked_by': r['checked_by'],
                                'checked_at': r['checked_at'].strftime('%Y-%m-%d %H:%M')} for r in cur.fetchall()}
    except Exception as e:
        logger.error('detect_checks.checked_names(%s): %s', kind, e)
        return {}


def recent_checked(kind: str, limit: int = 30) -> list[dict]:
    """The most recently checked objects, newest first: [{'name', 'checked_by', 'checked_at'}]."""
    if kind not in KINDS:
        return []
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            _ensure(conn, cur)
            cur.execute("""
                SELECT name, checked_by, checked_at FROM transient.detect_checks
                 WHERE kind = %s ORDER BY checked_at DESC LIMIT %s
            """, (kind, int(limit)))
            return [{'name': r['name'], 'checked_by': r['checked_by'],
                     'checked_at': r['checked_at'].strftime('%Y-%m-%d %H:%M')} for r in cur.fetchall()]
    except Exception as e:
        logger.error('detect_checks.recent_checked(%s): %s', kind, e)
        return []
