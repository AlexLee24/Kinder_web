Filled hourly by `app/services/lsst/alerts.py` (shown on DETECT › LSST, `/detect/lsst`). Only objects with a Lens or DESI match are stored.

| Column       | Type             | Describe                                                                 |
| ------------ | ---------------- | ------------------------------------------------------------------------ |
| oid          | bigint           | ALeRCE oid = Rubin diaObjectId (TNS internal name `LSST-AP-DO-<oid>`), PRIMARY KEY |
| ra           | double precision | ALeRCE meanra (deg)                                                      |
| dec          | double precision | ALeRCE meandec (deg)                                                     |
| firstmjd     | double precision | first detection (MJD)                                                    |
| lastmjd      | double precision | last detection (MJD)                                                     |
| n_det        | int              | number of detections                                                     |
| class_name   | text             | stamp classifier top class: SN / AGN / VS                                |
| probability  | double precision | probability of class_name                                                |
| lens_matches | jsonb            | cat.lens rows within 10", nearest first (max 5)                          |
| desi_matches | jsonb            | cat.desi rows within 30" (SN class only), by separation in R_e (max 5)   |
| n_lens       | int              | len(lens_matches)                                                        |
| n_desi       | int              | len(desi_matches)                                                        |
| best_sep     | double precision | separation of the first lens (else DESI) match, arcsec                   |
| best_z       | double precision | redshift of that match                                                   |
| obj_id       | bigint           | transient.objects.obj_id once linked to TNS (NULL = not in TNS yet)      |
| tns_name     | text             | TNS name, e.g. 2026ahlr                                                  |
| tns_link     | text             | 'oid' (internal name) or 'position' (TNS object within 1.5")            |
| first_seen   | timestamptz      | first time the watch stored it                                           |
| updated_at   | timestamptz      | last update                                                              |
