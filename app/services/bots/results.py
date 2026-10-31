"""What the lab bots produced, for Lab › Bots (/bots, private area). The reduction pipeline has its own page.

    gcn         the newest GCN circulars and Einstein Probe alerts (app/data/gcn.json, ep.json)
    astronote   the AstroNotes posted to Slack (app/data/bots/astronotes_posted.json)
    obs_log     the nights of the last run (status detail) and the observed rows of obs.logs for those nights
"""
import json
from datetime import datetime, timedelta, timezone

PAGE_BOTS = ('gcn', 'astronote', 'obs_log')
CALIBRATION = {'AUTOFLAT', 'BIAS', 'DARK'}      # as on Daily Trigger: listed after the science targets


def is_calibration(name):
    n = str(name or '').strip().upper()
    return n in CALIBRATION or n.endswith('FLAT')


def view(debug=False):
    """status.view for the bots on the page, without the admin-only parts (pid, log)."""
    from . import setup_problems, status
    keep = ('id', 'name', 'kind', 'schedule', 'about', 'health', 'health_label', 'heartbeat_at', 'started_at',
            'last_run', 'last_event', 'last_error', 'next_run', 'events', 'today')
    out = []
    for b in status.view(debug=debug, setup=setup_problems()):
        if b['id'] in PAGE_BOTS:
            row = {k: b.get(k) for k in keep}
            row['setup'] = (b.get('detail') or {}).get('setup') or ''
            out.append(row)
    return out


def _load(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def gcn():
    from . import robot
    from .gcn import EP_JSON, GCN_JSON
    circulars = [{'id': c.get('circularId'), 'subject': c.get('subject') or '', 'received_at': c.get('received_at'),
                  'text': c.get('text') or ''} for c in reversed(_load(GCN_JSON))]
    error = ''
    try:                                          # robot alerts (obs.robot_alerts): ids, status, visibility
        from app.db.robot import recent_alerts
        now = datetime.now(timezone.utc)
        ep = [dict(robot._public(a, now), status_by=a.get('status_by'), status_at=a.get('status_at'))
              for a in recent_alerts(20)]
    except Exception as e:                        # the DB is down: the bot's own file, without ids
        error = f'Robot alerts unavailable: {type(e).__name__}'
        ep = [{'name': e.get('object_name'), 'ra': e.get('ra'), 'dec': e.get('dec'), 'trigger_time': e.get('trigger_time'),
               'created_at': e.get('received_at'), 'script': e.get('script')} for e in reversed(_load(EP_JSON))]
    clients = [dict(c, ip=ip) for ip, c in robot.clients()]
    return {'circulars': circulars, 'ep': ep, 'robot_clients': clients, 'error': error}


def astronote():
    from .astronote import load_posted
    return {'notes': load_posted()}


def obs_log():
    from . import status
    from .obs_log import _TZ8, BACKFILL_DAYS
    detail = (status.get_all().get('obs_log') or {}).get('detail') or {}
    since = datetime.now(_TZ8).date() - timedelta(days=BACKFILL_DAYS - 1)
    rows, error = [], ''
    try:
        from app.db.obs import get_observed_since
        rows = get_observed_since(since)
    except Exception as e:  # the page still shows the run's nights
        error = f'Observation log unavailable: {type(e).__name__}'
    by_night = {}
    for r in rows:
        by_night.setdefault(r['date'], []).append({
            'name': r.get('target_name') or r.get('name'), 'telescope': r.get('telescope'),
            'calibration': is_calibration(r.get('target_name') or r.get('name')),
            'frames': [{'filter': f.get('filter'), 'exp': f.get('exp'), 'count': f.get('count')} for f in r.get('observed_filters') or []],
        })
    for targets in by_night.values():
        targets.sort(key=lambda t: t['calibration'])   # stable: science first, in the query's order
    runs = {n.get('night'): n for n in detail.get('nights') or []}
    nights = []
    for night in sorted(set(by_night) | set(runs), reverse=True):
        run = runs.get(night) or {}
        nights.append({'night': night, 'targets': by_night.get(night, []), 'frames': run.get('frames'),
                       'telescopes': run.get('telescopes') or sorted({t['telescope'] for t in by_night.get(night, []) if t['telescope']})})
    return {'days': BACKFILL_DAYS, 'nights': nights, 'error': error}


RESULTS = {'gcn': gcn, 'astronote': astronote, 'obs_log': obs_log}
