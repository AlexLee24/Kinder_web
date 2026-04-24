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

logger = logging.getLogger(__name__)

_connection_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_connection_pool(minconn: int = 2, maxconn: int = 60):
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=DB_HOST, port=int(DB_PORT),
            database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        _ensure_extra_tables()
        logger.info("Kinder connection pool initialised (%d-%d)", minconn, maxconn)
    return _connection_pool


class _PooledConn:
    """Wraps a pooled psycopg2 connection so that close() returns it to the pool."""
    __slots__ = ('_conn', '_pool')

    def __init__(self, conn, pool):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_pool', pool)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_conn'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_conn'), name, value)

    def close(self):
        pool = object.__getattribute__(self, '_pool')
        conn = object.__getattribute__(self, '_conn')
        pool.putconn(conn)


def get_tns_db_connection() -> '_PooledConn':
    """Return a raw pooled connection.  Caller MUST call conn.close() to
    return it to the pool (close() is intercepted — it does putconn, not
    actual socket close)."""
    p = init_connection_pool()
    return _PooledConn(p.getconn(), p)


@contextmanager
def get_db_connection():
    """Yield a pooled psycopg2 connection; returns it to the pool on exit."""
    p = init_connection_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
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

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("_ensure_extra_tables: %s", e)


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
