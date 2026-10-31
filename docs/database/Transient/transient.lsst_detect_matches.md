Written by `app/services/lsst/detect.py` (DETECT on LSST alerts): DETECT's own DESI (ZWARN = 0 only) and Lens cross-match of each alert, after rule v1 (DLR). Same `match_data` as `transient.cross_matches`; a reviewer's choice on /detect/lsst/review is kept in `match_data.host_user` / `host_user_by` / `host_user_at` and re-applied on every re-screen. Rows are upserted by `(oid, crossmatch_uid)`, so `match_id` and `flag` survive re-runs.

| Column         | Type             | Describe                                                   |
| -------------- | ---------------- | ---------------------------------------------------------- |
| match_id       | bigserial        | PRIMARY KEY                                                |
| oid            | bigint           | transient.lsst_alerts.oid (ON DELETE CASCADE)              |
| crossmatch_uid | text             | `LSST-<oid>\|<catalog>\|<candidate key>`, UNIQUE with oid    |
| catalog        | text             | DESI or Lens_<origin catalogue>                            |
| separation     | double precision | arcsec                                                     |
| is_host        | boolean          | host by rule v1, or chosen by a reviewer                   |
| redshift       | double precision | candidate z                                                |
| match_ra / match_dec | double precision | candidate position (deg)                             |
| match_data     | jsonb            | catalogue row + host-rule fields (d_dlr, host_rank, ...)    |
| flag           | boolean          | reviewer's star                                            |
| updated_date   | timestamptz      | last screen                                                |
