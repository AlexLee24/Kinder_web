"""Bot state and logs, shared by every gunicorn worker.

State: app/log/.bot_status.json, one entry per bot, read-modify-written under an flock (``update``):

    state        'listening' | 'running' | 'idle' | 'error' | 'stopped'
    pid          process running the bot
    started_at   listener start
    heartbeat_at listener's last sign of life
    last_run     {'started_at', 'finished_at', 'ok', 'message'}
    last_event   {'at', 'text', 'level'};  events: the newest 30 of them
    today        {'date' (UTC+8), 'n'}: events counted today
    last_error   {'at', 'text'}
    next_run     ISO time of the next scheduled run
    detail       bot specific (reduction: steps and folder overview; setup problems: 'setup')

Logs: logger ``bot.<id>`` → app/log/bots/<id>.log (1 MB × 3) and, through the root logger, the daily web log.
"""
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

try:
    import fcntl
except ImportError:  # non-POSIX: no cross-process lock
    fcntl = None

from app.paths import LOG_DIR

from . import BOTS, BY_ID

STATUS_FILE = LOG_DIR / '.bot_status.json'
BOT_LOG_DIR = LOG_DIR / 'bots'
MAX_EVENTS = 30
_TZ8 = timezone(timedelta(hours=8))
_lock = threading.Lock()
_loggers = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


# ── logs ──────────────────────────────────────────────────────────────────────

def log_path(bot_id):
    return BOT_LOG_DIR / f'{bot_id}.log'


def get_logger(bot_id):
    """``bot.<id>``: its own rotating file plus the daily web log (propagates to the root logger)."""
    with _lock:
        if bot_id in _loggers:
            return _loggers[bot_id]
        lg = logging.getLogger(f'bot.{bot_id}')
        lg.setLevel(logging.INFO)
        try:
            os.makedirs(BOT_LOG_DIR, exist_ok=True)
            fh = RotatingFileHandler(log_path(bot_id), maxBytes=1_000_000, backupCount=3, encoding='utf-8')
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            from app.core.log_setup import RedactSecretsFilter
            fh.addFilter(RedactSecretsFilter())
            lg.addHandler(fh)
        except OSError:
            pass
        _loggers[bot_id] = lg
        return lg


def read_log(bot_id, offset=None, max_bytes=200_000):
    """Log text for the page. offset None: the last ``max_bytes``; else what was appended since ``offset``.
    Returns {'text', 'offset', 'reset'}; reset is True when the file rotated (start over)."""
    p = log_path(bot_id)
    if not p.is_file():
        return {'text': '', 'offset': 0, 'reset': bool(offset)}
    size = p.stat().st_size
    reset = offset is not None and offset > size          # the file rotated: start over
    tail = offset is None or reset
    start = max(0, size - max_bytes) if tail else offset
    with open(p, 'rb') as fh:
        fh.seek(start)
        data = fh.read(max_bytes)
    text = data.decode('utf-8', errors='replace')
    if tail and start > 0 and '\n' in text:
        text = text.split('\n', 1)[1]                    # tail: drop the partial first line
    return {'text': text, 'offset': start + len(data), 'reset': reset}


# ── state ─────────────────────────────────────────────────────────────────────

def _read_file():
    try:
        with open(STATUS_FILE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def update(bot_id, _mutate=None, **fields):
    """Merge ``fields`` into the bot's entry (and apply ``_mutate(entry)``), under a cross-process lock."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with _lock, open(str(STATUS_FILE) + '.lock', 'a+') as lock_fh:
            if fcntl is not None:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                data = _read_file()
                entry = data.get(bot_id) if isinstance(data.get(bot_id), dict) else {}
                entry.update(fields)
                if _mutate:
                    _mutate(entry)
                entry['updated_at'] = now_iso()
                data[bot_id] = entry
                tmp = f'{STATUS_FILE}.{os.getpid()}.tmp'
                with open(tmp, 'w') as fh:
                    json.dump(data, fh, ensure_ascii=False)
                os.replace(tmp, STATUS_FILE)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)
    except Exception as e:  # state is best effort: never break a bot over it
        logging.getLogger(__name__).debug('bot status write failed: %s', e)


def event(bot_id, text, level='info', count=True):
    """Something the bot did (sent an alert, processed a night …): logged, listed on the page, counted today."""
    get_logger(bot_id).log(logging.ERROR if level == 'error' else logging.WARNING if level == 'warn' else logging.INFO, text)
    at = now_iso()
    today = datetime.now(_TZ8).date().isoformat()

    def mutate(e):
        ev = {'at': at, 'text': text[:500], 'level': level}
        e['last_event'] = ev
        e['events'] = ([ev] + list(e.get('events') or []))[:MAX_EVENTS]
        if count:
            t = e.get('today') or {}
            e['today'] = {'date': today, 'n': (t.get('n', 0) if t.get('date') == today else 0) + 1}
        if level == 'error':
            e['last_error'] = {'at': at, 'text': text[:500]}
    update(bot_id, _mutate=mutate)


def heartbeat(bot_id, **fields):
    update(bot_id, heartbeat_at=now_iso(), **fields)


def run_started(bot_id, **fields):
    at = now_iso()
    update(bot_id, state='running', pid=os.getpid(),
           _mutate=lambda e: e.__setitem__('last_run', {'started_at': at, 'finished_at': None, 'ok': None, 'message': ''}),
           **fields)


def run_finished(bot_id, ok, message='', **fields):
    at = now_iso()

    def mutate(e):
        run = dict(e.get('last_run') or {})
        run.update(finished_at=at, ok=bool(ok), message=str(message)[:500])
        e['last_run'] = run
        if not ok:
            e['last_error'] = {'at': at, 'text': str(message)[:500]}
    update(bot_id, state='idle' if ok else 'error', _mutate=mutate, **fields)


def get_all():
    return _read_file()


def guarded_run(bot_id, fn, *args, **kwargs):
    """Run a scheduled bot once: one run at a time across processes (flock), state and errors recorded.
    ``fn`` returns a one-line summary. Returns {'ok', 'message'} or {'error'} when a run is already going."""
    lock_fh = open(LOG_DIR / f'.bot_{bot_id}.lock', 'a+')
    try:
        if fcntl is not None:
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return {'error': 'Already running.'}
        run_started(bot_id)
        try:
            message = fn(*args, **kwargs) or 'Done.'
        except Exception as e:
            if isinstance(e, RuntimeError):      # the bot's own one-line reason
                get_logger(bot_id).error('Run failed: %s', e)
            else:
                get_logger(bot_id).exception('Run failed')
            run_finished(bot_id, False, f'{type(e).__name__}: {e}')
            return {'ok': False, 'message': str(e)}
        run_finished(bot_id, True, message)
        return {'ok': True, 'message': message}
    finally:
        lock_fh.close()                          # releases the flock


# ── view for the page ─────────────────────────────────────────────────────────

def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def health(bot, e, debug=False, off=False):
    """(code, label) for the status dot: ok | busy | idle | warn | bad | off."""
    detail = e.get('detail') or {}
    if off:
        return 'off', 'Disabled (BOTS_DISABLED)'
    if debug and bot.kind == 'listener':
        return 'off', 'Off (DEBUG)'
    if detail.get('setup'):
        return 'warn', 'Needs setup'
    if bot.kind == 'listener':
        hb = _parse(e.get('heartbeat_at'))
        if e.get('state') == 'stopped' or not hb:
            return 'bad', 'Stopped'
        age = (datetime.now(timezone.utc) - hb).total_seconds()
        if age > bot.stale_after or not _pid_alive(e.get('pid')):
            return 'bad', 'Not responding'
        return 'ok', 'Listening'
    if e.get('state') == 'running':
        if not _pid_alive(e.get('pid')):
            return 'bad', 'Died while running'
        return 'busy', 'Running'
    run = e.get('last_run') or {}
    if run.get('ok') is False:
        return 'bad', 'Last run failed'
    if not run:
        return 'idle', 'Manual only (DEBUG)' if debug else 'Not run yet'
    return 'ok', 'OK'


def view(debug=False, setup=None):
    """Every bot with its state, in page order. ``setup``: {bot id: problem found now} (missing settings, folders)."""
    from . import disabled
    data = _read_file()
    off = disabled()
    out = []
    for bot in BOTS:
        e = dict(data.get(bot.id) or {})
        problem = (setup or {}).get(bot.id)
        detail = {k: v for k, v in (e.get('detail') or {}).items() if k != 'setup' or setup is None}
        if problem:
            detail['setup'] = problem
        e['detail'] = detail
        code, label = health(bot, e, debug, bot.id in off)
        today = e.get('today') or {}
        out.append({
            'id': bot.id, 'name': bot.name, 'kind': bot.kind, 'schedule': bot.schedule, 'about': bot.about,
            'can_run': bot.can_run, 'can_stop': bot.can_stop, 'links': [list(x) for x in bot.links],
            'health': code, 'health_label': label,
            'state': e.get('state'), 'heartbeat_at': e.get('heartbeat_at'), 'started_at': e.get('started_at'),
            'last_run': e.get('last_run'), 'last_event': e.get('last_event'), 'last_error': e.get('last_error'),
            'next_run': e.get('next_run'), 'events': e.get('events') or [], 'detail': e.get('detail') or {},
            'today': today.get('n', 0) if today.get('date') == datetime.now(_TZ8).date().isoformat() else 0,
        })
    return out


def known(bot_id):
    return bot_id in BY_ID
