Filled hourly by `app/services/lsst/alerts.py` (screened by DETECT and shown on DETECT › LSST-DETECT, `/detect/lsst`). Only objects with a Lens or DESI match are stored.

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
| desi_matches | jsonb            | cat.desi rows within 30" and 3 R_e, ZWARN = 0 only (SN class only), by separation in R_e (max 5) |
| n_lens       | int              | len(lens_matches)                                                        |
| n_desi       | int              | len(desi_matches)                                                        |
| best_sep     | double precision | separation of the first lens (else DESI) match, arcsec                   |
| best_z       | double precision | redshift of that match                                                   |
| obj_id       | bigint           | transient.objects.obj_id once linked to TNS (NULL = not in TNS yet)      |
| tns_name     | text             | TNS name, e.g. 2026ahlr                                                  |
| tns_link     | text             | 'oid' (internal name) or 'position' (TNS object within 1.5")            |
| latest_mag / latest_filter / latest_mjd | double / text / double | newest LSST point (binned psfFlux > 0, AB mag) |
| peak_mag / peak_filter / peak_mjd | double / text / double | brightest LSST point |
| abs_latest / abs_peak | double precision | absolute magnitudes of those points (DETECT's absolute_magnitude) |
| z_used / z_source | double / text | redshift used: DESI host (ZWARN = 0) or the linked TNS object's |
| n_points     | int              | binned LSST points                                                       |
| mags_lastmjd / mags_at | double / timestamptz | ALeRCE lastmjd the magnitudes were computed from, and when |
| lc_points    | jsonb            | the binned LSST light curve, [[mjd, mag, mag_err, filter], ...] (DETECT's screen reads it) |
| review_status / review_by / review_at | text / text / timestamptz | LSST-DETECT review status: Inbox / Follow-up / Snoozed / Finish, who and when |
| first_seen   | timestamptz      | first time the watch stored it                                           |
| updated_at   | timestamptz      | last update                                                              |
