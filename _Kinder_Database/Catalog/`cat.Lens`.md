Combine all Lens galaxy data

| Column           | Type             | Describe                                              |
| ---------------- | ---------------- | ----------------------------------------------------- |
| lens_id          | serial           | ID, PRIMARY KEY                                       |
| ra               | double precision | deg                                                   |
| dec              | double precision | deg                                                   |
| z_lens           | double precision | redshift from lens system                             |
| z_source         | double precision | redshift from source                                  |
| lens_probability | double precision | probability of lens system (only in Karp et al. 2026) |
| lens_grade       | text             | grade for lens system                                 |
| known            | text             | 'known' / 'unknown' / 'candidate'                     |
| reference        | text             | from which catalogue                                  |
