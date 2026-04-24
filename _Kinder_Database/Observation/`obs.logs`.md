| Column          | Type                  | Describe                                 |
| --------------- | --------------------- | ---------------------------------------- |
| log_id          | serial                | log id, PRIMARY KEY                      |
| target_id       | int                   | FK -> obs.targets.target_id              |
| date            | timestamp w/ timezone | observation time                         |
| name            | text                  | 2026A, 2026gzf, EP260321a .... no prefix |
| telescope       | text                  | LOT, SLT                                 |
| program         | text                  | R01, R07...                              |
| priority        | text                  | Urgent, High, Normal, Filler             |
| repeat          | int                   | Plan repeat                              |
| trigger_by      | int                   | usr_id                                   |
| trigger         | bool                  | true / false                             |
| observed        | bool                  | true / false                             |
| trigger_filter  | text[]                | {rp, gp}                                 |
| trigger_count   | int[]                 | {300, 300} (seconds)                     |
| trigger_time    | int[]                 | {6, 6} (minutes)                         |
| observed_filter | text[]                | {rp, gp}                                 |
| observed_count  | int[]                 | {300, 300} (seconds)                     |
| observed_time   | int[]                 | {6, 6} (minutes)                         |

## Indexes

| Index Name               | Type   | Columns           | Purpose                                     |
| ------------------------ | ------ | ----------------- | ------------------------------------------- |
| obs_logs_pkey            | B-tree | log_id            | PRIMARY KEY                                 |
| obs_logs_target_date_idx | B-tree | (target_id, date) | get all logs for a target sorted by time    |
| obs_logs_telescope_idx   | B-tree | (telescope, date) | schedule query by telescope                 |
