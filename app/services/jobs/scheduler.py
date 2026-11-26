"""Background jobs: the routines (APScheduler) plus the GCN listener thread.

Started once per server by ``create_app()`` (``start_background_jobs(app)``). A file lock
(``app/log/.background_jobs.lock``) guarantees that only one process runs them when
gunicorn forks several workers; the others serve HTTP and stand by: they retry the lock
every STANDBY_EVERY seconds, so when the owner stops (killed, recycled, an old worker
outliving a restart) another worker takes the jobs and the bots over at once. A gunicorn
worker exits at most EXIT_GRACE seconds after SIGTERM or after its master dies, so a
restart never leaves an old worker holding the lock.

With ``DEBUG=True`` every job and daemon thread is disabled — only the NIST spectral-line
cache warm-up still runs.

Every scheduled job is a routine in ``app.services.jobs.routines.ROUTINES`` (schedule, steps, the admin page's
Admin › Routines): this module only registers them and runs the start-up work. Triggers are UTC
(``BackgroundScheduler(timezone='UTC')``); the page shows every time as ``12:00 UTC+8 (04:00 UTC+0)``.

Start-up (this process holds the lock, not DEBUG): today's backup when there is none yet, the Lulin calendar when the
last sync is over 6 h old, the DETECT page cache, a TNS import whose slot passed less than 10 min ago, the GCN
listener, a first AstroNote poll and the observation-log backfill, and auto photometry of last night 3 min later.
BOTS_DISABLED switches single bots off; LSST_WATCH=0 the LSST routines.
"""
import fcntl
import logging
import os
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import config
from app.paths import LOG_DIR

logger = logging.getLogger(__name__)

_bg_lock_fd = None  # keep the fd alive for the lifetime of the process (holds the lock)


def acquire_background_lock() -> bool:
    """Try to become the process that owns the background jobs (non-blocking file lock)."""
    global _bg_lock_fd
    os.makedirs(LOG_DIR, exist_ok=True)
    fh = open(os.path.join(LOG_DIR, '.background_jobs.lock'), 'w')
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()          # standby workers try again every STANDBY_EVERY s: do not leak a descriptor each time
        return False
    _bg_lock_fd = fh
    return True


STANDBY_EVERY = 15      # seconds between a standby worker's attempts to take the background jobs over
EXIT_GRACE = 10         # seconds a gunicorn worker may take to exit after SIGTERM / SIGINT / SIGQUIT


def _take_over_when_free(app):
    """Standby: every worker that lost the start-up race keeps trying the lock. When the owner stops (its worker
    exits, is killed or recycled, or an old worker from before a restart finally ends) one of them takes the jobs
    and the bots over within STANDBY_EVERY seconds, so they never stay down until the next restart."""
    while True:
        time.sleep(STANDBY_EVERY)
        try:
            if acquire_background_lock():
                logger.warning("[PID %s] Background jobs: the previous owner stopped, taking over", os.getpid())
                print(f"[PID {os.getpid()}] Background jobs: the previous owner stopped, taking over.")
                _run_background_jobs(app)
                return
        except Exception:
            logger.exception("Background jobs: take-over failed, trying again")


def _exit_in(seconds):
    t = threading.Timer(seconds, os._exit, args=(0,))
    t.daemon = True
    t.start()


def _exit_when_orphaned(ppid):
    """The master died without stopping this worker (SIGKILL, crash): gunicorn's worker notices and returns, but
    Python then waits for the scheduler's threads. Make sure it is gone EXIT_GRACE s later."""
    while os.getppid() == ppid:
        time.sleep(1)
    _exit_in(EXIT_GRACE)


def exit_soon_after_sigterm():
    """In a gunicorn worker: exit for sure EXIT_GRACE s after SIGTERM / SIGINT / SIGQUIT or after the master dies.

    gunicorn's own handler lets the worker finish, but Python then waits for every non-daemon thread (a scheduler
    job can run for an hour), and launchd SIGKILLs the master after its ExitTimeOut: the orphaned worker went on
    holding the background-jobs lock (and the bots) long after a restart. Only wraps gunicorn's handlers, so the
    Flask dev server and tests are untouched; must run in the main thread (create_app in the worker)."""
    import signal
    if threading.current_thread() is not threading.main_thread():
        return
    wrapped = False
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        prev = signal.getsignal(sig)
        if not callable(prev) or not str(getattr(prev, '__module__', '')).startswith('gunicorn'):
            continue

        def handler(signum, frame, prev=prev):
            _exit_in(EXIT_GRACE)
            prev(signum, frame)
        signal.signal(sig, handler)
        wrapped = True
    if wrapped:
        threading.Thread(target=_exit_when_orphaned, args=(os.getppid(),), name='exit-when-orphaned', daemon=True).start()


# Scheduler jobs that are not named bot_<id> but belong to a bot of Admin › Bots (the page shows their next run)
_BOT_OF_JOB = {'morning_chain': 'detect'}


def _bot_of(job_id):
    return _BOT_OF_JOB.get(job_id) or (job_id[4:] if job_id.startswith('bot_') else None)


def _watch_runs(scheduler):
    """After every run: the bot's next run for Admin › Bots and every job's next run for Admin › Routines (both are
    read by any gunicorn worker, the scheduler only lives in this one)."""
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

    from app.services.bots import status as bot_status
    from app.services.jobs import routines

    def on_event(ev):
        bot_id = _bot_of(ev.job_id)
        if bot_id:
            job = scheduler.get_job(ev.job_id)
            if job and job.next_run_time:
                bot_status.update(bot_id, next_run=job.next_run_time.isoformat(timespec='seconds'))
        routines.save_next_runs(scheduler)
    scheduler.add_listener(on_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)


def _start_bots(scheduler):
    """After the scheduler starts: the GCN listener, a first AstroNote poll and the observation-log backfill
    (as lab_bot did on start), and each scheduled bot's next run time for the page."""
    from app.services import bots
    from app.services.bots import gcn
    from app.services.bots import status as bot_status

    off = bots.disabled()
    for bot_id in off:
        bot_status.update(bot_id, state='disabled')
    for job in scheduler.get_jobs():
        bot_id = _bot_of(job.id)
        if bot_id and job.next_run_time:
            bot_status.update(bot_id, next_run=job.next_run_time.isoformat(timespec='seconds'))
    if 'gcn' not in off:
        gcn.start()
    for bot_id in ('astronote', 'obs_log'):
        job = scheduler.get_job(f'bot_{bot_id}')
        if job:
            threading.Thread(target=job.func, name=f'startup-bot-{bot_id}', daemon=True).start()
    if 'auto_phot' not in off:
        # a few minutes after every start (a deploy, a restart): last night's targets that are not done yet.
        # Already measured ones are skipped, so restarting again costs nothing.
        from datetime import datetime, timedelta, timezone

        from app.services.bots import auto_phot
        scheduler.add_job(auto_phot.run, 'date', run_date=datetime.now(timezone.utc) + timedelta(minutes=3),
                          kwargs={'nights': 1}, id='auto_phot_startup', misfire_grace_time=3600)


def start_background_jobs(app) -> bool:
    """Start all background work if this process wins the lock (returns True); otherwise stand by to take it over."""
    exit_soon_after_sigterm()
    if not acquire_background_lock():
        print(f"[PID {os.getpid()}] Background jobs already running in another process, standing by.")
        threading.Thread(target=_take_over_when_free, args=(app,), name='background-jobs-standby', daemon=True).start()
        return False
    _run_background_jobs(app)
    return True


def _run_background_jobs(app):
    """Register and start all background work (this process holds the lock)."""
    from apscheduler.executors.pool import ThreadPoolExecutor

    from app.services.astro.spectral_lines import warm_cache_async as _warm_spec_lines
    from app.services.jobs import routines
    from app.services.jobs import scheduler_state as _sched_state

    # Long routines (gap filler, AutoPhOT, TNS daily, the morning chain) must not hold up the 1-minute ones.
    _scheduler = BackgroundScheduler(daemon=True, timezone='UTC', executors={'default': ThreadPoolExecutor(20)})
    _sched_state.scheduler = _scheduler
    if not config.DEBUG:
        added = routines.register(_scheduler, app)
        routines.tns_startup_catch_up(_scheduler)
        _watch_runs(_scheduler)
        logger.info('Routines scheduled: %s', ', '.join(added))
    _scheduler.start()
    if not config.DEBUG:
        routines.save_next_runs(_scheduler)
        from app.services.lab_calendar import sync_lulin_if_stale
        # pg_dump skips a database that already has today's file, so a restart costs nothing; it runs in a thread
        # so the server accepts requests immediately.
        threading.Thread(target=routines.run, args=('daily_backup',), name='startup-backup', daemon=True).start()
        sync_lulin_if_stale(max_age_hours=6)
        routines.prewarm_detect_page()
        _start_bots(_scheduler)
    else:
        print("DEBUG mode: all background scheduled jobs are disabled.")
    # Warm NIST spectral-line cache regardless of DEBUG mode
    _warm_spec_lines()
