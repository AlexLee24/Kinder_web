"""Only tonight's Trigger duty (or an admin) sends the whole Daily / Direct Trigger; single targets stay open to members."""
from unittest import mock

import pytest

from conftest import PERSONAS

MEMBER = PERSONAS['member']['email']
SLT = {'telescope': 'SLT', 'greeting': 'Hi', 'script': '#waitfor 1\n', 'targets': [{'name': 'SN 2026a'}]}


@pytest.fixture(autouse=True)
def user_rows(monkeypatch):
    """The personas' DB rows, so the session check passes without a database."""
    rows = {p['email']: dict(p, session_version=0, must_change_password=False, has_password=False)
            for p in PERSONAS.values() if p}
    monkeypatch.setattr('app.core.auth._get_user_cached', rows.get)


@pytest.fixture
def sent(monkeypatch):
    """Everything after the duty check is stubbed: Slack, the plot, the Observation Log, the LOT schedule."""
    from app.blueprints.private_area import daily_trigger
    out = []
    monkeypatch.setattr('app.services.planning.trigger_send.send_to_slack', lambda *a, **k: out.append(a))
    monkeypatch.setattr('app.services.planning.trigger_send.mark_sent', lambda *a, **k: {})
    monkeypatch.setattr('app.services.planning.trigger_send.get_send_status', lambda: {})
    monkeypatch.setattr(daily_trigger, '_render_trigger_visibility_image', lambda *a: None)
    monkeypatch.setattr(daily_trigger, '_log_triggered_targets', lambda *a: [])
    monkeypatch.setattr('app.services.lab_calendar.lot_closed_tonight', lambda: [])
    return out


def _on_duty(*emails):
    people = [{'email': e, 'name': e.split('@')[0], 'event_id': 1, 'title': 'Trigger duty'} for e in emails]
    return mock.patch('app.blueprints.private_area.daily_trigger.tonight_duty', return_value=people)


def test_member_not_on_duty_cannot_send_the_whole_trigger(client_factory, sent):
    with _on_duty('someone@kinder.test'):
        r = client_factory('member').post('/daily_trigger/send_message', json=SLT)
    assert r.status_code == 403 and r.get_json()['duty_lock'] == ['someone']
    assert sent == []


def test_member_not_on_duty_can_send_a_single_target(client_factory, sent):
    with _on_duty('someone@kinder.test'):
        r = client_factory('member').post('/daily_trigger/send_message', json=dict(SLT, mark_sent=False))
    assert r.get_json()['success'] is True and len(sent) == 1


def test_single_send_with_several_targets_is_still_the_whole_trigger(client_factory, sent):
    body = dict(SLT, mark_sent=False, targets=[{'name': 'a'}, {'name': 'b'}])
    with _on_duty('someone@kinder.test'):
        r = client_factory('member').post('/daily_trigger/send_message', json=body)
    assert r.status_code == 403 and sent == []


def test_the_member_on_duty_sends(client_factory, sent):
    with _on_duty(MEMBER):
        r = client_factory('member').post('/daily_trigger/send_message', json=SLT)
    assert r.get_json()['success'] is True and len(sent) == 1


def test_admins_always_send(client_factory, sent):
    with _on_duty('someone@kinder.test'):
        r = client_factory('admin').post('/daily_trigger/send_message', json=SLT)
    assert r.get_json()['success'] is True


def test_nobody_on_duty_leaves_it_open(client_factory, sent):
    with _on_duty():
        r = client_factory('member').post('/daily_trigger/send_message', json=SLT)
    assert r.get_json()['success'] is True


def test_direct_trigger_is_open_to_everyone(client_factory, sent):
    with _on_duty('someone@kinder.test'):
        r = client_factory('member').post('/api/direct_trigger/send', json={'telescope': 'SLT'})
    assert r.status_code != 403


def test_daily_trigger_page_says_who_is_on_duty(client_factory, sent):
    with _on_duty('someone@kinder.test'):
        r = client_factory('member').get('/daily_trigger')
    assert r.status_code == 200 and 'name="x-duty-lock" content="someone"' in r.get_data(as_text=True)
