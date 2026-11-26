"""Daily Trigger auto exposure from CASTOR (app/services/planning/auto_exposure.py)."""
from datetime import date, datetime, timezone

import pytest

from app.paths import CASTOR_SRC
from app.services.planning import auto_exposure as ae

DET = {'*': {'mag': 16.98, 'mjd': 61365.75, 'filter': 'z', 'source': 'SLT(AUTO)'},
       'r': {'mag': 16.73, 'mjd': 61365.75, 'filter': 'r', 'source': 'SLT(AUTO)'},
       'g': {'mag': 16.79, 'mjd': 61365.74, 'filter': 'g', 'source': 'ATLAS'}}


def test_each_filter_takes_its_own_latest_magnitude_else_the_latest_in_any():
    m = ae.magnitudes('AT2026afqt', None, DET)
    assert m['rp']['mag'] == 16.73 and m['rp']['from'] == 'own'
    assert m['gp']['mag'] == 16.79 and m['gp']['from'] == 'own'
    assert m['up']['mag'] == 16.98 and m['up']['from'] == 'other'


def test_no_photometry_needs_a_typed_magnitude():
    m = ae.magnitudes('SN 2026x', '>18.5', {})
    assert all(v['mag'] == 18.5 and v['from'] == 'typed' for v in m.values())
    with pytest.raises(ae.NoMagnitude):
        ae.magnitudes('SN 2026x', '', {})


def _fake(monkeypatch, per_filter):
    monkeypatch.setattr(ae, 'best_time', lambda ra, dec, day=None: (datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc), 64.6))
    monkeypatch.setattr(ae, 'plan_filter', lambda cf, ra, dec, mag, snr, when: per_filter[cf])


def _p(elapsed, exp=300, count=1):
    return {'status': 'ok', 'exp': exp, 'count': count, 'elapsed': elapsed, 'snr': 20.0}


def test_the_filters_picked_are_planned_however_long(monkeypatch):
    _fake(monkeypatch, {'Sloan_u': _p(2400), 'Sloan_g': _p(500), 'Sloan_r': _p(400), 'Sloan_i': _p(600), 'Sloan_z': _p(900)})
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET)                     # default: all five
    assert res['selected'] == list(ae.ALL) and res['total_s'] == 4800 and res['too_long'] and len(res['plan']) == 5
    assert res['options']['gr']['total_s'] == 900 and res['options']['r']['total_s'] == 400
    res = ae.compute('AT2026afqt', 47.9, -2.0, choice='zp,gp', detections=DET)
    assert [f['filter'] for f in res['plan']] == ['gp', 'zp'] and res['total_s'] == 1400 and not res['too_long']


def test_selection_reads_lists_and_the_old_plan_names():
    assert ae.selection('rp, up') == ['up', 'rp']
    assert ae.selection(['ip']) == ['ip']
    assert ae.selection('gr') == ['gp', 'rp'] and ae.selection('auto') == list(ae.ALL)
    assert ae.selection('') == list(ae.ALL) and ae.selection('xx') == list(ae.ALL)


def test_a_filter_castor_cannot_plan_is_left_out_with_why(monkeypatch):
    none = {'status': 'saturated', 'exp': None, 'count': None, 'elapsed': None, 'snr': None}
    _fake(monkeypatch, {'Sloan_u': _p(120), 'Sloan_g': none, 'Sloan_r': _p(65), 'Sloan_i': _p(65), 'Sloan_z': _p(65)})
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET)
    assert 'gp' not in [f['filter'] for f in res['plan']] and any('g: saturates' in n for n in res['notes'])


def test_latest_mag_is_the_newest_detection():
    res = {'filters': {'rp': {'mag': 16.73, 'from': 'own', 'mjd': 61365.75}, 'gp': {'mag': 16.79, 'from': 'own', 'mjd': 61365.74},
                       'up': {'mag': 18, 'from': 'typed'}}}
    assert ae.latest_mag(res) == 16.73


def test_best_time_is_inside_the_night():
    when, alt = ae.best_time(47.9087, -2.0267, date(2026, 11, 26))
    local_h = (when.hour + 8) % 24
    assert (local_h >= 18 or local_h <= 6) and 55 < alt < 70


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_castor_plan_never_goes_below_the_shortest_frame():
    when = datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc)
    p = ae.plan_filter('Sloan_r', 47.9087, -2.0267, 16.7, 20, when)        # CASTOR alone: one 15 s frame
    assert p['status'] == 'ok' and p['exp'] >= ae.MIN_EXP_S['rp'] and p['snr'] >= 20
    z = ae.plan_filter('Sloan_z', 47.9087, -2.0267, 16.24, 20, when)     # AT2026afqt z: 60 s was too shallow for TS
    assert z['exp'] >= 300


def test_target_form_without_magnitude_cannot_use_auto(monkeypatch):
    from app.blueprints.private_area import targets
    monkeypatch.setattr(ae, 'latest_detections', lambda name: {})
    auto, snr, choice, res, err = targets._auto_exposure(
        {'name': 'SN 2026x', 'ra': '10:00:00', 'dec': '+20:00:00', 'mag': '', 'auto_exposure': True, 'auto_snr': 15,
         'auto_plan': 'rp,gp'}, 'SLT')
    assert auto and snr == 15 and choice == 'gp,rp' and res is None and 'enter its magnitude' in err
    assert targets._auto_exposure({'auto_exposure': True, 'auto_snr': 1}, 'SLT')[4].startswith('Target S/N')
    assert targets._auto_exposure({'auto_exposure': True}, 'LOT')[0] is False


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_the_shortest_frame_rule_never_saturates_a_bright_target():
    when = datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc)
    for mag in (9.0, 11.0, 12.5):
        p = ae.plan_filter('Sloan_r', 47.9087, -2.0267, mag, 20, when)
        assert p['exp'] is None or p['exp'] < p['sat_s'] * ae.SAT_MARGIN or p['exp'] <= 1, (mag, p)


def test_the_newest_detection_becomes_the_newest_mag(monkeypatch):
    _fake(monkeypatch, {f: _p(65) for f in ('Sloan_u', 'Sloan_g', 'Sloan_r', 'Sloan_i', 'Sloan_z')})
    det = {**DET, 'r': {**DET['r'], 'mjd': 61366.0}}               # r is the newest
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=det)
    assert res['latest'] == {'mag': 16.73, 'filter': 'r', 'mjd': 61366.0, 'source': 'SLT(AUTO)'}
    assert ae.latest_mag(res) == res['latest']['mag']
    typed = ae.compute('SN 2026x', 47.9, -2.0, typed_mag='18', detections={})
    assert typed['latest'] is None and ae.latest_mag(typed) is None
