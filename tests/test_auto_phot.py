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
    assert svc.label('SLT') == 'SLT(AUTO, w/o TS)'
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

    def fake_import(tid, obj, tel, old_ids):
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


def test_points_from_the_photometry_table(monkeypatch):
    import app.services.pipeline.autophot as ap
    monkeypatch.setattr(ap, 'photometry', lambda tid, run=None: {
        'limits': [('limiting_mag_3s2n', 3.0), ('limiting_mag_5s2n', 5.0)],
        'rows': [{'filter': 'r', 'mjd': 61360.7, 'psf': 19.57, 'psf_err': 0.09, 'det': True, 'limits': [21.1, 20.8], 'snr': 12.3, 'veto': '', 'name': 'a'},
                 {'filter': 'g', 'mjd': 61360.7, 'psf': 21.3, 'psf_err': 0.4, 'det': False, 'limits': [20.9, 20.5], 'snr': 1.2, 'veto': 'S/N 1.2 < 3.0', 'name': 'b'}]})
    pts = svc._points('t')
    assert pts[0] == {'filter': 'r', 'mjd': 61360.7, 'mag': 19.57, 'err': 0.09, 'lim': 21.1, 'snr': 12.3, 'det': True, 'veto': '', 'image': 'a'}
    assert pts[1]['mag'] is None and pts[1]['lim'] == 20.9 and pts[1]['veto'].startswith('S/N')


def test_trigger_page_api_needs_a_login(client):
    assert client.get('/api/daily_trigger/auto_phot').status_code == 401
    assert client.post('/api/daily_trigger/auto_phot/1/retry').status_code == 401
