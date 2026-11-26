"""Daily Trigger auto exposure from CASTOR (app/services/planning/auto_exposure.py)."""
from datetime import date, datetime, timezone

import pytest

from app.paths import CASTOR_SRC
from app.services.planning import auto_exposure as ae

NOW = 61366.5                  # 2026-11-26 12:00 UTC
DET = [{'mag': 16.98, 'mjd': 61365.75, 'filter': 'z', 'source': 'SLT(AUTO)'},
       {'mag': 16.73, 'mjd': 61365.75, 'filter': 'r', 'source': 'SLT(AUTO)'},
       {'mag': 16.79, 'mjd': 61365.74, 'filter': 'g', 'source': 'ATLAS'},
       {'mag': 16.70, 'mjd': 61360.0, 'filter': 'u', 'source': 'SLT(AUTO)'},       # u, 6.5 days old
       {'mag': 16.50, 'mjd': 61355.0, 'filter': 'i', 'source': 'ZTF'}]


def test_recent_photometry_first_own_filter_else_the_brightest_of_three_days():
    m = ae.magnitudes('AT2026afqt', None, DET, NOW)
    assert m['rp']['mag'] == 16.73 and m['rp']['from'] == 'own'
    assert m['gp']['mag'] == 16.79 and m['gp']['from'] == 'own'
    assert m['zp']['mag'] == 16.98 and m['zp']['from'] == 'own'
    # u and i have only older points: the brightest detection of the last 3 days (r 16.73)
    assert m['up']['mag'] == 16.73 and m['up']['from'] == 'bright' and m['up']['filter'] == 'r'
    assert m['ip']['mag'] == 16.73 and m['ip']['from'] == 'bright'


def test_nothing_in_three_days_goes_back_in_time():
    m = ae.magnitudes('AT2026afqt', None, DET, NOW + 10)
    assert m['up']['mag'] == 16.70 and m['up']['from'] == 'own_old'
    assert m['ip']['mag'] == 16.50 and m['ip']['from'] == 'own_old'
    assert m['rp']['mag'] == 16.73 and m['rp']['from'] == 'own_old'
    only_r = [d for d in DET if d['filter'] == 'r']
    m = ae.magnitudes('AT2026afqt', None, only_r, NOW + 10)
    assert m['gp']['mag'] == 16.73 and m['gp']['from'] == 'other'


def test_no_photometry_needs_a_typed_magnitude():
    m = ae.magnitudes('SN 2026x', '>18.5', [])
    assert all(v['mag'] == 18.5 and v['from'] == 'typed' for v in m.values())
    with pytest.raises(ae.NoMagnitude):
        ae.magnitudes('SN 2026x', '', [])


def _fake(monkeypatch, per_filter):
    monkeypatch.setattr(ae, 'best_time', lambda ra, dec, day=None: (datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc), 64.6))
    monkeypatch.setattr(ae, 'plan_filter', lambda cf, ra, dec, mag, snr, when, **kw: per_filter[cf])


def _p(elapsed, exp=300, count=1):
    return {'status': 'ok', 'exp': exp, 'count': count, 'elapsed': elapsed, 'snr': 20.0}


def test_the_filters_picked_are_planned_however_long(monkeypatch):
    _fake(monkeypatch, {'Sloan_u': _p(2400), 'Sloan_g': _p(500), 'Sloan_r': _p(400), 'Sloan_i': _p(600), 'Sloan_z': _p(900)})
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET, now_mjd=NOW)                     # default: all five
    assert res['selected'] == list(ae.ALL) and res['total_s'] == 4800 and res['too_long'] and len(res['plan']) == 5
    assert res['options']['gr']['total_s'] == 900 and res['options']['r']['total_s'] == 400
    res = ae.compute('AT2026afqt', 47.9, -2.0, choice='zp,gp', detections=DET, now_mjd=NOW)
    assert [f['filter'] for f in res['plan']] == ['gp', 'zp'] and res['total_s'] == 1400 and not res['too_long']


def test_selection_reads_lists_and_the_old_plan_names():
    assert ae.selection('rp, up') == ['up', 'rp']
    assert ae.selection(['ip']) == ['ip']
    assert ae.selection('gr') == ['gp', 'rp'] and ae.selection('auto') == list(ae.ALL)
    assert ae.selection('') == list(ae.ALL) and ae.selection('xx') == list(ae.ALL)


def test_a_filter_castor_cannot_plan_is_left_out_with_why(monkeypatch):
    none = {'status': 'saturated', 'exp': None, 'count': None, 'elapsed': None, 'snr': None}
    _fake(monkeypatch, {'Sloan_u': _p(120), 'Sloan_g': none, 'Sloan_r': _p(65), 'Sloan_i': _p(65), 'Sloan_z': _p(65)})
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET, now_mjd=NOW)
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


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_a_faint_target_gets_more_frames_not_longer_ones():
    when = datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc)
    for cf in ('Sloan_u', 'Sloan_g', 'Sloan_r', 'Sloan_z'):
        p = ae.plan_filter(cf, 47.9087, -2.0267, 19.5, 20, when, camera='SLT_DZ936')   # no flatness floor
        assert p['exp'] == ae.MAX_EXP_S and p['count'] >= 2 and p['snr'] >= 20, (cf, p)


def test_target_form_without_magnitude_cannot_use_auto(monkeypatch):
    from app.blueprints.private_area import targets
    monkeypatch.setattr(ae, 'latest_detections', lambda name: [])
    auto, snr, choice, res, err, cam = targets._auto_exposure(
        {'name': 'SN 2026x', 'ra': '10:00:00', 'dec': '+20:00:00', 'mag': '', 'auto_exposure': True, 'auto_snr': 15,
         'auto_plan': 'rp,gp'}, 'SLT')
    assert auto and snr == 15 and choice == 'gp,rp' and res is None and 'enter its magnitude' in err and cam is None
    assert targets._auto_exposure({'auto_exposure': True, 'auto_snr': 1}, 'SLT')[4].startswith('Target S/N')
    lot = targets._auto_exposure({'auto_exposure': True, 'name': 'SN 2026x', 'ra': '10:00:00', 'dec': '+20:00:00'}, 'LOT')
    assert lot[0] is True and lot[5] is None and 'enter its magnitude' in lot[4]          # LOT auto now too
    assert targets._auto_exposure({'auto_exposure': False, 'auto_camera': 'SLT_DZ936'}, 'SLT')[5] == 'SLT_DZ936'


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_the_shortest_frame_rule_never_saturates_a_bright_target():
    when = datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc)
    for mag in (9.0, 11.0, 12.5):
        p = ae.plan_filter('Sloan_r', 47.9087, -2.0267, mag, 20, when)
        assert p['exp'] is None or p['exp'] < p['sat_s'] * ae.SAT_MARGIN or p['exp'] <= 1, (mag, p)


def test_the_newest_detection_becomes_the_newest_mag(monkeypatch):
    _fake(monkeypatch, {f: _p(65) for f in ('Sloan_u', 'Sloan_g', 'Sloan_r', 'Sloan_i', 'Sloan_z')})
    det = [{**d, 'mjd': 61366.0} if d['filter'] == 'r' else d for d in DET]      # r is the newest
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=det, now_mjd=NOW)
    assert res['latest'] == {'mag': 16.73, 'filter': 'r', 'mjd': 61366.0, 'source': 'SLT(AUTO)'}
    assert ae.latest_mag(res) == res['latest']['mag']
    typed = ae.compute('SN 2026x', 47.9, -2.0, typed_mag='18', detections=[])
    assert typed['latest'] is None and ae.latest_mag(typed) is None


def test_without_its_own_snr_a_target_gets_10_when_19_mag_or_brighter_else_20(monkeypatch):
    seen = []
    monkeypatch.setattr(ae, 'best_time', lambda ra, dec, day=None: (datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc), 64.6))
    monkeypatch.setattr(ae, 'plan_filter', lambda cf, ra, dec, mag, snr, when, **kw: seen.append(snr) or _p(65))
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET, now_mjd=NOW)          # brightest 16.73
    assert res['snr'] == 10 and res['snr_auto'] and res['brightest'] == 16.73 and set(seen) == {10}
    faint = [{**d, 'mag': d['mag'] + 3} for d in DET]                                   # brightest 19.73
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=faint, now_mjd=NOW)
    assert res['snr'] == 20 and res['snr_auto']
    edge = [{**d, 'mag': 19.0} for d in DET]
    assert ae.compute('X', 47.9, -2.0, detections=edge, now_mjd=NOW)['snr'] == 10      # 19.0 itself: S/N 10
    res = ae.compute('AT2026afqt', 47.9, -2.0, snr=30, detections=faint, now_mjd=NOW)   # the target's own S/N wins
    assert res['snr'] == 30 and not res['snr_auto']


def test_target_form_snr_blank_is_automatic(monkeypatch):
    from app.blueprints.private_area import targets
    monkeypatch.setattr(ae, 'latest_detections', lambda name: [])
    for blank in ('', None, 'auto'):
        assert targets._auto_exposure({'auto_exposure': False, 'auto_snr': blank}, 'SLT')[1] is None
    assert targets._auto_exposure({'auto_exposure': False, 'auto_snr': '15'}, 'SLT')[1] == 15


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_the_lot_plan_is_much_shorter_for_a_faint_target():
    det = [{'mag': 20.37, 'mjd': 61360.0, 'filter': 'r', 'source': 'SLT(AUTO)'}]
    kw = dict(detections=det, now_mjd=NOW, day=date(2026, 11, 26))
    slt = ae.compute('AT2026ajog', 41.0, 20.0, camera='SLT_DZ936', **kw)
    lot = ae.compute('AT2026ajog', 41.0, 20.0, telescope='LOT', **kw)
    assert lot['telescope'] == 'LOT' and slt['telescope'] == 'SLT'
    assert lot['options']['all']['total_s'] * 4 < slt['options']['all']['total_s']
    assert ae.selection('gri') == ['gp', 'rp', 'ip'] and lot['options']['gri']['filters'] == ['gp', 'rp', 'ip']


def test_cameras_default_to_andor934_on_slt_and_sophia_on_lot():
    assert ae.camera_for('SLT') == 'SLT_DU934P' and ae.camera_for('SLT', 'SLT_DZ936') == 'SLT_DZ936'
    assert ae.camera_for('SLT', 'Sophia') == 'SLT_DU934P' and ae.camera_for('LOT', 'SLT_DZ936') == 'Sophia'
    assert ae.camera_name('Andor-DZ936') == 'Andor936' and ae.camera_name('Andor-DU934P') == 'Andor934'
    m = ae.FRAME_CAMERA_RE.search('Calibrated_AT2026afqt_D2026-11-25T113657_T113657_gp_Astrodon_2018_SLT_Andor-DZ936_bin1_gain0_95')
    assert m and ae.camera_name(m.group(2)) == 'Andor936'


def test_without_its_own_camera_a_target_uses_the_one_last_used(monkeypatch):
    ae._last_cache.clear()
    monkeypatch.setattr(ae, 'last_frames', lambda tel, name=None: {'night': '2026-11-25', 'camera': 'Andor936'})
    assert ae.last_camera('SLT')[0] == 'SLT_DZ936'
    monkeypatch.setattr(ae, 'best_time', lambda ra, dec, day=None: (datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc), 64.6))
    seen = []
    monkeypatch.setattr(ae, 'plan_filter', lambda cf, ra, dec, mag, snr, when, **kw: seen.append(kw['camera']) or _p(65))
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET, now_mjd=NOW)
    assert res['camera'] == 'SLT_DZ936' and res['camera_auto'] and set(seen) == {'SLT_DZ936'}
    res = ae.compute('AT2026afqt', 47.9, -2.0, detections=DET, now_mjd=NOW, camera='SLT_DU934P')   # picked: kept
    assert res['camera'] == 'SLT_DU934P' and not res['camera_auto']
    ae._last_cache.clear()
    monkeypatch.setattr(ae, 'last_frames', lambda tel, name=None: None)
    assert ae.last_camera('SLT')[0] == 'SLT_DU934P'                                            # unknown: Andor934
    ae._last_cache.clear()


@pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")
def test_the_flatness_term_is_left_out_so_andor934_plans_faint_targets():
    when = datetime(2026, 11, 26, 14, 48, tzinfo=timezone.utc)
    _, cat = ae._castor()
    assert all(c.camera.background_flatness_fraction == 0 for p in cat.profiles.values() for c in p.cameras.values()
               if c.camera is not None)
    p = ae.plan_filter('Sloan_r', 47.9087, -2.0267, 19.5, 20, when, camera='SLT_DU934P')
    assert p['status'] == 'ok' and p['exp'] == 300 and p['snr'] >= 20       # with the 2% it stopped at S/N ~6.5
