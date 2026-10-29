"""Pipeline paths: AutoPhOT is always the copy in this repository; only the workspaces and calibrated-frame
folders come from kinder.env. No database: nothing is read from the admin settings any more."""
from app.services.pipeline import config


def test_autophot_is_always_the_copy_in_the_repository(monkeypatch):
    monkeypatch.setenv('AUTOPHOT_DIR', '/somewhere/else')              # no longer read
    monkeypatch.setenv('AUTOPHOT_PYTHON', '/somewhere/else/python')
    p = config.paths()
    assert p['autophot_dir'] == config.VENDORED
    assert p['autophot_python'] == config.VENDORED / '.venv' / 'bin' / 'python'


def test_folders_come_from_kinder_env(monkeypatch, tmp_path):
    monkeypatch.delenv('AUTOPHOT_RUNS', raising=False)
    monkeypatch.delenv('CALIBRATED_SCIENCE_DIR', raising=False)
    assert config.paths()['autophot_runs'] == config.VENDORED_RUNS
    assert config.paths()['calibrated_dir'] == config.DEFAULT_CALIBRATED
    monkeypatch.setenv('AUTOPHOT_RUNS', str(tmp_path / 'runs'))
    monkeypatch.setenv('CALIBRATED_SCIENCE_DIR', str(tmp_path / 'cal'))
    assert config.paths()['autophot_runs'] == tmp_path / 'runs'
    assert config.paths()['calibrated_dir'] == tmp_path / 'cal'
    sources = {d['key']: d['source'] for d in config.describe()}
    assert sources['autophot_dir'] == 'this repository'
    assert sources['autophot_runs'] == 'kinder.env AUTOPHOT_RUNS'
