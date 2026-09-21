"""Single source of truth for every on-disk location the app uses.

Import this module before anything else in the ``app`` package: it also puts the two
vendored packages (CASTOR, DETECT) on ``sys.path`` and sets the ``DETECT_DATA_DIR``
default, which DETECT reads at import time.

Layout (relative to the project root)::

    kinder.env                  secrets / settings          -> ENV_FILE
    app/                        the Flask package           -> APP_DIR
    app/blueprints/             one folder per site area    -> BLUEPRINTS_DIR
    app/resources/              small data files in git     -> RESOURCES_DIR
    app/data/                   runtime data (git-ignored)  -> DATA_DIR
    app/log/                    daily logs (git-ignored)    -> LOG_DIR
    app/vendor/CASTOR/          git clone of CASTOR         -> CASTOR_DIR / CASTOR_SRC
    app/vendor/DETECT/          rsync copy of DETECT        -> DETECT_DIR / DETECT_DATA_DIR
"""
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

ENV_FILE = PROJECT_ROOT / 'kinder.env'
BLUEPRINTS_DIR = APP_DIR / 'blueprints'
RESOURCES_DIR = APP_DIR / 'resources'
DATA_DIR = APP_DIR / 'data'
LOG_DIR = APP_DIR / 'log'

VENDOR_DIR = APP_DIR / 'vendor'
CASTOR_DIR = VENDOR_DIR / 'CASTOR'
CASTOR_SRC = CASTOR_DIR / 'src'
DETECT_DIR = VENDOR_DIR / 'DETECT'
# DETECT keeps finder images and the SFD dust maps here (git-ignored, ~130 MB once the
# dust maps are fetched). Override with the DETECT_DATA_DIR environment variable.
os.environ.setdefault('DETECT_DATA_DIR', str(DETECT_DIR / 'data'))
DETECT_DATA_DIR = Path(os.environ['DETECT_DATA_DIR'])

# Runtime sub-directories under DATA_DIR (created lazily by their owners).
TNS_WORK_DIR = DATA_DIR / 'tns_api_download_work'
PHOT_CACHE_DIR = DATA_DIR / 'phot_cache'
SHARED_PLOTS_DIR = DATA_DIR / 'shared_plots'
BACKUP_DIR = DATA_DIR / 'backups'


def add_vendor_paths() -> None:
    """Make ``import castor`` and ``import function`` (DETECT) work.

    Appended (not prepended) so that project modules always win over vendored names.
    """
    for p in (CASTOR_SRC, DETECT_DIR):
        s = str(p)
        if s not in sys.path:
            sys.path.append(s)


add_vendor_paths()
