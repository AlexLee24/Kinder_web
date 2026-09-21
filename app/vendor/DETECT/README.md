# DETECT (embedded copy)

`function/` is a copy of the DETECT pipeline — HEALPix cross-match against
`cat.desi` / `cat.lens`, host rule v1 (DLR), screening + score, LS DR10 finder,
upload to `transient.cross_matches` / `transient.detect_screen` — so the web app
runs exactly the same code as the DETECT daemon:

* `app/services/detect/detect_pipeline.py` calls `function.run_detect` after each TNS import
  (hourly), for the object page's Run button, and daily for every Follow-up object.
* `app/services/astro/ext_M_calculator.py` is a shim over `function.module.calculator`, so
  every absolute magnitude on the site uses DETECT's cosmology and extinction.

Refresh with `scripts/sync_detect.sh [path-to-DETECT]` (see `VERSION`). When
DETECT is on GitHub, replace this directory with a clone, as with `../CASTOR/`.

Runtime needs `DETECT_DATA_DIR` (set by `app/paths.py` to `app/vendor/DETECT/data`,
git-ignored): finder images and the SFD dust maps (fetched on first use, ~130 MB).
DB credentials come from `kinder.env` (`PG_*`), the same names DETECT uses.
