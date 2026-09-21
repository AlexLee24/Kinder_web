| Column       | Type                  | Describe                                                               |
| ------------ | --------------------- | ---------------------------------------------------------------------- |
| comment_id   | bigserial             | comment id, PRIMARY KEY                                                |
| obj_id       | bigint                | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name         | text                  | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| usr_id       | int                   | comment by who                                                         |
| comment      | text                  | comment                                                                |
| comment_time | timestamp w/ timezone | comment time                                                           |