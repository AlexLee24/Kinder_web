-- ============================================================
-- Schema: transient
-- Depends on: auth (auth.users, auth.groups must exist first)
-- ============================================================

CREATE SCHEMA IF NOT EXISTS transient;

-- ------------------------------------------------------------
-- transient.default_permissions
-- Default visibility setting per data source (LOT, SLT, ...)
-- ------------------------------------------------------------
CREATE TABLE transient.default_permissions (
    source          TEXT PRIMARY KEY,   -- LOT, SLT, ATLAS ...
    permissions_set TEXT NOT NULL DEFAULT 'public'
                        CHECK (permissions_set IN ('public', 'login', 'groups')),
    groups          INT[] NOT NULL DEFAULT '{}'
);

-- ------------------------------------------------------------
-- transient.objects
-- Core transient object table (imported from TNS / internal)
-- obj_id format: year * 1_000_000 + count, e.g. 2026000001
-- ------------------------------------------------------------
CREATE TABLE transient.objects (
    obj_id              BIGINT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'Inbox'
                            CHECK (status IN ('Inbox', 'Snoozed', 'Follow-up', 'Finish')),
    pin                 BOOL NOT NULL DEFAULT FALSE,
    name_prefix         TEXT,                   -- SN, AT, FRB, TDE ...
    name                TEXT NOT NULL UNIQUE,   -- e.g. 2026A  (no prefix)
    internal_name       TEXT,                   -- e.g. ATLAS26aaa
    other_name          TEXT,                   -- e.g. EP260321a
    tag                 TEXT[] NOT NULL DEFAULT '{}',
    ra                  DOUBLE PRECISION NOT NULL,
    dec                 DOUBLE PRECISION NOT NULL,
    redshift            DOUBLE PRECISION,
    type                TEXT,                   -- SN Ia, SN IIb, TDE ...
    report_group        TEXT,                   -- ATLAS, ZTF, Lasair
    source_group        TEXT,                   -- ATLAS, ZTF
    discovery_date      DOUBLE PRECISION,       -- MJD
    discovery_mag       DOUBLE PRECISION,
    discovery_mag_err   DOUBLE PRECISION,
    discovery_filter    TEXT,
    reporters           TEXT[] NOT NULL DEFAULT '{}',
    received_date       DOUBLE PRECISION,       -- MJD
    creation_date       DOUBLE PRECISION,       -- MJD
    discovery_ADS       TEXT,
    class_ADS           TEXT,
    last_phot_date      DOUBLE PRECISION,       -- MJD
    last_modified_date  DOUBLE PRECISION,       -- MJD
    brightest_mag       DOUBLE PRECISION,
    brightest_abs_mag   DOUBLE PRECISION,    host_name           TEXT,                   -- NED host galaxy name    permission          TEXT NOT NULL DEFAULT 'public'
                            CHECK (permission IN ('public', 'login', 'groups')),
    groups              INT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX objects_status_idx        ON transient.objects (status);
CREATE INDEX objects_ra_dec_idx        ON transient.objects (ra, dec);
CREATE INDEX objects_tag_idx           ON transient.objects USING GIN (tag);
CREATE INDEX objects_groups_idx        ON transient.objects USING GIN (groups);
CREATE INDEX objects_last_modified_idx ON transient.objects (last_modified_date);

-- ------------------------------------------------------------
-- transient.photometry
-- ------------------------------------------------------------
CREATE TABLE transient.photometry (
    phot_id     BIGSERIAL PRIMARY KEY,
    obj_id      BIGINT NOT NULL
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    "MJD"       DOUBLE PRECISION NOT NULL,
    mag         DOUBLE PRECISION,
    mag_err     DOUBLE PRECISION,
    filter      TEXT,
    source      TEXT,
    permission  TEXT NOT NULL DEFAULT 'default'
                    CHECK (permission IN ('default', 'public', 'login', 'groups')),
    groups      INT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX photometry_obj_mjd_idx ON transient.photometry (obj_id, "MJD");
CREATE INDEX photometry_source_idx  ON transient.photometry (source);
CREATE INDEX photometry_groups_idx  ON transient.photometry USING GIN (groups);

-- ------------------------------------------------------------
-- transient.spectroscopy
-- ------------------------------------------------------------
CREATE TABLE transient.spectroscopy (
    spec_id     BIGSERIAL PRIMARY KEY,
    obj_id      BIGINT NOT NULL
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    "MJD"       DOUBLE PRECISION NOT NULL,
    wavelength  DOUBLE PRECISION NOT NULL,  -- Angstrom
    intensity   DOUBLE PRECISION,
    source      TEXT,
    permission  TEXT NOT NULL DEFAULT 'default'
                    CHECK (permission IN ('default', 'public', 'login', 'groups')),
    groups      INT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX spectroscopy_obj_mjd_idx ON transient.spectroscopy (obj_id, "MJD");
CREATE INDEX spectroscopy_groups_idx  ON transient.spectroscopy USING GIN (groups);

-- ------------------------------------------------------------
-- transient.cross_matches
-- Results from DETECT cross-match pipeline
-- ------------------------------------------------------------
CREATE TABLE transient.cross_matches (
    match_id        BIGSERIAL PRIMARY KEY,
    obj_id          BIGINT NOT NULL
                        REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name            TEXT,               -- denormalized cache
    catalog         TEXT NOT NULL,      -- DESI, Lens_XXXX, AGN_XXXX
    separation      DOUBLE PRECISION,   -- arcsec
    redshift        DOUBLE PRECISION,
    is_host         BOOL NOT NULL DEFAULT FALSE,
    updated_date    TIMESTAMPTZ,
    note            TEXT,
    run_date        TIMESTAMPTZ,
    status          TEXT,               -- Success, Error, Retry-Success
    error_message   TEXT
);

CREATE INDEX cross_matches_obj_catalog_idx ON transient.cross_matches (obj_id, catalog);
CREATE INDEX cross_matches_is_host_idx     ON transient.cross_matches (obj_id, is_host);

-- ------------------------------------------------------------
-- transient.target_images
-- BYTEA image storage (DESI cutouts, etc.)
-- Consider object storage (S3/MinIO) if image volume is large
-- ------------------------------------------------------------
CREATE TABLE transient.target_images (
    image_id    BIGSERIAL PRIMARY KEY,
    obj_id      BIGINT NOT NULL
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    image_data  BYTEA NOT NULL,
    source      TEXT                    -- DESI ...
);

CREATE INDEX target_images_obj_idx ON transient.target_images (obj_id);

-- ------------------------------------------------------------
-- transient.download_logs
-- TNS sync history
-- ------------------------------------------------------------
CREATE TABLE transient.download_logs (
    log_id          BIGSERIAL PRIMARY KEY,
    download_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
    obj_import      INT NOT NULL DEFAULT 0,
    obj_update      INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,      -- Success, Error, Retry-Success
    error_message   TEXT,
    filename        TEXT                -- e.g. tns_public_objects_2026_01.csv
);

-- ------------------------------------------------------------
-- transient.custom_targets
-- Per-user saved object list
-- Composite PK: (obj_id, usr_id)
-- ------------------------------------------------------------
CREATE TABLE transient.custom_targets (
    obj_id      BIGINT NOT NULL
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    usr_id      INT NOT NULL
                    REFERENCES auth.users(usr_id) ON DELETE CASCADE,
    save_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
    note        TEXT,
    PRIMARY KEY (obj_id, usr_id)
);

-- ------------------------------------------------------------
-- transient.object_views
-- Aggregated view counter per object
-- ------------------------------------------------------------
CREATE TABLE transient.object_views (
    obj_id      BIGINT PRIMARY KEY
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    counts      INT NOT NULL DEFAULT 0,
    last_view   TIMESTAMPTZ
);

-- ------------------------------------------------------------
-- transient.object_views_detail
-- Rolling window detail log (e.g. 30 days)
-- Periodically prune: DELETE WHERE view_time < now() - INTERVAL 'XX days'
-- ------------------------------------------------------------
CREATE TABLE transient.object_views_detail (
    view_id     BIGSERIAL PRIMARY KEY,
    obj_id      BIGINT NOT NULL
                    REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name        TEXT,                   -- denormalized cache
    usr_id      INT
                    REFERENCES auth.users(usr_id) ON DELETE SET NULL,
    view_time   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX object_views_detail_view_time_idx ON transient.object_views_detail (view_time);
CREATE INDEX object_views_detail_obj_usr_idx   ON transient.object_views_detail (obj_id, usr_id);

-- ------------------------------------------------------------
-- transient.comments
-- ------------------------------------------------------------
CREATE TABLE transient.comments (
    comment_id      BIGSERIAL PRIMARY KEY,
    obj_id          BIGINT NOT NULL
                        REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
    name            TEXT,               -- denormalized cache
    usr_id          INT
                        REFERENCES auth.users(usr_id) ON DELETE SET NULL,
    comment         TEXT NOT NULL,
    comment_time    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX comments_obj_idx ON transient.comments (obj_id);
