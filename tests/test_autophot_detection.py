"""AutoPhOT's detection decision (vendored main._decide_detection): the reason a point is not a detection is kept,
and the centroid-offset veto scales with the seeing. main.py needs photutils etc., so only the function is loaded."""
import ast
import logging
from pathlib import Path

import numpy as np
import pytest

MAIN = Path(__file__).resolve().parent.parent / 'app' / 'vendor' / 'autophot' / 'main.py'


@pytest.fixture(scope='module')
def decide():
    if not MAIN.is_file():
        pytest.skip('vendored AutoPhOT not checked out')
    tree = ast.parse(MAIN.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_decide_detection')
    ns = {'np': np, 'logging': logging, '_matched_filter_rescue': lambda out, cfg: False}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MAIN), 'exec'), ns)
    return ns['_decide_detection']


def _out(**kw):
    base = {'snr': 12.3, 'flux_psf': 10.0, 'flux_ap': 13.5, 'reduced_chi2': 1.24, 'empirical_p_false': 0.016,
            'separation': 3.41}
    base.update(kw)
    return base


def test_offset_within_one_fwhm_is_a_detection(decide):
    out = _out()
    assert decide(out, {}, 3.0, False, False, 3.57) is True
    assert out['detection_veto'] == ''


def test_offset_veto_keeps_its_reason(decide):
    out = _out()
    assert decide(out, {}, 3.0, False, False, np.nan) is False       # no FWHM: the 2" floor
    assert 'fitted centroid 3.41' in out['detection_veto'] and 'max 2.00' in out['detection_veto']
    out = _out()
    assert decide(out, {'detection_max_offset_fwhm': 0}, 3.0, False, False, 3.57) is False


def test_low_snr_and_chi2_reasons(decide):
    out = _out(snr=2.0)
    assert decide(out, {}, 3.0, False, False, 3.0) is False
    assert out['detection_veto'] == 'S/N 2.0 < 3.0'
    out = _out(reduced_chi2=40.0)
    assert decide(out, {}, 3.0, False, False, 3.0) is False
    assert out['detection_veto'].startswith('reduced chi2 40.0')


# ── Kinder side: the reason in the photometry table, and the image preview ──

def _fits(path, ra=6.540778, dec=-0.324788, n=200, scale=0.789):
    from astropy.io import fits
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [n / 2, n / 2]
    w.wcs.cdelt = [-scale / 3600, scale / 3600]
    rng = np.random.default_rng(1)
    data = rng.normal(1000, 20, (n, n))
    data[n // 2 - 2:n // 2 + 3, n // 2 - 2:n // 2 + 3] += 500
    hdr = w.to_header()
    hdr['FILTER'] = 'rp'
    hdr['EXPTIME'] = 300
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.writeto(path, data.astype('float32'), hdr, overwrite=True)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    from app.services.pipeline import autophot as ap
    monkeypatch.setattr(ap, 'runs_root', lambda: tmp_path)
    tid = ap.create_workspace({'name': 'AT2026ajog_SLT_20261115'}, user='a@x')
    d = tmp_path / tid
    cfg = ap._read_json(d / 'target.json')
    cfg.update(fits_dir=str(d / 'images'), ra='6.540778', dec='-0.324788')
    ap._write_json(d / 'target.json', cfg)
    _fits(d / 'images' / 'Calibrated_AT2026ajog_r.fits')
    out = d / 'images_REDUCED' / 'Calibrated_AT2026ajog_r'
    out.mkdir(parents=True)
    _fits(out / 'diff_Calibrated_AT2026ajog_r.fits')
    return ap, tid, d


def test_veto_reason_for_old_rows():
    from app.services.pipeline import autophot as ap
    assert ap._veto({'is_detection': 'True'}) == ''
    assert ap._veto({'is_detection': 'False', 'detection_veto': 'reduced chi2 40.0 > 10.0'}) == 'reduced chi2 40.0 > 10.0'
    assert 'fitted centroid 3.41' in ap._veto({'is_detection': 'False', 'snr': '12.3', 'separation': '3.41'})
    assert 'S/N 2.0' in ap._veto({'is_detection': 'False', 'snr': '2.0'}, 3.0)


def test_preview_is_drawn_cached_and_survives_the_fits(ws):
    from app.services.pipeline import previews
    ap, tid, d = ws
    png = previews.preview_png(tid, 'Calibrated_AT2026ajog_r')
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    cache = d / 'images_REDUCED' / 'Calibrated_AT2026ajog_r' / previews.CACHE_NAME
    assert cache.is_file()
    (d / 'images' / 'Calibrated_AT2026ajog_r.fits').unlink()            # FITS deleted after keep_days
    (d / 'images_REDUCED' / 'Calibrated_AT2026ajog_r' / 'diff_Calibrated_AT2026ajog_r.fits').unlink()
    assert previews.preview_png(tid, 'Calibrated_AT2026ajog_r') == cache.read_bytes()
    with pytest.raises(ap.NotFound):
        previews.preview_png(tid, 'Other_image')
