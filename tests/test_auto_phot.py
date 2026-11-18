"""Automatic photometry of each night's frames (app/services/auto_phot.py). AutoPhOT, the database and the object
lookup are replaced by stubs; what is checked is which frames are taken, how a night is worked through, and that a
re-run replaces the Transient page points it added before."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import auto_phot as svc

NIGHT = date(2026, 11, 16)


def _frame(root, target, day, tel='SLT', band='rp', t='163933'):
    d = root / target
    d.mkdir(parents=True, exist_ok=True)
    p = d / f'Calibrated_{target}_D{day}T{t}_T{t}_{band}_Astrodon_2018_{tel}_Andor-DZ936_bin1_gain0.95_300sec_MJD61360.fits'
    p.write_bytes(b'SIMPLE')
    return p


class FakeDB:
    def __init__(self):
        self.rows = {}

    def upsert(self, night, target, telescope, **f):
        r = self.rows.setdefault((night, target, telescope), {'id': len(self.rows) + 1, 'night': night.isoformat(),
                                                             'target': target, 'telescope': telescope, 'phot': [],
                                                             'phot_ids': [], 'n_frames': 0, 'status': 'queued'})
        r.update(f)
        return dict(r)

    def for_night(self, night):
        return [dict(r) for (n, *_), r in self.rows.items() if n == night]


@pytest.fixture
def fake(monkeypatch):
    import app.db.auto_phot as dbmod
    db = FakeDB()
    monkeypatch.setattr(dbmod, 'upsert', db.upsert)
    monkeypatch.setattr(dbmod, 'for_night', db.for_night)
    monkeypatch.setattr(svc, 'choose_template', lambda ra, dec: None)     # no network; tests that want TS set one
    return db


def test_scan_takes_the_night_and_groups_by_target_and_telescope(tmp_path):
    a = _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    b = _frame(tmp_path, 'AT2026ajog', '2026-11-16', band='gp', t='170032')
    _frame(tmp_path, 'AT2026ajog', '2026-11-15')                       # another night
    c = _frame(tmp_path, 'SN2026gzf', '2026-11-16', tel='LOT')
    (tmp_path / 'AT2026ajog' / 'notes.txt').write_text('x')
    got = svc.scan(NIGHT, tmp_path)
    assert got == {('AT2026ajog', 'SLT'): [a, b], ('SN2026gzf', 'LOT'): [c]}
    assert svc._band(a) == 'r' and svc._band(b) == 'g'


def test_labels_and_names():
    assert svc.label('SLT') == 'SLT(AUTO, w/o TS)' and svc.label('LOT', ts=True) == 'LOT(AUTO)'
    assert svc.workspace_name(NIGHT, 'AT2026ajog', 'SLT', svc.NO_TS_SUFFIX) == 'AUTO_AT2026ajog_SLT_20261116_noTS'
    assert svc.skipped_name('EP261007a') and svc.skipped_name('EPt261111a') and not svc.skipped_name('AT2026ajog')
    assert svc.workspace_name(NIGHT, "Tabby's Star", 'SLT') == 'AUTO_Tabby_s_Star_SLT_20261116'
    assert svc.last_night(datetime(2026, 11, 17, 13, 30, tzinfo=svc.TZ8)) == NIGHT


def test_ep_targets_are_skipped_without_running(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'EP261007a', '2026-11-16')
    monkeypatch.setattr(svc, 'position', lambda *a: pytest.fail('EP targets are not looked up'))
    msg = svc.run_night(NIGHT, root=tmp_path)
    assert fake.rows[(NIGHT, 'EP261007a', 'SLT')]['status'] == 'skipped'
    assert '1 skipped' in msg


def test_a_night_runs_once_and_a_retry_replaces_the_points(tmp_path, fake, monkeypatch):
    frames = [_frame(tmp_path, 'AT2026ajog', '2026-11-16'), _frame(tmp_path, 'AT2026ajog', '2026-11-16', t='170032')]
    calls = {'run': 0, 'deleted': [], 'inserted': 0}
    monkeypatch.setattr(svc, 'position', lambda t, f: ('2026ajog', 6.540778, -0.324788))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, **k: 'AUTO_AT2026ajog_SLT_20261116')
    monkeypatch.setattr(svc, '_frame_pngs', lambda *a: ['r'])
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda tid, paths, origin='': {'added': paths, 'skipped': []})

    def run_and_wait(tid, progress=None, stop=None):
        calls['run'] += 1
        progress({'done': 2, 'total': 2, 'failed': 0})
        return {'status': 'done'}
    monkeypatch.setattr(svc, '_run_and_wait', run_and_wait)
    monkeypatch.setattr(svc, '_points', lambda tid: [{'filter': 'r', 'mjd': 61360.7, 'mag': 19.57, 'err': 0.09, 'lim': 21.1,
                                                     'snr': 12.3, 'det': True, 'veto': '', 'image': 'x'}])

    def fake_import(phot, obj, tel, old_ids):
        calls['deleted'].append(list(old_ids))
        calls['inserted'] += 1
        return [100 + calls['inserted']]
    monkeypatch.setattr(svc, '_import', fake_import)

    svc.run_night(NIGHT, root=tmp_path)
    row = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert row['status'] == 'done' and row['obj_name'] == '2026ajog' and row['phot_ids'] == [101] and row['n_frames'] == 2
    assert 'already done' in svc.run_night(NIGHT, root=tmp_path) and calls['run'] == 1      # done: not again
    svc.run_night(NIGHT, only=('AT2026ajog', 'SLT'), force=True, root=tmp_path)             # Retry
    assert calls['run'] == 2 and calls['deleted'] == [[], [101]] and fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]['phot_ids'] == [102]


def test_no_position_is_a_failure_with_a_reason(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'NGC884', '2026-11-16')
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, None, None))
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'NGC884', 'SLT')]
    assert r['status'] == 'failed' and 'No position' in r['reason']


def test_stacks_fall_back_to_single_frames(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    stacks = []
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 6.54, -0.32))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, stack=True, **k: stacks.append(stack) or 'AUTO_X')
    monkeypatch.setattr(svc, '_frame_pngs', lambda *a: [])
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda *a, **k: {})
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: {'status': 'done'})
    monkeypatch.setattr(svc, '_points', lambda tid: [] if len(stacks) == 1 else [{'filter': 'r', 'mjd': 1, 'mag': None, 'err': None,
                                                                                 'lim': 21, 'snr': 1, 'det': False, 'veto': 'S/N', 'image': 'x'}])
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert stacks == [True, False] and r['status'] == 'done' and 'Not a Kinder object' in r['reason']


def test_a_rerun_from_the_page_measures_the_stacks_only(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    stacks = []
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 6.54, -0.32))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, stack=True, **k: stacks.append(stack) or 'AUTO_X')
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda *a, **k: {})
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: {'status': 'done'})
    monkeypatch.setattr(svc, '_points', lambda tid: [])
    svc.run_night(NIGHT, only=('AT2026ajog', 'SLT'), force=True, root=tmp_path, stack_only=True)
    assert stacks == [True] and fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]['status'] == 'failed'


def test_a_repeat_target_is_measured_frame_by_frame(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026aifu', '2026-11-16')
    stacks = []
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 6.54, -0.32))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'is_repeat', lambda t, tel: True)
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, stack=True, **k: stacks.append(stack) or 'AUTO_X')
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda *a, **k: {})
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: {'status': 'done'})
    monkeypatch.setattr(svc, '_points', lambda tid: [])
    svc.run_night(NIGHT, only=('AT2026aifu', 'SLT'), force=True, root=tmp_path, stack_only=True)   # even from the page
    assert stacks == [False]


def test_a_stopped_target_is_not_measured(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 6.54, -0.32))
    monkeypatch.setattr(svc, 'stop_requested', lambda *a: True)
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, **k: pytest.fail('a stopped target must not start'))
    svc.run_target(NIGHT, 'AT2026ajog', 'SLT', [tmp_path / 'x.fits'])
    r = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert r['status'] == 'failed' and r['reason'] == 'Stopped'


def test_points_from_the_photometry_table(monkeypatch):
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'photometry', lambda tid, run=None: {
        'limits': [('limiting_mag_3s2n', 3.0), ('limiting_mag_5s2n', 5.0)],
        'rows': [{'filter': 'r', 'mjd': 61360.7, 'psf': 19.57, 'psf_err': 0.09, 'det': True, 'limits': [21.1, 20.8], 'snr': 12.3, 'veto': '', 'name': 'a'},
                 {'filter': 'g', 'mjd': 61360.7, 'psf': 21.3, 'psf_err': 0.4, 'det': False, 'limits': [20.9, 20.5], 'snr': 1.2, 'veto': 'S/N 1.2 < 3.0', 'name': 'b'}]})
    pts = svc._points('t')
    assert pts[0] == {'filter': 'r', 'mjd': 61360.7, 'mag': 19.57, 'err': 0.09, 'lim': 21.1, 'snr': 12.3, 'det': True, 'veto': '',
                      'image': 'a', 'ts': False, 'ts_note': 'not subtracted'}
    assert pts[1]['mag'] is None and pts[1]['lim'] == 20.9 and pts[1]['veto'].startswith('S/N')


def test_trigger_page_api_needs_a_login(client):
    assert client.get('/api/daily_trigger/auto_phot').status_code == 401
    assert client.post('/api/daily_trigger/auto_phot/1/retry').status_code == 401


def test_picker_status_for_ticked_frames(fake, monkeypatch):
    fake.upsert(NIGHT, 'AT2026ajog', 'SLT', status='running', n_frames=6, n_done=2, phot=[])
    monkeypatch.setattr(svc, 'last_night', lambda now=None: NIGHT)
    got = svc.for_frames('AT2026ajog', [('2026-11-16', 'SLT'), ('2026-11-15', 'SLT'), ('2026-10-01', 'SLT'), (None, None)])
    assert [(g['night'], g['status']) for g in got] == [('2026-11-15', 'waiting'), ('2026-11-16', 'running')]
    assert got[1]['n_done'] == 2
    assert svc.for_frames('EP261007a', [('2026-11-16', 'SLT')]) == []


def test_the_night_is_listed_before_it_is_measured(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    _frame(tmp_path, 'SN2026gzf', '2026-11-16', tel='LOT')
    seen = []

    def run_target(night, target, telescope, frames, stop=None):
        seen.append({k[1]: r['status'] for k, r in fake.rows.items()})
        return fake.upsert(night, target, telescope, status='done')
    monkeypatch.setattr(svc, 'run_target', run_target)
    svc.run_night(NIGHT, root=tmp_path)
    assert seen[0] == {'AT2026ajog': 'queued', 'SN2026gzf': 'queued'}       # both listed before the first one runs


def test_auto_runs_have_their_own_slot(tmp_path, monkeypatch):
    import os
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'runs_root', lambda: tmp_path)
    for name, auto in (('mine', False), ('theirs', False), ('AUTO_x_SLT_20261116', True)):
        (tmp_path / name).mkdir()
        ap._write_json(tmp_path / name / 'target.json', {'auto': {'night': '2026-11-16'}} if auto else {})
        ap._write_json(tmp_path / name / 'job.json', {'status': 'running', 'pid': os.getpid()})
    assert ap._running_count() == 2 and ap._running_count(auto=True) == 1


def test_a_run_left_from_a_restart_is_waited_for_not_started_again(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'AT2026afqt', '2026-11-16')
    monkeypatch.setattr(svc, 'position', lambda t, f: ('2026afqt', 10.0, 5.0))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'choose_template', lambda ra, dec: 'panstarrs')
    monkeypatch.setattr(svc, '_still_running', lambda tid: True)
    monkeypatch.setattr(svc, 'ensure_workspace', lambda *a, **k: pytest.fail('must not touch a running workspace'))
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: pytest.fail('must not start another run'))
    waited = []
    monkeypatch.setattr(svc, '_wait', lambda tid, progress=None, stop=None: waited.append(tid) or {'status': 'done'})
    monkeypatch.setattr(svc, '_points', lambda tid: [{'filter': 'r', 'mjd': 1, 'mag': 19.0, 'err': .05, 'lim': 21, 'snr': 20,
                                                     'det': True, 'veto': '', 'image': 'x', 'ts': True}])
    monkeypatch.setattr(svc, '_import', lambda *a: [7])
    monkeypatch.setattr(svc, '_frame_pngs', lambda *a: [])
    svc.run_night(NIGHT, root=tmp_path)
    assert waited == ['AUTO_AT2026afqt_SLT_20261116'] and fake.rows[(NIGHT, 'AT2026afqt', 'SLT')]['status'] == 'done'


def test_a_night_measures_several_targets_at_once(tmp_path, fake, monkeypatch):
    import threading
    import time
    from app.services.pipeline import autophot as ap
    for i in range(6):
        _frame(tmp_path, f'AT2026aa{chr(97 + i)}', '2026-11-16')
    monkeypatch.setattr(ap, 'MAX_RUNNING_AUTO', 3)
    lock, now, peak = threading.Lock(), [0], [0]

    def run_target(night, target, telescope, frames, stop=None):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        time.sleep(0.15)
        with lock:
            now[0] -= 1
        return fake.upsert(night, target, telescope, status='failed' if target.endswith('f') else 'done')

    monkeypatch.setattr(svc, 'run_target', run_target)
    msg = svc.run_night(NIGHT, root=tmp_path)
    assert peak[0] == 3                                      # as many as the slots, not more
    assert '5 measured, 1 failed' in msg


def test_whole_field_is_drawn_north_up_whatever_the_frame_rotation(tmp_path):
    import io

    import numpy as np
    from astropy.coordinates import SkyCoord
    from astropy.io import fits
    from astropy.wcs import WCS
    from PIL import Image

    from app.services.pipeline import previews
    w = WCS(naxis=2)                                  # 0.8″/px, rotated 30° and mirrored
    w.wcs.ctype, w.wcs.crval, w.wcs.crpix = ['RA---TAN', 'DEC--TAN'], [150.0, 20.0], [200.5, 150.5]
    a, s = np.radians(30), 0.8 / 3600
    w.wcs.cd = [[s * np.cos(a), -s * np.sin(a)], [s * np.sin(a), s * np.cos(a)]]
    data = np.random.default_rng(1).normal(100, 3, (300, 400))
    star = SkyCoord(150.0, 20.0 + 60 / 3600, unit='deg')           # 60″ north of the centre
    x, y = (int(round(float(v))) for v in w.world_to_pixel(star))
    data[y - 2:y + 3, x - 2:x + 3] += 5000
    path = tmp_path / 'f.fits'
    fits.PrimaryHDU(data, header=w.to_header()).writeto(path)

    grid = previews.field_grid(path, max_px=200)
    assert grid['w'] > 320 and grid['h'] > 240                     # the rotated frame's north-up bounding box
    tx, ty = previews.target_px(grid, star)
    assert abs(tx - (grid['nx'] - 1) / 2) < 1.5 and ty < (grid['ny'] - 1) / 2 - 60 / grid['scale'] + 2   # north is up
    im = np.asarray(Image.open(io.BytesIO(previews.field_png(path, None, grid))).convert('L'))
    near = im[int(ty) - 2:int(ty) + 3, int(tx) - 2:int(tx) + 3]
    assert (near == 255).sum() >= 3                                 # the star lands where the ring goes
    my = int(grid['ny'] - 1 - ty)                                   # and not where a south-up image would put it
    assert (im[my - 2:my + 3, int(tx) - 2:int(tx) + 3] == 255).sum() <= 1


def test_a_band_the_main_catalog_lacks_gets_its_own_catalog(monkeypatch):
    """Pan-STARRS has no u: u frames are calibrated against SDSS where it covers the target, else Gaia XP."""
    from app.services.pipeline import coverage
    monkeypatch.setattr(coverage, 'check', lambda ra, dec: {'catalogs': {'pan_starrs': {'ok': True}, 'sdss': {'ok': True}}})
    assert svc.band_catalogs(10, 20, 'pan_starrs', ['u', 'g', 'r']) == {'u': 'sdss'}
    assert svc.band_catalogs(10, 20, 'sdss', ['u', 'g']) == {}
    monkeypatch.setattr(coverage, 'check', lambda ra, dec: {'catalogs': {'pan_starrs': {'ok': True}, 'sdss': {'ok': False}}})
    assert svc.band_catalogs(10, 20, 'pan_starrs', ['u', 'i']) == {'u': 'gaia'}


def _pt(image, band='r', ts=True, mag=19.5, note=''):
    return {'filter': band, 'mjd': 61360.7, 'mag': mag, 'err': 0.05, 'lim': 21.0, 'snr': 20.0, 'det': True,
            'veto': '', 'image': image, 'ts': ts, 'ts_note': note}


@pytest.mark.parametrize('row, ok', [
    ({'ts': True, 'align_q': 'pass', 'fscale_disc': 0.3, 'artifacts': 0}, True),
    ({'ts': True, 'align_q': 'warn', 'fscale_disc': None, 'artifacts': None}, True),
    ({'ts': False}, False),
    ({'ts': True, 'align_q': 'fail'}, False),
    ({'ts': True, 'fscale_disc': 35.0}, False),
    ({'ts': True, 'artifacts': 25}, False),
])
def test_ts_check(row, ok):
    assert svc.ts_check(row)[0] is ok


def test_merge_takes_the_no_ts_point_only_where_the_subtraction_failed():
    phot = [_pt('stack_g', 'g'), _pt('stack_r', 'r', ts=False, note='kernel flux scale off by 40%'), _pt('stack_u', 'u', ts=False)]
    fallback = [_pt('stack_g', 'g', ts=False, mag=18.0), _pt('stack_r', 'r', ts=False, mag=18.1)]
    out = {p['image']: p for p in svc.merge_fallback(phot, fallback)}
    assert out['stack_g']['mag'] == 19.5 and out['stack_g']['ts']                 # good TS kept
    assert out['stack_r']['mag'] == 18.1 and not out['stack_r']['ts'] and '40%' in out['stack_r']['ts_note']
    assert out['stack_u']['mag'] == 19.5 and not out['stack_u']['ts']             # nothing to replace it with


def test_import_labels_each_point():
    pts = svc.import_points([_pt('a'), _pt('b', ts=False), {**_pt('c'), 'det': False, 'mag': None, 'err': None}], 'SLT')
    assert [p['telescope'] for p in pts] == ['SLT(AUTO)', 'SLT(AUTO, w/o TS)', 'SLT(AUTO)']
    assert pts[2]['magnitude'] == 21.0 and pts[2]['magnitude_error'] is None     # a limit


def _ts_setup(monkeypatch, tmp_path, ts_phot, nots_phot):
    _frame(tmp_path, 'AT2026ajog', '2026-11-16')
    runs = []
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 6.54, -0.32))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'choose_template', lambda ra, dec: 'panstarrs')
    monkeypatch.setattr(svc, 'ensure_workspace',
                        lambda *a, stack=True, template=None, **k: runs.append((stack, template)) or
                        ('AUTO_X' if template else 'AUTO_X_noTS'))
    monkeypatch.setattr(svc, '_frame_pngs', lambda *a: [])
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda *a, **k: {})
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: {'status': 'done'})
    monkeypatch.setattr(svc, '_points', lambda tid: ts_phot if tid == 'AUTO_X' else nots_phot)
    return runs


def test_a_good_subtraction_is_used_alone(tmp_path, fake, monkeypatch):
    runs = _ts_setup(monkeypatch, tmp_path, [_pt('stack_r')], [])
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert runs == [(True, 'panstarrs')] and r['status'] == 'done' and r['phot'][0]['ts'] and r['workspace'] == 'AUTO_X'


def test_a_bad_subtraction_falls_back_to_no_ts_for_that_image(tmp_path, fake, monkeypatch):
    runs = _ts_setup(monkeypatch, tmp_path, [_pt('stack_r', ts=False, note='template alignment failed'), _pt('stack_g', 'g')],
                     [_pt('stack_r', ts=False, mag=18.4), _pt('stack_g', 'g', ts=False, mag=18.9)])
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert runs == [(True, 'panstarrs'), (True, None)]
    got = {p['image']: (p['mag'], p['ts']) for p in r['phot']}
    assert got == {'stack_r': (18.4, False), 'stack_g': (19.5, True)} and r['workspace'] == 'AUTO_X'


def test_a_ts_run_with_nothing_is_replaced_by_the_no_ts_run(tmp_path, fake, monkeypatch):
    runs = _ts_setup(monkeypatch, tmp_path, [], [_pt('stack_r', ts=False, mag=18.4)])
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'AT2026ajog', 'SLT')]
    assert runs == [(True, 'panstarrs'), (True, None)] and r['status'] == 'done' and r['workspace'] == 'AUTO_X_noTS'


@pytest.mark.parametrize('cores, parallel, env, expected', [
    (24, 4, None, 5),        # prod: a night's five bands measured together
    (8, 4, None, 1),
    (2, 4, None, 1),
    (None, 4, None, 1),
    (24, 4, '12', 12),       # AUTO_PHOT_NCPU overrides
    (24, 4, 'x', 5),
])
def test_auto_ncpu_shares_the_cores_between_auto_runs(monkeypatch, cores, parallel, env, expected):
    from app.services import auto_phot
    from app.services.pipeline import autophot as ap
    monkeypatch.setattr(auto_phot.os, 'cpu_count', lambda: cores)
    monkeypatch.setattr(ap, 'MAX_RUNNING_AUTO', parallel)
    if env is None:
        monkeypatch.delenv('AUTO_PHOT_NCPU', raising=False)
    else:
        monkeypatch.setenv('AUTO_PHOT_NCPU', env)
    assert auto_phot.auto_ncpu() == expected


def test_better_ts_keeps_each_bands_better_subtraction():
    prim = [_pt('stack_r'), _pt('stack_g', 'g'), _pt('stack_z', 'z', ts=False, note='template alignment failed')]
    prim[0]['snr'] = 12.3
    alt = [{**_pt('stack_r'), 'snr': 2.4, 'det': False}, {**_pt('stack_g', 'g'), 'snr': 120.0},
           {**_pt('stack_z', 'z'), 'snr': 13.5}]
    out = {p['image']: p for p in svc.better_ts(prim, alt, use={'r', 'g', 'z'})}
    assert out['stack_r']['snr'] == 12.3                       # the primary detection beats the alt's limit
    assert out['stack_g']['snr'] == 120.0                      # higher S/N
    assert out['stack_z']['ts'] and out['stack_z']['snr'] == 13.5   # a passed subtraction beats a failed one
    assert svc.better_ts(prim, alt, use=set()) == prim          # no other survey: nothing to compare


def test_auto_templates_are_tried_with_the_other_survey(tmp_path, fake, monkeypatch):
    _frame(tmp_path, 'SN2026gzf', '2026-11-16', tel='LOT')
    runs = []
    monkeypatch.setattr(svc, 'position', lambda t, f: (None, 149.93, 0.42))
    monkeypatch.setattr(svc, 'choose_catalog', lambda ra, dec: 'pan_starrs')
    monkeypatch.setattr(svc, 'choose_template', lambda ra, dec: 'auto')
    monkeypatch.setattr(svc, 'ensure_workspace',
                        lambda *a, stack=True, template=None, force=None, **k: runs.append((template, force)) or
                        ('AUTO_X_altTS' if force else 'AUTO_X' if template else 'AUTO_X_noTS'))
    monkeypatch.setattr(svc, 'workspace_name', lambda n, t, tel, suffix='': 'AUTO_X' + suffix)
    monkeypatch.setattr(svc, '_frame_pngs', lambda *a: [])
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'add_files', lambda *a, **k: {})
    monkeypatch.setattr(svc, '_run_and_wait', lambda *a, **k: {'status': 'done'})
    monkeypatch.setattr(svc, '_still_running', lambda tid: False)
    choices = {'AUTO_X': {'r': 'legacy'}, 'AUTO_X_altTS': {'r': 'panstarrs'}}
    monkeypatch.setattr(svc, 'template_choices', lambda tid: choices[tid])
    pts = {'AUTO_X': [{**_pt('stack_r'), 'snr': 2.4, 'det': False}], 'AUTO_X_altTS': [{**_pt('stack_r'), 'snr': 12.3}]}
    monkeypatch.setattr(svc, '_points', lambda tid: pts[tid])
    svc.run_night(NIGHT, root=tmp_path)
    r = fake.rows[(NIGHT, 'SN2026gzf', 'LOT')]
    assert runs == [('auto', None), ('auto', {'r': 'panstarrs'})]          # no no-TS run: both subtractions passed
    assert r['status'] == 'done' and r['phot'][0]['snr'] == 12.3 and r['phot'][0]['template'] == 'panstarrs'


def test_why_a_band_was_not_subtracted(tmp_path, monkeypatch):
    import json
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'tdir', lambda tid, must=True: tmp_path / tid)
    ws = tmp_path / 'ws'
    for band, survey, side in (('u', 'skymapper', 1.3), ('r', 'panstarrs', 8.2)):
        d = ws / 'images' / 'templates' / f'{band}_template'
        d.mkdir(parents=True)
        (d / svc.TEMPLATE_MARKER).write_text(json.dumps({'survey': survey, 'side': side}))
    (ws / 'web_run.log').write_text('[web] template subtraction: measuring a 1.16′ box around the target, ...\n')
    assert svc.no_ts_reason('ws', 'u') == 'the SkyMapper template has only 1.3′ of data around the target'
    assert svc.no_ts_reason('ws', 'r') == 'too few stars in the 1.16′ box around the target to align the Pan-STARRS template'
    assert svc.no_ts_reason('ws', 'z') == 'no survey template in this band'
    (ws / 'web_run.log').write_text('[web] template subtraction: measuring a 7.2′ box around the target\n')
    assert svc.no_ts_reason('ws', 'r') == 'AutoPhOT could not align the Pan-STARRS template'
    assert svc.no_ts_reason('noTS', 'r') is None                 # a run without templates says nothing


def test_a_redrawn_status_line_is_not_a_question():
    """AT2026aifu 2026-11-17: GaiaXPy's lines end in a carriage return; Kinder answered them and stopped the run."""
    from app.services.pipeline.autophot import _looks_like_prompt
    assert _looks_like_prompt('Saving file...Done! Output saved to path: ./output_synthetic_photometry.csv\r') is False
    assert _looks_like_prompt('Running query...\r') is False
    assert _looks_like_prompt('Telescope name not found, enter it: ') is True
    assert _looks_like_prompt('Choose one\n> \n') is True
    assert _looks_like_prompt('[1/5] [OK] a.fits\n') is False
