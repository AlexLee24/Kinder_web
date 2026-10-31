"""obs.lab_calendar_events and obs.lab_calendar_feeds: the Lab calendar (Lab › Calendar).

``obs.lab_calendar_events`` holds both kinds of event:
  source 'lab'    events the group adds on the page (``uid`` NULL); may repeat every 1–4 weeks or monthly.
                  Trigger duty (category 'trigger') names the member on duty (``assignee_email`` / ``assignee_name``)
  source 'lulin'  the Lulin LOT schedule, copied from its Google calendar by app/services/lab_calendar.py
                  (``uid`` = the Google event UID, so a re-sync updates rows instead of adding them again)
Times are TIMESTAMPTZ. An all-day event runs from 00:00 Taiwan time on its first day to 00:00 after its last day
(``end_at`` exclusive, like an iCalendar DTEND).

``obs.lab_calendar_feeds`` gives each member one secret subscription link (``token``); calendar apps fetch the feed
without a login, so the token is the only key. Resetting it breaks the old link.

``remind_minutes``: when Kinder reminds the members (bell + push) before a lab event — 30 by default (also for rows
from before the column existed), NULL = no reminder; all-day events count from 09:00 on their first day.
``obs.lab_event_reminders`` holds one row per (event, occurrence start) once that reminder went out.

``obs.lab_trigger_reminders``: one row per (night, member) once the sunset reminder for Trigger duty was handled, so
it goes out once even with several workers (``outcome``: sent / already_sent / no_device).
"""
import logging
import secrets

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

_ensured = False

_COLUMNS = ('id, source, uid, category, title, description, location, url, all_day, start_at, end_at, '
            'repeat, repeat_until, assignee_email, assignee_name, remind_minutes, created_by, created_by_name, created_at, updated_at')


def _ensure(cur):
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.lab_calendar_events (
            id              BIGSERIAL PRIMARY KEY,
            source          TEXT NOT NULL DEFAULT 'lab',
            uid             TEXT UNIQUE,
            category        TEXT NOT NULL DEFAULT 'other',
            title           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            location        TEXT NOT NULL DEFAULT '',
            url             TEXT NOT NULL DEFAULT '',
            all_day         BOOLEAN NOT NULL DEFAULT true,
            start_at        TIMESTAMPTZ NOT NULL,
            end_at          TIMESTAMPTZ NOT NULL,
            repeat          TEXT NOT NULL DEFAULT '',
            repeat_until    DATE,
            created_by      TEXT,
            created_by_name TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute('ALTER TABLE obs.lab_calendar_events ADD COLUMN IF NOT EXISTS assignee_email TEXT')
    cur.execute('ALTER TABLE obs.lab_calendar_events ADD COLUMN IF NOT EXISTS assignee_name TEXT')
    cur.execute('ALTER TABLE obs.lab_calendar_events ADD COLUMN IF NOT EXISTS remind_minutes INTEGER DEFAULT 30')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.lab_event_reminders (
            event_id   BIGINT NOT NULL,
            starts_at  TIMESTAMPTZ NOT NULL,
            recipients INTEGER NOT NULL DEFAULT 0,
            sent_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (event_id, starts_at)
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS lab_calendar_events_start_idx ON obs.lab_calendar_events (start_at)')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.lab_trigger_reminders (
            day       DATE NOT NULL,
            email     TEXT NOT NULL,
            event_id  BIGINT,
            outcome   TEXT NOT NULL DEFAULT 'sent',
            devices   INTEGER NOT NULL DEFAULT 0,
            sent_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (day, email)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.lab_calendar_feeds (
            email        TEXT PRIMARY KEY,
            token        TEXT NOT NULL UNIQUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ
        )
    """)
    cur.connection.commit()
    _ensured = True


def list_events(source=None, since=None):
    """Every event (both sources unless ``source`` is given), oldest first. ``since``: only events that end after it
    or repeat (a repeating event's later occurrences may still fall in the range)."""
    where, args = [], []
    if source:
        where.append('source = %s')
        args.append(source)
    if since is not None:
        where.append("(end_at > %s OR repeat <> '')")
        args.append(since)
    sql = f'SELECT {_COLUMNS} FROM obs.lab_calendar_events'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute(sql + ' ORDER BY start_at, id', args)
        return [dict(r) for r in cur.fetchall()]


def get_event(event_id):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute(f'SELECT {_COLUMNS} FROM obs.lab_calendar_events WHERE id = %s', (int(event_id),))
        r = cur.fetchone()
        return dict(r) if r else None


_EDITABLE = ('category', 'title', 'description', 'location', 'url', 'all_day', 'start_at', 'end_at',
             'repeat', 'repeat_until', 'assignee_email', 'assignee_name', 'remind_minutes')


def add_event(fields, created_by, created_by_name=''):
    """A new 'lab' event from ``fields`` (the _EDITABLE keys); returns its id."""
    cols = [k for k in _EDITABLE if k in fields]
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute(f"INSERT INTO obs.lab_calendar_events (source, {', '.join(cols)}, created_by, created_by_name) "
                    f"VALUES ('lab', {', '.join(['%s'] * len(cols))}, %s, %s) RETURNING id",
                    [fields[k] for k in cols] + [created_by, created_by_name])
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def update_event(event_id, fields):
    """Update a 'lab' event; True when it exists. Lulin rows are only changed by the sync."""
    cols = [k for k in _EDITABLE if k in fields]
    if not cols:
        return False
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute(f"UPDATE obs.lab_calendar_events SET {', '.join(f'{k} = %s' for k in cols)}, updated_at = now() "
                    "WHERE id = %s AND source = 'lab'", [fields[k] for k in cols] + [int(event_id)])
        conn.commit()
        return cur.rowcount > 0


def delete_event(event_id):
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute("DELETE FROM obs.lab_calendar_events WHERE id = %s AND source = 'lab'", (int(event_id),))
        conn.commit()
        return cur.rowcount > 0


def replace_source(source, events):
    """Make the rows of ``source`` exactly ``events`` (dicts with uid, category, title, description, location, url,
    all_day, start_at, end_at), matched by uid. Returns {'added', 'updated', 'removed'} in one transaction."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('SELECT uid, category, title, description, location, url, all_day, start_at, end_at '
                    'FROM obs.lab_calendar_events WHERE source = %s', (source,))
        old = {r[0]: r[1:] for r in cur.fetchall()}
        new_uids = set()
        added = updated = 0
        for e in events:
            uid = e['uid']
            if uid in new_uids:
                continue
            new_uids.add(uid)
            row = (e['category'], e['title'], e.get('description') or '', e.get('location') or '', e.get('url') or '',
                   bool(e['all_day']), e['start_at'], e['end_at'])
            if uid not in old:
                cur.execute('INSERT INTO obs.lab_calendar_events (source, uid, category, title, description, location, '
                            ' url, all_day, start_at, end_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
                            'ON CONFLICT (uid) DO NOTHING', (source, uid) + row)
                added += cur.rowcount
            elif tuple(old[uid]) != row:
                cur.execute('UPDATE obs.lab_calendar_events SET category = %s, title = %s, description = %s, '
                            ' location = %s, url = %s, all_day = %s, start_at = %s, end_at = %s, updated_at = now() '
                            'WHERE uid = %s AND source = %s', row + (uid, source))
                updated += cur.rowcount
        gone = [u for u in old if u not in new_uids]
        if gone:
            cur.execute('DELETE FROM obs.lab_calendar_events WHERE source = %s AND uid = ANY(%s)', (source, gone))
        conn.commit()
        return {'added': added, 'updated': updated, 'removed': len(gone)}


# ── Subscription links ──

def feed_token(email, reset=False):
    """The member's subscription token (made on first use; ``reset`` replaces it)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        if not reset:
            cur.execute('SELECT token FROM obs.lab_calendar_feeds WHERE email = %s', (email,))
            row = cur.fetchone()
            if row:
                return row[0]
        token = secrets.token_urlsafe(24)
        cur.execute('INSERT INTO obs.lab_calendar_feeds (email, token) VALUES (%s, %s) '
                    'ON CONFLICT (email) DO UPDATE SET token = EXCLUDED.token, created_at = now(), last_used_at = NULL',
                    (email, token))
        conn.commit()
        return token


def email_for_token(token):
    """Whose link this is (and note that it was used), or None."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('UPDATE obs.lab_calendar_feeds SET last_used_at = now() WHERE token = %s RETURNING email',
                    (token,))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


# ── Trigger duty reminders ──

def claim_reminder(day, email, event_id):
    """Take the (night, member) reminder; False when it was already handled (by this or another process)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('INSERT INTO obs.lab_trigger_reminders (day, email, event_id, outcome) VALUES (%s, %s, %s, %s) '
                    'ON CONFLICT DO NOTHING', (day, email, event_id, 'pending'))
        conn.commit()
        return cur.rowcount > 0


def finish_reminder(day, email, outcome, devices=0):
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('UPDATE obs.lab_trigger_reminders SET outcome = %s, devices = %s, sent_at = now() '
                    'WHERE day = %s AND email = %s', (outcome, int(devices), day, email))
        conn.commit()


def reminders_since(day):
    """{(day ISO, email): {'outcome', 'devices', 'sent_at'}} from ``day`` on."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute('SELECT day, email, outcome, devices, sent_at FROM obs.lab_trigger_reminders WHERE day >= %s', (day,))
        return {(r['day'].isoformat(), r['email']): {'outcome': r['outcome'], 'devices': r['devices'],
                                                     'sent_at': r['sent_at'].isoformat(timespec='seconds')}
                for r in cur.fetchall()}


# ── Event reminders ──

def claim_event_reminder(event_id, starts_at):
    """Take the reminder of one occurrence; False when it already went out (from this or another process)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('INSERT INTO obs.lab_event_reminders (event_id, starts_at) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    (int(event_id), starts_at))
        conn.commit()
        return cur.rowcount > 0


def finish_event_reminder(event_id, starts_at, recipients):
    with get_db_connection() as conn:
        cur = conn.cursor()
        _ensure(cur)
        cur.execute('UPDATE obs.lab_event_reminders SET recipients = %s, sent_at = now() WHERE event_id = %s AND starts_at = %s',
                    (int(recipients), int(event_id), starts_at))
        cur.execute("DELETE FROM obs.lab_event_reminders WHERE starts_at < now() - interval '60 days'")
        conn.commit()
