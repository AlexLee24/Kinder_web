| Column     | Type  | Describe                                                               |
| ---------- | --------- | ---------------------------------------------------------------------- |
| image_id   | bigserial | image id, PRIMARY KEY                                                  |
| obj_id     | bigint    | Object ID in the database -> year+count -> 2026000001 (zzzz is 475254) |
| name       | text      | 2026A, 2026gzf .... (denormalized, FK via obj_id)                      |
| image_data | bytea | image                                                                  |
| source     | text  | DESI ...                                                               |
