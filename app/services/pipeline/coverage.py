"""Which calibration catalogs and template surveys cover a position, for the Pipeline form.

    check(ra, dec)  {'ra', 'dec', 'catalogs': {name: item}, 'templates': {name: item}, 'time'}
                    item = {'ok': True | False | None, 'note': str}   (None = could not tell: service down)

All-sky catalogs (gaia, 2mass, apass, tic, refcat) and Pan-STARRS (Dec > -30) are answered from their footprints.
SDSS, SkyMapper and the Legacy Survey (DR10, DR11) are asked live, in parallel, each with a short timeout:
SDSS SkyServer for photometric objects within 2', the SkyMapper cone search, and a 16-pixel Legacy viewer cutout
(an uncovered position returns an error or an all-zero cutout). Results are cached per position for a week.
"""
import io
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor

from . import autophot as ap

logger = logging.getLogger(__name__)

CACHE_DAYS = 7
TIMEOUT = 20
UA = 'Kinder-pipeline-coverage/1.0'
CACHE_FILE = '.coverage_cache.json'


def _get(url, params=None, timeout=TIMEOUT):
    """(status, body); requests (certifi) rather than urllib, whose CA store rejects SkyServer's chain on macOS."""
    import requests
    r = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=timeout)
    return r.status_code, r.content


def _sdss(ra, dec):
    q = f'select count(*) as n from dbo.fGetNearbyObjEq({ra:.6f},{dec:.6f},2)'
    status, body = _get('https://skyserver.sdss.org/dr18/SkyServerWS/SearchTools/SqlSearch', {'cmd': q, 'format': 'json'})
    if status != 200:
        raise RuntimeError(f'SkyServer HTTP {status}')
    n = int(json.loads(body)[0]['Rows'][0]['n'])
    return n > 0, f'{n} SDSS objects within 2′' if n else 'outside the SDSS imaging footprint'


def _skymapper(ra, dec):
    status, body = _get('https://skymapper.anu.edu.au/sm-cone/public/query',
                        {'RA': f'{ra:.6f}', 'DEC': f'{dec:.6f}', 'SR': 0.05, 'RESPONSEFORMAT': 'CSV', 'VERB': 1})
    if status != 200 or body.lstrip().startswith(b'<'):
        raise RuntimeError(f'SkyMapper HTTP {status}')
    rows = [l for l in body.decode(errors='replace').splitlines()[1:] if l.strip()]
    return bool(rows), f'{len(rows)} SkyMapper sources within 3′' if rows else 'outside SkyMapper DR4'


def _legacy(ra, dec, layer):
    import numpy as np
    from astropy.io import fits
    status, body = _get('https://www.legacysurvey.org/viewer/fits-cutout',
                        {'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'layer': layer, 'pixscale': 0.262, 'bands': 'r',
                         'size': 16})
    if status in (404, 500):                             # the viewer answers 500 outside the footprint
        return False, f'outside {layer.upper()}'
    if status != 200:
        raise RuntimeError(f'Legacy viewer HTTP {status}')
    if not body.startswith(b'SIMPLE'):
        return None, 'unexpected answer from the Legacy Survey viewer'
    data = fits.getdata(io.BytesIO(body))
    ok = bool(np.any(np.isfinite(data) & (data != 0)))
    return ok, f'{layer.upper()} r-band imaging here' if ok else f'no {layer.upper()} r-band imaging here'


def _datalab_up():
    try:
        status, _ = _get('https://datalab.noirlab.edu/tap/availability', timeout=10)
        return status == 200
    except Exception:
        return False


def _run(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        logger.info('coverage %s: %s', getattr(fn, '__name__', fn), e)
        return None, 'could not ask the service just now'


def _live(ra, dec):
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {'sdss': pool.submit(_run, _sdss, ra, dec), 'skymapper': pool.submit(_run, _skymapper, ra, dec),
                'dr10': pool.submit(_run, _legacy, ra, dec, 'ls-dr10'),
                'dr11': pool.submit(_run, _legacy, ra, dec, 'ls-dr11'),
                'datalab': pool.submit(_datalab_up)}
        return {k: f.result() for k, f in futs.items()}


def _item(ok, note):
    return {'ok': ok, 'note': note}


def _build(ra, dec, live):
    ps1 = dec > -30
    sdss, sm, dr10, dr11 = live['sdss'], live['skymapper'], live['dr10'], live['dr11']
    legacy_note = dr10[1]
    if dr10[0] and not live['datalab']:
        legacy_note += ' · Data Lab is down: AutoPhOT reads the Tractor brick files instead (slower the first time)'
    catalogs = {
        'sdss': _item(*sdss),
        'pan_starrs': _item(ps1, 'Dec > −30°' if ps1 else 'Pan-STARRS stops at Dec −30°'),
        'gaia': _item(True, 'all-sky'),
        'apass': _item(True, 'all-sky, bright stars only (about 10–17 mag)'),
        '2mass': _item(True, 'all-sky, near-infrared JHK'),
        'legacy': _item(dr10[0], legacy_note),
        'skymapper': _item(*sm),
        'refcat': _item(True, 'all-sky (ATLAS-RefCat2)'),
        'tic': _item(True, 'all-sky (TESS Input Catalog)'),
        'auto': _item(True, 'AutoPhOT picks per filter'),
    }
    templates = {
        'panstarrs': _item(ps1, catalogs['pan_starrs']['note']),
        'legacy_dr11': _item(*dr11),
        'legacy': _item(*dr10),
        'sdss': _item(*sdss),
    }
    return {'ra': ra, 'dec': dec, 'catalogs': catalogs, 'templates': templates, 'time': time.time()}


def _key(ra, dec):
    return f'{ra:.4f},{dec:.4f}'


def check(ra, dec, refresh=False):
    ra, dec = float(ra) % 360.0, float(dec)
    if not -90 <= dec <= 90 or math.isnan(ra):
        raise ap.PipelineError('Dec must be between −90 and 90.')
    try:
        path = ap.runs_root() / CACHE_FILE
    except ap.PipelineError:
        path = None
    cache = ap._read_json(path) if path else {}
    hit = cache.get(_key(ra, dec))
    if hit and not refresh and time.time() - hit.get('time', 0) < CACHE_DAYS * 86400:
        return hit
    res = _build(ra, dec, _live(ra, dec))
    unsure = any(v['ok'] is None for part in ('catalogs', 'templates') for v in res[part].values())
    if path and not unsure:                              # never keep an answer from a service that was down
        cache = {k: v for k, v in cache.items() if time.time() - v.get('time', 0) < CACHE_DAYS * 86400}
        cache[_key(ra, dec)] = res
        try:
            ap._write_json(path, dict(list(cache.items())[-2000:]))
        except OSError:
            pass
    return res


def parse(ra, dec):
    """RA / Dec as typed in the form (degrees or sexagesimal) → floats."""
    try:
        return float(ra), float(dec)
    except (TypeError, ValueError):
        from astropy import units as u
        from astropy.coordinates import SkyCoord
        try:
            c = SkyCoord(str(ra), str(dec), unit=(u.hourangle, u.deg))
        except Exception:
            raise ap.PipelineError('Could not read RA / Dec.')
        return c.ra.deg, c.dec.deg
