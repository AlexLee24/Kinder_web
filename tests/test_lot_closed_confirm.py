"""On a night the Lulin schedule closes LOT, a LOT send goes through only after the page's three confirmations."""
import pytest

from test_trigger_duty_lock import sent, user_rows  # noqa: F401  (fixtures)

LOT = {'telescope': 'LOT', 'greeting': 'Hi', 'script': '#waitfor 1\n', 'targets': [{'name': 'SN 2026a'}]}


@pytest.fixture
def closed(monkeypatch, sent):  # noqa: F811
    monkeypatch.setattr('app.services.lab_calendar.lot_closed_tonight', lambda: ['UVEX'])
    monkeypatch.setattr('app.blueprints.private_area.daily_trigger.tonight_duty', lambda: [])
    return sent


@pytest.mark.parametrize('confirmed', [None, 0, 1, 2, 'x'])
def test_lot_send_refused_without_three_confirms(client_factory, closed, confirmed):
    body = dict(LOT) if confirmed is None else dict(LOT, lot_closed_confirmed=confirmed)
    r = client_factory('member').post('/daily_trigger/send_message', json=body)
    assert r.status_code == 409 and r.get_json()['confirms_needed'] == 3 and closed == []


def test_lot_send_goes_through_after_three_confirms(client_factory, closed):
    r = client_factory('member').post('/daily_trigger/send_message', json=dict(LOT, lot_closed_confirmed=3))
    assert r.get_json()['success'] is True and len(closed) == 1


def test_single_lot_target_after_three_confirms(client_factory, closed):
    body = dict(LOT, mark_sent=False, lot_closed_confirmed=3)
    r = client_factory('member').post('/daily_trigger/send_message', json=body)
    assert r.get_json()['success'] is True and len(closed) == 1


def test_slt_needs_no_confirm(client_factory, closed):
    r = client_factory('member').post('/daily_trigger/send_message', json=dict(LOT, telescope='SLT'))
    assert r.get_json()['success'] is True


def test_direct_trigger_lot_needs_three_confirms(client_factory, closed):
    c = client_factory('member')
    assert c.post('/api/direct_trigger/send', json={'telescope': 'LOT'}).status_code == 409
    assert c.post('/api/direct_trigger/send', json={'telescope': 'LOT', 'lot_closed_confirmed': 3}).status_code != 409
