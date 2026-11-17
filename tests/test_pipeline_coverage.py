"""Pipeline coverage check (which catalogs / template surveys cover a position) and the Legacy DR10/DR11 template
choice. The live services are replaced by stubs."""
import pytest

from app.services.pipeline import autophot as ap
from app.services.pipeline import coverage as cv


def _live(sdss=(True, '12 SDSS objects within 2′'), sm=(False, 'outside SkyMapper DR4'),
          dr10=(True, 'LS-DR10 r-band imaging here'), dr11=(True, 'LS-DR11 r-band imaging here'), datalab=True):
    return {'sdss': sdss, 'skymapper': sm, 'dr10': dr10, 'dr11': dr11, 'datalab': datalab}


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, 'runs_root', lambda: tmp_path)
    return tmp_path


def test_footprints_and_live_answers(runs, monkeypatch):
    calls = []
    monkeypatch.setattr(cv, '_live', lambda ra, dec: calls.append((ra, dec)) or _live(datalab=False))
    r = cv.check(6.540778, -0.324788)
    assert r['catalogs']['pan_starrs']['ok'] and r['catalogs']['sdss']['ok'] and r['catalogs']['gaia']['ok']
    assert r['catalogs']['skymapper']['ok'] is False
    assert r['catalogs']['legacy']['ok'] and 'Tractor brick' in r['catalogs']['legacy']['note']   # Data Lab down
    assert r['templates']['legacy_dr11']['ok'] and r['templates']['panstarrs']['ok']
    cv.check(6.540778, -0.324788)
    assert len(calls) == 1                                       # cached
    south = cv._build(100, -60, _live(sdss=(False, 'outside'), sm=(True, 'x')))
    assert south['catalogs']['pan_starrs']['ok'] is False and south['templates']['panstarrs']['ok'] is False


def test_unsure_answers_are_not_cached(runs, monkeypatch):
    calls = []
    monkeypatch.setattr(cv, '_live', lambda ra, dec: calls.append(1) or _live(sdss=(None, 'could not ask')))
    assert cv.check(10, 10)['catalogs']['sdss']['ok'] is None
    cv.check(10, 10)
    assert len(calls) == 2


def test_parse_takes_sexagesimal():
    ra, dec = cv.parse('00:26:09.79', '-00:19:29.2')
    assert abs(ra - 6.540792) < 1e-4 and abs(dec + 0.324778) < 1e-4
    with pytest.raises(ap.PipelineError):
        cv.parse('nope', 'x')


def test_dr11_is_a_template_choice():
    assert 'legacy_dr11' in ap.TS_DOWNLOAD and ap.TS_DOWNLOAD_LABELS['legacy_dr11'] == 'Legacy Survey DR11'
    assert ap.DOWNLOADED_TEMPLATE_RE.match('legacy_z_band_template.fits')
