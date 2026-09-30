| Column      | Type                  | Describe                                          |
| ----------- | --------------------- | ------------------------------------------------- |
| usr_id      | serial                | users id, PRIMARY KEY, can NOT be changed         |
| email       | text                  | gmail acc                                         |
| picture_url | text                  | image from google                                 |
| name        | text                  | user name, can be changed, NOT NULL               |
| roles       | int                   | 0 = guest, 1 = user, 50 = admin, 99 = super admin |
| last_login  | timestamp w/ timezone | usr last login to Kinder Marshal pages time       |
| join_date   | timestamp w/ timezone | usr when join to Kinder Marshal pages time        |
| api_key     | text                  | legacy plaintext key column, always NULL (migrated to api_key_hash) |
| api_key_hash | text                 | sha256 hex of the user's API key, UNIQUE (partial) |
| api_key_hint | text                 | last 4 characters of the key (display only)       |
| api_key_created_at | timestamp w/ timezone | when the current key was issued           |
| api_key_last_used_at | timestamp w/ timezone | last API use (updated at most once/minute) |
| google_sub  | text                  | Google account id bound at first Google login, UNIQUE (partial) |
| username    | text                  | direct-login name, UNIQUE on lower(username) (partial) |
