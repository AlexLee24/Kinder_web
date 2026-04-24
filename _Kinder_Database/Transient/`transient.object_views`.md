| Column    | Type                  | Describe                                                               |
| --------- | --------------------- | ---------------------------------------------------------------------- |
| obj_id    | bigint                | Object ID in the database -> year+count -> 2026000001, PRIMARY KEY     |
| name      | text                  | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| counts    | int                   | numbers of view                                                        |
| last_view | timestamp w/ timezone | last view time                                                         |