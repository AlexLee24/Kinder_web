"""Background jobs and bots stay up: standby workers take the lock over, the GCN watchdog restarts its listener.
No database needed."""
import threading
import time

import pytest

from app.services.bots import gcn
from app.services.jobs import scheduler


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, 'LOG_DIR', tmp_path)
    monkeypatch.setattr(scheduler, '_bg_lock_fd', None)
    yield tmp_path
    if scheduler._bg_lock_fd:
        scheduler._bg_lock_fd.close()


def test_standby_takes_over_when_the_owner_lets_go(lock_dir, monkeypatch):
    import fcntl
    owner = open(lock_dir / '.background_jobs.lock', 'w')          # another process holds the lock
    fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = threading.Event()
    monkeypatch.setattr(scheduler, 'STANDBY_EVERY', 0.05)
    monkeypatch.setattr(scheduler, '_run_background_jobs', lambda app: started.set())
    assert scheduler.acquire_background_lock() is False and scheduler._bg_lock_fd is None   # nothing leaked
    threading.Thread(target=scheduler._take_over_when_free, args=(None,), daemon=True).start()
    time.sleep(0.3)
    assert not started.is_set()
    owner.close()                                                    # the owner's process ends
    assert started.wait(2)


def test_watchdog_restarts_a_dead_or_stuck_listener(monkeypatch):
    runs = []

    def fake_loop(gen=0):
        runs.append(gen)
        while gen == gcn._gen:
            time.sleep(0.02)

    monkeypatch.setattr(gcn, '_loop', fake_loop)
    monkeypatch.setattr(gcn, '_missing_settings', lambda: [])
    monkeypatch.setattr(gcn.status, 'event', lambda *a, **k: None)
    monkeypatch.setattr(gcn, '_thread', None)
    gcn.watchdog()                                   # no thread yet: started
    time.sleep(0.1)
    assert len(runs) == 1
    gcn.watchdog()                                   # alive and beating: left alone
    assert len(runs) == 1
    monkeypatch.setattr(gcn, '_last_beat', time.monotonic() - gcn.STALL_AFTER - 1)
    old = gcn._thread
    gcn.watchdog()                                   # stuck: replaced, the old thread stops
    time.sleep(0.1)
    assert len(runs) == 2 and not old.is_alive() and gcn._thread.is_alive()
    gcn._gen += 1                                    # stop the fake listener
