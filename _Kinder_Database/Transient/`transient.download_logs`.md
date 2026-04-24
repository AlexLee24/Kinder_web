| Column        | Type                  | Describe                             |
| ------------- | --------------------- | ------------------------------------ |
| log_id        | bigserial             | log id, PRIMARY KEY                  |
| download_date | timestamp w/ timezone | run sync time                        |
| obj_import    | int                   | how many object imported to database |
| obj_update    | int                   | how many object updated in database  |
| status        | text                  | Success, Error, Retry-Success ...    |
| error_message | text                  | Error message                        |
| filename      | text                  | tns_public_objects_2016_01.csv       |
