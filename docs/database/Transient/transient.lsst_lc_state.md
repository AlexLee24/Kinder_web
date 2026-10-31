Written by `app/services/lsst/lightcurve.py`: the hourly LSST light-curve refresh only re-downloads an object when ALeRCE's `lastmjd` is newer than `alerce_lastmjd`. A refresh replaces the object's `LSST(alerce)` rows in `transient.photometry`.

| Column         | Type             | Describe                                            |
| -------------- | ---------------- | --------------------------------------------------- |
| obj_id         | bigint           | transient.objects.obj_id, PRIMARY KEY               |
| oid            | bigint           | ALeRCE oid used                                     |
| alerce_lastmjd | double precision | ALeRCE lastmjd at the last successful refresh       |
| n_points       | int              | LSST(alerce) points written (one per filter/night)  |
| refreshed_at   | timestamptz      | last attempt                                        |
| error          | text             | error of the last attempt (NULL = ok)               |
