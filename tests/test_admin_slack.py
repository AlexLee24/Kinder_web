"""Admin › Slack: who may send, what is checked before a message goes, and what goes to Slack (mocked)."""
from unittest import mock

import pytest

from app.blueprints.auth.admin import slack
from conftest import PERSONAS


@pytest.fixture(autouse=True)
def user_rows(monkeypatch):
    """The personas' DB rows, so the session check passes without a database."""
    rows = {p['email']: dict(p, session_version=0, must_change_password=False, has_password=False)
            for p in PERSONAS.values() if p}
    monkeypatch.setattr('app.core.auth._get_user_cached', rows.get)


@pytest.fixture
def fake_slack(monkeypatch):
    """A Slack client that records posts instead of sending; history kept in memory, not the DB."""
    posted, kept = [], []
    client = mock.Mock()
    client.chat_postMessage.side_effect = lambda **kw: posted.append(kw) or {'ok': True, 'ts': '1.2'}
    monkeypatch.setenv('SLACK_BOT_TOKEN', 'xoxb-test')
    monkeypatch.setenv('SLACK_CHANNEL_ID_CONTROL_ROOM', 'C0CONTROL1')
    monkeypatch.setattr(slack, '_remember', kept.append)
    with mock.patch('slack_sdk.WebClient', return_value=client):
        yield posted, kept


def test_members_cannot_send(client_factory, fake_slack):
    r = client_factory('member').post('/admin/slack/send', json={'text': 'hi', 'channel': 'SLACK_CHANNEL_ID_CONTROL_ROOM'})
    assert r.status_code in (302, 401, 403)
    assert fake_slack[0] == []


def test_admin_posts_to_a_known_channel(admin_client, fake_slack):
    posted, kept = fake_slack
    r = admin_client.post('/admin/slack/send', json={'text': '*Hello* lab', 'channel': 'SLACK_CHANNEL_ID_CONTROL_ROOM',
                                                     'template': 'push_on'})
    assert r.get_json()['ok'] is True
    assert posted == [{'channel': 'C0CONTROL1', 'text': '*Hello* lab', 'unfurl_links': False}]
    assert kept[0]['label'] == 'Control room' and kept[0]['template'] == 'push_on'


@pytest.mark.parametrize('body, error', [
    ({'text': '  ', 'channel': 'SLACK_CHANNEL_ID_CONTROL_ROOM'}, 'Write a message'),
    ({'text': 'x' * 3001, 'channel': 'SLACK_CHANNEL_ID_CONTROL_ROOM'}, 'under 3000'),
    ({'text': 'hi', 'channel': 'SOMETHING_ELSE'}, 'Choose a channel'),
    ({'text': 'hi', 'channel': 'custom', 'channel_id': '#general'}, 'channel id looks like'),
])
def test_bad_requests_send_nothing(admin_client, fake_slack, body, error):
    r = admin_client.post('/admin/slack/send', json=body)
    assert r.status_code == 400 and error in r.get_json()['error']
    assert fake_slack[0] == []


def test_custom_channel_id(admin_client, fake_slack):
    r = admin_client.post('/admin/slack/send', json={'text': 'hi', 'channel': 'custom', 'channel_id': 'c0abc1234'})
    assert r.get_json()['ok'] is True
    assert fake_slack[0][0]['channel'] == 'C0ABC1234'


def test_templates_never_break_the_page(monkeypatch):
    def boom():
        raise RuntimeError('db down')
    monkeypatch.setattr(slack, 'TEMPLATES', [('x', 'X', 'SLACK_CHANNEL_ID_CONTROL_ROOM', boom)])
    assert slack._templates()[0]['text'].startswith('(Could not fill this one in')
