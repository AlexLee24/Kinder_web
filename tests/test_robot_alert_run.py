"""GET /api/v1/robot/alert-run: the newest alert only while it can be taken now at Lulin, its #COUNT cut to fit."""
import math
from datetime import datetime, timedelta, timezone

import ephem
import pytest

from app.services.bots import robot

MIDNIGHT = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)       # 00:00 at Lulin (UTC+8)
NOON = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
SCRIPT = robot_script = (';===SLT URGENT Priority!!===\n\n#BINNING 1\n#FILTER rp_Astrodon_2018\n#INTERVAL 300\n'
                         '#COUNT 24\n;# mag: >22 mag\nEPt261111a\t{ra}\t{dec}\n#WAITFOR 1\n')


def _ra_at(hour_angle_h, when=MIDNIGHT):
    """RA (hh:mm:ss) that is hour_angle_h hours from the meridian at Lulin at ``when`` (negative = still rising)."""
    o = ephem.Observer()
    o.lon, o.lat = robot.LULIN[1], robot.LULIN[2]
    o.date = ephem.Date(when.replace(tzinfo=None))
    return str(ephem.hours(o.sidereal_time() - math.radians(hour_angle_h * 15)))


def _alert(ra, dec='23:30:00', **kw):
    return dict({'id': 7, 'uid': 'ep_x', 'source': 'einstein_probe', 'name': 'EPt261111a', 'telescope': 'SLT',
                 'ra': ra, 'dec': dec, 'trigger_time': '2026-11-11T15:00:00Z', 'created_at': '2026-11-11T15:01:00+00:00',
                 'expires_at': '2026-11-12T15:01:00+00:00', 'status': 'active', 'observable': True, 'max_alt': 80.0,
                 'moon_sep': 90.0, 'script': SCRIPT.format(ra=ra, dec=dec)}, **kw)


@pytest.fixture
def newest(monkeypatch):
    box = {}
    monkeypatch.setattr('app.db.robot.newest_active', lambda: box.get('a'))
    return box


def test_fit_script_cuts_count():
    s, n = robot.fit_script(SCRIPT, 330 * 5 + 10)
    assert n == 5 and '#COUNT 5\n' in s and '#COUNT 24' not in s and '#INTERVAL 300' in s


def test_fit_script_never_raises_count():
    s, n = robot.fit_script(SCRIPT, 10 * 3600)
    assert n == 24 and s == SCRIPT


def test_fit_script_no_room_for_one_frame():
    assert robot.fit_script(SCRIPT, 329) == (None, 0)


def test_daytime_is_null(newest):
    newest['a'] = _alert(_ra_at(0, NOON))
    body = robot.run_feed(NOON)
    assert body['alert'] is None and 'night' in body['reason']


def test_below_30_deg_is_null(newest):
    newest['a'] = _alert(_ra_at(-6))            # on the eastern horizon at midnight
    body = robot.run_feed(MIDNIGHT)
    assert body['alert'] is None and 'below 30' in body['reason']


def test_on_the_meridian_runs_until_it_sinks_to_20_deg(newest):
    newest['a'] = _alert(_ra_at(0))
    body = robot.run_feed(MIDNIGHT)
    a = body['alert']
    assert a and a['id'] == 7 and a['alt_now_deg'] > 80 and a['run_until_reason'] == 'alt'
    until = datetime.fromisoformat(a['run_until'])
    # Dec +23.5 at Lulin: cos H = (sin 20° - sin φ sin δ) / (cos φ cos δ) gives H ≈ 77.4°, about 5.16 h
    assert timedelta(hours=5.0) < until - MIDNIGHT < timedelta(hours=5.3)
    assert a['count'] == min(24, int((until - MIDNIGHT).total_seconds() // 330))
    assert f"#COUNT {a['count']}\n" in a['script']
    import hashlib
    assert a['script_sha256'] == hashlib.sha256(a['script'].encode()).hexdigest()


def test_late_target_stops_30_min_after_dawn(newest):
    late = MIDNIGHT + timedelta(hours=4, minutes=40)            # 04:40 at Lulin, shortly before astronomical dawn
    newest['a'] = _alert(_ra_at(-1, late))                      # still rising, high up
    body = robot.run_feed(late)
    a = body['alert']
    assert a and a['run_until_reason'] == 'dawn'
    o = ephem.Observer()
    o.lon, o.lat, o.elevation, o.pressure, o.horizon = robot.LULIN[1], robot.LULIN[2], robot.LULIN[3], 0, '-18'
    o.date = ephem.Date(late.replace(tzinfo=None))
    dawn = o.next_rising(ephem.Sun(), use_center=True).datetime().replace(tzinfo=timezone.utc)
    assert datetime.fromisoformat(a['run_until']) == (dawn + timedelta(minutes=30)).replace(microsecond=0) or \
        abs(datetime.fromisoformat(a['run_until']) - dawn - timedelta(minutes=30)) < timedelta(seconds=1)
    assert a['count'] == min(24, int((dawn + timedelta(minutes=30) - late).total_seconds() // 330))


def test_newest_only_no_alert(newest):
    assert robot.run_feed(MIDNIGHT) == {'api': 'kinder-robot-alert-run', 'version': 1,
                                        'now': MIDNIGHT.isoformat(timespec='seconds'), 'alert': None,
                                        'reason': 'no active alert'}


def test_route(client_factory, newest, monkeypatch):
    monkeypatch.setattr(robot, 'note_client', lambda *a: None)
    monkeypatch.setattr(robot, 'run_feed', lambda: {'api': 'kinder-robot-alert-run', 'alert': None, 'reason': 'x'})
    r = client_factory('anon').get('/api/v1/robot/alert-run')
    assert r.status_code == 200 and r.get_json()['reason'] == 'x' and r.headers['Cache-Control'] == 'no-store'
