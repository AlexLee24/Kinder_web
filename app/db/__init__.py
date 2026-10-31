"""Kinder Database Package — connection pool for the unified 'Kinder' PostgreSQL DB.

Schema layout:
  auth.*       → auth.py
  transient.*  → transient.py
  obs.*        → obs.py
  cat.*        → catalog.py
"""

import logging
import os
import threading
import time
import psycopg2
import psycopg2.pool
from contextlib import contextmanager

from app import config as _config  # noqa: F401  -- loads kinder.env (single place)

DB_HOST     = os.getenv("PG_HOST", "localhost")
DB_PORT     = os.getenv("PG_PORT", "5432")
DB_USER     = os.getenv("PG_USER", "postgres")
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_NAME     = "Kinder"

# application_name reported by this app's pooled connections (pg_stat_activity);
# the admin "terminate idle" tool uses it to avoid killing our own pool.
APP_DB_APPLICATION_NAME = "kinder_web"

_DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Smaller pool in DEBUG mode so we don't waste connections during development
_POOL_MIN = 1  if _DEBUG else 2
_POOL_MAX = 10 if _DEBUG else 60
# Idle connections kept open between requests. psycopg2's pool keeps only `minconn`
# and closes every other connection it gets back, so concurrent requests kept
# reconnecting (a TCP + auth handshake each: ~1.3 s over a remote link).
_POOL_KEEP_IDLE = 10
# A connection idle longer than this gets a liveness ping before it is handed out;
# fresher ones are used directly (a broken one still raises and is discarded).
_PING_AFTER_IDLE_S = 30.0

logger = logging.getLogger(__name__)

class _KeepIdlePool(psycopg2.pool.ThreadedConnectionPool):
    """ThreadedConnectionPool that keeps up to _POOL_KEEP_IDLE idle connections
    (instead of only `minconn`) and remembers when each was returned."""

    def __init__(self, *args, **kwargs):
        self.returned_at: dict[int, float] = {}
        super().__init__(*args, **kwargs)

    def _putconn(self, conn, key=None, close=False):
        # psycopg2 keeps a returned connection only while len(_pool) < minconn; raise
        # that bar for the duration of the call (putconn holds the pool lock).
        real_min = self.minconn
        self.minconn = max(real_min, min(_POOL_KEEP_IDLE, self.maxconn))
        try:
            super()._putconn(conn, key, close)
        finally:
            self.minconn = real_min
        if close or conn.closed:
            self.returned_at.pop(id(conn), None)
        else:
            self.returned_at[id(conn)] = time.monotonic()


_connection_pool: _KeepIdlePool | None = None


def init_connection_pool(minconn: int = _POOL_MIN, maxconn: int = _POOL_MAX):
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = _KeepIdlePool(
            minconn, maxconn,
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            connect_timeout=5,
            application_name=APP_DB_APPLICATION_NAME,
            # ── Server-side safety timeouts ───────────────────────────────
            # Kill any connection that sits idle-in-transaction for >5 min,
            # and any individual statement that runs >2 min.
            options=(
                "-c idle_in_transaction_session_timeout=300000"   # 5 min (ms)
                " -c statement_timeout=120000"                    # 2 min (ms)
            ),
            # ── TCP keepalives — detect broken/dead sockets promptly ──────
            keepalives=1,
            keepalives_idle=60,      # send keepalive probe after 60 s idle
            keepalives_interval=10,  # retry probe every 10 s
            keepalives_count=5,      # 5 failed probes → close socket
        )
        _ensure_extra_tables()
        logger.info("Kinder connection pool initialised (%d–%d) [debug=%s]",
                    minconn, maxconn, _DEBUG)
        threading.Thread(target=_warm_pool, name='db-warm', daemon=True).start()
    return _connection_pool


def _warm_pool(n: int = 4) -> None:
    """Open a few connections at start-up, in the background, so the first pages
    (several queries in parallel) don't each pay a connection handshake."""
    p = _connection_pool
    if p is None:
        return
    conns = []
    try:
        for _ in range(min(n, _POOL_KEEP_IDLE, p.maxconn)):
            conns.append(p.getconn())
    except Exception as exc:
        logger.debug("pool warm-up stopped: %s", exc)
    for c in conns:
        try:
            p.putconn(c)
        except Exception:
            pass


def get_pool_stats() -> dict:
    """Return current pool usage statistics.

    Returns a dict with keys:
      pool_min, pool_max, in_use, idle, usage_pct
    Returns all-zero dict if the pool has not been initialised yet.
    """
    p = _connection_pool
    if p is None:
        return {"pool_min": 0, "pool_max": 0, "in_use": 0, "idle": 0, "usage_pct": 0.0}
    try:
        # psycopg2 private attributes – stable across all 2.x versions
        in_use = len(p._used)   # type: ignore[attr-defined]  — psycopg2 internal, stable across 2.x
        idle   = len(p._pool)   # type: ignore[attr-defined]  — psycopg2 internal, stable across 2.x
        total  = p.maxconn
        return {
            "pool_min":  p.minconn,
            "pool_max":  total,
            "in_use":    in_use,
            "idle":      idle,
            "usage_pct": round(in_use / total * 100, 1) if total else 0.0,
        }
    except Exception:
        return {"pool_min": 0, "pool_max": 0, "in_use": 0, "idle": 0, "usage_pct": 0.0}


def close_connection_pool():
    """Close all connections and destroy the pool (e.g. on app teardown)."""
    global _connection_pool
    if _connection_pool is not None:
        try:
            _connection_pool.closeall()
            logger.info("Kinder connection pool closed.")
        except Exception as exc:
            logger.warning("Error closing connection pool: %s", exc)
        finally:
            _connection_pool = None


def recycle_idle_connections():
    """Close and discard all idle (not in-use) connections in the pool so that
    fresh connections are created on the next request.

    This prevents the 'stale idle connection with high age' problem where pool
    connections opened at startup are still alive hours later.  Call this
    periodically (e.g. every 30 minutes) from the background scheduler.
    """
    p = _connection_pool
    if p is None:
        return
    try:
        with p._lock:  # type: ignore[attr-defined]
            idle_conns = list(p._pool)  # type: ignore[attr-defined]
            p._pool.clear()             # type: ignore[attr-defined]
        closed = 0
        for conn in idle_conns:
            try:
                conn.close()
                closed += 1
            except Exception:
                pass
        logger.info("recycle_idle_connections: closed %d idle connection(s).", closed)
    except Exception as exc:
        logger.warning("recycle_idle_connections: %s", exc)


def _reset_conn(conn, pool_ref) -> bool:
    """Ensure a connection is in a clean state before returning it to the pool.

    If the connection has an open / aborted transaction (STATUS_IN_TRANSACTION
    or STATUS_IN_ERROR) we issue a rollback so PostgreSQL doesn't see it as
    'idle in transaction'.  Returns False (and discards the connection) if the
    reset itself fails.
    """
    try:
        # Open or aborted transaction → roll back. (psycopg2 has no STATUS_IN_ERROR;
        # referencing it raised here, so every used connection was discarded and
        # the next query had to reconnect.)
        if conn.info.transaction_status in (
            psycopg2.extensions.TRANSACTION_STATUS_INTRANS,
            psycopg2.extensions.TRANSACTION_STATUS_INERROR,
        ):
            conn.rollback()
        return True
    except Exception as exc:
        logger.debug("_reset_conn: rollback failed (%s); discarding connection.", exc)
        try:
            pool_ref.putconn(conn, close=True)
        except Exception:
            pass
        return False   # caller must NOT putconn again


class _PooledConn:
    """Wraps a pooled psycopg2 connection so that close() returns it to the pool
    in a clean (STATUS_READY) state — no dirty transactions left open."""
    __slots__ = ('_conn', '_pool')

    def __init__(self, conn, pool):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_pool', pool)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_conn'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_conn'), name, value)

    def close(self):
        p    = object.__getattribute__(self, '_pool')
        conn = object.__getattribute__(self, '_conn')
        if _reset_conn(conn, p):
            p.putconn(conn)


def _is_healthy(conn, pool=None) -> bool:
    """Liveness probe for a connection taken from the pool. Skipped (True) for a
    connection returned less than _PING_AFTER_IDLE_S ago; otherwise one round trip
    (SELECT 1 in autocommit, so no BEGIN / ROLLBACK)."""
    if conn.closed:
        return False
    returned = getattr(pool, 'returned_at', {}).get(id(conn)) if pool is not None else None
    if returned is not None and time.monotonic() - returned < _PING_AFTER_IDLE_S:
        return True
    try:
        was_auto = conn.autocommit
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.autocommit = was_auto
        return True
    except Exception:
        return False


def _checkout(p):
    """getconn() with a health check: a dead connection is discarded and one
    replacement is fetched (itself checked once more)."""
    conn = p.getconn()
    if _is_healthy(conn, p):
        return conn
    try:
        p.putconn(conn, close=True)
    except Exception:
        pass
    conn = p.getconn()
    if not _is_healthy(conn):
        try:
            p.putconn(conn, close=True)
        except Exception:
            pass
        raise psycopg2.OperationalError("could not obtain a healthy pooled connection")
    return conn


def get_tns_db_connection() -> '_PooledConn':
    """Return a raw pooled connection.  Caller MUST call conn.close() to
    return it to the pool (close() is intercepted — it does putconn, not
    actual socket close)."""
    p = init_connection_pool()
    return _PooledConn(_checkout(p), p)


@contextmanager
def get_db_connection():
    """Yield a pooled psycopg2 connection; returns it to the pool on exit.

    • Stale connections (server-closed while idle) are discarded and replaced.
    • Any OperationalError during use discards the broken connection entirely.
    • Before returning to the pool the connection is always reset (rollback if
      an open/aborted transaction exists) so PostgreSQL never sees a leftover
      'idle in transaction' from this pool.
    """
    p = init_connection_pool()
    # Discard a connection that the server closed while it sat in the pool.
    conn = _checkout(p)
    _returned = False
    try:
        yield conn
    except psycopg2.OperationalError:
        # Connection broke mid-query; remove it from the pool entirely.
        try:
            p.putconn(conn, close=True)
        except Exception:
            pass
        _returned = True
        raise
    finally:
        if not _returned:
            # Reset dirty state before handing back to pool
            if not _reset_conn(conn, p):
                _returned = True  # _reset_conn already discarded it
            else:
                p.putconn(conn)


_parallel_pool = None


def run_parallel(*calls):
    """Run independent read queries at the same time, each on its own pooled
    connection, and return their results in order. A page that needs several
    queries then waits for the slowest one instead of their sum (each round trip
    to a remote DB costs ~0.25 s). calls: zero-argument callables (use lambda /
    functools.partial). An exception in any call is re-raised here."""
    global _parallel_pool
    if len(calls) < 2:
        return [c() for c in calls]
    if _parallel_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _parallel_pool = ThreadPoolExecutor(max_workers=max(2, min(8, _POOL_MAX // 2)), thread_name_prefix='db-par')
    futures = [_parallel_pool.submit(c) for c in calls]
    return [f.result() for f in futures]


_background_pool = None


def run_in_background(fn, *args, **kwargs) -> None:
    """Fire-and-forget DB work the page does not need to wait for (view counters,
    cached-value refreshes): runs after the response on a small worker pool;
    errors are logged, never raised."""
    global _background_pool
    if _background_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _background_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='db-bg')

    def _run():
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("background %s failed: %s", getattr(fn, '__name__', fn), exc)
    _background_pool.submit(_run)


def check_db_connection() -> bool:
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            connect_timeout=5,
        )
        conn.close()
        logger.info("Connected to Kinder DB at %s:%s", DB_HOST, DB_PORT)
        return True
    except Exception as e:
        logger.error("Kinder DB connection failed: %s", e)
        return False


# Cached connectivity flag so pages (e.g. the "DB offline" home banner) don't
# pay a fresh connect_timeout on every request while the DB is down.
_STATUS_CACHE_SECONDS = 15
_status_cache = {"available": True, "checked_at": 0.0}


def _check_via_pool() -> bool:
    """Is the DB reachable? Uses a pooled connection (no fresh handshake)."""
    try:
        with get_db_connection() as conn:
            if conn.closed:
                return False
        return True
    except Exception:
        return check_db_connection()


def _refresh_status() -> None:
    try:
        was_available = _status_cache["available"]
        available = _check_via_pool()
        _status_cache["available"] = available
        _status_cache["checked_at"] = time.monotonic()
        if available and not was_available:
            logger.info("Kinder DB connection restored (%s:%s).", DB_HOST, DB_PORT)
        elif not available and was_available:
            logger.error("Kinder DB connection lost (%s:%s) — home page will show 'DB offline'.", DB_HOST, DB_PORT)
    finally:
        _status_cache["refreshing"] = False


def is_db_available(force: bool = False) -> bool:
    """Return the last-known DB availability. When it is older than
    _STATUS_CACHE_SECONDS it is re-checked in a background thread, so a request
    never waits on the check (force=True checks inline). Logs whenever the status
    flips so outages/recoveries are traceable."""
    if force:
        _status_cache["refreshing"] = True
        _refresh_status()
        return _status_cache["available"]
    if time.monotonic() - _status_cache["checked_at"] >= _STATUS_CACHE_SECONDS and not _status_cache.get("refreshing"):
        _status_cache["refreshing"] = True
        threading.Thread(target=_refresh_status, name='db-status', daemon=True).start()
    return _status_cache["available"]


# ---------------------------------------------------------------------------
# Extra tables not in the original Kinder schema DDL (backward-compat needs)
# ---------------------------------------------------------------------------

def _shrink_stored_avatars(cur) -> None:
    """One-time per row: re-encode oversized uploaded avatars (base64 data: URIs,
    formerly stored at full camera resolution) to a small thumbnail. Pages link
    to /avatar/<id>, but the value is still read with every user lookup."""
    from app.core.avatars import MAX_STORED_BYTES, shrink_data_uri
    try:
        cur.execute("SELECT usr_id FROM auth.users "
                    "WHERE picture_url LIKE 'data:%%' AND length(picture_url) > %s",
                    (MAX_STORED_BYTES,))
        ids = [r[0] for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("_ensure_extra_tables: avatar shrink skipped: %s", exc)
        return
    shrunk = 0
    for usr_id in ids:   # one row at a time: the originals can be many MB each
        try:
            cur.execute("SELECT picture_url FROM auth.users WHERE usr_id = %s", (usr_id,))
            row = cur.fetchone()
            small = shrink_data_uri(row[0]) if row and row[0] else None
            if small and len(small) < len(row[0]):
                cur.execute("UPDATE auth.users SET picture_url = %s WHERE usr_id = %s",
                            (small, usr_id))
                shrunk += 1
        except Exception as exc:
            logger.warning("_ensure_extra_tables: avatar shrink failed for usr_id=%s: %s",
                           usr_id, exc)
    if shrunk:
        logger.info("Shrunk %d oversized profile picture(s)", shrunk)


def _migrate_plaintext_api_keys(cur) -> None:
    """One-time: hash legacy plaintext auth.users.api_key values, then drop them.

    Hashing is done in Python (no pgcrypto dependency). Keys keep working: the
    lookup compares sha256(presented key) with api_key_hash."""
    import hashlib
    try:
        cur.execute("SELECT usr_id, api_key FROM auth.users "
                    "WHERE api_key IS NOT NULL AND api_key_hash IS NULL")
        rows = cur.fetchall()
    except Exception as exc:
        logger.warning("_ensure_extra_tables: api key migration skipped: %s", exc)
        return
    migrated = 0
    for usr_id, key in rows:
        key = (key or '').strip()
        try:
            if key:
                cur.execute(
                    "UPDATE auth.users SET api_key_hash = %s, api_key_hint = %s, "
                    "api_key_created_at = COALESCE(api_key_created_at, now()), api_key = NULL "
                    "WHERE usr_id = %s AND api_key_hash IS NULL",
                    (hashlib.sha256(key.encode('utf-8')).hexdigest(), key[-4:], usr_id))
            else:
                cur.execute("UPDATE auth.users SET api_key = NULL WHERE usr_id = %s", (usr_id,))
            migrated += 1
        except Exception as exc:
            logger.warning("_ensure_extra_tables: api key migration failed for usr_id=%s: %s",
                           usr_id, exc)
    # Rows that were already hashed must not keep a plaintext copy either.
    try:
        cur.execute("UPDATE auth.users SET api_key = NULL "
                    "WHERE api_key IS NOT NULL AND api_key_hash IS NOT NULL")
    except Exception as exc:
        logger.warning("_ensure_extra_tables: clearing plaintext api keys failed: %s", exc)
    if migrated:
        logger.info("Migrated %d plaintext API key(s) to hashed storage", migrated)


def _ensure_extra_tables():
    """Create supplementary tables used by app logic that are absent from the
    core Kinder schema DDL.  All created under appropriate schemas."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            connect_timeout=5,
        )
        # Autocommit: every statement is its own transaction, so one failing
        # statement (e.g. missing privilege, pre-existing duplicate data) does not
        # roll back the others.
        conn.autocommit = True
        cur = conn.cursor()

        def _run(sql):
            try:
                cur.execute(sql)
            except Exception as exc:
                logger.warning("_ensure_extra_tables: statement failed: %s", exc)

        # auth.users — password login for admin-created accounts.
        # password_hash: werkzeug scrypt hash (NULL = no password login).
        # session_version: bumped on password change/reset to log out old sessions.
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS "
             "must_change_password BOOLEAN NOT NULL DEFAULT FALSE")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS "
             "session_version INTEGER NOT NULL DEFAULT 0")

        # auth.users.username — login name for admin-created "direct login"
        # accounts (email stays the internal identity; a placeholder
        # <username>@users.invalid is stored when the admin gives none).
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS username TEXT")
        _run("CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx "
             "ON auth.users(lower(username)) WHERE username IS NOT NULL")

        # auth.users.google_sub — the Google account id ("sub") bound at first
        # Google sign-in; a different Google account for the same email is refused.
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS google_sub TEXT")
        _run("CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_idx "
             "ON auth.users(google_sub) WHERE google_sub IS NOT NULL")

        # API keys are stored hashed (sha256 hex); only the last 4 chars are kept
        # in clear (api_key_hint) so users/admins can tell keys apart.
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_hash TEXT")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_hint TEXT")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_created_at TIMESTAMPTZ")
        _run("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_last_used_at TIMESTAMPTZ")
        _run("CREATE UNIQUE INDEX IF NOT EXISTS users_api_key_hash_idx "
             "ON auth.users(api_key_hash) WHERE api_key_hash IS NOT NULL")
        _migrate_plaintext_api_keys(cur)
        _shrink_stored_avatars(cur)

        # auth.invitations — invitation tokens for new user sign-up
        _run("""
            CREATE TABLE IF NOT EXISTS auth.invitations (
                token       TEXT PRIMARY KEY,
                email       TEXT,
                is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
                role        TEXT    NOT NULL DEFAULT 'user',
                invited_by  INT     REFERENCES auth.users(usr_id) ON DELETE SET NULL,
                invited_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                status      TEXT    NOT NULL DEFAULT 'pending',
                accepted_at TIMESTAMPTZ
            )
        """)

        # auth.system_settings — generic key/value store
        _run("""
            CREATE TABLE IF NOT EXISTS auth.system_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)

        # transient.object_source_permissions — per-object per-source visibility
        _run("""
            CREATE TABLE IF NOT EXISTS transient.object_source_permissions (
                id             SERIAL PRIMARY KEY,
                object_name    TEXT NOT NULL,
                data_type      TEXT NOT NULL CHECK (data_type IN ('phot', 'spec')),
                source_name    TEXT NOT NULL,
                allowed_groups INT[]    DEFAULT NULL,
                is_public      BOOLEAN  NOT NULL DEFAULT FALSE,
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (object_name, data_type, source_name)
            )
        """)

        # Unique constraint needed for ON CONFLICT in photometry inserts
        _run("""
            DO $$ BEGIN
                BEGIN
                    ALTER TABLE transient.photometry
                        ADD CONSTRAINT phot_uniq UNIQUE (obj_id, "MJD", filter, source);
                EXCEPTION WHEN duplicate_table THEN NULL;
                END;
            END $$
        """)

        # Unique constraint for obs.logs upsert
        _run("""
            DO $$ BEGIN
                BEGIN
                    ALTER TABLE obs.logs
                        ADD CONSTRAINT obs_logs_target_date_uniq UNIQUE (target_id, date);
                EXCEPTION WHEN duplicate_table THEN NULL;
                END;
            END $$
        """)

        # kinder_id — internal sequential ID: year*1_000_000 + letter_rank
        _run("""
            ALTER TABLE transient.objects
                ADD COLUMN IF NOT EXISTS kinder_id BIGINT
        """)
        _run("""
            CREATE UNIQUE INDEX IF NOT EXISTS objects_kinder_id_idx
                ON transient.objects(kinder_id)
                WHERE kinder_id IS NOT NULL
        """)
        _run("""
            CREATE INDEX IF NOT EXISTS objects_discovery_date_idx
                ON transient.objects(discovery_date DESC)
        """)
        _run("""
            CREATE INDEX IF NOT EXISTS objects_name_prefix_idx
                ON transient.objects(name_prefix)
        """)
        _run("""
            CREATE INDEX IF NOT EXISTS objects_type_idx
                ON transient.objects(type)
                WHERE type IS NOT NULL AND type != ''
        """)
        _run("""
            CREATE INDEX IF NOT EXISTS objects_last_phot_date_idx
                ON transient.objects(last_phot_date DESC)
        """)

        # obs.logs indexes — date index enables the sargable date-range filter
        _run("""
            CREATE INDEX IF NOT EXISTS obs_logs_date_idx
                ON obs.logs(date)
        """)
        _run("""
            CREATE INDEX IF NOT EXISTS obs_logs_name_idx
                ON obs.logs(name)
        """)

        # obs.targets index — speeds up active-only filtering
        _run("""
            CREATE INDEX IF NOT EXISTS obs_targets_active_idx
                ON obs.targets(active, name)
        """)

        # obs.direct_trigger_targets — Direct Trigger: a short-lived list for
        # changing tonight's plan, kept apart from the Daily Trigger targets.
        _run("""
            CREATE TABLE IF NOT EXISTS obs.direct_trigger_targets (
                id           SERIAL PRIMARY KEY,
                telescope    TEXT NOT NULL CHECK (telescope IN ('SLT', 'LOT')),
                name         TEXT NOT NULL,
                ra           TEXT NOT NULL,
                dec          TEXT NOT NULL,
                mag          TEXT,
                priority     TEXT NOT NULL DEFAULT 'Normal',
                note         TEXT,
                repeat_count INTEGER NOT NULL DEFAULT 0,
                program      TEXT,
                auto_exp     BOOLEAN NOT NULL DEFAULT TRUE,
                filters      JSONB,
                created_by   TEXT,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_sent_at TIMESTAMPTZ
            )
        """)

        # transient.objects — name lookup used by _resolve_obj_id_with_prefix
        _run("""
            CREATE UNIQUE INDEX IF NOT EXISTS objects_name_idx
                ON transient.objects(name)
        """)

        # Ensure tag always has a safe default even if an INSERT omits it.
        _run("""
            ALTER TABLE transient.objects
                ALTER COLUMN tag SET DEFAULT '{}'::text[]
        """)
        _run("""
            UPDATE transient.objects
               SET tag = '{}'::text[]
             WHERE tag IS NULL
        """)

        # cat.ned — NED cone-search result cache
        _run("""
            CREATE TABLE IF NOT EXISTS cat.ned (
                ned_id        SERIAL PRIMARY KEY,
                object_name   TEXT NOT NULL,
                ra_center     DOUBLE PRECISION NOT NULL,
                dec_center    DOUBLE PRECISION NOT NULL,
                radius_arcsec DOUBLE PRECISION NOT NULL DEFAULT 60,
                searched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                result_count  INT NOT NULL DEFAULT 0,
                results       JSONB NOT NULL DEFAULT '[]'::jsonb
            )
        """)
        _run("""
            CREATE UNIQUE INDEX IF NOT EXISTS cat_ned_object_radius_idx
                ON cat.ned (object_name, radius_arcsec)
        """)

        # transient.cross_matches — extra columns used by DETECT cross-matching
        # (previously ALTERed on every request in services/detect/detect_cross_match.py).
        _run("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE")
        _run("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_data JSONB")
        _run("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_ra DOUBLE PRECISION")
        _run("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_dec DOUBLE PRECISION")

        # transient.lsst_alerts — LSST objects (ALeRCE) near a Lens / DESI galaxy, kept
        # whether or not they are in TNS yet (app/services/lsst/alerts.py).
        _run("""
            CREATE TABLE IF NOT EXISTS transient.lsst_alerts (
                oid           BIGINT PRIMARY KEY,
                ra            DOUBLE PRECISION NOT NULL,
                dec           DOUBLE PRECISION NOT NULL,
                firstmjd      DOUBLE PRECISION,
                lastmjd       DOUBLE PRECISION,
                n_det         INT,
                class_name    TEXT,
                probability   DOUBLE PRECISION,
                lens_matches  JSONB NOT NULL DEFAULT '[]'::jsonb,
                desi_matches  JSONB NOT NULL DEFAULT '[]'::jsonb,
                n_lens        INT NOT NULL DEFAULT 0,
                n_desi        INT NOT NULL DEFAULT 0,
                best_sep      DOUBLE PRECISION,
                best_z        DOUBLE PRECISION,
                obj_id        BIGINT REFERENCES transient.objects(obj_id) ON DELETE SET NULL,
                tns_name      TEXT,
                tns_link      TEXT,
                first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        _run("CREATE INDEX IF NOT EXISTS lsst_alerts_firstmjd_idx ON transient.lsst_alerts (firstmjd)")
        _run("CREATE INDEX IF NOT EXISTS lsst_alerts_obj_idx ON transient.lsst_alerts (obj_id)")
        # Latest / brightest LSST point and their absolute magnitudes (DETECT's formula), kept
        # current by the watch whenever ALeRCE has a newer point (app/services/lsst/alerts.py).
        for col, typ in (("latest_mag", "DOUBLE PRECISION"), ("latest_filter", "TEXT"), ("latest_mjd", "DOUBLE PRECISION"),
                         ("peak_mag", "DOUBLE PRECISION"), ("peak_filter", "TEXT"), ("peak_mjd", "DOUBLE PRECISION"),
                         ("abs_latest", "DOUBLE PRECISION"), ("abs_peak", "DOUBLE PRECISION"),
                         ("z_used", "DOUBLE PRECISION"), ("z_source", "TEXT"), ("n_points", "INT"),
                         ("mags_lastmjd", "DOUBLE PRECISION"), ("mags_at", "TIMESTAMPTZ")):
            _run(f"ALTER TABLE transient.lsst_alerts ADD COLUMN IF NOT EXISTS {col} {typ}")
        # transient.lsst_lc_state — last ALeRCE lastmjd seen per TNS object, so the hourly
        # LSST light-curve refresh only re-downloads objects with new points.
        _run("""
            CREATE TABLE IF NOT EXISTS transient.lsst_lc_state (
                obj_id         BIGINT PRIMARY KEY REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
                oid            BIGINT NOT NULL,
                alerce_lastmjd DOUBLE PRECISION,
                n_points       INT,
                refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                error          TEXT
            )
        """)

        cur.close()
    except Exception as e:
        logger.warning("_ensure_extra_tables: %s", e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Shared SQL fragment — SELECT from transient.objects with backward-compat
# column aliases matching the old tns_objects schema expected by routes.
# ---------------------------------------------------------------------------

OBJECT_COMPAT_COLS = """
    o.obj_id,
    o.obj_id                                                               AS objid,
    o.kinder_id,
    o.name_prefix,
    o.name,
    o.ra,
    o.dec                                                                  AS declination,
    o.redshift,
    o.type,
    NULL::int                                                              AS typeid,
    o.report_group                                                         AS reporting_group,
    NULL::int                                                              AS reporting_groupid,
    o.source_group,
    NULL::int                                                              AS source_groupid,
    CASE WHEN o.discovery_date IS NOT NULL THEN
         to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day',
                 'YYYY-MM-DD HH24:MI:SS') END                              AS discoverydate,
    o.discovery_mag                                                        AS discoverymag,
    o.discovery_filter                                                     AS discmagfilter,
    o.discovery_filter                                                     AS filter,
    array_to_string(o.reporters, ', ')                                     AS reporters,
    CASE WHEN o.received_date IS NOT NULL THEN
         to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day',
                 'YYYY-MM-DD HH24:MI:SS') END                              AS time_received,
    COALESCE(o.internal_name, '') ||
      CASE WHEN o.other_name IS NOT NULL
           THEN ', ' || o.other_name ELSE '' END                          AS internal_names,
    o.discovery_ADS                                                        AS discovery_ads_bibcode,
    o.class_ADS                                                            AS class_ads_bibcodes,
    CASE WHEN o.creation_date IS NOT NULL THEN
         to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day',
                 'YYYY-MM-DD HH24:MI:SS') END                              AS creationdate,
    CASE WHEN o.last_phot_date IS NOT NULL THEN
         to_char(TIMESTAMP '1858-11-17' + o.last_phot_date * INTERVAL '1 day',
                 'YYYY-MM-DD HH24:MI:SS') END                              AS last_photometry_date,
    CASE WHEN o.last_modified_date IS NOT NULL THEN
         to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day',
                 'YYYY-MM-DD HH24:MI:SS') END                              AS lastmodified,
    o.brightest_mag,
    o.brightest_abs_mag,
    o.pin::int                                                             AS pin,
    array_to_string(o.tag, ', ')                                           AS tags,
    CASE o.status
        WHEN 'Finish'    THEN 'finished'
        WHEN 'Follow-up' THEN 'followup'
        WHEN 'Snoozed'   THEN 'snoozed'
        ELSE 'object'
    END                                                                    AS tag,
    o.status,
    CASE WHEN o.status NOT IN ('Snoozed') THEN 1 ELSE 0 END               AS inbox,
    CASE WHEN o.status = 'Snoozed'        THEN 1 ELSE 0 END               AS snoozed,
    CASE WHEN o.status = 'Follow-up'      THEN 1 ELSE 0 END               AS follow,
    CASE WHEN o.status = 'Finish'         THEN 1 ELSE 0 END               AS finish_follow,
    o.permission,
    o.groups
"""
