"""Lab › Special Run › Euclid-SLSN: Euclid DR1-Foundation (+ Q1) host-galaxy cutouts of every SLSN Kinder knows.

Targets = transient.objects whose type starts with 'SLSN' + the literature list in slsn_list.txt
(an entry within MATCH_ARCSEC of a DB object is the same SN; the DB name wins, the list name is kept as alias).

run() (one at a time across gunicorn workers, via an flock on OUT_DIR/.run.lock):
  1. async ADQL lists every MER VIS tile centre of DR1-Foundation and Q1 (~14 000 tiles, 0.5° wide);
  2. targets within 0.45° of a tile centre get an exact footprint query (INTERSECTS on fov);
  3. covered targets get VIS + NISP Y/J/H cutouts (CUTOUT_ARCSEC radius) and a PNG
     (VIS asinh stretch | NISP H/J/Y colour), all under DATA_DIR/special_run/euclid_slsn/<slug>/.
Progress lives in state.json (read by any worker), the outcome in results.json.
"""
import fcntl
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app.paths import DATA_DIR

logger = logging.getLogger(__name__)

OUT_DIR = DATA_DIR / 'special_run' / 'euclid_slsn'
STATE_FILE = OUT_DIR / 'state.json'
RESULTS_FILE = OUT_DIR / 'results.json'
LOCK_FILE = OUT_DIR / '.run.lock'
LIST_FILE = Path(__file__).with_name('slsn_list.txt')

MATCH_ARCSEC = 3.0          # list entry ↔ DB object
RELEASES = ('dr1', 'q1')    # schemas on the ESA archive, preferred first
TILE_NEAR_DEG = 0.45        # pre-selection around a tile centre (tiles are ~0.53° on a side)
CUTOUT_ARCSEC = 15.0        # cutout radius → 30" × 30" (300 px VIS at 0.1"/px)
BANDS = ('VIS', 'NIR_Y', 'NIR_J', 'NIR_H')
WORKERS = 4
QUERY_TIMEOUT = 90          # s per ESA TAP query (astroquery's http.client calls have no timeout of their own)
CUTOUT_TIMEOUT = 180        # s per cutout download


def _timed(fn, timeout, *args, **kwargs):
    """Call fn in a daemon thread and give up after `timeout` s, so a silent ESA server cannot hang the run."""
    box = {}

    def _call():
        try:
            box['r'] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 -- re-raised in the caller
            box['e'] = e
    th = threading.Thread(target=_call, daemon=True, name='euclid-call')
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f'no answer from ESA in {timeout} s')
    if 'e' in box:
        raise box['e']
    return box.get('r')

_SLUG = re.compile(r'[^A-Za-z0-9_.+-]+')


def slug(name: str) -> str:
    return _SLUG.sub('_', name).strip('_') or 'target'


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1, default=str))
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- targets

def load_list() -> list[dict]:
    rows = []
    for line in LIST_FILE.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        p = line.split()
        try:
            rows.append({'name': p[0], 'ra': float(p[1]), 'dec': float(p[2]), 'redshift': float(p[3]),
                         'type': 'SLSN-I', 'quality': p[8], 'survey': p[9], 'explosion_mjd': float(p[6])})
        except (IndexError, ValueError):
            logger.warning('[EUCLID-SLSN] bad list line: %s', line)
    return rows


def load_db_slsn() -> list[dict]:
    from app.db import get_db_connection
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(name_prefix, ''), name, ra, dec, redshift, type FROM transient.objects "
                    "WHERE type ILIKE 'SLSN%%' AND ra IS NOT NULL AND dec IS NOT NULL ORDER BY name")
        out = []
        for prefix, name, ra, dec, z, typ in cur.fetchall():
            out.append({'name': f'{prefix} {name}'.strip(), 'obj_name': name, 'ra': float(ra), 'dec': float(dec),
                        'redshift': float(z) if z is not None else None, 'type': typ, 'in_db': True})
        return out


def _sep_arcsec(ra1, dec1, ra2, dec2):
    import numpy as np
    r1, d1, r2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    s = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * np.cos(d2) * np.sin((r2 - r1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(s, 0, 1)))) * 3600.0


def merged_targets() -> list[dict]:
    import numpy as np
    db = load_db_slsn()
    targets = list(db)
    if db:
        dra = np.array([t['ra'] for t in db])
        ddec = np.array([t['dec'] for t in db])
    by_name = {t['obj_name'].lower(): i for i, t in enumerate(db)}
    for row in load_list():
        if db:
            sep = _sep_arcsec(dra, ddec, row['ra'], row['dec'])
            i = by_name.get(row['name'].lower(), int(np.argmin(sep)))   # same name wins even when positions differ
            if row['name'].lower() in by_name or sep[i] < MATCH_ARCSEC:
                db[i].setdefault('aliases', []).append(row['name'])
                db[i].update(quality=row['quality'], survey=row['survey'])
                if db[i]['redshift'] is None:
                    db[i]['redshift'] = row['redshift']
                continue
        targets.append({**row, 'in_db': False})
    return targets


_TNS_NAME = re.compile(r'^\d{4}[A-Za-z]{1,4}$')
SURVEY_ID_BASE = 1_100_000_000   # TNS-style ids are year*1e6+rank, i.e. ≥ 1.9e9 for modern years


def import_list_to_db(dry_run=True) -> dict:
    """Add list SLSNs that Kinder does not have yet (no object of the same name, none within MATCH_ARCSEC).

    New rows: type SLSN-I, redshift from the list, discovery_date = explosion MJD, source 'SLSN list (Special Run)'.
    Objects already in the DB under another type are reported, never changed."""
    import numpy as np
    from app.db import get_db_connection
    rows = load_list()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, ra, dec, type FROM transient.objects WHERE ra IS NOT NULL AND dec IS NOT NULL")
        db = cur.fetchall()
        names = {n.lower(): t for n, _, _, t in db}
        dra = np.array([float(r[1]) for r in db])
        ddec = np.array([float(r[2]) for r in db])
        add, other_type = [], []
        for r in rows:
            hit = names.get(r['name'].lower())
            if hit is None and len(db):
                sep = _sep_arcsec(dra, ddec, r['ra'], r['dec'])
                i = int(np.argmin(sep))
                if sep[i] < MATCH_ARCSEC:
                    hit = db[i][3]
                    r = {**r, 'db_name': db[i][0]}
            if hit is None:
                add.append(r)
            elif not str(hit or '').upper().startswith('SLSN'):
                other_type.append({'name': r['name'], 'db_name': r.get('db_name', r['name']), 'db_type': hit})
        if not dry_run and add:
            from datetime import date
            from app.db.transient import _tns_name_to_kinder_id
            now_mjd = (date.today() - date(1858, 11, 17)).days
            # obj_id has no default: TNS-style names use Kinder's year*1e6+rank id; survey names (PTF12dam, DES…)
            # take ids from SURVEY_ID_BASE up, a range no TNS year reaches.
            cur.execute("SELECT COALESCE(MAX(obj_id), %s) FROM transient.objects WHERE obj_id >= %s AND obj_id < %s",
                        (SURVEY_ID_BASE, SURVEY_ID_BASE, SURVEY_ID_BASE + 10_000_000))
            next_id = cur.fetchone()[0] + 1
            for r in add:
                tns = bool(_TNS_NAME.match(r['name']))
                kid = _tns_name_to_kinder_id(r['name'][:4] + r['name'][4:].lower()) if tns else None
                oid = kid if kid else next_id
                if not kid:
                    next_id += 1
                cur.execute(
                    "INSERT INTO transient.objects (obj_id, kinder_id, name, name_prefix, type, ra, dec, redshift, "
                    "discovery_date, source_group, received_date, last_modified_date, status, tag) "
                    "VALUES (%s, %s, %s, %s, 'SLSN-I', %s, %s, %s, %s, 'SLSN list (Special Run)', %s, %s, 'Inbox', "
                    "'{}'::text[]) ON CONFLICT DO NOTHING",
                    (oid, kid, r['name'], 'SN' if tns else '', r['ra'], r['dec'], r['redshift'],
                     int(r['explosion_mjd']), now_mjd, now_mjd))
            conn.commit()
    return {'list': len(rows), 'added' if not dry_run else 'to_add': [r['name'] for r in add],
            'other_type': other_type}


# ---------------------------------------------------------------- state

def status() -> dict:
    st = _read_json(STATE_FILE, {'state': 'idle'})
    if st.get('state') == 'running' and time.time() - st.get('heartbeat', 0) > 300:
        st['state'] = 'stale'      # worker died mid-run
    return st


def results() -> dict:
    return _read_json(RESULTS_FILE, {})


class _Progress:
    def __init__(self):
        self.st = {'state': 'running', 'started': _now(), 'step': 'Starting', 'done': 0, 'total': 0,
                   'log': [], 'heartbeat': time.time()}
        self._lock = threading.Lock()

    def log(self, msg, **kw):
        with self._lock:
            self.st['log'] = (self.st['log'] + [f'{datetime.now():%H:%M:%S} {msg}'])[-60:]
            self.st.update(kw, heartbeat=time.time())
            _write_json(STATE_FILE, self.st)
        logger.info('[EUCLID-SLSN] %s', msg)

    def tick(self):
        with self._lock:
            self.st['done'] += 1
            self.st['heartbeat'] = time.time()
            _write_json(STATE_FILE, self.st)


# ---------------------------------------------------------------- Euclid

def _euclid():
    from astroquery.esa.euclid import Euclid
    Euclid.ROW_LIMIT = -1
    return Euclid


def _tile_centres(E):
    """Distinct MER VIS tile centres of every release. Async job: synchronous TAP stops at 2000 rows
    (DR1-Foundation alone has ~14 000 VIS mosaics)."""
    out = {}
    for rel in RELEASES:
        job = E.launch_job_async(f"SELECT DISTINCT tile_index, ra, dec FROM {rel}.mosaic_product "
                                 "WHERE product_type='DpdMerBksMosaic' AND filter_name='VIS'")
        if job is None:
            raise RuntimeError(f'Euclid {rel} tile listing failed')
        r = job.get_results()
        for t, a, d in zip(r['tile_index'], r['ra'], r['dec']):
            out[(rel, int(t))] = (float(a), float(d))
    return [(rel, t, a, d) for (rel, t), (a, d) in out.items()]


def _mosaics_at(E, ra, dec):
    """Best covering MER tile for each release in RELEASES order (DR1 first): the tile that has the most of
    BANDS, nearest centre on ties; every band then comes from that same tile."""
    for rel in RELEASES:
        q = (f"SELECT file_name, file_path, filter_name, instrument_name, tile_index, ra, dec FROM {rel}.mosaic_product "
             "WHERE product_type='DpdMerBksMosaic' "
             f"AND INTERSECTS(CIRCLE({ra:.7f},{dec:.7f},0.0003),fov)=1")
        job = E.launch_job(q)
        if job is None:
            raise RuntimeError(f'Euclid {rel} footprint query failed')
        tiles = {}
        for r in job.get_results():
            band = str(r['filter_name'])
            if band not in BANDS:
                continue
            tile = tiles.setdefault(str(r['tile_index']), {'bands': {}, 'sep': float(
                _sep_arcsec(float(r['ra']), float(r['dec']), ra, dec))})
            tile['bands'].setdefault(band, {'file': f"{r['file_path']}/{r['file_name']}",
                                            'instrument': str(r['instrument_name']),
                                            'tile': str(r['tile_index']), 'release': rel})
        if tiles:
            best = min(tiles.values(), key=lambda x: (-len(x['bands']), x['sep']))
            if 'VIS' in best['bands'] or len(best['bands']) >= 2:
                return best['bands']
    return {}


_tls = threading.local()


def _thread_client():
    """astroquery's Euclid client is not safe to share between download threads (empty files)."""
    if not hasattr(_tls, 'client'):
        from astroquery.esa.euclid import EuclidClass
        _tls.client = EuclidClass()
    return _tls.client


def _fits_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 2880:
        return False
    try:
        from astropy.io import fits
        with fits.open(path) as h:
            return any(x.data is not None for x in h)
    except Exception:
        return False


def _cutout(mosaic, ra, dec, out: Path, refresh=False, tries=3):
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    src = out.with_suffix('.src')      # which mosaic the cached cutout came from (Q1 → DR1 re-downloads)
    if not refresh and _fits_ok(out) and src.exists() and src.read_text() == mosaic['file']:
        return out
    for attempt in range(tries):
        out.unlink(missing_ok=True)
        try:
            _timed(_thread_client().get_cutout, CUTOUT_TIMEOUT,
                   file_path=mosaic['file'], instrument=mosaic['instrument'], id=mosaic['tile'],
                   coordinate=SkyCoord(ra, dec, unit='deg'), radius=CUTOUT_ARCSEC * u.arcsec, output_file=str(out))
        except Exception as e:
            logger.warning('[EUCLID-SLSN] cutout %s try %d: %s', out, attempt + 1, e)
            if isinstance(e, TimeoutError):
                _tls.__dict__.pop('client', None)   # the abandoned call may still be using it
        if _fits_ok(out):
            src.write_text(mosaic['file'])
            return out
        time.sleep(1.5 * (attempt + 1))
    out.unlink(missing_ok=True)
    raise RuntimeError('cutout empty after retries')


# ---------------------------------------------------------------- PNG

def _mtf(m, x):
    """Midtones transfer function (PixInsight / Siril): maps m → 0.5, keeps 0 → 0 and 1 → 1."""
    return ((m - 1) * x) / ((2 * m - 1) * x - m)


def _stretch(img, shadows=-2.8, target=0.25):
    """Screen Transfer Function autostretch, as PixInsight's STF / Siril's autostretch:
    normalise to [0,1], clip shadows at median + shadows·MAD(σ), then a midtones transfer that puts the
    sky median at `target`. The same maths runs in the browser (static/js/special_run_euclid.js)."""
    import numpy as np
    a = np.asarray(img, dtype=float)
    a = np.where(np.isfinite(a), a, np.nanmedian(a))
    lo, hi = a.min(), a.max()
    x = (a - lo) / max(hi - lo, 1e-30)
    med = np.median(x)
    mad = 1.4826 * np.median(np.abs(x - med))
    c0 = min(max(med + shadows * mad, 0.0), 1.0)
    m = _mtf(target, med - c0)
    y = np.clip((x - c0) / max(1 - c0, 1e-30), 0, 1)
    return _mtf(m, y)


LS_LAYERS = {'dr10': 'ls-dr10', 'dr11': 'ls-dr11'}
LS_URL = 'https://www.legacysurvey.org/viewer/jpeg-cutout'
_ls_lock = threading.Lock()   # the viewer answers 429 to parallel requests: one at a time per process


def ls_cutout(slug_: str, key: str, t: dict | None = None) -> Path | None:
    """Legacy Survey colour JPEG on the Euclid cutout grid (0.1"/px, same size), cached next to the FITS."""
    import requests
    layer = LS_LAYERS.get(key)
    if not layer:
        return None
    out = OUT_DIR / slug_ / f'LS_{key}.jpg'
    if out.exists() and out.stat().st_size > 500:
        return out
    if t is None:
        t = next((r for r in results().get('covered', []) if r.get('slug') == slug_), None)
    if t is None:
        return None
    size = int(round(CUTOUT_ARCSEC * 2 / 0.1)) + 1
    with _ls_lock:
        if out.exists() and out.stat().st_size > 500:
            return out
        for attempt in range(5):
            try:
                r = requests.get(LS_URL, params={'ra': f"{t['ra']:.6f}", 'dec': f"{t['dec']:.6f}", 'layer': layer,
                                                 'pixscale': '0.1', 'size': size}, timeout=40)
            except requests.RequestException as e:
                logger.warning('[EUCLID-SLSN] LS %s %s: %s', slug_, key, e)
                r = None
            if r is not None and r.status_code == 200 and r.headers.get('content-type', '').startswith('image/'):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.content)
                return out
            time.sleep(2 ** attempt)
    return None


def pixels(slug_: str, band: str):
    """(float32 array, target x, target y) of one cutout, for the browser renderer; None when missing."""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    path = OUT_DIR / slug_ / f'{band}.fits'
    if not _fits_ok(path):
        return None
    res = results()
    t = next((r for r in res.get('covered', []) if r.get('slug') == slug_), None)
    with fits.open(path) as h:
        hdu = next(x for x in h if x.data is not None)
        data = np.asarray(hdu.data, dtype='<f4')
        px = py = None
        if t:
            try:
                px, py = (float(v) for v in WCS(hdu.header).world_to_pixel_values(t['ra'], t['dec']))
            except Exception:
                pass
    return data, px, py


def make_png(t: dict, files: dict, out: Path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import patheffects
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS

    def load(band):
        with fits.open(files[band]) as h:
            hdu = next(x for x in h if x.data is not None)
            return np.asarray(hdu.data, dtype=float), WCS(hdu.header)

    panels = []
    if 'VIS' in files:
        img, w = load('VIS')
        panels.append(('Euclid VIS', _stretch(img), w, img.shape))
    if all(b in files for b in ('NIR_H', 'NIR_J', 'NIR_Y')):
        chans = [load(b) for b in ('NIR_H', 'NIR_J', 'NIR_Y')]
        shape = min(c[0].shape for c in chans)
        rgb = np.dstack([_stretch(c[0][:shape[0], :shape[1]]) for c in chans])
        panels.append(('NISP H / J / Y', rgb, chans[0][1], shape))
    elif 'NIR_H' in files:
        img, w = load('NIR_H')
        panels.append(('NISP H', _stretch(img), w, img.shape))
    if not panels:
        return None

    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.6), dpi=110)
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor('#111')
    for ax, (label, img, w, shape) in zip(axes, panels):
        ax.imshow(img, origin='lower', cmap='gray' if img.ndim == 2 else None, interpolation='nearest')
        x, y = w.world_to_pixel_values(t['ra'], t['dec'])
        gap, arm = shape[0] * 0.035, shape[0] * 0.07
        for dx, dy in ((1, 0), (0, 1)):
            ax.plot([x + dx * gap, x + dx * (gap + arm)], [y + dy * gap, y + dy * (gap + arm)], color='#F39F5A', lw=1.6)
        pix = abs(w.proj_plane_pixel_scales()[0].to_value('arcsec'))
        bar = 5.0 / pix
        halo = [patheffects.withStroke(linewidth=2.5, foreground='black')]
        ax.plot([shape[1] * 0.06, shape[1] * 0.06 + bar], [shape[0] * 0.06] * 2, color='white', lw=2, path_effects=halo)
        ax.text(shape[1] * 0.06 + bar / 2, shape[0] * 0.09, '5"', color='white', ha='center', fontsize=9, path_effects=halo)
        ax.text(0.03, 0.96, label, transform=ax.transAxes, color='white', fontsize=10, va='top', path_effects=halo)
        ax.text(0.97, 0.96, 'N↑ E←', transform=ax.transAxes, color='white', fontsize=9, va='top', ha='right', path_effects=halo)
        ax.set_axis_off()
    z = f"z = {t['redshift']:.4g}" if t.get('redshift') is not None else ''
    fig.suptitle(f"{t['name']}   {t.get('type', '')}   {z}", color='white', fontsize=12, y=0.97)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.9, wspace=0.03)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


# ---------------------------------------------------------------- run

def _process(t, mosaics, refresh, prog):
    d = OUT_DIR / slug(t['name'])
    d.mkdir(parents=True, exist_ok=True)
    files, errors = {}, []
    for band, m in mosaics.items():
        try:
            files[band] = _cutout(m, t['ra'], t['dec'], d / f'{band}.fits', refresh)
        except Exception as e:  # one band failing must not lose the others
            errors.append(f'{band}: {e}')
    png = None
    try:
        png = make_png(t, files, d / 'host.png')
    except Exception as e:
        errors.append(f'png: {e}')
        logger.exception('[EUCLID-SLSN] png %s', t['name'])
    prog.log(f"{t['name']}: {len(files)} band(s)" + (f" — {'; '.join(errors)}" if errors else ''))
    first = next(iter(mosaics.values()))
    return {**t, 'covered': True, 'tile': first['tile'], 'release': first['release'],
            'bands': sorted(files), 'png': png is not None, 'slug': slug(t['name']), 'errors': errors}


def run(refresh=False):
    """Blocking run; returns False when another run holds the lock."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return False
    prog = _Progress()
    try:
        import numpy as np
        prog.log('Loading SLSN targets (Kinder DB + list)', step='Targets')
        targets = merged_targets()
        prog.log(f'{len(targets)} targets ({sum(t["in_db"] for t in targets)} in Kinder DB)')

        E = _euclid()
        prog.log('Listing Euclid DR1 + Q1 MER tiles', step='Tiles')
        tiles = _timed(_tile_centres, 4 * QUERY_TIMEOUT, E)
        tra = np.array([a for _, _, a, _ in tiles])
        tdec = np.array([d for _, _, _, d in tiles])
        near = [t for t in targets if _sep_arcsec(tra, tdec, t['ra'], t['dec']).min() < TILE_NEAR_DEG * 3600]
        prog.log(f'{len(tiles)} tiles; {len(near)} targets near Euclid coverage', step='Footprints', total=len(near))

        covered = []
        for t in near:
            m = {}
            for attempt in range(2):
                try:
                    m = _timed(_mosaics_at, QUERY_TIMEOUT, E, t['ra'], t['dec'])
                    break
                except Exception as e:
                    prog.log(f"{t['name']}: footprint query failed ({e})" + (', retrying' if attempt == 0 else ''))
            if m:
                covered.append((t, m))
            first = next(iter(m.values()), {})
            prog.log(f"{t['name']}: " + (f"{first['release'].upper()} tile {first['tile']}" if m else 'outside Euclid'))
            prog.tick()
        prog.log(f'{len(covered)} targets inside Euclid mosaics; downloading cutouts', step='Cutouts',
                 done=0, total=len(covered))

        out = []
        with ThreadPoolExecutor(WORKERS) as pool:
            futs = [pool.submit(_process, t, m, refresh, prog) for t, m in covered]
            for f in futs:
                out.append(f.result())
                prog.tick()

        prog.log('Fetching Legacy Survey DR10 / DR11 comparison cutouts', step='Legacy Survey',
                 done=0, total=len(out))
        for r in out:
            got = []
            for key in LS_LAYERS:
                if refresh:
                    (OUT_DIR / r['slug'] / f'LS_{key}.jpg').unlink(missing_ok=True)
                if ls_cutout(r['slug'], key, r):
                    got.append(key)
            r['ls'] = got
            prog.tick()
        covered_names = {t['name'] for t, _ in covered}
        res = {'finished': _now(), 'n_targets': len(targets), 'n_tiles': len(tiles),
               'covered': sorted(out, key=lambda r: r['name']),
               'not_covered': [{'name': t['name'], 'ra': t['ra'], 'dec': t['dec'], 'in_db': t['in_db']}
                               for t in targets if t['name'] not in covered_names],
               'cutout_arcsec': CUTOUT_ARCSEC * 2}
        _write_json(RESULTS_FILE, res)
        prog.log(f'Done: {len(out)} hosts with Euclid imaging', state='done', step='Done', finished=_now())
    except Exception as e:
        logger.exception('[EUCLID-SLSN] run failed')
        prog.log(f'Failed: {e}', state='error', step='Error')
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return True


def start(refresh=False) -> bool:
    """Start run() in a daemon thread; False when a run is already going."""
    st = status()
    if st.get('state') == 'running':
        return False
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:   # cheap pre-check so the caller gets an honest answer
        with open(LOCK_FILE, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return False
    _write_json(STATE_FILE, {'state': 'running', 'started': _now(), 'step': 'Starting', 'done': 0, 'total': 0,
                             'log': [], 'heartbeat': time.time()})
    threading.Thread(target=run, kwargs={'refresh': refresh}, daemon=True, name='euclid-slsn').start()
    return True
