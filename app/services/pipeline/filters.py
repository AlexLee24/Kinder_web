"""Which standard filter a FITS was taken in, from its header (ported from work-web's scripts/autophot_templates.py).

Used to sort uploaded templates into AutoPhOT's templates/<filter>_template/ without the user
naming the filter, and to show which filters of a workspace have a template. Only astropy and
yaml; AutoPhOT itself is never imported here.

Order of the checks: telescope.yml for this telescope + instrument → telescope.yml for any
instrument → AutoPhOT's own name rules (check.py _resolve_standard_band: gp, g.00000, g782,
V_HIGH …) → the file name (g_template.fits, template_r.fits).
"""
import re
from pathlib import Path

BANDS = set('ugrizyUBVRIJHK')          # AutoPhOT's standard filters (case matters: r = SDSS, R = Johnson-Cousins)
META_KEYS = {'name', 'airmass', 'date', 'exptime', 'filter_key_0', 'filter_key_1', 'gain', 'mjd', 'pixel_scale',
             'readnoise', 'saturate', 'rdnoise', 'location'}
FILTER_KEYS = ('FILTER', 'FILTER1', 'FILTNAME', 'FILTER2', 'BAND', 'PASSBAND')
TEMPLATE_DIR_RE = re.compile(r'([A-Za-z])p?_template')


def norm(token):
    return str(token).strip().replace(' ', '').replace('-', '_').lower()


def heuristic_band(token):
    """AutoPhOT's rules for a raw filter name → standard filter, or None."""
    t = norm(token)
    if not t:
        return None
    if t in {'gp', 'rp', 'ip', 'zp', 'up'}:
        return t[0]
    if '_' in t:
        first = t.split('_')[0]
        if first in {'u', 'g', 'r', 'i', 'z', 'y'}:
            return first
        if len(first) == 2 and first[1] == 'p' and first[0] in 'ugrizy':
            return first[0]
    if len(t) >= 2 and t[0] in 'ugrizy' and any(ch.isdigit() for ch in t[1:]):
        return t[0]
    m = re.match(r'^([a-zA-Z]+)', str(token).strip().replace(' ', '').replace('-', '_'))
    if m and m.group(1) in BANDS:                           # exact case (UBVRI ≠ ugriz)
        return m.group(1)
    return None


_db_cache = {}


def telescope_db(yml_path):
    """telescope.yml → ({(telescope, instrument): {raw: band}}, {raw: band} over all, {(telescope, instrument): [filter keys]})."""
    p = Path(yml_path)
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return {}, {}, {}
    if key in _db_cache:
        return _db_cache[key]
    per, glob, keys = {}, {}, {}
    try:
        import yaml
        db = yaml.safe_load(p.read_text()) or {}
    except Exception:
        db = {}
    for tel, tv in (db.items() if isinstance(db, dict) else []):
        if not isinstance(tv, dict):
            continue
        for ins, iv in (tv.get('INSTRUME') or {}).items():
            if not isinstance(iv, dict):
                continue
            m = {k: v for k, v in iv.items() if isinstance(k, str) and isinstance(v, str)
                 and v in BANDS and k.lower() not in META_KEYS}
            tk = (str(tel).strip(), str(ins).strip())
            per[tk] = m
            keys[tk] = [v for k, v in iv.items() if k in ('filter_key_0', 'filter_key_1') and isinstance(v, str)]
            for k, v in m.items():
                glob.setdefault(k, v)
    _db_cache.clear()
    _db_cache[key] = (per, glob, keys)
    return per, glob, keys


def band_of(header, db, name=''):
    """(standard filter | None, how it was decided, raw filter value) for a header (dict or astropy Header)."""
    per, glob, keys = db
    telescope = str(header.get('TELESCOP', '') or '').strip()
    instrument = str(header.get('INSTRUME', '') or '').strip()
    tkey = (telescope, instrument)
    raw = ''
    for k in list(keys.get(tkey, [])) + list(FILTER_KEYS):
        v = str(header.get(k, '') or '').strip()
        if v:
            raw = v
            break
    if raw:
        for table, how in ((per.get(tkey, {}), 'telescope.yml'), (glob, 'telescope.yml (another instrument)')):
            for k, v in table.items():
                if k == raw or norm(k) == norm(raw):
                    return v, how, raw
        b = heuristic_band(raw)
        if b:
            return b, 'filter name', raw
    m = re.search(r'(?:^|[_\-. ])([ugrizy])(?:p)?(?=[_\-. ]|$)', stem(name)) if name else None
    if m:
        return m.group(1), 'file name', raw
    return None, '', raw


_meta_cache = {}


def telescope_meta(yml_path):
    """telescope.yml → {(telescope, instrument): {'exptime': header key, 'date': header key}} (keys the yml names)."""
    p = Path(yml_path)
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return {}
    if key in _meta_cache:
        return _meta_cache[key]
    out = {}
    try:
        import yaml
        db = yaml.safe_load(p.read_text()) or {}
    except Exception:
        db = {}
    for tel, tv in (db.items() if isinstance(db, dict) else []):
        if not isinstance(tv, dict):
            continue
        for ins, iv in (tv.get('INSTRUME') or {}).items():
            if isinstance(iv, dict):
                out[(str(tel).strip(), str(ins).strip())] = {
                    k: v for k, v in ((k, iv.get(k)) for k in ('exptime', 'date'))
                    if isinstance(v, str) and v != 'not_given_by_user'}
    _meta_cache.clear()
    _meta_cache[key] = out
    return out


def short_filter(raw):
    """The filter as people say it: rp_Astrodon_2019 → rp, 'g DECam SDSS c0001 …' → g; a long odd name stays whole."""
    first = re.split(r'[_\s]', str(raw).strip(), maxsplit=1)[0]
    return first if 0 < len(first) <= 3 else str(raw).strip()


def _exptime(header, meta):
    for k in [meta.get('exptime'), 'EXPTIME', 'EXPOSURE']:
        v = header.get(k) if k else None
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def header_info(header, db, meta, name=''):
    """What one frame is, from its header and telescope.yml:
    {'band', 'how', 'raw', 'telescope', 'instrument', 'filter', 'exptime', 'date', 'tag'}; tag reads like 'LOT rp 300s'."""
    band, how, raw = band_of(header, db, name)
    telescope = str(header.get('TELESCOP', '') or '').strip()
    instrument = str(header.get('INSTRUME', '') or '').strip()
    m = meta.get((telescope, instrument), {})
    exp = _exptime(header, m)
    date = str(header.get(m.get('date') or 'DATE-OBS', '') or header.get('DATE-OBS', '') or '').strip()
    filt = short_filter(raw) if raw else (band or '')
    parts = [telescope or instrument, filt, f'{exp:g}s' if exp else '']
    return {'band': band or '', 'how': how, 'raw': raw, 'telescope': telescope, 'instrument': instrument,
            'filter': filt, 'exptime': exp, 'date': date, 'tag': ' '.join(p for p in parts if p)}


def band_of_folder(rel):
    """A path inside templates/ that already names its filter (g_template/x.fits) → that filter."""
    for part in Path(rel).parts[:-1]:
        m = TEMPLATE_DIR_RE.fullmatch(part)
        if m and m.group(1) in BANDS:
            return m.group(1)
    return None


def stem(name):
    """Name without any FITS extension: x.fits.fz → x."""
    n = Path(str(name)).name
    while re.search(r'\.(fits|fit|fts|fz|gz)$', n, flags=re.I):
        n = re.sub(r'\.(fits|fit|fts|fz|gz)$', '', n, flags=re.I)
    return n


def image_header(path):
    """Header of the first 2-D image in a FITS (primary cards merged in for an extension)."""
    from astropy.io import fits
    with fits.open(path) as hdul:
        for x in hdul:
            if x.data is not None and getattr(x.data, 'ndim', 0) == 2:
                return fits.Header(list(hdul[0].header.cards) + list(x.header.cards)) if x is not hdul[0] else x.header
    raise ValueError('no 2-D image')


def write_plain_fits(src, dest):
    """AutoPhOT reads templates only as *.fits: copy one, or unpack .fz / .gz into a plain FITS."""
    import shutil
    if str(src).lower().endswith(('.fits', '.fit', '.fts')):
        shutil.copy2(src, dest)
        return
    from astropy.io import fits
    with fits.open(src) as hdul:
        for x in hdul:
            if x.data is not None and getattr(x.data, 'ndim', 0) == 2:
                header = image_header(src)
                fits.PrimaryHDU(x.data, header=header).writeto(dest, overwrite=True)
                return
    raise ValueError('no 2-D image')
