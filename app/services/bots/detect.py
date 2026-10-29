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
