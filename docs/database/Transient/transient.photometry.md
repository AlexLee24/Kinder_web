| Column     | Type             | Describe                                                               |     |
| ---------- | ---------------- | ---------------------------------------------------------------------- | --- |
| phot_id    | bigserial        | photometry id, PRIMARY KEY                                             |     |
| obj_id     | bigint           | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |     |
| name       | text             | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |     |
| MJD        | double precision | 65535.213                                                              |     |
| mag        | double precision | 16.789                                                                 |     |
| mag_err    | double precision | 0.002                                                                  |     |
| filter     | text             | r                                                                      |     |
| source     | text             | ATLAS, LOT, SLT                                                        |     |
| permission | text             | default, public, login, groups. Default set as "default"               |     |
| groups     | int[]            | {group_id, ...}. Default set as "{}"                                   |     |

## Indexes

| Index Name             | Type   | Columns       | Purpose                                    |
| ---------------------- | ------ | ------------- | ------------------------------------------ |
| photometry_pkey        | B-tree | phot_id       | PRIMARY KEY                                |
| photometry_obj_mjd_idx | B-tree | (obj_id, MJD) | get light curve for object, sorted by time |
| photometry_source_idx  | B-tree | source        | filter by ATLAS / LOT / SLT                |
| photometry_groups_idx  | GIN    | groups        | permission filter: group_id = ANY(groups)  |

