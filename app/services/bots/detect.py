"""DETECT bot: what the embedded DETECT pipeline (services/detect/detect_pipeline.py) did, for Admin › Bots.

DETECT is not scheduled here: its runs come from the hourly TNS import, the daily 04:00 UTC Follow-up re-screen
(services/jobs/scheduler.py), the admin buttons and the object page. detect_pipeline calls ``started`` and ``finished``
around every run, whatever started it, so the bot's state, events and log cover all of them.
"""
import os

from . import status

BOT = 'detect'
log = status.get_logger(BOT)


def setup_problem():
    """What is missing for DETECT to run at all ('' when fine). The SFD dust maps are fetched on first use, so not a problem."""
    from app.services.detect import detect_pipeline as dp
    if not dp.ENABLED:
        return 'DETECT is switched off in this instance (DETECT_IN_WEB=0 in kinder.env).'
    if not os.path.isdir(os.path.join(dp.DETECT_DIR, 'function')):
        return f'DETECT code not found in {dp.DETECT_DIR} (scripts/sync_detect.sh).'
    return ''


def _counts_text(counts):
    return ' · '.join(f'{v} {k}' for k, v in (counts or {}).items())


def started(label, n=None):
    status.run_started(BOT)
    log.info('── %s: started%s', label, f' ({n} objects)' if n else '')


def finished(label, ok, counts=None, seconds=None, error=''):
    """Record how a run ended: state, last run, one event (what it found, or why it failed) and the log."""
    took = f' in {seconds:g} s' if seconds is not None else ''
    if ok:
        text = f'{label}: {_counts_text(counts) or "done"}{took}'
        status.run_finished(BOT, True, text)
        status.event(BOT, text)
    else:
        text = f'{label} failed: {error or "see the server log"}'
        status.run_finished(BOT, False, text)
        status.event(BOT, text, level='error')


def overview():
    """What the DB and the code say about DETECT (the Overview tab): the same as detect_pipeline.status()."""
    from app.services.detect import detect_pipeline as dp
    return dp.status()


# ── TNS-DETECT and LSST-DETECT on the bot card ──────────────────────────────
# Each TNS-DETECT trigger: (job_status id written by detect_pipeline._Run, name, UTC hours or None for every hour, minutes)
TNS_RUNS = (
    ('detect_tns_hourly', 'TNS hourly import', None, (15, 45)),     # auto_tns_download._HOURLY_MINUTES
    ('detect_tns_daily', 'TNS daily import', (1, 4, 12), (0,)),     # auto_tns_download._DAILY_HOURS
    ('detect_follow_up', 'Follow-up re-screen', (4,), (0,)),        # scheduler: daily_detect_followups
)
LSST_HOURLY = (None, (25,))         # scheduler: lsst_watch
LSST_SWEEP = ((14,), (30,))         # scheduler: lsst_daily_sweep
LSST_STALE_HOURS = 30               # no new LSST object at ALeRCE for this long: a whole night is missing


def _next_slot(now, hours, minutes):
    """First UTC time after ``now`` at one of ``minutes`` past one of ``hours`` (None: every hour)."""
    from datetime import timedelta
    base = now.replace(minute=0, second=0, microsecond=0)
    for h in range(49):
        t0 = base + timedelta(hours=h)
        if hours is not None and t0.hour not in hours:
            continue
        for m in sorted(minutes):
            if t0.replace(minute=m) > now:
                return t0.replace(minute=m).isoformat(timespec='seconds')
    return None


def _iso_ts(ts):
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec='seconds')
    except (TypeError, ValueError):
        return None


def _iso_mjd(mjd):
    from datetime import datetime, timedelta, timezone
    try:
        return (datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=float(mjd))).isoformat(timespec='seconds')
    except (TypeError, ValueError):
        return None


def _tns(now):
    from app.services.jobs import job_status
    jobs = job_status.get_all()
    runs = []
    for job_id, name, hours, minutes in TNS_RUNS:
        rec = jobs.get(job_id) or {}
        runs.append({'name': name, 'started_at': rec.get('started_at'), 'finished_at': rec.get('finished_at'),
                     'ok': rec.get('status') != 'error' if rec.get('status') else None,
                     'message': rec.get('message') or '', 'next_run': _next_slot(now, hours, minutes)})
    return {'runs': runs}


def _lsst(now):
    import json

    from app.db.auth import get_settings
    from app.services.lsst import alerts
    s = get_settings((alerts.STATUS_KEY, alerts.LAST_RUN_KEY, alerts.CURSOR_KEY))
    try:
        st = json.loads(s.get(alerts.STATUS_KEY) or 'null') or {}
    except ValueError:
        st = {}
    try:
        last = json.loads(s.get(alerts.LAST_RUN_KEY) or 'null') or {}
    except ValueError:
        last = {}
    try:
        running = alerts.is_running()
    except OSError:                             # no data folder for the lock file yet: nothing ever ran here
        running = False
    state = st.get('state')
    if state == 'running' and not running:
        state = 'interrupted'                   # the process died mid-run (restart / deploy)
    error = next((ln.split('FAILED:', 1)[1].strip() for ln in reversed(st.get('log') or []) if 'FAILED:' in ln), '')
    window = last.get('window') or []
    newest = _iso_mjd(s.get(alerts.CURSOR_KEY))
    stale_h = None
    if newest:
        from datetime import datetime
        stale_h = round((now - datetime.fromisoformat(newest)).total_seconds() / 3600, 1)
    return {
        'enabled': alerts.ENABLED,
        'state': state, 'phase': st.get('phase'), 'trigger': st.get('trigger'),
        'started_at': _iso_ts(st.get('started_at')), 'finished_at': _iso_ts(st.get('finished_at')),
        'error': error if state == 'error' else '',
        'last_ok': {
            'at': _iso_ts(last.get('at')), 'trigger': last.get('trigger'), 'seconds': last.get('seconds'),
            'window': [_iso_mjd(w) for w in window[:2]],
            'fetched': last.get('fetched'), 'by_class': last.get('by_class') or {},
            'lens': last.get('lens'), 'desi': last.get('desi'), 'stored': last.get('stored'),
            'linked': last.get('linked'), 'relinked': last.get('relinked'),
            'detect': last.get('detect') or {}, 'lc': last.get('lc') or {},
        } if last else None,
        'newest_alert_at': newest, 'stale_hours': stale_h, 'stale': stale_h is not None and stale_h > LSST_STALE_HOURS,
        'next_hourly': _next_slot(now, *LSST_HOURLY), 'next_sweep': _next_slot(now, *LSST_SWEEP),
    }


def sources():
    """What the card shows for each half of DETECT: the TNS-DETECT triggers (last run, next run) and the
    LSST-DETECT watch (last run, what ALeRCE returned, how new its newest object is, next runs)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = {}
    for key, fn in (('tns', _tns), ('lsst', _lsst)):
        try:
            out[key] = fn(now)
        except Exception as e:                  # the card still renders the other half
            log.warning('DETECT card: %s status unavailable: %s', key, e)
            out[key] = {'unavailable': f'{type(e).__name__}: {e}'[:200]}
    return out
