| Column      | Type                  | Describe                                          |
| ----------- | --------------------- | ------------------------------------------------- |
| usr_id      | serial                | users id, PRIMARY KEY, can NOT be changed         |
| email       | text                  | gmail acc                                         |
| picture_url | text                  | image from google                                 |
| name        | text                  | user name, can be changed, NOT NULL               |
| roles       | int                   | 0 = guest, 1 = user, 50 = admin, 99 = super admin |
| last_login  | timestamp w/ timezone | usr last login to Kinder Marshal pages time       |
| join_date   | timestamp w/ timezone | usr when join to Kinder Marshal pages time        |
| api_key     | text                  | usr api key, save "hash", UNIQUE                  |
