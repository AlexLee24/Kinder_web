# Vendored packages

Third-party code that the app imports directly. `app/paths.py` appends both directories
to `sys.path` when the `app` package is imported.

| Directory | What | How it gets here | Imported as |
|---|---|---|---|
| `CASTOR/` | Exposure Time Calculator engine (https://github.com/AlexLee24/CASTOR) | **git clone** (git-ignored): `git clone https://github.com/AlexLee24/CASTOR.git app/vendor/CASTOR`; update with `git -C app/vendor/CASTOR pull` | `castor.*` (from `CASTOR/src`) |
| `DETECT/` | DETECT transient screening pipeline (`function/` package) | rsync copy, **tracked in git**: `scripts/sync_detect.sh [/path/to/DETECT]`; `DETECT/VERSION` records the source commit | `function.*` (from `DETECT/`) |

Runtime data for DETECT (finder images, SFD dust maps) lives in `DETECT/data/`
(git-ignored, `DETECT_DATA_DIR`). Do not edit files inside these directories by hand —
changes would be lost on the next pull/sync; fix them upstream instead.
