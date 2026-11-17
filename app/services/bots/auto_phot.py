"""Auto photometry bot: last night's calibrated Lulin frames → AutoPhOT → Daily Trigger page and Transient pages.

``run()`` daily 05:30 UTC (13:30 UTC+8, after the reduction pipeline has calibrated the night) and "Run now":
measures every target of the last BACKFILL_NIGHTS nights that is not done yet (app/services/auto_phot.py).
"""
from datetime import timedelta

from . import status

BOT = 'auto_phot'
log = status.get_logger(BOT)
BACKFILL_NIGHTS = 3


def setup_problem():
    try:
        from app.services import auto_phot
        auto_phot.calibrated_root()
    except Exception as e:
        return str(e)
    try:
        from app.services.pipeline import config
        bad = [c['detail'] for c in config.check(probe_python=False) if not c['ok']]
        if bad:
            return 'Pipeline (AutoPhOT) is not set up: ' + '; '.join(bad)
    except Exception as e:
        return f'Pipeline check failed: {e}'
    return ''


def _stop():
    return bool((status.get_all().get(BOT) or {}).get('stop_requested'))


def _run(nights=BACKFILL_NIGHTS):
    from app.services import auto_phot
    problem = setup_problem()
    if problem:
        status.update(BOT, detail={'setup': problem})
        raise RuntimeError(problem)
    status.update(BOT, stop_requested=False)
    last = auto_phot.last_night()
    lines = []
    for back in range(nights - 1, -1, -1):                       # old → new
        night = last - timedelta(days=back)
        line = auto_phot.run_night(night, stop=_stop)
        log.info(line)
        lines.append(line)
        if _stop():
            lines.append('Stopped.')
            break
    status.update(BOT, detail={'nights': lines[::-1]})
    return lines[-1] if lines else 'Nothing to do.'


def run(nights=BACKFILL_NIGHTS):
    return status.guarded_run(BOT, _run, nights)


def stop():
    e = status.get_all().get(BOT) or {}
    if e.get('state') != 'running':
        return {'error': 'Not running.'}
    status.update(BOT, stop_requested=True)
    return {'ok': True, 'message': 'Stopping after the current target…'}
