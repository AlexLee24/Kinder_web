"""Spectrum upload checks (app/services/spectrum_upload.py, the object page's Upload) and the
public object query's argument parsing (app/blueprints/astronomy_tools/query_api.py).
No database: only the pure helpers and the requests refused before any query runs."""
from datetime import datetime, timezone

import pytest

from app.blueprints.astronomy_tools import query_api as qa
from app.services.spectrum_upload import check_observation_mjd, check_spectrum_points

WL = [4000.0 + 2 * i for i in range(50)]
FL = [1e-16 * (1 + i % 5) for i in range(50)]


def test_good_spectrum_passes():
    points, errors, warnings = check_spectrum_points(WL, FL)
    assert errors == [] and warnings == [] and len(points) == 50


@pytest.mark.parametrize('wl, fl, needle', [
    (WL, FL[:10], 'every point needs both'),
    (WL[:5], FL[:5], 'at least 10'),
    ([w / 10 for w in WL], FL, 'nanometres'),
    ([w / 1e4 for w in WL], FL, 'micrometres'),
    ([w * 100 for w in WL], FL, 'outside'),
    ([-w for w in WL], FL, 'positive'),
    (WL, [1.0] * 50, 'same value'),
    (WL, FL[:-1] + ['x'], 'not finite'),
    (WL, FL[:-1] + [float('nan')], 'not finite'),
    (WL, FL[:-1] + [True], 'not finite'),
    ('4000 4002', FL, 'lists'),
])
def test_bad_spectra_are_refused(wl, fl, needle):
    _, errors, _ = check_spectrum_points(wl, fl)
    assert any(needle in e for e in errors), errors


def test_unsorted_and_repeated_wavelengths_are_warnings():
    points, errors, warnings = check_spectrum_points(WL[::-1] + [WL[0]], FL + [FL[0]])
    assert errors == []
    assert [p[0] for p in points] == sorted(p[0] for p in points)
    assert any('sorted' in w for w in warnings) and any('repeated' in w for w in warnings)


def test_observation_epoch_must_be_believable():
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert check_observation_mjd(61345.0, now) is None                  # 2026-11-01
    assert 'future' in check_observation_mjd(61400.0, now)
    assert 'before 1950' in check_observation_mjd(30000.0, now)


def test_type_filter_is_case_insensitive_with_prefix_and_special_values():
    params = []
    sql = qa._type_clause('slsn-i, SLSN*, AT', ['SLSN-I', 'SN Ia'], params)
    assert sql.count(' OR ') == 2 and "o.name_prefix = 'AT'" in sql
    assert params == ['slsn-i', 'slsn%']


def test_unknown_type_suggests_the_closest():
    with pytest.raises(qa.QueryError, match='Did you mean SLSN-I'):
        qa._type_clause('SLSN-l', ['SLSN-I', 'SN Ia'], [])


def test_like_wildcards_in_a_prefix_are_escaped():
    params = []
    qa._type_clause('SN_I%*', [], params)
    assert params == ['sn\\_i\\%%']


def test_coordinates_take_degrees_or_sexagesimal():
    assert qa._coord('150.1', True) == 150.1
    assert qa._coord('10:00:00', True) == pytest.approx(150.0)
    assert qa._coord('-00:30:00', False) == pytest.approx(-0.5)
    with pytest.raises(qa.QueryError):
        qa._coord('north', False)
    assert qa._hms(150.0) == '10:00:00.00' and qa._dms(-0.5) == '-00:30:00.0'


@pytest.mark.parametrize('query, needle', [
    ('typ=SN', "Did you mean 'type'"),
    ('discovered_after=2025-13-01', 'YYYY-MM-DD'),
    ('limit=0', 'limit'),
    ('format=xml', 'csv or json'),
    ('radius=5', 'needs ra and dec'),
    ('ra=10', 'both ra and dec'),
    ('sort=distance', 'cone search'),
    ('z_min=abc', 'number'),
])
def test_bad_query_arguments_are_400(app, query, needle):
    r = app.test_client().get(f'/api/query/objects?{query}')
    assert r.status_code == 400
    assert needle in r.get_json()['error']
    assert r.headers['Access-Control-Allow-Origin'] == '*'
