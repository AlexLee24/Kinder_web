Written by `app/services/lsst/detect.py`: the DETECT review image of an LSST alert (LS DR10 host-model overlay, else a marked cutout / DSS2, else a text card), served at /detect/lsst/review/image/<oid>. Redrawn only when `lsst_detect_screen.image_key` changes.

| Column     | Type        | Describe                                    |
| ---------- | ----------- | ------------------------------------------- |
| oid        | bigint      | transient.lsst_alerts.oid, PRIMARY KEY      |
| image_data | bytea       | PNG                                         |
| created_at | timestamptz | when it was drawn                           |
