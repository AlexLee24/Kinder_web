"""Alerts for the Lulin observing robot: stored in obs.robot_alerts (app/db/robot.py), served by two keyless,
read-only endpoints (astronomy_tools/robot_api.py): GET /api/v1/robot/alert and GET /api/v1/robot/alert-run.

The endpoint shows at most ONE alert: the newest one that is active (not cancelled on Triggers › Alerts) and not
expired, with its ACP script; ``alert`` is null when there is none. The robot remembers the id it last ran and runs an
alert only when its id is LARGER (ids only grow): a repeated poll never runs an alert twice, and when the newest alert
is cancelled and an older one shows again, that older one is not run a second time. If the id it is running
disappears (cancelled or expired) it can stop.
Each alert also says whether it rises above MIN_ALT during tonight's dark time at Lulin (``observable_tonight``);
the robot decides what to do with that.

GET /api/v1/robot/alert-run is the same alert, shown only when it can be taken RIGHT NOW at Lulin: the Sun is below
-18° (astronomical night) and the target is at least RUN_MIN_ALT up. Its script is cut to fit: #COUNT drops so the
frames (each #INTERVAL + FRAME_OVERHEAD_S) end before the target sinks under RUN_END_ALT or DAWN_GRACE after
astronomical dawn, whichever is first (never more frames than the stored script). ``alert`` is null otherwise; it is
also null when the newest alert cannot be taken now, even if an older one could (the robot compares ids).
"""
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

from . import status

MIN_ALT = 30.0              # degrees, during astronomical darkness
EXPIRES_AFTER = timedelta(hours=24)
MAX_CLIENTS = 10            # robot clients remembered for Triggers › Alerts
LULIN = ('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)

# alert-run
DARK_SUN_ALT = -18.0        # degrees: astronomical night
RUN_MIN_ALT = 30.0          # degrees: the target must be this high now
RUN_END_ALT = 20.0          # degrees: frames end before the target sinks below this
DAWN_GRACE = timedelta(minutes=30)   # ... or this long after astronomical dawn, whichever is first
FRAME_OVERHEAD_S = 30       # readout, saving etc. per frame
_COUNT_RE = re.compile(r'^(#COUNT[ \t]+)(\d+)[ \t]*$', re.I | re.M)
_INTERVAL_RE = re.compile(r'^#INTERVAL[ \t]+(\d+(?:\.\d+)?)[ \t]*$', re.I | re.M)


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


def _angle(value, hours):
    """ephem angle from 'hh:mm:ss' / 'dd:mm:ss' text or decimal degrees."""
    import ephem
    try:
        deg = float(value)
    except (TypeError, ValueError):
        return ephem.hours(str(value)) if hours else ephem.degrees(str(value))
    return ephem.hours(math.radians(deg)) if hours else ephem.degrees(math.radians(deg))


def run_window(ra, dec, now=None):
    """Can the target be taken right now at Lulin, and until when?
    {'dark', 'alt_now', 'until', 'until_reason'}: ``until`` (UTC) is the earlier of the last minute the target is still
    at least RUN_END_ALT up ('alt') and astronomical dawn + DAWN_GRACE ('dawn'); None unless it is dark now."""
    import ephem
    now = now or datetime.now(timezone.utc)
    o = ephem.Observer()
    o.lon, o.lat, o.elevation = LULIN[1], LULIN[2], LULIN[3]
    o.pressure = 0
    o.date = ephem.Date(now.astimezone(timezone.utc).replace(tzinfo=None))
    body = ephem.FixedBody()
    body._ra, body._dec, body._epoch = _angle(ra, True), _angle(dec, False), ephem.J2000
    body.compute(o)
    sun = ephem.Sun(o)
    out = {'dark': math.degrees(sun.alt) < DARK_SUN_ALT, 'alt_now': round(math.degrees(body.alt), 1),
           'until': None, 'until_reason': None}
    if not out['dark']:
        return out
    o.horizon = str(DARK_SUN_ALT)
    dawn = o.next_rising(ephem.Sun(), use_center=True).datetime().replace(tzinfo=timezone.utc)
    until, reason = dawn + DAWN_GRACE, 'dawn'
    step = timedelta(minutes=1)
    t = now
    while t + step <= until:
        o.date = ephem.Date((t + step).astimezone(timezone.utc).replace(tzinfo=None))
        body.compute(o)
        if math.degrees(body.alt) < RUN_END_ALT:
            until, reason = t, 'alt'
            break
        t += step
    out.update(until=until, until_reason=reason)
    return out


def fit_script(script, seconds):
    """(script, count) with #COUNT lowered so the frames, #INTERVAL + FRAME_OVERHEAD_S each, fit in ``seconds``
    (never above the script's own count); (None, 0) when not even one frame fits. A script without exactly one
    #INTERVAL and one #COUNT is returned as it is, count None."""
    iv, ct = _INTERVAL_RE.findall(script), _COUNT_RE.findall(script)
    if len(iv) != 1 or len(ct) != 1:
        return script, None
    n = min(int(ct[0][1]), int(max(seconds, 0) // (float(iv[0]) + FRAME_OVERHEAD_S)))
    if n < 1:
        return None, 0
    return _COUNT_RE.sub(lambda m: f'{m.group(1)}{n}', script), n


def run_feed(now=None):
    """Body of GET /api/v1/robot/alert-run: the newest active, unexpired alert when it can be taken right now at
    Lulin, its script cut to the time left; else null, with ``reason`` saying why."""
    from app.db.robot import newest_active
    now = now or datetime.now(timezone.utc)
    body = {'api': 'kinder-robot-alert-run', 'version': 1, 'now': now.isoformat(timespec='seconds'), 'alert': None,
            'reason': None}
    a = newest_active()
    if not a:
        body['reason'] = 'no active alert'
        return body
    w = run_window(a['ra'], a['dec'], now)
    if not w['dark']:
        body['reason'] = 'not astronomical night at Lulin'
    elif w['alt_now'] < RUN_MIN_ALT:
        body['reason'] = f"{a['name']} is at {w['alt_now']}°, below {RUN_MIN_ALT:g}°"
    else:
        script, count = fit_script(a['script'], (w['until'] - now).total_seconds())
        if script is None:
            body['reason'] = f"no time left for one frame of {a['name']}"
        else:
            body['alert'] = dict(_public(dict(a, script=script), now), alt_now_deg=w['alt_now'], count=count,
                                 run_until=w['until'].isoformat(timespec='seconds'), run_until_reason=w['until_reason'])
    return body


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
