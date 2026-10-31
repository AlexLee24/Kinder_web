"""obs.robot_alerts: targets handed to the Lulin observing robot through GET /api/v1/robot/alert.

One row per alert. ``id`` only grows and is never reused, so the robot can tell a new alert from one it already
ran; ``uid`` is the source's own key (EP: 'ep_<trigger time>'), so an alert delivered twice is stored once.
A row can be cancelled (and restored) from Lab › Bots; past ``expires_at`` it counts as expired.
"""
import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

_ensured = False

_COLUMNS = ('id, uid, source, name, telescope, ra, dec, trigger_time, script, max_alt, moon_sep, observable, '
            'created_at, expires_at, status, status_by, status_at')


def _ensure(cur):
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.robot_alerts (
            id           BIGSERIAL PRIMARY KEY,
            uid          TEXT NOT NULL UNIQUE,
            source       TEXT NOT NULL,
            name         TEXT NOT NULL,
            telescope    TEXT NOT NULL DEFAULT 'SLT',
            ra           TEXT NOT NULL,
            dec          TEXT NOT NULL,
            trigger_time TEXT,
            script       TEXT NOT NULL,
            max_alt      DOUBLE PRECISION,
            moon_sep     DOUBLE PRECISION,
            observable   BOOLEAN,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at   TIMESTAMPTZ NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            status_by    TEXT,
            status_at    TIMESTAMPTZ
        )
    """)
    cur.connection.commit()
    _ensured = True


def _row(r):
    d = dict(r)
    for k in ('created_at', 'expires_at', 'status_at'):
        if d.get(k) is not None:
            d[k] = d[k].isoformat(timespec='seconds')
    return d


def add_alert(uid, source, name, ra, dec, script, expires_at, telescope='SLT', trigger_time=None,
              max_alt=None, moon_sep=None, observable=None):
    """Store an alert; returns its new id, or None when ``uid`` is already stored."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute("INSERT INTO obs.robot_alerts (uid, source, name, telescope, ra, dec, trigger_time, script, "
                    " max_alt, moon_sep, observable, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (uid) DO NOTHING RETURNING id",
                    (uid, source, name, telescope, ra, dec, trigger_time, script, max_alt, moon_sep, observable,
                     expires_at))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def newest_active():
    """The newest alert that is active and not expired, or None."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute(f"SELECT {_COLUMNS} FROM obs.robot_alerts WHERE status = 'active' AND expires_at > now() "
                    "ORDER BY id DESC LIMIT 1")
        r = cur.fetchone()
        return _row(r) if r else None


def recent_alerts(limit=20):
    """The newest alerts, newest first (Lab › Bots)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute(f'SELECT {_COLUMNS} FROM obs.robot_alerts ORDER BY id DESC LIMIT %s', (int(limit),))
        return [_row(r) for r in cur.fetchall()]


def set_status(alert_id, status, by):
    """'active' or 'cancelled'; returns True when the row exists."""
    if status not in ('active', 'cancelled'):
        raise ValueError(status)
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('UPDATE obs.robot_alerts SET status = %s, status_by = %s, status_at = now() WHERE id = %s',
                    (status, by, int(alert_id)))
        conn.commit()
        return cur.rowcount > 0
