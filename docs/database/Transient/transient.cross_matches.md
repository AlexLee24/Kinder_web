| Column        | Type                  | Describe                                                               |
| ------------- | --------------------- | ---------------------------------------------------------------------- |
| match_id      | bigserial             | cross match id, PRIMARY KEY                                            |
| obj_id        | bigint                | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name          | text                  | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| catalog       | text                  | DESI, Lens_XXXX, AGN_XXXX                                              |
| separation    | double precision      | arcsec                                                                 |
| redshift      | double precision      | redshift from DESI                                                     |
| is_host       | bool                  | True / False                                                           |
| updated_date  | timestamp w/ timezone | 2026-01-06 03:22:09.623438+08                                          |
| note          | text                  | Note, e.g., Lens redshift, grade ....                                  |
| run_date      | timestamp w/ timezone | run sync time                                                          |
| status        | text                  | Success, Error, Retry-Success ...                                      |
| error_message | text                  | Error message                                                          |

## Indexes

| Index Name                    | Type   | Columns              | Purpose                                     |
| ----------------------------- | ------ | -------------------- | ------------------------------------------- |
| cross_matches_pkey            | B-tree | match_id             | PRIMARY KEY                                 |
| cross_matches_obj_catalog_idx | B-tree | (obj_id, catalog)    | get all matches for an object by catalog    |
| cross_matches_is_host_idx     | B-tree | (obj_id, is_host)    | find host galaxy quickly                    |

