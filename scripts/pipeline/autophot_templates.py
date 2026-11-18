"""每個波段挑最好的模板（ts_download = 'auto'），給 autophot_web_run.py 用。

AutoPhOT 一次只能從一個巡天下載模板，而且只看下載成不成功，不看模板在目標周圍蓋到多少：
  - Pan-STARRS 是從單一 skycell 切的，目標靠近 skycell 邊緣時只剩幾角分有資料（AT2026afqt 2026-11-16：10′ 只剩 5.2′），
    裁小以後星太少，對齊（z）和 SFFT kernel（r，flux scale 差 39%）都失敗，只好退回不減；
  - Pan-STARRS 沒有 u，SDSS 只蓋北天和赤道帶，Legacy Survey 沒有 u，AutoPhOT 自己的 Legacy 下載只有 gri。
所以這裡把 AutoPhOT 的 download_panstarrs_template 換成 pick()：每個波段依序試 SURVEYS 裡的巡天，量目標周圍真正
有資料的方框邊長，夠大（≥ GOOD_FRACTION × 要的大小）就用，都不夠就用最大的。u 波段南天用 SkyMapper（幾張曝光疊起來）。

選好的模板寫成 <band>_template/<巡天>_<band>_band_template.fits，旁邊的 kinder_template.json 記下巡天、大小和方框；
同樣的設定下次直接沿用（AutoPhOT 處理過的衍生檔也留著），設定變了就整個資料夾清掉重下載（AutoPhOT 會優先用
*.fits.original，不清乾淨會用到舊模板）。

另外兩件跟模板／u 校正有關、在跑 AutoPhOT 之前要做的事：
  ensure_telescope_bands  wdir/telescope.yml 裡 LEGACY / SDSS / SkyMapper 缺的波段對照補上（LEGACY 沒有 z、SDSS 只有 r），
                          不然 AutoPhOT 會停下來問，自動跑時只能接受預設答案；
  purge_stale_gaia        Gaia XP 合成測光失敗時（2026-11-18 Gaia archive 回 HTTP 500）AutoPhOT 退回只有 G/BP/RP 的星表，
                          還把它存成快取，之後每次都讀這份沒有 u 的快取，u 永遠校正不了：沒有 SdssStd_mag_u 的快取刪掉重查。
"""
import json
import shutil
import tempfile
from pathlib import Path

SURVEYS = {
    'u': ('sdss', 'skymapper'),
    'g': ('panstarrs', 'legacy', 'sdss', 'skymapper'),
    'r': ('panstarrs', 'legacy', 'sdss', 'skymapper'),
    'i': ('panstarrs', 'legacy', 'sdss', 'skymapper'),
    'z': ('panstarrs', 'legacy', 'sdss', 'skymapper'),
}
OTHER_BANDS = ('panstarrs',)            # y, w …
GOOD_FRACTION = 0.8                     # 目標周圍有資料的方框 ≥ 要的大小 × 0.8 就算夠
MIN_FORCE_SIDE = 3.0                    # 指定的巡天（force）至少要有這麼大（arcmin）才用
MARKER = 'kinder_template.json'
LEGACY_LAYERS = ('ls-dr10', 'ls-dr11')
LEGACY_PIXSCALE = 0.262
LEGACY_MAX_PIX = 3000                   # viewer 的 fits-cutout 上限
SKYMAPPER_SIAP = 'https://api.skymapper.nci.org.au/public/siap/dr4/query'
SKYMAPPER_MAX_IMAGES = 8
TIMEOUT = 120
UA = 'Kinder-pipeline-templates/1.0'
LABELS = {'panstarrs': 'Pan-STARRS', 'legacy': 'Legacy Survey', 'sdss': 'SDSS', 'skymapper': 'SkyMapper'}


def log(msg):
    print(f'[web] {msg}', flush=True)


def _get(url, params=None, timeout=TIMEOUT):
    import requests
    r = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=timeout)
    r.raise_for_status()
    return r


# ── how much of a template has data around the target ─────────────────────────

def usable_side(path, ra, dec):
    """模板在目標周圍真正有資料的方框邊長（arcmin）：目標到資料最近一邊的距離 × 2；目標不在資料裡是 0。"""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    from astropy.wcs.utils import proj_plane_pixel_scales
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if h.data is not None and getattr(h.data, 'ndim', 0) == 2)
        data = np.asarray(hdu.data, dtype=float)
        wcs = WCS(hdu.header).celestial
    x, y = (float(v) for v in wcs.all_world2pix(ra, dec, 0))
    ok = np.isfinite(data) & (data != 0)
    rows, cols = np.flatnonzero(ok.mean(axis=1) > 0.5), np.flatnonzero(ok.mean(axis=0) > 0.5)
    if not len(rows) or not len(cols):
        return 0.0
    half = min(x - cols[0], cols[-1] - x, y - rows[0], rows[-1] - y)
    scale = float(np.mean(proj_plane_pixel_scales(wcs))) * 3600
    return max(0.0, float(2 * half * scale / 60))


# ── downloaders: each writes one 2-D FITS into `dest` and returns its path, or None ────────────────

def fetch_panstarrs(ra, dec, size, dest, band, autophot_fn=None):
    if band not in 'grizy':
        return None
    if dec < -30.5:
        return None
    if autophot_fn is None:
        from templates import download_panstarrs_template as autophot_fn
    p = autophot_fn(ra=ra, dec=dec, size=size, template_folder=str(dest), band=band)
    return Path(p) if p else None


def fetch_legacy(ra, dec, size, dest, band):
    """Legacy Survey DR10（不行再 DR11）viewer 的單波段 fits-cutout；AutoPhOT 自己的只有 gri。"""
    import io

    import numpy as np
    from astropy.io import fits
    if band not in 'griz':
        return None
    npix = min(LEGACY_MAX_PIX, int(round(size * 60 / LEGACY_PIXSCALE)))
    for layer in LEGACY_LAYERS:
        try:
            r = _get('https://www.legacysurvey.org/viewer/fits-cutout',
                     {'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'layer': layer, 'pixscale': LEGACY_PIXSCALE,
                      'bands': band, 'size': npix})
            with fits.open(io.BytesIO(r.content)) as hdul:
                hdu = next(h for h in hdul if h.data is not None)
                data = np.asarray(hdu.data, dtype='float32')
                head = hdu.header.copy()
        except Exception as e:
            log(f'template {band}: Legacy {layer} cutout failed ({e})')
            continue
        if data.ndim == 3:
            data = data[0]
        if not np.isfinite(data).any() or not np.any(data[np.isfinite(data)] != 0):
            continue                                   # 沒蓋到：全是 0
        for k in ('NAXIS3', 'CTYPE3', 'CRPIX3', 'CRVAL3', 'CDELT3', 'CUNIT3', 'BANDS', 'BAND0', 'BAND1', 'BAND2'):
            head.remove(k, ignore_missing=True)
        head['NAXIS'] = 2
        head.update({'TELESCOP': 'LEGACY', 'INSTRUME': 'SURVEY', 'FILTER': band, 'LSLAYER': layer})
        out = Path(dest) / f'legacy_{band}_band_template.fits'
        fits.PrimaryHDU(data, head).writeto(out, overwrite=True)
        return out
    return None


def sdss_covers(ra, dec):
    import json as _json
    r = _get('https://skyserver.sdss.org/dr18/SkyServerWS/SearchTools/SqlSearch',
             {'cmd': f'select count(*) as n from dbo.fGetNearbyObjEq({ra:.6f},{dec:.6f},2)', 'format': 'json'}, timeout=30)
    return int(_json.loads(r.content)[0]['Rows'][0]['n']) > 0


def fetch_sdss(ra, dec, size, dest, band, autophot_fn=None):
    if band not in 'ugriz':
        return None
    try:
        if not sdss_covers(ra, dec):
            return None
    except Exception as e:
        log(f'template {band}: SDSS footprint check failed ({e})')
        return None
    if autophot_fn is None:
        from templates import download_sdss_template as autophot_fn
    p = autophot_fn(ra=ra, dec=dec, size=size, template_folder=str(dest), f=band)
    return Path(p) if p else None


def skymapper_images(ra, dec, band, size):
    """SkyMapper DR4 蓋住目標的曝光（不必蓋滿整個方框，疊起來會補齊）：長的（main survey 100 s）在前。"""
    import csv
    import io
    r = _get(SKYMAPPER_SIAP, {'POS': f'{ra:.6f},{dec:.6f}', 'SIZE': f'{size / 60:.4f}', 'BAND': band,
                              'FORMAT': 'image/fits', 'INTERSECT': 'CENTER', 'RESPONSEFORMAT': 'CSV'})
    rows = [x for x in csv.DictReader(io.StringIO(r.text)) if x.get('get_image')]
    rows.sort(key=lambda x: (-float(x.get('exptime') or 0), x.get('mjd_obs') or ''))
    return rows


SKYMAPPER_SCALE = 0.497                 # arcsec/px of SkyMapper's images


def target_grid(ra, dec, size, scale):
    """A north-up TAN grid of size arcmin, scale arcsec/px, centred on the target."""
    from astropy.wcs import WCS
    n = int(round(size * 60 / scale))
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.cdelt = [n / 2 + 0.5, n / 2 + 0.5], [-scale / 3600, scale / 3600]
    w.wcs.crval, w.wcs.ctype = [ra, dec], ['RA---TAN', 'DEC--TAN']
    w.pixel_shape = (n, n)
    return w


def fetch_skymapper(ra, dec, size, dest, band, max_images=SKYMAPPER_MAX_IMAGES):
    """SkyMapper DR4 的切圖（南天，有 u）：最多 max_images 張曝光重投影到以目標為中心的格點，依各自的 ZPAPPROX 換成同一個
    零點，再以曝光時間加權平均（天光雜訊為主時權重 ∝ 曝光時間）。單張 100 s 的 u 只到 ~19 等，疊起來深一些。"""
    import io

    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    if band not in 'uvgriz' or dec > 16:
        return None
    try:
        rows = skymapper_images(ra, dec, band, size)[:max_images]
    except Exception as e:
        log(f'template {band}: SkyMapper query failed ({e})')
        return None
    deg = f'{size / 60:.4f}'
    frames = []
    for x in rows:
        url = x['get_image'].split('&size=')[0] + f'&size={deg},{deg}'
        try:
            with fits.open(io.BytesIO(_get(url).content)) as hdul:
                frames.append((np.asarray(hdul[0].data, dtype='float64'), hdul[0].header.copy(),
                               float(x.get('exptime') or hdul[0].header.get('EXPTIME') or 1)))
        except Exception as e:
            log(f'template {band}: SkyMapper image {x.get("image_name") or ""} failed ({e})')
    if not frames:
        return None
    ref_data, ref_head, ref_t = frames[0]
    zp_ref = ref_head.get('ZPAPPROX')
    planes, weights = [ref_data], [ref_t]
    try:
        from reproject import reproject_interp
    except ImportError:
        reproject_interp = None
        log(f'template {band}: reproject not installed; using one SkyMapper exposure')
    if reproject_interp is not None:
        # 每張切圖只有那張 CCD 上的部分：目標靠 CCD 邊時第一張可能只有 1′（AT 2026ajby u 2026-11-17）。
        # 全部投影到以目標為中心、size 見方的格點，各張互補成整個方框。
        ref_head = ref_head.copy()
        out_wcs = target_grid(ra, dec, size, SKYMAPPER_SCALE)
        n = out_wcs.pixel_shape[0]
        for k in [k for k in list(ref_head) if k[:2] in ('CD', 'PC', 'PV') or k[:4] in ('CRPI', 'CRVA', 'CDEL', 'CTYP',
                                                                                       'CUNI', 'NAXI', 'A_', 'B_', 'AP_', 'BP_')]:
            del ref_head[k]
        ref_head.update(out_wcs.to_header())
        planes, weights = [], []
        for data, head, t in frames:
            arr, _ = reproject_interp((data, WCS(head)), out_wcs, shape_out=(n, n))
            zp = head.get('ZPAPPROX')
            planes.append(arr * (10 ** (0.4 * (zp_ref - zp)) if zp and zp_ref else 1.0))
            weights.append(t)
    cube = np.stack(planes)
    w = np.asarray(weights)[:, None, None] * np.isfinite(cube)
    with np.errstate(invalid='ignore', divide='ignore'):
        data = np.nansum(np.nan_to_num(cube) * w, axis=0) / w.sum(axis=0)
    data[w.sum(axis=0) == 0] = np.nan
    total = float(sum(weights))
    head = ref_head
    head['NCOMBINE'] = (len(planes), 'SkyMapper exposures combined (Kinder)')
    head['LIVETIME'] = (total, 'total exposure of the combined SkyMapper frames [s]')
    head['GAIN'] = (float(head.get('GAIN') or 1) * total / ref_t, 'effective gain of the weighted mean')
    head['FILTER'] = band
    out = Path(dest) / f'skymapper_{band}_band_template.fits'
    fits.PrimaryHDU(data.astype('float32'), head).writeto(out, overwrite=True)
    log(f'template {band}: SkyMapper {len(planes)} exposure(s), {total:g} s in all')
    return out


FETCH = {'panstarrs': fetch_panstarrs, 'legacy': fetch_legacy, 'sdss': fetch_sdss, 'skymapper': fetch_skymapper}


# ── the picker that replaces AutoPhOT's download_panstarrs_template ───────────

def _folder(template_folder, band):
    return Path(template_folder) / f'{band}_template'


def _marker(folder):
    try:
        return json.loads((folder / MARKER).read_text())
    except (OSError, ValueError):
        return None


def pick(ra, dec, size, template_folder, band, fetch=None, autophot_fns=None, force=None):
    """每個波段依 SURVEYS 的順序下載，第一個在目標周圍有 ≥ GOOD_FRACTION × size 資料的就用，都不夠就用最大的。
    force（巡天名）：先試它，有 ≥ MIN_FORCE_SIDE 就用（自動測光拿另一個巡天再做一次，比較哪個減得好）。
    回傳 <band>_template/<巡天>_<band>_band_template.fits，或 None（沒有任何巡天有這個波段）。"""
    fetch = fetch or FETCH
    autophot_fns = autophot_fns or {}
    band = str(band).strip()
    size = float(size)
    folder = _folder(template_folder, band)
    mk = _marker(folder)
    if mk and mk.get('size') == size and mk.get('force') == force and (folder / mk.get('file', '')).is_file():
        log(f'template {band}: {LABELS.get(mk["survey"], mk["survey"])} as before ({mk["side"]:.1f}′ around the target)')
        return str(folder / mk['file'])

    order = tuple(SURVEYS.get(band.lower(), OTHER_BANDS))
    if force in FETCH:
        order = (force,) + tuple(x for x in order if x != force)
    best = None                                       # (side, survey, path, tmpdir)
    tmps = []
    try:
        for survey in order:
            tmp = Path(tempfile.mkdtemp(prefix=f'kinder-tpl-{band}-'))
            tmps.append(tmp)
            fn = fetch[survey]
            kwargs = {'autophot_fn': autophot_fns[survey]} if survey in autophot_fns else {}
            try:
                path = fn(ra, dec, size, tmp, band, **kwargs)
            except Exception as e:
                log(f'template {band}: {LABELS.get(survey, survey)} failed ({e})')
                path = None
            if not path or not Path(path).is_file():
                continue
            try:
                side = usable_side(path, ra, dec)
            except Exception as e:
                log(f'template {band}: could not measure the {LABELS.get(survey, survey)} cutout ({e})')
                continue
            log(f'template {band}: {LABELS.get(survey, survey)} has {side:.1f}′ of data around the target')
            if best is None or side > best[0]:
                best = (side, survey, Path(path))
            if side >= GOOD_FRACTION * size or (survey == force and side >= MIN_FORCE_SIDE):
                best = (side, survey, Path(path))
                break
        if best is None:
            log(f'template {band}: no survey has this band here; measured without template subtraction')
            return None
        side, survey, path = best
        if side < GOOD_FRACTION * size and not (survey == force and side >= MIN_FORCE_SIDE):
            log(f'template {band}: none reaches {GOOD_FRACTION * size:.1f}′; using {LABELS.get(survey, survey)} ({side:.1f}′)')
        for old in (folder, Path(template_folder) / f'{band}p_template'):   # 換巡天：舊模板和 AutoPhOT 的衍生檔都清掉
            if old.is_dir():
                shutil.rmtree(old)
        folder.mkdir(parents=True, exist_ok=True)
        name = f'{survey}_{band}_band_template.fits'
        shutil.copyfile(path, folder / name)
        (folder / MARKER).write_text(json.dumps({'survey': survey, 'size': size, 'side': round(side, 2), 'file': name,
                                                 'force': force, 'tried': list(order[:order.index(survey) + 1])}))
        log(f'template {band}: using {LABELS.get(survey, survey)}')
        return str(folder / name)
    finally:
        for t in tmps:
            shutil.rmtree(t, ignore_errors=True)


def install(templates_module, force=None):
    """AutoPhOT 的下載迴圈（download_templates: panstarrs）每個波段呼叫 download_panstarrs_template：換成 pick()。
    force：{波段: 巡天}，那些波段先試指定的巡天。"""
    originals = {'panstarrs': templates_module.download_panstarrs_template,
                 'sdss': templates_module.download_sdss_template}
    force = dict(force or {})

    def download(ra, dec, size, template_folder, band='r'):
        return pick(ra, dec, size, template_folder, band, autophot_fns=originals, force=force.get(str(band).strip()))

    templates_module.download_panstarrs_template = download
    return download


# ── telescope.yml and the Gaia catalogue cache ────────────────────────────────

TEMPLATE_TELESCOPES = {
    'LEGACY': ('SURVEY', {'Name': 'LEGACY+SURVEY', 'airmass': 'not_given_by_user', 'date': 'not_given_by_user',
                          'exptime': 'not_given_by_user', 'filter_key_0': 'FILTER', 'gain': 'not_given_by_user',
                          'mjd': 'not_given_by_user', 'pixel_scale': 0.262, 'readnoise': 'not_given_by_user',
                          'saturate': 'not_given_by_user'}, 'griz'),
    'SDSS': ('Imaging', {'Name': 'SDSS+Imaging', 'airmass': 'not_given_by_user', 'date': 'DATE-OBS', 'exptime': 'EXPTIME',
                         'filter_key_0': 'FILTER', 'gain': 'GAIN', 'mjd': 'MJD-OBS', 'pixel_scale': 0.396,
                         'readnoise': 'not_given_by_user', 'saturate': 'not_given_by_user'}, 'ugriz'),
    'SkyMapper': ('SG_32_Det', {'Name': 'SkyMapper+SG_32_Det', 'airmass': 'AIRMASS', 'date': 'DATE-OBS',
                                'exptime': 'EXPTIME', 'filter_key_0': 'FILTER', 'gain': 'GAIN', 'mjd': 'MJD-OBS',
                                'pixel_scale': 0.5, 'readnoise': 5, 'saturate': 'SATURATE'}, 'uvgriz'),
}
LOCATION = {'alt': None, 'lat': None, 'lon': None, 'name': None}


def ensure_telescope_bands(yml_path):
    """telescope.yml 裡模板巡天的條目：沒有就加，缺的波段對照補上。改了回傳 True。"""
    import yaml
    p = Path(yml_path)
    if not p.parent.is_dir():
        return False
    doc = (yaml.safe_load(p.read_text()) if p.is_file() else None) or {}
    changed = False
    for tel, (inst, entry, bands) in TEMPLATE_TELESCOPES.items():
        t = doc.setdefault(tel, {})
        insts = t.setdefault('INSTRUME', {})
        e = insts.get(inst)
        if not isinstance(e, dict):
            insts[inst] = e = dict(entry)
            changed = True
        for b in bands:
            if b not in e:
                e[b] = b
                changed = True
        if 'location' not in t:
            t['location'] = dict(LOCATION)
            changed = True
    if changed:
        p.write_text(yaml.safe_dump(doc, default_flow_style=False, sort_keys=True))
    return changed


def purge_stale_gaia(wdir, column='SdssStd_mag_u'):
    """AutoPhOT 存下來、卻沒有 Gaia XP 合成測光（column）的 Gaia 星表快取：刪掉，下次重查。回傳刪掉的檔名。"""
    root = Path(wdir) / 'catalog_queries' / 'gaia'
    gone = []
    if not root.is_dir():
        return gone
    for f in root.rglob('*.csv'):
        try:
            with open(f, encoding='utf-8', errors='replace') as fh:
                head = fh.readline()
        except OSError:
            continue
        if column not in head.split(','):
            try:
                f.unlink()
                gone.append(f.name)
            except OSError:
                pass
    if gone:
        log(f'Gaia catalogue cache without XP synthetic photometry removed ({len(gone)}): queried again')
    return gone
