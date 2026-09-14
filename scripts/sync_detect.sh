#!/usr/bin/env bash
# Copy the DETECT pipeline (its `function/` package) into app/modules/DETECT so the
# web app runs the same cross-match / host rule / screening code as the daemon.
#
#   scripts/sync_detect.sh [/path/to/DETECT]      (default: ../../DETECT next to this repo)
#
# Once DETECT lives on GitHub this becomes a `git clone` like app/modules/CASTOR.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-/Volumes/Mac_mini/Lab_Macmini/DETECT}"
DST="$HERE/app/modules/DETECT"

[ -d "$SRC/function" ] || { echo "no DETECT checkout at $SRC" >&2; exit 1; }
mkdir -p "$DST"
rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'analysis/' \
  --exclude 'database/build_desi_catalog.py' --exclude 'database/migrate_healpix.py' \
  --exclude 'scheduler.py' --exclude '_daily_run.py' --exclude '_hourly_run.py' \
  --exclude 'data_source.py' --exclude 'module/TNS_api_download.py' \
  --exclude 'module/photometry_download.py' --exclude 'module/Follow_up_target.py' \
  "$SRC/function/" "$DST/function/"
cp "$SRC/requirements.txt" "$DST/requirements.txt"
{
  echo "source: $SRC"
  echo "synced: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ( cd "$SRC" && git rev-parse --short HEAD 2>/dev/null | sed 's/^/commit: /' ) || true
} > "$DST/VERSION"
echo "DETECT synced to $DST"
cat "$DST/VERSION"
