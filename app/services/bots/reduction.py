"""Reduction bot: the Lulin reduction pipeline (auto_calibration.sh) run step by step from the web app.

auto_calibration.sh ran these in /Users/greatlab/reduction_pipeline with conda env "Lulin"; here each one is a
subprocess of the reduction Python, in that folder, so every step gets its own state, time and log lines:

    raw_summon_rsync.py → rsync_script.sh (zsh) → remove_last_file.py → raw_selection_copy.py →
    raw_add_header_rename.py → calibration_bias.py → calibration_dark.py → calibration_flat.py →
    science_calibrate.py → science_astrometry_net_plate_solve.py

As in the shell script a failed step does not stop the rest; the run counts as failed. "Stop" kills the running
step (its process group) and skips the remaining ones.

Settings (kinder.env):
    REDUCTION_PIPELINE_DIR    the folder (default: parent of the calibrated science folder, see system.monitor)
    REDUCTION_PYTHON          Python of the "Lulin" conda env (default: looked for under the folder owner's conda)
    REDUCTION_HOUR_UTC        run daily at this hour (UTC); unset = only by hand
    REDUCTION_STEP_TIMEOUT    seconds before a step is killed (default 10800)
"""
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import status

BOT = 'reduction'
log = status.get_logger(BOT)

STEPS = (
    ('summon_rsync', 'Plan download', 'py', 'raw_summon_rsync.py'),
    ('rsync', 'Download raw frames', 'zsh', 'rsync_script.sh'),
    ('remove_last', 'Drop unfinished file', 'py', 'remove_last_file.py'),
    ('select', 'Select raw frames', 'py', 'raw_selection_copy.py'),
    ('header', 'Headers and names', 'py', 'raw_add_header_rename.py'),
    ('bias', 'Master bias', 'py', 'calibration_bias.py'),
    ('dark', 'Master dark', 'py', 'calibration_dark.py'),
    ('flat', 'Master flat', 'py', 'calibration_flat.py'),
    ('calibrate', 'Calibrate science', 'py', 'science_calibrate.py'),
    ('astrometry', 'Plate solve', 'py', 'science_astrometry_net_plate_solve.py'),
)
CONDA_ENV = 'Lulin'
_CONDA_DIRS = ('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge', 'opt/anaconda3', 'opt/miniconda3')
EXTRA_PATH = ('/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin')


def root():
    from app.services.system.monitor import reduction_root
    return reduction_root()


def python():
    """The reduction Python: REDUCTION_PYTHON, else <conda>/envs/Lulin/bin/python of the folder's owner."""
    env = (os.environ.get('REDUCTION_PYTHON') or '').strip()
    if env:
        return Path(env).expanduser()
    r = root()
    homes = []
    if r:
        parts = Path(r).parts
        if len(parts) >= 3 and parts[1] == 'Users':
            homes.append(Path(*parts[:3]))
    homes.append(Path.home())
    for home in homes:
        for d in _CONDA_DIRS:
            p = home / d / 'envs' / CONDA_ENV / 'bin' / 'python'
            if p.is_file():
                return p
    return None


def hour_utc():
    try:
        h = int((os.environ.get('REDUCTION_HOUR_UTC') or '').strip())
        return h if 0 <= h <= 23 else None
    except ValueError:
        return None


def schedule_label():
    h = hour_utc()
    return f'Daily {h:02d}:00 UTC ({(h + 8) % 24:02d}:00 UTC+8)' if h is not None else 'Only by hand (set REDUCTION_HOUR_UTC to schedule)'


def setup_problem():
    r, py = root(), python()
    if not r or not r.is_dir():
        return f'Reduction folder not found: {r or "(not set)"} — set REDUCTION_PIPELINE_DIR.'
    if not py or not py.is_file():
        return f'Python of the "{CONDA_ENV}" conda env not found — set REDUCTION_PYTHON.'
    missing = [s[3] for s in STEPS if not (r / s[3]).is_file()]
    if missing:
        return 'Missing in the reduction folder: ' + ', '.join(missing)
    return ''


# ── run ───────────────────────────────────────────────────────────────────────

_stop = threading.Event()


def _steps_state(states):
    return [{'key': k, 'label': lbl, 'script': script, **states.get(k, {'state': 'pending'})} for k, lbl, _, script in STEPS]


def _run_step(r, py, kind, script, timeout, on_line):
    cmd = ['/bin/zsh', script] if kind == 'zsh' else [str(py), '-u', script]
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join([str(py.parent)] + [p for p in env.get('PATH', '').split(os.pathsep) if p] + list(EXTRA_PATH))
    env['PYTHONUNBUFFERED'] = '1'
    env.pop('PYTHONPATH', None)                    # never hand Kinder's import path to the pipeline
    proc = subprocess.Popen(cmd, cwd=str(r), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True, text=True, errors='replace', bufsize=1)
    status.update(BOT, step_pid=proc.pid)
    deadline = time.monotonic() + timeout
    timer = threading.Timer(timeout, lambda: _kill(proc.pid))
    timer.daemon = True
    timer.start()
    try:
        for line in proc.stdout:
            on_line(line.rstrip())
        rc = proc.wait()
    finally:
        timer.cancel()
        status.update(BOT, step_pid=None)
    return rc, time.monotonic() > deadline


def _kill(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    time.sleep(5)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _pipeline():
    problem = setup_problem()
    if problem:
        status.update(BOT, detail={'setup': problem, 'steps': _steps_state({})})
        raise RuntimeError(problem)
    r, py = root(), python()
    timeout = int(os.environ.get('REDUCTION_STEP_TIMEOUT') or 10800)
    _stop.clear()
    status.update(BOT, stop_requested=False)
    states = {}

    def save():
        status.update(BOT, detail={'steps': _steps_state(states), 'root': str(r), 'python': str(py)})

    save()
    failed = []
    for key, label, kind, script in STEPS:
        if _stop.is_set() or (status.get_all().get(BOT) or {}).get('stop_requested'):
            states[key] = {'state': 'skipped'}
            continue
        started = datetime.now(timezone.utc)
        states[key] = {'state': 'running', 'started_at': started.isoformat(timespec='seconds')}
        save()
        log.info('── %s (%s)', label, script)
        tail = []

        def on_line(line, _key=key):
            if line:
                log.info('[%s] %s', _key, line)
                tail.append(line)
                del tail[:-5]
        try:
            rc, timed_out = _run_step(r, py, kind, script, timeout, on_line)
        except OSError as e:
            rc, timed_out = -1, False
            tail.append(str(e))
        secs = round((datetime.now(timezone.utc) - started).total_seconds())
        stopped = bool((status.get_all().get(BOT) or {}).get('stop_requested'))
        state = 'stopped' if stopped else 'ok' if rc == 0 else 'failed'
        states[key] = {'state': state, 'rc': rc, 'secs': secs, 'started_at': started.isoformat(timespec='seconds'),
                       'tail': tail[-3:] if state != 'ok' else []}
        if state == 'failed':
            failed.append(label)
            status.event(BOT, f'{label} failed (exit {rc}{", timed out" if timed_out else ""}) after {secs} s', level='error')
        else:
            log.info('%s: %s in %s s', label, state, secs)
        save()
        if stopped:
            _stop.set()
    save()                                         # the skipped ones
    if _stop.is_set():
        status.event(BOT, 'Run stopped by hand', level='warn', count=False)
        raise RuntimeError('Stopped by hand.')
    if failed:
        raise RuntimeError('Failed: ' + ', '.join(failed))
    status.event(BOT, f'Reduction finished ({len(STEPS)} steps)')
    return f'All {len(STEPS)} steps finished.'


def run():
    return status.guarded_run(BOT, _pipeline)


def start_now():
    """For "Run now": run in a thread so the request returns at once."""
    e = status.get_all().get(BOT) or {}
    if e.get('state') == 'running' and status._pid_alive(e.get('pid')):
        return {'error': 'Already running.'}
    threading.Thread(target=run, name='bot-reduction', daemon=True).start()
    return {'ok': True, 'message': 'Started.'}


def stop():
    """Kill the running step (from any worker) and skip the rest."""
    e = status.get_all().get(BOT) or {}
    if e.get('state') != 'running':
        return {'error': 'Not running.'}
    status.update(BOT, stop_requested=True)
    pid = e.get('step_pid')
    if pid:
        threading.Thread(target=_kill, args=(int(pid),), daemon=True).start()
    return {'ok': True, 'message': 'Stopping…'}


# ── folder overview for the page ─────────────────────────────────────────────

_overview_cache = {'at': 0.0, 'value': None}


def _count_fits(path, limit=20000):
    n = 0
    for _, _, files in os.walk(path):
        n += sum(1 for f in files if f.lower().endswith(('.fits', '.fts', '.fit')))
        if n >= limit:
            break
    return n


def _mtime(p):
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')
    except OSError:
        return None


def overview(max_age=60):
    """What is in the pipeline folders: newest raw nights, newest calibrated folders, the top level."""
    now = time.monotonic()
    if _overview_cache['value'] is not None and now - _overview_cache['at'] < max_age:
        return _overview_cache['value']
    r = root()
    out = {'root': str(r or ''), 'exists': bool(r and r.is_dir()), 'python': str(python() or ''),
           'schedule': schedule_label(), 'problem': setup_problem(), 'raw': [], 'calibrated': [], 'folders': []}
    if out['exists']:
        try:
            out['folders'] = sorted(({'name': p.name, 'dir': p.is_dir(), 'modified': _mtime(p)}
                                     for p in r.iterdir() if not p.name.startswith('.')),
                                    key=lambda x: (not x['dir'], x['name'].lower()))[:80]
        except OSError:
            pass
        from .obs_log import raw_dir
        raw = raw_dir()
        if raw and raw.is_dir():
            nights = sorted((p for p in raw.iterdir() if p.is_dir() and p.name[:3].upper() in ('SLT', 'LOT')),
                            key=lambda p: p.name[3:], reverse=True)[:8]
            out['raw'] = [{'name': p.name, 'frames': _count_fits(p), 'modified': _mtime(p)} for p in nights]
        try:
            from app.services.pipeline import config as pconfig
            cal = pconfig.paths().get('calibrated_dir')
        except Exception:
            cal = None
        if cal and cal.is_dir():
            sets = sorted((p for p in cal.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
            out['calibrated'] = [{'name': p.name, 'frames': _count_fits(p), 'modified': _mtime(p)} for p in sets]
    _overview_cache.update(at=time.monotonic(), value=out)
    return out
