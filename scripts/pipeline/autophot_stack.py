"""網頁的疊圖：把同一個濾鏡的幾張曝光對齊、合成一張，存成 AutoPhOT 可以直接測光的 FITS。
用 AutoPhOT 自己的 Python 跑（autophot_web_run.py 匯入；要 reproject、astroalign）。

  python autophot_stack.py <spec.json>
spec：{'files': [...], 'out': '...fits', 'align': 'auto'|'wcs'|'stars', 'combine': 'mean'|'median', 'sigma': 3.0,
       'telescope_yml': '.../telescope.yml'}

單位：輸出保持原始 ADU（平均，不是總和），所以：
  EXPTIME = 單張曝光時間（各張的平均），GAIN = N × 單張 gain（N 張平均後的等效增益），
  讀出雜訊 = √N × 單張讀出雜訊（電子數）；這兩個寫在 telescope.yml 指定的 header 鍵（AutoPhOT 從那裡讀）。
  DATE-OBS / MJD-OBS = 第一張開始到最後一張結束的中點；NCOMBINE、LIVETIME（總曝光）、每張的檔名寫進 header。
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning

warnings.simplefilter('ignore', FITSFixedWarning)


def log(msg):
    print(msg, flush=True)


def image_hdu(hdul):
    for h in hdul:
        if h.data is not None and getattr(h.data, 'ndim', 0) == 2:
            return h
    raise ValueError('no 2-D image')


def telescope_keys(yml_path, header):
    """telescope.yml 裡這台望遠鏡+儀器用的 header 鍵：gain、readnoise、exptime、date、mjd。"""
    keys = {'gain': 'GAIN', 'readnoise': 'RDNOISE', 'exptime': 'EXPTIME', 'date': 'DATE-OBS', 'mjd': 'MJD-OBS'}
    try:
        import yaml
        db = yaml.safe_load(Path(yml_path).read_text()) or {}
        inst = (db.get(str(header.get('TELESCOP', '')).strip()) or {}).get('INSTRUME', {}).get(str(header.get('INSTRUME', '')).strip()) or {}
        for k in keys:
            v = inst.get(k)
            if isinstance(v, str) and v and v != 'not_given_by_user':
                keys[k] = v
            elif isinstance(v, (int, float)):
                keys[k] = float(v)                # 直接給數值（例如 readnoise: 5）
    except Exception as e:
        log(f'  (telescope.yml not read: {e})')
    return keys


def has_wcs(h):
    """header 裡有真的天球 WCS（CRVAL、CRPIX 與 CD/CDELT 都在）；沒有時 astropy 會給一個不對應天空的單位 WCS。"""
    if not all(k in h for k in ('CRVAL1', 'CRVAL2', 'CRPIX1', 'CRPIX2')):
        return False
    if not (('CD1_1' in h and 'CD2_2' in h) or ('CDELT1' in h and 'CDELT2' in h)):
        return False
    try:
        return WCS(h).celestial.has_celestial
    except Exception:
        return False


def header_number(h, key):
    if isinstance(key, float):
        return key
    try:
        v = float(h.get(key))
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def obs_window(h, keys, exptime):
    """(開始, 結束) 的 Time：DATE-OBS（或 MJD-OBS）當開始，加曝光時間。"""
    t0 = None
    mjd = header_number(h, keys['mjd']) if keys['mjd'] in h or isinstance(keys['mjd'], float) else None
    if mjd:
        t0 = Time(mjd, format='mjd')
    else:
        for k in (keys['date'], 'DATE-OBS'):
            if isinstance(k, str) and h.get(k):
                try:
                    t0 = Time(str(h[k]).replace(' ', 'T'), format='isot', scale='utc')
                    break
                except ValueError:
                    pass
    if t0 is None:
        return None, None
    return t0, t0 + (exptime or 0) / 86400.0


class StackError(Exception):
    pass


def stack(spec):
    """疊一組影像（spec 見檔頭）；回傳 {'out', 'n', 'rms', 'rms_single', 'align'}。網頁的 runner 直接 import 呼叫。"""
    files = [Path(f) for f in spec['files']]
    if len(files) < 2:
        raise StackError('Need at least two images to stack')
    align, combine, nsig = spec.get('align', 'auto'), spec.get('combine', 'mean'), float(spec.get('sigma', 3.0))
    out = Path(spec['out'])

    log(f'[stack] {len(files)} images → {out.name}  (align: {align}, combine: {combine}, clip: {nsig:g}σ)')
    datas, heads = [], []
    for f in files:
        with fits.open(f) as hdul:
            h = image_hdu(hdul)
            datas.append(np.asarray(h.data, dtype=np.float64))         # BZERO/BSCALE 已經套用
            heads.append(h.header.copy() if h is hdul[0] else fits.Header(list(hdul[0].header.cards) + list(h.header.cards)))
        log(f'  read {f.name}  {datas[-1].shape}  filter={heads[-1].get("FILTER")}')

    no_wcs = [f.name for f, h in zip(files, heads) if not has_wcs(h)]
    if align == 'auto':
        align = 'stars' if no_wcs else 'wcs'
        log(f'  alignment: {align}' + (f' ({len(no_wcs)} image(s) without WCS)' if no_wcs else ' (every image has a WCS)'))
    elif align == 'wcs' and no_wcs:
        raise StackError(f'No WCS in {", ".join(no_wcs)}; use star matching (or automatic) alignment')

    filters = {str(h.get('FILTER', '')) for h in heads}
    if len(filters) > 1:
        raise StackError(f'Images have different filters: {", ".join(sorted(filters))}')
    shapes = {d.shape for d in datas}

    # 參考影像：時間在中間的那張（對齊誤差最平均）
    keys = telescope_keys(spec.get('telescope_yml', ''), heads[0])
    exps = [header_number(h, keys['exptime']) or header_number(h, 'EXPTIME') or 0.0 for h in heads]
    windows = [obs_window(h, keys, e) for h, e in zip(heads, exps)]
    order = sorted(range(len(files)), key=lambda i: windows[i][0].mjd if windows[i][0] is not None else i)
    ref = order[len(order) // 2]
    log(f'  reference frame: {files[ref].name}')
    ref_h, ref_shape = heads[ref], datas[ref].shape

    # 1. 對齊到參考影像的格點
    aligned = []
    for i, (d, h) in enumerate(zip(datas, heads)):
        if i == ref:
            aligned.append(d.copy())
            continue
        if align == 'stars':
            import astroalign as aa
            src = np.nan_to_num(d, nan=float(np.nanmedian(d)))
            tgt = np.nan_to_num(datas[ref], nan=float(np.nanmedian(datas[ref])))
            try:
                tf, (m_src, m_tgt) = aa.find_transform(src, tgt)
                reg, foot = aa.apply_transform(tf, src, tgt, fill_value=np.nan)
            except Exception as e:
                raise StackError(f'Star matching failed for {files[i].name}: {e}' + ('' if no_wcs else '  (try WCS alignment)'))
            reg = reg.astype(np.float64)
            reg[foot] = np.nan
            aligned.append(reg)
            resid = np.hypot(*(tf(m_src) - m_tgt).T)
            log(f'  aligned {files[i].name} by star matching: shift dx={tf.translation[0]:+.2f} dy={tf.translation[1]:+.2f} px, '
                f'rotation {np.degrees(tf.rotation):+.3f}°, scale {tf.scale:.4f}, {len(m_src)} stars, rms {np.sqrt(np.mean(resid ** 2)):.3f} px')
        else:
            from reproject import reproject_interp
            w_in, w_ref = WCS(h).celestial, WCS(ref_h).celestial
            reg, foot = reproject_interp((d, w_in), w_ref, shape_out=ref_shape, order='bilinear')
            reg[foot < 0.999] = np.nan                                 # 邊緣只有部分覆蓋的像素不要
            aligned.append(reg)
            # 位移量（參考影像中心在這張的位置）
            cy, cx = (ref_shape[0] - 1) / 2, (ref_shape[1] - 1) / 2
            sky = w_ref.pixel_to_world(cx, cy)
            px, py = w_in.world_to_pixel(sky)
            log(f'  aligned {files[i].name} by WCS  (shift dx={float(px) - cx:+.2f} dy={float(py) - cy:+.2f} px)')
    if len(shapes) > 1 and align == 'stars':
        log('  note: different image sizes; star matching resampled them onto the reference grid')

    # 2. 背景加法正規化：每張的天空對齊到參考影像（亮度尺度不動，所以單位還是 ADU）
    _, ref_bkg, _ = sigma_clipped_stats(aligned[ref], sigma=3.0, maxiters=5)
    sky_rms = []
    for i, a in enumerate(aligned):
        _, bkg, std = sigma_clipped_stats(a, sigma=3.0, maxiters=5)
        a += ref_bkg - bkg
        sky_rms.append(std)
        log(f'  {files[i].name}: sky {bkg:9.2f} ADU  rms {std:7.2f}  → offset {ref_bkg - bkg:+.2f}')

    # 3. 合併
    cube = np.array(aligned)
    n_cov = np.sum(np.isfinite(cube), axis=0)
    if combine == 'median':
        stack = np.nanmedian(cube, axis=0)
    else:
        # 雜訊模型的 clipping（IRAF / DOLPHOT crreject 的作法）：每個像素的期望雜訊 = 那張的天空 rms 加上星光的 Poisson 雜訊，
        # 偏離中位數超過 nsig 倍就丟掉；只有幾張影像時，不能用這幾個值自己的離散程度估 σ（太不穩，會誤殺正常像素）
        g = header_number(heads[ref], keys['gain']) or 1.0
        rms = np.array(sky_rms)[:, None, None]
        keep = np.isfinite(cube)
        for _ in range(3):
            med = np.nanmedian(np.where(keep, cube, np.nan), axis=0)
            sigma = np.sqrt(rms ** 2 + np.clip(med - ref_bkg, 0, None)[None] / g)
            new_keep = np.isfinite(cube) & (np.abs(cube - med[None]) <= nsig * sigma)
            if np.array_equal(new_keep, keep):
                break
            keep = new_keep
        stack = np.nanmean(np.where(keep, cube, np.nan), axis=0)
        rej = ~keep & np.isfinite(cube)
        log(f'  noise-model clipping ({nsig:g}σ, gain {g:g}) rejected {100 * rej.sum() / max(1, np.isfinite(cube).sum()):.3f} % of pixels (cosmic rays, satellites, hot pixels)')
    stack[n_cov == 0] = np.nan
    n = len(files)
    log(f'  pixels covered by all {n} frames: {100 * np.mean(n_cov == n):.1f} %')

    # 4. header：參考影像的 header（WCS 就是參考影像的格點）+ 疊圖資訊
    hdr = ref_h.copy()
    for k in ('BZERO', 'BSCALE', 'BLANK', 'CHECKSUM', 'DATASUM'):
        hdr.remove(k, ignore_missing=True, remove_all=True)
    gain1 = header_number(ref_h, keys['gain'])
    rn1 = header_number(ref_h, keys['readnoise'])
    gain_key = keys['gain'] if isinstance(keys['gain'], str) else 'GAIN'
    rn_key = keys['readnoise'] if isinstance(keys['readnoise'], str) else 'RDNOISE'
    eff = n if combine == 'mean' else n * 2 / np.pi                    # 中位數的雜訊比平均大 √(π/2)
    if gain1:
        hdr[gain_key] = (round(gain1 * eff, 4), f'effective gain of the {combine} of {n} frames (single {gain1:g})')
    else:
        log(f'  WARNING: no gain in the header ({gain_key}); AutoPhOT will fall back to 1 e-/ADU')
    if rn1:
        hdr[rn_key] = (round(rn1 * np.sqrt(eff), 3), f'effective read noise of the {combine} of {n} frames (single {rn1:g})')
    exp_key = keys['exptime'] if isinstance(keys['exptime'], str) else 'EXPTIME'
    hdr[exp_key] = (round(float(np.mean(exps)), 3), f'mean exposure per frame ({combine} stack, ADU per frame)')
    hdr['NCOMBINE'] = (n, 'number of frames stacked')
    hdr['LIVETIME'] = (round(float(np.sum(exps)), 3), 'total exposure time of the stacked frames [s]')
    starts = [w[0] for w in windows if w[0] is not None]
    ends = [w[1] for w in windows if w[1] is not None]
    if starts:
        t0, t1 = min(starts), max(ends)
        mid = t0 + (t1 - t0) / 2
        date_key = keys['date'] if isinstance(keys['date'], str) else 'DATE-OBS'
        hdr[date_key] = (mid.isot[:23], 'midpoint of first start and last end (stack)')
        if date_key != 'DATE-OBS':
            hdr['DATE-OBS'] = (mid.isot[:23], 'midpoint of first start and last end (stack)')
        mjd_key = keys['mjd'] if isinstance(keys['mjd'], str) else 'MJD-OBS'
        hdr[mjd_key] = (round(mid.mjd, 6), 'midpoint of first start and last end (stack)')
        hdr['MJD-BEG'] = (round(t0.mjd, 6), 'start of the first stacked frame')
        hdr['MJD-END'] = (round(t1.mjd, 6), 'end of the last stacked frame')
        log(f'  time: {t0.isot[:19]} → {t1.isot[:19]}  mid {mid.isot[:19]}  (MJD {mid.mjd:.5f})')
    sats = [header_number(h, 'SATURATE') for h in heads]
    sat = min([s for s in sats if s] or [65535.0])
    hdr['SATURATE'] = (round(sat * 0.95, 1), 'conservative: 95 % of the single-frame limit')
    hdr['STACKREF'] = (files[ref].name, 'reference frame (WCS and pixel grid)')
    hdr['STACKALN'] = (align, 'alignment: wcs (reproject) or stars (astroalign)')
    hdr['STACKCMB'] = (f'{combine}' + (f' {nsig:g}sigma' if combine == 'mean' else ''), 'combine method')
    for i, f in enumerate(files):
        hdr[f'IMCMB{i + 1:03d}'] = (f.name[:68], 'stacked frame')
    hdr.add_history(f'Stacked by the AutoPhOT web page: {n} frames, align={align}, combine={combine}')

    out.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(stack.astype(np.float32), header=hdr).writeto(out, overwrite=True)
    finite = stack[np.isfinite(stack)]
    _, bkg, std = sigma_clipped_stats(finite, sigma=3.0, maxiters=5)
    single = [sigma_clipped_stats(a, sigma=3.0, maxiters=5)[2] for a in aligned]
    log(f'  stack sky {bkg:.2f} ADU, rms {std:.2f} ADU  (single frames {np.median(single):.2f}; improvement ×{np.median(single) / std:.2f}, √N = {np.sqrt(n):.2f})')
    log(f'[stack] wrote {out}')
    return {'out': str(out), 'n': n, 'rms': float(std), 'rms_single': float(np.median(single)), 'align': align}


def main():
    try:
        r = stack(json.loads(Path(sys.argv[1]).read_text()))
    except StackError as e:
        sys.exit(str(e))
    print(json.dumps(r), flush=True)


if __name__ == '__main__':
    main()
