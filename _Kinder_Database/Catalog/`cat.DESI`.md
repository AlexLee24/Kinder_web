
| Column         | Type             | Describe             |
| -------------- | ---------------- | -------------------- |
| desi_target_id | bigint           | DESI target id (64-bit), PRIMARY KEY |
| ra             | double precision | deg                  |
| dec            | double precision | deg                  |
| redshift       | double precision |                      |
| redshift_err   | double precision |                      |
| delta_chi_2    | double precision | delta chi square     |
| zwarn          | int              | zwarn tag, 1 = ZWARN |