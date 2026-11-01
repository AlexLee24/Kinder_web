"""NAS backup bot (app/services/bots/nas_backup.py): which raw nights, masters and calibrated targets move, and a
real move into a folder that stands in for the mounted NAS share. No SMB, no database."""
import json
import os
from datetime import date

import pytest

from app.services.bots import nas_backup as nb

TODAY = date(2026, 11, 15)          # keeps 202611 and 202610


def mjd(d):
    return (d - date(1858, 11, 17)).days


def touch(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / 'reduction_pipeline'
    lulin = r / 'RAW_IMG_Sync' / 'home' / 'janet' / 'lulin_data'
    for night in ('LOT20260830', 'SLT20260930', 'LOT20261005', 'LOT20261101'):
        touch(lulin / night / 'janet' / f'{night}_001.fits')
        touch(lulin / night / 'flat' / f'{night}_flat.fits')
    touch(lulin / 'notes.txt')                                      # no date: stays
    mb = r / 'MasterBDF'
    setup = 'Master_BIAS_LOT_SOPHIA_bin1_x2048_y2048_gain0.92'
    for d in (date(2026, 8, 30), date(2026, 9, 10), date(2026, 10, 5), date(2026, 11, 1)):
        touch(mb / f'{setup}_MJD{mjd(d)}.fits')
    lone = 'Master_FLAT_SLT_Andor_bin1_x1024_y1024_rp'
    touch(mb / f'{lone}_MJD{mjd(date(2026, 6, 1))}.fits')           # the only (so newest) of its setup: stays
    touch(mb / 'Master_BIAS_LOT_SOPHIA_bin1_x2048_y2048_gain0.92.fits')   # undated global master: stays
    cal = r / 'Calibrated_Science'
    touch(cal / 'SN2025old' / f'Calibrated_SN2025old_rp_MJD{mjd(date(2026, 8, 20))}.fits')
    touch(cal / 'SN2025old' / f'Calibrated_SN2025old_gp_MJD{mjd(date(2026, 9, 1))}.fits')
    touch(cal / 'SN2026new' / f'Calibrated_SN2026new_rp_MJD{mjd(date(2026, 8, 1))}.fits')
    touch(cal / 'SN2026new' / f'Calibrated_SN2026new_rp_MJD{mjd(date(2026, 11, 2))}.fits')
    touch(cal / 'SN2026edge' / f'Calibrated_SN2026edge_rp_MJD{mjd(date(2026, 9, 14))}.fits')   # 62 days, September
    monkeypatch.setenv('REDUCTION_PIPELINE_DIR', str(r))
    monkeypatch.delenv('OBS_RAW_DIR', raising=False)
    monkeypatch.setattr(nb, 'MOVES_FILE', tmp_path / 'moves.jsonl')
    return r


def names(items):
    return sorted(str(rel) for _, _, rel in items)


def test_kept_months_and_names():
    assert nb.kept_months(date(2026, 11, 1)) == {'202611', '202610'}
    assert nb.kept_months(date(2027, 1, 3)) == {'202701', '202612'}
    assert nb.month_of_name('LOT20261031') == '202610'
    assert nb.month_of_name('SN2026fvx-20260318_122935-gp.fts') == '202603'
    assert nb.month_of_name('notes.txt') is None
    assert nb.month_of_name('x_20261399') is None                   # not a month


def test_plan(root):
    got = names(nb.plan(root, TODAY))
    lulin = 'RAW_IMG_Sync/home/janet/lulin_data'
    setup = 'Master_BIAS_LOT_SOPHIA_bin1_x2048_y2048_gain0.92'
    assert got == sorted([
        f'{lulin}/LOT20260830', f'{lulin}/SLT20260930',
        f'MasterBDF/{setup}_MJD{mjd(date(2026, 8, 30))}.fits',
        f'MasterBDF/{setup}_MJD{mjd(date(2026, 9, 10))}.fits',
        'Calibrated_Science/SN2025old', 'Calibrated_Science/SN2026edge',
    ])


def test_master_needs_its_raw_month_gone(root):
    """Early in a month last month's masters stay even when older than 30 days: their raw frames are still here."""
    got = names(nb.plan(root, date(2026, 10, 20)))                 # keeps 202610 and 202609
    assert not any('MasterBDF' in g and f'MJD{mjd(date(2026, 9, 10))}' in g for g in got)
    assert any(f'MJD{mjd(date(2026, 8, 30))}' in g for g in got)


def test_move_to_nas(root, tmp_path, monkeypatch):
    nas = tmp_path / 'nas'
    nas.mkdir()
    monkeypatch.setenv('NAS_IP', '100.77.208.119')
    monkeypatch.setenv('NAS_USER', 'u')
    monkeypatch.setenv('NAS_PWD', 'p@ss/word')
    monkeypatch.setenv('NAS_PATH', 'smb://100.77.208.119/great_data/Auto_Backup')
    monkeypatch.delenv('NAS_ARCHIVE_DRY_RUN', raising=False)
    monkeypatch.setattr(nb, 'mount', lambda s: (nas, False))
    # a file copied by an earlier run that stopped before deleting: skipped, not copied again
    old = root / 'Calibrated_Science' / 'SN2025old'
    first = sorted(old.iterdir())[0]
    touch(nas / 'Auto_Backup' / 'Calibrated_Science' / 'SN2025old' / first.name)
    # Synology metadata from a night rsynced off a Synology: dropped, not moved (the NAS refuses @eaDir)
    eadir = root / 'RAW_IMG_Sync/home/janet/lulin_data/LOT20260830/janet/@eaDir'
    touch(eadir / 'LOT20260830_001.fits' / 'SYNOINDEX_MEDIA_INFO', 10)
    lines = []
    assert nb.step(root, lines.append, today=TODAY) == 0, lines
    dest = nas / 'Auto_Backup'
    assert (dest / 'RAW_IMG_Sync/home/janet/lulin_data/LOT20260830/janet/LOT20260830_001.fits').is_file()
    assert (dest / 'RAW_IMG_Sync/home/janet/lulin_data/SLT20260930/flat/SLT20260930_flat.fits').is_file()
    assert len(list((dest / 'Calibrated_Science' / 'SN2025old').iterdir())) == 2
    assert len(list((dest / 'MasterBDF').iterdir())) == 2
    assert not list(dest.rglob('*' + nb.PART)) and not list(dest.rglob('@eaDir'))
    lulin = root / 'RAW_IMG_Sync' / 'home' / 'janet' / 'lulin_data'
    assert sorted(p.name for p in lulin.iterdir()) == ['LOT20261005', 'LOT20261101', 'notes.txt']
    assert not old.exists() and (root / 'Calibrated_Science' / 'SN2026new').is_dir()
    assert len(list((root / 'MasterBDF').iterdir())) == 4
    moves = nb.recent_moves()
    assert len(moves) == 6 and all(m['finished'] for m in moves)
    assert json.loads(nb.MOVES_FILE.read_text().splitlines()[0])['folder'] == 'RAW_IMG_Sync'
    assert 'p@ss' not in '\n'.join(lines)
    assert nb.step(root, lines.append, today=TODAY) == 0
    assert lines[-1] == 'Nothing to move to the NAS.'


def test_overview_totals_count_every_move(root):
    """The 30-day total adds up every move, not just the rows the page lists."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with open(nb.MOVES_FILE, 'w') as fh:
        for i in range(250):
            fh.write(json.dumps({'at': now, 'folder': 'MasterBDF', 'path': f'MasterBDF/m{i}.fits',
                                 'files': 1, 'bytes': 1000, 'finished': True}) + '\n')
    o = nb.overview(max_age=0)
    assert o['month'] == {'items': 250, 'files': 250, 'bytes': 250000}
    assert len(o['moves']) == 100 and o['moves'][0]['path'] == 'MasterBDF/m249.fits'


def test_dry_run_moves_nothing(root, monkeypatch):
    monkeypatch.setenv('NAS_IP', '1.2.3.4')
    monkeypatch.setenv('NAS_USER', 'u')
    monkeypatch.setenv('NAS_PWD', 'p')
    monkeypatch.setenv('NAS_PATH', 'great_data/Auto_Backup')
    monkeypatch.setenv('NAS_ARCHIVE_DRY_RUN', '1')
    monkeypatch.setattr(nb, 'mount', lambda s: pytest.fail('dry run must not mount'))
    lines = []
    assert nb.step(root, lines.append, today=TODAY) == 0
    assert sum(1 for x in lines if x.startswith('would move')) == 6
    assert (root / 'Calibrated_Science' / 'SN2025old').is_dir() and not nb.recent_moves()


def test_settings(monkeypatch):
    for k in ('NAS_IP', 'NAS_USER', 'NAS_PWD', 'NAS_PATH'):
        monkeypatch.delenv(k, raising=False)
    assert nb.settings() is None and not nb.configured()
    monkeypatch.setenv('NAS_PATH', 'smb://100.77.208.119/great_data/Auto_Backup')
    s = nb.settings()
    assert (s['ip'], s['share'], s['sub']) == ('100.77.208.119', 'great_data', 'Auto_Backup')
    assert 'NAS_USER' in nb.setup_problem() and 'NAS_PWD' in nb.setup_problem()


def test_find_mount_only_own_mounts(monkeypatch):
    me = nb.getpass.getuser()
    out = (f'//alex@100.77.208.119/great_data on /Volumes/great_data (smbfs, nodev, nosuid, mounted by someone_else)\n'
           f'//GUEST:@100.77.208.119/great_data on /Users/{me}/nas (smbfs, nodev, nosuid, mounted by {me})\n')

    class R:
        stdout = out
    monkeypatch.setattr(nb.subprocess, 'run', lambda *a, **k: R())
    assert str(nb.find_mount('100.77.208.119', 'great_data')) == f'/Users/{me}/nas'
    assert nb.find_mount('100.77.208.119', 'other') is None


def test_pipeline_busy(root, monkeypatch):
    from app.services.bots import reduction
    monkeypatch.setattr(reduction, 'external_runs', lambda: [])
    for name in nb.ACTIVITY:
        p = root / name
        if p.exists():
            os.utime(p, (1e9, 1e9))
    assert nb.pipeline_busy(root) == ''
    touch(root / 'Process_temp' / 'frame.fits')
    assert 'Process_temp' in nb.pipeline_busy(root)
