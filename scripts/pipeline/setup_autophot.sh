#!/usr/bin/env bash
# Build AutoPhOT's own Python environment at app/vendor/autophot/.venv (git-ignored).
# AutoPhOT needs Python 3.12 and its own scientific stack, so it never shares Kinder's .venv.
#
#   scripts/pipeline/setup_autophot.sh        needs uv (https://docs.astral.sh/uv/)
#
# Run again after scripts/sync_autophot.sh when AutoPhOT's dependencies change.
# External programs AutoPhOT can use, installed separately on the server:
#   astrometry.net (solve-field), SExtractor, SCAMP, SWarp, HOTPANTS.
#   SCAMP + SWarp (template alignment for sparse fields): Homebrew has no SWarp, so on the production Mac they come
#   from conda-forge in their own env, with wrappers on the service's PATH (2026-11-18):
#     conda create -n astromatic -c conda-forge --override-channels astromatic-scamp astromatic-swarp
#     for t in scamp swarp; do printf '#!/bin/sh\nexec %s/envs/astromatic/bin/%s "$@"\n' "$(conda info --base)" $t \
#       > ~/.local/bin/$t; chmod 755 ~/.local/bin/$t; done
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
AP="$HERE/app/vendor/autophot"
[ -f "$AP/pyproject.toml" ] || { echo "AutoPhOT is not in $AP; run scripts/sync_autophot.sh first" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv not found: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

cd "$AP"
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
# [all]: every optional alignment / subtraction method the Pipeline page offers;
# gaiaxpy (Gaia XP synthetic photometry) and legacystamps (Legacy Survey templates) are imported when used.
# sip_tpv: SWarp reads TPV, not SIP; AutoPhOT converts SLT/LOT's SIP headers with it before SWarp (without it SWarp
# ignores the distortion). It still imports pkg_resources, which setuptools 81 dropped.
uv pip install --python .venv/bin/python -e ".[all]" gaiaxpy legacystamps sip_tpv "setuptools<81"
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); import autophot, prepare, sip_tpv; print('AutoPhOT ready, Python', sys.version.split()[0])"
for t in sex scamp swarp; do command -v "$t" >/dev/null || echo "note: $t is not on PATH (AutoPhOT falls back to other methods)"; done
