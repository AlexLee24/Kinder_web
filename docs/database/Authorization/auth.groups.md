| Column      | Type | Describe          |
| ----------- | ---- | ----------------- |
| group_id    | serial | group id, PRIMARY KEY |
| name        | text | group name        |
| description | text | group description |
| joinable    | bool | True / False      |
| create_by   | int  | usr_id            |
| manager     | int  | usr_id            |

