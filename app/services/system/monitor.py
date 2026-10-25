"""Numbers for the admin System page (modelled on EAU_Web's admin server page).

Live, cheap (called every 10 s by the page):
  host()       CPU, load, memory, swap, uptime of the whole machine
  process()    this Kinder process and its gunicorn siblings
  top_procs()  the processes using the most memory / CPU on the machine
  disks()      every volume that holds something Kinder uses
  pipeline()   AutoPhOT runs and workspaces

Slow (walks big folders, so it runs in a background thread and is cached in app/data):
  sizes()      folder sizes of Kinder's data, the workspaces and the reduction pipeline
               (/Users/greatlab/reduction_pipeline on the production Mac)

psutil does the work on both macOS (production) and Linux; without it the stdlib fallbacks
give what they can and the page leaves the rest empty.
"""
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from app.paths import APP_DIR, DATA_DIR, LOG_DIR

try:
    import psutil
except ImportError:          # pragma: no cover - psutil is installed with Kinder
    psutil = None

logger = logging.getLogger(__name__)

REPO = APP_DIR.parent
SIZES_FILE = DATA_DIR / 'system_sizes.json'
SIZES_EVERY = 1800            # folder sizes are recounted at most every 30 min (or on demand)
SCAN_FILE_LIMIT = 3_000_000   # stop counting a tree after this many files (marked as partial)
_scan_lock = threading.Lock()
_scan_state = {'running': False, 'started': 0.0}
_started = time.time()
if psutil:
    psutil.cpu_percent(interval=None)            # first reading of a process is always 0; start the clock now


def _gb(n):
    return round(n / 1073741824.0, 2) if n is not None else None


def reduction_root():
    """The reduction pipeline's folder: REDUCTION_PIPELINE_DIR, else the parent of Calibrated_Science."""
    env = os.getenv('REDUCTION_PIPELINE_DIR', '').strip()
    if env:
        return Path(env).expanduser()
    try:
        from app.services.pipeline import config as pconfig
        cal = pconfig.paths().get('calibrated_dir')
        return cal.parent if cal else None
    except Exception:
        return None


def _workspaces_root():
    try:
        from app.services.pipeline import config as pconfig
        return pconfig.paths().get('autophot_runs')
    except Exception:
        return None


# ── Live numbers ──

def host():
    out = {'cpus': os.cpu_count(), 'loadavg': list(os.getloadavg()) if hasattr(os, 'getloadavg') else None,
           'platform': f'{sys.platform} · Python {sys.version.split()[0]}'}
    if psutil:
        out['cpu_pct'] = psutil.cpu_percent(interval=None)          # since the previous call (first call: 0)
        out['cpu_per_core'] = psutil.cpu_percent(interval=None, percpu=True)
        vm = psutil.virtual_memory()
        out.update(mem_total=vm.total, mem_avail=vm.available, mem_used_pct=vm.percent)
        sw = psutil.swap_memory()
        out.update(swap_total=sw.total, swap_used=sw.used, swap_pct=sw.percent)
        out['uptime'] = time.time() - psutil.boot_time()
        try:
            io = psutil.disk_io_counters()
            out['disk_io'] = {'read': io.read_bytes, 'write': io.write_bytes} if io else None
        except Exception:
            out['disk_io'] = None
        try:
            net = psutil.net_io_counters()
            out['net_io'] = {'sent': net.bytes_sent, 'recv': net.bytes_recv}
        except Exception:
            out['net_io'] = None
    return out


def _proc_info(p):
    with p.oneshot():
        mi = p.memory_info()
        info = {'pid': p.pid, 'name': p.name(), 'rss': mi.rss, 'cpu_pct': p.cpu_percent(interval=None),
                'threads': p.num_threads(), 'started': p.create_time()}
        try:
            info['fds'] = p.num_fds() if hasattr(p, 'num_fds') else None
        except Exception:
            info['fds'] = None
    return info


def process():
    """This worker, and the whole Kinder server (gunicorn master and all its workers)."""
    out = {'pid': os.getpid(), 'started': _started}
    if not psutil:
        return out
    me = psutil.Process()
    out['self'] = _proc_info(me)
    family = [me]
    try:
        parent = me.parent()
        if parent and 'gunicorn' in ' '.join(parent.cmdline()).lower():
            family = [parent] + parent.children()
            out['server'] = 'gunicorn'
    except Exception:
        pass
    infos = []
    for p in family:
        try:
            infos.append(_proc_info(p))
        except Exception:
            pass
    out['workers'] = len(infos) - (1 if out.get('server') else 0)
    out['rss_total'] = sum(i['rss'] for i in infos)
    out['cpu_total'] = round(sum(i['cpu_pct'] for i in infos), 1)
    try:
        out['autophot'] = [_proc_info(c) for c in me.children(recursive=True)]
    except Exception:
        out['autophot'] = []
    return out


def top_procs(n=8):
    if not psutil:
        return []
    rows = []
    for p in psutil.process_iter(['pid', 'name', 'username', 'memory_info', 'cpu_percent']):
        try:
            mi = p.info['memory_info']
            rows.append({'pid': p.info['pid'], 'name': p.info['name'] or '?', 'user': p.info['username'] or '',
                         'rss': mi.rss if mi else 0, 'cpu_pct': p.info['cpu_percent'] or 0.0})
        except Exception:
            pass
    by_mem = sorted(rows, key=lambda r: -r['rss'])[:n]
    by_cpu = sorted(rows, key=lambda r: -r['cpu_pct'])[:n]
    return {'by_mem': by_mem, 'by_cpu': by_cpu, 'n': len(rows)}


def _labelled_paths():
    out = [('Kinder', REPO), ('Kinder data', DATA_DIR)]
    ws = _workspaces_root()
    if ws:
        out.append(('Pipeline workspaces', ws))
    rr = reduction_root()
    if rr:
        out.append(('Reduction pipeline', rr))
    return out


def disks():
    """One row per volume holding any of Kinder's folders, with which folders live there."""
    vols = {}
    for label, p in _labelled_paths():
        probe = Path(p)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            dev = os.stat(probe).st_dev
            du = shutil.disk_usage(probe)
        except OSError:
            continue
        v = vols.setdefault(dev, {'total': du.total, 'free': du.free, 'used': du.total - du.free,
                                  'used_pct': round((du.total - du.free) * 100.0 / max(1, du.total), 1),
                                  'mount': _mount_of(probe), 'holds': []})
        v['holds'].append({'label': label, 'path': str(p), 'exists': Path(p).exists()})
    return list(vols.values())


def _mount_of(p):
    if psutil:
        best = ''
        try:
            for part in psutil.disk_partitions(all=False):
                if str(p).startswith(part.mountpoint) and len(part.mountpoint) > len(best):
                    best = part.mountpoint
        except Exception:
            pass
        if best:
            return best
    p = Path(p).resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return str(p)


def pipeline():
    out = {'running': 0, 'workspaces': 0}
    try:
        from app.services.pipeline import autophot as ap
        from app.services.pipeline import config as pconfig
        r = ap.runs_root()
        if r.is_dir():
            out['workspaces'] = sum(1 for d in r.iterdir() if d.is_dir() and not d.name.startswith('.') and (d / 'target.json').is_file())
            out['running'] = ap._running_count()
        out['max_running'] = ap.MAX_RUNNING
        out['keep_days'] = pconfig.FITS_KEEP_DAYS
        stamp = r / '.wdir' / '.cleanup'
        out['last_cleanup'] = stamp.stat().st_mtime if stamp.exists() else None
    except Exception:
        pass
    return out


def db_pool():
    try:
        from app.db import get_pool_stats
        return get_pool_stats()
    except Exception:
        return None


def snapshot():
    """Everything the page shows that is cheap to read."""
    t0 = time.perf_counter()
    out = {'time': time.time(), 'host': host(), 'process': process(), 'top': top_procs(),
           'disks': disks(), 'pipeline': pipeline(), 'db_pool': db_pool(), 'sizes': sizes_cached()}
    out['took_ms'] = round((time.perf_counter() - t0) * 1000, 1)
    return out


# ── Folder sizes (background) ──

def _tree(path, limit=SCAN_FILE_LIMIT):
    """(bytes, files, newest mtime, partial) of a folder, not following links."""
    total = files = 0
    newest = 0.0
    stack = [str(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            total += st.st_size
                            files += 1
                            if st.st_mtime > newest:
                                newest = st.st_mtime
                            if files >= limit:
                                return total, files, newest, True
                    except OSError:
                        pass
        except OSError:
            pass
    return total, files, newest, False


def _children(path, top=None):
    """Sizes of each item directly in a folder, biggest first."""
    rows = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return rows
    for e in entries:
        if e.name.startswith('.') and e.name not in ('.wdir', '.deleted'):
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                b, n, newest, partial = _tree(e.path)
            elif e.is_file(follow_symlinks=False):
                st = e.stat(follow_symlinks=False)
                b, n, newest, partial = st.st_size, 1, st.st_mtime, False
            else:
                continue
        except OSError:
            continue
        rows.append({'name': e.name, 'bytes': b, 'files': n, 'newest': newest, 'partial': partial, 'dir': e.is_dir()})
    rows.sort(key=lambda r: -r['bytes'])
    return rows[:top] if top else rows


def _workspace_fits(ws_root):
    """Per workspace: total bytes and how much of it is FITS (deleted after FITS_KEEP_DAYS)."""
    rows = []
    if not ws_root or not Path(ws_root).is_dir():
        return rows
    for d in sorted(Path(ws_root).iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        total = fits = 0
        for base, _, names in os.walk(d):
            for n in names:
                try:
                    s = os.path.getsize(os.path.join(base, n))
                except OSError:
                    continue
                total += s
                if n.lower().endswith(('.fits', '.fit', '.fts', '.fz', '.gz', '.unused')):
                    fits += s
        rows.append({'name': d.name, 'bytes': total, 'fits': fits})
    rows.sort(key=lambda r: -r['bytes'])
    return rows


def _scan():
    t0 = time.time()
    out = {'started': t0, 'groups': []}
    kinder = [('app/data', DATA_DIR), ('app/log', LOG_DIR), ('AutoPhOT environment', REPO / 'app' / 'vendor' / 'autophot' / '.venv'),
              ('Kinder .venv', REPO / '.venv')]
    out['groups'].append({'key': 'kinder', 'label': 'Kinder', 'path': str(REPO),
                          'items': [dict(zip(('bytes', 'files', 'newest', 'partial'), _tree(p)), name=n) for n, p in kinder if p.exists()]})
    data_children = _children(DATA_DIR, top=12)
    if data_children:
        out['groups'].append({'key': 'data', 'label': 'Inside app/data', 'path': str(DATA_DIR), 'items': data_children})
    ws = _workspaces_root()
    if ws and Path(ws).is_dir():
        out['groups'].append({'key': 'workspaces', 'label': 'Pipeline workspaces', 'path': str(ws), 'items': _workspace_fits(ws)})
    rr = reduction_root()
    if rr and rr.is_dir():
        out['groups'].append({'key': 'reduction', 'label': 'Reduction pipeline', 'path': str(rr), 'items': _children(rr)})
        cal = rr / 'Calibrated_Science'
        if cal.is_dir():
            out['groups'].append({'key': 'calibrated', 'label': 'Calibrated_Science, biggest folders', 'path': str(cal),
                                  'items': _children(cal, top=25)})
    elif rr:
        out['groups'].append({'key': 'reduction', 'label': 'Reduction pipeline', 'path': str(rr), 'items': [], 'missing': True})
    for g in out['groups']:
        g['bytes'] = sum(i['bytes'] for i in g['items'])
    out['finished'] = time.time()
    out['took_s'] = round(out['finished'] - t0, 1)
    return out


def _scan_thread():
    import fcntl
    lock = open(SIZES_FILE.parent / '.system_sizes.lock', 'a') if SIZES_FILE.parent.is_dir() else None
    try:
        if lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)    # another gunicorn worker is already counting
            except OSError:
                return
        result = _scan()
        SIZES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SIZES_FILE.with_name(f'.{SIZES_FILE.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(result))
        os.replace(tmp, SIZES_FILE)
        logger.info('system: folder sizes counted in %.1f s', result['took_s'])
    except Exception:
        logger.exception('system: folder size scan failed')
    finally:
        if lock:
            lock.close()
        with _scan_lock:
            _scan_state['running'] = False


def refresh_sizes(force=False):
    """Start a recount in the background if the last one is old (or force). Returns True if one started."""
    with _scan_lock:
        if _scan_state['running']:
            return False
        if not force and SIZES_FILE.exists() and time.time() - SIZES_FILE.stat().st_mtime < SIZES_EVERY:
            return False
        _scan_state.update(running=True, started=time.time())
    threading.Thread(target=_scan_thread, name='system-sizes', daemon=True).start()
    return True


def sizes_cached():
    """Last counted sizes (may be old) plus whether a recount is going; starts one when due."""
    refresh_sizes()
    try:
        data = json.loads(SIZES_FILE.read_text())
    except (OSError, ValueError):
        data = None
    with _scan_lock:
        return {'data': data, 'scanning': _scan_state['running'], 'scan_started': _scan_state['started'] or None,
                'every_s': SIZES_EVERY}
