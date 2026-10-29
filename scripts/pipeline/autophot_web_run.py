"""Kinder Pipeline 的 AutoPhOT 執行檔：用 AutoPhOT 自己的 Python 跑（app/services/pipeline/autophot.py 呼叫），
AutoPhOT 的資料夾由環境變數 AUTOPHOT_DIR 給（沒給就用工作目錄），工作目錄是工作區。不要用 Kinder 的 .venv。

  python autophot_web_run.py <工作區資料夾>
工作區的 target.json 是網頁存的設定；跑完把輸出位置寫進 result.json，結束碼寫進 exit.json
（網頁有好幾個 gunicorn worker，靠這個檔案知道這次是成功還是失敗）。
AutoPhOT 碰到不認得的望遠鏡、濾鏡會用 input() 問，網頁把回答從 stdin（工作區裡的 FIFO）送進來。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

# AutoPhOT 下載的巡天模板（app/services/pipeline/autophot.py DOWNLOADED_TEMPLATE_RE 同一個樣式）
DOWNLOADED_TEMPLATE = re.compile(r'^(panstarrs|sdss|legacy|2MASS)_[A-Za-z0-9]+_band_template.*\.fits(\.unused)?$')


def deep_merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def parse_coord(ra, dec):
    """度數或六十進位（12:34:56.7 / 12h34m56.7s）→ 度數；沒填 → (None, None)。"""
    ra, dec = str(ra or '').strip(), str(dec or '').strip()
    if not ra and not dec:
        return None, None
    try:
        return float(ra), float(dec)
    except ValueError:
        from astropy import units as u
        from astropy.coordinates import SkyCoord
        c = SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
        # 一定要是 Python float：numpy 數值會被 AutoPhOT 存進 input.yaml 變成 !!python/object 標記，它自己的 safe_load 讀不回來
        return float(c.ra.deg), float(c.dec.deg)


FITS_EXT = ('.fits', '.fit', '.fts', '.fits.fz', '.fits.gz')


def make_stacks(cfg_in, tdir):
    """疊圖打勾時，執行前先疊：同一濾鏡、同一晚（UT 往前推 12 小時的日期）、至少兩張的組各疊成 stack_<濾鏡>_<日期>.fits。
    組成、設定、檔案修改時間都沒變的組直接沿用上次的疊圖；組不存在了的疊圖移到 .removed/stacks/。回傳新的 stacks 記錄。"""
    import shutil
    from astropy.io import fits
    from astropy.time import Time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from autophot_stack import StackError, stack

    top = cfg_in['fits_dir']
    old = cfg_in.get('stacks') or {}
    opts = {'align': cfg_in.get('stack_align') or 'auto', 'combine': cfg_in.get('stack_combine') or 'mean',
            'sigma': float(cfg_in.get('stack_sigma') or 3.0)}
    groups = {}
    for root_dir, dirs, names in os.walk(top):
        rel_root = os.path.relpath(root_dir, top)
        if rel_root != '.' and (cfg_in.get('top_only', True) or rel_root.split(os.sep)[0] == 'templates'):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != 'templates' and not d.startswith('.')]
        for n in sorted(names):
            rel = os.path.normpath(os.path.join(rel_root, n))
            if not n.lower().endswith(FITS_EXT) or rel in old:
                continue
            try:
                h = fits.getheader(os.path.join(top, rel))
            except Exception:
                continue
            if h.get('STACKREF'):                       # 別的方式留下的疊圖，不要再疊
                continue
            filt = str(h.get('FILTER') or h.get('FILTER1') or '').strip()
            try:
                night = (Time(str(h.get('DATE-OBS', '')).replace(' ', 'T'), format='isot') - 0.5).isot[:10]
            except ValueError:
                night = str(h.get('DATE-OBS', ''))[:10] or 'unknown'
            groups.setdefault((filt, night), []).append(rel)

    new = {}
    for (filt, night), members in sorted(groups.items()):
        if len(members) < 2:
            print(f'[web] stacking: {filt} {night} has a single frame; measured as it is', flush=True)
            continue
        safe = ''.join(c for c in filt if c.isalnum())[:16] or 'filter'
        name = f'stack_{safe}_{night.replace("-", "")}.fits'
        mtime = max(os.path.getmtime(os.path.join(top, m)) for m in members)
        prev = old.get(name) or {}
        if (os.path.isfile(os.path.join(top, name)) and sorted(prev.get('members', [])) == sorted(members)
                and all(prev.get(k) == v for k, v in opts.items()) and prev.get('mtime') == mtime):
            print(f'[web] stacking: {name} is up to date ({len(members)} frames)', flush=True)
            new[name] = prev
            continue
        print(f'[web] stacking {filt} {night}: {len(members)} frames → {name}', flush=True)
        try:
            r = stack({'files': [os.path.join(top, m) for m in members], 'out': os.path.join(top, name),
                       'telescope_yml': os.path.join(cfg_in['wdir'], 'telescope.yml'), **opts})
        except StackError as e:
            sys.exit(f'Stacking {filt} {night} failed: {e}')
        new[name] = {'members': members, **opts, 'mtime': mtime, 'time': time.time(), 'filter': filt, 'night': night,
                     'align_used': r['align'], 'rms': r['rms'], 'rms_single': r['rms_single']}
    for name in set(old) - set(new):                    # 組沒了（影像被移除）：舊疊圖移走
        p = os.path.join(top, name)
        if os.path.isfile(p):
            dest = os.path.join(tdir, '.removed', 'stacks', time.strftime('%Y%m%d-%H%M%S_') + name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(p, dest)
        print(f'[web] stacking: {name} no longer has a group; moved to .removed/stacks/', flush=True)
    # 記回 target.json（只動 stacks，其他設定保持網頁存的）
    cfg_now = json.loads(open(os.path.join(tdir, 'target.json')).read())
    cfg_now['stacks'] = new
    with open(os.path.join(tdir, 'target.json'), 'w') as f:
        f.write(json.dumps(cfg_now, ensure_ascii=False, indent=1))
    return new


def has_wcs(path):
    """影像 header 有沒有能用的天球 WCS（CTYPE + CRVAL）。"""
    import warnings

    from astropy.io import fits
    from astropy.wcs import WCS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            w = WCS(fits.getheader(path)).celestial
        return bool(w.has_celestial) and w.wcs.ctype[0] != ''
    except Exception:
        return False


def science_frames(cfg_in):
    """這次要量的影像（最上層的 FITS，疊圖除外；templates/ 和其他子資料夾不算）。"""
    top = cfg_in['fits_dir']
    stacks = set(cfg_in.get('stacks') or {})
    out = []
    for root_dir, dirs, names in os.walk(top):
        rel_root = os.path.relpath(root_dir, top)
        if rel_root != '.' and (cfg_in.get('top_only', True) or rel_root.split(os.sep)[0] == 'templates'):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != 'templates' and not d.startswith('.') and not d.endswith('_REDUCED')]
        for n in sorted(names):
            rel = os.path.normpath(os.path.join(rel_root, n))
            if n.lower().endswith(('.fits', '.fit', '.fts')) and rel not in stacks:
                out.append(os.path.join(top, rel))
    return out


def our_astrometry(paths, tdir, what='frame'):
    """用我們的 astrometry（astrometry_solve.py，跟 Reduction 同一套 solve-field 做法）解 paths，WCS 寫回影像本身。
    做過的影像 header 有 KWASTROM（solved / failed），已經是 Astrometry.net 解過的（例如 Reduction、伺服器上校正好的）
    也跳過，所以每張只會做一次。

    回傳我們沒解出來的影像：解失敗的（KWASTROM = failed）、或伺服器上沒有 solve-field 而沒解的。"""
    from concurrent.futures import ThreadPoolExecutor

    from astropy.io import fits
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import astrometry_solve as asv

    todo, done = [], []
    for path in paths:
        try:
            h = fits.getheader(path)
        except Exception:
            continue
        if h.get(asv.MARK) or any('Astrometry.net' in str(c[1]) for c in h.cards if c[0] in ('HISTORY', 'COMMENT')):
            done.append(path)
        else:
            todo.append(path)
    solver = asv.find_solve_field() if todo else None
    if todo and not solver:
        print(f'[web] astrometry: solve-field not found on this server; {len(todo)} {what}(s) not solved', flush=True)
    elif not todo:
        print(f'[web] astrometry: every {what} already has its WCS', flush=True)
    else:
        print(f'[web] astrometry: solving {len(todo)} {what}(s) with solve-field', flush=True)
        work = os.path.join(tdir, '.astrometry')
        os.makedirs(work, exist_ok=True)

        def one(path):
            rec = asv.solve(path, path, solver, log=lambda t: print(f'[web] astrometry: {t}', flush=True), workdir=work)
            if rec['status'] != 'solved':
                try:
                    with fits.open(path, mode='update') as hdul:
                        hdul[0].header[asv.MARK] = ('failed', f"Kinder solve-field: {rec.get('reason', '')}"[:68])
                except Exception:
                    pass
            return rec['status'] == 'solved'

        with ThreadPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2) // 2))) as ex:
            ok = sum(ex.map(one, todo))
        print(f'[web] astrometry: {ok} of {len(todo)} {what}(s) solved', flush=True)
        done += todo
    unsolved = [p for p in todo if p not in done]                      # 沒有 solve-field
    for p in done:
        try:
            if fits.getheader(p).get(asv.MARK) == 'failed':
                unsolved.append(p)
        except Exception:
            unsolved.append(p)
    return unsolved


def template_box(files, ra, dec):
    """模板在目標周圍真正有資料的方框邊長（arcmin），所有模板取最小；量不到回 None。

    Pan-STARRS 的模板是從單一 skycell 切出來的：目標靠近 skycell 邊緣時，超出的部分是空白，
    AutoPhOT 會把空白邊裁掉，結果模板只蓋到科學影像的一小塊（例如 6′×5′ 對 13′×13′），
    低於 AutoPhOT 要求的 25% 覆蓋率，所有對齊方法都被拒絕、整張不做 TS。"""
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    from astropy.wcs.utils import proj_plane_pixel_scales
    sides = []
    for f in files:
        try:
            with fits.open(f) as hdul:
                hdu = next(h for h in hdul if h.data is not None and getattr(h.data, 'ndim', 0) == 2)
                data = np.asarray(hdu.data, dtype=float)
                wcs = WCS(hdu.header).celestial
            x, y = (float(v) for v in wcs.all_world2pix(ra, dec, 0))
            ok = np.isfinite(data) & (data != 0)          # 空白的地方是 NaN 或 0
            rows, cols = np.flatnonzero(ok.mean(axis=1) > 0.5), np.flatnonzero(ok.mean(axis=0) > 0.5)
            if not len(rows) or not len(cols):
                continue
            half = min(x - cols[0], cols[-1] - x, y - rows[0], rows[-1] - y)   # 目標到最近一邊（像素）
            scale = float(np.mean(proj_plane_pixel_scales(wcs))) * 3600          # arcsec/px
            side = max(0.0, float(2 * half * scale / 60))     # plain float: numpy scalars break AutoPhOT's input.yaml
            print(f'[web] template {os.path.basename(f)}: {side:.1f}′ of data around the target', flush=True)
            sides.append(side)
        except Exception as e:                            # 量不到就不裁，照 AutoPhOT 原本的做法
            print(f'[web] could not measure template {os.path.basename(f)}: {e}', flush=True)
    return min(sides) if sides else None


def plain_yaml_numbers(yaml):
    """讓 yaml.dump 把 numpy 的數字和陣列寫成一般的數字和清單。

    AutoPhOT 把整份設定寫進 images_REDUCED/input.yaml，每張影像的子程序再用 yaml.safe_load 讀回來；
    設定裡只要有一個 numpy 數字（例如 numpy.float64），就會寫成 !!python/object/apply 標籤，
    safe_load 讀不回來，整次執行每張影像都失敗。這裡在寫的那一端統一轉掉，不管值是哪裡來的。"""
    import numpy as np
    for dumper in (yaml.Dumper, yaml.SafeDumper):
        yaml.add_multi_representer(np.generic, lambda d, v: d.represent_data(v.item()), Dumper=dumper)
        yaml.add_representer(np.ndarray, lambda d, v: d.represent_data(v.tolist()), Dumper=dumper)


def main():
    tdir = Path(sys.argv[1]).resolve()
    ap_dir = os.environ.get('AUTOPHOT_DIR') or os.getcwd()     # AutoPhOT 的模組（autophot、prepare、lightcurve）在這裡
    if ap_dir not in sys.path:
        sys.path.insert(1, ap_dir)
    cfg_in = json.loads((tdir / 'target.json').read_text())

    from autophot import AutomatedPhotometry
    import yaml
    plain_yaml_numbers(yaml)

    config = AutomatedPhotometry.load()
    config['fits_dir'] = cfg_in['fits_dir']
    config['wdir'] = cfg_in['wdir']
    ra, dec = parse_coord(cfg_in.get('ra'), cfg_in.get('dec'))
    if ra is not None:
        # 給了座標就不能再給真實名稱（AutoPhOT 會當成設定衝突），名稱只留在網頁顯示；網頁一定會給座標
        config['target_name'], config['target_ra'], config['target_dec'] = 'Transient', ra, dec
    else:
        config['target_name'] = cfg_in.get('target') or cfg_in['name']
    config['nCPU'] = int(cfg_in.get('ncpu') or 1)
    config['catalog']['use_catalog'] = cfg_in.get('catalog') or 'sdss'     # AutoPhOT 沒有預設星表，null 會直接報錯；網頁預設 SDSS
    if config['catalog']['use_catalog'] == 'pan_starrs':
        config['catalog']['use_catalog'] = 'panstarrs'    # catalog.yml 的鍵是 panstarrs（查詢時 AutoPhOT 自己再轉成 pan_starrs）
    ts = config['template_subtraction']
    ts['do_subtraction'] = bool(cfg_in.get('subtraction'))
    if cfg_in.get('sub_method'):
        ts['method'] = cfg_in['sub_method']
    if ts['do_subtraction']:                         # 網頁 TS 區的設定
        ts['download_templates'] = cfg_in.get('ts_download') or False
        ts['templates_size'] = float(cfg_in.get('ts_size') or 10)
        ts['alignment_method'] = cfg_in.get('ts_align') or 'spalipy'
        ts['forceconv'] = cfg_in.get('ts_forceconv') or 'REF'
    for key, value in (cfg_in.get('overrides') or {}).items():          # 網頁「全部設定」改過的值：'photometry.detection_limit' → 5.0
        *path, last = key.split('.')
        d = config
        for k in path:
            d = d.setdefault(k, {})
        d[last] = value
        print(f'[web] {key} = {value!r}', flush=True)
    extra = yaml.safe_load(cfg_in.get('extra_yaml') or '') or {}
    if not isinstance(extra, dict):
        sys.exit('Extra settings must be YAML key: value pairs')
    deep_merge(config, extra)

    # 要量哪些影像：AutoPhOT 用 os.walk 掃整個 fits_dir，這裡把 Prepare.clean() 的清單過濾
    #   不掃子資料夾 → 只留最上層；疊圖打勾 → 只量疊好的圖（stack_with_singles 時單張也量）；沒勾 → 疊好的圖不量
    # （模板由 find_templates 另外找，不受影響）
    use_stack, with_singles = bool(cfg_in.get('stack')), bool(cfg_in.get('stack_with_singles'))
    # WCS：每張影像（和下面的模板）先用我們的 astrometry 解。AutoPhOT 自己的 plate solve（wcs.redo_wcs）預設關掉，
    # 直接用我們的 WCS；網頁勾了「AutoPhOT plate solve」就打開。我們有任何一張解不出來，這次自動打開，
    # 讓 AutoPhOT 自己解（redo_wcs 是整次執行共用的）。「全部設定」裡自己給了 wcs.redo_wcs 就照那個。
    wcs_cfg = config.setdefault('wcs', {})
    wcs_user = 'wcs.redo_wcs' in (cfg_in.get('overrides') or {}) or 'redo_wcs' in (extra.get('wcs') or {})
    unsolved = our_astrometry(science_frames(cfg_in), str(tdir))      # 疊圖之前：對齊也用得到 WCS
    if wcs_user:
        print(f"[web] AutoPhOT plate solve {'on' if wcs_cfg.get('redo_wcs') else 'off'} (wcs.redo_wcs in All settings)", flush=True)
    elif cfg_in.get('ap_solve'):
        wcs_cfg['redo_wcs'] = True
        print('[web] AutoPhOT plate solve on (chosen in the workspace)', flush=True)
    elif unsolved:
        wcs_cfg['redo_wcs'] = True
        print(f'[web] AutoPhOT plate solve on: our astrometry did not solve {len(unsolved)} image(s): '
              + ', '.join(os.path.basename(p) for p in unsolved[:5]) + (' …' if len(unsolved) > 5 else ''), flush=True)
    else:
        wcs_cfg['redo_wcs'] = False
        print('[web] AutoPhOT plate solve off: using the WCS from our astrometry', flush=True)
    auto_wcs = not wcs_user and not cfg_in.get('ap_solve') and not wcs_cfg['redo_wcs']
    if use_stack:
        cfg_in['stacks'] = make_stacks(cfg_in, str(tdir))
    import prepare
    _clean = prepare.Prepare.clean
    top = os.path.realpath(config['fits_dir'])
    stack_info = cfg_in.get('stacks') or {}
    stacks = {os.path.realpath(os.path.join(top, k)) for k in stack_info}
    members = {os.path.realpath(os.path.join(top, m)) for v in stack_info.values() for m in v.get('members', [])}

    def clean_selected(self):
        files = _clean(self)
        kept = files
        if cfg_in.get('top_only', True):
            kept = [f for f in kept if os.path.realpath(os.path.dirname(f)) == top]
            if len(kept) != len(files):
                print(f'[web] skip subfolders: {len(files) - len(kept)} FITS in subfolders not measured', flush=True)
        is_stack = lambda f: os.path.realpath(f) in stacks
        n_stack = sum(map(is_stack, kept))
        if use_stack:
            if not with_singles:
                n_mem = sum(1 for f in kept if os.path.realpath(f) in members)
                print(f'[web] stacking: measuring {n_stack} stack(s) instead of their {n_mem} frames', flush=True)
                kept = [f for f in kept if os.path.realpath(f) not in members]
        elif n_stack:
            print(f'[web] stacking off: {n_stack} stacked image(s) not measured', flush=True)
            kept = [f for f in kept if not is_stack(f)]
        return kept
    prepare.Prepare.clean = clean_selected

    # 模板：AutoPhOT 下載（或找到上傳的）模板之後，也先用我們的 astrometry 解，所以接在 find_templates 後面。
    # 下載的巡天模板解不出來時，它 header 本來的 WCS 照樣能用；其他模板解不出來就打開 AutoPhOT plate solve。
    # 接著做 TS 時，把科學影像（和模板）裁成以目標為中心、模板真正有資料的方框（preprocessing.trim_image，邊長 arcmin），
    # 這樣對齊時模板幾乎蓋滿整張圖。run_photometry 之後每張影像的設定都從同一份 input_yaml 複製，這時改還來得及。
    # 網頁 TS 區可以關掉（ts_crop），「全部設定」裡自己給了 trim_image 也不動它。
    trim_set = float((config.get('preprocessing') or {}).get('trim_image') or 0) > 0
    crop = cfg_in.get('ts_crop', True) and not trim_set and ra is not None
    if ts['do_subtraction']:
        _find_templates = prepare.Prepare.find_templates

        def find_solve_crop(self, *args, **kwargs):
            files = _find_templates(self, *args, **kwargs)
            unsolved_tpl = [p for p in our_astrometry(files, str(tdir), 'template')
                            if not (DOWNLOADED_TEMPLATE.match(os.path.basename(p)) and has_wcs(p))]
            if auto_wcs and unsolved_tpl:
                self.input_yaml.setdefault('wcs', {})['redo_wcs'] = True
                print(f'[web] AutoPhOT plate solve on: our astrometry did not solve template(s) '
                      + ', '.join(os.path.basename(p) for p in unsolved_tpl), flush=True)
            if not crop:
                return files
            side = template_box(files, ra, dec)
            if side is None:
                return files
            if side < 0.5:
                print('[web] the target is at the edge of the template or outside it: no crop; choose another survey '
                      'or your own template', flush=True)
                return files
            # 留一點邊（plain_yaml_numbers 之外再保險一次：一定是 Python float）
            box = float(round(float(side) * 0.9, 2))
            self.input_yaml.setdefault('preprocessing', {})['trim_image'] = box
            print(f'[web] template subtraction: measuring a {box:g}′ box around the target, the part of each image the '
                  f'template covers' + (' (small: few calibration stars; a survey with a bigger template helps)' if box < 3 else ''),
                  flush=True)
            return files
        prepare.Prepare.find_templates = find_solve_crop
    print(f"[web] fits_dir = {config['fits_dir']}", flush=True)
    print(f"[web] target   = {config['target_name']}  RA={config.get('target_ra')}  Dec={config.get('target_dec')}", flush=True)
    t0 = time.time()
    output_file = AutomatedPhotometry.run_photometry(default_input=config)
    result = {'output_file': output_file, 'time': time.time(), 'elapsed': time.time() - t0, 'plots': [], 'errors': []}

    # 光變曲線與表：存在 LightCurve_Output.csv 同一個資料夾
    if output_file and os.path.isfile(output_file):
        import matplotlib
        matplotlib.use('Agg')
        from lightcurve import generate_photometry_table, plot_lightcurve
        for method in ('PSF', 'AP'):
            for name, fn in (('plot_lightcurve', lambda: plot_lightcurve(output_file, snr_limit=3, method=method, input_yaml=config)),
                             ('generate_photometry_table', lambda: generate_photometry_table(output_file, snr_limit=3, method=method, input_yaml=config))):
                try:
                    fn()
                    print(f'[web] {name} ({method}) done', flush=True)
                except Exception as e:                      # 一種方法沒有結果時不要整個失敗
                    result['errors'].append(f'{name} ({method}): {type(e).__name__}: {e}')
                    print(f'[web] {name} ({method}) failed: {e}', flush=True)
    (tdir / 'result.json').write_text(json.dumps(result, indent=1))
    print(f'[web] finished in {result["elapsed"]:.0f} s → {output_file}', flush=True)


def _record_exit(code):
    try:
        (Path(sys.argv[1]).resolve() / 'exit.json').write_text(json.dumps({'code': code, 'time': time.time()}))
    except OSError:
        pass


if __name__ == '__main__':
    try:
        main()
    except SystemExit as e:
        _record_exit(0 if e.code in (None, 0) else 1)
        raise
    except BaseException:
        _record_exit(1)
        raise
    _record_exit(0)
