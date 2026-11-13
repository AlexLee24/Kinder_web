"""Tools › Sky Cutouts: Euclid DR1 / Q1 cutouts at any position, next to colour images of other surveys
(Legacy Survey DR10 / DR11 / model / residual, HSC PDR3, Pan-STARRS1, SDSS, unWISE, GALEX, VLASS).

Reuses the archive helpers of the Euclid-SLSN special run (app/services/special_run/euclid_slsn.py):
footprint query (DR1 first, then Q1, every covering tile), astroquery cutouts with timeouts and retries, and the
serial, cached Legacy Survey viewer fetch.

    resolve(text)                       'ra dec' (deg or sexagesimal), a Kinder object name, or a Sesame name
    coverage(ra, dec)                   {'covered', 'release', 'tile', 'bands'} — the first tile with real pixels
    pixels(ra, dec, fov, band)          (float32 array, target x, target y, binning) for the browser stretch
    survey_jpeg(ra, dec, fov, key)      Path of a survey colour JPEG (key in SURVEYS); 404 when the survey has no data there
    image_jpeg(ra, dec, fov, src)       Path of a JPEG for any source (SOURCES): Euclid is STF-stretched on the server
    sources()                           [{key, label, group, kind, bands?}] — what /api/cutouts/sources lists

Files live under DATA_DIR/euclid_cutouts/<ra>_<dec>/ (coverage.json, <band>_<fov>.fits, LS_<key>_<fov>.jpg);
folders untouched for CACHE_DAYS are removed when a new position is fetched.
"""
import json
import logging
import shutil
import threading
import time
from pathlib import Path

from app.paths import DATA_DIR
from app.services.special_run import euclid_slsn as es

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / 'euclid_cutouts'
CACHE_DAYS = 14
FOV_CHOICES = (10, 20, 30, 45, 60, 90, 120)      # arcsec, full width
MAX_SIDE = 640                                   # px sent to the browser per band (larger cutouts are binned)
BANDS = es.BANDS
# key → Legacy Survey viewer layer (the viewer also serves HSC, SDSS, unWISE, … as layers), or None for Pan-STARRS1
SURVEYS = {
    'dr10': 'ls-dr10', 'dr11': 'ls-dr11', 'dr10_model': 'ls-dr10-model', 'dr10_resid': 'ls-dr10-resid',
    'hsc': 'hsc-dr3', 'ps1': None, 'sdss': 'sdss', 'unwise': 'unwise-neo7', 'galex': 'galex', 'vlass': 'vlass1.2',
}
SURVEY_LABELS = {
    'dr10': 'Legacy Survey DR10', 'dr11': 'Legacy Survey DR11', 'dr10_model': 'Legacy Survey DR10 model',
    'dr10_resid': 'Legacy Survey DR10 residual', 'hsc': 'HSC PDR3', 'ps1': 'Pan-STARRS1', 'sdss': 'SDSS',
    'unwise': 'unWISE', 'galex': 'GALEX', 'vlass': 'VLASS',
}
EUCLID_SOURCES = {    # key → (label, bands as R, G, B or a single band)
    'vis': ('Euclid VIS', ('VIS',)), 'nisp': ('Euclid NISP H / J / Y colour', ('NIR_H', 'NIR_J', 'NIR_Y')),
    'nisp_y': ('Euclid NISP Y', ('NIR_Y',)), 'nisp_j': ('Euclid NISP J', ('NIR_J',)), 'nisp_h': ('Euclid NISP H', ('NIR_H',)),
}
PS1_FILES = 'https://ps1images.stsci.edu/cgi-bin/ps1filenames.py'
PS1_CUT = 'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class EuclidError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _pos_dir(ra: float, dec: float) -> Path:
    return CACHE_DIR / f'{ra:.5f}_{dec:+.5f}'


def _prune():
    """Drop cached positions nobody looked at for CACHE_DAYS (cheap: one listdir per new position)."""
    if not CACHE_DIR.exists():
        return
    cutoff = time.time() - CACHE_DAYS * 86400
    for d in CACHE_DIR.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------- resolve

def resolve(text: str) -> dict:
    """Coordinates from free text. Order: numbers / sexagesimal, Kinder object, Sesame (CDS) name."""
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    q = (text or '').strip()
    if not q or len(q) > 100:
        raise EuclidError('Give coordinates (RA Dec) or an object name.')
    parts = q.replace(',', ' ').split()
    if len(parts) == 2:
        try:
            ra, dec = float(parts[0]), float(parts[1])
            if 0 <= ra < 360 and -90 <= dec <= 90:
                return {'ra': ra, 'dec': dec, 'source': 'coordinates'}
        except ValueError:
            pass
    if any(c in q for c in ':hms') or len(parts) == 6:
        try:
            c = SkyCoord(q.replace(',', ' '), unit=(u.hourangle, u.deg))
            return {'ra': float(c.ra.deg), 'dec': float(c.dec.deg), 'source': 'coordinates'}
        except Exception:
            pass
    hit = _kinder_object(q)
    if hit:
        return hit
    import re
    names = [q] + ([f'SN {q}', f'AT {q}'] if re.fullmatch(r'\d{4}[A-Za-z]{1,4}', q) else [])   # TNS name, no prefix
    for name in names:
        try:
            c = SkyCoord.from_name(name)
            return {'ra': float(c.ra.deg), 'dec': float(c.dec.deg), 'source': 'Sesame', 'name': name}
        except Exception:
            continue
    raise EuclidError(f'Could not resolve "{q}" (use RA Dec in degrees or hh:mm:ss ±dd:mm:ss).', 404)


def _kinder_object(q: str) -> dict | None:
    import re
    name = re.sub(r'^(SN|AT)\s*', '', q, flags=re.I).strip()
    try:
        from app.db import get_db_connection
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(name_prefix, ''), name, ra, dec FROM transient.objects "
                        "WHERE lower(name) = lower(%s) AND ra IS NOT NULL LIMIT 1", (name,))
            row = cur.fetchone()
    except Exception:
        logger.exception('[EUCLID] Kinder lookup %s', q)
        return None
    if not row:
        return None
    return {'ra': float(row[2]), 'dec': float(row[3]), 'source': 'Kinder',
            'name': f'{row[0]} {row[1]}'.strip(), 'obj_name': row[1]}


# ---------------------------------------------------------------- Euclid

def coverage(ra: float, dec: float) -> dict:
    """First covering tile (DR1, then Q1) whose VIS cutout has real pixels at the position; cached per position."""
    d = _pos_dir(ra, dec)
    cache = d / 'coverage.json'
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except ValueError:
            pass
    with _lock(str(d)):
        if cache.exists():
            return json.loads(cache.read_text())
        if not d.exists():
            _prune()
        d.mkdir(parents=True, exist_ok=True)
        E = es._euclid()
        try:
            cands = es._timed(es._mosaics_at, es.QUERY_TIMEOUT, E, ra, dec)
        except Exception as e:
            raise EuclidError(f'Euclid archive did not answer ({e}).', 502)
        out = {'covered': False, 'reason': 'outside Euclid DR1 / Q1'}
        for c in cands:
            band = 'VIS' if 'VIS' in c else next(iter(c))
            try:
                probe = es._cutout(c[band], ra, dec, d / f'probe_{band}.fits', radius_arcsec=3)
            except Exception as e:
                logger.warning('[EUCLID] probe %s: %s', c[band]['tile'], e)
                continue
            ok = es._has_data(probe, ra, dec, box=8)
            probe.unlink(missing_ok=True)
            probe.with_suffix('.src').unlink(missing_ok=True)
            if ok:
                first = c[band]
                out = {'covered': True, 'release': first['release'], 'tile': first['tile'],
                       'bands': sorted(c), 'mosaics': c}
                break
            out = {'covered': False, 'reason': 'inside a tile footprint, but no Euclid pixels there'}
        cache.write_text(json.dumps(out))
        return out


def pixels(ra: float, dec: float, fov: int, band: str):
    """(float32 2-D array, target x, target y, bin factor) of one Euclid band; EuclidError when not available."""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    if band not in BANDS:
        raise EuclidError('Unknown band.', 404)
    cov = coverage(ra, dec)
    if not cov.get('covered') or band not in cov.get('mosaics', {}):
        raise EuclidError(cov.get('reason') or f'No Euclid {band} here.', 404)
    d = _pos_dir(ra, dec)
    out = d / f'{band}_{fov}.fits'
    with _lock(str(out)):
        try:
            es._cutout(cov['mosaics'][band], ra, dec, out, radius_arcsec=fov / 2)
        except Exception as e:
            raise EuclidError(f'Euclid cutout failed ({e}).', 502)
    with fits.open(out) as h:
        hdu = next(x for x in h if x.data is not None)
        data = np.asarray(hdu.data, dtype=np.float32)
        try:
            px, py = (float(v) for v in WCS(hdu.header).world_to_pixel_values(ra, dec))
        except Exception:
            px, py = data.shape[1] / 2, data.shape[0] / 2
    fin = data[np.isfinite(data)]
    if fin.size == 0 or fin.min() == fin.max():   # tile lists the band but has no pixels here (e.g. NISP J / Y gaps)
        raise EuclidError(f'No Euclid {band.replace("NIR_", "NISP ")} pixels here.', 404)
    f = int(np.ceil(max(data.shape) / MAX_SIDE))
    if f > 1:   # mean-bin big fields so the browser gets ≤ MAX_SIDE px a side
        hh, ww = data.shape[0] // f * f, data.shape[1] // f * f
        data = np.nanmean(data[:hh, :ww].reshape(hh // f, f, ww // f, f), axis=(1, 3)).astype(np.float32)
        px, py = (px + 0.5) / f - 0.5, (py + 0.5) / f - 0.5
    return np.ascontiguousarray(data, dtype='<f4'), px, py, f


# ---------------------------------------------------------------- other surveys (colour JPEGs)

def survey_jpeg(ra: float, dec: float, fov: int, key: str) -> Path:
    if key not in SURVEYS:
        raise EuclidError('Unknown survey.', 404)
    label = SURVEY_LABELS[key]
    d = _pos_dir(ra, dec)
    if not d.exists():
        _prune()
    out = d / f'S_{key}_{fov}.jpg'
    if SURVEYS[key] is None:
        path = _ps1_jpeg(ra, dec, fov, out)
    else:
        size = min(int(round(fov / 0.1)) + 1, MAX_SIDE)
        path = es.ls_jpeg(ra, dec, SURVEYS[key], out, size=size, pixscale=fov / size)
    if path is None:
        raise EuclidError(f'{label} did not answer.', 502)
    if _blank(path):
        raise EuclidError(f'No {label} data here.', 404)
    return path


def _blank(path: Path) -> bool:
    """True for a flat image (the viewer answers outside a survey's footprint with an all-black JPEG)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return all(hi - lo <= 2 for lo, hi in im.convert('RGB').getextrema())
    except Exception:
        return False


def _ps1_jpeg(ra: float, dec: float, fov: int, out: Path) -> Path | None:
    """Pan-STARRS1 3π stack, i / r / g colour JPEG at the native 0.25″/px (dec > −30°)."""
    import requests
    if out.exists() and out.stat().st_size > 500:
        return out
    if dec < -30.5:
        raise EuclidError('No Pan-STARRS1 data south of −30°.', 404)
    with _lock(str(out)):
        if out.exists() and out.stat().st_size > 500:
            return out
        try:
            r = requests.get(PS1_FILES, params={'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'filters': 'gri'}, timeout=30)
            r.raise_for_status()
            rows = [ln.split() for ln in r.text.strip().splitlines()[1:]]
            files = {row[4]: row[7] for row in rows if len(row) >= 8}
            if not all(b in files for b in 'gri'):
                raise EuclidError('No Pan-STARRS1 data here.', 404)
            r = requests.get(PS1_CUT, params={'red': files['i'], 'green': files['r'], 'blue': files['g'],
                                              'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'size': int(round(fov / 0.25)),
                                              'format': 'jpg'}, timeout=60)
        except requests.RequestException as e:
            logger.warning('[EUCLID] PS1 %.5f %.5f: %s', ra, dec, e)
            return None
        if r.status_code != 200 or not r.headers.get('content-type', '').startswith('image/'):
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        return out


# ---------------------------------------------------------------- any source as one JPEG (for other pages)

def sources() -> list[dict]:
    out = [{'key': k, 'label': lab, 'group': 'Euclid', 'kind': 'fits', 'bands': list(b)}
           for k, (lab, b) in EUCLID_SOURCES.items()]
    return out + [{'key': k, 'label': lab, 'group': 'Other surveys', 'kind': 'jpeg'} for k, lab in SURVEY_LABELS.items()]


def image_jpeg(ra: float, dec: float, fov: int, src: str) -> Path:
    """One JPEG of any source; Euclid bands get the default STF autostretch (linked for NISP colour), north up."""
    if src in SURVEYS:
        return survey_jpeg(ra, dec, fov, src)
    if src not in EUCLID_SOURCES:
        raise EuclidError('Unknown source.', 404)
    import numpy as np
    from PIL import Image
    out = _pos_dir(ra, dec) / f'E_{src}_{fov}.jpg'
    if out.exists() and out.stat().st_size > 500:
        return out
    chans = [pixels(ra, dec, fov, b)[0] for b in EUCLID_SOURCES[src][1]]
    h = min(c.shape[0] for c in chans)
    w = min(c.shape[1] for c in chans)
    rgb = np.stack([es._stretch(c[:h, :w]) for c in chans], axis=-1)
    if rgb.shape[-1] == 1:
        rgb = np.repeat(rgb, 3, axis=-1)
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)[::-1])   # FITS rows run south → north
    with _lock(str(out)):
        img.save(out, quality=92)
    return out
