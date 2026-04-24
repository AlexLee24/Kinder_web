| Column    | Type                  | Describe                                                               |
| --------- | --------------------- | ---------------------------------------------------------------------- |
| obj_id    | bigint                | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name      | text                  | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| usr_id    | int                   | save by which user, COMPOSITE PK (obj_id, usr_id)                     |
| save_date | timestamp w/ timezone | the time save into custom target list                                  |
| note      | text                  | note                                                                   |