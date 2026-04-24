| Column     | Type             | Describe                                                               |
| ---------- | ---------------- | ---------------------------------------------------------------------- |
| spec_id    | bigserial        | spectroscopy id, PRIMARY KEY                                           |
| obj_id     | bigint           | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name       | text             | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| MJD        | double precision | 65535.213                                                              |
| wavelength | double precision | in Angstrom                                                            |
| intensity  | double precision | 100                                                                    |
| source     | text             | ATLAS, LOT, SLT                                                        |
| permission | text             | default, public, login, groups. Default set as "default"               |
| groups     | int[]            | {group_id, ...}. Default set as "{}"                                   |                                      |

## Indexes

| Index Name               | Type   | Columns        | Purpose                                          |
| ------------------------ | ------ | -------------- | ------------------------------------------------ |
| spectroscopy_pkey        | B-tree | spec_id        | PRIMARY KEY                                      |
| spectroscopy_obj_mjd_idx | B-tree | (obj_id, MJD)  | get spectra for object, sorted by epoch          |
| spectroscopy_groups_idx  | GIN    | groups         | permission filter: group_id = ANY(groups)        |

