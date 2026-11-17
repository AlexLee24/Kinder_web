"""CASTOR check (/castor/snr_check): unlisted, password only; the report lives outside git."""
import json

import pytest
from werkzeug.security import generate_password_hash

from app.blueprints.astronomy_tools import castor_report as cr

URL = '/castor/snr_check'
ROWS = [
    {'tel': 'SLT', 'cam': 'SLT_DZ936', 'band': 'r', 'target': 'AT2026ajog', 'image': 'stack x6', 'date': '2026-11-16T16:55',
     'exp': '6x300s', 'X': 2.45, 'fwhm': 4.03, 'ts': 'TS', 'mag': 20.372, 'err': 0.196, 'snr_meas': 16.8, 'chi2': 0.91,
     'snr_noise': 16.8, 'snr_castor': 11.5, 'ratio': 1.46, 'ratio_noise': 1.46, 'kinder': '1'},
    {'tel': 'LOT', 'cam': 'Sophia', 'band': 'r', 'target': 'SN2025wny', 'image': '2026-09-12T194159', 'date': '2026-09-12T19:41',
     'exp': '1x300s', 'X': 1.69, 'fwhm': 2.38, 'ts': 'w/o TS', 'mag': 19.475, 'err': 0.035, 'snr_meas': 37.4, 'chi2': 1.46,
     'snr_noise': 45.1, 'snr_castor': 42.7, 'ratio': 0.87, 'ratio_noise': 1.06, 'kinder': ''},
    {'tel': 'LOT', 'cam': 'Sophia', 'band': 'g', 'target': 'SN2025wny', 'image': '2026-02-12T125603', 'date': '2026-02-12T12:56',
     'exp': '1x300s', 'X': 1.05, 'fwhm': 1.97, 'ts': 'w/o TS', 'mag': 20.302, 'err': 0.04, 'snr_meas': 32.3, 'chi2': '',
     'snr_noise': 32.3, 'snr_castor': 29.3, 'ratio': 1.10, 'ratio_noise': 1.10, 'kinder': ''},
]


@pytest.fixture
def report(tmp_path, monkeypatch):
    f = tmp_path / 'snr_check.json'
    f.write_text(json.dumps({'password_hash': generate_password_hash('castor'), 'title': 'Test report',
                             'generated': '2026-11-18', 'notes': [{'title': 'Findings', 'items': ['Secret finding']}],
                             'rows': ROWS}))
    monkeypatch.setattr(cr, 'REPORT_FILE', f)
    return f


def test_no_report_file_is_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(cr, 'REPORT_FILE', tmp_path / 'missing.json')
    assert client.get(URL).status_code == 404


def test_locked_page_shows_only_the_password_form(client, report):
    r = client.get(URL)
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'type="password"' in page
    assert 'Secret finding' not in page and 'AT2026ajog' not in page
    assert r.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert 'no-store' in r.headers['Cache-Control']


def test_wrong_password_stays_locked(client, report):
    r = client.post(URL, data={'password': 'nope'})
    assert r.status_code == 401
    assert 'Wrong password.' in r.get_data(as_text=True)
    assert 'AT2026ajog' not in client.get(URL).get_data(as_text=True)


def test_right_password_opens_the_report(client, report):
    r = client.post(URL, data={'password': 'castor'})
    assert r.status_code == 303
    page = client.get(URL).get_data(as_text=True)
    assert 'Test report' in page and 'Secret finding' in page
    assert 'AT2026ajog' in page and 'stack ×6' in page and 'SN2025wny' in page
    assert page.index('LOT · Sophia 2048B · g') < page.index('LOT · Sophia 2048B · r') < page.index('SLT · Andor iKon-L DZ936 · r')
    # Lock forgets it
    client.post(URL + '/lock')
    assert 'AT2026ajog' not in client.get(URL).get_data(as_text=True)


def test_a_browser_form_post_passes_the_same_origin_check(client, report):
    """A browser sends Origin with the form; the page must not make it 'null' (Referrer-Policy: no-referrer does)."""
    from tests.conftest import BASE_URL
    page = client.get(URL)
    assert 'no-referrer' not in page.headers.get('Referrer-Policy', '')
    r = client.post(URL, data={'password': 'castor'}, headers={'Origin': BASE_URL})
    assert r.status_code == 303


def test_a_new_password_signs_everyone_out(client, report):
    client.post(URL, data={'password': 'castor'})
    data = json.loads(report.read_text())
    data['password_hash'] = generate_password_hash('another-one')
    report.write_text(json.dumps(data))
    assert 'AT2026ajog' not in client.get(URL).get_data(as_text=True)


def test_password_tries_are_limited(client, report):
    for _ in range(cr.LOGIN_BURST):
        client.post(URL, data={'password': 'nope'})
    r = client.post(URL, data={'password': 'castor'})
    assert 'Too many tries' in r.get_data(as_text=True)


def test_groups_and_medians():
    g = cr.groups(ROWS)
    assert [(x['tel'], x['band']) for x in g] == [('LOT', 'g'), ('LOT', 'r'), ('SLT', 'r')]
    assert g[1]['ratio'] == (0.87, 0.87, 0.87) and g[2]['camera'] == 'Andor iKon-L DZ936'


def test_the_page_is_not_linked_from_the_site(client):
    for path in ('/', '/astronomy_tools', '/sky_cutouts'):
        r = client.get(path)
        if r.status_code == 200:
            assert '/castor/snr_check' not in r.get_data(as_text=True)
