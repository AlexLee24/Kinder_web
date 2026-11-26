"""Routines: every scheduled background job in one registry, for the scheduler and Admin › Routines.

A routine is either a list of steps run here (``run()``: one run at a time across processes, a log file of its own,
run history) or one of the lab bots (``bot``: the bot keeps its own state and log, see app/services/bots). The
scheduler (jobs/scheduler.py) registers ``ROUTINES``; the admin page reads the same list, so a schedule is written
down once. All triggers are UTC; ``at()`` writes a time the way the page shows it: ``12:00 UTC+8 (04:00 UTC+0)``.

Steps of a chain run in order; a failing step is logged and the next one still runs (they do not depend on each
other's success, only on their order). Whatever the steps log from the routine's thread goes to
app/log/routines/<id>.log as well as to the daily web log.
"""
import fcntl
import importlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from app.paths import LOG_DIR

logger = logging.getLogger(__name__)

TZ8 = timezone(timedelta(hours=8))
ROUTINE_LOG_DIR = LOG_DIR / 'routines'
HISTORY_FILE = LOG_DIR / '.routine_history.json'
NEXT_RUN_FILE = LOG_DIR / '.routine_next_run.json'
HISTORY_KEEP = 20


def at(hour, minute=0):
    """UTC hour:minute as the page writes it: '12:00 UTC+8 (04:00 UTC+0)'."""
    t = datetime(2000, 1, 1, hour, minute, tzinfo=timezone.utc)
    return f'{t.astimezone(TZ8):%H:%M} UTC+8 ({t:%H:%M} UTC+0)'


@dataclass(frozen=True)
class Step:
    name: str
    func: str                      # 'module:function', imported when the step runs
    kwargs: dict = field(default_factory=dict)
    manual_kwargs: dict = field(default_factory=dict)    # extra kwargs for Run now (e.g. a forced backup)
    enabled: str = ''              # 'module:flag' — skip the step when that attribute is false


@dataclass(frozen=True)
class Routine:
    id: str
    name: str
    group: str
    when: str                      # schedule as shown on the page
    about: str
    trigger: tuple = ()            # (('cron', {...}) | ('interval', {...}), …) — several are OR'ed
    steps: tuple = ()
    bot: str = ''                  # a lab bot: run / log / state come from app/services/bots
    job_id: str = ''               # APScheduler id (default: the routine id; bots keep bot_<id>)
    can_run: bool = True
    enabled: str = ''              # 'module:flag' or 'module:function()' — the routine is off when false
    times: tuple = ()              # UTC (hour, minute) marks for the day strip on the page

    @property
    def jid(self):
        return self.job_id or self.id


def _cron(**kw):
    return ('cron', kw)


def _every(**kw):
    return ('interval', kw)


P = 'app.services.photometry.phot_scheduler'
TNS = 'app.services.tns.auto_tns_download'
CAL = 'app.services.lab_calendar'
PREWARM = Step('DETECT page cache', 'app.services.jobs.routines:prewarm_detect_page')

ROUTINES = (
    # ── Photometry & targets ────────────────────────────────────────────────────────────────────────────
    Routine('morning_chain', 'Morning photometry chain', 'Photometry & targets', f'Daily {at(3, 30)}',
            'One chain instead of six jobs an hour apart: each step starts when the previous one is done, so DETECT '
            'and the magnitudes always see the fresh photometry.',
            trigger=(_cron(hour=3, minute=30),), times=((3, 30),),
            steps=(Step('Inbox photometry fetch', f'{P}:fetch_inbox_photometry'),
                   Step('DETECT follow-up re-screen', 'app.services.detect.detect_pipeline:run_followups',
                        enabled='app.services.detect.detect_pipeline:ENABLED'),
                   PREWARM,
                   Step('Target magnitudes', f'{P}:update_target_mags'),
                   Step('SLT auto exposure (CASTOR)', 'app.services.planning.auto_exposure:update_all'),
                   Step('Retire stale follow-ups', f'{P}:retire_stale_followups'),
                   Step('Host redshift sync', 'app.db.transient:sync_host_redshifts'))),
    Routine('auto_phot', 'Auto photometry (AutoPhOT)', 'Photometry & targets', f'Daily {at(5, 30)} · and 3 min after a restart',
            "Last night's calibrated Lulin frames → AutoPhOT → Daily Trigger and Transient pages; then the target "
            'magnitudes and tonight\'s auto exposure from the new points.',
            trigger=(_cron(hour=5, minute=30),), bot='auto_phot', job_id='bot_auto_phot', times=((5, 30),)),

    # ── TNS & alerts ────────────────────────────────────────────────────────────────────────────────────
    Routine('tns_hourly', 'TNS hourly import', 'TNS & alerts', 'Every hour at :15 and :45',
            "TNS hourly file → transient.objects (new objects get their light curve) → DETECT → auto-snooze; then the "
            'DETECT page cache.',
            trigger=(_cron(minute='15,45'),), steps=(Step('Import + DETECT', f'{TNS}:run_hourly_now'), PREWARM)),
    Routine('tns_daily', 'TNS daily import', 'TNS & alerts', f'Daily {at(1)} · {at(4)} · {at(12)}',
            'TNS daily files of today, yesterday and the day before (fills what the hourly files missed) → DETECT for '
            'the objects that are new.',
            trigger=(_cron(hour='1,4,12', minute=0),), times=((1, 0), (4, 0), (12, 0)),
            steps=(Step('Import + DETECT', f'{TNS}:run_daily_now'), PREWARM)),
    Routine('tns_gap_fill', 'TNS gap filler', 'TNS & alerts', 'Every hour at :35',
            "Names missing from this year's sequence (2026a, b, …) asked one by one from the TNS object API "
            '(60 s apart for the rate limit). A long run simply skips the next hours.',
            trigger=(_cron(minute=35),), steps=(Step('Fill kinder_id gaps', 'app.services.tns.tns_gap_filler:run_once'),)),
    Routine('lsst_watch', 'LSST watch', 'TNS & alerts', 'Every hour at :25',
            'New ALeRCE LSST objects vs Lens / DESI, LSST light curves of TNS objects (after the :15 TNS import).',
            trigger=(_cron(minute=25),), enabled='app.services.lsst.alerts:ENABLED',
            steps=(Step('LSST watch', 'app.services.lsst.alerts:run_watch'),)),
    Routine('lsst_daily_sweep', 'LSST daily sweep', 'TNS & alerts', f'Daily {at(14, 30)}',
            'Re-reads the last 1.5 days of LSST objects (late ingests), after the Chilean night.',
            trigger=(_cron(hour=14, minute=30),), enabled='app.services.lsst.alerts:ENABLED', times=((14, 30),),
            steps=(Step('LSST sweep', 'app.services.lsst.alerts:run_daily_sweep'),)),
    Routine('astronote', 'TNS AstroNotes', 'TNS & alerts', 'Every 5 min', 'New TNS AstroNotes → Slack.',
            trigger=(_every(minutes=5),), bot='astronote', job_id='bot_astronote'),
    Routine('gcn_watchdog', 'GCN listener watchdog', 'TNS & alerts', 'Every 1 min',
            'Starts the GCN / Einstein Probe listener again when its thread died or stopped beating.',
            trigger=(_every(minutes=1),), can_run=False, enabled='app.services.jobs.routines:_bot_on(gcn)',
            steps=(Step('Watchdog', 'app.services.bots.gcn:watchdog'),)),

    # ── Lulin data ──────────────────────────────────────────────────────────────────────────────────────
    Routine('obs_log', 'Observation log', 'Lulin data', f'Daily {at(4, 15)}',
            'Lulin raw frames (FITS headers) → obs.logs "observed", last 15 nights.',
            trigger=(_cron(hour=4, minute=15),), bot='obs_log', job_id='bot_obs_log', times=((4, 15),)),
    Routine('reduction', 'Reduction pipeline', 'Lulin data', 'REDUCTION_HOUR_UTC (unset: by hand)',
            "The Lulin reduction pipeline (auto_calibration.sh), step by step.", bot='reduction', job_id='bot_reduction'),
    Routine('nas_backup', 'NAS backup', 'Lulin data', 'Every NAS_ARCHIVE_INTERVAL_MIN (60) min',
            'Old raw nights, masters and calibrated targets → lab NAS (only with NAS_IP / NAS_PATH set).',
            bot='nas_backup', job_id='bot_nas_backup'),

    # ── Lab calendar ────────────────────────────────────────────────────────────────────────────────────
    Routine('lab_calendar_tick', 'Calendar reminders', 'Lab calendar', 'Every 1 min',
            'Lab events: remind the members before they start. After Lulin sunset: "Trigger duty tonight" to the '
            'person on duty (once a night).',
            trigger=(_every(minutes=1),),
            steps=(Step('Event reminders', f'{CAL}:send_event_reminders'),
                   Step('Trigger duty tonight', f'{CAL}:send_trigger_reminders'))),
    Routine('lab_trigger_duty', 'Trigger duty: open nights', 'Lab calendar',
            f'Fri {at(2)} · Sun {at(2)} and {at(8)}',
            'Friday: the week after next has a night without Trigger duty → Slack. Sunday (twice): the week starting '
            'tomorrow is still open → Slack again. Each posts at most once.',
            trigger=(_cron(day_of_week='fri', hour=2, minute=0), _cron(day_of_week='sun', hour='2,8', minute=0)),
            steps=(Step('Duty check', 'app.services.jobs.routines:duty_check'),)),
    Routine('lulin_calendar_sync', 'Lulin LOT calendar sync', 'Lab calendar', 'Every 6 h (and at start when older)',
            'Lulin LOT Google calendar → Lab › Calendar.',
            trigger=(_every(hours=6),), steps=(Step('Sync', f'{CAL}:sync_lulin'),)),

    # ── Database & housekeeping ─────────────────────────────────────────────────────────────────────────
    Routine('daily_backup', 'Database backup', 'Database & housekeeping', f'Daily {at(3)} · at start if today has none',
            'pg_dump of every database → app/data/backups/ (one file a day). Run now always dumps again.',
            trigger=(_cron(hour=3, minute=0),), times=((3, 0),),
            steps=(Step('pg_dump', 'app.services.jobs.backup:run_daily_backup', manual_kwargs={'force': True}),)),
    Routine('db_maintenance', 'Database connections', 'Database & housekeeping', 'Every 10 min',
            'Pool and server connection check (email alert over the limit); every third run also closes idle '
            'pooled connections.',
            trigger=(_every(minutes=10),),
            steps=(Step('Connection check', 'app.services.jobs.db_monitor:check_and_alert'),
                   Step('Recycle idle connections', 'app.services.jobs.routines:recycle_db'))),
    Routine('housekeeping', 'Housekeeping', 'Database & housekeeping', 'Every hour',
            'Daily Trigger targets switched off > 3 days (not kept) → deleted; Pipeline FITS older than 7 days → '
            'deleted.',
            trigger=(_every(hours=1),),
            steps=(Step('Prune switched-off targets', 'app.services.jobs.target_cleanup:prune_off_targets'),
                   Step('Pipeline FITS clean-up', 'app.services.pipeline.autophot:cleanup_expired'))),
)
BY_ID = {r.id: r for r in ROUTINES}
GROUPS = tuple(dict.fromkeys(r.group for r in ROUTINES))


# ── small step helpers ──────────────────────────────────────────────────────────────────────────────────

def _bot_on(bot_id):
    from app.services import bots
    return bot_id not in bots.disabled()


def duty_check(now=None):
    """lab_trigger_duty: Sunday (UTC+8) → the eve check of that slot, any other day → the Friday check."""
    from app.services import lab_calendar as cal
    now = (now or datetime.now(timezone.utc)).astimezone(TZ8)
    if now.weekday() == 6:
        return cal.check_duty_eve(slot='am' if now.hour < 13 else 'pm')
    return cal.check_duty_weeks()


_recycle_n = 0


def recycle_db(manual=False):
    """db_maintenance: close idle pooled connections every third run (every 30 min), or now on Run now."""
    global _recycle_n
    _recycle_n += 1
    if not manual and _recycle_n % 3:
        return 'skipped (every third run)'
    from app.db import recycle_idle_connections
    return recycle_idle_connections()


_app = None


def prewarm_detect_page():
    """The DETECT page cache of the latest dates (lives in this process; needs the Flask app)."""
    if _app is None:
        return 'skipped (no app)'
    from app.blueprints.detect.cache import prewarm_detect_page_cache
    return prewarm_detect_page_cache(app_obj=_app)


# ── resolving names ─────────────────────────────────────────────────────────────────────────────────────

def _resolve(path):
    """'module:attr' → the attribute; 'module:fn(arg)' → fn(arg) called now."""
    mod, _, attr = path.partition(':')
    arg = None
    if attr.endswith(')') and '(' in attr:
        attr, _, arg = attr[:-1].partition('(')
    obj = getattr(importlib.import_module(mod), attr)
    return obj(arg) if arg is not None else obj


def is_enabled(r):
    if not r.enabled:
        return True
    try:
        return bool(_resolve(r.enabled))
    except Exception:
        return False


def _bot_func(r):
    from app.services import bots   # noqa: F401  (package import first)
    return importlib.import_module(f'app.services.bots.{r.bot}').run


# ── per-routine log ─────────────────────────────────────────────────────────────────────────────────────

_bound = {}                 # thread ident → routine id
_handlers = {}
_hlock = threading.Lock()


def log_path(rid):
    return ROUTINE_LOG_DIR / f'{rid}.log'


def _file_handler(rid):
    with _hlock:
        h = _handlers.get(rid)
        if h is None:
            os.makedirs(ROUTINE_LOG_DIR, exist_ok=True)
            h = RotatingFileHandler(log_path(rid), maxBytes=1_000_000, backupCount=2, encoding='utf-8')
            h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            try:
                from app.core.log_setup import RedactSecretsFilter
                h.addFilter(RedactSecretsFilter())
            except Exception:
                pass
            _handlers[rid] = h
        return h


class _Capture(logging.Handler):
    """On the root logger: a record logged from a thread that is running a routine also goes to its file."""

    def emit(self, record):
        rid = _bound.get(record.thread)
        if rid:
            try:
                _file_handler(rid).handle(record)
            except Exception:
                pass


_capture = None


def _install_capture():
    global _capture
    with _hlock:
        if _capture is None:
            _capture = _Capture(level=logging.INFO)
            logging.getLogger().addHandler(_capture)


def read_log(rid, offset=None, max_bytes=200_000):
    """Same contract as bots.status.read_log: {'text', 'offset', 'reset'}."""
    r = BY_ID[rid]
    if r.bot:
        from app.services.bots import status
        return status.read_log(r.bot, offset, max_bytes)
    p = log_path(rid)
    if not p.is_file():
        return {'text': '', 'offset': 0, 'reset': bool(offset)}
    size = p.stat().st_size
    reset = offset is not None and offset > size
    tail = offset is None or reset
    start = max(0, size - max_bytes) if tail else offset
    with open(p, 'rb') as fh:
        fh.seek(start)
        data = fh.read(max_bytes)
    text = data.decode('utf-8', errors='replace')
    if tail and start > 0 and '\n' in text:
        text = text.split('\n', 1)[1]
    return {'text': text, 'offset': start + len(data), 'reset': reset}


# ── shared state files (several gunicorn workers read them) ─────────────────────────────────────────────

def _read_json(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _update_json(path, mutate):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(str(path) + '.lock', 'a+') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            data = _read_json(path)
            mutate(data)
            tmp = f'{path}.{os.getpid()}.tmp'
            with open(tmp, 'w') as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def history():
    return _read_json(HISTORY_FILE)


def _record(rid, entry):
    def mutate(data):
        runs = [e for e in (data.get(rid) or []) if e.get('started_at') != entry['started_at']]
        data[rid] = ([entry] + runs)[:HISTORY_KEEP]
    try:
        _update_json(HISTORY_FILE, mutate)
    except Exception as e:
        logger.debug('routine history write failed: %s', e)


def save_next_runs(scheduler):
    """Called in the process that owns the scheduler: every job's next run, for the page in any worker."""
    out = {}
    for job in scheduler.get_jobs():
        if job.next_run_time:
            out[job.id] = job.next_run_time.astimezone(timezone.utc).isoformat(timespec='seconds')
    try:
        _update_json(NEXT_RUN_FILE, lambda d: (d.clear(), d.update(out), d.__setitem__('_at', _now())))
    except Exception as e:
        logger.debug('routine next-run write failed: %s', e)


def next_runs():
    return _read_json(NEXT_RUN_FILE)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ── running ─────────────────────────────────────────────────────────────────────────────────────────────

def _lock_file(rid):
    os.makedirs(ROUTINE_LOG_DIR, exist_ok=True)
    return open(ROUTINE_LOG_DIR / f'.{rid}.lock', 'a+')


def is_running(rid):
    """True while any process runs this routine (its flock is held)."""
    r = BY_ID.get(rid)
    if r is None:
        return False
    if r.bot:
        from app.services.bots import status
        return (status.get_all().get(r.bot) or {}).get('state') == 'running'
    fh = _lock_file(rid)
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        fh.close()
    return False


def _summary(value):
    if value is None:
        return 'done'
    if isinstance(value, dict):
        if not value:
            return 'done'
        return ', '.join(f'{k}={v}' for k, v in list(value.items())[:6])[:200]
    if isinstance(value, (list, tuple)):
        return f'{len(value)} item(s)'
    return str(value)[:200]


def run(rid, manual=False):
    """Run a routine once (the scheduler calls this; Run now calls it in a thread).
    Returns {'ok', 'message'} or {'error'} when it is already running."""
    r = BY_ID[rid]
    if r.bot:
        fn = _bot_func(r)
        res = fn()
        return res if isinstance(res, dict) else {'ok': True, 'message': str(res)}
    fh = _lock_file(rid)
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            logger.info('Routine %s is still running: this run is skipped', rid)
            return {'error': 'Already running.'}
        return _run_steps(r, manual)
    finally:
        fh.close()


def _run_steps(r, manual):
    from app.services.jobs import job_status
    _install_capture()
    me = threading.get_ident()
    _bound[me] = r.id
    started = _now()
    t0 = time.monotonic()
    rlog = logging.getLogger(f'routine.{r.id}')
    job_status.record_start(r.id)
    _record(r.id, {'started_at': started, 'finished_at': None, 'ok': None, 'manual': manual, 'steps': []})
    steps, failed = [], []
    try:
        rlog.info('▶ %s (%s)', r.name, 'Run now' if manual else 'scheduled')
        for s in r.steps:
            if s.enabled:
                try:
                    on = bool(_resolve(s.enabled))
                except Exception:
                    on = False
                if not on:
                    steps.append({'name': s.name, 'ok': None, 'message': 'off', 'secs': 0})
                    continue
            ts = time.monotonic()
            rlog.info('· %s', s.name)
            try:
                kwargs = {**s.kwargs, **(s.manual_kwargs if manual else {})}
                if s.func.endswith(':recycle_db'):
                    kwargs['manual'] = manual
                value = _resolve(s.func)(**kwargs)
                bad = isinstance(value, dict) and value.get('error')
                msg = str(value['error'])[:200] if bad else _summary(value)
                ok = not bad
            except Exception as e:
                rlog.exception('%s failed', s.name)
                ok, msg = False, f'{type(e).__name__}: {e}'[:200]
            secs = round(time.monotonic() - ts, 1)
            (rlog.info if ok else rlog.error)('  %s %s (%.1f s): %s', '✓' if ok else '✗', s.name, secs, msg)
            steps.append({'name': s.name, 'ok': ok, 'message': msg, 'secs': secs})
            if not ok:
                failed.append(f'{s.name}: {msg}')
        secs = round(time.monotonic() - t0, 1)
        ok = not failed
        message = '; '.join(failed)[:300] if failed else (steps[-1]['message'] if len(steps) == 1 else f'{len(steps)} steps done')
        rlog.info('■ %s in %.1f s%s', 'Done' if ok else 'Finished with errors', secs, '' if ok else ': ' + message)
    finally:
        _bound.pop(me, None)
    job_status.record_finish(r.id, ok, '' if ok else message)
    _record(r.id, {'started_at': started, 'finished_at': _now(), 'ok': ok, 'manual': manual, 'secs': secs,
                   'message': message, 'steps': steps})
    return {'ok': ok, 'message': message}


def start_now(rid):
    """Run now (admin): in a background thread. Returns {'ok', 'message'} or {'error'}."""
    r = BY_ID.get(rid)
    if r is None:
        return {'error': 'Unknown routine.'}
    if not r.can_run:
        return {'error': 'This routine cannot be run by hand.'}
    if r.bot:
        from app.services.bots import BY_ID as BOTS
        if not BOTS.get(r.bot) or not BOTS[r.bot].can_run:
            return {'error': 'This bot cannot be run by hand.'}
        if r.bot == 'reduction':
            from app.services.bots import reduction
            return reduction.start_now()
    if is_running(rid):
        return {'error': 'Already running.'}
    if r.bot:
        threading.Thread(target=_bot_func(r), name=f'manual-routine-{rid}', daemon=True).start()
    else:
        threading.Thread(target=run, args=(rid,), kwargs={'manual': True}, name=f'manual-routine-{rid}',
                         daemon=True).start()
    return {'ok': True, 'message': 'Started.'}


# ── scheduler side ──────────────────────────────────────────────────────────────────────────────────────

def build_trigger(r):
    from apscheduler.triggers.combining import OrTrigger
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    parts = []
    for kind, kw in r.trigger:
        parts.append(CronTrigger(timezone='UTC', **kw) if kind == 'cron' else IntervalTrigger(timezone='UTC', **kw))
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else OrTrigger(parts)


def bot_trigger(r):
    """Bots whose schedule comes from the environment (reduction hour, NAS interval)."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    if r.bot == 'reduction':
        from app.services.bots import reduction
        h = reduction.hour_utc()
        return CronTrigger(timezone='UTC', hour=h, minute=0) if h is not None else None
    if r.bot == 'nas_backup':
        from app.services.bots import nas_backup
        return IntervalTrigger(timezone='UTC', minutes=nas_backup.interval_min()) if nas_backup.configured() else None
    return build_trigger(r)


def schedule_label(r):
    """The page's schedule text; the env-driven bots read their setting now."""
    try:
        if r.bot == 'reduction':
            from app.services.bots import reduction
            h = reduction.hour_utc()
            return f'Daily {at(h)}' if h is not None else 'By hand only (REDUCTION_HOUR_UTC unset)'
        if r.bot == 'nas_backup':
            from app.services.bots import nas_backup
            return (f'Every {nas_backup.interval_min()} min' if nas_backup.configured()
                    else 'Off until NAS_IP / NAS_PATH are set')
    except Exception:
        pass
    return r.when


def day_marks(r):
    """UTC (hour, minute) marks for the page's 24 h strip."""
    if r.bot == 'reduction':
        try:
            from app.services.bots import reduction
            h = reduction.hour_utc()
            return ((h, 0),) if h is not None else ()
        except Exception:
            return ()
    return r.times


def register(scheduler, app=None):
    """Add every routine that is on to ``scheduler`` (the process that owns the background jobs)."""
    global _app
    _app = app
    _install_capture()
    from app.services import bots
    off = bots.disabled()
    added = []
    for r in ROUTINES:
        if r.bot and r.bot in off:
            continue
        if not is_enabled(r):
            continue
        trig = bot_trigger(r) if r.bot else build_trigger(r)
        if trig is None:
            continue
        func = _bot_func(r) if r.bot else run
        args = () if r.bot else (r.id,)
        scheduler.add_job(func, trig, args=args, id=r.jid, max_instances=1, coalesce=True, misfire_grace_time=600)
        added.append(r.id)
    return added


def tns_startup_catch_up(scheduler):
    """A restart right after a TNS slot (within 10 min) still runs that import, as the old daemon loop did."""
    now = datetime.now(timezone.utc)
    for rid, minutes, hours in (('tns_hourly', (15, 45), None), ('tns_daily', (0,), (1, 4, 12))):
        for back in range(0, 11):
            t = now - timedelta(minutes=back)
            if t.minute in minutes and (hours is None or t.hour in hours):
                scheduler.add_job(run, 'date', args=(rid,), run_date=now + timedelta(seconds=30),
                                  id=f'{rid}_startup', misfire_grace_time=600)
                break


def view(debug=False):
    """Every routine for the page: schedule, next run, state, last run, history, steps."""
    from app.services import bots
    from app.services.bots import status as bot_status
    from app.services.jobs import scheduler_state
    hist = history()
    nexts = next_runs()
    bot_states = bot_status.get_all()
    off = bots.disabled()
    sched = scheduler_state.scheduler
    now = datetime.now(timezone.utc)
    out = []
    for r in ROUTINES:
        on = is_enabled(r) and not (r.bot and r.bot in off)
        nxt = None
        if sched:
            job = sched.get_job(r.jid)
            if job and job.next_run_time:
                nxt = job.next_run_time.astimezone(timezone.utc).isoformat(timespec='seconds')
        if not nxt:
            nxt = nexts.get(r.jid)
            if nxt and nxt < now.isoformat():
                nxt = None
        if not nxt and on and not debug:
            try:
                trig = bot_trigger(r) if r.bot else build_trigger(r)
                t = trig.get_next_fire_time(None, now) if trig else None
                nxt = t.astimezone(timezone.utc).isoformat(timespec='seconds') if t else None
            except Exception:
                nxt = None
        if r.bot:
            e = bot_states.get(r.bot) or {}
            lr = e.get('last_run') or {}
            runs = [{'started_at': lr.get('started_at'), 'finished_at': lr.get('finished_at'), 'ok': lr.get('ok'),
                     'message': lr.get('message') or ''}] if lr else []
            running = e.get('state') == 'running'
        else:
            runs = hist.get(r.id) or []
            running = is_running(r.id)
        state = ('off' if not on else 'running' if running else
                 'bad' if runs and runs[0].get('ok') is False else 'ok' if runs else 'idle')
        out.append({
            'id': r.id, 'name': r.name, 'group': r.group, 'about': r.about, 'when': schedule_label(r),
            'bot': r.bot, 'can_run': r.can_run, 'enabled': on, 'next_run': None if debug else nxt,
            'running': running, 'state': state, 'runs': runs,
            'steps': [s.name for s in r.steps], 'marks': [list(m) for m in day_marks(r)],
        })
    return out
