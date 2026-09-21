| Column             | Type             | Describe                                                               |
| ------------------ | ---------------- | ---------------------------------------------------------------------- |
| obj_id             | bigint           | Object ID in the database, PRIMARY KEY -> year+count -> 2026000001 (zzzz is 475254) |
| status             | text             | Inbox / Snoozed / Follow-up / Finish                                   |
| pin                | bool             | True / False                                                           |
| name_prefix        | text             | SN / AT / FRB / TDE .....                                              |
| name               | text             | 2026A, 2026gzf ....                                                    |
| internal_name      | text             | ATLAS26aaa ...                                                         |
| other_name         | text             | EP260321a ...                                                          |
| tag                | text[]           | {Lens, Possible Lens, ...}                                                          |
| ra                 | double precision | 123.456                                                                |
| dec                | double precision | -25.345                                                                |
| redshift           | double precision | 1.2345                                                                 |
| type               | text             | SN Ia, SN IIb, TDE                                                     |
| report_group       | text             | ATLAS, ZTF, Lasair                                                     |
| source_group       | text             | ATLAS, ZTF                                                             |
| discovery_date     | double precision | save in MJD                                                            |
| discovery_mag      | double precision | 19.78                                                                  |
| discovery_mag_err  | double precision | 0.02                                                                   |
| discovery_filter   | text             | r                                                                      |
| reporters          | text[]           | {Alex Lee, YuHsing Lee, ...}                                                        |
| received_date      | double precision | save in MJD                                                            |
| creation_date      | double precision | save in MJD                                                            |
| discovery_ADS      | text             | ADS code                                                               |
| class_ADS          | text             | ADS code                                                               |
| last_phot_date     | double precision | save in MJD                                                            |
| last_modified_date | double precision | save in MJD                                                            |
| brightest_mag      | double precision | 16.789                                                                 |
| brightest_abs_mag  | double precision | -22.789                                                                |
| host_name          | text             | NED host galaxy name (set via NED cone search)                         |
| permission         | text             | public, login, groups. Default set as "public"                         |
| groups             | int[]            | {group_id, ...}. Default set as "{}"                                   |

## Indexes

| Index Name                     | Type    | Columns          | Purpose                                     |
| ------------------------------ | ------- | ---------------- | ------------------------------------------- |
| objects_pkey                   | B-tree  | obj_id           | PRIMARY KEY                                 |
| objects_name_uniq              | B-tree  | name             | UNIQUE, fast lookup by TNS name             |
| objects_status_idx             | B-tree  | status           | filter by Inbox / Follow-up ...             |
| objects_ra_dec_idx             | B-tree  | (ra, dec)        | spatial bounding box query                  |
| objects_tag_idx                | GIN     | tag              | array search: ANY(tag) = 'Lens'             |
| objects_groups_idx             | GIN     | groups           | permission filter: group_id = ANY(groups)   |
| objects_last_modified_idx      | B-tree  | last_modified_date | cache invalidation, recent changes query  |

