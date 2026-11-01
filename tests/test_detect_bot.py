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
    assert bot.can_run and bot.kind == 'scheduled' and ('TNS-DETECT', '/detect') in bot.links and ('LSST-DETECT', '/detect/lsst') in bot.links


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


def test_next_slot_of_each_trigger():
    from datetime import datetime, timezone

    from app.services.bots.detect import LSST_HOURLY, LSST_SWEEP, TNS_RUNS, _next_slot
    now = datetime(2026, 11, 1, 16, 17, tzinfo=timezone.utc)
    nxt = {name: _next_slot(now, h, m) for _, name, h, m in TNS_RUNS}
    assert nxt == {'TNS hourly import': '2026-11-01T16:45:00+00:00', 'TNS daily import': '2026-11-02T01:00:00+00:00',
                   'Follow-up re-screen': '2026-11-02T04:00:00+00:00'}
    assert _next_slot(now, *LSST_HOURLY) == '2026-11-01T16:25:00+00:00'
    assert _next_slot(now, *LSST_SWEEP) == '2026-11-02T14:30:00+00:00'


def test_card_shows_lsst_failure_and_how_new_alerce_is(monkeypatch):
    import json
    import time

    from app.services.bots import detect as detect_bot
    from app.services.lsst import alerts
    cursor = 61344.318807          # 2026-10-31 07:39 UTC
    settings = {
        alerts.STATUS_KEY: json.dumps({'state': 'error', 'trigger': 'hourly', 'started_at': time.time() - 60,
                                       'finished_at': time.time(), 'log': ['16:25:00  FAILED: ALeRCE HTTP 403']}),
        alerts.LAST_RUN_KEY: json.dumps({'at': time.time() - 3600, 'fetched': 25, 'by_class': {'SN': 1, 'AGN': 16, 'VS': 8},
                                         'window': [cursor - 0.08, cursor + 1.3]}),
        alerts.CURSOR_KEY: str(cursor),
    }
    monkeypatch.setattr('app.db.auth.get_settings', lambda keys: {k: settings[k] for k in keys})
    monkeypatch.setattr(alerts, 'is_running', lambda: False)
    lsst = detect_bot.sources()['lsst']
    assert lsst['state'] == 'error' and lsst['error'] == 'ALeRCE HTTP 403'
    assert lsst['last_ok']['by_class'] == {'SN': 1, 'AGN': 16, 'VS': 8}
    assert lsst['newest_alert_at'].startswith('2026-10-31T07:39') and lsst['stale']
