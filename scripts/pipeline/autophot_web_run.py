"""Kinder Pipeline 的 AutoPhOT 執行檔：用 AutoPhOT 自己的 Python 跑（app/services/pipeline/autophot.py 呼叫），
AutoPhOT 的資料夾由環境變數 AUTOPHOT_DIR 給（沒給就用工作目錄），工作目錄是工作區。不要用 Kinder 的 .venv。

  python autophot_web_run.py <工作區資料夾>
工作區的 target.json 是網頁存的設定；跑完把輸出位置寫進 result.json，結束碼寫進 exit.json
（網頁有好幾個 gunicorn worker，靠這個檔案知道這次是成功還是失敗）。
AutoPhOT 碰到不認得的望遠鏡、濾鏡會用 input() 問，網頁把回答從 stdin（工作區裡的 FIFO）送進來。
"""
import json
import os
import sys
import time
from pathlib import Path


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


def main():
    tdir = Path(sys.argv[1]).resolve()
    ap_dir = os.environ.get('AUTOPHOT_DIR') or os.getcwd()     # AutoPhOT 的模組（autophot、prepare、lightcurve）在這裡
    if ap_dir not in sys.path:
        sys.path.insert(1, ap_dir)
    cfg_in = json.loads((tdir / 'target.json').read_text())

    from autophot import AutomatedPhotometry
    import yaml

    config = AutomatedPhotometry.load()
    config['fits_dir'] = cfg_in['fits_dir']
    config['wdir'] = cfg_in['wdir']
    ra, dec = parse_coord(cfg_in.get('ra'), cfg_in.get('dec'))
    if ra is not None:
        # 給了座標就不能再給真實名稱（AutoPhOT 會當成設定衝突），名稱只留在網頁顯示；網頁一定會給座標
        config['target_name'], config['target_ra'], config['target_dec'] = 'Transient', ra, dec
    else:
        config['target_name'] = cfg_in['name']
    config['nCPU'] = int(cfg_in.get('ncpu') or 1)
    config['catalog']['use_catalog'] = cfg_in.get('catalog') or 'sdss'     # AutoPhOT 沒有預設星表，null 會直接報錯；網頁預設 SDSS
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
