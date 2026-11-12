"""Tools › Spectrum: where a DESI TARGETID's coadd is looked for (app/services/astro/desi_spectrum.py)
and the /spectrum page + /api/spectrum/desi/<targetid> route. No network: Data Lab and the DESI
server are stubbed; the real download is checked by hand (see the module docstring)."""
import pytest

from app.services.astro import desi_spectrum as ds

TID = 39627857210645888


def _dl(**kw):
    row = dict(release='dr1', survey='main', program='dark', healpix=19468, z=0.444, zerr=3e-5, zwarn=0,
               spectype='GALAXY', subtype='', deltachi2=334.8, ra=0.489, dec=3.029, primary=True)
    row.update(kw)
    return row


def test_plan_follows_data_lab_primary_first():
    dl = [_dl(), _dl(survey='sv3', program='bright', primary=False), _dl(release='edr', survey='sv3', primary=False)]
    plan = ds._plan(None, dl, None, None, None, None, None)
    assert plan == [('dr1', 'main', 'dark', 19468), ('dr1', 'sv3', 'bright', 19468), ('edr', 'sv3', 'dark', 19468)]


def test_plan_filters_on_release_survey_program():
    dl = [_dl(), _dl(survey='sv3', program='bright', primary=False), _dl(release='edr', survey='sv3', primary=False)]
    assert ds._plan(None, dl, 'edr', None, None, None, None) == [('edr', 'sv3', 'dark', 19468)]
    assert ds._plan(None, dl, None, 'sv3', 'bright', None, None) == [('dr1', 'sv3', 'bright', 19468)]


def test_plan_uses_cat_desi_when_data_lab_is_silent():
    cat = {'release': 'dr1', 'survey': 'main', 'program': 'bright', 'healpix': 123, 'ra': 10.0, 'dec': 5.0}
    assert ds._plan(cat, [], None, None, None, None, None)[0] == ('dr1', 'main', 'bright', 123)


def test_plan_searches_the_pixel_of_a_given_position():
    plan = ds._plan(None, [], None, None, None, 0.489, 3.029)
    pix = ds.healpix_of(0.489, 3.029)
    assert plan[0] == ('dr1', 'main', 'dark', pix) and len(plan) > 10
    assert all(p[3] == pix for p in plan)


def test_plan_is_empty_without_anything_to_go_on():
    assert ds._plan(None, [], None, None, None, None, None) == []


def test_data_lab_csv_is_parsed(monkeypatch):
    csv_dr1 = ('survey,program,healpix,z,zerr,zwarn,spectype,subtype,deltachi2,mean_fiber_ra,mean_fiber_dec,zcat_primary\n'
               'sv3,bright,19468,0.44,1e-5,0,GALAXY,"",12.5,0.489,3.03,f\n'
               'main,dark,19468,0.4442,3e-5,0,GALAXY,"",334.78,0.489,3.03,t\n')

    class R:
        def __init__(self, text):
            self.text, self.ok, self.status_code = text, True, 200

    class S:
        def get(self, url, params, headers, timeout):
            assert f'targetid = {TID}' in params['sql']
            return R(csv_dr1 if 'desi_dr1' in params['sql'] else 'survey,program\n')

    rows = ds.lookup_datalab(TID, S())
    assert [(r['survey'], r['program'], r['primary']) for r in rows] == [('main', 'dark', True), ('sv3', 'bright', False)]
    assert rows[0]['healpix'] == 19468 and rows[0]['deltachi2'] == 334.78


def test_spectrum_page_renders(client):
    r = client.get(f'/spectrum?targetid={TID}')
    assert r.status_code == 200
    assert str(TID).encode() in r.data and b'js/spectrum.js' in r.data


def test_api_returns_targetid_as_string(client, monkeypatch):
    seen = {}

    def fake(targetid, **kw):
        seen.update(kw, targetid=targetid)
        return {'targetid': str(targetid), 'arms': {}, 'cached': True}

    monkeypatch.setattr(ds, 'get_spectrum', fake)
    r = client.get(f'/api/spectrum/desi/{TID}?release=dr1&survey=main&program=dark&ra=bad')
    assert r.status_code == 200 and r.get_json()['targetid'] == str(TID)
    assert seen == {'targetid': TID, 'release': 'dr1', 'survey': 'main', 'program': 'dark',
                    'ra': None, 'dec': None, 'refresh': False}


def test_api_passes_spectrum_errors_through(client, monkeypatch):
    def fake(targetid, **kw):
        raise ds.SpectrumError('nope', 404)

    monkeypatch.setattr(ds, 'get_spectrum', fake)
    r = client.get(f'/api/spectrum/desi/{TID}')
    assert r.status_code == 404 and r.get_json() == {'error': 'nope'}


@pytest.mark.parametrize('bad', ['0', '-5'])
def test_api_rejects_bad_ids(client, bad):
    assert client.get(f'/api/spectrum/desi/{bad}').status_code in (400, 404)
