#!/usr/bin/env bash
# Build AutoPhOT's own Python environment at app/vendor/autophot/.venv (git-ignored).
# AutoPhOT needs Python 3.12 and its own scientific stack, so it never shares Kinder's .venv.
#
#   scripts/pipeline/setup_autophot.sh        needs uv (https://docs.astral.sh/uv/)
#
# Run again after scripts/sync_autophot.sh when AutoPhOT's dependencies change.
# External programs AutoPhOT can use, installed separately on the server:
#   astrometry.net (solve-field), SExtractor, SWarp, HOTPANTS.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
AP="$HERE/app/vendor/autophot"
[ -f "$AP/pyproject.toml" ] || { echo "AutoPhOT is not in $AP; run scripts/sync_autophot.sh first" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

cd "$AP"
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
# [all]: every optional alignment / subtraction method the Pipeline page offers;
# gaiaxpy (Gaia XP synthetic photometry) and legacystamps (Legacy Survey templates) are imported when used.
uv pip install --python .venv/bin/python -e ".[all]" gaiaxpy legacystamps
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); import autophot, prepare; print('AutoPhOT ready, Python', sys.version.split()[0])"
