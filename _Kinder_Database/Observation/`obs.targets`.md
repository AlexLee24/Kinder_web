| Column      | Type             | Describe                                 |
| ----------- | ---------------- | ---------------------------------------- |
| target_id   | serial           | target id, PRIMARY KEY                   |
| active      | bool             | True / False                             |
| name        | text             | 2026A, 2026gzf, EP260321a .... no prefix |
| mag         | double precision | 16.789                                   |
| ra          | double precision | 123.456                                  |
| dec         | double precision | -25.345                                  |
| telescope   | text             | LOT, SLT                                 |
| program     | text             | R01, R07...                              |
| priority    | text             | Urgent, High, Normal, Filler             |
| plan_filter | text[]           | {rp, gp}                                 |
| plan_count  | int[]            | {300, 300} (seconds)                     |
| plan_time   | int[]            | {6, 6} (minutes)                         |
| repeat      | int              | Repeat plan how many times, DEFAULT=0    |
| plan        | text             | Plan to staff                            |
| note        | text             | Note to group                            |
| create_by   | int              | user id                                  |

## Indexes

| Index Name              | Type   | Columns         | Purpose                                  |
| ----------------------- | ------ | --------------- | ---------------------------------------- |
| obs_targets_pkey        | B-tree | target_id       | PRIMARY KEY                              |
| obs_targets_name_uniq   | B-tree | name            | UNIQUE, fast lookup by object name       |
| obs_targets_active_idx  | B-tree | (active, telescope) | filter active targets by telescope   |
| obs_targets_priority_idx| B-tree | priority        | filter by Urgent / High / Normal ...     |

