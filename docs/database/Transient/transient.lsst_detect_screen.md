Written by `app/services/lsst/detect.py`: DETECT's `screen_target` on one LSST alert (columns as `transient.detect_screen`). Built from the alert's LSST light curve (`lsst_alerts.lc_points`: first point = discovery mag, brightest = peak) and, once linked, the TNS object's type and redshift. Re-screened when the light curve gains a point (within 30 days of the first detection) or a reviewer changes the host (`screened_lastmjd` set to NULL).

| Column            | Type             | Describe                                              |
| ----------------- | ---------------- | ----------------------------------------------------- |
| oid               | bigint           | transient.lsst_alerts.oid, PRIMARY KEY                |
| name              | text             | `LSST-<oid>`                                          |
| score             | integer          | DETECT priority score                                 |
| host_status       | text             | confirmed / review / none                             |
| tags              | text[]           | DETECT tags (Host-*, Nuclear, Luminous, TDE?, ...)    |
| flags             | jsonb            | every screen flag                                     |
| host_targetid     | bigint           | DESI TARGETID of the host                             |
| z / z_source      | double / text    | desi_host or tns                                      |
| abs_mag / abs_mag_band / abs_mag_source / abs_mag_discovery | real / text / text / real | M from the peak (else discovery) LSST point |
| peak_mag / peak_filter / peak_mjd | real / text / double | brightest LSST point                    |
| center_sep_arcsec / d_dlr / offset_kpc | real | host offset                                  |
| review_day        | date             | UTC date of the first LSST detection (the review page's day) |
| screened_lastmjd  | double precision | light-curve lastmjd screened (NULL = re-screen next run) |
| image_key         | text             | hash of host / candidates / score / tags / M of the stored image |
| run_date          | timestamptz      | last screen                                           |
