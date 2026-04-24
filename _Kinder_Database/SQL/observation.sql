-- ============================================================
-- Schema: obs
-- Depends on: auth (auth.users must exist first)
-- ============================================================

CREATE SCHEMA IF NOT EXISTS obs;

-- ------------------------------------------------------------
-- obs.targets
-- Active observation target list
-- ------------------------------------------------------------
CREATE TABLE obs.targets (
    target_id   SERIAL PRIMARY KEY,
    active      BOOL NOT NULL DEFAULT TRUE,
    name        TEXT NOT NULL UNIQUE,   -- TNS name, no prefix, e.g. 2026A
    mag         DOUBLE PRECISION,
    ra          DOUBLE PRECISION NOT NULL,
    dec         DOUBLE PRECISION NOT NULL,
    telescope   TEXT NOT NULL,          -- LOT, SLT
    program     TEXT,                   -- R01, R07 ...
    priority    TEXT NOT NULL DEFAULT 'Normal'
                    CHECK (priority IN ('Urgent', 'High', 'Normal', 'Filler')),
    plan_filter TEXT[]  NOT NULL DEFAULT '{}',  -- {rp, gp}
    plan_count  INT[]   NOT NULL DEFAULT '{}',  -- seconds per filter
    plan_time   INT[]   NOT NULL DEFAULT '{}',  -- minutes per filter
    repeat      INT NOT NULL DEFAULT 0,
    plan        TEXT,                   -- plan note to staff
    note        TEXT,                   -- note to group
    create_by   INT REFERENCES auth.users(usr_id) ON DELETE SET NULL
);

CREATE INDEX obs_targets_active_tel_idx  ON obs.targets (active, telescope);
CREATE INDEX obs_targets_priority_idx    ON obs.targets (priority);

-- ------------------------------------------------------------
-- obs.logs
-- One row per observation attempt
-- ------------------------------------------------------------
CREATE TABLE obs.logs (
    log_id          SERIAL PRIMARY KEY,
    target_id       INT REFERENCES obs.targets(target_id) ON DELETE SET NULL,
    date            TIMESTAMPTZ NOT NULL,
    name            TEXT,               -- denormalized from obs.targets.name
    telescope       TEXT NOT NULL,
    program         TEXT,
    priority        TEXT CHECK (priority IN ('Urgent', 'High', 'Normal', 'Filler')),
    repeat          INT NOT NULL DEFAULT 0,
    trigger_by      INT REFERENCES auth.users(usr_id) ON DELETE SET NULL,
    trigger         BOOL NOT NULL DEFAULT FALSE,
    observed        BOOL NOT NULL DEFAULT FALSE,
    trigger_filter  TEXT[] NOT NULL DEFAULT '{}',
    trigger_count   INT[]  NOT NULL DEFAULT '{}',   -- seconds
    trigger_time    INT[]  NOT NULL DEFAULT '{}',   -- minutes
    observed_filter TEXT[] NOT NULL DEFAULT '{}',
    observed_count  INT[]  NOT NULL DEFAULT '{}',   -- seconds
    observed_time   INT[]  NOT NULL DEFAULT '{}'    -- minutes
);

CREATE INDEX obs_logs_target_date_idx ON obs.logs (target_id, date);
CREATE INDEX obs_logs_telescope_idx   ON obs.logs (telescope, date);
