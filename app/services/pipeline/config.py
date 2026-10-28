"""Where the pipeline tools live on this server.

Admins set the paths in Admin → Operations → Pipeline (auth.system_settings); an
empty setting falls back to the environment (kinder.env), then to the AutoPhOT copy
kept in this repository (app/vendor/autophot, scripts/sync_autophot.sh) with its own
Python (scripts/pipeline/setup_autophot.sh) and workspaces in app/data/autophot-runs.
Nothing here imports AutoPhOT: it runs in its own Python.
"""
import os
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VENDORED = REPO / 'app' / 'vendor' / 'autophot'          # tracked in git, see app/vendor/README.md
VENDORED_RUNS = REPO / 'app' / 'data' / 'autophot-runs'   # git-ignored

# setting key → (environment variable, label shown in the admin panel)
SETTINGS = {
    'autophot_dir': ('AUTOPHOT_DIR', 'AutoPhOT folder'),
    'autophot_python': ('AUTOPHOT_PYTHON', 'AutoPhOT Python'),
    'autophot_runs': ('AUTOPHOT_RUNS', 'Workspaces folder'),
    'calibrated_dir': ('CALIBRATED_SCIENCE_DIR', 'Calibrated science folder'),
}
# where the reduction pipeline on the production server writes calibrated frames, one folder per set
DEFAULT_CALIBRATED = Path('/Users/greatlab/reduction_pipeline/Calibrated_Science')
FITS_KEEP_DAYS = 7                # uploaded / copied FITS are deleted this long after they arrive; results stay

# Pipeline stages, in order. A stage that is not ready is shown as planned.
STAGES = [
    {'key': 'reduction', 'label': 'Reduction', 'ready': False,
     'about': 'Bias, dark and flat correction, cosmic rays and astrometry for raw frames.'},
    {'key': 'photometry', 'label': 'Photometry', 'tool': 'AutoPhOT', 'ready': True,
     'about': 'PSF and aperture photometry, calibration, template subtraction and limits.'},
]

_cache = {'at': 0.0, 'values': None}
_TTL = 60.0   # saving the settings calls clear_cache()


def _stored():
    """The settings as stored (strings, '' when unset), cached for a few seconds."""
    now = time.monotonic()
    if _cache['values'] is not None and now - _cache['at'] < _TTL:
        return _cache['values']
    from app.db.auth import get_settings
    got = get_settings(f'pipeline.{k}' for k in SETTINGS)          # one query for all of them
    values = {k: (got.get(f'pipeline.{k}') or '').strip() for k in SETTINGS}
    _cache.update(at=time.monotonic(), values=values)   # after the queries: a slow / unreachable DB must not expire it at once
    return values


def clear_cache():
    _cache.update(at=0.0, values=None)


def _path(value):
    return Path(value).expanduser() if value else None


def paths():
    """{'autophot_dir', 'autophot_python', 'autophot_runs', 'calibrated_dir'} → Path or None."""
    stored = _stored()
    raw = {k: stored.get(k) or os.getenv(env, '').strip() for k, (env, _) in SETTINGS.items()}
    out = {k: _path(v) for k, v in raw.items()}
    vendored = not out['autophot_dir']
    if vendored:
        out['autophot_dir'] = VENDORED
    if not out['autophot_python']:
        out['autophot_python'] = out['autophot_dir'] / '.venv' / 'bin' / 'python'
    if not out['autophot_runs']:
        out['autophot_runs'] = VENDORED_RUNS if vendored else out['autophot_dir'].parent / 'autophot-runs'
    if not out['calibrated_dir']:
        out['calibrated_dir'] = DEFAULT_CALIBRATED
    return out


def describe():
    """For the admin panel: stored value, environment fallback and the path in use."""
    stored = _stored()
    used = paths()
    return [{'key': k, 'label': label, 'env': env, 'value': stored.get(k, ''),
             'env_value': os.getenv(env, '').strip(), 'used': str(used[k]) if used[k] else ''}
            for k, (env, label) in SETTINGS.items()]


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
            detail = (f'{py} does not exist (run scripts/pipeline/setup_autophot.sh)' if d == VENDORED
                      else f'{py} does not exist (run "uv sync" in the AutoPhOT folder)')
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
    keep = ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'TZ')
    env = {k: os.environ[k] for k in keep if k in os.environ}
    home = os.environ.get('HOME') or str(Path.home())
    # PATH is kept (solve-field, sex, swarp, hotpants live there) with uv's ~/.local/bin first
    env['PATH'] = os.pathsep.join([str(Path(home) / '.local' / 'bin'),
                                   os.environ.get('PATH') or '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'])
    env.update(PYTHONUNBUFFERED='1', MPLBACKEND='Agg')
    return env
