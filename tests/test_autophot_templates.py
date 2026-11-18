"""scripts/pipeline/autophot_templates.py: a template survey per band, telescope.yml bands, stale Gaia caches."""
import importlib.util
import json
import os

import numpy as np
import pytest

fits = pytest.importorskip('astropy.io.fits')
yaml = pytest.importorskip('yaml')
from astropy.wcs import WCS  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, 'scripts', 'pipeline', 'autophot_templates.py')
RA, DEC = 47.9087, -2.0267


@pytest.fixture(scope='module')
def kt():
    spec = importlib.util.spec_from_file_location('autophot_templates', PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cutout(path, side_arcmin=10.0, data_rows=None, scale=1.0):
    """A cutout centred on the target, scale arcsec/px; only `data_rows` (from the bottom) hold data."""
    n = int(round(side_arcmin * 60 / scale))
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.cdelt = [n / 2 + 0.5, n / 2 + 0.5], [-scale / 3600, scale / 3600]
    w.wcs.crval, w.wcs.ctype = [RA, DEC], ['RA---TAN', 'DEC--TAN']
    data = np.ones((n, n), dtype='float32')
    if data_rows is not None:
        data[data_rows:] = np.nan
    fits.PrimaryHDU(data, w.to_header()).writeto(path, overwrite=True)
    return path


def fake(calls, survey, rows=None):
    def fn(ra, dec, size, dest, band, **kw):
        calls.append((survey, band))
        if rows == 'none':
            return None
        return cutout(dest / f'{survey}_{band}_band_template.fits', size, rows)
    return fn


def test_usable_side_is_twice_the_distance_to_the_nearest_edge(kt, tmp_path):
    full = cutout(tmp_path / 'a.fits')
    assert kt.usable_side(full, RA, DEC) == pytest.approx(10.0, abs=0.05)
    edge = cutout(tmp_path / 'b.fits', data_rows=456)         # data ends 2.6′ above the target (PS1 skycell edge)
    assert kt.usable_side(edge, RA, DEC) == pytest.approx(5.2, abs=0.05)


def test_pan_starrs_at_a_skycell_edge_gives_way_to_the_legacy_survey(kt, tmp_path):
    calls = []
    fetch = {'panstarrs': fake(calls, 'panstarrs', rows=456), 'legacy': fake(calls, 'legacy'),
             'sdss': fake(calls, 'sdss'), 'skymapper': fake(calls, 'skymapper')}
    p = kt.pick(RA, DEC, 10, tmp_path / 'templates', 'r', fetch=fetch)
    assert p.endswith('r_template/legacy_r_band_template.fits')
    assert calls == [('panstarrs', 'r'), ('legacy', 'r')]          # stops at the first big enough
    mk = json.loads((tmp_path / 'templates' / 'r_template' / kt.MARKER).read_text())
    assert mk['survey'] == 'legacy' and mk['side'] == pytest.approx(10.0, abs=0.05)
    assert sorted(os.listdir(tmp_path / 'templates' / 'r_template')) == [kt.MARKER, 'legacy_r_band_template.fits']


def test_a_full_pan_starrs_cutout_is_kept(kt, tmp_path):
    calls = []
    fetch = {s: fake(calls, s) for s in kt.FETCH}
    assert kt.pick(RA, DEC, 10, tmp_path, 'g', fetch=fetch).endswith('panstarrs_g_band_template.fits')
    assert calls == [('panstarrs', 'g')]


def test_u_comes_from_sdss_or_skymapper(kt, tmp_path):
    calls = []
    fetch = {'panstarrs': fake(calls, 'panstarrs'), 'legacy': fake(calls, 'legacy'),
             'sdss': fake(calls, 'sdss', rows='none'), 'skymapper': fake(calls, 'skymapper')}
    assert kt.pick(RA, DEC, 10, tmp_path, 'u', fetch=fetch).endswith('u_template/skymapper_u_band_template.fits')
    assert calls == [('sdss', 'u'), ('skymapper', 'u')]


def test_when_none_is_big_enough_the_biggest_is_used(kt, tmp_path):
    calls = []
    fetch = {'panstarrs': fake(calls, 'panstarrs', rows=456), 'legacy': fake(calls, 'legacy', rows=500),
             'sdss': fake(calls, 'sdss', rows='none'), 'skymapper': fake(calls, 'skymapper', rows=350)}
    assert kt.pick(RA, DEC, 10, tmp_path, 'z', fetch=fetch).endswith('legacy_z_band_template.fits')
    assert [c[0] for c in calls] == ['panstarrs', 'legacy', 'sdss', 'skymapper']


def test_no_survey_with_the_band(kt, tmp_path):
    fetch = {s: fake([], s, rows='none') for s in kt.FETCH}
    assert kt.pick(RA, DEC, 10, tmp_path, 'u', fetch=fetch) is None
    assert not (tmp_path / 'u_template').exists()


def test_the_choice_is_reused_and_a_new_size_redone(kt, tmp_path):
    calls = []
    fetch = {s: fake(calls, s) for s in kt.FETCH}
    first = kt.pick(RA, DEC, 10, tmp_path, 'i', fetch=fetch)
    (tmp_path / 'i_template' / 'zp_template.fits').write_bytes(b'derived by AutoPhOT')
    assert kt.pick(RA, DEC, 10, tmp_path, 'i', fetch=fetch) == first and len(calls) == 1
    assert (tmp_path / 'i_template' / 'zp_template.fits').exists()          # AutoPhOT's products stay while reused
    kt.pick(RA, DEC, 8, tmp_path, 'i', fetch=fetch)
    assert len(calls) == 2 and not (tmp_path / 'i_template' / 'zp_template.fits').exists()


def test_an_old_pan_starrs_folder_is_cleared_when_the_survey_changes(kt, tmp_path):
    old = tmp_path / 'r_template'
    old.mkdir()
    (old / 'panstarrs_r_band_template.fits').write_bytes(b'old')
    (old / 'panstarrs_r_band_template.fits.original').write_bytes(b'old')   # AutoPhOT would prefer this one
    fetch = {'panstarrs': fake([], 'panstarrs', rows=456), 'legacy': fake([], 'legacy'),
             'sdss': fake([], 'sdss'), 'skymapper': fake([], 'skymapper')}
    kt.pick(RA, DEC, 10, tmp_path, 'r', fetch=fetch)
    assert sorted(os.listdir(old)) == [kt.MARKER, 'legacy_r_band_template.fits']


def test_install_replaces_autophots_pan_starrs_download(kt, tmp_path, monkeypatch):
    class Mod:
        @staticmethod
        def download_panstarrs_template(ra, dec, size, template_folder, band='r'):
            return cutout(os.path.join(template_folder, 'ps1.fits'), size)

        @staticmethod
        def download_sdss_template(ra, dec, size, template_folder, f='r'):
            return None
    seen = {}
    monkeypatch.setattr(kt, 'pick', lambda *a, **k: seen.update(args=a, fns=k['autophot_fns']) or 'x')
    kt.install(Mod)
    assert Mod.download_panstarrs_template(ra=RA, dec=DEC, size=10, template_folder='t', band='z') == 'x'
    assert seen['args'] == (RA, DEC, 10, 't', 'z') and set(seen['fns']) == {'panstarrs', 'sdss'}


def test_telescope_yml_gets_the_template_bands(kt, tmp_path):
    p = tmp_path / 'telescope.yml'
    p.write_text(yaml.safe_dump({'LEGACY': {'INSTRUME': {'SURVEY': {'Name': 'LEGACY+SURVEY', 'g': 'g', 'r': 'r', 'i': 'i'}}},
                                 'LOT': {'INSTRUME': {'x': {'r': 'r'}}}}))
    assert kt.ensure_telescope_bands(p) is True
    doc = yaml.safe_load(p.read_text())
    assert doc['LEGACY']['INSTRUME']['SURVEY']['z'] == 'z'
    assert {b: doc['SDSS']['INSTRUME']['Imaging'][b] for b in 'ugriz'} == {b: b for b in 'ugriz'}
    assert doc['SkyMapper']['INSTRUME']['SG_32_Det']['u'] == 'u'
    assert doc['LOT'] == {'INSTRUME': {'x': {'r': 'r'}}}                     # others untouched
    assert kt.ensure_telescope_bands(p) is False                          # once only


def test_gaia_cache_without_xp_photometry_is_removed(kt, tmp_path):
    d = tmp_path / 'catalog_queries' / 'gaia' / 'transient'
    d.mkdir(parents=True)
    (d / 'stale.csv').write_text('source_id,ra,dec,phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag\n1,2,3,4,5,6\n')
    (d / 'good.csv').write_text('source_id,ra,dec,SdssStd_mag_u,SdssStd_mag_error_u\n1,2,3,4,5\n')
    assert kt.purge_stale_gaia(tmp_path) == ['stale.csv']
    assert sorted(os.listdir(d)) == ['good.csv']
    assert kt.purge_stale_gaia(tmp_path / 'nowhere') == []


def test_a_forced_survey_is_tried_first_and_kept_apart(kt, tmp_path):
    calls = []
    fetch = {'panstarrs': fake(calls, 'panstarrs', rows=456), 'legacy': fake(calls, 'legacy'),
             'sdss': fake(calls, 'sdss'), 'skymapper': fake(calls, 'skymapper')}
    # the alt run: Pan-STARRS has only 5.2′ but it is the survey asked for and ≥ MIN_FORCE_SIDE
    p = kt.pick(RA, DEC, 10, tmp_path, 'r', fetch=fetch, force='panstarrs')
    assert p.endswith('panstarrs_r_band_template.fits') and calls == [('panstarrs', 'r')]
    # a later unforced pick is not served from the forced marker
    assert kt.pick(RA, DEC, 10, tmp_path, 'r', fetch=fetch).endswith('legacy_r_band_template.fits')
    # too little of the forced survey: the usual order decides
    calls.clear()
    tiny = {**fetch, 'skymapper': fake(calls, 'skymapper', rows=360)}
    got = kt.pick(RA, DEC, 10, tmp_path / 'b', 'g', fetch=tiny, force='skymapper')   # SkyMapper 2.0′ < 3′
    assert got.endswith('legacy_g_band_template.fits')            # then Pan-STARRS 5.2′, Legacy 10′
    assert [c[0] for c in calls] == ['skymapper', 'panstarrs', 'legacy']


def test_target_grid_is_centred(kt):
    w = kt.target_grid(RA, DEC, 8.0, kt.SKYMAPPER_SCALE)
    n = w.pixel_shape[0]
    assert n == round(8 * 60 / kt.SKYMAPPER_SCALE)
    x, y = w.all_world2pix(RA, DEC, 0)
    assert x == pytest.approx((n - 1) / 2) and y == pytest.approx((n - 1) / 2)


def test_a_choice_from_an_older_version_is_fetched_again(kt, tmp_path):
    """AT 2026ajby u: the 1.3′ SkyMapper template from before the target-centred grid was reused on the rerun."""
    calls = []
    fetch = {s: fake(calls, s) for s in kt.FETCH}
    kt.pick(RA, DEC, 10, tmp_path, 'u', fetch=fetch)
    mk = tmp_path / 'u_template' / kt.MARKER
    old = json.loads(mk.read_text())
    assert old['version'] == kt.MARKER_VERSION
    del old['version']
    mk.write_text(json.dumps(old))
    kt.pick(RA, DEC, 10, tmp_path, 'u', fetch=fetch)
    assert len(calls) == 2


def test_the_grid_header_has_a_cd_matrix(kt):
    """AutoPhOT's relative WCS correction reads wcs.cd ('No cd is present' otherwise)."""
    w = kt.target_grid(RA, DEC, 8.0, kt.SKYMAPPER_SCALE)
    h = kt.cd_header(w)
    assert 'PC1_1' not in h and 'CDELT1' not in h
    assert h['CD1_1'] == pytest.approx(-kt.SKYMAPPER_SCALE / 3600) and h['CD2_2'] == pytest.approx(kt.SKYMAPPER_SCALE / 3600)
    back = WCS(h)
    assert back.wcs.has_cd()
    assert back.all_world2pix(RA, DEC, 0) == pytest.approx(w.all_world2pix(RA, DEC, 0))


def test_sdss_cache_without_u_is_removed(kt, tmp_path):
    d = tmp_path / 'catalog_queries' / 'sdss' / 'transient'
    d.mkdir(parents=True)
    (d / 'qso.csv').write_text('DR16Q,SDSS,RAJ2000,DEJ2000,Plate,MJD\n1,2,3,4,5,6\n')     # VII/289/dr16q, no u
    (d / 'stars.csv').write_text('objID,RA_ICRS,DE_ICRS,umag,e_umag,gmag\n1,2,3,4,5,6\n')
    assert kt.purge_stale_sdss(tmp_path) == ['qso.csv']
    assert sorted(os.listdir(d)) == ['stars.csv']
    assert kt.purge_stale_sdss(tmp_path / 'nowhere') == []


def test_autophots_telescope_yml_writes_are_whole_and_locked(kt, tmp_path):
    """Three runs rewriting the shared telescope.yml at once left 'lat: n' + 'll' in it (2026-11-18)."""
    import types
    p = tmp_path / 'telescope.yml'
    p.write_text('OLD: {}\n')
    mod = types.ModuleType('prepare')
    assert kt.atomic_telescope_writes(mod) is True
    assert kt.atomic_telescope_writes(mod) is False                     # once
    with mod.open(str(p), 'w') as f:
        yaml.dump({'SLT': {'location': {'lat': None}}}, f)
        assert p.read_text() == 'OLD: {}\n'                             # nothing half-written meanwhile
    assert yaml.safe_load(p.read_text()) == {'SLT': {'location': {'lat': None}}}
    assert (tmp_path / '.telescope.lock').exists()
    assert not [x for x in os.listdir(tmp_path) if x.endswith('.tmp')]
    other = tmp_path / 'other.txt'
    with mod.open(str(other), 'w') as f:                                 # anything else: the real open
        f.write('x')
    assert other.read_text() == 'x'
    with mod.open(str(p)) as f:
        assert 'SLT' in f.read()


def test_telescope_bands_are_written_whole(kt, tmp_path):
    p = tmp_path / 'telescope.yml'
    p.write_text(yaml.safe_dump({'LOT': {'INSTRUME': {'x': {'r': 'r'}}}}))
    assert kt.ensure_telescope_bands(p) is True
    assert yaml.safe_load(p.read_text())['SkyMapper']['INSTRUME']['SG_32_Det']['u'] == 'u'
    assert not [x for x in os.listdir(tmp_path) if x.endswith('.tmp')]
