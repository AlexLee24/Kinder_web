"""Einstein Probe alerts are judged like alert-run: observable now / later tonight → control room with the script
alert-run carries; too low → ToO channel (hand script only above 20°), still pushed, marked for information."""
import json
from datetime import datetime, timezone

import pytest

from app.services.bots import gcn, robot

NIGHT = datetime(2026, 11, 15, 17, 23, tzinfo=timezone.utc)     # 01:23 at Lulin
DAY = datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc)         # 12:00
AFTER_DAWN = datetime(2026, 11, 15, 22, 30, tzinfo=timezone.utc)  # 06:30
RA = '3:54:34.56'


def _plan(dec, now, ra=RA):
    p = robot.plan_night(ra, dec, gcn.slt_script('EPt261115a', ra, dec), now)
    if p['kind'] == 'now':
        p['alt_now'] = robot.run_window(ra, dec, now)['alt_now']
    return p


def test_now_matches_alert_run(monkeypatch):
    dec = '+20:00:00'
    script = gcn.slt_script('EPt261115a', RA, dec)
    p = _plan(dec, NIGHT)
    assert p['kind'] == 'now'
    a = {'id': 1, 'uid': 'u', 'source': 'einstein_probe', 'name': 'EPt261115a', 'telescope': 'SLT', 'ra': RA,
         'dec': dec, 'trigger_time': '', 'created_at': '', 'expires_at': '2099-01-01T00:00:00+00:00',
         'status': 'active', 'observable': True, 'max_alt': 70.0, 'moon_sep': 90.0, 'script': script}
    monkeypatch.setattr('app.db.robot.newest_active', lambda: a)
    run = robot.run_feed(NIGHT)['alert']
    assert run and run['count'] == p['count'] and run['script'] == p['script']
    text = gcn.ep_message('EPt261115a', RA, dec, p)
    assert '*now*' in text and f"#COUNT {p['count']}" in text and '/api/v1/robot/alert-run' in text
    assert '鹿林*現在*就能拍' in text and 'We can trigger' not in text


def test_later_in_daytime():
    p = _plan('+20:00:00', DAY)
    assert p['kind'] == 'later' and p['start'] > DAY and p['count'] >= 1
    text = gcn.ep_message('EPt261115a', RA, '+20:00:00', p)
    assert 'we can trigger it tonight' in text and 'will carry this script' in text and '起機器人的 alert-run API' in text


def test_after_dawn_looks_at_the_coming_night():
    p = _plan('+20:00:00', AFTER_DAWN)
    assert p['kind'] == 'later' and (p['start'] - AFTER_DAWN).total_seconds() < 15 * 3600


def test_low_between_20_and_30_has_hand_script():
    p = _plan('-44:18:39.60', DAY)                       # this alert: peaks ~22° at Lulin
    assert p['kind'] == 'low' and 20 <= p['max_alt'] < 30 and p['never_high'] and p['script']
    text = gcn.ep_message('EPt261115a', RA, '-44:18:39.60', p)
    assert 'too low at Lulin' in text and '不拍' in text and 'never gets above 30°' in text
    assert '```' in text and 'We can trigger' not in text


def test_low_below_20_has_no_script():
    p = _plan('-55:00:00', NIGHT)
    assert p['kind'] == 'low' and p['max_alt'] < 20 and p['script'] is None
    text = gcn.ep_message('EPt261115a', RA, '-55:00:00', p)
    assert '```' not in text and 'too low to observe' in text


def test_daytime_only_target():
    p = _plan('+10:00:00', NIGHT, ra='15:00:00')
    assert p['kind'] == 'low' and not p['never_high']
    assert 'only in daytime' in gcn.ep_message('EPt261115a', '15:00:00', '+10:00:00', p)


@pytest.mark.parametrize('dec, channel, title', [('+20:00:00', 'CTRL', 'Einstein Probe alert EPt'),
                                                 ('-44:18:39.60', 'TOO', 'too low at Lulin')])
def test_routing_and_push(monkeypatch, tmp_path, dec, channel, title):
    monkeypatch.setenv('SLACK_CHANNEL_ID_CONTROL_ROOM', 'CTRL')
    monkeypatch.setenv('SLACK_CHANNEL_ID_ToO', 'TOO')
    monkeypatch.delenv('SLACK_CHANNEL_ID_EP_COPY', raising=False)
    for attr in ('EP_JSON', 'TARGETS_FILE', 'PLOT_PATH'):
        monkeypatch.setattr(gcn, attr, tmp_path / attr)
    posts, pushes = [], []
    monkeypatch.setattr(gcn, '_send_slack', lambda c, ch, text, plot=None: posts.append((ch, text)))
    monkeypatch.setattr(gcn, '_send_email', lambda *a: None)
    monkeypatch.setattr(gcn, '_ep_plot', lambda *a, **k: None)
    monkeypatch.setattr(robot, 'publish', lambda *a, **k: 1)
    monkeypatch.setattr('app.services.notifications.webpush.member_ids', lambda: [1])
    monkeypatch.setattr('app.services.notifications.webpush.send_to_users',
                        lambda ids, t, b, url, category=None: pushes.append((t, b)) or 1)

    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NIGHT

    monkeypatch.setattr(gcn, 'datetime', FixedDT)

    class Sent:
        seen = set()

        def add(self, uid):
            pass

    raw = json.dumps({'trigger_time': '2026-11-15T17:20:00Z', 'ra': 58.644, 'dec': -44.311 if dec[0] == '-' else 20.0})
    gcn.handle_ep(raw, None, Sent())
    assert [ch for ch, _ in posts] == [channel]
    assert pushes and title in pushes[0][0]
