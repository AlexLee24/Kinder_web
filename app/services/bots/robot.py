"""Alerts for the Lulin observing robot: stored in obs.robot_alerts (app/db/robot.py), served by one keyless,
read-only endpoint, GET /api/v1/robot/alert (astronomy_tools/robot_api.py).

The endpoint shows at most ONE alert: the newest one that is active (not cancelled on Triggers › Alerts) and not
expired, with its ACP script; ``alert`` is null when there is none. The robot remembers the id it last ran and runs an
alert only when its id is LARGER (ids only grow): a repeated poll never runs an alert twice, and when the newest alert
is cancelled and an older one shows again, that older one is not run a second time. If the id it is running
disappears (cancelled or expired) it can stop.
Each alert also says whether it rises above MIN_ALT during tonight's dark time at Lulin (``observable_tonight``);
the robot decides what to do with that.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from . import status

MIN_ALT = 30.0              # degrees, during astronomical darkness
EXPIRES_AFTER = timedelta(hours=24)
MAX_CLIENTS = 10            # robot clients remembered for Triggers › Alerts
LULIN = ('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)


def visibility_tonight(name, ra, dec, now=None):
    """{'max_alt', 'moon_sep', 'observable'} for the rest of tonight's astronomical darkness at Lulin (the trigger
    night, which turns over at 08:00 UTC+8). None values when it cannot be computed."""
    import ephem
    import numpy as np

    from app.services.planning import obsplan as obs
    from app.services.planning.trigger_send import _TAIPEI, _trigger_day_key

    now = now or datetime.now(timezone.utc)
    observer = obs.create_ephem_observer(*LULIN)
    target = obs.create_ephem_target(name, ra, dec)
    day = datetime.strptime(_trigger_day_key(now.astimezone(_TAIPEI)), '%Y-%m-%d')
    midnight_utc = day + timedelta(hours=16)               # 00:00 UTC+8 after that evening
    _, _, _, astro = obs.calculate_twilight_times(observer, ephem.Date(midnight_utc))
    start = max(float(astro[0]), float(ephem.Date(now.replace(tzinfo=None))))
    end = float(astro[1])
    if start >= end:                                       # tonight's darkness is over
        return {'max_alt': None, 'moon_sep': None, 'observable': False}
    alts, _ = obs.compute_target_altaz(target, observer, ephem.Date(start), ephem.Date(end), nsteps=200)
    alts = np.asarray(alts)
    peak = start + (end - start) * int(np.argmax(alts)) / (len(alts) - 1)
    max_alt = float(np.max(alts))
    return {'max_alt': round(max_alt, 1), 'moon_sep': round(float(obs.moonsep_single(target, observer, ephem.Date(peak))), 1),
            'observable': max_alt >= MIN_ALT}


def publish(uid, source, name, ra, dec, script, telescope='SLT', trigger_time=None, log=None):
    """Hand an alert to the robot. Returns the new id, or None (already published, or the DB failed)."""
    from app.db.robot import add_alert
    try:
        vis = visibility_tonight(name, ra, dec)
    except Exception as e:  # never hold the alert back over the plot maths
        if log:
            log.warning('Robot alert %s: visibility not computed: %s', name, e)
        vis = {'max_alt': None, 'moon_sep': None, 'observable': None}
    try:
        return add_alert(uid, source, name, ra, dec, script, datetime.now(timezone.utc) + EXPIRES_AFTER,
                         telescope=telescope, trigger_time=trigger_time, **{k: vis[k] for k in ('max_alt', 'moon_sep', 'observable')})
    except Exception as e:
        if log:
            log.error('Robot alert %s not stored: %s', name, e)
        return None


def _public(a, now):
    st = a['status']
    if st == 'active' and datetime.fromisoformat(a['expires_at']) <= now:
        st = 'expired'
    script = a['script'] if a['script'].endswith('\n') else a['script'] + '\n'
    return {'id': a['id'], 'uid': a['uid'], 'source': a['source'], 'name': a['name'], 'telescope': a['telescope'],
            'ra': a['ra'], 'dec': a['dec'], 'trigger_time': a['trigger_time'], 'created_at': a['created_at'],
            'expires_at': a['expires_at'], 'status': st, 'observable_tonight': a['observable'],
            'max_alt_deg': a['max_alt'], 'moon_sep_deg': a['moon_sep'],
            'script': script, 'script_sha256': hashlib.sha256(script.encode()).hexdigest()}


def feed():
    """Body of GET /api/v1/robot/alert: the newest active, unexpired alert, or null."""
    from app.db.robot import newest_active
    now = datetime.now(timezone.utc)
    a = newest_active()
    return {'api': 'kinder-robot-alert', 'version': 1, 'now': now.isoformat(timespec='seconds'),
            'alert': _public(a, now) if a else None}


def note_client(ip, alert_id, agent):
    """Remember who polls and which alert id it got (shown on Triggers › Alerts under GCN & Einstein Probe)."""
    at = status.now_iso()

    def mutate(e):
        clients = dict(e.get('robot_clients') or {})
        prev = clients.get(ip) or {}
        clients[ip] = {'at': at, 'alert_id': alert_id, 'agent': (agent or '')[:120],
                       'polls': int(prev.get('polls') or 0) + 1}
        e['robot_clients'] = dict(sorted(clients.items(), key=lambda kv: kv[1]['at'], reverse=True)[:MAX_CLIENTS])
    status.update('gcn', _mutate=mutate)


def clients():
    return list(((status.get_all().get('gcn') or {}).get('robot_clients') or {}).items())
