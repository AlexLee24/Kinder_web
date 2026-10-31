| New Name                            | Old Name                   | Describe                                |
| ----------------------------------- | -------------------------- | --------------------------------------- |
| [[`transient.objects`]]             | `tns_objects`              | transient objects info data             |
| [[`transient.photometry`]]          | `photometry`               | transient photometry                    |
| [[`transient.spectroscopy`]]        | `spectroscopy`             | transient spectroscopy                  |
| [[`transient.cross_matches`]]       | `cross_match_results`      | transient cross-match results (DETECT)  |
| [[`transient.target_images`]]       | `target_images`            | transient image (BYTEA)(DESI, or other) |
| [[`transient.download_logs`]]       | `tns_download_log`         | TNS sync log                            |
| [[`transient.custom_targets`]]      | `custom_targets`           | custom targets list                     |
| [[`transient.object_views_detail`]] | object_view_counts         | detail object view for 30 days          |
| [[`transient.object_views`]]        | object_views               | object views count                      |
| [[`transient.comments`]]            | comments                   | comments                                |
| [[`transient.default_permissions`]] | default_source_permissions | default permissions                     |

| [[`transient.lsst_alerts`]]         | —                          | LSST (ALeRCE) objects near a Lens / DESI galaxy, in TNS or not |
| [[`transient.lsst_lc_state`]]       | —                          | last ALeRCE lastmjd per TNS object (LSST light-curve refresh) |
| [[`transient.lsst_detect_matches`]] | —                          | DETECT's DESI / Lens candidates of an LSST alert (host rule, reviewer's host) |
| [[`transient.lsst_detect_screen`]]  | —                          | DETECT's verdict per LSST alert: score, host status, tags, M |
| [[`transient.lsst_target_images`]]  | —                          | DETECT review image (LS DR10 host model) per LSST alert |
