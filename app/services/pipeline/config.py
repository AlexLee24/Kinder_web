"""Where the pipeline tools live on this server.

AutoPhOT is always the copy kept in this repository (app/vendor/autophot, updated with
scripts/sync_autophot.sh) run by its own Python (app/vendor/autophot/.venv, made by
scripts/pipeline/setup_autophot.sh), so every server runs the same, reviewed version.
Only the two folders that differ per server come from kinder.env: the workspaces
(AUTOPHOT_RUNS, default app/data/autophot-runs) and the reduction pipeline's calibrated
frames (CALIBRATED_SCIENCE_DIR). The admin panel shows them; it does not change them.
Nothing here imports AutoPhOT: it runs in its own Python.
"""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VENDORED = REPO / 'app' / 'vendor' / 'autophot'          # tracked in git, see app/vendor/README.md
VENDORED_RUNS = REPO / 'app' / 'data' / 'autophot-runs'   # git-ignored

VENDORED_PYTHON = VENDORED / '.venv' / 'bin' / 'python'

# path key → (kinder.env variable or None when fixed, label shown on the pages)
SETTINGS = {
    'autophot_dir': (None, 'AutoPhOT folder'),
    'autophot_python': (None, 'AutoPhOT Python'),
    'autophot_runs': ('AUTOPHOT_RUNS', 'Workspaces folder'),
    'calibrated_dir': ('CALIBRATED_SCIENCE_DIR', 'Calibrated science folder'),
}
# where the reduction pipeline on the production server writes calibrated frames, one folder per set
DEFAULT_CALIBRATED = Path('/Users/greatlab/reduction_pipeline/Calibrated_Science')
FITS_KEEP_DAYS = 7                # uploaded / copied FITS are deleted this long after they arrive; results stay

# Pipeline stages, in order. A stage that is not ready is shown as planned.
STAGES = [
    {'key': 'reduction', 'label': 'Reduction', 'tool': 'Lab pipeline', 'ready': True,
     'about': 'Bias, dark and flat correction, cosmic rays and astrometry for raw frames.'},
    {'key': 'photometry', 'label': 'Photometry', 'tool': 'AutoPhOT', 'ready': True,
     'about': 'PSF and aperture photometry, calibration, template subtraction and limits.'},
]


def _env_path(var):
    v = (os.getenv(var) or '').strip()
    return Path(v).expanduser() if v else None


def paths():
    """{'autophot_dir', 'autophot_python', 'autophot_runs', 'calibrated_dir'} → Path."""
    return {'autophot_dir': VENDORED, 'autophot_python': VENDORED_PYTHON,
            'autophot_runs': _env_path('AUTOPHOT_RUNS') or VENDORED_RUNS,
            'calibrated_dir': _env_path('CALIBRATED_SCIENCE_DIR') or DEFAULT_CALIBRATED}


def describe():
    """For the admin panel (read only): each path in use and where it comes from."""
    used = paths()
    out = []
    for k, (env, label) in SETTINGS.items():
        source = ('this repository' if env is None
                  else f'kinder.env {env}' if (os.getenv(env) or '').strip() else f'default (set {env} in kinder.env to change)')
        out.append({'key': k, 'label': label, 'env': env or '', 'used': str(used[k]), 'source': source})
    return out


def check(probe_python=True):
    """Problems that stop AutoPhOT from running here: [{'key', 'ok', 'detail'}], all ok → ready."""
    p = paths()
    out = []
    d = p['autophot_dir']
    out.append({'key': 'autophot_dir', 'ok': bool(d and (d / 'autophot.py').is_file()),
                'detail': 'autophot.py found' if d and (d / 'autophot.py').is_file()
                else ('Not set' if not d else f'No autophot.py in {d}')})
    py = p['autophot_python']
    ok, detail = False, 'Not set'
    if py:
        if not py.is_file():
            detail = f'{py} does not exist (run scripts/pipeline/setup_autophot.sh)'
        elif not os.access(py, os.X_OK):
            detail = f'{py} is not executable'
        elif probe_python:
            try:
                r = subprocess.run([str(py), '-c', 'import sys; print(sys.version.split()[0])'],
                                   capture_output=True, text=True, timeout=20, env=child_env(), cwd=str(d or py.parent))
                ok = r.returncode == 0
                detail = f'Python {r.stdout.strip()}' if ok else (r.stderr.strip().splitlines() or ['failed'])[-1]
            except (OSError, subprocess.SubprocessError) as e:
                detail = f'Could not start: {e}'
        else:
            ok, detail = True, str(py)
    out.append({'key': 'autophot_python', 'ok': ok, 'detail': detail})
    runs = p['autophot_runs']
    if not runs:
        out.append({'key': 'autophot_runs', 'ok': False, 'detail': 'Not set'})
    elif runs.is_dir():
        w = os.access(runs, os.W_OK | os.X_OK)
        out.append({'key': 'autophot_runs', 'ok': w, 'detail': 'Writable' if w else f'{runs} is not writable'})
    else:
        parent_ok = runs.parent.is_dir() and os.access(runs.parent, os.W_OK)
        out.append({'key': 'autophot_runs', 'ok': parent_ok,
                    'detail': 'Will be created on first use' if parent_ok else f'{runs} does not exist'})
    return out


def ready():
    return all(c['ok'] for c in check(probe_python=False))


def child_env():
    """Environment for AutoPhOT: only what it needs, never Kinder's secrets (DB, OAuth, Slack, TNS)."""
    keep = ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'TZ', 'ASTROMETRY_CONFIG')
    env = {k: os.environ[k] for k in keep if k in os.environ}
    home = os.environ.get('HOME') or str(Path.home())
    # PATH is kept (solve-field, sex, swarp, hotpants live there) with uv's ~/.local/bin first
    env['PATH'] = os.pathsep.join([str(Path(home) / '.local' / 'bin'),
                                   os.environ.get('PATH') or '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'])
    env.update(PYTHONUNBUFFERED='1', MPLBACKEND='Agg')
    return env
