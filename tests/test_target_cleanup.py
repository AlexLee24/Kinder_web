"""Off Daily Trigger targets go 3 days after they were switched off, unless kept; targets that are on stay."""
from datetime import datetime, timedelta, timezone

from app.db import obs


def test_delete_at_counts_three_days_from_switching_off():
    off = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
    base = {'target_id': 1, 'active': False, 'name': 'X', 'off_since': off, 'keep': False}
    d = obs._target_to_dict(dict(base))
    assert d['delete_at'] == (off + timedelta(days=3)).isoformat()
    assert obs._target_to_dict({**base, 'keep': True})['delete_at'] is None          # kept
    assert obs._target_to_dict({**base, 'active': True, 'off_since': None})['delete_at'] is None   # on


def test_the_prune_only_deletes_off_targets_that_are_not_kept(monkeypatch):
    seen = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append((sql, params))

        def fetchall(self):
            return []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self, **k): return Cur()
        def commit(self): pass

    monkeypatch.setattr(obs, 'get_db_connection', lambda: Conn())
    monkeypatch.setattr(obs, '_cleanup_ready', True)
    assert obs.prune_off_targets() == []
    sql, params = seen[-1]
    assert 'active = FALSE' in sql and 'NOT keep' in sql and 'off_since <' in sql
    assert params == (3,)
