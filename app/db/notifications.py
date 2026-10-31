"""auth.notifications: the bell in the top bar (after EAU_Web's web.notifications).

One row per (account, message). Everything Kinder pushes (app/services/notifications/webpush.py: admin messages,
Einstein Probe alerts, Trigger duty reminders) is written here first, so people without push still see it under the
bell; ``read_at`` NULL = unread. Rows older than KEEP_DAYS are dropped when new ones are written.
"""
import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

KEEP_DAYS = 120
_ensured = False


def _ensure(cur):
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth.notifications (
            id         BIGSERIAL PRIMARY KEY,
            usr_id     INTEGER NOT NULL REFERENCES auth.users(usr_id) ON DELETE CASCADE,
            kind       TEXT NOT NULL DEFAULT 'announce',
            title      TEXT NOT NULL,
            body       TEXT NOT NULL DEFAULT '',
            url        TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at    TIMESTAMPTZ
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS notifications_usr_idx ON auth.notifications (usr_id, id DESC)')
    cur.connection.commit()
    _ensured = True


def add_many(usr_ids, kind, title, body='', url=''):
    """One notification per account; returns {usr_id: notification id}."""
    ids = sorted({int(u) for u in usr_ids or []})
    if not ids:
        return {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        rows = extras.execute_values(
            cur, 'INSERT INTO auth.notifications (usr_id, kind, title, body, url) VALUES %s RETURNING usr_id, id',
            [(u, kind, title[:200], (body or '')[:1000], (url or '')[:1000]) for u in ids], fetch=True)
        cur.execute("DELETE FROM auth.notifications WHERE created_at < now() - %s * interval '1 day'", (KEEP_DAYS,))
        conn.commit()
        return {r[0]: r[1] for r in rows}


def unread_count(usr_id):
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('SELECT count(*) FROM auth.notifications WHERE usr_id = %s AND read_at IS NULL', (int(usr_id),))
        return int(cur.fetchone()[0])


def unread_counts(usr_ids):
    """{usr_id: unread} for these accounts (the badge number sent with a push)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('SELECT usr_id, count(*) FROM auth.notifications WHERE usr_id = ANY(%s) AND read_at IS NULL '
                    'GROUP BY usr_id', ([int(u) for u in usr_ids],))
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def recent(usr_id, limit=30):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute('SELECT id, kind, title, body, url, created_at, read_at FROM auth.notifications '
                    'WHERE usr_id = %s ORDER BY id DESC LIMIT %s', (int(usr_id), int(limit)))
        return [dict(r) for r in cur.fetchall()]


def open_one(usr_id, notif_id):
    """Mark one notification read and return its url ('' when it is not this account's)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('UPDATE auth.notifications SET read_at = COALESCE(read_at, now()) WHERE id = %s AND usr_id = %s '
                    'RETURNING url', (int(notif_id), int(usr_id)))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def mark_read(usr_id, ids=None):
    """Mark these (or, without ids, all) of the account's notifications read."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        if ids is None:
            cur.execute('UPDATE auth.notifications SET read_at = now() WHERE usr_id = %s AND read_at IS NULL',
                        (int(usr_id),))
        else:
            cur.execute('UPDATE auth.notifications SET read_at = now() WHERE usr_id = %s AND id = ANY(%s) '
                        'AND read_at IS NULL', (int(usr_id), [int(i) for i in ids]))
        conn.commit()


def delete(usr_id, ids=None, read=False):
    """Delete these ids, or (``read``) every read one, of the account."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        if read:
            cur.execute('DELETE FROM auth.notifications WHERE usr_id = %s AND read_at IS NOT NULL', (int(usr_id),))
        else:
            cur.execute('DELETE FROM auth.notifications WHERE usr_id = %s AND id = ANY(%s)',
                        (int(usr_id), [int(i) for i in ids or []]))
        conn.commit()
        return cur.rowcount
