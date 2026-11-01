Written by `app/db/detect_checks.py`: objects a person has looked at on DETECT, TNS-DETECT (`kind = 'tns'`, the `transient.objects` name) and LSST-DETECT (`kind = 'lsst'`, `LSST-<oid>`). No row = not checked. Ticked by the Check box in the overview's "Highest priority right now" (which then lists it under Checked), the Check button / C key on a review card, and every host decision on a card (set host, Follow-up, Done, No host). Shared by the lab. Created on first use.

| Column     | Type        | Describe                              |
| ---------- | ----------- | ------------------------------------- |
| kind       | text        | `tns` or `lsst` (primary key with name) |
| name       | text        | object name / `LSST-<oid>`            |
| checked_by | text        | email of who checked it first         |
| checked_at | timestamptz | when                                  |
