"""Job last-run registry — in-memory within a process, file-backed across gunicorn workers."""
import threading
import json
import os
import time
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_registry: dict = {}  # in-process store (authoritative for is_running)

# Persist completed-run results to this file so all workers can read them.
_STATUS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'log', '.job_status.json')
)
_last_read_ts: float = 0.0
_FILE_CACHE_TTL = 10.0  # seconds between file re-reads
_file_cache: dict = {}


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _persist() -> None:
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with _lock:
            data = {k: dict(v) for k, v in _registry.items()
                    if v.get('finished_at')}   # only write completed entries
        tmp = _STATUS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, _STATUS_FILE)          # atomic replace
    except Exception as e:
        logger.debug('job_status persist error: %s', e)


def _read_file() -> dict:
    global _last_read_ts, _file_cache
    now = time.monotonic()
    if now - _last_read_ts < _FILE_CACHE_TTL:
        return _file_cache
    try:
        with open(_STATUS_FILE, 'r') as f:
            _file_cache = json.load(f)
    except FileNotFoundError:
        _file_cache = {}
    except Exception as e:
        logger.debug('job_status read error: %s', e)
    _last_read_ts = now
    return _file_cache


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_start(job_id: str) -> None:
    with _lock:
        prev = _registry.get(job_id, {})
        _registry[job_id] = {
            **prev,
            'started_at': _now_iso(),
            'finished_at': None,
        }


def record_finish(job_id: str, success: bool, message: str = '') -> None:
    with _lock:
        prev = _registry.get(job_id, {})
        _registry[job_id] = {
            **prev,
            'finished_at': _now_iso(),
            'status': 'success' if success else 'error',
            'message': message,
        }
    _persist()


def is_running(job_id: str) -> bool:
    """Only reliable within the process that owns the scheduler."""
    with _lock:
        rec = _registry.get(job_id)
        if not rec:
            return False
        return bool(rec.get('started_at') and not rec.get('finished_at'))


def get_all() -> dict:
    """Merge file (cross-worker) with in-process registry (most recent)."""
    file_data = _read_file()
    with _lock:
        merged = dict(file_data)
        merged.update(_registry)   # in-process entries override (more recent)
        return {k: dict(v) for k, v in merged.items()}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
