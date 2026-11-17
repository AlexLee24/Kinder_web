"""Automatic photometry of each night's Lulin frames, shown on the Daily Trigger page.

Every morning (bot ``auto_phot``, after the reduction pipeline has calibrated the night) and on request:

1. Find last night's calibrated frames:  <Calibrated_Science>/<target>/Calibrated_<target>_D<yyyy-mm-dd>T…_<SLT|LOT>_….fits
   grouped by (target folder, telescope). Targets whose name starts with "EP" are left to the EP pipeline (skipped).
2. For each group, a Pipeline workspace AUTO_<target>_<TEL>_<yyyymmdd> (owner ``auto-photometry``; not in anyone's
   workspace list, admins can open it) gets copies of the frames and runs AutoPhOT: no template subtraction, frames
   of each filter stacked per night (if the stack gives nothing, the single frames instead), PSF photometry,
   calibration catalog from the coverage check (Pan-STARRS where it covers the target).
3. The points (detections, and 3σ limits for non-detections) go into the Kinder object's photometry with the
   telescope ``SLT(AUTO, w/o TS)`` / ``LOT(AUTO, w/o TS)``. A re-run of the same night replaces them.
4. obs.auto_phot keeps the state and the numbers for the page; a 60″ zoom per filter is saved as PNG in the
   workspace (auto_frames/<filter>.png), so the page keeps showing it after the FITS are cleaned up.
"""
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AUTO_USER = 'auto-photometry'
AUTO_NAME = 'Auto photometry'
TZ8 = timezone(timedelta(hours=8))
FRAME_RE = re.compile(r'_D(\d{4}-\d{2}-\d{2})T\d{6}_.*?_(SLT|LOT)[_\-]', re.I)
CATALOG_PREFERENCE = ('pan_starrs', 'sdss', 'skymapper', 'legacy', 'gaia')
WAIT_SLOT_S = 3 * 3600          # wait at most this long for a free AutoPhOT slot
RUN_TIMEOUT_S = 3 * 3600        # one target's run
POLL_S = 15
MAX_DEFAULT_ANSWERS = 5         # AutoPhOT asking (unknown telescope / filter): accept its default this often


def label(telescope):
    return f'{telescope}(AUTO, w/o TS)'


def skipped_name(target):
    return str(target).strip().upper().startswith('EP')


def last_night(now=None):
    """The evening whose frames are complete: before noon (UTC+8) the one before yesterday is still being taken
    care of by the morning run, so 'last night' is always the local date minus one."""
    now = now or datetime.now(TZ8)
    return (now - timedelta(days=1)).date()


# ── 1. frames ────────────────────────────────────────────────────────────────

def calibrated_root():
    from app.services.pipeline import calibrated
    return calibrated.root()


def scan(night, root=None):
    """{(target folder, telescope): [frame paths]} for one night."""
    root = Path(root) if root else calibrated_root()
    day = night.isoformat() if isinstance(night, date) else str(night)
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')):
        for f in sorted(d.rglob('*.fit*')):
            if not f.is_file() or f.name.startswith('.'):
                continue
            m = FRAME_RE.search(f.name)
            if m and m.group(1) == day:
                out.setdefault((d.name, m.group(2).upper()), []).append(f)
    return out


# ── 2. position, catalog, workspace ─────────────────────────────────────────

def _object(target):
    """(Kinder object name, ra, dec) or (None, None, None)."""
    from app.db import get_db_connection
    from app.db.transient import TNSObjectDB
    name = TNSObjectDB.resolve_object_name(target) or TNSObjectDB.resolve_object_name(target.replace(' ', ''))
    if not name:
        return None, None, None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT ra, dec FROM transient.objects WHERE name = %s LIMIT 1', (name,))
        r = cur.fetchone()
    if r and r[0] is not None and r[1] is not None:
        return name, float(r[0]), float(r[1])
    return name, None, None


def _from_targets(target):
    try:
        from app.db.obs import _parse_dec_deg, _parse_ra_deg, get_observation_targets
        for t in get_observation_targets(active_only=False):
            if str(t.get('name') or '').replace(' ', '') == target.replace(' ', '') and t.get('ra') and t.get('dec'):
                return _parse_ra_deg(t['ra']), _parse_dec_deg(t['dec'])
    except Exception:
        logger.exception('auto_phot: observation targets lookup failed')
    return None, None


def _from_header(path):
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from astropy.io import fits
    h = fits.getheader(path)
    ra, dec = h.get('RA') or h.get('OBJCTRA'), h.get('DEC') or h.get('OBJCTDEC')
    if ra is None or dec is None:
        return None, None
    try:
        return float(ra), float(dec)
    except (TypeError, ValueError):
        c = SkyCoord(str(ra), str(dec), unit=(u.hourangle, u.deg))
        return c.ra.deg, c.dec.deg


def position(target, frames):
    """(obj_name, ra, dec): the Kinder object's position, else the observation target's, else the FITS header's."""
    name, ra, dec = _object(target)
    if ra is None:
        ra, dec = _from_targets(target)
    if ra is None and frames:
        ra, dec = _from_header(frames[0])
    return name, ra, dec


def choose_catalog(ra, dec):
    try:
        from app.services.pipeline import coverage
        cats = coverage.check(ra, dec)['catalogs']
        for c in CATALOG_PREFERENCE:
            if (cats.get(c) or {}).get('ok'):
                return c
    except Exception as e:
        logger.info('auto_phot: coverage check failed (%s); using the footprint rule', e)
    return 'pan_starrs' if dec > -30 else 'skymapper'


def workspace_name(night, target, telescope):
    from app.services.pipeline import autophot as ap
    return ap.clean_name(f'AUTO_{target}_{telescope}_{night.strftime("%Y%m%d")}')


def ensure_workspace(night, target, telescope, ra, dec, catalog, stack=True):
    from app.services.pipeline import autophot as ap
    tid = workspace_name(night, target, telescope)
    if not (ap.runs_root() / tid / 'target.json').is_file():
        ap.create_workspace({'name': tid}, user=AUTO_USER, user_name=AUTO_NAME)
    ap.save_target(tid, {'target': target, 'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'catalog': catalog, 'ncpu': 1,
                         'subtraction': False, 'stack': stack, 'stack_with_singles': False}, user=AUTO_USER)
    cfg = ap._read_json(ap.tdir(tid) / 'target.json')
    cfg['auto'] = {'night': night.isoformat(), 'target': target, 'telescope': telescope}
    ap._write_json(ap.tdir(tid) / 'target.json', cfg)
    return tid


# ── run one workspace ────────────────────────────────────────────────────────

def _wait_for_slot(stop=None):
    from app.services.pipeline import autophot as ap
    end = time.time() + WAIT_SLOT_S
    while ap._running_count() >= ap.MAX_RUNNING:
        if time.time() > end or (stop and stop()):
            raise RuntimeError('No free AutoPhOT slot (other runs are going on this server).')
        time.sleep(30)


def _run_and_wait(tid, progress=None, stop=None):
    """Start AutoPhOT and wait for it; returns the final job state."""
    from app.services.pipeline import autophot as ap
    _wait_for_slot(stop)
    ap.start(tid, AUTO_USER)
    t0, answers = time.time(), 0
    while True:
        time.sleep(POLL_S)
        j = ap.job(tid)
        if progress and j.get('progress'):
            progress(j['progress'])
        if j.get('status') != 'running':
            return j
        if j.get('waiting'):
            if answers >= MAX_DEFAULT_ANSWERS:
                ap.stop(tid)
                return {**j, 'status': 'failed', 'reason': 'AutoPhOT kept asking for input: '
                        + (j.get('log') or '').strip().splitlines()[-1][:200]}
            ap.answer(tid, '')
            answers += 1
        if time.time() - t0 > RUN_TIMEOUT_S or (stop and stop()):
            ap.stop(tid)
            return {**j, 'status': 'failed', 'reason': 'Stopped: the run took too long' if not (stop and stop()) else 'Stopped'}


def _fail_reason(tid, job):
    from app.services.pipeline import autophot as ap
    if job.get('reason'):
        return job['reason']
    try:
        st = ap.image_status(tid) or {}
        for f in st.get('failed') or []:
            if f.get('hint') or f.get('errors'):
                return (f.get('hint') or f['errors'][-1])[:300]
        probs = ap.run_problems(tid)
        if probs:
            return probs[0]['text'][:300]
    except Exception:
        logger.exception('auto_phot: reading why %s failed', tid)
    return 'AutoPhOT measured no image'


def _points(tid):
    """obs.auto_phot.phot from the run's photometry table."""
    from app.services.pipeline import autophot as ap
    ph = ap.photometry(tid) or {}
    li3 = next((i for i, (_, s) in enumerate(ph.get('limits') or []) if abs(s - 3) < 1e-6), 0)
    out = []
    for r in ph.get('rows') or []:
        lim = r['limits'][li3] if r['limits'] else None
        out.append({'filter': r['filter'], 'mjd': r['mjd'], 'mag': r['psf'] if r['det'] else None,
                    'err': r['psf_err'] if r['det'] else None, 'lim': lim, 'snr': r['snr'], 'det': bool(r['det']),
                    'veto': r.get('veto') or '', 'image': r['name']})
    return out


def _frame_pngs(tid, ra, dec, phot):
    """auto_frames/<filter>.png: a 60″ zoom of the best image of each filter."""
    from astropy.coordinates import SkyCoord
    from app.services.pipeline import autophot as ap
    from app.services.pipeline import previews
    d = ap.tdir(tid) / 'auto_frames'
    d.mkdir(exist_ok=True)
    coord = SkyCoord(ra, dec, unit='deg')
    best = {}
    for p in phot:
        cur = best.get(p['filter'])
        if cur is None or (p.get('snr') or 0) > (cur.get('snr') or 0):
            best[p['filter']] = p
    made = []
    for f, p in best.items():
        try:
            _, original, _ = previews._sources(tid, p['image'], None)
            png = previews.zoom_png(original, coord) if original else None
        except Exception:
            logger.exception('auto_phot: frame zoom %s %s', tid, f)
            png = None
        if png:
            (d / f'{re.sub(r"[^A-Za-z0-9]", "_", f)}.png').write_bytes(png)
            made.append(f)
    return made


def frame_png_path(tid, band):
    from app.services.pipeline import autophot as ap
    try:
        p = ap.tdir(tid, must=False) / 'auto_frames' / f'{re.sub(r"[^A-Za-z0-9]", "_", band)}.png'
    except ap.PipelineError:
        return None
    return p if p.is_file() else None


def _import(tid, obj_name, telescope, old_ids):
    """Replace this night's AUTO points of the object: delete the previous run's rows, insert the new ones."""
    from app.db.transient import TNSObjectDB
    from app.services.pipeline import autophot as ap
    if old_ids:
        TNSObjectDB.delete_photometry_points(obj_name, old_ids)
    pts = [{'mjd': p['mjd'], 'magnitude': p['magnitude'], 'magnitude_error': p['magnitude_error'],
            'filter': p['filter'], 'telescope': label(telescope)} for p in ap.export_rows(tid, 'PSF', 3.0)]
    return TNSObjectDB.add_photometry_batch_ids(obj_name, pts) if pts else []


def run_target(night, target, telescope, frames, stop=None):
    """Measure one (night, target, telescope); returns its obs.auto_phot row."""
    from app.db import auto_phot as db
    from app.services.pipeline import autophot as ap
    filters = sorted({_band(f) for f in frames} - {''})
    base = dict(n_frames=len(frames), filters=filters)
    if skipped_name(target):
        return db.upsert(night, target, telescope, status='skipped', reason='EP targets are left to the EP pipeline', **base)
    prev = next((r for r in db.for_night(night) if r['target'] == target and r['telescope'] == telescope), None)
    obj_name, ra, dec = position(target, frames)
    if ra is None:
        return db.upsert(night, target, telescope, status='failed', obj_name=obj_name,
                         reason='No position: not a Kinder object, not an observation target, no RA/Dec in the header', **base)
    now = datetime.now(timezone.utc)
    row = db.upsert(night, target, telescope, status='queued', obj_name=obj_name, ra=ra, dec=dec, reason=None,
                    n_done=0, started_at=now, finished_at=None, **base)
    try:
        catalog = choose_catalog(ra, dec)
        phot = []
        for stack in (True, False):
            tid = ensure_workspace(night, target, telescope, ra, dec, catalog, stack=stack)
            ap.add_files(tid, [str(f) for f in frames], origin='auto')
            db.upsert(night, target, telescope, status='running', workspace=tid)
            job = _run_and_wait(tid, progress=lambda p: db.upsert(night, target, telescope, n_done=p['done']), stop=stop)
            phot = _points(tid) if job.get('status') == 'done' else []
            if phot or job.get('reason'):
                break
            logger.info('auto_phot: %s %s %s: the stacks gave no photometry; measuring the single frames', night, target, telescope)
        if not phot:
            return db.upsert(night, target, telescope, status='failed', reason=_fail_reason(tid, job),
                             finished_at=datetime.now(timezone.utc))
        ids = []
        if obj_name:
            ids = _import(tid, obj_name, telescope, (prev or {}).get('phot_ids') or [])
        _frame_pngs(tid, ra, dec, phot)
        return db.upsert(night, target, telescope, status='done', phot=phot, phot_ids=ids, n_done=len(frames),
                         reason=None if obj_name else 'Not a Kinder object: measured, not added to a Transient page',
                         finished_at=datetime.now(timezone.utc))
    except Exception as e:
        logger.exception('auto_phot: %s %s %s', night, target, telescope)
        return db.upsert(night, target, telescope, status='failed', reason=f'{type(e).__name__}: {e}'[:300],
                         finished_at=datetime.now(timezone.utc))


def _band(path):
    m = re.search(r'_T\d{6}_([A-Za-z]+?)p?_', Path(path).name)
    return (m.group(1) if m else '').lower()


def run_night(night, only=None, force=False, stop=None, root=None):
    """Measure every (target, telescope) of a night that is not done yet; only=(target, telescope) for one.
    Returns a one-line summary."""
    from app.db import auto_phot as db
    groups = scan(night, root)
    have = {(r['target'], r['telescope']): r for r in db.for_night(night)}
    todo = []
    for key, frames in sorted(groups.items()):
        if only and key != tuple(only):
            continue
        r = have.get(key)
        if r and not force and (r['status'] == 'done' or r['status'] == 'skipped') and r['n_frames'] == len(frames):
            continue
        todo.append((key, frames))
    done = failed = skipped = 0
    for (target, telescope), frames in todo:
        if stop and stop():
            break
        row = run_target(night, target, telescope, frames, stop=stop)
        done += row['status'] == 'done'
        failed += row['status'] == 'failed'
        skipped += row['status'] == 'skipped'
    return (f'{night}: {len(groups)} target(s) with frames, {done} measured, {failed} failed, {skipped} skipped (EP), '
            f'{len(groups) - len(todo)} already done')


def queue_retry(night, target, telescope):
    """Mark one row queued and measure it in a background thread (the Trigger page's Retry)."""
    import threading
    from app.db import auto_phot as db
    db.upsert(night, target, telescope, status='queued', reason=None)

    def go():
        try:
            run_night(night, only=(target, telescope), force=True)
        except Exception:
            logger.exception('auto_phot: retry %s %s %s', night, target, telescope)
    threading.Thread(target=go, daemon=True, name=f'auto-phot-{target}').start()
