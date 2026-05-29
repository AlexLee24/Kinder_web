"""Kinder Database Package — connection pool for the unified 'Kinder' PostgreSQL DB.

Schema layout:
  auth.*       → auth.py
  transient.*  → transient.py
  obs.*        → obs.py
  cat.*        → catalog.py
"""

import logging
import os
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '..', '..', '..', 'kinder.env')
load_dotenv(dotenv_path, override=True)

DB_HOST     = os.getenv("PG_HOST", "localhost")
DB_PORT     = os.getenv("PG_PORT", "5432")
DB_USER     = os.getenv("PG_USER", "postgres")
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_NAME     = "Kinder"

_DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Smaller pool in DEBUG mode so we don't waste connections during development
_POOL_MIN = 1  if _DEBUG else 2
_POOL_MAX = 10 if _DEBUG else 60

logger = logging.getLogger(__name__)

_connection_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_connection_pool(minconn: int = _POOL_MIN, maxconn: int = _POOL_MAX):
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
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
    return _connection_pool


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
        status = conn.status   # psycopg2.extensions.STATUS_*
        if status in (
            psycopg2.extensions.STATUS_IN_TRANSACTION,   # = 2
            psycopg2.extensions.STATUS_IN_ERROR,         # = 4
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


def get_tns_db_connection() -> '_PooledConn':
    """Return a raw pooled connection.  Caller MUST call conn.close() to
    return it to the pool (close() is intercepted — it does putconn, not
    actual socket close)."""
    p = init_connection_pool()
    return _PooledConn(p.getconn(), p)


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
    conn = p.getconn()
    # Discard a connection that the server closed while it sat in the pool.
    if conn.closed:
        p.putconn(conn, close=True)
        conn = p.getconn()
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


def check_db_connection() -> bool:
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        conn.close()
        logger.info("Connected to Kinder DB at %s:%s", DB_HOST, DB_PORT)
        return True
    except Exception as e:
        logger.error("Kinder DB connection failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Extra tables not in the original Kinder schema DDL (backward-compat needs)
# ---------------------------------------------------------------------------

def _ensure_extra_tables():
    """Create supplementary tables used by app logic that are absent from the
    core Kinder schema DDL.  All created under appropriate schemas."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        cur = conn.cursor()

        # auth.invitations — invitation tokens for new user sign-up
        cur.execute("""
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.system_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)

        # transient.object_source_permissions — per-object per-source visibility
        cur.execute("""
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
        cur.execute("""
            DO $$ BEGIN
                BEGIN
                    ALTER TABLE transient.photometry
                        ADD CONSTRAINT phot_uniq UNIQUE (obj_id, "MJD", filter, source);
                EXCEPTION WHEN duplicate_table THEN NULL;
                END;
            END $$
        """)

        # Unique constraint for obs.logs upsert
        cur.execute("""
            DO $$ BEGIN
                BEGIN
                    ALTER TABLE obs.logs
                        ADD CONSTRAINT obs_logs_target_date_uniq UNIQUE (target_id, date);
                EXCEPTION WHEN duplicate_table THEN NULL;
                END;
            END $$
        """)

        # kinder_id — internal sequential ID: year*1_000_000 + letter_rank
        cur.execute("""
            ALTER TABLE transient.objects
                ADD COLUMN IF NOT EXISTS kinder_id BIGINT
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS objects_kinder_id_idx
                ON transient.objects(kinder_id)
                WHERE kinder_id IS NOT NULL
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS objects_discovery_date_idx
                ON transient.objects(discovery_date DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS objects_name_prefix_idx
                ON transient.objects(name_prefix)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS objects_type_idx
                ON transient.objects(type)
                WHERE type IS NOT NULL AND type != ''
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS objects_last_phot_date_idx
                ON transient.objects(last_phot_date DESC)
        """)

        # obs.logs indexes — date index enables the sargable date-range filter
        cur.execute("""
            CREATE INDEX IF NOT EXISTS obs_logs_date_idx
                ON obs.logs(date)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS obs_logs_name_idx
                ON obs.logs(name)
        """)

        # obs.targets index — speeds up active-only filtering
        cur.execute("""
            CREATE INDEX IF NOT EXISTS obs_targets_active_idx
                ON obs.targets(active, name)
        """)

        # transient.objects — name lookup used by _resolve_obj_id_with_prefix
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS objects_name_idx
                ON transient.objects(name)
        """)

        # Ensure tag always has a safe default even if an INSERT omits it.
        cur.execute("""
            ALTER TABLE transient.objects
                ALTER COLUMN tag SET DEFAULT '{}'::text[]
        """)
        cur.execute("""
            UPDATE transient.objects
               SET tag = '{}'::text[]
             WHERE tag IS NULL
        """)

        # cat.ned — NED cone-search result cache
        cur.execute("""
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
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS cat_ned_object_radius_idx
                ON cat.ned (object_name, radius_arcsec)
        """)

        conn.commit()
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
