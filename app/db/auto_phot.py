"""obs.auto_phot: the automatic photometry of each night's Lulin frames (app/services/auto_phot.py).

One row per (night, target, telescope). ``night`` is the evening's date (the UTC date of the frames, which at Lulin
is also the local evening's date). ``target`` is the Calibrated_Science folder name; ``obj_name`` the Kinder object
it matched (None: measured, but not added to any Transient page). ``phot`` holds the measured points:
[{'filter', 'mjd', 'mag', 'err', 'lim', 'snr', 'det', 'veto', 'image'}]. ``phot_ids`` are the transient.photometry
rows the run added, so a re-run replaces them.
"""
import json
import logging

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

_ensured = False
STATUSES = ('queued', 'running', 'done', 'failed', 'skipped')


def _ensure(cur):
    global _ensured
    if _ensured:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS obs.auto_phot (
            id          BIGSERIAL PRIMARY KEY,
            night       DATE NOT NULL,
            target      TEXT NOT NULL,
            telescope   TEXT NOT NULL,
            obj_name    TEXT,
            workspace   TEXT,
            status      TEXT NOT NULL DEFAULT 'queued',
            reason      TEXT,
            n_frames    INTEGER NOT NULL DEFAULT 0,
            n_done      INTEGER NOT NULL DEFAULT 0,
            filters     TEXT[] NOT NULL DEFAULT '{}',
            ra          DOUBLE PRECISION,
            dec         DOUBLE PRECISION,
            phot        JSONB NOT NULL DEFAULT '[]'::jsonb,
            phot_ids    BIGINT[] NOT NULL DEFAULT '{}',
            started_at  TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (night, target, telescope)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS auto_phot_night ON obs.auto_phot (night DESC)")
    cur.connection.commit()
    _ensured = True


def _row(r):
    d = dict(r)
    d['night'] = d['night'].isoformat()
    for k in ('started_at', 'finished_at', 'updated_at'):
        if d.get(k) is not None:
            d[k] = d[k].isoformat(timespec='seconds')
    d['filters'] = list(d.get('filters') or [])
    d['phot_ids'] = list(d.get('phot_ids') or [])
    return d


def upsert(night, target, telescope, **fields):
    """Create or update the row of (night, target, telescope); returns it."""
    allowed = {'obj_name', 'workspace', 'status', 'reason', 'n_frames', 'n_done', 'filters', 'ra', 'dec', 'phot',
               'phot_ids', 'started_at', 'finished_at'}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if 'phot' in fields:
        fields['phot'] = json.dumps(fields['phot'])
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cols = ['night', 'target', 'telescope'] + list(fields)
        vals = [night, target, telescope] + list(fields.values())
        sets = ', '.join(f'{k} = EXCLUDED.{k}' for k in fields) + (', ' if fields else '') + 'updated_at = now()'
        cur.execute(f"INSERT INTO obs.auto_phot ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                    f"ON CONFLICT (night, target, telescope) DO UPDATE SET {sets} RETURNING *", vals)
        row = cur.fetchone()
        conn.commit()
    return _row(row)


def get(row_id):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute('SELECT * FROM obs.auto_phot WHERE id = %s', (row_id,))
        r = cur.fetchone()
    return _row(r) if r else None


def for_night(night):
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute('SELECT * FROM obs.auto_phot WHERE night = %s ORDER BY telescope, target', (night,))
        return [_row(r) for r in cur.fetchall()]


def nights(limit=60):
    """The nights that have rows, newest first: [{'night', 'n', 'n_done', 'n_failed'}]."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute("SELECT night, count(*) AS n, count(*) FILTER (WHERE status = 'done') AS n_done, "
                    "count(*) FILTER (WHERE status = 'failed') AS n_failed FROM obs.auto_phot "
                    "GROUP BY night ORDER BY night DESC LIMIT %s", (limit,))
        return [{**dict(r), 'night': r['night'].isoformat()} for r in cur.fetchall()]


def latest_by_target(targets):
    """{target name: newest row} for the given Calibrated_Science / observation-target names."""
    if not targets:
        return {}
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        _ensure(cur)
        cur.execute("SELECT DISTINCT ON (target, telescope) * FROM obs.auto_phot WHERE target = ANY(%s) "
                    "ORDER BY target, telescope, night DESC", (list(targets),))
        out = {}
        for r in cur.fetchall():
            d = _row(r)
            out.setdefault(d['target'], []).append(d)
        return out
