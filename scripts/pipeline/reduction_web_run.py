"""Reduce one batch of uploaded frames for the Pipeline page (app/services/pipeline/reduce.py starts it).

Run with the reduction pipeline's own Python (the Lulin conda env: astropy, ccdproc):

    python -u reduction_web_run.py <batch dir> <pipeline dir> <solve-field>

  <batch>/raw/            the frames uploaded from the page: science, and any bias / dark / flat
  <batch>/work/           a private copy of the pipeline: its scripts, Process_temp/, MasterBDF/, … (removed at the end)
  <batch>/results/        Calibrated_*.fits (calibrated + WCS) and Reduced_*.fits (calibrated, astrometry failed);
                          masters/ holds master frames made from uploaded calibration frames
  <batch>/progress.json   steps, astrometry per frame and problems, read by the page

The calibration steps are the pipeline's own scripts (raw_add_header_rename … science_calibrate), copied into
work/ and run unchanged, so they see only this batch's frames. work/MasterBDF/ links the pipeline's master frames
for the same telescope, camera and binning (read only, never written) next to the masters made here; a master
made from this batch's own calibration frames wins over the pipeline's one of the same night.

Astrometry is astrometry_solve.py per calibrated frame (EAU_Web's solve-field strategy: narrow scale range from
the header first, then wider, then blind; CPU and wall-clock limits).

Batches run one at a time on the server: a second one waits ("queued") on <batches>/.run.lock.
"""
import fcntl
import glob
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import astrometry_solve  # noqa: E402

SCRIPTS = ('setting_and_toolbox.py', 'raw_add_header_rename.py', 'calibration_bias.py', 'calibration_dark.py',
           'calibration_flat.py', 'science_calibrate.py')
DIRS = ('Process_temp', 'MasterBDF', 'Astrometry_temp', 'Calibrated_DF_Problem/sub_b_DARK_dummy',
        'Calibrated_DF_Problem/sub_bd_FLAT_dummy', 'Calibrated_Science_Problem/Reduced_Science_dummy')
STEPS = (
    ('queue', 'Wait for the server'),
    ('prepare', 'Copy the pipeline and frames'),
    ('header', 'Read headers, rename'),
    ('bias', 'Master bias'),
    ('dark', 'Master dark'),
    ('flat', 'Master flat'),
    ('calibrate', 'Calibrate science frames'),
    ('astrometry', 'Astrometry (solve-field)'),
    ('finish', 'Collect results'),
)
STEP_SCRIPT = {'header': 'raw_add_header_rename.py', 'bias': 'calibration_bias.py', 'dark': 'calibration_dark.py',
               'flat': 'calibration_flat.py', 'calibrate': 'science_calibrate.py'}
FRAME_TYPE = {'bias': 'BIAS_', 'dark': 'DARK_', 'flat': 'FLAT_'}       # Process_temp names after the header step
STEP_TIMEOUT = int(os.environ.get('REDUCTION_STEP_TIMEOUT') or 3 * 3600)

SOLVE_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))

batch = Path(sys.argv[1]).resolve()
pipeline = Path(sys.argv[2]).resolve()
solve_field = sys.argv[3]
work, raw, results = batch / 'work', batch / 'raw', batch / 'results'
_lock = threading.Lock()
_print_lock = threading.Lock()
_children = set()                                 # solve-field process groups, killed on SIGTERM
state = {'status': 'queued', 'step': 'queue', 'started': time.time(),
         'steps': [{'id': s, 'label': label, 'status': 'pending'} for s, label in STEPS],
         'astrometry': [], 'problems': [], 'results': [], 'masters': []}


def save():
    with _lock:
        tmp = batch / f'.progress.{os.getpid()}.tmp'
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        os.replace(tmp, batch / 'progress.json')


def say(text):
    with _print_lock:
        print(f'[kinder] {text}', flush=True)


def step(sid, status, note=''):
    for s in state['steps']:
        if s['id'] == sid:
            s['status'] = status
            if status == 'running':
                s['started'] = time.time()
                state['step'] = sid
            elif status in ('done', 'failed', 'skipped'):
                s['ended'] = time.time()
            if note:
                s['note'] = note
    save()


def on_term(signum, frame):
    for pgid in list(_children):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    os._exit(143)


# ── calibration (the pipeline's scripts) ─────────────────────────────────────

def run_script(sid):
    script = work / STEP_SCRIPT[sid]
    say(f'python {script.name}')
    try:
        r = subprocess.run([sys.executable, '-u', str(script)], cwd=str(work), stdin=subprocess.DEVNULL,
                           timeout=STEP_TIMEOUT)
        return r.returncode
    except subprocess.TimeoutExpired:
        say(f'{script.name} took longer than {STEP_TIMEOUT} s and was stopped')
        return -1


def toolbox():
    spec = importlib.util.spec_from_file_location('setting_and_toolbox', work / 'setting_and_toolbox.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def frames(prefix=''):
    return sorted(glob.glob(str(work / 'Process_temp' / f'{prefix}*.fits')))


def link_masters(tb):
    """Link the pipeline's masters for this batch's telescope / camera / binning into work/MasterBDF/,
    except the ones this batch makes itself (same name: those are made from the uploaded frames)."""
    from astropy.io import fits

    prefixes, own = set(), set()
    names = tb.image_type_name()
    for fp in frames():
        with fits.open(fp) as hdul:
            i = tb.fits_info(hdul)
        base = f"{i['telescope']}_{i['camera']}_bin{i['binning']}_x{i['x_pixel_number']}_"
        prefixes.update(f'Master_{t}_{base}' for t in ('BIAS', 'DARK', 'FLAT'))
        y = f"y{i['y_pixel_number']}_"
        if i['imgtype'] in names['bias']:
            own.add(f"Master_BIAS_{base}{y}gain{i['gain']}_MJD{i['intMJD']}.fits")
        elif i['imgtype'] in names['dark']:
            own.add(f"Master_DARK_{base}{y}gain{i['gain']}_{i['strtemp']}_{i['intexptime']}sec_MJD{i['intMJD']}.fits")
        elif i['imgtype'] in names['flat']:
            own.add(f"Master_FLAT_{base}{y}{i['filter']}_MJD{i['intMJD']}.fits")
    linked = 0
    src_dir = pipeline / 'MasterBDF'
    if prefixes and src_dir.is_dir():
        pre = tuple(prefixes)
        with os.scandir(src_dir) as it:
            for e in it:
                if e.name.endswith('.fits') and e.name.startswith(pre) and e.name not in own:
                    try:
                        os.symlink(e.path, work / 'MasterBDF' / e.name)
                        linked += 1
                    except FileExistsError:
                        pass
    return linked, len(own)


def collect_problems():
    """The pipeline's .dummy notes: which frames could not be calibrated and why."""
    out = []
    for rel, what in (('Calibrated_Science_Problem/Reduced_Science_dummy', 'science'),
                      ('Calibrated_DF_Problem/sub_bd_FLAT_dummy', 'flat'),
                      ('Calibrated_DF_Problem/sub_b_DARK_dummy', 'dark')):
        for fp in sorted(glob.glob(str(work / rel / '*.dummy'))):
            text = Path(fp).read_text(errors='replace')
            why = [ln.strip() for ln in text.splitlines() if ln.strip().startswith('No suitable')]
            out.append({'kind': what, 'name': Path(fp).name.replace('.dummy', '.fits'),
                        'why': ' '.join(why) or 'Not calibrated'})
    for fp in sorted(glob.glob(str(work / 'MasterBDF' / '*.dummy'))):
        lines = [ln.strip() for ln in Path(fp).read_text(errors='replace').splitlines() if ln.strip().endswith('.fits')]
        out.append({'kind': 'master', 'name': Path(fp).name.replace('.dummy', '.fits'),
                    'why': f'Too few frames to combine ({len(lines)}); the pipeline needs at least 4.'})
    return out


# ── astrometry (astrometry_solve.py: EAU_Web's solve-field strategy) ──────────

def solve(src):
    """One calibrated frame → results/Calibrated_*.fits (with WCS), else results/Reduced_*.fits as it is."""
    rec = {'name': src.name, 'status': 'running'}
    with _lock:
        state['astrometry'].append(rec)
    save()
    name = src.name.replace('Reduced_', 'Calibrated_', 1)
    got = astrometry_solve.solve(src, results / name, solve_field, log=say, children=_children, workdir=str(work))
    if got['status'] != 'solved':
        shutil.copy2(src, results / src.name)
    rec.update(got, output=name if got['status'] == 'solved' else src.name)
    save()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGTERM, on_term)
    os.umask(0o002)
    save()
    lock = open(batch.parent / '.run.lock', 'a')
    step('queue', 'running')
    say('waiting for any other batch to finish')
    fcntl.flock(lock, fcntl.LOCK_EX)                     # held until this process exits
    state['status'] = 'running'
    step('queue', 'done')

    step('prepare', 'running')
    if work.exists():
        shutil.rmtree(work)
    for d in DIRS:
        (work / d).mkdir(parents=True, exist_ok=True)
    missing = [s for s in SCRIPTS if not (pipeline / s).is_file()]
    if missing:
        raise RuntimeError(f'Not in {pipeline}: {", ".join(missing)}')
    for s in SCRIPTS:
        shutil.copy2(pipeline / s, work / s)
    n = 0
    for fp in sorted(raw.iterdir()):
        if fp.is_file() and fp.suffix.lower() in ('.fits', '.fit', '.fts'):
            shutil.copy2(fp, work / 'Process_temp' / fp.name)
            n += 1
    if not n:
        raise RuntimeError('No frames in this batch.')
    results.mkdir(exist_ok=True)
    for old in results.iterdir():                        # a run again starts clean
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    step('prepare', 'done', f'{n} frame{"s" * (n != 1)}')

    step('header', 'running')
    if run_script('header') != 0:
        raise RuntimeError('raw_add_header_rename.py failed (see the log).')
    tb = toolbox()
    linked, own = link_masters(tb)
    say(f'{linked} master frames linked from {pipeline / "MasterBDF"}')
    step('header', 'done', f'{linked} pipeline masters linked' + (f', {own} made here' if own else ''))

    for sid in ('bias', 'dark', 'flat'):
        count = len(frames(FRAME_TYPE[sid]))
        if not count:
            step(sid, 'skipped', 'No frames uploaded: the pipeline masters are used')
            continue
        step(sid, 'running')
        rc = run_script(sid)
        step(sid, 'done' if rc == 0 else 'failed', f'{count} frame{"s" * (count != 1)}')

    step('calibrate', 'running')
    rc = run_script('calibrate')
    reduced = sorted(Path(p) for p in glob.glob(str(work / 'Astrometry_temp' / 'Reduced_*.fits')))
    state['problems'] = collect_problems()
    if rc != 0 and not reduced:
        step('calibrate', 'failed')
        raise RuntimeError('science_calibrate.py failed (see the log).')
    step('calibrate', 'done' if reduced else 'failed',
         f'{len(reduced)} calibrated' + (f', {sum(p["kind"] == "science" for p in state["problems"])} not'
                                         if state['problems'] else ''))

    if reduced:
        step('astrometry', 'running')
        with ThreadPoolExecutor(max_workers=SOLVE_WORKERS) as ex:
            list(ex.map(solve, reduced))
        ok = sum(r['status'] == 'solved' for r in state['astrometry'])
        step('astrometry', 'done' if ok else 'failed', f'{ok} of {len(reduced)} solved')
    else:
        step('astrometry', 'skipped', 'Nothing was calibrated')

    step('finish', 'running')
    masters = []
    for fp in sorted((work / 'MasterBDF').iterdir()):
        if fp.is_file() and not fp.is_symlink() and fp.suffix == '.fits':
            (results / 'masters').mkdir(exist_ok=True)
            shutil.copy2(fp, results / 'masters' / fp.name)
            masters.append(fp.name)
    state['masters'] = masters
    state['results'] = sorted(p.name for p in results.glob('*.fits'))
    if not os.environ.get('REDUCTION_KEEP_WORK'):
        shutil.rmtree(work, ignore_errors=True)
    step('finish', 'done', f"{len(state['results'])} frame{'s' * (len(state['results']) != 1)}")
    state['status'] = 'done' if state['results'] else 'failed'
    state['ended'] = time.time()
    save()
    return 0 if state['results'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        say(f'FAILED: {e}')
        for s in state['steps']:
            if s['status'] == 'running':
                s['status'] = 'failed'
                s['ended'] = time.time()
        state.update(status='failed', error=str(e), ended=time.time())
        try:
            state['problems'] = state['problems'] or collect_problems()
        except Exception:
            pass
        save()
        sys.exit(1)
