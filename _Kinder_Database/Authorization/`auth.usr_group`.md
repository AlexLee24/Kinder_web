| Column   | Type                  | Describe                     |
| -------- | --------------------- | ---------------------------- |
| usr_id     | int                   | users id, COMPOSITE PK (usr_id, group_id)  |
| group_id   | int                   | group id, COMPOSITE PK (usr_id, group_id)  |
| status     | text                  | 'request' / 'joined' / 'rejected'  |
| created_at | timestamp w/ timezone | created at                         |