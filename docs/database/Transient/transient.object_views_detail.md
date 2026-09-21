This table only needs to save XX days of data

| Column    | Type                  | Describe                                                               |
| --------- | --------------------- | ---------------------------------------------------------------------- |
| view_id   | bigserial             | view detail id, PRIMARY KEY                                            |
| obj_id    | bigint                | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name      | text                  | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| usr_id    | int                   | user that view this object                                             |
| view_time | timestamp w/ timezone | viewing time                                                           |

## Indexes

| Index Name                         | Type   | Columns            | Purpose                                      |
| ---------------------------------- | ------ | ------------------ | -------------------------------------------- |
| object_views_detail_pkey           | B-tree | view_id            | PRIMARY KEY                                  |
| object_views_detail_view_time_idx  | B-tree | view_time          | TTL cleanup: DELETE WHERE view_time < cutoff |
| object_views_detail_obj_usr_idx    | B-tree | (obj_id, usr_id)   | dedup check before inserting new view        |
