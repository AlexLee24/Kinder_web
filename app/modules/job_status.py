"""In-memory registry for tracking scheduled job last-run results."""
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_registry: dict = {}


def record_start(job_id: str) -> None:
    with _lock:
        prev = _registry.get(job_id, {})
        _registry[job_id] = {
            **prev,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'finished_at': None,
        }


def record_finish(job_id: str, success: bool, message: str = '') -> None:
    with _lock:
        prev = _registry.get(job_id, {})
        _registry[job_id] = {
            **prev,
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'status': 'success' if success else 'error',
            'message': message,
        }


def is_running(job_id: str) -> bool:
    with _lock:
        rec = _registry.get(job_id)
        if not rec:
            return False
        return bool(rec.get('started_at') and not rec.get('finished_at'))


def get_all() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _registry.items()}
