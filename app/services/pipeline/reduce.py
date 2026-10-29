"""Reduction batches for the Pipeline page: upload raw frames, reduce them with the lab's pipeline, get them back.

scripts/pipeline/reduction_web_run.py does the work with the reduction pipeline's own Python (the Lulin conda env):
the pipeline's calibration scripts run unchanged in a private copy, then astrometry_solve.py solves every calibrated
frame. This module stores the uploads, starts and stops runs and reads what the runner wrote.

  One folder per batch: <workspaces>/.reduction/<id>/
    batch.json      owner, name, created, the uploaded frames (type, object, filter, … read from the headers)
    raw/            the uploaded frames (science and any bias / dark / flat)
    .uploads/       uploads in progress
    job.json        the current or last run (status, pid), shared by all gunicorn workers
    progress.json   steps, astrometry per frame, problems (written by the runner)
    run.log         the runner's output
    results/        Calibrated_*.fits (calibrated + WCS), Reduced_*.fits (astrometry failed), masters/
  A batch is deleted KEEP_DAYS after its last run ended (or after it was made, if it never ran).
  Batches run one at a time on the server; the runner waits on .reduction/.run.lock.
"""
import contextlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import autophot as ap
from . import config
from .autophot import NotConfigured, NotFound, PipelineError

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / 'scripts' / 'pipeline' / 'reduction_web_run.py'
SCRIPTS = ('setting_and_toolbox.py', 'raw_add_header_rename.py', 'calibration_bias.py', 'calibration_dark.py',
           'calibration_flat.py', 'science_calibrate.py')
BID_RE = re.compile(r'\d{8}-\d{6}-[0-9a-f]{4}')
EXT = ('.fits', '.fit', '.fts')                  # what the pipeline's scripts read
KEEP_DAYS = config.FITS_KEEP_DAYS
CLEANUP_EVERY = 3600
MAX_FILES = 500
TYPES = {'light': 'Science', 'bias': 'Bias', 'dark': 'Dark', 'flat': 'Flat'}
_IMAGETYP = {'light': 'light', 'lightframe': 'light', 'object': 'light', 'bias': 'bias', 'biasframe': 'bias',
             'zero': 'bias', 'dark': 'dark', 'darkframe': 'dark', 'flat': 'flat', 'flatframe': 'flat'}
_PIPELINE_TYPES = {'light', 'lightframe', 'bias', 'biasframe', 'dark', 'darkframe', 'flat', 'flatframe'}
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


# ── Paths and setup ──

def root():
    return ap.runs_root() / '.reduction'


def pipeline_dir():
    from app.services.bots import reduction as bot
    return bot.root()


def python():
    from app.services.bots import reduction as bot
    return bot.python()


def solve_field():
    import sys
    sys.path.insert(0, str(RUNNER.parent))
    import astrometry_solve
    return astrometry_solve.find_solve_field()


def check():
    """What a batch needs on this server: [{'key', 'label', 'ok', 'detail'}]."""
    out = []
    p = pipeline_dir()
    missing = [s for s in SCRIPTS if not (p and (p / s).is_file())]
    out.append({'key': 'pipeline', 'label': 'Reduction pipeline', 'ok': bool(p) and not missing,
                'detail': str(p) if p and not missing else (f'Not found: {p or "(not set)"}' if not p or not p.is_dir()
                                                             else f'Missing in {p}: {", ".join(missing)}')})
    py = python()
    out.append({'key': 'python', 'label': 'Pipeline Python', 'ok': bool(py and py.is_file()),
                'detail': str(py) if py else 'No Lulin conda env found (set REDUCTION_PYTHON)'})
    sf = solve_field()
    out.append({'key': 'solve_field', 'label': 'solve-field', 'ok': bool(sf),
                'detail': sf or 'astrometry.net is not installed (brew install astrometry-net)'})
    try:
        r = ap.runs_root()
        ok = os.access(r if r.is_dir() else r.parent, os.W_OK)
        out.append({'key': 'runs', 'label': 'Workspaces folder', 'ok': ok, 'detail': str(r) if ok else f'{r} is not writable'})
    except NotConfigured as e:
        out.append({'key': 'runs', 'label': 'Workspaces folder', 'ok': False, 'detail': str(e)})
    return out


def ready():
    return all(c['ok'] for c in check())


def bdir(bid, must=True):
    if not BID_RE.fullmatch(bid or ''):
        raise NotFound('No such batch.')
    d = root() / bid
    if must and not (d / 'batch.json').is_file():
        raise NotFound('No such batch.')
    return d


_read = ap._read_json
_write = ap._write_json


# ── Batches ──

def create(user=''):
    root().mkdir(parents=True, exist_ok=True)
    bid = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    d = root() / bid
    (d / 'raw').mkdir(parents=True)
    _write(d / 'batch.json', {'id': bid, 'owner': user, 'created': time.time(), 'files': {}})
    return bid


def require(bid, user='', is_admin=False):
    b = _read(bdir(bid) / 'batch.json')
    if not is_admin and b.get('owner') != user:
        raise NotFound('No such batch.')
    return b


def _name(b):
    """target_telescope_date from the first science frame's header, like a workspace name."""
    sci = [f for f in (b.get('files') or {}).values() if f.get('type') == 'light']
    if not sci:
        return 'Calibration frames' if b.get('files') else 'Empty batch'
    f = sorted(sci, key=lambda x: x.get('date') or '')[0]
    objs = sorted({x.get('object') or '' for x in sci} - {''})
    target = objs[0] + (f' +{len(objs) - 1}' if len(objs) > 1 else '') if objs else 'Unknown target'
    tels = '+'.join(sorted({x.get('telescope') or '' for x in sci} - {''}))
    return ' · '.join(x for x in (target, tels, (f.get('date') or '')[:10]) if x)


def summary(bid):
    d = bdir(bid)
    b = _read(d / 'batch.json')
    j = job_status(bid)
    p = _read(d / 'progress.json') if j.get('status') else {}
    files = list((b.get('files') or {}).values())
    counts = {t: sum(f.get('type') == t for f in files) for t in TYPES}
    solved = sum(a.get('status') == 'solved' for a in p.get('astrometry') or [])
    ended = j.get('end') or 0
    return {'id': bid, 'name': _name(b), 'owner': b.get('owner', ''), 'created': b.get('created'), 'counts': counts,
            'n_files': len(files), 'status': j.get('status') or 'new', 'ended': ended,
            'expires': (ended or b.get('created') or time.time()) + KEEP_DAYS * 86400,
            'n_results': len(p.get('results') or []), 'solved': solved, 'step': p.get('step') if j.get('status') == 'running' else None}


def batches(user='', is_admin=False):
    r = root()
    if not r.is_dir():
        return []
    out = []
    for d in r.iterdir():
        if d.is_dir() and BID_RE.fullmatch(d.name) and (d / 'batch.json').is_file():
            owner = _read(d / 'batch.json').get('owner')
            if is_admin or owner == user:
                with contextlib.suppress(PipelineError):
                    out.append(summary(d.name))
    return sorted(out, key=lambda s: s['created'] or 0, reverse=True)


def delete(bid):
    _busy(bid)
    shutil.rmtree(bdir(bid))


def cleanup_expired(force=False):
    """Delete batches KEEP_DAYS after their last run ended (or after they were made); at most hourly."""
    try:
        r = root()
        if not r.is_dir():
            return 0
        stamp = r / '.cleanup'
        now = time.time()
        if not force and stamp.exists() and now - stamp.stat().st_mtime < CLEANUP_EVERY:
            return 0
        stamp.touch()
        n = 0
        for d in list(r.iterdir()):
            if not (d.is_dir() and BID_RE.fullmatch(d.name)):
                continue
            j = job_status(d.name) if (d / 'batch.json').is_file() else {}
            if j.get('status') == 'running':
                continue
            t = j.get('end') or _read(d / 'batch.json').get('created') or d.stat().st_mtime
            if now - t > KEEP_DAYS * 86400:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        return n
    except (NotConfigured, OSError):
        return 0


# ── Uploads ──

def _clean_name(name):
    base = os.path.basename(str(name or '').replace('\\', '/')).strip()
    base = re.sub(r'[^A-Za-z0-9_+\-.~]', '_', base)[:200]
    if not base or base.startswith('.') or not base.lower().endswith(EXT):
        raise PipelineError(f'{name}: only .fits, .fit and .fts frames (uncompressed) can be reduced.')
    return base


def _frame_info(path, name):
    """Header facts for the file list; refuses a frame the pipeline would not know what to do with."""
    from astropy.io import fits
    try:
        h = fits.getheader(path)
    except Exception:
        raise PipelineError(f'{name} is not a readable FITS file.')
    raw_type = str(h.get('IMAGETYP') or '').strip()
    if raw_type.lower() not in _PIPELINE_TYPES:
        raise PipelineError(f'{name}: IMAGETYP is "{raw_type or "missing"}"; the pipeline reduces Light, Bias, Dark and Flat frames.')
    return {'type': _IMAGETYP[raw_type.lower()], 'object': str(h.get('OBJECT') or '').strip()[:60],
            'filter': str(h.get('FILTER') or '').strip()[:40], 'telescope': str(h.get('TELESCOP') or '').strip()[:30],
            'camera': str(h.get('CAMERA') or h.get('INSTRUME') or '').strip()[:60],
            'exptime': h.get('EXPTIME') if isinstance(h.get('EXPTIME'), (int, float)) else None,
            'binning': h.get('XBINNING') if isinstance(h.get('XBINNING'), int) else None,
            'date': str(h.get('DATE-OBS') or '').strip()[:19], 'size': os.path.getsize(path)}


def upload_chunk(bid, name, offset, total, data):
    d = bdir(bid)
    _busy(bid)
    name = _clean_name(name)
    if not 0 < total <= ap.MAX_UPLOAD_BYTES:
        raise PipelineError(f'{name}: files up to {ap.MAX_UPLOAD_BYTES // 1024 ** 3} GB.')
    if offset < 0 or not data or offset + len(data) > total:
        raise PipelineError('Upload out of range; start the file again.')
    dest = d / 'raw' / name
    if dest.exists():
        raise PipelineError(f'{name} is already in this batch.')
    part = d / '.uploads' / (name + '.part')
    part.parent.mkdir(exist_ok=True)
    if offset == 0:
        part.unlink(missing_ok=True)
        if len(_read(d / 'batch.json').get('files') or {}) >= MAX_FILES:
            raise PipelineError(f'A batch holds up to {MAX_FILES} frames.')
    have = part.stat().st_size if part.exists() else 0
    if have != offset:
        raise PipelineError('Upload out of order; start the file again.')
    with open(part, 'ab') as f:
        f.write(data)
    received = offset + len(data)
    if received < total:
        return {'done': False, 'received': received}
    try:
        info = _frame_info(part, name)
    except PipelineError:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    b = _read(d / 'batch.json')
    b.setdefault('files', {})[name] = info
    _write(d / 'batch.json', b)
    return {'done': True, 'name': name, 'file': info}


def remove_file(bid, name):
    d = bdir(bid)
    _busy(bid)
    name = _clean_name(name)
    (d / 'raw' / name).unlink(missing_ok=True)
    b = _read(d / 'batch.json')
    (b.get('files') or {}).pop(name, None)
    _write(d / 'batch.json', b)


# ── Runs (state in job.json, as for AutoPhOT) ──

def job_status(bid):
    d = bdir(bid, must=False)
    j = _read(d / 'job.json')
    if j.get('status') == 'running' and not ap._alive(j.get('pid')):
        j = _finish(d, j, None)
    return j


def _finish(d, j, code):
    p = _read(d / 'progress.json')
    if j.get('stopping'):
        status = 'stopped'
    elif p.get('status') == 'done':
        status = 'done'
    else:
        status = 'failed'
    j = {**j, 'status': status, 'end': time.time(), 'code': code}
    with contextlib.suppress(OSError):
        _write(d / 'job.json', j)
    return j


def _busy(bid):
    if job_status(bid).get('status') == 'running':
        raise PipelineError('This batch is being reduced; wait for it to finish or stop it.')


def start(bid, user=''):
    d = bdir(bid)
    problems = [f"{c['label']}: {c['detail']}" for c in check() if not c['ok']]
    if problems:
        raise NotConfigured('Reduction is not set up on this server. ' + '; '.join(problems))
    with ap._start_lock():
        _busy(bid)
        files = _read(d / 'batch.json').get('files') or {}
        if not any(f.get('type') == 'light' for f in files.values()):
            raise PipelineError('Upload at least one science (Light) frame.')
        for name in ('progress.json',):
            (d / name).unlink(missing_ok=True)
        env = {**config.child_env(), 'PYTHONUNBUFFERED': '1'}
        py = python()
        env['PATH'] = os.pathsep.join([str(py.parent), env.get('PATH', ''), '/opt/homebrew/bin', '/usr/local/bin'])
        if os.environ.get('REDUCTION_STEP_TIMEOUT'):
            env['REDUCTION_STEP_TIMEOUT'] = os.environ['REDUCTION_STEP_TIMEOUT']
        log = open(d / 'run.log', 'w')
        log.write(f'$ reduce {bid} ({len(files)} frames)\n')
        log.flush()
        try:
            proc = subprocess.Popen([str(py), '-u', str(RUNNER), str(d), str(pipeline_dir()), solve_field()],
                                    cwd=str(d), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=True)
        except Exception:
            log.close()
            raise
        state = {'status': 'running', 'pid': proc.pid, 'start': time.time(), 'by': user}
        _write(d / 'job.json', state)

    def wait():
        code = proc.wait()
        log.close()
        _finish(d, _read(d / 'job.json') or state, code)

    threading.Thread(target=wait, daemon=True, name=f'reduce-{bid}').start()


def stop(bid):
    d = bdir(bid)
    j = job_status(bid)
    if j.get('status') != 'running':
        raise PipelineError('This batch is not running.')
    j['stopping'] = True
    _write(d / 'job.json', j)
    pid = j.get('pid')
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGTERM)               # the runner kills its solve-field groups, then exits

    def hard():
        time.sleep(5)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    threading.Thread(target=hard, daemon=True).start()


def job(bid, offset=0):
    """Run state for the page: job + progress + the log from offset (the page follows it)."""
    d = bdir(bid)
    j = job_status(bid)
    j.pop('pid', None)
    p = _read(d / 'progress.json')
    text, new_offset, reset = '', 0, False
    try:
        size = (d / 'run.log').stat().st_size
        if offset > size:
            offset, reset = 0, True
        start_at = max(offset, size - 200_000)
        reset = reset or start_at != offset
        with open(d / 'run.log', 'rb') as f:
            f.seek(start_at)
            text = f.read().decode('utf-8', errors='replace')
        new_offset = size
    except OSError:
        pass
    return {'job': j, 'progress': p, 'log': ANSI_RE.sub('', text), 'offset': new_offset, 'reset': reset,
            'summary': summary(bid)}


# ── Results ──

def results(bid):
    """[{'name', 'size', 'solved', 'master'}] in results/ (masters/ last)."""
    d = bdir(bid) / 'results'
    p = _read(bdir(bid) / 'progress.json')
    solved = {a.get('output'): a for a in p.get('astrometry') or []}
    out = []
    if d.is_dir():
        for f in sorted(d.glob('*.fits')):
            a = solved.get(f.name) or {}
            out.append({'name': f.name, 'size': f.stat().st_size, 'solved': a.get('status') == 'solved',
                        'astrometry': a, 'master': False})
        for f in sorted((d / 'masters').glob('*.fits')) if (d / 'masters').is_dir() else []:
            out.append({'name': f'masters/{f.name}', 'size': f.stat().st_size, 'solved': None, 'master': True})
    return out


def result_path(bid, rel):
    base = (bdir(bid) / 'results').resolve()
    p = (base / (rel or '')).resolve()
    if base not in p.parents or not p.is_file() or not p.name.endswith('.fits'):
        raise NotFound('No such file.')
    return p


def zip_path(bid):
    """results.zip, made again when the results changed (FITS are stored, they hardly compress)."""
    import zipfile
    d = bdir(bid)
    files = [d / 'results' / r['name'] for r in results(bid)]
    if not files:
        raise NotFound('No results yet.')
    z = d / 'results.zip'
    newest = max(f.stat().st_mtime for f in files)
    if z.is_file() and z.stat().st_mtime >= newest:
        return z
    tmp = d / f'.results.{os.getpid()}.zip'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
        for f in files:
            zf.write(f, f.relative_to(d / 'results'))
    os.replace(tmp, z)
    return z


def send_to_autophot(bid, names, user='', is_admin=False, tid='', new_name=''):
    """Copy result frames into a Photometry workspace: an existing one (tid) or a new one called new_name."""
    paths = [result_path(bid, n) for n in names if not str(n).startswith('masters/')]
    if not paths:
        raise PipelineError('Pick at least one frame.')
    if tid:
        ap.require(tid, user, is_admin)
    else:
        b = _read(bdir(bid) / 'batch.json')
        sci = [f for f in (b.get('files') or {}).values() if f.get('type') == 'light']
        hint = {'object': sci[0].get('object', '')} if sci else {}
        tid = ap.create_workspace({'name': new_name or _default_ws_name(b), 'hint': hint}, user=user)
    got = ap.add_files(tid, paths, origin=f'reduction:{bid}')
    return {'id': tid, **got}


def _default_ws_name(b):
    sci = sorted((f for f in (b.get('files') or {}).values() if f.get('type') == 'light'), key=lambda x: x.get('date') or '')
    if not sci:
        return 'reduction'
    f = sci[0]
    return '_'.join(x for x in (f.get('object'), f.get('telescope'), (f.get('date') or '')[:10].replace('-', '')) if x)
