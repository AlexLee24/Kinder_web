"""DESI coadded spectra by TARGETID (Tools › Spectrum, /spectrum).

Where a spectrum lives: DESI groups coadds by HEALPix (nside 64, nested) per survey/program,
    {base}/{release path}/healpix/{survey}/{program}/{hpx // 100}/{hpx}/coadd-{survey}-{program}-{hpx}.fits
Where a TARGETID was observed: NOIRLab Astro Data Lab's desi_dr1.zpix / desi_edr.zpix (every coadd,
with redshift), then Kinder's cat.desi (DR1 zcat_primary + EDR-only targets); with neither, the pixel
comes from a given RA / Dec and the usual survey/program pairs are tried in turn.

A coadd file is 100-200 MB, so it is never downloaded: astropy reads it through HTTP Range
requests (1 MB blocks) — the HDU headers, the FIBERMAP TARGETID column and one row of each arm's
FLUX / IVAR / MASK, about 3 s. Z / ZWARN / SPECTYPE of that coadd come from Data Lab, else from the
redrock file of the same pixel.
Results are cached as gzip JSON under DATA_DIR/desi_spectra.
"""
import csv
import gzip
import io
import json
import logging
import threading
import time

import healpy as hp
import numpy as np
import requests
from astropy.io import fits

from app.paths import DATA_DIR

logger = logging.getLogger(__name__)

BASE_URL = 'https://data.desi.lbl.gov/public'
DATALAB_URL = 'https://datalab.noirlab.edu/query/query'
DATALAB_TOKEN = 'anonymous.0.0.anon_access'   # Data Lab's public anonymous token
RELEASE_PATHS = {'dr1': 'dr1/spectro/redux/iron', 'edr': 'edr/spectro/redux/fuji'}
RELEASE_LABELS = {'dr1': 'DR1 (iron)', 'edr': 'EDR (fuji)'}
NSIDE = 64
ARMS = ('b', 'r', 'z')

# survey/program pairs tried when cat.desi does not say, most common first
_TRY_PAIRS = {
    'dr1': [('main', 'dark'), ('main', 'bright'), ('main', 'backup'), ('sv3', 'dark'), ('sv3', 'bright'),
            ('sv1', 'dark'), ('sv1', 'bright'), ('sv1', 'other'), ('special', 'dark'), ('special', 'bright'),
            ('sv2', 'dark'), ('sv2', 'bright'), ('sv3', 'backup'), ('sv1', 'backup'), ('cmx', 'other'),
            ('special', 'backup'), ('special', 'other')],
    'edr': [('sv3', 'dark'), ('sv3', 'bright'), ('sv1', 'dark'), ('sv1', 'bright'), ('sv1', 'other'),
            ('sv2', 'dark'), ('sv2', 'bright'), ('sv3', 'backup'), ('sv1', 'backup'), ('cmx', 'other'),
            ('special', 'dark'), ('special', 'bright')],
}

CACHE_DIR = DATA_DIR / 'desi_spectra'
_CACHE_VERSION = 2
_TIMEOUT = 60
_FETCHES = threading.BoundedSemaphore(3)   # concurrent DESI downloads per process


class SpectrumError(Exception):
    """A message the page can show as is; ``status`` is the HTTP status for the API."""

    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


# ── where ────────────────────────────────────────────────────────────────────

def coadd_url(release: str, survey: str, program: str, hpx: int, kind: str = 'coadd') -> str:
    return (f'{BASE_URL}/{RELEASE_PATHS[release]}/healpix/{survey}/{program}/{hpx // 100}/{hpx}/'
            f'{kind}-{survey}-{program}-{hpx}.fits')


def healpix_of(ra: float, dec: float) -> int:
    return int(hp.ang2pix(NSIDE, float(ra), float(dec), nest=True, lonlat=True))


def lookup_target(targetid: int) -> dict | None:
    """cat.desi row of a TARGETID (None when absent or the DB is unreachable)."""
    try:
        from app.db import get_db_connection
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT targetid, survey, program, desi_healpix64, data_release, z, zerr, zwarn,
                       spectype, subtype, deltachi2, ra, dec, mag_g, mag_r, mag_z, morphtype
                  FROM cat.desi WHERE targetid = %s
            """, (int(targetid),))
            r = cur.fetchone()
    except Exception as e:   # the page still works from RA / Dec
        logger.warning('[SPECTRUM] cat.desi lookup failed for %s: %s', targetid, e)
        return None
    if not r:
        return None
    keys = ('targetid', 'survey', 'program', 'healpix', 'release', 'z', 'zerr', 'zwarn', 'spectype',
            'subtype', 'deltachi2', 'ra', 'dec', 'mag_g', 'mag_r', 'mag_z', 'morphtype')
    return dict(zip(keys, r))


# ── HTTP Range file for astropy ──────────────────────────────────────────────

class _RangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file, fetched in cached 1 MB blocks."""
    BLOCK = 1 << 20

    def __init__(self, url: str, session: requests.Session, size: int):
        super().__init__()
        self.url, self.session, self.size = url, session, size
        self.pos, self.blocks, self.requests = 0, {}, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = 0 if whence == io.SEEK_SET else self.pos if whence == io.SEEK_CUR else self.size
        self.pos = max(0, base + offset)
        return self.pos

    def _block(self, b: int) -> bytes:
        data = self.blocks.get(b)
        if data is None:
            lo = b * self.BLOCK
            hi = min(lo + self.BLOCK, self.size) - 1
            r = self.session.get(self.url, headers={'Range': f'bytes={lo}-{hi}'}, timeout=_TIMEOUT)
            r.raise_for_status()
            if r.status_code != 206 and lo > 0:
                raise SpectrumError('The DESI server ignored a byte-range request.', 502)
            data = r.content[:hi - lo + 1] if r.status_code == 206 else r.content[lo:hi + 1]
            self.blocks[b] = data
            self.requests += 1
        return data

    def readinto(self, buf):
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        out = bytearray()
        while len(out) < n:
            b, off = divmod(self.pos + len(out), self.BLOCK)
            chunk = self._block(b)[off:off + n - len(out)]
            if not chunk:
                break
            out += chunk
        buf[:len(out)] = out
        self.pos += len(out)
        return len(out)


def _open_remote(url: str, session: requests.Session):
    """(fits.HDUList, _RangeFile) or None when the file does not exist."""
    r = session.head(url, timeout=_TIMEOUT, allow_redirects=True)
    if r.status_code == 404:
        return None
    if r.status_code >= 500:
        raise SpectrumError(f'The DESI data server answered HTTP {r.status_code}; try again later.', 502)
    r.raise_for_status()
    size = int(r.headers.get('content-length') or 0)
    if not size:
        raise SpectrumError('The DESI data server did not report the file size.', 502)
    raw = _RangeFile(url, session, size)
    return fits.open(io.BufferedReader(raw, 1 << 16), lazy_load_hdus=True, memmap=False), raw


# ── read ─────────────────────────────────────────────────────────────────────

def _num(v, nd=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return round(f, nd) if nd is not None else f


def _clean_str(v) -> str:
    if isinstance(v, bytes):
        v = v.decode('ascii', 'ignore')
    return str(v or '').strip()


def _read_coadd(hdul, row: int) -> dict:
    arms = {}
    for arm in ARMS:
        a = arm.upper()
        wave = np.asarray(hdul[f'{a}_WAVELENGTH'].data, dtype=float)
        flux = np.asarray(hdul[f'{a}_FLUX'].section[row], dtype=float)
        ivar = np.asarray(hdul[f'{a}_IVAR'].section[row], dtype=float)
        try:
            mask = np.asarray(hdul[f'{a}_MASK'].section[row])
            ivar = np.where(mask != 0, 0.0, ivar)
        except KeyError:
            pass
        bad = ~np.isfinite(flux) | ~np.isfinite(ivar)
        flux = np.where(bad, 0.0, flux)
        ivar = np.where(bad, 0.0, ivar)
        arms[arm] = {
            'wave': np.round(wave, 2).tolist(),
            'flux': [float(f'{x:.4g}') for x in flux],
            'ivar': [float(f'{x:.4g}') for x in ivar],
        }
    return arms


def _fibermap_info(fm, row: int) -> dict:
    names = fm.columns.names
    def col(name):
        return fm[name][row] if name in names else None
    return {
        'target_ra': _num(col('TARGET_RA'), 6),
        'target_dec': _num(col('TARGET_DEC'), 6),
        'coadd_numexp': int(col('COADD_NUMEXP')) if col('COADD_NUMEXP') is not None else None,
        'coadd_exptime': _num(col('COADD_EXPTIME'), 1),
        'objtype': _clean_str(col('OBJTYPE')),
    }


def _read_redrock(release, survey, program, hpx, targetid, session) -> dict:
    """Z / ZWARN / SPECTYPE of this very coadd from its redrock file ({} when unavailable)."""
    try:
        opened = _open_remote(coadd_url(release, survey, program, hpx, 'redrock'), session)
        if not opened:
            return {}
        hdul, _raw = opened
        with hdul:
            t = hdul['REDSHIFTS'].data
            idx = np.nonzero(np.asarray(t['TARGETID']) == targetid)[0]
            if not len(idx):
                return {}
            i = int(idx[0])
            return {
                'z': _num(t['Z'][i]), 'zerr': _num(t['ZERR'][i]), 'zwarn': int(t['ZWARN'][i]),
                'spectype': _clean_str(t['SPECTYPE'][i]), 'subtype': _clean_str(t['SUBTYPE'][i]),
                'deltachi2': _num(t['DELTACHI2'][i], 2),
            }
    except SpectrumError:
        raise
    except Exception as e:
        logger.info('[SPECTRUM] redrock read failed %s %s/%s/%s: %s', targetid, survey, program, hpx, e)
        return {}


def _try(release, survey, program, hpx, targetid, session):
    """The spectrum dict when this coadd holds the TARGETID, else None."""
    url = coadd_url(release, survey, program, hpx)
    opened = _open_remote(url, session)
    if not opened:
        return None
    hdul, raw = opened
    with hdul:
        fm = hdul['FIBERMAP'].data
        idx = np.nonzero(np.asarray(fm['TARGETID']) == targetid)[0]
        if not len(idx):
            return None
        row = int(idx[0])
        arms = _read_coadd(hdul, row)
        info = _fibermap_info(fm, row)
    logger.info('[SPECTRUM] %s from %s (row %d, %d range requests)', targetid, url, row, raw.requests)
    return {'release': release, 'survey': survey, 'program': program, 'healpix': hpx,
            'url': url, 'arms': arms, 'fibermap': info}


# ── cache ────────────────────────────────────────────────────────────────────

def _cache_path(targetid, release, survey, program):
    return CACHE_DIR / f'{targetid}_{release}_{survey}_{program}.json.gz'


def _cache_load(targetid, release=None, survey=None, program=None):
    if not CACHE_DIR.is_dir():
        return None
    pattern = f'{targetid}_{release or "*"}_{survey or "*"}_{program or "*"}.json.gz'
    for p in sorted(CACHE_DIR.glob(pattern)):
        try:
            with gzip.open(p, 'rt') as f:
                data = json.load(f)
            if data.get('cache_version') == _CACHE_VERSION:
                return data
        except Exception:
            continue
    return None


def _cache_save(data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path(data['targetid'], data['release'], data['survey'], data['program'])
        tmp = p.with_suffix('.tmp')
        with gzip.open(tmp, 'wt') as f:
            json.dump(data, f, separators=(',', ':'))
        tmp.replace(p)
    except OSError as e:
        logger.warning('[SPECTRUM] cache write failed: %s', e)


# ── Data Lab: every DESI spectrum of a TARGETID ─────────────────────────────

def lookup_datalab(targetid: int, session: requests.Session) -> list[dict]:
    """All DR1 / EDR coadds of a TARGETID from NOIRLab Astro Data Lab (desi_dr1.zpix, desi_edr.zpix),
    the ZCAT_PRIMARY one first. [] when Data Lab is unreachable or knows nothing."""
    rows = []
    for rel, table in (('dr1', 'desi_dr1.zpix'), ('edr', 'desi_edr.zpix')):
        sql = (f'SELECT survey, program, healpix, z, zerr, zwarn, spectype, subtype, deltachi2, '
               f'mean_fiber_ra, mean_fiber_dec, zcat_primary FROM {table} WHERE targetid = {int(targetid)}')
        try:
            r = session.get(DATALAB_URL, params={'sql': sql, 'ofmt': 'csv', 'async': 'false'},
                            headers={'X-DL-AuthToken': DATALAB_TOKEN}, timeout=20)
        except requests.RequestException as e:
            logger.info('[SPECTRUM] Data Lab unreachable for %s: %s', targetid, e)
            return rows
        if not r.ok or r.text.startswith('Error'):
            logger.info('[SPECTRUM] Data Lab %s: HTTP %s %s', table, r.status_code, r.text[:200])
            continue
        for d in csv.DictReader(io.StringIO(r.text)):
            try:
                rows.append({
                    'release': rel, 'survey': d['survey'].strip().lower(), 'program': d['program'].strip().lower(),
                    'healpix': int(d['healpix']), 'z': _num(d['z']), 'zerr': _num(d['zerr']),
                    'zwarn': int(float(d['zwarn'])) if d.get('zwarn') not in (None, '') else None,
                    'spectype': _clean_str(d['spectype']), 'subtype': _clean_str(d['subtype']),
                    'deltachi2': _num(d['deltachi2'], 2),
                    'ra': _num(d['mean_fiber_ra'], 6), 'dec': _num(d['mean_fiber_dec'], 6),
                    'primary': str(d.get('zcat_primary', '')).strip().lower() in ('t', 'true', '1'),
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: (x['release'] != 'dr1', not x['primary']))
    return rows


def _plan(cat, dl, release, survey, program, ra, dec):
    """Ordered (release, survey, program, healpix) coadds to open."""
    cands = []

    def add(rel, sv, pg, hpx):
        if rel in RELEASE_PATHS and sv and pg and hpx is not None:
            t = (rel, str(sv).lower(), str(pg).lower(), int(hpx))
            if t not in cands:
                cands.append(t)

    for r in dl:
        add(r['release'], r['survey'], r['program'], r['healpix'])
    if cat:
        add(cat.get('release') or 'dr1', cat.get('survey'), cat.get('program'), cat.get('healpix'))
    pos_ra = ra if ra is not None else (cat or {}).get('ra')
    pos_dec = dec if dec is not None else (cat or {}).get('dec')
    pix = healpix_of(pos_ra, pos_dec) if pos_ra is not None and pos_dec is not None else None
    if pix is None and cat and cat.get('healpix') is not None:
        pix = int(cat['healpix'])
    if not cands and pix is not None:      # nothing says where: try the usual survey/program pairs
        for rel in RELEASE_PATHS:
            for sv, pg in _TRY_PAIRS[rel]:
                add(rel, sv, pg, pix)
    if survey and program and pix is not None:
        for rel in ([release] if release else list(RELEASE_PATHS)):
            add(rel, survey, program, pix)
    return [c for c in cands if (not release or c[0] == release) and (not survey or c[1] == survey)
            and (not program or c[2] == program)]


# ── public ───────────────────────────────────────────────────────────────────

def get_spectrum(targetid: int, release: str | None = None, survey: str | None = None,
                 program: str | None = None, ra: float | None = None, dec: float | None = None,
                 refresh: bool = False) -> dict:
    """The coadded DESI spectrum of a TARGETID (see module docstring). Raises SpectrumError."""
    targetid = int(targetid)
    if targetid <= 0:
        raise SpectrumError('TARGETID must be a positive integer.', 400)
    release = (release or '').lower() or None
    if release and release not in RELEASE_PATHS:
        raise SpectrumError(f'Unknown release "{release}" (dr1 or edr).', 400)
    survey = (survey or '').lower() or None
    program = (program or '').lower() or None

    if not refresh:
        hit = _cache_load(targetid, release, survey, program)
        if hit:
            hit['cached'] = True
            return hit

    t0 = time.time()
    cat = lookup_target(targetid)
    if not _FETCHES.acquire(timeout=90):
        raise SpectrumError('Kinder is busy downloading other spectra; try again in a minute.', 503)
    try:
        with requests.Session() as session:
            session.headers['User-Agent'] = 'Kinder-Spectrum/1.0'
            dl = lookup_datalab(targetid, session)
            attempts = _plan(cat, dl, release, survey, program, ra, dec)
            if not attempts:
                if dl:
                    have = ', '.join(f"{r['release']}:{r['survey']}/{r['program']}" for r in dl)
                    raise SpectrumError(f'TARGETID {targetid} has no coadd matching that release / survey / '
                                        f'program; DESI has {have}.', 404)
                raise SpectrumError(f'TARGETID {targetid} is neither in Kinder\'s DESI catalogue nor found '
                                    'through Astro Data Lab (DR1 / EDR). Give its RA / Dec to search its HEALPix pixel.', 404)
            found = None
            for rel, sv, pg, hpx in attempts:
                try:
                    found = _try(rel, sv, pg, hpx, targetid, session)
                except requests.RequestException as e:
                    raise SpectrumError(f'Could not reach the DESI data server ({e.__class__.__name__}).', 502)
                if found:
                    break
            if not found:
                tried = ', '.join(f'{r}:{s}/{p}/{h}' for r, s, p, h in attempts[:8])
                raise SpectrumError(f'No DESI coadd holds TARGETID {targetid} (tried {tried}'
                                    f'{" …" if len(attempts) > 8 else ""}).', 404)
            key = (found['release'], found['survey'], found['program'])
            zrow = next((r for r in dl if (r['release'], r['survey'], r['program']) == key), None)
            rr = ({k: zrow[k] for k in ('z', 'zerr', 'zwarn', 'spectype', 'subtype', 'deltachi2')} if zrow
                  else _read_redrock(*key, found['healpix'], targetid, session))
    finally:
        _FETCHES.release()

    # redshift: the fit of this very coadd (Data Lab / redrock file); cat.desi's primary spectrum otherwise
    same_as_cat = bool(cat) and (cat.get('survey'), cat.get('program')) == (found['survey'], found['program'])
    src = rr or ({k: cat.get(k) for k in ('z', 'zerr', 'zwarn', 'spectype', 'subtype', 'deltachi2')} if cat else {})
    fm = found['fibermap']
    pos_ra = ra if ra is not None else (cat or {}).get('ra')
    pos_dec = dec if dec is not None else (cat or {}).get('dec')
    data = {
        'cache_version': _CACHE_VERSION,
        'targetid': str(targetid),   # > 2**53: a JS number would round it
        'release': found['release'],
        'release_label': RELEASE_LABELS[found['release']],
        'survey': found['survey'],
        'program': found['program'],
        'healpix': found['healpix'],
        'coadd_url': found['url'],
        'ra': _num(fm.get('target_ra') if fm.get('target_ra') is not None else pos_ra, 6),
        'dec': _num(fm.get('target_dec') if fm.get('target_dec') is not None else pos_dec, 6),
        'z': _num(src.get('z')),
        'zerr': _num(src.get('zerr')),
        'zwarn': int(src['zwarn']) if src.get('zwarn') is not None else None,
        'spectype': _clean_str(src.get('spectype')),
        'subtype': _clean_str(src.get('subtype')),
        'deltachi2': _num(src.get('deltachi2'), 2),
        'z_source': 'redrock' if rr else ('cat.desi' if cat else ''),
        'primary': bool(zrow['primary']) if zrow else same_as_cat,
        'in_catalogue': bool(cat),
        'alternatives': [{k: r[k] for k in ('release', 'survey', 'program', 'z', 'spectype', 'zwarn', 'primary')}
                         for r in dl],
        'mag': {b: _num((cat or {}).get(f'mag_{b}'), 2) for b in 'grz'},
        'morphtype': _clean_str((cat or {}).get('morphtype')),
        'coadd_numexp': fm.get('coadd_numexp'),
        'coadd_exptime': fm.get('coadd_exptime'),
        'arms': found['arms'],
        'fetched_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'fetch_seconds': round(time.time() - t0, 1),
    }
    _cache_save(data)
    data['cached'] = False
    return data
