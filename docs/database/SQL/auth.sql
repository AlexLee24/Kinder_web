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
    -- Legacy plaintext column: always NULL now (migrated to api_key_hash at startup).
    api_key     TEXT UNIQUE,
    api_key_requested_at TIMESTAMPTZ,
    -- API key storage: sha256 hex of the key + its last 4 characters. The key
    -- itself is shown once when issued and never stored.
    api_key_hash         TEXT,
    api_key_hint         TEXT,
    api_key_created_at   TIMESTAMPTZ,
    api_key_last_used_at TIMESTAMPTZ,
    -- Google account id ("sub") bound at the first Google sign-in.
    google_sub           TEXT,
    -- Direct-login name for admin-created accounts ([A-Za-z0-9._-]{3,32}).
    -- Accounts created without an email store <username>@users.invalid in email.
    username             TEXT,
    -- Password login for admin-created accounts (NULL = Google login only).
    -- Werkzeug scrypt hash; never selected into user dicts / sessions.
    password_hash        TEXT,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    password_changed_at  TIMESTAMPTZ,
    -- Bumped on password change/reset so existing sessions are logged out.
    session_version      INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX users_api_key_hash_idx ON auth.users(api_key_hash) WHERE api_key_hash IS NOT NULL;
CREATE UNIQUE INDEX users_google_sub_idx ON auth.users(google_sub) WHERE google_sub IS NOT NULL;
CREATE UNIQUE INDEX users_username_lower_idx ON auth.users(lower(username)) WHERE username IS NOT NULL;

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
