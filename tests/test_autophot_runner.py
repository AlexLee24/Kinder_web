"""scripts/pipeline/autophot_web_run.py: the template box it hands to AutoPhOT. AutoPhOT writes its settings to
images_REDUCED/input.yaml and every image's subprocess reads them back with yaml.safe_load, so the value must be a
plain float (a numpy scalar made every image of a run fail)."""
import importlib.util
import os

import numpy as np
import pytest
import yaml

fits = pytest.importorskip('astropy.io.fits')
from astropy.wcs import WCS  # noqa: E402

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'pipeline', 'autophot_web_run.py')
RA, DEC = 149.928635, 0.418438


@pytest.fixture(scope='module')
def runner():
    spec = importlib.util.spec_from_file_location('autophot_web_run', RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def template(path, blank_cols=0):
    """A 10' Pan-STARRS-like template (0.25"/px) on the target; the first blank_cols columns empty, as at a sky-cell edge."""
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.cdelt = [1200.5, 1200.5], [-0.25 / 3600, 0.25 / 3600]
    w.wcs.crval, w.wcs.ctype = [RA, DEC], ['RA---TAN', 'DEC--TAN']
    data = np.ones((2400, 2400), dtype='float32')
    data[:, :blank_cols] = np.nan
    fits.PrimaryHDU(data, header=w.to_header()).writeto(path)
    return str(path)


def test_box_is_the_data_around_the_target(runner, tmp_path):
    assert runner.template_box([template(tmp_path / 'full.fits')], RA, DEC) == pytest.approx(10, abs=0.01)
    # 3.5' blank on one side: the target is 1.5' from the data's edge, so the box is 3'
    assert runner.template_box([template(tmp_path / 'edge.fits', 840)], RA, DEC) == pytest.approx(3, abs=0.01)


def test_box_survives_autophots_input_yaml(runner, tmp_path):
    side = runner.template_box([template(tmp_path / 'edge.fits', 840)], RA, DEC)
    assert type(side) is float
    text = yaml.dump({'preprocessing': {'trim_image': float(round(side * 0.9, 2))}})
    assert yaml.safe_load(text)['preprocessing']['trim_image'] == pytest.approx(2.7, abs=0.01)


def test_urllib_gets_certifi_when_no_bundle_is_set(runner, monkeypatch):
    certifi = pytest.importorskip('certifi')
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    assert runner.ca_bundle() == certifi.where() == os.environ['SSL_CERT_FILE']
    monkeypatch.setenv('SSL_CERT_FILE', '/etc/ssl/mine.pem')
    assert runner.ca_bundle() == '/etc/ssl/mine.pem'           # a bundle someone chose stays


def test_a_tiny_template_does_not_shrink_the_others(runner, tmp_path, capsys):
    """AT 2026ajby 2026-11-17: SkyMapper u had 1.3′, so g/r/i/z were cut to 1.16′ (88 px) and none could be aligned."""
    full = template(tmp_path / 'r.fits')
    tiny = template(tmp_path / 'u.fits', 960)                    # data ends 1′ beside the target: a 2′ box
    assert runner.template_box([full, tiny], RA, DEC) == pytest.approx(10, abs=0.01)
    assert 'u.fits: only 2.0′ around the target' in capsys.readouterr().out
    assert runner.template_box([tiny], RA, DEC) == pytest.approx(2.0, abs=0.01)       # all tiny: the smallest


def test_gaiaxpy_does_not_save_its_table(runner, monkeypatch):
    """GaiaXPy's 'Done! Output saved to path' ends in a carriage return, which Kinder took for a question."""
    import sys
    import types
    seen = []
    fake = types.ModuleType('gaiaxpy')
    fake.generate = lambda *a, **kw: seen.append(kw) or 'table'
    monkeypatch.setitem(sys.modules, 'gaiaxpy', fake)
    runner.quiet_gaiaxpy()
    runner.quiet_gaiaxpy()                                       # once only
    assert fake.generate(['1'], photometric_system='x') == 'table'
    assert seen == [{'photometric_system': 'x', 'save_file': False}]
    fake.generate(['1'], save_file=True)
    assert seen[-1]['save_file'] is True


def test_vizier_falls_back_to_a_mirror(runner, tmp_path, monkeypatch):
    """CDS answered every query with 404 on 2026-11-18; the subprocesses read the mirror from ASTROPY_CONFIG_DIR."""
    monkeypatch.delenv('ASTROPY_CONFIG_DIR', raising=False)
    assert runner.vizier_mirror(str(tmp_path), ok=lambda h: True) is None
    assert 'ASTROPY_CONFIG_DIR' not in os.environ
    host = runner.vizier_mirror(str(tmp_path), ok=lambda h: h != 'vizier.cds.unistra.fr')
    assert host == 'vizier.cfa.harvard.edu'
    cfg = tmp_path / '.astropy_config' / 'astroquery.cfg'
    assert 'server = vizier.cfa.harvard.edu' in cfg.read_text()
    assert os.environ['ASTROPY_CONFIG_DIR'] == str(cfg.parent)
    monkeypatch.delenv('ASTROPY_CONFIG_DIR', raising=False)
    assert runner.vizier_mirror(str(tmp_path / 'b'), ok=lambda h: False) is None


def test_vizier_error_answers_leave_the_cache(runner, tmp_path):
    import pickle
    from types import SimpleNamespace as Resp           # what astroquery pickles has a .content, like this
    answers = {
        'html.pickle': b'<!doctype html>\n<html lang="en"><head><title>404</title></head></html>',
        'down.pickle': b'<?xml version="1.0"?><VOTABLE><RESOURCE><INFO ID="Error" name="Error" value="The database is '
                       b'not currently reachable."/><INFO name="QUERY_STATUS" value="ERROR">no connection</INFO></RESOURCE></VOTABLE>',
        'table.pickle': b'<?xml version="1.0"?><VOTABLE><RESOURCE><TABLE name="V/154/sdss16"></TABLE></RESOURCE></VOTABLE>',
        'none.pickle': b'<?xml version="1.0"?><VOTABLE><RESOURCE><INFO name="QUERY_STATUS" value="OK"/></RESOURCE></VOTABLE>',
    }
    for name, body in answers.items():
        (tmp_path / name).write_bytes(pickle.dumps(Resp(content=body)))
    (tmp_path / 'junk.pickle').write_bytes(b'not a pickle')
    assert sorted(runner.purge_vizier_errors(str(tmp_path))) == ['down.pickle', 'html.pickle']
    assert sorted(os.listdir(tmp_path)) == ['junk.pickle', 'none.pickle', 'table.pickle']
    assert runner.purge_vizier_errors(str(tmp_path / 'nowhere')) == []


def test_frames_are_grouped_in_time_order_per_visit():
    import sys
    sys.path.insert(0, 'scripts/pipeline')
    import autophot_web_run as r
    m = lambda h, mi: 61000 + (h * 60 + mi) / 1440   # noqa: E731
    e = [('u0', 'up', 'n', m(13, 0)), ('u1', 'up', 'n', m(13, 6)), ('g1', 'gp', 'n', m(13, 12)),
         ('u2', 'up', 'n', m(17, 0)), ('u3', 'up', 'n', m(17, 6)), ('u4', 'up', 'n', m(17, 12)), ('g2', 'gp', 'n', m(17, 18))]
    g = r.group_frames(e, {'u': 2, '*': 1})
    assert g[('up', 'n', '130000')] == ['u0', 'u1'] and g[('up', 'n', '170000')] == ['u2', 'u3', 'u4']
    assert g[('gp', 'n', '131200')] == ['g1'] and g[('gp', 'n', '171800')] == ['g2']
    assert r.group_frames(e)[('up', 'n', '')] == ['u0', 'u1', 'u2', 'u3', 'u4']        # no sizes: the whole night
    four = [(f'u{i}', 'up', 'n', m(13, 6 * i)) for i in range(4)]
    assert sorted(r.group_frames(four, {'u': 2}).values()) == [['u0', 'u1'], ['u2', 'u3']]
