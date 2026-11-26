"""Auto exposure of Daily Trigger SLT targets, from CASTOR.

Each filter gets CASTOR's Simple-mode plan (castorCLI.plan.compute_plan, the calculator on /exposure_time_calculator):
the frame length and count that reach the target's S/N (default 20) for the magnitude it had last, at the hour
tonight the target stands highest at Lulin.

Magnitudes: each filter its own latest detection on the target's Transient page; a filter without one, the latest
detection in any filter; a target with no detection at all, the magnitude typed on the target (no magnitude at all:
no auto exposure).

Plans: all five filters, g + r, or r only. 'auto' takes the first of those whose time at the telescope stays within
MAX_TOTAL_S; a target can pin one (and then gets it however long it takes), or leave auto exposure for its own filters.

update_all() refreshes every SLT auto target (magnitude, plan, filters): daily at 12:00 UTC+8 and after the
auto photometry bot has measured last night.
"""
import logging
import math
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# (script filter, band, CASTOR filter)
BANDS = (('up', 'u', 'Sloan_u'), ('gp', 'g', 'Sloan_g'), ('rp', 'r', 'Sloan_r'), ('ip', 'i', 'Sloan_i'), ('zp', 'z', 'Sloan_z'))
PLANS = {'all': ('up', 'gp', 'rp', 'ip', 'zp'), 'gr': ('gp', 'rp'), 'r': ('rp',)}
PLAN_LABEL = {'all': 'u g r i z', 'gr': 'g + r', 'r': 'r only'}
CHOICES = ('auto', 'all', 'gr', 'r')
DEFAULT_SNR = 20.0
MAX_TOTAL_S = 30 * 60          # 'auto': the longest a plan may take at the telescope
# Shortest frame: CASTOR would give a bright target 15 s frames, but a frame that short holds too few field stars
# for AutoPhOT's zero point and template alignment (AT2026afqt z, 2026-11-25: 5 stars in 8')
MIN_EXP_S = 60
SITE, TELESCOPE, CAMERA = 'lulin', 'SLT', 'SLT_DZ936'      # the SLT camera since 2026-11-03
LULIN = ('120:52:21.5', '23:28:10.0', 2800)
TZ8 = timezone(timedelta(hours=8))
MIN_ALT_DEG = 20


class NoMagnitude(ValueError):
    pass


def _band(f):
    s = str(f or '').strip().lower()
    return s[:-1] if len(s) > 1 and s.endswith('p') else s


# ── magnitudes ──────────────────────────────────────────────────────────────

def _obj_id(cur, name):
    from app.db.transient import _resolve_obj_id_with_prefix
    name = re.sub(r'\s+', '', str(name or ''))
    if not name:
        return None
    if not name.upper().startswith('EP'):
        return _resolve_obj_id_with_prefix(cur, name)
    cur.execute("SELECT obj_id FROM transient.objects WHERE internal_name ILIKE %s "
                "OR EXISTS (SELECT 1 FROM unnest(tag) t(v) WHERE t.v ILIKE %s) LIMIT 1", (f'%{name}%', f'%{name}%'))
    row = cur.fetchone()
    return row[0] if row else None


def latest_detections(name):
    """{band: {'mag', 'mjd', 'filter', 'source'}} of the target's latest detection per filter on its Transient page,
    and '*': the latest in any filter. Detections only (a limit has no error)."""
    from app.db import get_db_connection
    with get_db_connection() as conn:
        cur = conn.cursor()
        oid = _obj_id(cur, name)
        if oid is None:
            return {}
        cur.execute('SELECT mag, "MJD", filter, source FROM transient.photometry WHERE obj_id = %s AND mag IS NOT NULL '
                    'AND mag > 0 AND mag_err IS NOT NULL ORDER BY "MJD" DESC', (oid,))
        rows = cur.fetchall()
    out = {}
    for mag, mjd, f, src in rows:
        d = {'mag': float(mag), 'mjd': float(mjd), 'filter': f, 'source': src or ''}
        out.setdefault('*', d)
        out.setdefault(_band(f), d)
    return out


def magnitudes(name, typed_mag=None, detections=None):
    """{script filter: {'mag', 'from'}} for the five filters; 'from' says where the magnitude came from."""
    det = latest_detections(name) if detections is None else detections
    typed = None
    try:
        typed = float(str(typed_mag).lstrip('>').strip()) if typed_mag not in (None, '') else None
    except ValueError:
        typed = None
    out = {}
    for sf, b, _ in BANDS:
        d = det.get(b) or det.get('*')
        if d:
            out[sf] = {'mag': d['mag'], 'from': 'own' if det.get(b) else 'other', 'filter': d['filter'], 'mjd': d['mjd'],
                       'source': d['source']}
        elif typed is not None:
            out[sf] = {'mag': typed, 'from': 'typed'}
        else:
            raise NoMagnitude(f'{name} has no photometry on Kinder: enter its magnitude to use auto exposure.')
    return out


# ── tonight ─────────────────────────────────────────────────────────────────

def best_time(ra, dec, day=None):
    """(UTC datetime, altitude in degrees) of the target's highest point at Lulin between the evening and morning
    astronomical twilight of the night starting on `day` (UTC+8; default today)."""
    import ephem
    day = day or datetime.now(TZ8).date()
    o = ephem.Observer()
    o.lon, o.lat, o.elevation = LULIN
    o.horizon = '-18'
    o.date = ephem.Date(datetime(day.year, day.month, day.day, 4, 0))          # 12:00 UTC+8
    sun = ephem.Sun()
    try:
        start, end = o.next_setting(sun, use_center=True), o.next_rising(sun, use_center=True)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        start, end = ephem.Date(o.date + 7 / 24), ephem.Date(o.date + 17 / 24)
    star = ephem.FixedBody()
    star._ra, star._dec, star._epoch = ephem.degrees(math.radians(float(ra))), ephem.degrees(math.radians(float(dec))), ephem.J2000
    best = None
    t = start
    while t <= end:
        o.date = t
        star.compute(o)
        alt = math.degrees(star.alt)
        if best is None or alt > best[1]:
            best = (t, alt)
        t = ephem.Date(t + 10 * ephem.minute)
    when = best[0].datetime().replace(tzinfo=timezone.utc, microsecond=0)
    return when, best[1]


# ── CASTOR ──────────────────────────────────────────────────────────────────

_catalogue = None


def _castor():
    global _catalogue
    import app.paths  # noqa: F401  (puts the vendored CASTOR on sys.path)
    from castorCLI import plan, presets
    if _catalogue is None:
        from app.blueprints.astronomy_tools.helpers import _CASTOR_PRESETS_PATH
        _catalogue = presets.load(_CASTOR_PRESETS_PATH)
    return plan, _catalogue


def _fwhm(cat):
    try:
        return float(cat.profile(SITE).median_seeing_fwhm or 1.4)
    except Exception:
        return 1.4


def plan_filter(castor_filter, ra, dec, mag, snr, when):
    """CASTOR's plan for one filter: {'status', 'exp', 'count', 'elapsed', 'snr'} (exp None when no frame works)."""
    plan, cat = _castor()
    kw = dict(site=SITE, telescope=TELESCOPE, camera=CAMERA, optic_filter=castor_filter, ra=float(ra), dec=float(dec),
              mag=float(mag), observing_time_utc=when.isoformat().replace('+00:00', 'Z'), fwhm=_fwhm(cat))
    r = plan.compute_plan(cat, **kw, target_snr=float(snr))
    rec, status = r.get('recommended'), r.get('status')
    if not rec:
        return {'status': status, 'exp': None, 'count': None, 'elapsed': None, 'snr': None}
    if rec['exp_s'] < MIN_EXP_S and (r['conditions'].get('saturation_time_s') or 0) > MIN_EXP_S:
        n = max(1, round(rec['total_s'] / MIN_EXP_S))
        rec = plan.compute_snr(cat, **kw, single_exp_time=MIN_EXP_S, num_exposures=n)['chosen']
    return {'status': status, 'exp': int(rec['exp_s']), 'count': int(rec['frames']), 'elapsed': int(rec['elapsed_s']),
            'snr': round(float(rec['snr']), 1)}


WHY = {'saturated': 'saturates even the shortest frame', 'unreachable': 'cannot reach the S/N (sky background)',
       'below_horizon': 'not above the horizon tonight'}


def compute(name, ra, dec, typed_mag=None, snr=DEFAULT_SNR, choice='auto', day=None, detections=None):
    """The target's plan for tonight. Raises NoMagnitude when there is nothing to compute it from."""
    snr = float(snr or DEFAULT_SNR)
    choice = choice if choice in CHOICES else 'auto'
    mags = magnitudes(name, typed_mag, detections)
    when, alt = best_time(ra, dec, day)
    filters, notes = {}, []
    for sf, b, cf in BANDS:
        p = plan_filter(cf, ra, dec, mags[sf]['mag'], snr, when)
        filters[sf] = {**p, **mags[sf]}
        if p['exp'] is None:
            notes.append(f'{b}: {WHY.get(p["status"], p["status"])}')
    options = {}
    for k, fs in PLANS.items():
        usable = [sf for sf in fs if filters[sf]['exp']]
        options[k] = {'total_s': sum(filters[sf]['elapsed'] for sf in usable), 'filters': usable}
    if choice == 'auto':
        chosen = next((k for k in ('all', 'gr', 'r') if options[k]['filters'] and options[k]['total_s'] <= MAX_TOTAL_S), 'r')
    else:
        chosen = choice
    plan = [{'filter': sf, 'exp': filters[sf]['exp'], 'count': filters[sf]['count']} for sf in options[chosen]['filters']]
    if alt < MIN_ALT_DEG:
        notes.append(f'highest tonight only {alt:.0f}°')
    return {'computed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'night': (day or datetime.now(TZ8).date()).isoformat(),
            'when': when.isoformat(), 'alt': round(alt, 1), 'snr': snr, 'choice': choice, 'chosen': chosen,
            'filters': filters, 'options': options, 'plan': plan, 'too_long': options[chosen]['total_s'] > MAX_TOTAL_S,
            'max_total_s': MAX_TOTAL_S, 'min_exp_s': MIN_EXP_S, 'notes': notes}


def latest_mag(result):
    """The magnitude to show on the target: the latest detection in any filter it was computed from."""
    ds = [f for f in result['filters'].values() if f.get('from') in ('own', 'other') and f.get('mjd') is not None]
    return max(ds, key=lambda f: f['mjd'])['mag'] if ds else None


def apply(target, **kw):
    """Compute and store one target's plan (its filters follow it). Returns the result, or raises NoMagnitude."""
    from app.db.obs import set_auto_exposure_result
    res = compute(target['name'], target['ra'], target['dec'], target.get('mag'), target.get('auto_snr') or DEFAULT_SNR,
                  target.get('auto_plan') or 'auto', **kw)
    set_auto_exposure_result(target['id'], res, filters=res['plan'] or None, mag=latest_mag(res))
    return res


def update_all(day=None):
    """Every active SLT auto-exposure target: tonight's plan from its latest magnitudes. A summary line."""
    from app.db.obs import get_observation_targets, set_auto_exposure_result
    done, failed = 0, []
    for t in get_observation_targets(active_only=True):
        if not t.get('auto_exposure') or (t.get('telescope') or '').upper() != 'SLT':
            continue
        try:
            apply(t, day=day)
            done += 1
        except NoMagnitude as e:
            prev = t.get('auto_result') or {}
            set_auto_exposure_result(t['id'], {**prev, 'error': str(e), 'computed_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
            failed.append(t['name'])
        except Exception:
            logger.exception('auto exposure: %s', t.get('name'))
            failed.append(t['name'])
    line = f'auto exposure: {done} targets planned' + (f'; failed: {", ".join(failed)}' if failed else '')
    logger.info(line)
    return line
