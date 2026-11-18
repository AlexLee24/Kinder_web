"""Kinder patch in the vendored AutoPhOT: catalog._select_sdss_vizier_table keeps to SDSS's photometric releases."""
import importlib.util
import os
import sys

import pytest

pd = pytest.importorskip('pandas')
Table = pytest.importorskip('astropy.table').Table
AP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'vendor', 'autophot')


@pytest.fixture(scope='module')
def select():
    src = open(os.path.join(AP, 'catalog.py')).read()
    start = src.index('_SDSS_RELEASE_RANK = {')
    end = src.index('# =====', src.index('def _select_sdss_vizier_table'))
    ns = {'pd': pd, 'np': __import__('numpy'), 'logger': __import__('logging').getLogger('t'),
          '_catalog_radec': lambda df: (None, None), '_field_coverage_fraction': lambda *a: float('nan')}
    exec(src[start:end], ns)
    return ns['_select_sdss_vizier_table']


def table(name, **cols):
    t = Table(cols)
    t.meta['name'] = name
    return t


def test_quasar_catalogues_do_not_win(select):
    stars = table('V/154/sdss16', RA_ICRS=[1.0, 2.0], DE_ICRS=[1.0, 2.0], mode=[1, 1], **{'class': [6, 6]}, clean=[1, 1],
                  umag=[18.0, 19.0])
    qso = table('VII/289/superset', RAJ2000=[1.0, 2.0, 3.0], DEJ2000=[1.0, 2.0, 3.0])
    got = select([qso, stars])
    assert list(got['umag']) == [18.0, 19.0]


def test_nothing_photometric_falls_back_to_what_came(select):
    qso = table('VII/289/dr16q', RAJ2000=[1.0], DEJ2000=[1.0])
    assert len(select([qso])) == 1
