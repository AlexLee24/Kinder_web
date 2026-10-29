"""DETECT in Admin › Bots: every run of the embedded pipeline, whatever started it, is recorded as a bot run.
No database needed."""
import pytest

from app.services import bots
from app.services.bots import status
from app.services.detect import detect_pipeline as dp


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(status, 'LOG_DIR', tmp_path)
    monkeypatch.setattr(status, 'STATUS_FILE', tmp_path / '.bot_status.json')
    monkeypatch.setattr(dp, '_state', {'running': None, 'last': None})
    return tmp_path


def detect_view():
    return next(b for b in status.view() if b['id'] == 'detect')


def test_detect_is_one_of_the_bots():
    bot = bots.BY_ID['detect']
    assert bot.can_run and bot.kind == 'scheduled' and ('Review queue', '/detect') in bot.links


def test_a_run_shows_as_running_then_as_an_event(state):
    with dp._Run('Follow-up', 3):
        assert detect_view()['health'] == 'busy'
        dp._state['running']['counts'] = {'objects': 3, 'confirmed': 1, 'review': 0, 'none': 2}
    v = detect_view()
    assert v['health'] == 'ok' and v['today'] == 1
    assert v['last_run']['ok'] is True
    assert v['last_event']['text'].startswith('Follow-up: 3 objects · 1 confirmed')


def test_a_failed_run_needs_attention(state):
    with pytest.raises(RuntimeError):
        with dp._Run('recent 2h'):
            raise RuntimeError('boom')
    v = detect_view()
    assert v['health'] == 'bad' and 'boom' in v['last_error']['text']
    assert v['events'][0]['level'] == 'error'
