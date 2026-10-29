"""Reduction bot: the Lulin reduction pipeline (auto_calibration.sh) run step by step from the web app.

auto_calibration.sh ran these in /Users/greatlab/reduction_pipeline with conda env "Lulin"; here each one is a
subprocess of the reduction Python, in that folder, so every step gets its own state, time and log lines:

    raw_summon_rsync.py → rsync_script.sh (zsh) → remove_last_file.py → raw_selection_copy.py →
    raw_add_header_rename.py → calibration_bias.py → calibration_dark.py → calibration_flat.py →
    science_calibrate.py → science_astrometry_net_plate_solve.py

As in the shell script a failed step does not stop the rest; the run counts as failed. "Stop" kills the running
step (its process group) and skips the remaining ones. Steps run with umask 002 so the folder owner's own cron job
can still overwrite what the web server wrote. A run is refused while the pipeline is already running outside
Kinder (greatlab's crontab, see crontab_setup.txt); the page shows such runs too.

Settings (kinder.env):
    REDUCTION_PIPELINE_DIR    the folder (default: parent of the calibrated science folder, see system.monitor)
    REDUCTION_PYTHON          Python of the "Lulin" conda env (default: looked for under the folder owner's conda)
    REDUCTION_HOUR_UTC        run daily at this hour (UTC); unset = only by hand (the folder owner's cron runs it)
    REDUCTION_SKIP_SYNC       1 = skip the two download steps (the web server's user has no ssh key for the raw host)
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
SYNC_STEPS = ('summon_rsync', 'rsync')
# folders of the pipeline shown on the page: (label, path below the reduction folder)
PROBLEM_DIRS = (('Plate solve failed', 'Calibrated_Science_Problem/Astrometry_fail'),
                ('Science calibration problems', 'Calibrated_Science_Problem/Reduced_Science_dummy'),
                ('Dark problems', 'Calibrated_DF_Problem/sub_b_DARK_dummy'),
                ('Flat problems', 'Calibrated_DF_Problem/sub_bd_FLAT_dummy'))
ACTIVITY = ('rsync_script.sh', 'Process_temp', 'Astrometry_temp', 'MasterBDF', 'Calibrated_Science')


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


def skip_sync():
    return (os.environ.get('REDUCTION_SKIP_SYNC') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def external_runs():
    """Pipeline steps running right now that Kinder did not start: [{'pid', 'script', 'user', 'since'}]."""
    try:
        import psutil
    except ImportError:
        return []
    mine = (status.get_all().get(BOT) or {}).get('step_pid')
    scripts = {s[3] for s in STEPS}
    out = []
    for p in psutil.process_iter(['pid', 'cmdline', 'username', 'create_time']):
        try:
            cmd = p.info.get('cmdline') or []
            hit = next((os.path.basename(a) for a in cmd if os.path.basename(a) in scripts), None)
            if hit and any('/.reduction/' in a for a in cmd):     # a Pipeline › Reduction batch (its own copy)
                continue
            if not hit or (mine and (p.info['pid'] == mine or _parent_is(p, mine))):
                continue
            out.append({'pid': p.info['pid'], 'script': hit, 'user': p.info.get('username') or '',
                        'since': datetime.fromtimestamp(p.info['create_time'], timezone.utc).isoformat(timespec='seconds')})
        except Exception:
            continue
    return out


def _parent_is(proc, pid):
    try:
        return any(a.pid == pid for a in proc.parents())
    except Exception:
        return False


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
    cmd = ['/bin/sh', '-c', 'umask 002; exec "$@"', 'sh'] + cmd     # group-writable, like the owner's own runs
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
    _stop.clear()                                  # first: a Stop pressed from here on must count
    status.update(BOT, stop_requested=False)
    problem = setup_problem()
    if problem:
        status.update(BOT, detail={'setup': problem, 'steps': _steps_state({})})
        raise RuntimeError(problem)
    other = external_runs()
    if other:
        raise RuntimeError(f"Already running outside Kinder ({other[0]['script']}, pid {other[0]['pid']}).")
    r, py = root(), python()
    timeout = int(os.environ.get('REDUCTION_STEP_TIMEOUT') or 10800)
    skip = SYNC_STEPS if skip_sync() else ()
    states = {}

    def save():
        status.update(BOT, detail={'steps': _steps_state(states), 'root': str(r), 'python': str(py)})

    save()
    failed = []
    for key, label, kind, script in STEPS:
        if key in skip or _stop.is_set() or (status.get_all().get(BOT) or {}).get('stop_requested'):
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
    if _stop.is_set() or (status.get_all().get(BOT) or {}).get('stop_requested'):
        status.event(BOT, 'Run stopped by hand', level='warn', count=False)
        raise RuntimeError('Stopped by hand.')
    if failed:
        raise RuntimeError('Failed: ' + ', '.join(failed))
    done = len(STEPS) - len(skip)
    status.event(BOT, f'Reduction finished ({done} steps{", download skipped" if skip else ""})')
    return f'All {done} steps finished.' + (' Download skipped (REDUCTION_SKIP_SYNC).' if skip else '')


def run():
    return status.guarded_run(BOT, _pipeline)


def start_now():
    """For "Run now": run in a thread so the request returns at once."""
    e = status.get_all().get(BOT) or {}
    if e.get('state') == 'running' and status._pid_alive(e.get('pid')):
        return {'error': 'Already running.'}
    other = external_runs()
    if other:
        return {'error': f"The pipeline is already running outside Kinder ({other[0]['script']})."}
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


def _count_entries(path, newest=False):
    """Entries directly in a folder (fast: no recursion), and optionally the newest one's time."""
    n, last = 0, 0.0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith('.'):
                    continue
                n += 1
                if newest:
                    try:
                        last = max(last, e.stat().st_mtime)
                    except OSError:
                        pass
    except OSError:
        pass
    if newest:
        return n, (datetime.fromtimestamp(last, timezone.utc).isoformat(timespec='seconds') if last else None)
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
           'schedule': schedule_label(), 'problem': setup_problem(), 'skip_sync': skip_sync(), 'raw': [],
           'calibrated': [], 'folders': [], 'problems': [], 'masters': None, 'activity': None, 'crontab': '',
           'external': external_runs()}
    if out['exists']:
        for label, rel in PROBLEM_DIRS:
            p = r / rel
            if p.is_dir():
                out['problems'].append({'label': label, 'path': rel, 'files': _count_entries(p), 'modified': _mtime(p)})
        mb = r / 'MasterBDF'
        if mb.is_dir():
            n, newest = _count_entries(mb, newest=True)
            out['masters'] = {'files': n, 'newest': newest}
        stamps = [(r / a).stat().st_mtime for a in ACTIVITY if (r / a).exists()]
        if stamps:
            out['activity'] = datetime.fromtimestamp(max(stamps), timezone.utc).isoformat(timespec='seconds')
        try:
            out['crontab'] = (r / 'crontab_setup.txt').read_text(errors='replace')[:2000]
        except OSError:
            pass
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
        if not (cal and cal.is_dir()):
            cal = r / 'Calibrated_Science'
        if cal.is_dir():
            sets = sorted((p for p in cal.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
            out['calibrated'] = [{'name': p.name, 'frames': _count_fits(p), 'modified': _mtime(p)} for p in sets]
    _overview_cache.update(at=time.monotonic(), value=out)
    return out
