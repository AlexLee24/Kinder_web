"""auth.push_subscriptions and auth.push_broadcasts: Web Push (app/services/notifications/webpush.py).

``push_subscriptions``: one row per browser / device that turned push on (``endpoint`` is unique; a device that logs
in as someone else moves to that account). ``categories`` says which kinds of push the device takes (today only
'announce'; the column is there for automatic pushes later). ``fail_count`` / ``last_ok_at`` / ``last_error`` record
delivery: a 404 / 410 from the push service deletes the row, other errors delete it after MAX_FAILS in a row.

``push_broadcasts``: what admins sent from Admin › Push (who, to whom, how many devices took it).
"""
import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

MAX_FAILS = 5
_ensured = False

_SUB_COLUMNS = ('s.id, s.usr_id, s.endpoint, s.p256dh, s.auth, s.categories, s.user_agent, s.fail_count, '
                's.last_ok_at, s.last_error, s.created_at')


def _ensure(cur):
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth.push_subscriptions (
            id          BIGSERIAL PRIMARY KEY,
            usr_id      INTEGER NOT NULL REFERENCES auth.users(usr_id) ON DELETE CASCADE,
            endpoint    TEXT NOT NULL UNIQUE,
            p256dh      TEXT NOT NULL,
            auth        TEXT NOT NULL,
            categories  TEXT[] NOT NULL DEFAULT '{announce}',
            user_agent  TEXT,
            fail_count  INTEGER NOT NULL DEFAULT 0,
            last_ok_at  TIMESTAMPTZ,
            last_error  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS push_subscriptions_usr_idx ON auth.push_subscriptions (usr_id)')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth.push_broadcasts (
            id           BIGSERIAL PRIMARY KEY,
            author_email TEXT,
            title        TEXT NOT NULL,
            body         TEXT NOT NULL DEFAULT '',
            url          TEXT NOT NULL DEFAULT '',
            target       TEXT NOT NULL,
            target_desc  TEXT NOT NULL DEFAULT '',
            recipients   INTEGER NOT NULL DEFAULT 0,
            devices      INTEGER NOT NULL DEFAULT 0,
            delivered    INTEGER,
            failed       INTEGER,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.connection.commit()
    _ensured = True


def _cursor(conn, dict_rows=True):
    cur = conn.cursor(cursor_factory=extras.RealDictCursor) if dict_rows else conn.cursor()
    _ensure(cur)
    return cur


# ── Subscriptions ──

def save(usr_id, endpoint, p256dh, auth, user_agent='', categories=('announce',)):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute("""
            INSERT INTO auth.push_subscriptions (usr_id, endpoint, p256dh, auth, categories, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET usr_id = EXCLUDED.usr_id, p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth, categories = EXCLUDED.categories, user_agent = EXCLUDED.user_agent,
                fail_count = 0, last_error = NULL
        """, (int(usr_id), endpoint, p256dh, auth, list(categories), (user_agent or '')[:300] or None))
        conn.commit()


def remove(usr_id, endpoint):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('DELETE FROM auth.push_subscriptions WHERE usr_id = %s AND endpoint = %s', (int(usr_id), endpoint))
        conn.commit()
        return cur.rowcount


def delete(sub_id):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('DELETE FROM auth.push_subscriptions WHERE id = %s', (int(sub_id),))
        conn.commit()
        return cur.rowcount > 0


def status(usr_id, endpoint):
    """(this device is subscribed for this account, how many devices the account has)."""
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('SELECT count(*), count(*) FILTER (WHERE endpoint = %s) FROM auth.push_subscriptions '
                    'WHERE usr_id = %s', (endpoint or '', int(usr_id)))
        n, mine = cur.fetchone()
        return bool(mine), int(n)


def subscriptions(usr_ids=None, category=None, sub_id=None):
    """Rows (dicts) to send to: one device, some accounts, or everyone; optionally only those taking ``category``."""
    where, args = [], []
    if sub_id is not None:
        where.append('s.id = %s')
        args.append(int(sub_id))
    if usr_ids is not None:
        where.append('s.usr_id = ANY(%s)')
        args.append([int(u) for u in usr_ids])
    if category:
        where.append('%s = ANY(s.categories)')
        args.append(category)
    sql = f'SELECT {_SUB_COLUMNS} FROM auth.push_subscriptions s'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    with get_db_connection() as conn:
        cur = _cursor(conn)
        cur.execute(sql + ' ORDER BY s.usr_id, s.created_at', args)
        return [dict(r) for r in cur.fetchall()]


def mark_ok(sub_id):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('UPDATE auth.push_subscriptions SET fail_count = 0, last_ok_at = now(), last_error = NULL '
                    'WHERE id = %s', (int(sub_id),))
        conn.commit()


def mark_failed(sub_id, error, gone):
    """Record a failed send; True when the row was deleted (gone, or too many failures in a row)."""
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        if gone:
            cur.execute('DELETE FROM auth.push_subscriptions WHERE id = %s', (int(sub_id),))
        else:
            cur.execute('UPDATE auth.push_subscriptions SET fail_count = fail_count + 1, last_error = %s '
                        'WHERE id = %s', ((error or '')[:300], int(sub_id)))
            cur.execute('DELETE FROM auth.push_subscriptions WHERE id = %s AND fail_count >= %s',
                        (int(sub_id), MAX_FAILS))
        conn.commit()
        return gone or cur.rowcount > 0


def device_counts():
    """{usr_id: number of devices}."""
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('SELECT usr_id, count(*) FROM auth.push_subscriptions GROUP BY usr_id')
        return {r[0]: int(r[1]) for r in cur.fetchall()}


# ── Broadcasts ──

def add_broadcast(author_email, title, body, url, target, target_desc, recipients, devices):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('INSERT INTO auth.push_broadcasts (author_email, title, body, url, target, target_desc, '
                    ' recipients, devices) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
                    (author_email, title, body or '', url or '', target, (target_desc or '')[:1000], recipients, devices))
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def finish_broadcast(broadcast_id, delivered, failed):
    with get_db_connection() as conn:
        cur = _cursor(conn, False)
        cur.execute('UPDATE auth.push_broadcasts SET delivered = %s, failed = %s WHERE id = %s',
                    (delivered, failed, int(broadcast_id)))
        conn.commit()


def recent_broadcasts(limit=30):
    with get_db_connection() as conn:
        cur = _cursor(conn)
        cur.execute('SELECT id, author_email, title, body, url, target, target_desc, recipients, devices, delivered, '
                    ' failed, created_at FROM auth.push_broadcasts ORDER BY id DESC LIMIT %s', (int(limit),))
        return [dict(r) for r in cur.fetchall()]
