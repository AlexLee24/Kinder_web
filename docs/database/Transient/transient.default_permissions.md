
| Column          | Type   | Describe              |
| --------------- | ------ | --------------------- |
| source          | text   | LOT, SLT ... PRIMARY KEY                     |
| permissions_set | text   | 'public' / 'login' / 'groups'                |
| groups          | int[]  | {group_id, ...}                              |
