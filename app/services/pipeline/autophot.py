"""AutoPhOT bridge for the Pipeline page (ported from work-web's modules/autophot.py).

The work is done by scripts/pipeline/autophot_web_run.py, run with AutoPhOT's own
Python in AutoPhOT's folder; this module stores settings, starts and stops runs,
passes answers to AutoPhOT's questions and reads what it wrote.

  One folder per workspace: <runs>/<id>/
    target.json   settings from the web page
    images/       the FITS uploaded from the page or handed over by a pipeline stage (AutoPhOT's
                  fits_dir), templates in images/templates/<filter>_template/; output in images_REDUCED/
    .uploads/     uploads in progress (chunks are appended, then the FITS is checked and moved in)
    job.json      the current or last run (status, pid) — shared by all gunicorn workers
    .stdin        FIFO that becomes AutoPhOT's stdin, so any worker can send an answer
    run_target.json  the settings the current run was started with (target.json may change after)
    web_run.log, result.json, exit.json, legacy/<time>/ (earlier runs)
  Shared cache (catalog queries): <runs>/.wdir/. Its telescope.yml is this server's
  telescope/instrument list (not in git), started from and topped up with the template
  app/services/pipeline/telescope.yml; AutoPhOT's answers and the Telescopes page change it.
"""
import contextlib
import fcntl
import json
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path

from . import config
from . import filters as bands

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / 'scripts' / 'pipeline' / 'autophot_web_run.py'
TELESCOPE_YML = Path(__file__).resolve().parent / 'telescope.yml'
TELESCOPE_HISTORY_KEEP = 30

TS_DOWNLOAD = ['panstarrs', 'legacy', 'sdss']          # surveys AutoPhOT can download templates from
TS_DOWNLOAD_LABELS = {'panstarrs': 'Pan-STARRS', 'legacy': 'Legacy Survey', 'sdss': 'SDSS'}
TS_ALIGN = ['spalipy', 'swarp', 'reproject', 'astroalign', 'tweakwcs', 'chi2_shift']
TS_FORCECONV = ['REF', 'SCI', 'AUTO']
DEFAULT_CATALOG = 'sdss'          # AutoPhOT has no default catalog (null fails)
CATALOGS = ['sdss', 'pan_starrs', 'gaia', 'apass', '2mass', 'legacy', 'skymapper', 'refcat', 'tic', 'auto']
SUB_METHODS = ['sfft', 'hotpants', 'zogy']
FITS_EXT = ('.fits', '.fit', '.fts', '.fits.fz', '.fits.gz')
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')
TEXT_EXT = ('.log', '.txt', '.yml', '.yaml', '.json', '.dat', '.cat', '.reg', '.param', '.conv', '.sex', '.md', '.ecsv', '.tex')
MAX_RUNNING = 2                   # AutoPhOT runs at once on this server
MAX_SCAN = 500
MAX_UPLOAD_BYTES = 4 * 1024 ** 3  # one FITS
UPLOAD_CHUNK = 8 * 1024 * 1024    # the page sends files in pieces of this size (under the request size limit)
FILTER_RE = re.compile(r'[A-Za-z0-9_+\-]{1,16}')
LEGACY_KEEP = 3                   # archived runs kept per workspace
LEGACY_RE = re.compile(r'^\d{8}-\d{6}(?:-\d+)?$')
TID_RE = re.compile(r'[A-Za-z0-9_+\-.]{1,80}')
RUN_CFG = 'run_target.json'       # settings of the current run, archived with it


class PipelineError(Exception):
    status = 400


class NotFound(PipelineError):
    status = 404


class NotConfigured(PipelineError):
    status = 503


# ── Paths ──

def root():
    p = config.paths()['autophot_dir']
    if not p or not (p / 'autophot.py').is_file():
        raise NotConfigured(f'AutoPhOT is missing from {p}: check out the repository again (scripts/sync_autophot.sh updates it).')
    return p


def python():
    p = config.paths()['autophot_python']
    if not p or not p.is_file():
        raise NotConfigured(f'AutoPhOT has no Python environment at {p}: run scripts/pipeline/setup_autophot.sh.')
    return p


def runs_root():
    p = config.paths()['autophot_runs']
    if not p:
        raise NotConfigured('The workspaces folder is not set (AUTOPHOT_RUNS in kinder.env).')
    return p


def target_id(name):
    return re.sub(r'[^A-Za-z0-9_+\-.]', '_', name.strip().replace(' ', '_')).strip('.')[:80]


def tdir(tid, must=True):
    if not TID_RE.fullmatch(tid or '') or tid.startswith('.'):
        raise NotFound('No such workspace.')
    d = runs_root() / tid
    if must and not (d / 'target.json').is_file():
        raise NotFound('No such workspace.')
    return d


def _read_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return {}


def _write_json(p, data):
    p = Path(p)
    tmp = p.with_name(f'.{p.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def reduced_dir(cfg):
    """AutoPhOT's output folder: <fits_dir>_REDUCED (outdir_name can change it)."""
    import yaml
    out = str((cfg.get('overrides') or {}).get('outdir_name') or 'REDUCED')
    try:
        extra = yaml.safe_load(cfg.get('extra_yaml') or '') or {}
        out = str(extra.get('outdir_name') or out) if isinstance(extra, dict) else out
    except yaml.YAMLError:
        pass
    return Path(str(cfg['fits_dir']).rstrip('/') + '_' + out)


# ── Images in a workspace ──

def _fits_in(d, recursive):
    """FITS in a folder; with recursive, also subfolders except templates/ (AutoPhOT finds templates itself)."""
    it = d.rglob('*') if recursive else d.iterdir()
    return sorted(p for p in it if p.is_file() and p.name.lower().endswith(FITS_EXT)
                  and 'templates' not in p.relative_to(d).parts[:-1])


def _scan_dir(d, recursive):
    from astropy.io import fits
    files = _fits_in(d, recursive)
    n_sub = 0 if recursive else len(_fits_in(d, True)) - len(files)
    db = bands.telescope_db(_telescope_file())
    meta = bands.telescope_meta(_telescope_file())
    out = []
    for p in files[:MAX_SCAN]:
        info = {'name': str(p.relative_to(d))}
        try:
            with fits.open(p) as hdul:
                h = dict(hdul[0].header)
                for ext in hdul[1:2]:
                    h = {**dict(ext.header), **h}
            for k in ('TELESCOP', 'INSTRUME', 'FILTER', 'DATE-OBS', 'EXPTIME'):
                info[k] = str(h.get(k, '')) if h.get(k) is not None else ''
            if not info['FILTER']:
                info['FILTER'] = ' / '.join(str(h[k]) for k in ('FILTER1', 'FILTER2') if h.get(k))
            hi = bands.header_info(h, db, meta, p.name)
            info['band'], info['tag'] = hi['band'], hi['tag']
        except Exception as e:
            info['error'] = f'{type(e).__name__}: {e}'
        out.append(info)
    tags = {}
    for f in out:
        if f.get('tag'):
            tags[f['tag']] = tags.get(f['tag'], 0) + 1
    return {'path': str(d), 'n': len(files), 'n_sub': n_sub, 'files': out,
            'tags': [{'tag': t, 'n': n} for t, n in sorted(tags.items())],
            'missing': sum(1 for f in out if f.get('error') or not (f.get('TELESCOP') and f.get('INSTRUME') and f.get('FILTER')))}


def images_dir(tid):
    return tdir(tid, must=False) / 'images'


def _upload_name(name):
    from werkzeug.utils import secure_filename
    n = secure_filename(os.path.basename(str(name or '')))[:150]
    if not n or not n.lower().endswith(FITS_EXT):
        raise PipelineError('Only FITS files can be added (.fits, .fit, .fts, .fits.fz, .fits.gz).')
    return n


TEMPLATE_AUTO = 'auto'


def _template_dir(tid, band):
    if not FILTER_RE.fullmatch(band or ''):
        raise PipelineError('Template filter: letters, digits, _ + - only (e.g. r, g, V).')
    return images_dir(tid) / 'templates' / f'{band}_template'


def _image_dest(tid, name, template_filter=''):
    """Where a new file goes: images/<name>, or images/templates/<filter>_template/<name>.fits for a template
    (template_filter 'auto' is decided from the header once the file is here, see _place_template)."""
    base = images_dir(tid)
    if template_filter == TEMPLATE_AUTO:
        return base / 'templates' / '.incoming' / name
    if template_filter:
        return _template_dir(tid, template_filter) / (bands.stem(name) + '.fits')
    return base / name


def _place_template(tid, src, name, band=''):
    """Put a template where AutoPhOT looks: templates/<filter>_template/<name>.fits (.fz / .gz unpacked).

    AutoPhOT stops and asks when a filter has more than one template, so any earlier one of that
    filter is set aside as <name>.fits.unused (shown on the page, can be removed). Returns (rel, band, how)."""
    how = 'chosen'
    if not band:
        try:
            band, how, raw = bands.band_of(bands.image_header(src), bands.telescope_db(_telescope_file()), name)
        except Exception:
            raise PipelineError(f'{name} is not a readable FITS image.')
        if not band:
            raise PipelineError(f'Could not tell the filter of {name}'
                                + (f' (header FILTER = {raw})' if raw else ' (no filter in the header)')
                                + '; choose it and upload again.')
    dest_dir = _template_dir(tid, band)
    dest = dest_dir / (bands.stem(name) + '.fits')
    if dest.exists():
        raise PipelineError(f'templates/{band}_template/{dest.name} is already in this workspace.')
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        bands.write_plain_fits(src, dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise PipelineError(f'{name} is not a readable FITS image.')
    for other in sorted(dest_dir.glob('*.fits')):
        if other != dest and not other.name.startswith('PSF_model_'):
            other.rename(other.with_name(other.name + '.unused'))
    return str(dest.relative_to(images_dir(tid))), band, how


def _check_fits(path, label):
    try:
        from astropy.io import fits
        with fits.open(path) as hdul:
            hdul[0].header
    except Exception:
        raise PipelineError(f'{label} is not a readable FITS file.')


def _added(tid, rels, origin, template=False):
    """Record new files: they are no longer 'removed', and note where they came from.
    A template switches template subtraction on, until the settings have been saved once."""
    cfg = _read_json(tdir(tid) / 'target.json')
    if template and not cfg.get('configured'):
        cfg['subtraction'] = True
    cfg['removed'] = sorted(set(cfg.get('removed') or []) - set(rels))
    cfg['imported'] = time.time()
    cfg.setdefault('origins', {})
    cfg.setdefault('added_at', {})
    now = time.time()
    for r in rels:
        cfg['origins'][r] = origin
        cfg['added_at'][r] = now                      # the 7-day clock (FITS_KEEP_DAYS) starts here
    cfg['expired'] = [e for e in cfg.get('expired') or [] if e.get('name') not in rels]
    _write_json(tdir(tid) / 'target.json', cfg)


def upload_chunk(tid, name, offset, total, data, template_filter=''):
    """Append one piece of an upload; on the last piece check the FITS and move it into images/.

    The page sends each file in UPLOAD_CHUNK pieces, in order, so no request is larger than
    the server's limit. Returns {'done': False, 'received'} or {'done': True, 'name'}."""
    tdir(tid)
    _busy(tid)
    name = _upload_name(name)
    if not 0 < total <= MAX_UPLOAD_BYTES:
        raise PipelineError(f'{name}: files up to {MAX_UPLOAD_BYTES // 1024 ** 3} GB.')
    if offset < 0 or not data or offset + len(data) > total:
        raise PipelineError('Upload out of range; start the file again.')
    dest = _image_dest(tid, name, template_filter)
    rel = str(dest.relative_to(images_dir(tid)))
    if dest.exists():
        raise PipelineError(f'{rel} is already in this workspace.')
    part = tdir(tid) / '.uploads' / (rel.replace('/', '__') + '.part')
    part.parent.mkdir(parents=True, exist_ok=True)
    if offset == 0:
        part.unlink(missing_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have != offset:
        raise PipelineError('Upload out of order; start the file again.')
    with open(part, 'ab') as f:
        f.write(data)
    received = offset + len(data)
    if received < total:
        return {'done': False, 'received': received}
    try:
        _check_fits(part, name)
        if template_filter:
            rel, band, how = _place_template(tid, part, name, '' if template_filter == TEMPLATE_AUTO else template_filter)
            part.unlink(missing_ok=True)
            _added(tid, [rel], 'upload', template=True)
            return {'done': True, 'name': rel, 'band': band, 'how': how}
    except PipelineError:
        part.unlink(missing_ok=True)
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part, dest)
    _added(tid, [rel], 'upload')
    return {'done': True, 'name': rel}


def add_files(tid, paths, origin='reduction', move=False, template_filter=''):
    """Hand files to a workspace from another pipeline stage (e.g. reduced frames from Reduction).

    paths are files on this server that the stage wrote; each must be a readable FITS. An existing
    file with the same name is kept and reported in 'skipped'. Returns {'added', 'skipped'}."""
    tdir(tid)
    _busy(tid)
    added, skipped = [], []
    for src in paths:
        src = Path(src)
        name = _upload_name(src.name)
        dest = _image_dest(tid, name, template_filter)
        rel = str(dest.relative_to(images_dir(tid)))
        if dest.exists():
            skipped.append(rel)
            continue
        if not src.is_file():
            raise PipelineError(f'{src} not found.')
        _check_fits(src, name)
        if template_filter:
            rel = _place_template(tid, src, name, '' if template_filter == TEMPLATE_AUTO else template_filter)[0]
            if move:
                src.unlink()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            (shutil.move if move else shutil.copy2)(str(src), str(dest))
        added.append(rel)
    if added:
        _added(tid, added, origin, template=bool(template_filter))
    return {'added': added, 'skipped': skipped}


def _pick(body, old, key, allowed, default):
    v = body[key] if key in body else old.get(key, default)
    if v not in allowed:
        raise PipelineError(f'Unknown value for {key}: {v}')
    return v


def _num(body, old, key, default, lo, hi, cast=float):
    raw = body.get(key) if key in body else old.get(key, default)
    try:
        v = cast(raw if raw not in (None, '') else default)
    except (TypeError, ValueError):
        raise PipelineError(f'{key} must be a number.')
    return max(lo, min(v, hi))


def _flag(body, old, key, default=False):
    return bool(body[key]) if key in body else bool(old.get(key, default))


def target_label(cfg):
    """The astronomical target of a workspace. Workspaces made before targets and names were separate
    have only 'name', which then was the target."""
    return str(cfg['target'] if 'target' in cfg else cfg.get('name', '')).strip()


def clean_name(name):
    """A workspace name as it is stored and used for its folder: letters, digits and _ + - . only."""
    return target_id(str(name or ''))


class NameTaken(PipelineError):
    status = 409

    def __init__(self, name):
        super().__init__(f'A workspace called {name} already exists. Add a name of your own at the end '
                         f'(for example {name}_second).')
        self.name = name


def _workspaces():
    r = runs_root()
    if not r.is_dir():
        return
    for d in sorted(r.iterdir(), key=lambda x: x.name.lower()):
        if d.is_dir() and not d.name.startswith('.') and TID_RE.fullmatch(d.name) and (d / 'target.json').is_file():
            yield d


def name_taken(name, exclude=None):
    """Is there a workspace with this name (as its name or as its folder)? Case does not matter."""
    low = name.lower()
    for d in _workspaces():
        if d.name == exclude:
            continue
        if d.name.lower() == low or str(_read_json(d / 'target.json').get('name', '')).lower() == low:
            return True
    return not exclude and tdir(name, must=False).exists()


def final_name(name, suffix=''):
    """The name from the auto-name and what the user added after it: <auto>_<suffix>."""
    name, suffix = clean_name(name), clean_name(suffix)
    if not name:
        raise PipelineError('Enter a workspace name.')
    if suffix:
        name = f'{name[:78 - len(suffix)]}_{suffix}'
    return name[:80]


def create_workspace(body, user='', user_name=''):
    """The first page: an empty workspace that only has a name and an owner; images are uploaded after.

    Target, position, template subtraction and the other settings come on the workspace page.
    body: name (from the images: target_telescope_date), suffix (the user's own ending), hint
    (object / ra / dec read from the headers, offered later as the target)."""
    name = final_name(body.get('name'), body.get('suffix'))
    if name.startswith('.') or not TID_RE.fullmatch(name):
        raise PipelineError('Enter a workspace name.')
    if name_taken(name):
        raise NameTaken(name)
    d = tdir(name, must=False)
    runs_root().mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir(exist_ok=False)                          # two people creating the same name: one gets here first
    except FileExistsError:
        raise NameTaken(name)
    hint = body.get('hint') if isinstance(body.get('hint'), dict) else {}
    cfg = _build_cfg(name, {}, {}, user)
    cfg.update(name=name, target='', ra='', dec='', owner=user, owner_name=user_name or user, removed=[],
               hint={k: str(hint.get(k) or '').strip()[:80] for k in ('object', 'ra', 'dec') if str(hint.get(k) or '').strip()})
    images_dir(name).mkdir(parents=True, exist_ok=True)
    _write_json(d / 'target.json', cfg)
    return name


def save_target(tid, body, user=''):
    """Update the settings of a workspace (target, position, template subtraction, catalog, …).
    Everything is optional: the page saves each change as it is made; the run asks for the position."""
    old = _read_json(tdir(tid) / 'target.json')
    _busy(tid)
    cfg = _build_cfg(tid, body, old, user)
    cfg['configured'] = True
    if old.get('ts_download') and (cfg['ts_download'], cfg['ts_size']) != (old.get('ts_download'), old.get('ts_size')):
        _drop_downloaded_templates(tid)          # AutoPhOT keeps a downloaded template forever: fetch it again
    _write_json(tdir(tid) / 'target.json', cfg)
    return tid


DOWNLOADED_TEMPLATE_RE = re.compile(r'^(panstarrs|sdss|legacy|2MASS)_[A-Za-z0-9]+_band_template.*\.fits(\.unused)?$')


def _drop_downloaded_templates(tid):
    """Delete the templates AutoPhOT downloaded (<survey>_<band>_band_template.fits): it skips the download while one
    exists, so after a change of survey or size the old cutout would be used again. Templates people uploaded stay."""
    tpl = images_dir(tid) / 'templates'
    gone = []
    if tpl.is_dir():
        for p in sorted(tpl.glob('*_template/*')):
            if p.is_file() and DOWNLOADED_TEMPLATE_RE.match(p.name):
                p.unlink()
                gone.append(p.name)
    if gone:
        logger.info('pipeline: %s: removed downloaded templates %s (survey or size changed)', tid, ', '.join(gone))
    return gone


def _build_cfg(tid, body, old, user):
    ra = str(body['ra'] if 'ra' in body else old.get('ra') or '').strip()[:40]
    dec = str(body['dec'] if 'dec' in body else old.get('dec') or '').strip()[:40]
    if ra and dec:
        _parse_coord(ra, dec)
    target = str(body['target'] if 'target' in body else target_label(old)).strip()[:80]
    catalog = _pick(body, old, 'catalog', CATALOGS, DEFAULT_CATALOG)
    sub_method = _pick(body, old, 'sub_method', SUB_METHODS, 'sfft')
    extra = str(body['extra_yaml'] if 'extra_yaml' in body else old.get('extra_yaml', ''))
    if extra.strip():
        import yaml
        try:
            if not isinstance(yaml.safe_load(extra), dict):
                raise PipelineError('Extra settings must be YAML key: value pairs.')
        except yaml.YAMLError as e:
            raise PipelineError(f'Extra settings are not valid YAML: {e}')
    overrides = clean_overrides(body['overrides']) if 'overrides' in body else old.get('overrides') or {}
    return {**old, 'target': target, 'fits_dir': str(images_dir(tid)), 'ra': ra, 'dec': dec,
            'catalog': catalog, 'overrides': overrides,
            'ncpu': int(_num(body, old, 'ncpu', 1, 1, os.cpu_count() or 1, int)),
            'subtraction': _flag(body, old, 'subtraction'), 'sub_method': sub_method, 'extra_yaml': extra,
            'top_only': True,              # uploads are flat; templates/ is found by AutoPhOT itself
            # stacking: stack = measure the stacks (off by default); stack_with_singles = also the single frames
            'stack': _flag(body, old, 'stack'),
            'stack_with_singles': _flag(body, old, 'stack_with_singles'),
            'stack_align': _pick(body, old, 'stack_align', ['auto', 'stars', 'wcs'], 'auto'),
            'stack_combine': _pick(body, old, 'stack_combine', ['mean', 'median'], 'mean'),
            'stack_sigma': _num(body, old, 'stack_sigma', 3.0, 1.5, 10.0),
            # template subtraction
            'ts_download': _pick(body, old, 'ts_download', [''] + TS_DOWNLOAD, ''),
            'ts_size': _num(body, old, 'ts_size', 10, 1.0, 60.0),
            'ts_align': _pick(body, old, 'ts_align', TS_ALIGN, 'spalipy'),
            'ts_forceconv': _pick(body, old, 'ts_forceconv', TS_FORCECONV, 'REF'),
            # measure only the box around the target that the template covers (scripts/pipeline/autophot_web_run.py)
            'ts_crop': _flag(body, old, 'ts_crop', True),
            # AutoPhOT's own plate solve (wcs.redo_wcs): off, our astrometry gives the WCS; turned on for a run where ours fails
            'ap_solve': _flag(body, old, 'ap_solve', False),
            'wdir': str(runs_root() / '.wdir'), 'created': old.get('created') or time.time(),
            'created_by': old.get('created_by') or user}


# ── Who sees a workspace: its owner, the people who opened its share link, admins ──
# Workspaces from before owners existed have no 'owner'; everyone with the page still sees those.

class Forbidden(PipelineError):
    status = 403


def _listed(cfg, key, user):
    return bool(user) and any(m.get('user') == user for m in cfg.get(key) or [])


def role_of(cfg, user='', is_admin=False):
    """'owner' (run, delete, share, everything: the creator and admins) or 'member' (sees the workspace and its
    results: opened the invite link, was given the right to run, or the owner opened running to everyone who can
    open the Pipeline page) or ''. Callers have already checked that the person has an account that can open the page."""
    owner = cfg.get('owner')
    if not owner or is_admin or (user and owner == user):
        return 'owner'
    if user and (_listed(cfg, 'members', user) or _listed(cfg, 'runners', user) or cfg.get('run_all')):
        return 'member'
    return ''


def can_edit(cfg, role, user=''):
    """Settings, images, run / stop / answer: the owner, and the people the owner gave that right
    (one by one, or everyone who can open the Pipeline page)."""
    return role == 'owner' or (role == 'member' and (bool(cfg.get('run_all')) or _listed(cfg, 'runners', user)))


def require(tid, user='', is_admin=False, owner=False, edit=False):
    """The person's role in a workspace; NotFound (not Forbidden) when they may not see it at all.
    owner=True: only its owner; edit=True: the owner, or a person the owner lets run it."""
    cfg = _read_json(tdir(tid) / 'target.json')
    role = role_of(cfg, user, is_admin)
    if not role:
        raise NotFound('No such workspace.')
    if owner and role != 'owner':
        raise Forbidden('Only the owner of this workspace can do that.')
    if edit and not can_edit(cfg, role, user):
        raise Forbidden('Only the owner can change or run this workspace, unless they gave you the right to.')
    return role


def set_run_access(tid, add=None, remove=None, run_all=None):
    """Who besides the owner may change and run the workspace. add: {'user': email, 'name': name} (the caller has
    checked the account can open the Pipeline page); remove: email; run_all: everyone who can open the page."""
    cfg = _read_json(tdir(tid) / 'target.json')
    runners = [r for r in cfg.get('runners') or [] if r.get('user') != remove]
    if add and add.get('user') and add['user'] != cfg.get('owner') and not any(r['user'] == add['user'] for r in runners):
        runners.append({'user': add['user'], 'name': add.get('name') or add['user'], 'at': time.time()})
    cfg['runners'] = runners
    if run_all is not None:
        cfg['run_all'] = bool(run_all)
    _write_json(tdir(tid) / 'target.json', cfg)
    return {'runners': runners, 'run_all': bool(cfg.get('run_all'))}


# ── Images are kept FITS_KEEP_DAYS after they arrive; the owner can add days ──

MAX_KEEP_EXTRA = 30


def keep_seconds(cfg):
    return (config.FITS_KEEP_DAYS + int(cfg.get('keep_extra') or 0)) * 86400


def keep_one_more_day(tid):
    """Move the removal of this workspace's images one day later; returns the days they are kept in all."""
    cfg = _read_json(tdir(tid) / 'target.json')
    extra = int(cfg.get('keep_extra') or 0)
    if extra >= MAX_KEEP_EXTRA:
        raise PipelineError(f'Images can be kept at most {config.FITS_KEEP_DAYS + MAX_KEEP_EXTRA} days.')
    cfg['keep_extra'] = extra + 1
    _write_json(tdir(tid) / 'target.json', cfg)
    return config.FITS_KEEP_DAYS + extra + 1


def _earliest_expiry(cfg, imgs):
    """When the first image / template of the workspace will be removed (epoch seconds), None without any."""
    if not imgs.is_dir():
        return None
    times = [_arrived(cfg, imgs, str(p.relative_to(imgs))) for p in _fits_in(imgs, True)]
    times += [_arrived(cfg, imgs, t['name']) for t in _templates(imgs) if t['active']]
    return min(times) + keep_seconds(cfg) if times else None


# ── Results shared by a link without logging in, behind a password the owner chooses ──

def result_share_create(tid, run, password, user=''):
    """One link for one set of results ('' = the current ones, else an earlier run's id)."""
    import secrets
    from werkzeug.security import generate_password_hash
    run = str(run or '')
    run_paths(tid, run or None)                              # NotFound for a run that does not exist
    pw = str(password or '')
    if not 4 <= len(pw) <= 64:
        raise PipelineError('Choose a password of 4 to 64 characters.')
    cfg = _read_json(tdir(tid) / 'target.json')
    share = {'id': secrets.token_hex(4), 'token': secrets.token_urlsafe(18), 'run': run,
             'hash': generate_password_hash(pw), 'at': time.time(), 'by': user}
    cfg['result_shares'] = (cfg.get('result_shares') or []) + [share]
    _write_json(tdir(tid) / 'target.json', cfg)
    return share


def result_shares(cfg, run=None):
    """The links (id, token, run, time; never the password hash), optionally of one set of results only."""
    return [{k: x.get(k) for k in ('id', 'token', 'run', 'at')} for x in cfg.get('result_shares') or []
            if run is None or x.get('run', '') == run]


def result_share_stop(tid, share_id):
    cfg = _read_json(tdir(tid) / 'target.json')
    shares = cfg.get('result_shares') or []
    if not any(x.get('id') == share_id for x in shares):
        raise NotFound('No such link.')
    cfg['result_shares'] = [x for x in shares if x.get('id') != share_id]
    _write_json(tdir(tid) / 'target.json', cfg)


def find_result_share(token):
    """(tid, share) for a results link, or (None, None)."""
    import hmac
    token = str(token or '')
    for d in _workspaces():
        for x in _read_json(d / 'target.json').get('result_shares') or []:
            if hmac.compare_digest(str(x.get('token') or ''), token):
                return d.name, x
    return None, None


def check_result_password(share, password):
    from werkzeug.security import check_password_hash
    return check_password_hash(str(share.get('hash') or ''), str(password or ''))


def share_on(tid):
    """Turn the invite link on (kept if already on): anyone logged in who opens it can see the workspace and its
    results; whether they may also change and run it is the owner's allow_run switch."""
    import secrets
    cfg = _read_json(tdir(tid) / 'target.json')
    if not (cfg.get('share') or {}).get('token'):
        cfg['share'] = {'token': secrets.token_urlsafe(18), 'at': time.time()}
        _write_json(tdir(tid) / 'target.json', cfg)
    return cfg['share']


def share_off(tid):
    cfg = _read_json(tdir(tid) / 'target.json')
    cfg.pop('share', None)
    cfg['members'] = []
    _write_json(tdir(tid) / 'target.json', cfg)


def join_share(tid, token, user):
    """Open the invite link: the person is remembered as a member, so the workspace is in their list afterwards."""
    import hmac
    cfg = _read_json(tdir(tid) / 'target.json')
    real = (cfg.get('share') or {}).get('token') or ''
    if not real or not hmac.compare_digest(real, str(token or '')):
        raise NotFound('This share link is not valid any more.')
    if role_of(cfg, user) != 'owner' and not any(m.get('user') == user for m in cfg.get('members') or []):
        cfg['members'] = (cfg.get('members') or []) + [{'user': user, 'at': time.time()}]
        _write_json(tdir(tid) / 'target.json', cfg)
    return tid


def _parse_coord(ra, dec):
    try:
        float(ra), float(dec)
        return
    except ValueError:
        pass
    try:
        from astropy import units as u
        from astropy.coordinates import SkyCoord
        SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
    except Exception:
        raise PipelineError('Could not read RA / Dec. Use degrees or 12:34:56.7 / -12:34:56.7.')


def workspace_images(tid):
    """Images in the workspace (header summary), templates, removed ones and stacks."""
    cfg = _read_json(tdir(tid) / 'target.json')
    d = images_dir(tid)
    out = _scan_dir(d, False) if d.is_dir() else {'path': str(d), 'n': 0, 'n_sub': 0, 'files': [], 'missing': 0}
    out['templates'] = _templates(d)
    science = {}
    for f in out['files']:
        science[f.get('band') or ''] = science.get(f.get('band') or '', 0) + 1
    active = {t['band'] for t in out['templates'] if t['active']}
    out['coverage'] = [{'band': b, 'n': n, 'template': b in active} for b, n in sorted(science.items(), key=lambda x: (not x[0], x[0]))]
    out['removed'] = sorted(cfg.get('removed') or [])
    origins = cfg.get('origins') or {}
    ks = keep_seconds(cfg)
    for f in out['files']:
        f['origin'] = origins.get(f['name'], '')
        f['expires'] = _arrived(cfg, d, f['name']) + ks
    for t in out['templates']:
        t['expires'] = _arrived(cfg, d, t['name']) + ks
    out['keep_days'] = config.FITS_KEEP_DAYS + int(cfg.get('keep_extra') or 0)
    out['expired'] = cfg.get('expired') or []
    out['restorable'] = sum(1 for e in out['expired'] if str(e.get('origin', '')).startswith('calibrated:'))
    out['stacks'] = sorted(cfg.get('stacks') or {})
    return out


# ── Retention: results stay, FITS go FITS_KEEP_DAYS after they arrive ──

CLEANUP_EVERY = 3600              # at most one sweep an hour (scheduler job and page opens share it)


def _is_fits_like(name):
    n = name.lower()
    return n.endswith(FITS_EXT) or (n.endswith('.unused') and n[:-7].endswith(FITS_EXT))


def _arrived(cfg, images, rel):
    """When a file in images/ arrived: recorded at upload / hand-over, else the file's own times."""
    t = (cfg.get('added_at') or {}).get(rel)
    if t:
        return float(t)
    try:
        st = (images / rel).stat()
        return max(st.st_mtime, st.st_ctime)
    except OSError:
        return time.time()


def cleanup_expired(force=False):
    """Delete every FITS older than FITS_KEEP_DAYS in every workspace that is not running:
    frames and templates in images/ (by arrival), set-aside ones in .removed/, unfinished uploads,
    and FITS AutoPhOT wrote in images_REDUCED/ and legacy/ (by date). Light curves, tables, figures,
    logs and settings stay. Returns {'files', 'bytes'}; never raises."""
    out = {'files': 0, 'bytes': 0}
    try:
        r = runs_root()
        if not r.is_dir():
            return out
        stamp = r / '.wdir' / '.cleanup'
        now = time.time()
        if not force and stamp.exists() and now - stamp.stat().st_mtime < CLEANUP_EVERY:
            return out
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        for d in sorted(r.iterdir()):
            if d.is_dir() and not d.name.startswith('.') and TID_RE.fullmatch(d.name) and (d / 'target.json').is_file():
                try:
                    n, b = _cleanup_workspace(d, now)
                    out['files'] += n
                    out['bytes'] += b
                except Exception:
                    logger.exception('pipeline: cleanup of %s failed', d.name)
        if out['files']:
            logger.info('pipeline: deleted %d FITS (%.1f GB) older than %d days', out['files'], out['bytes'] / 1e9, config.FITS_KEEP_DAYS)
    except NotConfigured:
        pass
    except Exception:
        logger.exception('pipeline: FITS cleanup failed')
    return out


def _cleanup_workspace(d, now):
    j = _read_json(d / 'job.json')
    if j.get('status') == 'running' and _alive(j.get('pid')):
        return 0, 0
    cfg = _read_json(d / 'target.json')
    keep = keep_seconds(cfg)
    images = d / 'images'
    n = size = 0
    expired = cfg.get('expired') or []
    gone = []

    def drop(p):
        nonlocal n, size
        try:
            size += p.stat().st_size
            p.unlink()
            n += 1
            return True
        except OSError:
            return False

    if images.is_dir():
        for p in sorted(images.rglob('*')):
            if p.is_file() and _is_fits_like(p.name):
                rel = str(p.relative_to(images))
                if now - _arrived(cfg, images, rel) > keep and drop(p):
                    gone.append(rel)
                    expired.append({'name': rel, 'origin': (cfg.get('origins') or {}).get(rel, ''), 'at': now})
    removed = d / '.removed'
    if removed.is_dir():
        for p in sorted(removed.rglob('*')):
            if p.is_file() and _is_fits_like(p.name):
                rel = str(p.relative_to(removed))
                if now - _arrived(cfg, removed, rel) > keep and drop(p):
                    cfg['removed'] = [x for x in cfg.get('removed') or [] if x != rel]
    uploads = d / '.uploads'
    if uploads.is_dir():
        for p in uploads.iterdir():
            if p.is_file() and now - p.stat().st_mtime > 86400:
                drop(p)
    outputs = [reduced_dir(cfg)] + ([x / 'images_REDUCED' for x in (d / 'legacy').iterdir() if x.is_dir()]
                                    if (d / 'legacy').is_dir() else [])
    for base in outputs:
        if base.is_dir():
            for p in base.rglob('*'):
                if p.is_file() and _is_fits_like(p.name) and now - p.stat().st_mtime > keep:
                    drop(p)
    if gone or cfg.get('removed') != _read_json(d / 'target.json').get('removed'):
        for rel in gone:
            (cfg.get('added_at') or {}).pop(rel, None)
        cfg['expired'] = expired[-2000:]
        _write_json(d / 'target.json', cfg)
    return n, size


def restore_expired(tid):
    """Copy again the deleted frames that came from Calibrated_Science (their source is still there)."""
    from . import calibrated
    _busy(tid)
    cfg = _read_json(tdir(tid) / 'target.json')
    paths, missing = [], []
    for e in cfg.get('expired') or []:
        origin = str(e.get('origin') or '')
        if origin.startswith('calibrated:'):
            try:
                paths.append((calibrated.file_path(origin.split(':', 1)[1]), origin))
            except PipelineError:
                missing.append(e['name'])
    added = []
    for src, origin in paths:
        added += add_files(tid, [src], origin=origin)['added']
    return {'added': added, 'missing': missing}


def _templates(d):
    """templates/<filter>_template/*: [{'name', 'band', 'active'}]; .unused ones are kept aside by _place_template."""
    tpl = d / 'templates'
    out = []
    if not tpl.is_dir():
        return out
    for p in sorted(tpl.rglob('*')):
        n = p.name.lower()
        if not p.is_file() or p.name.startswith(('.', 'PSF_model_')) or '.incoming' in p.parts:
            continue
        unused = n.endswith('.unused')
        if not (unused and n[:-7].endswith(FITS_EXT)) and not n.endswith(FITS_EXT):
            continue
        rel = str(p.relative_to(d))
        out.append({'name': rel, 'band': bands.band_of_folder(p.relative_to(tpl)) or '',
                    'active': not unused and n.endswith('.fits')})
    return out


def classify(headers):
    """Standard filter and tag ('LOT rp 300s') of FITS headers read by the page before upload:
    [{'name', 'band', 'how', 'raw', 'tag', 'telescope', 'filter', 'exptime'}]."""
    db = bands.telescope_db(_telescope_file())
    meta = bands.telescope_meta(_telescope_file())
    out = []
    for h in (headers or [])[:5000]:
        if not isinstance(h, dict):
            continue
        name = str(h.get('name') or '')[:300]
        card = {str(k)[:8].upper(): str(v)[:80] for k, v in (h.get('header') or {}).items() if isinstance(k, str)}
        hi = bands.header_info(card, db, meta, name)
        folder_band = bands.band_of_folder(name)
        out.append({'name': name, 'band': hi['band'] or folder_band or '', 'how': hi['how'] or ('folder name' if folder_band else ''),
                    'raw': hi['raw'], 'tag': hi['tag'], 'telescope': hi['telescope'], 'filter': hi['filter'], 'exptime': hi['exptime']})
    return out


def _inside(base, rel):
    base = base.resolve()
    p = (base / (rel or '')).resolve()
    if p != base and base not in p.parents:
        raise NotFound('No such file.')
    return p


def remove_image(tid, rel):
    """Move one image (or template) out of the workspace to .removed/; it can be put back."""
    _busy(tid)
    p = _inside(images_dir(tid), rel)
    if not p.is_file():
        raise NotFound('No such file.')
    rel = str(p.relative_to(images_dir(tid).resolve()))
    trash = tdir(tid) / '.removed' / rel
    trash.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(trash))
    cfg = _read_json(tdir(tid) / 'target.json')
    cfg['removed'] = sorted(set(cfg.get('removed') or []) | {rel})
    _write_json(tdir(tid) / 'target.json', cfg)


def restore_image(tid, rel):
    _busy(tid)
    cfg = _read_json(tdir(tid) / 'target.json')
    if rel not in (cfg.get('removed') or []):
        raise NotFound('No such file.')
    src = _inside(tdir(tid) / '.removed', rel)
    dest = _inside(images_dir(tid), rel)
    if src.is_file() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    cfg['removed'] = sorted(set(cfg.get('removed') or []) - {rel})
    _write_json(tdir(tid) / 'target.json', cfg)


def _count_rows(p):
    try:
        with open(p, 'rb') as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0


def info(tid, user=None, is_admin=False):
    """One workspace for the pages. With a user, 'role' says what that person may do and the owner also gets 'share'."""
    d = tdir(tid)
    cfg = _read_json(d / 'target.json')
    res = _read_json(d / 'result.json')
    red = reduced_dir(cfg)
    job = job_status(tid)
    have = red.is_dir() and any(red.iterdir())
    lc = red / 'LightCurve_Output.csv'
    imgs = images_dir(tid)
    n_images = len(_fits_in(imgs, not cfg.get('top_only', True))) if imgs.is_dir() else 0
    updated = max((p.stat().st_mtime for p in (d / 'target.json', d / 'web_run.log', d / 'result.json') if p.exists()), default=0)
    status = job.get('status') or ('done' if res else 'incomplete' if (d / 'web_run.log').is_file() else '')
    role = role_of(cfg, user or '', is_admin) if user is not None else 'owner'
    return {
        'id': tid, 'name': cfg.get('name', tid), 'target': target_label(cfg), 'owner': cfg.get('owner', ''),
        'owner_name': cfg.get('owner_name') or cfg.get('owner', ''), 'role': role, 'can_edit': can_edit(cfg, role, user or ''),
        'share': cfg.get('share') if role == 'owner' else None, 'run_all': bool(cfg.get('run_all')),
        'runners': [{'user': r.get('user'), 'name': r.get('name') or r.get('user')} for r in cfg.get('runners') or []],
        'members': [m.get('user') for m in cfg.get('members') or []] if role == 'owner' else [],
        'result_shares': result_shares(cfg) if role == 'owner' else [],
        'expires': _earliest_expiry(cfg, imgs), 'keep_days': config.FITS_KEEP_DAYS + int(cfg.get('keep_extra') or 0),
        'cfg': cfg, 'run_cfg': run_cfg(tid), 'result': res, 'reduced': str(red), 'has_results': have,
        'lightcurve_csv': lc.is_file(), 'n_rows': _count_rows(lc), 'n_images': n_images, 'updated': updated,
        'images': str(imgs), 'status': status, 'job': job,
        'n_legacy': sum(1 for x in (d / 'legacy').iterdir() if x.is_dir()) if (d / 'legacy').is_dir() else 0,
    }


def targets(user=None, is_admin=False):
    """The workspaces a person sees: their own, the ones shared with them, and (admins) all. user=None: every one."""
    out = []
    for d in _workspaces():
        try:
            i = info(d.name, user, is_admin)
        except Exception:
            logger.exception('pipeline: could not read workspace %s', d.name)
            continue
        if i['role']:
            out.append(i)
    return out


def delete_target(tid):
    """Move the whole workspace (images, results, settings, log) to <runs>/.deleted/; not erased."""
    d = tdir(tid)
    _busy(tid)
    trash = runs_root() / '.deleted'
    trash.mkdir(exist_ok=True)
    dest = trash / f"{tid}_{time.strftime('%Y%m%d-%H%M%S')}"
    d.rename(dest)
    return str(dest)


# ── Runs (state in job.json so every gunicorn worker sees it) ──

def _alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _finish(d, job, code):
    """Record how a run ended. code=None when the worker that started it is gone (exit.json tells)."""
    if code is None:
        code = _read_json(d / 'exit.json').get('code')
    if job.get('stopping'):
        status = 'stopped'
    elif code == 0 and (d / 'result.json').is_file():
        status = 'done'
    else:
        status = 'failed'
    job = {**job, 'status': status, 'end': time.time(), 'code': code}
    with contextlib.suppress(OSError):
        _write_json(d / 'job.json', job)
    with contextlib.suppress(OSError):
        (d / '.stdin').unlink()
    return job


def job_status(tid):
    d = tdir(tid, must=False)                       # a workspace being created has no target.json yet
    j = _read_json(d / 'job.json')
    if j.get('status') == 'running' and not _alive(j.get('pid')):
        j = _finish(d, j, None)
    return j


def _busy(tid):
    if job_status(tid).get('status') == 'running':
        raise PipelineError('AutoPhOT is running in this workspace.')


def _running_count():
    r = runs_root()
    if not r.is_dir():
        return 0
    n = 0
    for d in r.iterdir():
        if d.is_dir() and not d.name.startswith('.') and TID_RE.fullmatch(d.name):
            j = _read_json(d / 'job.json')
            n += j.get('status') == 'running' and _alive(j.get('pid'))
    return n


def job(tid):
    j = job_status(tid)
    log = tdir(tid) / 'web_run.log'
    try:
        with open(log, 'rb') as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 40000))
            j['log'] = f.read().decode('utf-8', errors='replace')
    except OSError:
        j['log'] = ''
    j['waiting'] = j.get('status') == 'running' and _looks_like_prompt(j['log'])
    j['progress'] = _progress(log)
    j.pop('pid', None)
    return j


PROGRESS_RE = re.compile(rb'^\[(\d+)/(\d+)\]\s+\[(OK|FAIL)\]', re.M)


def _progress(log):
    """AutoPhOT's '[i/N] [OK|FAIL] image' lines → {'done', 'total', 'failed'}; None before the first image ends."""
    try:
        text = log.read_bytes()
    except OSError:
        return None
    hits = PROGRESS_RE.findall(text)
    if not hits:
        return None
    return {'done': len(hits), 'total': max(int(h[1]) for h in hits), 'failed': sum(h[2] == b'FAIL' for h in hits)}


def _looks_like_prompt(log):
    """The last line has no newline, or ends with AutoPhOT's '>' prompt → it waits for input."""
    tail = log[-400:]
    if not tail or tail.endswith('\n'):
        return tail.rstrip().endswith('>')
    return True


@contextlib.contextmanager
def _start_lock():
    r = runs_root()
    r.mkdir(parents=True, exist_ok=True)
    with open(r / '.start.lock', 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def start(tid, user=''):
    d = tdir(tid)
    py, cwd = python(), root()
    if not RUNNER.is_file():
        raise NotConfigured(f'Runner script missing: {RUNNER}')
    with _start_lock():
        _busy(tid)
        if _running_count() >= MAX_RUNNING:
            raise PipelineError(f'{MAX_RUNNING} AutoPhOT runs are already going on this server; try again when one finishes.')
        if not _fits_in(images_dir(tid), False):
            raise PipelineError('Upload at least one FITS image first.')
        cfg = _read_json(d / 'target.json')
        if not (str(cfg.get('ra') or '').strip() and str(cfg.get('dec') or '').strip()):
            raise PipelineError('Enter the target position (RA and Dec) first.')
        _parse_coord(cfg['ra'], cfg['dec'])
        archive_previous(tid)                        # the previous run moves to legacy/<time>/
        for name in ('result.json', 'exit.json'):
            (d / name).unlink(missing_ok=True)
        shutil.copyfile(d / 'target.json', d / RUN_CFG)
        fifo = d / '.stdin'
        with contextlib.suppress(FileNotFoundError):
            fifo.unlink()
        os.mkfifo(fifo, 0o600)
        sync_telescope_yml()
        (d / 'web_run.log').write_text(f'$ autophot {d.name}\n')
        log = open(d / 'web_run.log', 'a')           # append: answers written by the web page are kept
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        wfd = os.open(fifo, os.O_WRONLY)             # kept open in the child, so stdin never hits EOF
        os.set_blocking(rfd, True)
        try:
            # cwd is the workspace, so whatever AutoPhOT drops in its working folder stays there;
            # the runner imports AutoPhOT from AUTOPHOT_DIR
            proc = subprocess.Popen([str(py), '-u', str(RUNNER), str(d)], cwd=str(d), stdin=rfd, stdout=log,
                                    stderr=subprocess.STDOUT, text=True, env={**config.child_env(), 'AUTOPHOT_DIR': str(cwd)},
                                    start_new_session=True, pass_fds=(wfd,))
        except Exception:
            log.close()
            with contextlib.suppress(OSError):
                fifo.unlink()
            raise
        finally:
            os.close(rfd)
            os.close(wfd)
        state = {'status': 'running', 'pid': proc.pid, 'start': time.time(), 'by': user}
        _write_json(d / 'job.json', state)

    def wait():
        code = proc.wait()
        log.close()
        _finish(d, _read_json(d / 'job.json') or state, code)

    threading.Thread(target=wait, daemon=True, name=f'autophot-{tid}').start()
    logger.info('pipeline: %s started AutoPhOT in %s (pid %s)', user or '?', tid, proc.pid)


def answer(tid, text):
    """Send one line to AutoPhOT's stdin ('' = Enter, use the default) and note it in the log."""
    d = tdir(tid)
    if job_status(tid).get('status') != 'running':
        raise PipelineError('AutoPhOT is not running.')
    line = str(text or '').replace('\r', ' ').replace('\n', ' ')[:500]
    fifo = d / '.stdin'
    try:
        if not stat.S_ISFIFO(fifo.lstat().st_mode):
            raise OSError('not a FIFO')
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        raise PipelineError('AutoPhOT is not reading input right now.')
    try:
        os.write(fd, (line + '\n').encode())
    finally:
        os.close(fd)
    with open(d / 'web_run.log', 'a') as f:
        f.write(line + '   ⟵ sent from the web page\n')


def stop(tid):
    d = tdir(tid)
    j = job_status(tid)
    if j.get('status') != 'running':
        raise PipelineError('AutoPhOT is not running.')
    j['stopping'] = True
    _write_json(d / 'job.json', j)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(j['pid'], signal.SIGKILL)          # the whole group, including nCPU > 1 workers


# ── Output files (everything in <fits_dir>_REDUCED) ──

def run_paths(tid, run=None):
    """The current run (run=None) or an archived one (legacy/<run>/): {'reduced', 'log', 'result', 'cfg'}."""
    d = tdir(tid)
    if not run:
        cfg = run_cfg(tid)
        return {'reduced': reduced_dir(cfg), 'log': d / 'web_run.log', 'result': d / 'result.json', 'cfg': cfg}
    if not LEGACY_RE.match(run) or not (d / 'legacy' / run).is_dir():
        raise NotFound('No such run.')
    base = d / 'legacy' / run
    return {'reduced': base / 'images_REDUCED', 'log': base / 'web_run.log', 'result': base / 'result.json',
            'cfg': _read_json(base / 'target.json')}


PROBLEM_RE = re.compile(r'^\[(ERROR|CRITICAL)\]\s*(.*)')


def run_problems(tid, run=None, limit=12):
    """What AutoPhOT reported as errors in a run's log ([ERROR] lines with their indented continuation),
    each once, in order: [{'text', 'n'}] (n = how many times it came)."""
    try:
        lines = run_paths(tid, run)['log'].read_text(errors='replace').splitlines()
    except (OSError, NotFound):
        return []
    found, cur = [], None
    for line in lines:
        m = PROBLEM_RE.match(line.strip()) if line[:1] == '[' else None
        if m:
            cur = [m.group(2).strip()]
            found.append(cur)
        elif cur is not None and line.startswith((' ', '\t')) and line.strip() and not line.strip().startswith(('Traceback', 'File ', 'raise ')):
            if len(cur) < 6:
                cur.append(line.strip())
        else:
            cur = None
    out, seen = [], {}
    for parts in found:
        text = ' '.join(parts)
        if text.startswith('Type ') or not text:
            continue
        if text in seen:
            out[seen[text]]['n'] += 1
            continue
        seen[text] = len(out)
        out.append({'text': text, 'n': 1})
    return out[:limit]


def run_cfg(tid):
    """Settings the current run was started with; target.json for runs from before run_target.json existed."""
    d = tdir(tid)
    return _read_json(d / RUN_CFG) or _read_json(d / 'target.json')


def safe_out(tid, rel='', run=None):
    base = run_paths(tid, run)['reduced'].resolve()
    return base, _inside(base, rel)


def kind(name):
    n = name.lower()
    if n.endswith(IMAGE_EXT):
        return 'image'
    if n.endswith('.csv'):
        return 'csv'
    if n.endswith('.pdf'):
        return 'pdf'
    if n.endswith(FITS_EXT):
        return 'fits'
    if n.endswith(TEXT_EXT):
        return 'text'
    return 'other'


def listing(tid, rel='', run=None):
    base, d = safe_out(tid, rel, run)
    if not d.is_dir():
        raise NotFound('No such folder.')
    rel = str(d.relative_to(base)) if d != base else ''
    dirs, files = [], []
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if p.name.startswith('.') or p.is_symlink():
            continue
        r = str(p.relative_to(base))
        if p.is_dir():
            sub = [x for x in p.rglob('*') if x.is_file()]
            dirs.append({'name': p.name, 'path': r, 'n_files': len(sub),
                         'n_images': sum(1 for x in sub if kind(x.name) == 'image'), 'mtime': p.stat().st_mtime})
        else:
            st = p.stat()
            files.append({'name': p.name, 'path': r, 'kind': kind(p.name), 'size': st.st_size, 'mtime': st.st_mtime,
                          'lightcurve': p.name.startswith('LightCurve')})
    crumbs, acc = [], ''
    for part in Path(rel).parts if rel else []:
        acc = f'{acc}/{part}' if acc else part
        crumbs.append({'name': part, 'path': acc})
    return {'base': str(base), 'rel': rel, 'crumbs': crumbs, 'dirs': dirs, 'files': files}


# ── All AutoPhOT settings, read from AutoPhOT's databases/default_input.yml (keys, defaults, comments) ──

# Keys the main form handles or the runner fills in: not listed
FORM_KEYS = {'fits_dir', 'target_name', 'target_ra', 'target_dec', 'nCPU', 'wdir',
             'catalog.use_catalog', 'template_subtraction.do_subtraction', 'template_subtraction.method',
             'template_subtraction.download_templates', 'template_subtraction.templates_size',
             'template_subtraction.alignment_method', 'template_subtraction.forceconv'}
COMMON_KEYS = [
    'restart', 'select_filter', 'selected_filters', 'global_verbose_level', 'plot_format', 'preprocessing.trim_image',
    'cosmic_rays.remove_cmrays', 'photometry.detection_limit', 'photometry.upper_limit_snr', 'photometry.force_photometry',
    'photometry.crowded_field', 'photometry.apply_colorterms', 'wcs.redo_wcs', 'wcs.solver', 'wcs.projection_type',
    'catalog.catalog_custom_fpath', 'zeropoint.fit_method', 'limiting_magnitude.snr_thresholds',
    'limiting_magnitude.inject_source_location', 'limiting_magnitude.n_jobs',
    'postprocessing.transient_color_correction',
]
# A setting whose name contains one of these is shown as a password field (name hint only)
MASKED_NAME_HINTS = ('pwd', 'api', 'passw', 'wsid', 'bot_id')
_schema_cache = {}


def ytext(v):
    """A value → one line of YAML (True, 0.4, [g, r], null, .inf …), used for display and comparison."""
    import yaml
    s = yaml.safe_dump(v, default_flow_style=True, width=10 ** 9, allow_unicode=True).strip()
    return s[:-3].strip() if s.endswith('...') else s


def _lookup(data, path):
    for k in path:
        if not isinstance(data, dict) or k not in data:
            raise KeyError(k)
        data = data[k]
    return data


def schema():
    """[{'key': 'photometry.detection_limit', 'section', 'name', 'sub', 'type', 'help', 'note', 'default', 'kind'}]."""
    import yaml
    p = root() / 'databases' / 'default_input.yml'
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        raise NotConfigured(f'{p} not found.')
    if key in _schema_cache:
        return _schema_cache[key]
    text = p.read_text()
    data = (yaml.safe_load(text) or {}).get('default_input') or {}
    items, stack, note = [], [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            note = []
            continue
        if s.startswith('#'):
            note.append(s.lstrip('#').strip())
            continue
        m = re.match(r'^( *)([^\s:#][^:#]*?):(.*)$', line)
        if not m:
            continue
        indent, name, rest = len(m.group(1)), m.group(2).strip(), m.group(3)
        cm = re.search(r'\s#\s?(.*)$', rest)
        comment = cm.group(1).strip() if cm else ''
        value = (rest[:cm.start()] if cm else rest).strip()
        stack = [(i, k) for i, k in stack if i < indent]
        if indent == 0:                                   # default_input:
            note = []
            continue
        path = [k for _, k in stack] + [name]
        if not value and not comment:                     # a block (photometry:, wcs: …)
            stack.append((indent, name))
            note = []
            continue
        try:
            default = _lookup(data, path)
        except KeyError:
            note = []
            continue
        typ, _, help_ = comment.partition('---') if '---' in comment else ('', '', comment)
        k = '.'.join(path)
        if k not in FORM_KEYS and not help_.strip().startswith('Runtime'):
            kind_ = 'bool' if isinstance(default, bool) else 'number' if isinstance(default, (int, float)) else 'text'
            items.append({'key': k, 'section': path[0] if len(path) > 1 else 'general', 'name': name,
                          'sub': '.'.join(path[1:-1]), 'type': typ.strip(), 'help': help_.strip(), 'note': ' '.join(note),
                          'default': ytext(default), 'kind': kind_,
                          'secret': any(w in name.lower() for w in MASKED_NAME_HINTS)})
        note = []
    _schema_cache.clear()
    _schema_cache[key] = items
    return items


def clean_overrides(raw):
    """{key: one line of YAML} from the page → {key: value}; unknown keys and defaults are dropped."""
    import yaml
    if not isinstance(raw, dict):
        raise PipelineError('Invalid settings.')
    known = {it['key']: it for it in schema()}
    out = {}
    for k, txt in raw.items():
        if k not in known:
            continue
        try:
            v = yaml.safe_load(str(txt)) if str(txt).strip() != '' else None
        except yaml.YAMLError as e:
            raise PipelineError(f'{k}: not valid YAML ({e})')
        if ytext(v) != known[k]['default'] and v != yaml.safe_load(known[k]['default']):     # 3 and 3.0 are equal
            out[k] = v
    return out


def settings_view(tid=None):
    items = schema()
    cfg = _read_json(tdir(tid) / 'target.json') if tid else {}
    titles = {}
    for it in items:
        titles[it['section']] = titles.get(it['section'], 0) + 1
    return {'items': items, 'common': [k for k in COMMON_KEYS if any(it['key'] == k for it in items)],
            'sections': [{'id': s, 'n': n} for s, n in titles.items()],
            'overrides': {k: ytext(v) for k, v in (cfg.get('overrides') or {}).items()}}


# ── Photometry table: LightCurve_Output.csv (one row per image) and colours ──

def _f(v):
    try:
        x = float(v)
        return x if x == x else None                     # NaN → None
    except (TypeError, ValueError):
        return None


def _truthy(v):
    return str(v).strip().lower() in ('true', '1', '1.0', 'yes')


def photometry(tid, run=None):
    """{'rows', 'limits': [(column, snr)], 'bands', 'colors', 'magsys', 'files'}; None without results."""
    import csv as _csv
    base, _ = safe_out(tid, '', run)
    p = base / 'LightCurve_Output.csv'
    if not p.is_file():
        return None
    with open(p, newline='') as fh:
        data = list(_csv.DictReader(fh))
    cols = list(data[0].keys()) if data else []
    limits = sorted(((c, float(m.group(1).replace('p', '.'))) for c in cols
                     for m in [re.fullmatch(r'limiting_mag_(\d+(?:p\d+)?)s2n', c)] if m), key=lambda x: x[1])
    rows = []
    for r in data:
        name = r.get('filename', '')
        rows.append({
            'name': name, 'folder': name if name and '/' not in name and (base / name).is_dir() else '',
            'date': (r.get('date') or '').replace('T', ' ')[:19], 'mjd': _f(r.get('mjd')), 'filter': r.get('filter', ''),
            'psf': _f(r.get('mag_psf')), 'psf_err': _f(r.get('mag_psf_err')),
            'ap': _f(r.get('mag_ap')), 'ap_err': _f(r.get('mag_ap_err')),
            'snr': _f(r.get('snr')), 'det': _truthy(r.get('is_detection')),
            'limits': [_f(r.get(c)) for c, _ in limits],
            'zp': _f(r.get('zp_psf')), 'zp_err': _f(r.get('zp_psf_err')), 'zp_ok': _truthy(r.get('zp_psf_reliable')),
            'zp_flags': [x.strip() for x in re.split(r';|\|', r.get('zp_psf_flags') or '') if x.strip() and x.strip().lower() != 'nan'],
            'zp_neff': _f(r.get('zp_psf_neff')), 'zp_n': _f(r.get('zp_psf_nsrc')),
            'fwhm': _f(r.get('image_fwhm')), 'airmass': _f(r.get('airmass')),
            'exptime': _f(r.get('exposure_time')), 'telescope': (r.get('telescope') or '').strip(),
            'ts': _truthy(r.get('preformsubtractioned')),     # measured on the difference image (False when subtraction fell back to the frame)
        })
    rows.sort(key=lambda x: (x['mjd'] is None, x['mjd'] or 0))
    from astropy.time import Time  # AutoPhOT's date column holds MJD; UTC from MJD
    for r in rows:
        if r['mjd'] is not None:
            r['date'] = Time(r['mjd'], format='mjd').iso[:19]
    bands = {}
    for r in rows:
        b = bands.setdefault(r['filter'], {'n': 0, 'det': 0, 'lims': [[] for _ in limits]})
        b['n'] += 1
        b['det'] += r['det']
        for i, v in enumerate(r['limits']):
            if v is not None:
                b['lims'][i].append(v)
    for b in bands.values():
        b['lim_median'] = [sorted(v)[len(v) // 2] if v else None for v in b.pop('lims')]
    colors = {}
    for method in ('PSF', 'AP'):
        cp = base / f'LightCurve_{method}_Colors.dat'
        if cp.is_file():
            with open(cp, newline='') as fh:
                colors[method] = [{'date': c.get('Date', ''), 'mjd': _f(c.get('MJD')), 'color': c.get('Color', ''),
                                   'value': _f(c.get('Value')), 'err': _f(c.get('Error'))} for c in _csv.DictReader(fh)]
    magsys = sorted({r.get('magsys', '') for r in data if r.get('magsys')})
    files = [f for f in ('LightCurve_Output.csv', 'LightCurve_PSF.dat', 'LightCurve_AP.dat',
                         'Detections_LightCurve_Output_PSF.csv', 'Detections_LightCurve_Output_AP.csv') if (base / f).is_file()]
    return {'rows': rows, 'limits': limits, 'bands': bands, 'colors': colors, 'magsys': ', '.join(magsys), 'files': files}


NO_TS_TAG = '_(w/o_TS)'       # appended to the telescope, no spaces, so every row stays 5 columns (e.g. SLT_(w/o_TS))


def export_rows(tid, method='PSF', limit=3.0, run=None):
    """The light curve as points: [{'mjd', 'magnitude', 'magnitude_error' (None = upper limit), 'upper',
    'filter', 'telescope'}]. Non-detections are limits at `limit` σ. An image measured without template
    subtraction (off, or it fell back to the frame) gets _(w/o_TS) after its telescope."""
    ph = photometry(tid, run)
    if not ph:
        raise NotFound('No results yet.')
    key = 'psf' if method.upper() == 'PSF' else 'ap'
    li = next((i for i, (_, snr) in enumerate(ph['limits']) if abs(snr - float(limit)) < 1e-6), None)
    out = []
    for r in ph['rows']:
        if r['mjd'] is None:
            continue
        mag, err = r[key], r[key + '_err']
        lim = r['limits'][li] if li is not None else None
        if r['det'] and mag is not None:
            point = {'magnitude': round(mag, 3), 'magnitude_error': round(err, 3) if err is not None else None, 'upper': False}
        elif lim is not None:
            point = {'magnitude': round(lim, 3), 'magnitude_error': None, 'upper': True}
        else:
            continue
        point.update(mjd=round(r['mjd'], 5), filter=re.sub(r'\s+', '_', r['filter']) or 'unknown',
                     telescope=(re.sub(r'\s+', '_', r['telescope']) or 'unknown') + ('' if r['ts'] else NO_TS_TAG))
        out.append(point)
    return out


def export_text(tid, method='PSF', limit=3.0, header=True, run=None):
    """Plain-text light curve for import, space-separated: MJD magnitude error filter telescope;
    a limit is written >mag with error nan."""
    lines = []
    for pt in export_rows(tid, method, limit, run):
        m = ('>' if pt['upper'] else '') + f"{pt['magnitude']:.3f}"
        e = f"{pt['magnitude_error']:.3f}" if pt['magnitude_error'] is not None else 'nan'
        lines.append((f"{pt['mjd']:.5f}", m, e, pt['filter'], pt['telescope']))
    head = ('MJD', 'magnitude', 'error', 'filter', 'telescope')
    widths = [max(len(x[i]) for x in lines + [head]) for i in range(5)]

    def fmt(row):
        return '  '.join(v.ljust(w) for v, w in zip(row, widths)).rstrip()
    return '\n'.join(([fmt(head)] if header else []) + [fmt(x) for x in lines]) + '\n'


# ── Import into a Kinder object's photometry (the page asks three times first) ──

def _import_args(body):
    method = 'AP' if str(body.get('method') or 'PSF').upper() == 'AP' else 'PSF'
    try:
        limit = float(body.get('limit') or 3)
    except (TypeError, ValueError):
        limit = 3.0
    run = str(body.get('run') or '') or None
    with_limits = bool(body.get('with_limits', True))
    return method, limit, run, with_limits


def import_preview(tid, body):
    """What an import would do: the object as Kinder knows it, the points, how many look like duplicates."""
    from app.db.transient import TNSObjectDB
    method, limit, run, with_limits = _import_args(body)
    name = str(body.get('object') or '').strip()[:80]
    if not name:
        raise PipelineError('Enter the Kinder object.')
    found = TNSObjectDB.resolve_object_name(name) or TNSObjectDB.resolve_object_name(name.replace(' ', ''))
    if not found:
        raise NotFound(f'{name} is not a Kinder object.')
    points = [pt for pt in export_rows(tid, method, limit, run) if with_limits or not pt['upper']]
    existing = TNSObjectDB.get_photometry(found)
    have = {(round(float(e['mjd']), 4), str(e.get('filter') or ''), str(e.get('telescope') or '')) for e in existing if e.get('mjd') is not None}
    dup = sum(1 for pt in points if (round(pt['mjd'], 4), pt['filter'], pt['telescope']) in have)
    done = [i for i in _read_json(tdir(tid) / 'target.json').get('imports') or []
            if i.get('object') == found and not i.get('undone') and i.get('run') == run and i.get('method') == method]
    return {'object': found, 'points': points, 'n_existing': len(existing), 'n_duplicates': dup,
            'already': done[-1] if done else None, 'method': method, 'limit': limit, 'run': run}


def import_points(tid, body, user=''):
    """Write the points into the object's photometry; `confirm` must repeat the object name exactly."""
    from app.db.transient import TNSObjectDB
    pv = import_preview(tid, body)
    if str(body.get('confirm') or '').strip() != pv['object']:
        raise PipelineError(f'Type {pv["object"]} to confirm.')
    if not pv['points']:
        raise PipelineError('No points to import.')
    pts = [{k: pt[k] for k in ('mjd', 'magnitude', 'magnitude_error', 'filter', 'telescope')} for pt in pv['points']]
    ids = TNSObjectDB.add_photometry_batch_ids(pv['object'], pts)
    rec = {'id': time.strftime('%Y%m%d-%H%M%S'), 'time': time.time(), 'by': user, 'object': pv['object'],
           'method': pv['method'], 'limit': pv['limit'], 'run': pv['run'], 'n_points': len(pts),
           'n_inserted': len(ids), 'phot_ids': ids}
    cfg = _read_json(tdir(tid) / 'target.json')
    cfg['imports'] = (cfg.get('imports') or []) + [rec]
    _write_json(tdir(tid) / 'target.json', cfg)
    logger.info('pipeline: %s imported %d/%d points of %s into %s', user or '?', len(ids), len(pts), tid, pv['object'])
    return {k: v for k, v in rec.items() if k != 'phot_ids'}


def undo_import(tid, import_id, user=''):
    """Delete exactly the points one import added (points that were already there are untouched)."""
    from app.db.transient import TNSObjectDB
    cfg = _read_json(tdir(tid) / 'target.json')
    rec = next((i for i in cfg.get('imports') or [] if i.get('id') == import_id and not i.get('undone')), None)
    if not rec:
        raise NotFound('No such import.')
    n = TNSObjectDB.delete_photometry_points(rec['object'], rec.get('phot_ids') or [])
    rec.update(undone=time.time(), undone_by=user, n_deleted=n)
    _write_json(tdir(tid) / 'target.json', cfg)
    logger.info('pipeline: %s undid import %s of %s (%d points deleted from %s)', user or '?', import_id, tid, n, rec['object'])
    return {'deleted': n, 'object': rec['object']}


def imports(tid):
    return [{k: v for k, v in i.items() if k != 'phot_ids'} for i in _read_json(tdir(tid) / 'target.json').get('imports') or []]


# AutoPhOT zeropoint flags → plain sentences; unknown ones are shown as they are
_ZP_FLAG_RULES = [
    (r'([\d.]+) mag ZP gradient along (\w+)', 'The zeropoint drifts by {0} mag along {1} across the detector'),
    (r'calibrator residuals spatially correlated \(N_eff=(\d+) of (\d+)\)',
     'Calibrator residuals are spatially correlated: effectively {0} independent of {1} stars'),
    (r'very few calibrators \(N=(\d+)\)', 'Very few calibrators (N={0})'),
    (r'non-finite zeropoint', 'The zeropoint is not finite'),
]


def zp_flag_text(flag):
    for pat, msg in _ZP_FLAG_RULES:
        m = re.search(pat, flag)
        if m:
            return msg.format(*m.groups())
    return flag


# ── Per image: measured or not, and why (web_run.log [i/N] [OK|FAIL], LOG_*.log, IncorrectFiles.txt) ──

_FAIL_HINTS = [
    (r"unexpected keyword argument 'maxiter'",
     'AutoPhOT bug in the low-S/N (MCMC) PSF fit, fixed in the AlexLee24/autophot fork. Update AutoPhOT and run again.'),
    (r'get_wcs returned None|No pre-existing WCS', 'The image has no WCS and astrometry.net could not solve it.'),
    (r'(?i)no sources|too few sources|not enough sources', 'Too few stars were found in the image.'),
    (r'(?i)catalog', 'The calibration catalog could not be used for this image.'),
]


def _strip_fits(name):
    return re.sub(r'\.(fits|fit|fts)(\.fz|\.gz)?$', '', name, flags=re.I)


def _ap_base(name):
    """The name AutoPhOT gives an image (its output folder, LOG_<base>.log, the CSV's filename column):
    the file name without extension, spaces and dots as '_', '_APT' / '_ERROR' dropped (main.py)."""
    base = os.path.splitext(Path(name).name)[0]
    return base.replace(' ', '_').replace('.', '_').replace('_APT', '').replace('_ERROR', '')


def _log_errors(log_path):
    msgs = []
    try:
        for line in log_path.read_text(errors='replace').splitlines():
            m = re.search(r'Message\s*:\s*(.+)$', line) or re.search(r'(?:^|\s)ERROR - (?!Type\s*:)(.+)$', line)
            if m and m.group(1).strip() not in msgs:
                msgs.append(m.group(1).strip())
    except OSError:
        pass
    return msgs


def _rel_to(path, folder):
    try:
        return str(Path(path).relative_to(folder))
    except ValueError:
        return Path(path).name


def _header_filter(path):
    try:
        from astropy.io import fits
        h = fits.getheader(path)
        return str(h.get('FILTER') or h.get('FILTER1') or '')
    except Exception:
        return ''


def image_status(tid, run=None):
    """{'n_in', 'n_ok', 'failed': [...]}; None when nothing ran."""
    rp = run_paths(tid, run)
    cfg, base, log = rp['cfg'], rp['reduced'], rp['log']
    entries = {}
    if log.is_file():
        for line in log.read_text(errors='replace').splitlines():
            m = re.match(r'^\[(\d+)/(\d+)\]\s+\[(OK|FAIL)\]\s+(.+?)(?:\s+\(exit code (-?\d+)\))?\s*$', line)
            if m:
                entries[m.group(4)] = m.group(3)
    ok_names = set()
    if (base / 'LightCurve_Output.csv').is_file():
        import csv as _csv
        with open(base / 'LightCurve_Output.csv', newline='') as fh:
            ok_names = {_ap_base(r['filename']) for r in _csv.DictReader(fh) if r.get('filename')}
    if not entries:
        fits_dir = Path(cfg.get('fits_dir', ''))
        if fits_dir.is_dir():
            for p in _fits_in(fits_dir, not cfg.get('top_only', True)):
                entries[str(p)] = 'OK' if _ap_base(p.name) in ok_names else 'FAIL'
    if not entries:
        return None
    failed = []
    for path, status in entries.items():
        name = _ap_base(path)
        if (status == 'OK' and not ok_names) or name in ok_names:
            continue
        logs = list(base.rglob(f'LOG_{name}.log')) if base.is_dir() else []
        errors = _log_errors(logs[0]) if logs else []
        hint = next((h for pat, h in _FAIL_HINTS for e in errors[-1:] if re.search(pat, e)), '')
        failed.append({'name': Path(path).name, 'path': path, 'status': status, 'errors': errors, 'hint': hint,
                       'filter': _header_filter(path), 'rel': _rel_to(path, cfg.get('fits_dir', '')),
                       'log': str(logs[0].relative_to(base)) if logs else '',
                       'folder': str(logs[0].parent.relative_to(base)) if logs else ''})
    bad = Path(cfg.get('fits_dir', '')) / 'IncorrectFiles.txt'
    if bad.is_file():
        for line in bad.read_text(errors='replace').splitlines():
            p = line.strip()
            if p and not any(f['path'] == p for f in failed) and p not in entries:
                failed.append({'name': Path(p).name, 'path': p, 'status': 'SKIPPED', 'errors': [], 'filter': _header_filter(p),
                               'rel': _rel_to(p, cfg.get('fits_dir', '')),
                               'hint': 'Skipped before photometry: the FITS header lacks TELESCOP, INSTRUME or FILTER.',
                               'log': '', 'folder': ''})
    n_in = len(entries) + sum(1 for f in failed if f['status'] == 'SKIPPED')
    return {'n_in': n_in, 'n_ok': n_in - len(failed), 'failed': failed}


# ── Legacy: before each run, the previous output, log, result and settings move to legacy/<time>/ ──

def archive_previous(tid):
    d = tdir(tid)
    cfg = _read_json(d / RUN_CFG) or _read_json(d / 'target.json')
    red = reduced_dir(cfg)
    has_out = red.is_dir() and any(red.iterdir())
    log, res = d / 'web_run.log', d / 'result.json'
    if not has_out and not log.exists():
        return None
    when = _read_json(res).get('time') or (log.stat().st_mtime if log.exists() else red.stat().st_mtime)
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(when))
    dest, i = d / 'legacy' / stamp, 1
    while dest.exists():
        i += 1
        dest = d / 'legacy' / f'{stamp}-{i}'
    dest.mkdir(parents=True)
    if has_out:
        red.rename(dest / 'images_REDUCED')
    elif red.is_dir():
        red.rmdir()
    for p in (log, res, d / 'job.json', d / 'exit.json', d / 'web_stack.log'):
        if p.exists():
            p.rename(dest / p.name)
    (d / RUN_CFG).unlink(missing_ok=True)
    snap = dict(cfg)
    if (dest / 'web_run.log').exists():
        snap['_archived_from'] = str(red)
    _write_json(dest / 'target.json', snap)
    prune_legacy(tid)
    return dest.name


def prune_legacy(tid):
    """Keep the newest LEGACY_KEEP archived runs; older ones are deleted for good."""
    d = tdir(tid) / 'legacy'
    if not d.is_dir():
        return []
    runs = sorted((x for x in d.iterdir() if x.is_dir() and LEGACY_RE.match(x.name)), key=lambda x: x.name, reverse=True)
    gone = []
    for old in runs[LEGACY_KEEP:]:
        shutil.rmtree(old, ignore_errors=True)
        gone.append(old.name)
    return gone


def legacy_runs(tid):
    d = tdir(tid) / 'legacy'
    out = []
    if not d.is_dir():
        return out
    for r in sorted((x for x in d.iterdir() if x.is_dir() and LEGACY_RE.match(x.name)), key=lambda x: x.name, reverse=True):
        cfg = _read_json(r / 'target.json')
        res = _read_json(r / 'result.json')
        lc = r / 'images_REDUCED' / 'LightCurve_Output.csv'
        ok = fail = 0
        if (r / 'web_run.log').is_file():
            for line in (r / 'web_run.log').read_text(errors='replace').splitlines():
                m = re.match(r'^\[\d+/\d+\]\s+\[(OK|FAIL)\]', line)
                if m:
                    ok += m.group(1) == 'OK'
                    fail += m.group(1) == 'FAIL'
        size = sum(p.stat().st_size for p in r.rglob('*') if p.is_file())
        when = res.get('time') or ((r / 'web_run.log').stat().st_mtime if (r / 'web_run.log').exists() else None)
        out.append({'id': r.name, 'time': when, 'finished': bool(res), 'elapsed': res.get('elapsed'),
                    'n_ok': ok, 'n_fail': fail, 'n_rows': _count_rows(lc),
                    'catalog': cfg.get('catalog', ''), 'stack': cfg.get('stack', False), 'subtraction': cfg.get('subtraction', False),
                    'sub_method': cfg.get('sub_method', ''), 'n_overrides': len(cfg.get('overrides') or {}), 'size': size})
    return out


def delete_legacy(tid, run):
    """Move one archived run to <runs>/.deleted/ (not erased)."""
    run_paths(tid, run)
    trash = runs_root() / '.deleted'
    trash.mkdir(exist_ok=True)
    dest = trash / f'{tid}_legacy_{run}_{time.strftime("%Y%m%d-%H%M%S")}'
    (tdir(tid) / 'legacy' / run).rename(dest)
    return str(dest)


# ── Name → coordinates (CDS Sesame) ──

def resolve(name):
    """J2000 position for an object name from SIMBAD / NED / VizieR via CDS Sesame; only the name is sent."""
    import xml.etree.ElementTree as ET

    import requests
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    name = str(name or '').strip()[:80]
    if not name:
        raise PipelineError('Enter a name.')
    try:
        r = requests.get('https://cds.unistra.fr/cgi-bin/nph-sesame/-ox/SNV', params={name: ''}, timeout=10)
        r.raise_for_status()
        root_el = ET.fromstring(r.content)
    except Exception:
        raise PipelineError('Could not reach CDS Sesame.')
    for res in root_el.iter('Resolver'):
        ra, dec = res.findtext('jradeg'), res.findtext('jdedeg')
        if ra and dec:
            c = SkyCoord(float(ra) * u.deg, float(dec) * u.deg)
            src = (res.get('name') or '').split('=')[-1] or 'Sesame'
            return {'ra': c.ra.to_string(u.hourangle, sep=':', precision=2, pad=True),
                    'dec': c.dec.to_string(u.deg, sep=':', precision=1, alwayssign=True, pad=True),
                    'source': src}
    raise NotFound(f'{name} was not found in SIMBAD, NED or VizieR.')


# ── telescope.yml: the repository copy is the template; each server reads and writes its own copy ──
#
#   app/services/pipeline/telescope.yml   template, in git; AutoPhOT never writes it
#   <runs>/.wdir/telescope.yml            this server's copy (not in git): AutoPhOT reads it and adds the
#                                         telescopes it meets; the Telescopes page edits it
# Whenever a Pipeline page opens (and before each run), telescopes, instruments and keys that are in the
# template but missing here are added; nothing already here is changed (a value still 'not_given_by_user'
# here counts as missing).

TELESCOPE_FIELDS = {'Name', 'pixel_scale', 'gain', 'readnoise', 'saturate', 'airmass', 'mjd', 'date', 'exptime',
                    'GAIN', 'RDNOISE', 'AIRMASS', 'SATURATE'}
UNSET = 'not_given_by_user'
_tel_synced = {}                  # (template mtime, local mtime) of the last check in this process


def local_telescope_yml():
    return runs_root() / '.wdir' / 'telescope.yml'


def _telescope_file():
    """The file to read: this server's copy, or the template before there is one."""
    try:
        p = local_telescope_yml()
    except NotConfigured:
        return TELESCOPE_YML
    return p if p.is_file() else TELESCOPE_YML


def _add_missing(dst, src, path=()):
    """Copy into dst what src has and dst lacks, recursively; returns what was added ('LOT / SOPHIA', 'LOT / SOPHIA / gain')."""
    import copy
    added = []
    for k, v in src.items():
        here = path + (str(k),)
        if k not in dst or (dst[k] == UNSET and v != UNSET):
            dst[k] = copy.deepcopy(v)
            added.append(' / '.join(x for x in here if x != 'INSTRUME'))
        elif isinstance(v, dict) and isinstance(dst[k], dict):
            added += _add_missing(dst[k], v, here)
    return added


def _keep_history(text, who):
    history = runs_root() / '.wdir' / 'telescope_history'
    history.mkdir(parents=True, exist_ok=True)
    (history / f"telescope-{time.strftime('%Y%m%d-%H%M%S')}-{who}.yml").write_text(text)
    for stale in sorted(history.glob('telescope-*.yml'))[:-TELESCOPE_HISTORY_KEEP]:
        stale.unlink(missing_ok=True)


def sync_telescope_yml():
    """Make sure this server has its own telescope.yml and add what the template has that it lacks.

    Returns {'created': bool, 'added': [...]} ; never raises (a page must still open)."""
    import yaml
    out = {'created': False, 'added': []}
    try:
        wdir = runs_root() / '.wdir'
        wdir.mkdir(parents=True, exist_ok=True)
        local = wdir / 'telescope.yml'
        with open(wdir / '.telescope.lock', 'a') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                if local.is_symlink():                   # before: a link to the repository copy
                    text = local.read_text() if local.exists() else ''
                    local.unlink()
                    local.write_text(text or TELESCOPE_YML.read_text())
                    logger.warning('pipeline: %s was a link to the repository; now a copy of it on this server', local)
                if not local.exists():
                    shutil.copyfile(TELESCOPE_YML, local)
                    out['created'] = True
                    logger.info('pipeline: %s created from the template', local)
                key = (TELESCOPE_YML.stat().st_mtime, local.stat().st_mtime)
                if _tel_synced.get(str(local)) == key or _running_count():
                    return out                           # nothing new, or AutoPhOT may be writing it
                template = yaml.safe_load(TELESCOPE_YML.read_text()) or {}
                old = local.read_text()
                mine = yaml.safe_load(old) or {}
                if not isinstance(template, dict) or not isinstance(mine, dict):
                    return out
                out['added'] = _add_missing(mine, template)
                if out['added']:
                    _keep_history(old, 'before-template')
                    tmp = local.with_name(f'.telescope.yml.{os.getpid()}.tmp')
                    tmp.write_text(yaml.safe_dump(mine, sort_keys=True, allow_unicode=True, default_flow_style=False))
                    os.replace(tmp, local)
                    logger.info('pipeline: added from the template to %s: %s', local, ', '.join(out['added'][:20]))
                _tel_synced[str(local)] = (TELESCOPE_YML.stat().st_mtime, local.stat().st_mtime)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    except NotConfigured:
        pass
    except Exception:
        logger.exception('pipeline: could not check telescope.yml against the template')
    return out


def telescope_text():
    try:
        return _telescope_file().read_text()
    except FileNotFoundError:
        return ''


def _telescope_rows(data, template=None):
    rows = []
    for tel, block in (data or {}).items():
        for inst, cfg in ((block or {}).get('INSTRUME') or {}).items():
            cfg = cfg or {}
            in_template = template is None or inst in (((template.get(tel) or {}).get('INSTRUME')) or {})
            filters = {k: v for k, v in cfg.items()
                       if k not in TELESCOPE_FIELDS and not str(k).startswith('filter_key')}
            rows.append({'telescope': str(tel), 'instrument': str(inst), 'pixel_scale': cfg.get('pixel_scale'),
                         'gain': cfg.get('gain'), 'readnoise': cfg.get('readnoise'), 'saturate': cfg.get('saturate'),
                         'filters': sorted({str(v) for v in filters.values()}), 'n_filter_names': len(filters),
                         'local_only': not in_template})
    return rows


def telescope_summary():
    """Each telescope + instrument with the values that matter most (local_only: not in the template); None when it does not parse."""
    import yaml
    try:
        template = yaml.safe_load(TELESCOPE_YML.read_text()) or {}
    except (OSError, yaml.YAMLError):
        template = {}
    try:
        return _telescope_rows(yaml.safe_load(telescope_text()) or {}, template if isinstance(template, dict) else {})
    except yaml.YAMLError:
        return None


def save_telescope(text, user=''):
    """Replace this server's telescope.yml after checking it; the previous version goes to <runs>/.wdir/telescope_history/."""
    import yaml
    text = str(text or '').replace('\r\n', '\n')
    if len(text) > 1024 * 1024:
        raise PipelineError('telescope.yml is too large.')
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PipelineError(f'Not valid YAML: {e}')
    if not isinstance(data, dict) or not data:
        raise PipelineError('telescope.yml must list telescopes (TELESCOP value: {INSTRUME: {...}}).')
    for tel, block in data.items():
        if not isinstance(block, dict) or not isinstance(block.get('INSTRUME'), dict):
            raise PipelineError(f'{tel}: needs an INSTRUME block with one entry per instrument.')
        for inst, cfg in block['INSTRUME'].items():
            if not isinstance(cfg, dict):
                raise PipelineError(f'{tel} / {inst}: must be key: value pairs.')
    if _running_count():
        raise PipelineError('AutoPhOT is running and may add to telescope.yml; save when it has finished.')
    sync_telescope_yml()                                 # this server's copy exists (not configured → NotConfigured below)
    local = local_telescope_yml()
    if not text.endswith('\n'):
        text += '\n'
    old = telescope_text()
    if old == text:
        return {'changed': False}
    if old:
        _keep_history(old, re.sub(r'[^A-Za-z0-9_.-]', '_', user.split('@')[0])[:30] or 'web')
    tmp = local.with_name(f'.telescope.yml.{os.getpid()}.tmp')
    tmp.write_text(text)
    os.replace(tmp, local)
    logger.info('pipeline: %s saved telescope.yml (%d telescopes)', user or '?', len(data))
    return {'changed': True}
