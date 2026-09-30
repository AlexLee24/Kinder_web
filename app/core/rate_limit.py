"""Rate limiting shared by every worker process on this host.

Hits are stored in a small SQLite file under ``DATA_DIR`` (override with the
``RATE_LIMIT_DB`` environment variable), so gunicorn workers see each other's
counts. If the file cannot be used, the limiter falls back to a per-process
in-memory store instead of failing the request.
"""
import logging
import os
import random
import sqlite3
import threading
import time
from collections import defaultdict, deque

from app.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv('RATE_LIMIT_DB') or str(DATA_DIR / 'rate_limit.sqlite3')
_MAX_WINDOW_S = 24 * 3600          # hits older than this are purged
_init_lock = threading.Lock()
_initialised = False

# In-memory fallback (per process).
_mem_lock = threading.Lock()
_mem_hits: dict[str, deque] = defaultdict(deque)


def _connect() -> sqlite3.Connection:
    global _initialised
    conn = sqlite3.connect(_DB_PATH, timeout=2.0, isolation_level=None)
    if not _initialised:
        with _init_lock:
            if not _initialised:
                os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('CREATE TABLE IF NOT EXISTS hits (key TEXT NOT NULL, ts REAL NOT NULL)')
                conn.execute('CREATE INDEX IF NOT EXISTS hits_key_ts ON hits (key, ts)')
                _initialised = True
    return conn


def _mem_count(key: str, window: float, now: float) -> deque:
    q = _mem_hits[key]
    while q and now - q[0] > window:
        q.popleft()
    return q


def _db_call(fn):
    """Run fn(conn) inside an immediate transaction; None if the DB is unusable."""
    try:
        conn = _connect()
    except (sqlite3.Error, OSError) as exc:
        logger.warning('rate limiter: shared store unavailable (%s); using in-memory', exc)
        return None
    try:
        conn.execute('BEGIN IMMEDIATE')
        try:
            result = fn(conn)
            if random.random() < 0.01:
                conn.execute('DELETE FROM hits WHERE ts < ?', (time.time() - _MAX_WINDOW_S,))
            conn.execute('COMMIT')
            return result
        except Exception:
            conn.execute('ROLLBACK')
            raise
    except sqlite3.Error as exc:
        logger.warning('rate limiter: shared store error (%s); using in-memory', exc)
        return None
    finally:
        conn.close()


def allow(key: str, limit: int, window: float) -> bool:
    """Record a hit and return True if fewer than ``limit`` hits for ``key``
    happened in the last ``window`` seconds; otherwise return False (no hit recorded)."""
    limit = max(1, int(limit))
    now = time.time()

    def _run(conn):
        n = conn.execute('SELECT COUNT(*) FROM hits WHERE key = ? AND ts > ?',
                         (key, now - window)).fetchone()[0]
        if n >= limit:
            return False
        conn.execute('INSERT INTO hits (key, ts) VALUES (?, ?)', (key, now))
        return True

    result = _db_call(_run)
    if result is not None:
        return result
    with _mem_lock:
        q = _mem_count(key, window, now)
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def count(key: str, window: float) -> int:
    """Number of hits recorded for ``key`` in the last ``window`` seconds."""
    now = time.time()
    result = _db_call(lambda conn: conn.execute(
        'SELECT COUNT(*) FROM hits WHERE key = ? AND ts > ?', (key, now - window)).fetchone()[0])
    if result is not None:
        return result
    with _mem_lock:
        return len(_mem_count(key, window, now))


def hit(key: str) -> None:
    """Record a hit for ``key`` unconditionally."""
    now = time.time()
    done = _db_call(lambda conn: conn.execute(
        'INSERT INTO hits (key, ts) VALUES (?, ?)', (key, now)) and True)
    if done is None:
        with _mem_lock:
            _mem_hits[key].append(now)


def clear(key: str) -> None:
    """Forget all hits for ``key`` (e.g. reset failed logins after a success)."""
    _db_call(lambda conn: conn.execute('DELETE FROM hits WHERE key = ?', (key,)) and True)
    with _mem_lock:
        _mem_hits.pop(key, None)
