"""Background jobs: APScheduler cron/interval jobs plus the long-running daemon threads.

Started once per server by ``create_app()`` (``start_background_jobs(app)``). A file lock
(``app/log/.background_jobs.lock``) guarantees that only one process runs them when
gunicorn forks several workers; the others just serve HTTP.

With ``DEBUG=True`` every job and daemon thread is disabled — only the NIST spectral-line
cache warm-up still runs.

Job overview (times are UTC — ``BackgroundScheduler`` is created with ``timezone='UTC'``
so the schedule does not depend on the host's local timezone; the admin panel labels
these jobs in UTC too):

    daily_backup                   03:00      pg_dump -> app/data/backups/
    daily_phot_fetch               03:30      photometry for every Inbox object
    daily_detect_followups         04:00      DETECT re-screens every Follow-up object
    daily_target_mag_update        05:00      refresh obs.targets magnitudes
    daily_retire_stale_followups   05:30      Follow-up/Snoozed -> Finish
    daily_host_redshift_sync       06:00      host redshift -> transient.objects
    db_monitor                     every 10m  pool / pg_stat_activity check + email alert
    db_recycle                     every 30m  close idle pooled connections
    detect_page_prewarm            every 30m  rebuild DETECT page cache
    lsst_watch                     hh:25      new ALeRCE LSST objects vs Lens/DESI + LSST light curves of TNS objects
    lsst_daily_sweep               14:30      re-read the last 1.5 days of LSST objects (late ingests)

    bot_astronote                  every 5m   new TNS AstroNotes -> Slack
    bot_obs_log                    04:00      Lulin raw frames -> obs.logs (last 15 nights)
    bot_reduction                  REDUCTION_HOUR_UTC (unset: by hand only)  reduction pipeline

Daemon threads: ``auto_tns_download`` (hourly/daily TNS sync, real UTC clock),
``tns_gap_filler`` (hourly kinder_id gap fill), ``nist-spec-lines`` (one-shot),
``bot-gcn`` (GCN circulars + Einstein Probe alerts). The lab bots (app/services/bots) record their own state
for Admin › Bots instead of using ``_tracked``; BOTS_DISABLED switches single bots off.
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
            result = fn(*args, **kwargs)
        except Exception as _exc:
            _job_status.record_finish(job_id, False, str(_exc)[:200])
            raise
        # Several jobs report failure by returning {'error': ...} instead of raising.
        if isinstance(result, dict) and result.get('error'):
            _job_status.record_finish(job_id, False, str(result['error'])[:200])
        else:
            _job_status.record_finish(job_id, True)
        return result
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


# Scheduler jobs that are not named bot_<id> but belong to a bot of Admin › Bots (the page shows their next run)
_BOT_OF_JOB = {'daily_detect_followups': 'detect'}


def _add_bot_jobs(scheduler):
    """Lab bots on a schedule (app/services/bots); each records its own state for Admin › Bots."""
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

    from app.services import bots
    from app.services.bots import astronote, obs_log, reduction
    from app.services.bots import status as bot_status

    off = bots.disabled()
    if 'astronote' not in off:
        scheduler.add_job(astronote.run, 'interval', minutes=5, id='bot_astronote')
    if 'obs_log' not in off:
        scheduler.add_job(obs_log.run, 'cron', hour=4, minute=0, id='bot_obs_log')     # 12:00 UTC+8
    if 'reduction' not in off and reduction.hour_utc() is not None:
        scheduler.add_job(reduction.run, 'cron', hour=reduction.hour_utc(), minute=0, id='bot_reduction')

    def note_next_run(ev):
        bot_id = _BOT_OF_JOB.get(ev.job_id) or (ev.job_id[4:] if ev.job_id.startswith('bot_') else None)
        if bot_id:
            job = scheduler.get_job(ev.job_id)
            if job and job.next_run_time:
                bot_status.update(bot_id, next_run=job.next_run_time.isoformat(timespec='seconds'))
    scheduler.add_listener(note_next_run, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)


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
        bot_id = _BOT_OF_JOB.get(job.id) or (job.id[4:] if job.id.startswith('bot_') else None)
        if bot_id and job.next_run_time:
            bot_status.update(bot_id, next_run=job.next_run_time.isoformat(timespec='seconds'))
    if 'gcn' not in off:
        gcn.start()
    for bot_id in ('astronote', 'obs_log'):
        job = scheduler.get_job(f'bot_{bot_id}')
        if job:
            threading.Thread(target=job.func, name=f'startup-bot-{bot_id}', daemon=True).start()


def start_background_jobs(app) -> bool:
    """Register and start all background work. Returns True if this process owns them."""
    # The DETECT page cache lives with its blueprint; warming it is the one place a
    # background job reaches into app.blueprints.
    from app.blueprints.detect.cache import prewarm_detect_page_cache
    from app.db import recycle_idle_connections as _db_recycle
    from app.db.transient import sync_host_redshifts
    from app.services.astro.spectral_lines import warm_cache_async as _warm_spec_lines
    from app.services.detect import detect_pipeline as _detect_pipeline
    from app.services.jobs import scheduler_state as _sched_state
    from app.services.jobs.backup import run_daily_backup
    from app.services.jobs.db_monitor import check_and_alert as _db_check_and_alert
    from app.services.lsst import alerts as _lsst_alerts
    from app.services.photometry.phot_scheduler import (
        fetch_inbox_photometry,
        retire_stale_followups,
        update_target_mags,
    )
    from app.services.pipeline.autophot import cleanup_expired as _pipeline_cleanup
    from app.services.tns.auto_tns_download import start_auto_tns_downloader
    from app.services.tns.tns_gap_filler import start_gap_filler

    if not acquire_background_lock():
        print(f"[PID {os.getpid()}] Background jobs already running in another process, skipping.")
        return False

    log_dir = str(LOG_DIR)
    _scheduler = BackgroundScheduler(daemon=True, timezone='UTC')
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
        _scheduler.add_job(_tracked('pipeline_fits_cleanup', _pipeline_cleanup),              'interval', minutes=60,   id='pipeline_fits_cleanup')  # Pipeline FITS older than 7 days
        _scheduler.add_job(_tracked('detect_page_prewarm', prewarm_detect_page_cache),        'interval', minutes=30,   id='detect_page_prewarm', kwargs={'app_obj': app})  # needs the app: no request context in the scheduler thread
        if _detect_pipeline.ENABLED:
            # DETECT re-screens every Follow-up object once a day (M from the latest light
            # curve, host against the latest catalogue); hourly runs hang off the TNS import.
            _scheduler.add_job(_tracked('daily_detect_followups', _detect_pipeline.run_followups), 'cron', hour=4, minute=0, id='daily_detect_followups')  # after the 03:30 UTC photometry fetch
        if _lsst_alerts.ENABLED:
            # :25 = after the :15 TNS import, so new TNS names are there to link to
            _scheduler.add_job(_tracked('lsst_watch', _lsst_alerts.run_watch),                'cron', minute=25,        id='lsst_watch')
            _scheduler.add_job(_tracked('lsst_daily_sweep', _lsst_alerts.run_daily_sweep),    'cron', hour=14, minute=30, id='lsst_daily_sweep')  # Chilean night is over by ~11 UTC
        _add_bot_jobs(_scheduler)
    _scheduler.start()
    if not config.DEBUG:
        # Start-up backup runs in the background so the server accepts requests immediately
        # (pg_dump can take minutes).
        threading.Thread(target=_tracked('daily_backup', run_daily_backup), name='startup-backup', daemon=True).start()
        _tracked('detect_page_prewarm', prewarm_detect_page_cache)(prewarm_days=1, refresh_latest=True, force_latest=True, app_obj=app)
        start_auto_tns_downloader(log_dir=log_dir)
        start_gap_filler(log_dir=log_dir)
        _start_bots(_scheduler)
    else:
        print("DEBUG mode: all background scheduled jobs are disabled.")
    # Warm NIST spectral-line cache regardless of DEBUG mode
    _warm_spec_lines()
    return True
