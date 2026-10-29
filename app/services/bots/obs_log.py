"""Observation-log bot: Lulin raw frames → obs.logs (was lab_bot check_observe.py).

``run()`` (daily 04:00 UTC = 12:00 UTC+8, and "Run now") rescans the last BACKFILL_DAYS nights in the synced raw
folder, read only:

    <raw dir>/SLT<yyyymmdd>*/{janet,bias-dark,flat}/*.fits|*.fts      (and LOT…)

and for each (target, telescope) of a night counts frames per (FILTER, EXPTIME) from the FITS headers. The target
is the file name before the first '-'. Each one is written as an "observed" row of obs.logs, matched by
(name, date, telescope): an existing row only gets observed = TRUE and its observed filters / counts / times, so a
trigger someone entered is never touched; a new row is inserted with target_id NULL (as lab_bot did).

Raw folder: OBS_RAW_DIR, else <reduction pipeline>/RAW_IMG_Sync/home/janet/lulin_data.
"""
import glob
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import status

BOT = 'obs_log'
log = status.get_logger(BOT)

BACKFILL_DAYS = 15
TELESCOPES = (('[sS][lL][tT]', 'SLT'), ('[lL][oO][tT]', 'LOT'))
SUBFOLDERS = ('janet', 'bias-dark', 'flat')     # science, calibration
VALID_PRIORITIES = {'Urgent', 'High', 'Normal', 'Filler'}
_TZ8 = timezone(timedelta(hours=8))


def raw_dir():
    env = (os.environ.get('OBS_RAW_DIR') or '').strip()
    if env:
        return Path(env).expanduser()
    from app.services.system.monitor import reduction_root
    root = reduction_root()
    return root / 'RAW_IMG_Sync' / 'home' / 'janet' / 'lulin_data' if root else None


def scan_night(base, night):
    """[{'target', 'telescope', 'observations': [{'filter', 'exp', 'count'}]}] for one night (a date)."""
    from astropy.io import fits

    ymd = night.strftime('%Y%m%d')
    summary = {}
    for pattern, tel in TELESCOPES:
        for folder in glob.glob(os.path.join(base, f'{pattern}{ymd}*')):
            for sub in SUBFOLDERS:
                path = os.path.join(folder, sub)
                if not os.path.isdir(path):
                    continue
                for fp in glob.glob(os.path.join(path, '*.fits')) + glob.glob(os.path.join(path, '*.fts')):
                    try:
                        with fits.open(fp) as hdul:
                            fil = hdul[0].header.get('FILTER', 'Unknown')
                            exp = hdul[0].header.get('EXPTIME', 'Unknown')
                        if isinstance(fil, str) and '_' in fil:
                            fil = fil.split('_')[0]
                        exp = int(exp) if isinstance(exp, (int, float)) else exp
                    except Exception:
                        fil = exp = 'Error'
                    target = os.path.basename(fp).replace('.fits', '').replace('.fts', '').split('-')[0]
                    key = summary.setdefault((target, tel), {})
                    key[(fil, exp)] = key.get((fil, exp), 0) + 1
    return [{'target': t, 'telescope': tel,
             'observations': [{'filter': f, 'exp': e, 'count': c} for (f, e), c in obs.items()]}
            for (t, tel), obs in summary.items()]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def save_observed(cur, night, row):
    """Mark one target observed on that night (only the observed_* fields of an existing row change)."""
    obs = sorted(row['observations'], key=lambda o: (str(o['filter']), str(o['exp'])))
    o_filter = [str(o['filter']) for o in obs]
    o_count = [_int(o['count']) for o in obs]
    o_time = [_int(o['exp']) for o in obs]
    date = night.isoformat()
    cur.execute('SELECT log_id FROM obs.logs WHERE name = %s AND date = %s AND telescope = %s LIMIT 1',
                (row['target'], date, row['telescope']))
    found = cur.fetchone()
    if found:
        cur.execute('UPDATE obs.logs SET observed = TRUE, observed_filter = %s, observed_count = %s, observed_time = %s '
                    'WHERE log_id = %s', (o_filter, o_count, o_time, found[0]))
        return 'updated'
    cur.execute("INSERT INTO obs.logs (target_id, date, name, telescope, program, priority, repeat, trigger_by, trigger, "
                " observed, trigger_filter, trigger_count, trigger_time, observed_filter, observed_count, observed_time) "
                "VALUES (NULL, %s, %s, %s, '', 'Normal', 0, NULL, FALSE, TRUE, '{}', '{}', '{}', %s, %s, %s)",
                (date, row['target'], row['telescope'], o_filter, o_count, o_time))
    return 'added'


def _scan(days=BACKFILL_DAYS):
    base = raw_dir()
    if not base or not base.is_dir():
        problem = f'Raw frame folder not found: {base or "(not set)"} — set OBS_RAW_DIR or REDUCTION_PIPELINE_DIR.'
        status.update(BOT, detail={'setup': problem})
        raise RuntimeError(problem)
    from app.db import get_db_connection

    today = datetime.now(_TZ8).date()
    nights, added, updated = [], 0, 0
    for back in range(days - 1, -1, -1):                     # old → new
        night = today - timedelta(days=back)
        rows = scan_night(str(base), night)
        if not rows:
            continue
        with get_db_connection() as conn:
            cur = conn.cursor()
            for row in rows:
                if save_observed(cur, night, row) == 'added':
                    added += 1
                else:
                    updated += 1
            conn.commit()
        frames = sum(o['count'] for r in rows for o in r['observations'])
        nights.append({'night': night.isoformat(), 'targets': len(rows), 'frames': frames,
                       'telescopes': sorted({r['telescope'] for r in rows})})
        log.info('%s: %d targets, %d frames (%s)', night, len(rows), frames,
                 ', '.join(f"{r['target']}/{r['telescope']}" for r in rows))
    status.update(BOT, detail={'raw_dir': str(base), 'nights': nights[::-1]})
    if added:
        status.event(BOT, f'{added} new observation log rows ({len(nights)} nights with data)')
    return f'{len(nights)} of the last {days} nights have frames: {added} rows added, {updated} refreshed.'


def run(days=BACKFILL_DAYS):
    return status.guarded_run(BOT, _scan, days)
