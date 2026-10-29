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


def test_numpy_values_in_the_settings_are_written_as_plain_yaml(runner):
    """Any numpy number AutoPhOT or the runner puts in the settings (not only trim_image) must read back with safe_load."""
    runner.plain_yaml_numbers(yaml)
    cfg = {'preprocessing': {'trim_image': np.float64(3.86)}, 'n': np.int64(4), 'ok': np.bool_(True),
           'xy': np.array([1.5, 2.5]), 'nested': [{'v': np.float32(0.5)}]}
    back = yaml.safe_load(yaml.dump(cfg, default_flow_style=False))
    assert back == {'preprocessing': {'trim_image': 3.86}, 'n': 4, 'ok': True, 'xy': [1.5, 2.5], 'nested': [{'v': 0.5}]}


def test_our_astrometry_reports_the_frames_it_did_not_solve(runner, tmp_path, monkeypatch):
    """What decides whether AutoPhOT's own plate solve is turned on for a run: frames ours solved before are fine, a
    frame ours failed on is not, and without solve-field on the server nothing new is solved."""
    import sys
    sys.path.insert(0, os.path.dirname(RUNNER))
    import astrometry_solve as asv
    solved, failed, new = (template(tmp_path / f'{n}.fits') for n in ('solved', 'failed', 'new'))
    for path, mark in ((solved, 'solved'), (failed, 'failed')):
        with fits.open(path, mode='update') as hdul:
            hdul[0].header[asv.MARK] = mark
    monkeypatch.setattr(asv, 'find_solve_field', lambda: None)
    assert sorted(runner.our_astrometry([solved, failed, new], str(tmp_path))) == sorted([failed, new])
    assert runner.our_astrometry([solved], str(tmp_path)) == []
    # a downloaded survey template keeps its own WCS when ours fails on it
    assert runner.has_wcs(failed) and runner.DOWNLOADED_TEMPLATE.match('panstarrs_r_band_template.fits')
