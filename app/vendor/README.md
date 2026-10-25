# Vendored packages

Third-party code the app uses. `app/paths.py` appends CASTOR and DETECT to `sys.path` when
the `app` package is imported; AutoPhOT is never imported by Kinder, it runs in its own Python.

| Directory | What | How it gets here | Imported as |
|---|---|---|---|
| `CASTOR/` | Exposure Time Calculator engine (https://github.com/AlexLee24/CASTOR) | **git clone** (git-ignored): `git clone https://github.com/AlexLee24/CASTOR.git app/vendor/CASTOR`; update with `git -C app/vendor/CASTOR pull` | `castor.*` (from `CASTOR/src`) |
| `DETECT/` | DETECT transient screening pipeline (`function/` package) | rsync copy, **tracked in git**: `scripts/sync_detect.sh [/path/to/DETECT]`; `DETECT/VERSION` records the source commit | `function.*` (from `DETECT/`) |
| `autophot/` | AutoPhOT photometry pipeline (https://github.com/Astro-Sean/autophot, MIT licence, `autophot/LICENSE`) for the Pipeline page | rsync copy, **tracked in git**: `scripts/sync_autophot.sh [ref or /path/to/autophot]`; `autophot/VERSION` records the source commit. Its Python: `scripts/pipeline/setup_autophot.sh` → `autophot/.venv` (git-ignored) | not imported; run by `scripts/pipeline/autophot_web_run.py` |

Runtime data for DETECT (finder images, SFD dust maps) lives in `DETECT/data/`
(git-ignored, `DETECT_DATA_DIR`). Do not edit files inside these directories by hand —
changes would be lost on the next pull/sync; fix them upstream instead.
