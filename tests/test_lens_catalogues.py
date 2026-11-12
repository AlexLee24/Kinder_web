"""DETECT lens matches: catalogue names, grade / probability, links (app/services/detect/lens_catalogues.py)."""
from urllib.parse import parse_qs, urlparse

from app.services.detect import lens_catalogues as lc

EUCLID = {'lens_id': 1, 'ra': 37.9656, 'dec': -59.5841, 'lens_grade': 'A', 'lens_probability': None,
          'reference': 'Euclid-DR1-26Nov12',
          'catalogue_ids': {'Euclid-DR1-26Nov12': {'name': 'EUCL-DR1-L023521', 'id': '15arcsec_near_RADEC_Tile1'}}}


def test_euclid_links_the_lens_page():
    d = lc.describe(EUCLID)
    (c,) = d['catalogues']
    assert d['measure'] == 'Grade A'
    assert c['url'] == 'https://euclid-eclipse-lenses.org/lens.html?lens=15arcsec_near_RADEC_Tile1'
    assert c['id'] == 'EUCL-DR1-L023521' and c['site'] == 'https://euclid-eclipse-lenses.org/'
    assert d['photo_url'].startswith('https://www.legacysurvey.org/viewer?ra=37.965600&dec=-59.584100')


def test_merged_row_lists_every_catalogue():
    d = lc.describe(dict(EUCLID, reference='SuGOHI5 HOLISMOKES8 Euclid-DR1-26Nov12', ra=214.25, dec=42.97))
    names = [c['name'] for c in d['catalogues']]
    assert names == ['SuGOHI V', 'HOLISMOKES VIII', 'Euclid DR1 strong lenses (ECLIPSE)']
    q = parse_qs(urlparse(d['catalogues'][0]['url']).query)
    assert d['catalogues'][0]['url'].startswith('/detect/lens/sugohi?') and q == {'ra': ['214.250000'], 'dec': ['42.970000']}


def test_probability_and_numeric_grade():
    assert lc.measure({'lens_probability': 0.934}) == 'P(lens) 0.93'
    assert lc.measure({'lens_grade': '2.5', 'lens_probability': 0.99}) == 'Grade 2.5 / 3 · P(lens) 0.99'
    assert lc.measure({'grade': 'B'}) == 'Grade B'          # LSST match rows call it grade
    assert lc.measure({}) is None


def test_holismokes2_opens_vizier_around_the_lens():
    (c,) = lc.describe({'ra': 109.1437, 'dec': 38.3523, 'reference': 'HOLISMOKES2'})['catalogues']
    q = parse_qs(urlparse(c['url']).query)
    assert c['url'].startswith(lc.VIZIER) and q['-source'] == ['J/A+A/644/A163'] and q['-c.rs'] == ['3']


def test_unknown_reference_still_named_with_an_image():
    d = lc.describe({'ra': 10.0, 'dec': 1.0, 'reference': 'Karp+2023', 'lens_probability': 0.5})
    assert d['catalogues'] == [{'ref': 'Karp+2023', 'name': 'Karp+2023', 'site': None, 'url': None, 'id': None,
                                'scale': None}]
    assert d['photo_url'] and d['measure'] == 'P(lens) 0.50'


def test_sugohi_handoff_posts_the_search(client_factory):
    r = client_factory('anon').get('/detect/lens/sugohi?ra=32.46922&dec=-5.82954')
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and 'action="https://www-utap.phys.s.u-tokyo.ac.jp/~oguri/sugohi/cand.php"' in body
    assert 'name="ra0" value="32.469220"' in body and 'name="position" value="radial"' in body
    assert "form-action https://www-utap.phys.s.u-tokyo.ac.jp" in r.headers['Content-Security-Policy']


def test_sugohi_handoff_needs_a_position(client_factory):
    c = client_factory('anon')
    assert c.get('/detect/lens/sugohi?ra=x&dec=1').status_code == 400
    assert c.get('/detect/lens/sugohi?ra=400&dec=1').status_code == 400
