-- ============================================================
-- Schema: cat
-- ============================================================

CREATE SCHEMA IF NOT EXISTS cat;

-- ------------------------------------------------------------
-- cat.desi
-- Source: DESI survey, TARGETID is native 64-bit integer
-- ------------------------------------------------------------
CREATE TABLE cat.desi (
    desi_target_id  BIGINT PRIMARY KEY,
    ra              DOUBLE PRECISION NOT NULL,
    dec             DOUBLE PRECISION NOT NULL,
    redshift        DOUBLE PRECISION,
    redshift_err    DOUBLE PRECISION,
    delta_chi_2     DOUBLE PRECISION,
    zwarn           INT   -- 0 = clean, 1 = ZWARN flag
);

CREATE INDEX cat_desi_ra_dec_idx ON cat.desi (ra, dec);

-- ------------------------------------------------------------
-- cat.lens
-- Combined lens galaxy catalogue (multiple sources)
-- ------------------------------------------------------------
CREATE TABLE cat.lens (
    lens_id          SERIAL PRIMARY KEY,
    ra               DOUBLE PRECISION NOT NULL,
    dec              DOUBLE PRECISION NOT NULL,
    z_lens           DOUBLE PRECISION,
    z_source         DOUBLE PRECISION,
    lens_probability DOUBLE PRECISION,
    lens_grade       TEXT,
    known            TEXT CHECK (known IN ('known', 'unknown', 'candidate')),
    reference        TEXT  -- source catalogue name
);

CREATE INDEX cat_lens_ra_dec_idx ON cat.lens (ra, dec);
