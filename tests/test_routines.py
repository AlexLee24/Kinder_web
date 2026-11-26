"""Routines registry (app/services/jobs/routines.py): triggers, labels, chained runs, the per-routine log and lock."""
import logging
import threading
from datetime import datetime, timezone

import pytest

from app.services.jobs import job_status, routines


@pytest.fixture
def rt_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(routines, 'LOG_DIR', tmp_path)
    monkeypatch.setattr(routines, 'ROUTINE_LOG_DIR', tmp_path / 'routines')
    monkeypatch.setattr(routines, 'HISTORY_FILE', tmp_path / '.routine_history.json')
    monkeypatch.setattr(routines, 'NEXT_RUN_FILE', tmp_path / '.routine_next_run.json')
    monkeypatch.setattr(routines, '_handlers', {})
    monkeypatch.setattr(job_status, '_STATUS_FILE', str(tmp_path / '.job_status.json'))
    return tmp_path


def test_every_scheduled_routine_has_a_working_trigger():
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    ids = [r.id for r in routines.ROUTINES]
    assert len(ids) == len(set(ids))
    for r in routines.ROUTINES:
        if r.bot:
            continue
        trig = routines.build_trigger(r)
        assert trig is not None, r.id
        assert trig.get_next_fire_time(None, now) >= now
        for s in r.steps:                                  # every step resolves to a callable
            assert callable(routines._resolve(s.func)), s.func


def test_times_read_utc8_then_utc0():
    assert routines.at(3, 30) == '11:30 UTC+8 (03:30 UTC+0)'
    assert routines.at(20) == '04:00 UTC+8 (20:00 UTC+0)'
    assert routines.BY_ID['morning_chain'].when == 'Daily 11:30 UTC+8 (03:30 UTC+0)'


def test_duty_trigger_fires_friday_and_twice_on_sunday():
    trig = routines.build_trigger(routines.BY_ID['lab_trigger_duty'])
    t = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)             # Thursday
    fires = []
    for _ in range(4):
        t = trig.get_next_fire_time(None, t)
        fires.append(t.strftime('%a %H'))
        t = t.replace(second=1)
    assert fires == ['Fri 02', 'Sun 02', 'Sun 08', 'Fri 02']


def test_duty_check_dispatches_by_taipei_day(monkeypatch):
    from app.services import lab_calendar as cal
    calls = []
    monkeypatch.setattr(cal, 'check_duty_weeks', lambda: calls.append('weeks'))
    monkeypatch.setattr(cal, 'check_duty_eve', lambda slot: calls.append('eve-' + slot))
    routines.duty_check(datetime(2026, 11, 27, 2, tzinfo=timezone.utc))   # Fri 10:00 UTC+8
    routines.duty_check(datetime(2026, 11, 29, 2, tzinfo=timezone.utc))   # Sun 10:00 UTC+8
    routines.duty_check(datetime(2026, 11, 29, 8, tzinfo=timezone.utc))   # Sun 16:00 UTC+8
    assert calls == ['weeks', 'eve-am', 'eve-pm']


def test_chain_runs_every_step_logs_and_records(rt_dir, monkeypatch):
    log = logging.getLogger('test.routine.steps')
    seen = []

    def ok_step():
        log.info('first step says hi')
        seen.append('a')
        return {'n': 3}

    def bad_step():
        seen.append('b')
        raise ValueError('boom')

    def err_step():
        seen.append('c')
        return {'error': 'nothing to do'}

    mod = type('M', (), {'ok_step': staticmethod(ok_step), 'bad_step': staticmethod(bad_step),
                         'err_step': staticmethod(err_step), 'last': staticmethod(lambda: seen.append('d'))})
    monkeypatch.setattr(routines, '_resolve', lambda path: getattr(mod, path.split(':')[1]))
    r = routines.Routine('t_chain', 'Test chain', 'Test', 'never', '',
                         steps=(routines.Step('A', 'x:ok_step'), routines.Step('B', 'x:bad_step'),
                                routines.Step('C', 'x:err_step'), routines.Step('D', 'x:last')))
    monkeypatch.setitem(routines.BY_ID, r.id, r)
    logging.getLogger().setLevel(logging.INFO)

    res = routines.run(r.id, manual=True)

    assert seen == ['a', 'b', 'c', 'd']                    # a failing step does not stop the chain
    assert res['ok'] is False and 'B: ValueError: boom' in res['message'] and 'C: nothing to do' in res['message']
    last = routines.history()['t_chain'][0]
    assert last['manual'] and last['finished_at'] and [s['ok'] for s in last['steps']] == [True, False, False, True]
    text = routines.read_log('t_chain')['text']
    assert 'first step says hi' in text and '✗ B' in text and '▶ Test chain (Run now)' in text
    assert '■ Finished with errors' in text
    assert job_status.get_all()['t_chain']['status'] == 'error'


def test_a_running_routine_is_not_started_twice(rt_dir, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)

    monkeypatch.setattr(routines, '_resolve', lambda path: slow)
    r = routines.Routine('t_slow', 'Slow', 'Test', 'never', '', steps=(routines.Step('S', 'x:slow'),))
    monkeypatch.setitem(routines.BY_ID, r.id, r)
    t = threading.Thread(target=routines.run, args=(r.id,))
    t.start()
    assert started.wait(5)
    assert routines.is_running(r.id)
    assert routines.run(r.id) == {'error': 'Already running.'}
    release.set()
    t.join(5)
    assert not routines.is_running(r.id)


def test_recycle_every_third_run_or_on_run_now(monkeypatch):
    import app.db as db
    calls = []
    monkeypatch.setattr(db, 'recycle_idle_connections', lambda: calls.append(1))
    monkeypatch.setattr(routines, '_recycle_n', 0)
    for _ in range(6):
        routines.recycle_db()
    routines.recycle_db(manual=True)
    assert len(calls) == 3


def test_register_adds_routines_with_their_ids(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.services import bots
    monkeypatch.setattr(bots, 'disabled', lambda: set())
    s = BackgroundScheduler(timezone='UTC')
    added = routines.register(s)
    ids = {j.id for j in s.get_jobs()}
    assert {'morning_chain', 'tns_hourly', 'tns_daily', 'tns_gap_fill', 'lab_calendar_tick', 'housekeeping',
            'db_maintenance', 'bot_auto_phot', 'bot_astronote', 'bot_obs_log'} <= ids
    assert 'daily_detect_followups' not in ids and 'detect_page_prewarm' not in ids     # folded into the chains
    assert set(added) <= set(routines.BY_ID)
