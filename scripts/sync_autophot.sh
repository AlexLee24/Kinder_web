#!/usr/bin/env bash
# Copy AutoPhOT (https://github.com/Astro-Sean/autophot, MIT licence) into app/vendor/autophot,
# so the Pipeline page runs the version kept in this repository and a deploy needs no separate checkout.
#
#   scripts/sync_autophot.sh                  latest upstream (GitHub, default branch)
#   scripts/sync_autophot.sh <ref>            a tag, branch or commit of upstream
#   scripts/sync_autophot.sh /path/to/autophot   a local checkout, as it is on disk
#
# Then: scripts/pipeline/setup_autophot.sh (its Python environment) and commit app/vendor/autophot.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DST="$HERE/app/vendor/autophot"
REPO_URL="https://github.com/Astro-Sean/autophot.git"
ARG="${1:-}"
TMP=""
trap '[ -n "$TMP" ] && rm -rf "$TMP"' EXIT

if [ -n "$ARG" ] && [ -d "$ARG" ]; then
  SRC="$(cd "$ARG" && pwd)"
  ORIGIN="$SRC"
else
  TMP="$(mktemp -d)"
  git clone -q "$REPO_URL" "$TMP/autophot"
  [ -n "$ARG" ] && git -C "$TMP/autophot" checkout -q "$ARG"
  SRC="$TMP/autophot"
  ORIGIN="$REPO_URL"
fi
[ -f "$SRC/autophot.py" ] && [ -f "$SRC/LICENSE" ] || { echo "no AutoPhOT at $SRC" >&2; exit 1; }

mkdir -p "$DST"
# .venv (its Python, made by setup_autophot.sh) and VERSION stay; everything else mirrors the source
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'VERSION' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '*.egg-info' \
  --exclude 'temp_*' --exclude '*.code-workspace' --exclude '.DS_Store' \
  "$SRC/" "$DST/"
{
  echo "source: $ORIGIN"
  echo "synced: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ( cd "$SRC" && git log -1 --format='commit: %h %ad %s' --date=short 2>/dev/null ) || true
  ( cd "$SRC" && [ -n "$(git status --porcelain 2>/dev/null)" ] && echo "local changes: yes" ) || true
} > "$DST/VERSION"
# tracked (.gitignore excepts app/vendor/autophot/; its .venv and caches stay ignored)
git -C "$HERE" add -A "$DST"
# files upstream tracks although its own .gitignore matches them (logo.png)
( cd "$SRC" && git ls-files 2>/dev/null ) | while IFS= read -r f; do
  [ -f "$DST/$f" ] && git -C "$HERE" add -f "$DST/$f"
done
echo "AutoPhOT synced to $DST (staged)"
cat "$DST/VERSION"
