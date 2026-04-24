-- ============================================================
-- Schema: auth
-- ============================================================

CREATE SCHEMA IF NOT EXISTS auth;

-- ------------------------------------------------------------
-- auth.users
-- ------------------------------------------------------------
CREATE TABLE auth.users (
    usr_id      SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    picture_url TEXT,
    name        TEXT NOT NULL,
    roles       INT NOT NULL DEFAULT 0
                    CHECK (roles IN (0, 1, 50, 99)),
                    -- 0=guest, 1=user, 50=admin, 99=super_admin
    last_login  TIMESTAMPTZ,
    join_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
    api_key     TEXT UNIQUE
);

-- ------------------------------------------------------------
-- auth.images
-- One row per user (1:1 with auth.users)
-- ------------------------------------------------------------
CREATE TABLE auth.images (
    usr_id      INT PRIMARY KEY
                    REFERENCES auth.users(usr_id) ON DELETE CASCADE,
    image_data  BYTEA NOT NULL
);

-- ------------------------------------------------------------
-- auth.groups
-- ------------------------------------------------------------
CREATE TABLE auth.groups (
    group_id    SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    joinable    BOOL NOT NULL DEFAULT FALSE,
    create_by   INT REFERENCES auth.users(usr_id) ON DELETE SET NULL,
    manager     INT REFERENCES auth.users(usr_id) ON DELETE SET NULL
);

-- ------------------------------------------------------------
-- auth.usr_group
-- Composite PK: (usr_id, group_id)
-- ------------------------------------------------------------
CREATE TABLE auth.usr_group (
    usr_id      INT NOT NULL
                    REFERENCES auth.users(usr_id) ON DELETE CASCADE,
    group_id    INT NOT NULL
                    REFERENCES auth.groups(group_id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'request'
                    CHECK (status IN ('request', 'joined', 'rejected')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (usr_id, group_id)
);
