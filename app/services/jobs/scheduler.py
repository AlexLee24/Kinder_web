"""Background jobs: APScheduler cron/interval jobs plus the long-running daemon threads.

Started once per server by ``create_app()`` (``start_background_jobs(app)``). A file lock
(``app/log/.background_jobs.lock``) guarantees that only one process runs them when
gunicorn forks several workers; the others just serve HTTP.

With ``DEBUG=True`` every job and daemon thread is disabled — only the NIST spectral-line
cache warm-up still runs.

Job overview (times are in the scheduler's timezone, i.e. the host's local timezone —
``BackgroundScheduler`` is created without an explicit ``timezone``):

    daily_backup                   03:00      pg_dump -> app/data/backups/
    daily_phot_fetch               03:30      photometry for every Inbox object
    daily_detect_followups         04:00      DETECT re-screens every Follow-up object
    daily_target_mag_update        05:00      refresh obs.targets magnitudes
    daily_retire_stale_followups   05:30      Follow-up/Snoozed -> Finish
    daily_host_redshift_sync       06:00      host redshift -> transient.objects
    db_monitor                     every 10m  pool / pg_stat_activity check + email alert
    db_recycle                     every 30m  close idle pooled connections
    detect_page_prewarm            every 30m  rebuild DETECT page cache

Daemon threads: ``auto_tns_download`` (hourly/daily TNS sync, real UTC clock),
``tns_gap_filler`` (hourly kinder_id gap fill), ``nist-spec-lines`` (one-shot).
Every job is wrapped by ``_tracked`` so its last run is visible in the admin panel via
``app.services.jobs.job_status``.
"""
import fcntl
import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import config
from app.paths import LOG_DIR

logger = logging.getLogger(__name__)

_bg_lock_fd = None  # keep the fd alive for the lifetime of the process (holds the lock)


def _tracked(job_id, fn):
    from app.services.jobs import job_status as _job_status

    def wrapper(*args, **kwargs):
        _job_status.record_start(job_id)
        try:
            fn(*args, **kwargs)
            _job_status.record_finish(job_id, True)
        except Exception as _exc:
            _job_status.record_finish(job_id, False, str(_exc)[:200])
            raise
    wrapper.__name__ = fn.__name__
    return wrapper


def acquire_background_lock() -> bool:
    """Try to become the process that owns the background jobs (non-blocking file lock)."""
    global _bg_lock_fd
    os.makedirs(LOG_DIR, exist_ok=True)
    _bg_lock_fd = open(os.path.join(LOG_DIR, '.background_jobs.lock'), 'w')
    try:
        fcntl.flock(_bg_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def start_background_jobs(app) -> bool:
    """Register and start all background work. Returns True if this process owns them."""
    from app.services.jobs.backup import run_daily_backup
    from app.services.photometry.phot_scheduler import fetch_inbox_photometry, update_target_mags, retire_stale_followups
    # from app.services.notifications.gcn_alert import start_gcn_listener  # reserved for future use
    from app.services.tns.auto_tns_download import start_auto_tns_downloader
    from app.services.detect import detect_pipeline as _detect_pipeline
    from app.services.tns.tns_gap_filler import start_gap_filler
    from app.services.jobs.db_monitor import check_and_alert as _db_check_and_alert
    from app.db import recycle_idle_connections as _db_recycle
    from app.db.transient import sync_host_redshifts
    # The DETECT page cache lives with its blueprint; warming it is the one place a
    # background job reaches into app.blueprints.
    from app.blueprints.detect.cache import prewarm_detect_page_cache
    from app.services.astro.spectral_lines import warm_cache_async as _warm_spec_lines
    from app.services.jobs import scheduler_state as _sched_state

    if not acquire_background_lock():
        print(f"[PID {os.getpid()}] Background jobs already running in another process, skipping.")
        return False

    log_dir = str(LOG_DIR)
    _scheduler = BackgroundScheduler(daemon=True)
    _sched_state.scheduler = _scheduler
    if not config.DEBUG:
        _scheduler.add_job(_tracked('daily_backup', run_daily_backup),                        'cron', hour=3, minute=0,  id='daily_backup')
        _scheduler.add_job(_tracked('daily_phot_fetch', fetch_inbox_photometry),              'cron', hour=3, minute=30, id='daily_phot_fetch')
        # _scheduler.add_job(fetch_missing_photometry, 'cron', minute=0,                      id='hourly_missing_phot')
        _scheduler.add_job(_tracked('daily_target_mag_update', update_target_mags),           'cron', hour=5, minute=0,  id='daily_target_mag_update')
        _scheduler.add_job(_tracked('daily_retire_stale_followups', retire_stale_followups),  'cron', hour=5, minute=30, id='daily_retire_stale_followups')
        _scheduler.add_job(_tracked('daily_host_redshift_sync', sync_host_redshifts),         'cron', hour=6, minute=0,  id='daily_host_redshift_sync')
        _scheduler.add_job(_tracked('db_monitor', _db_check_and_alert),                       'interval', minutes=10,   id='db_monitor')
        _scheduler.add_job(_tracked('db_recycle', _db_recycle),                               'interval', minutes=30,   id='db_recycle')
        _scheduler.add_job(_tracked('detect_page_prewarm', prewarm_detect_page_cache),        'interval', minutes=30,   id='detect_page_prewarm', kwargs={'app_obj': app})  # needs the app: no request context in the scheduler thread
        if _detect_pipeline.ENABLED:
            # DETECT re-screens every Follow-up object once a day (M from the latest light
            # curve, host against the latest catalogue); hourly runs hang off the TNS import.
            _scheduler.add_job(_tracked('daily_detect_followups', _detect_pipeline.run_followups), 'cron', hour=4, minute=0, id='daily_detect_followups')  # after the 03:30 UTC photometry fetch
    _scheduler.start()
    if not config.DEBUG:
        # Start-up backup runs in the background so the server accepts requests immediately
        # (pg_dump can take minutes).
        threading.Thread(target=_tracked('daily_backup', run_daily_backup), name='startup-backup', daemon=True).start()
        _tracked('detect_page_prewarm', prewarm_detect_page_cache)(prewarm_days=1, refresh_latest=True, force_latest=True, app_obj=app)
        # start_gcn_listener(log_dir=log_dir)
        start_auto_tns_downloader(log_dir=log_dir)
        start_gap_filler(log_dir=log_dir)
    else:
        print("DEBUG mode: all background scheduled jobs are disabled.")
    # Warm NIST spectral-line cache regardless of DEBUG mode
    _warm_spec_lines()
    return True
