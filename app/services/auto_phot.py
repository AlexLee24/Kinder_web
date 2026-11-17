"""Automatic photometry of each night's Lulin frames, shown on the Daily Trigger page.

Every morning (bot ``auto_phot``, after the reduction pipeline has calibrated the night) and on request:

1. Find last night's calibrated frames:  <Calibrated_Science>/<target>/Calibrated_<target>_D<yyyy-mm-dd>T…_<SLT|LOT>_….fits
   grouped by (target folder, telescope). Targets whose name starts with "EP" are left to the EP pipeline (skipped).
2. For each group, a Pipeline workspace AUTO_<target>_<TEL>_<yyyymmdd> (owner ``auto-photometry``; not in anyone's
   workspace list, admins can open it) gets copies of the frames and runs AutoPhOT: no template subtraction, frames
   of each filter stacked per night (if the stack gives nothing, the single frames instead), PSF photometry,
   calibration catalog from the coverage check (Pan-STARRS where it covers the target); a band that catalog does
   not have (u in Pan-STARRS) is calibrated against one that does: SDSS where it covers the target, else Gaia XP.
3. The points (detections, and 3σ limits for non-detections) go into the Kinder object's photometry with the
   telescope ``SLT(AUTO, w/o TS)`` / ``LOT(AUTO, w/o TS)``. A re-run of the same night replaces them.
4. obs.auto_phot keeps the state and the numbers for the page; a 60″ zoom per filter is saved as PNG in the
   workspace (auto_frames/<filter>.png), so the page keeps showing it after the FITS are cleaned up.
"""
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AUTO_USER = 'auto-photometry'
AUTO_NAME = 'Auto photometry'
TZ8 = timezone(timedelta(hours=8))
FRAME_RE = re.compile(r'_D(\d{4}-\d{2}-\d{2})T\d{6}_.*?_(SLT|LOT)[_\-]', re.I)
CATALOG_PREFERENCE = ('pan_starrs', 'sdss', 'skymapper', 'legacy', 'gaia')
BAND_CATALOGS = ('sdss', 'pan_starrs', 'legacy', 'gaia')     # for a band the main catalog lacks (u: SDSS, else Gaia XP)
ALL_SKY = {'gaia'}
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


_frames_cache = {}
FRAMES_TTL = 300


def night_frames(night):
    """{(target, telescope): {'n', 'filters': {band: count}}} for the page, from the calibrated folder (5 min cache);
    {} when the folder is not on this server."""
    key = night.isoformat()
    hit = _frames_cache.get(key)
    if hit and time.time() - hit[0] < FRAMES_TTL:
        return hit[1]
    try:
        groups = scan(night)
    except Exception as e:
        logger.info('auto_phot: cannot list the frames of %s (%s)', key, e)
        groups = {}
    out = {}
    for k, frames in groups.items():
        counts = {}
        for f in frames:
            b = _band(f) or '?'
            counts[b] = counts.get(b, 0) + 1
        out[k] = {'n': len(frames), 'filters': counts}
    _frames_cache.clear() if len(_frames_cache) > 20 else None
    _frames_cache[key] = (time.time(), out)
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


_cat_bands = None


def catalog_bands():
    """{catalog: set of bands} from AutoPhOT's databases/catalog.yml (its key panstarrs is our pan_starrs)."""
    global _cat_bands
    if _cat_bands is None:
        import yaml
        path = Path(__file__).resolve().parents[1] / 'vendor' / 'autophot' / 'databases' / 'catalog.yml'
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as e:
            logger.warning('auto_phot: cannot read %s (%s)', path, e)
            raw = {}
        out = {}
        for name, cols in raw.items():
            if isinstance(cols, dict):
                out['pan_starrs' if name == 'panstarrs' else name] = {k for k in cols if f'{k}_err' in cols}
        _cat_bands = out
    return _cat_bands


def band_catalogs(ra, dec, main, bands):
    """{band: catalog} for the bands the main catalog has no magnitudes in, e.g. {'u': 'sdss'} next to Pan-STARRS."""
    have = catalog_bands()
    missing = sorted(b for b in bands if b and b not in have.get(main, set()))
    if not missing:
        return {}
    try:
        from app.services.pipeline import coverage
        cats = coverage.check(ra, dec)['catalogs']
    except Exception as e:
        logger.info('auto_phot: coverage check failed (%s); all-sky catalogs only for %s', e, missing)
        cats = {}
    out = {}
    for b in missing:
        for c in BAND_CATALOGS:
            if c != main and b in have.get(c, set()) and (c in ALL_SKY or (cats.get(c) or {}).get('ok')):
                out[b] = c
                break
    return out


def workspace_name(night, target, telescope):
    from app.services.pipeline import autophot as ap
    return ap.clean_name(f'AUTO_{target}_{telescope}_{night.strftime("%Y%m%d")}')


def ensure_workspace(night, target, telescope, ra, dec, catalog, stack=True, bands=None):
    from app.services.pipeline import autophot as ap
    tid = workspace_name(night, target, telescope)
    if not (ap.runs_root() / tid / 'target.json').is_file():
        ap.create_workspace({'name': tid}, user=AUTO_USER, user_name=AUTO_NAME)
    ap.save_target(tid, {'target': target, 'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'catalog': catalog, 'ncpu': 1,
                         'subtraction': False, 'stack': stack, 'stack_with_singles': False}, user=AUTO_USER)
    cfg = ap._read_json(ap.tdir(tid) / 'target.json')
    cfg['auto'] = {'night': night.isoformat(), 'target': target, 'telescope': telescope}
    cfg['catalog_bands'] = dict(bands or {})      # per band, where the main catalog has none (the runner maps them)
    ap._write_json(ap.tdir(tid) / 'target.json', cfg)
    return tid


# ── run one workspace ────────────────────────────────────────────────────────

STOP_FILE = '.stop_requested'          # in the workspace: Stop on the Trigger page (any worker can write it)


class Stopped(Exception):
    pass


def _stop_path(night, target, telescope):
    from app.services.pipeline import autophot as ap
    return ap.runs_root() / workspace_name(night, target, telescope) / STOP_FILE


def stop_requested(night, target, telescope):
    try:
        return _stop_path(night, target, telescope).is_file()
    except Exception:
        return False


def clear_stop(night, target, telescope):
    try:
        _stop_path(night, target, telescope).unlink(missing_ok=True)
    except Exception:
        pass


def request_stop(night, target, telescope):
    """Stop one (night, target, telescope): a queued one does not start, a running AutoPhOT process is killed.
    The row ends as failed / "Stopped", so Retry measures it again."""
    from app.db import auto_phot as db
    from app.services.pipeline import autophot as ap
    p = _stop_path(night, target, telescope)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.now(timezone.utc).isoformat())
    tid = workspace_name(night, target, telescope)
    if _still_running(tid):
        try:
            ap.stop(tid)
        except ap.PipelineError:
            pass
    db.upsert(night, target, telescope, status='failed', reason='Stopped', finished_at=datetime.now(timezone.utc))


def _wait_for_slot(stop=None):
    from app.services.pipeline import autophot as ap
    end = time.time() + WAIT_SLOT_S
    while ap._running_count(auto=True) >= ap.MAX_RUNNING_AUTO:     # its own slot: people's runs are not counted
        if time.time() > end or (stop and stop()):
            raise RuntimeError('Another auto photometry run did not finish.')
        time.sleep(30)


def _run_and_wait(tid, progress=None, stop=None):
    """Start AutoPhOT and wait for it; returns the final job state."""
    from app.services.pipeline import autophot as ap
    end = time.time() + WAIT_SLOT_S
    while True:                       # a Retry from the page and the daily run may reach the slot together
        _wait_for_slot(stop)
        if stop and stop():
            raise Stopped()
        try:
            ap.start(tid, AUTO_USER)
            break
        except ap.PipelineError as e:
            if 'Auto photometry is already running' not in str(e) or time.time() > end:   # all slots taken meanwhile
                raise
            time.sleep(30)
    return _wait(tid, progress, stop)


def _still_running(tid):
    """A run of this workspace that outlived the process that started it (Kinder restarted during a deploy)."""
    from app.services.pipeline import autophot as ap
    try:
        return (ap.runs_root() / tid / 'target.json').is_file() and ap.job_status(tid).get('status') == 'running'
    except Exception:
        return False


def _wait(tid, progress=None, stop=None):
    """Wait for the workspace's AutoPhOT run to end (answering its questions with the default); the final job state."""
    from app.services.pipeline import autophot as ap
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


def _safe(band):
    return re.sub(r"[^A-Za-z0-9]", "_", band)


def _frame_pngs(tid, ra, dec, phot):
    """auto_frames/<filter>.png, a 60″ zoom of the best image of each filter (the Last night thumbnails), and
    <filter>_field.png, that image's whole field north up on one grid for all filters (field.json), the Workspace's."""
    import json
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
    made, grid = [], None
    gfile = d / 'field.json'
    if gfile.is_file():
        try:
            grid = json.loads(gfile.read_text())
        except ValueError:
            grid = None
    for f, p in best.items():
        try:
            _, original, _ = previews._sources(tid, p['image'], None)
        except Exception:
            logger.exception('auto_phot: frame of %s %s', tid, f)
            original = None
        if not original:
            continue
        try:
            png = previews.zoom_png(original, coord)
            if png:
                (d / f'{_safe(f)}.png').write_bytes(png)
                made.append(f)
            if grid is None:
                grid = previews.field_grid(original)
                if grid:
                    gfile.write_text(json.dumps(grid))
            fpng = previews.field_png(original, coord, grid) if grid else None
            if fpng:
                (d / f'{_safe(f)}_field.png').write_bytes(fpng)
        except Exception:
            logger.exception('auto_phot: frame pngs %s %s', tid, f)
    return made


def ensure_field_pngs(row):
    """Rows measured before the whole-field images existed: draw them now while the FITS are still kept (once)."""
    from app.services.pipeline import autophot as ap
    tid = row.get('workspace')
    if not tid or row.get('status') != 'done' or row.get('ra') is None:
        return
    try:
        d = ap.tdir(tid, must=False) / 'auto_frames'
    except ap.PipelineError:
        return
    mark = d / '.field_tried'
    if (d / 'field.json').is_file() or mark.exists() or not d.is_dir():
        return
    mark.touch()
    _frame_pngs(tid, row['ra'], row['dec'], row.get('phot') or [])


def field_grid(tid):
    import json
    from app.services.pipeline import autophot as ap
    try:
        return json.loads((ap.tdir(tid, must=False) / 'auto_frames' / 'field.json').read_text())
    except (OSError, ValueError, ap.PipelineError):
        return None


# A survey image of the frames' field: the first of these with data at the target. 'ls' layers come from the
# Legacy Survey viewer (any size, north up), 'hips' from CDS hips2fits.
FIELD_SURVEYS = [('euclid', 'Euclid Q1', 'hips', 'CDS/P/Euclid/Q1/color'),
                 ('dr11', 'Legacy DR11', 'ls', 'ls-dr11'), ('dr10', 'Legacy DR10', 'ls', 'ls-dr10'),
                 ('ps1', 'Pan-STARRS1', 'ls', 'ps1'), ('hsc', 'HSC PDR3', 'ls', 'hsc-dr3'), ('sdss', 'SDSS', 'ls', 'sdss'),
                 ('dss', 'DSS2', 'hips', 'CDS/P/DSS2/color')]
LS_CUTOUT = 'https://www.legacysurvey.org/viewer/jpeg-cutout'
_locks, _locks_guard = {}, threading.Lock()


def _lock(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())
HIPS2FITS = 'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'


def _survey_fetch(kind, layer, grid):
    import requests
    if kind == 'ls':
        r = requests.get(LS_CUTOUT, params={'ra': f"{grid['ra']:.6f}", 'dec': f"{grid['dec']:.6f}", 'layer': layer,
                                            'width': grid['nx'], 'height': grid['ny'], 'pixscale': f"{grid['scale']:.4f}"},
                         timeout=40)
    else:
        r = requests.get(HIPS2FITS, params={'hips': layer, 'ra': f"{grid['ra']:.6f}", 'dec': f"{grid['dec']:.6f}",
                                            'width': grid['nx'], 'height': grid['ny'], 'projection': 'TAN',
                                            'fov': max(grid['w'], grid['h']) / 3600, 'format': 'jpg'}, timeout=30)
    if r.status_code != 200 or not r.headers.get('content-type', '').startswith('image/'):
        return None
    return r.content


def _has_sky_at(jpg, xy, box=6):
    """False when the image is flat around the target (outside the survey: the services answer with black)."""
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(jpg)) as im:
            x, y = int(round(xy[0])), int(round(xy[1]))
            cut = im.convert('L').crop((max(0, x - box), max(0, y - box), x + box + 1, y + box + 1))
            lo, hi = cut.getextrema()
            return hi - lo > 4 or hi > 12
    except Exception:
        return False


def _ring(jpg, xy, grid):
    """The survey image with the target ringed like on the frames."""
    import io
    from PIL import Image, ImageDraw
    try:
        with Image.open(io.BytesIO(jpg)) as im:
            im = im.convert('RGB')
            r = max(6, round(max(grid['nx'], grid['ny']) * 0.025))
            ImageDraw.Draw(im).ellipse([xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r], outline=(0, 229, 255), width=2)
            buf = io.BytesIO()
            im.save(buf, format='JPEG', quality=90)
            return buf.getvalue()
    except Exception:
        return jpg


def field_survey(row):
    """{'key', 'label'} of the survey image of this row's field (auto_frames/survey.jpg), fetched the first time;
    {'key': None} when no survey has the target (or the frames have no field yet)."""
    import json
    from astropy.coordinates import SkyCoord
    from app.services.pipeline import autophot as ap
    from app.services.pipeline import previews
    tid = row.get('workspace')
    grid = field_grid(tid) if tid else None
    if not grid or row.get('ra') is None:
        return {'key': None}
    d = ap.tdir(tid, must=False) / 'auto_frames'
    meta = d / 'survey.json'
    with _lock(str(meta)):
        if meta.is_file():
            try:
                return json.loads(meta.read_text())
            except ValueError:
                pass
        xy = previews.target_px(grid, SkyCoord(row['ra'], row['dec'], unit='deg'))
        out, unsure = {'key': None}, False
        for key, label_, kind, layer in FIELD_SURVEYS:
            try:
                jpg = _survey_fetch(kind, layer, grid)
            except Exception as e:
                logger.info('auto_phot: %s survey %s: %s', tid, key, e)
                jpg, unsure = None, True
            if jpg and xy and _has_sky_at(jpg, xy):
                (d / 'survey.jpg').write_bytes(_ring(jpg, xy, grid))
                out = {'key': key, 'label': label_}
                break
            if jpg is None:
                unsure = True
        if out['key'] or not unsure:            # a service that did not answer may have it next time
            meta.write_text(json.dumps(out))
        return out


def survey_path(tid):
    from app.services.pipeline import autophot as ap
    try:
        p = ap.tdir(tid, must=False) / 'auto_frames' / 'survey.jpg'
    except ap.PipelineError:
        return None
    return p if p.is_file() else None


def details(row):
    """Why a row failed / what its run is doing, for the Trigger page: {'reason', 'images': [{'name', 'status',
    'hint', 'errors'}], 'problems': [...], 'log': last lines of the AutoPhOT log, 'progress'}."""
    from app.services.pipeline import autophot as ap
    out = {'reason': row.get('reason') or '', 'images': [], 'problems': [], 'log': '', 'progress': None}
    tid = row.get('workspace')
    if not tid or not (ap.runs_root() / tid / 'target.json').is_file():
        return out
    try:
        j = ap.job(tid)
        out['log'] = '\n'.join((j.get('log') or '').splitlines()[-80:])
        out['progress'] = j.get('progress')
        out['job'] = {k: j.get(k) for k in ('status', 'start', 'end', 'code')}
    except Exception:
        logger.exception('auto_phot: job of %s', tid)
    try:
        st = ap.image_status(tid) or {}
        out['images'] = [{k: f.get(k) for k in ('name', 'status', 'hint', 'errors', 'filter')} for f in st.get('failed') or []][:30]
        out['n_in'], out['n_ok'] = st.get('n_in'), st.get('n_ok')
        out['problems'] = ap.run_problems(tid)
    except Exception:
        logger.exception('auto_phot: image status of %s', tid)
    return out


def frame_png_path(tid, band, field=False):
    from app.services.pipeline import autophot as ap
    try:
        p = ap.tdir(tid, must=False) / 'auto_frames' / f'{_safe(band)}{"_field" if field else ""}.png'
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


def run_target(night, target, telescope, frames, stop=None, stack_only=False):
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
    if stop_requested(night, target, telescope):           # stopped while it waited in the queue
        return db.upsert(night, target, telescope, status='failed', reason='Stopped', finished_at=datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    row = db.upsert(night, target, telescope, status='queued', obj_name=obj_name, ra=ra, dec=dec, reason=None,
                    n_done=0, started_at=now, finished_at=None, **base)
    try:
        catalog = choose_catalog(ra, dec)
        bands = band_catalogs(ra, dec, catalog, filters)
        if bands:
            logger.info('auto_phot: %s %s: %s, and %s', target, telescope, catalog,
                        ', '.join(f'{b} from {c}' for b, c in bands.items()))
        phot = []
        progress = lambda p: db.upsert(night, target, telescope, n_done=p['done'])   # noqa: E731
        outer = stop
        stop = lambda: bool(outer and outer()) or stop_requested(night, target, telescope)   # noqa: E731
        # the page's Rerun / Retry / Measure now: the stacks only; the daily run falls back to the single frames
        for stack in ((True,) if stack_only else (True, False)):
            if stop():
                raise Stopped()
            tid = workspace_name(night, target, telescope)
            if _still_running(tid):             # started before a restart: wait for it instead of starting another
                logger.info('auto_phot: %s is still running from before; waiting for it', tid)
                db.upsert(night, target, telescope, status='running', workspace=tid)
                job = _wait(tid, progress, stop)
            else:
                tid = ensure_workspace(night, target, telescope, ra, dec, catalog, stack=stack, bands=bands)
                ap.add_files(tid, [str(f) for f in frames], origin='auto')
                db.upsert(night, target, telescope, status='running', workspace=tid)
                job = _run_and_wait(tid, progress=progress, stop=stop)
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
    except Stopped:
        logger.info('auto_phot: %s %s %s stopped', night, target, telescope)
        return db.upsert(night, target, telescope, status='failed', reason='Stopped', finished_at=datetime.now(timezone.utc))
    except Exception as e:
        logger.exception('auto_phot: %s %s %s', night, target, telescope)
        if stop_requested(night, target, telescope):
            return db.upsert(night, target, telescope, status='failed', reason='Stopped', finished_at=datetime.now(timezone.utc))
        return db.upsert(night, target, telescope, status='failed', reason=f'{type(e).__name__}: {e}'[:300],
                         finished_at=datetime.now(timezone.utc))


def _band(path):
    m = re.search(r'_T\d{6}_([A-Za-z]+?)p?_', Path(path).name)
    return (m.group(1) if m else '').lower()


def run_night(night, only=None, force=False, stop=None, root=None, stack_only=False):
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
    for (target, telescope), frames in todo:                 # the page lists the whole night at once
        if not (only or skipped_name(target)):
            clear_stop(night, target, telescope)                # a new run: an old Stop does not count
            db.upsert(night, target, telescope, status='queued', reason=None, n_done=0, n_frames=len(frames),
                      filters=sorted({_band(f) for f in frames} - {''}))
    # several targets at once (ap.MAX_RUNNING_AUTO, AUTO_PHOT_PARALLEL): each has its own workspace and AutoPhOT process
    from app.services.pipeline import autophot as ap

    def one(item):
        (target, telescope), frames = item
        if stop and stop():
            return None
        try:
            return run_target(night, target, telescope, frames, stop=stop, **({'stack_only': True} if stack_only else {}))
        except Exception:
            logger.exception('auto_phot: %s %s %s', night, target, telescope)
            return {'status': 'failed'}

    done = failed = skipped = 0
    with ThreadPoolExecutor(max_workers=max(1, min(ap.MAX_RUNNING_AUTO, len(todo) or 1)), thread_name_prefix='auto-phot') as pool:
        for row in pool.map(one, todo):
            if not row:
                continue
            done += row['status'] == 'done'
            failed += row['status'] == 'failed'
            skipped += row['status'] == 'skipped'
    return (f'{night}: {len(groups)} target(s) with frames, {done} measured, {failed} failed, {skipped} skipped (EP), '
            f'{len(groups) - len(todo)} already done')


def for_frames(target, keys):
    """What auto photometry did with these frames, for the Pipeline's calibrated picker: keys are (night iso,
    telescope) of the ticked frames of folder ``target``. [{'night', 'telescope', 'status', 'n_frames', 'n_done',
    'mags': [[filter, mag or None, lim]], 'url'}]; nights it never touched and will not (older than the daily
    run's 3 nights) are left out."""
    from app.db import auto_phot as db
    keys = sorted({(str(n), str(t).upper()) for n, t in keys if n and t})
    if not keys:
        return []
    out, oldest = [], last_night() - timedelta(days=2)
    rows = {}
    for n in {k[0] for k in keys}:
        try:
            for r in db.for_night(date.fromisoformat(n)):
                rows[(r['night'], r['telescope'], r['target'])] = r
        except Exception:
            logger.exception('auto_phot: status for %s', n)
    for n, tel in keys:
        r = rows.get((n, tel, target))
        url = '/daily_trigger#dtAuto'
        if r:
            mags = [[p['filter'], p['mag'], p['lim']] for p in r['phot']]
            out.append({'night': n, 'telescope': tel, 'status': r['status'], 'n_frames': r['n_frames'], 'n_done': r['n_done'],
                        'reason': r.get('reason') or '', 'mags': mags, 'url': url})
        elif skipped_name(target):
            continue
        elif date.fromisoformat(n) >= oldest:
            out.append({'night': n, 'telescope': tel, 'status': 'waiting', 'n_frames': 0, 'n_done': 0, 'reason': '',
                        'mags': [], 'url': url})
    return out


def queue_retry(night, target, telescope):
    """Mark one row queued and measure it in a background thread (the Trigger page's Rerun / Retry / Measure now):
    the stacked frames only, no fall-back to the single frames."""
    _frames_cache.pop(night.isoformat(), None)
    import threading
    from app.db import auto_phot as db
    clear_stop(night, target, telescope)
    db.upsert(night, target, telescope, status='queued', reason=None)

    def go():
        try:
            run_night(night, only=(target, telescope), force=True, stack_only=True)
        except Exception:
            logger.exception('auto_phot: retry %s %s %s', night, target, telescope)
    threading.Thread(target=go, daemon=True, name=f'auto-phot-{target}').start()
