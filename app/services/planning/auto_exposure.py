"""Auto exposure of Daily Trigger SLT targets, from CASTOR.

Each filter gets CASTOR's Simple-mode plan (castorCLI.plan.compute_plan, the calculator on /exposure_time_calculator):
the frame length and count that reach the target's S/N (default 20) for the magnitude it had last, at the hour
tonight the target stands highest at Lulin.

Magnitudes: each filter its own latest detection on the target's Transient page; a filter without one, the latest
detection in any filter; a target with no detection at all, the magnitude typed on the target (no magnitude at all:
no auto exposure).

Filters: the ones picked on the target (auto_plan, e.g. 'up,gp,rp,ip,zp'; default all five), however long they take;
a plan over MAX_TOTAL_S is flagged, with what g + r or r alone would take. Every filter is computed, so the form can
change the pick without asking CASTOR again.

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
ALL = tuple(sf for sf, _, _ in BANDS)
PLANS = {'all': ALL, 'gr': ('gp', 'rp'), 'r': ('rp',)}       # the shorter plans offered when the pick runs long
DEFAULT_SNR = 20.0
MAX_TOTAL_S = 30 * 60          # a plan longer than this at the telescope is flagged
# Shortest frame per filter: CASTOR answers for the target alone and would give a 17 mag target 60 s or less, but
# template subtraction needs field stars to align on. What SLT frames did, 2026-11-15..25 auto photometry: z TS
# needs ~19 mag (3 sigma) of depth: 150 s failed 2 of 3 (16.8-16.9 mag), 300 s worked 4 of 6 (the 2 failures were a
# Pan-STARRS alignment, 19.4-19.7 mag deep), stacks always; g r i at 150 s always worked (60 s never tried); u is
# stacked two by two at 300 s. A target bright enough to saturate gets shorter frames (SAT_MARGIN).
MIN_EXP_S = {'up': 300, 'gp': 150, 'rp': 150, 'ip': 150, 'zp': 300}
FRAME_STEPS = (150,)          # frame lengths besides CASTOR's own (150 s: what SLT has been taking)
SAT_MARGIN = 0.7              # a frame at most 70% of CASTOR's saturation time for the target
SITE, TELESCOPE, CAMERA = 'lulin', 'SLT', 'SLT_DZ936'      # the SLT camera since 2026-11-03
LULIN = ('120:52:21.5', '23:28:10.0', 2800)
TZ8 = timezone(timedelta(hours=8))
MIN_ALT_DEG = 20


class NoMagnitude(ValueError):
    pass


def selection(choice):
    """The script filters picked for a target, in u g r i z order: 'up,rp' (or a list); the old plan names (auto,
    all, gr, r) still read; nothing valid means all five."""
    if isinstance(choice, str) and choice in PLANS:
        return list(PLANS[choice])
    items = choice.split(',') if isinstance(choice, str) else list(choice or [])
    picked = {str(x).strip().lower() for x in items}
    out = [sf for sf in ALL if sf in picked]
    return out or list(ALL)


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


def latest_by_object(names):
    """{object name (bare, as in transient.objects): its latest detection's magnitude}, in one query: the Newest Mag
    the target form fills in when an object is picked (the same one the daily update writes)."""
    from app.db import get_db_connection
    names = [n for n in set(names or []) if n]
    if not names:
        return {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT ON (o.name) o.name, p.mag FROM transient.photometry p JOIN transient.objects o '
                    'ON o.obj_id = p.obj_id WHERE o.name = ANY(%s) AND p.mag IS NOT NULL AND p.mag > 0 '
                    'AND p.mag_err IS NOT NULL ORDER BY o.name, p."MJD" DESC', (names,))
        return {n: float(m) for n, m in cur.fetchall()}


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


def plan_filter(castor_filter, ra, dec, mag, snr, when, min_exp=None):
    """CASTOR's plan for one filter, frames at least min_exp s (default: MIN_EXP_S of that filter):
    {'status', 'exp', 'count', 'elapsed', 'snr', 'sat_s'} (exp None when no frame works)."""
    if min_exp is None:
        min_exp = next((MIN_EXP_S[sf] for sf, _, cf in BANDS if cf == castor_filter), 60)
    plan, cat = _castor()
    kw = dict(site=SITE, telescope=TELESCOPE, camera=CAMERA, optic_filter=castor_filter, ra=float(ra), dec=float(dec),
              mag=float(mag), observing_time_utc=when.isoformat().replace('+00:00', 'Z'), fwhm=_fwhm(cat))
    r = plan.compute_plan(cat, **kw, target_snr=float(snr))
    rec, status = r.get('recommended'), r.get('status')
    if not rec:
        return {'status': status, 'exp': None, 'count': None, 'elapsed': None, 'snr': None}
    # longer frames than CASTOR's, up to min_exp, but never into saturation: the target's peak pixel must stay below
    # full well with SAT_MARGIN to spare (better seeing than the median 1.4" puts more light in the peak)
    t_sat = float(r['conditions'].get('saturation_time_s') or 0)
    # (CASTOR's own pick can sit just under saturation too: mag 11 in r, 15 s of a 17.4 s limit)
    want = max(rec['exp_s'], min_exp)
    steps = set(plan.SHORT_EXPOSURES) | set(plan.PREFERRED_EXPOSURES) | set(FRAME_STEPS)
    safe = [t for t in sorted(steps) if t <= want and t < t_sat * SAT_MARGIN]
    if safe and safe[-1] != rec['exp_s']:
        t = safe[-1]
        rec = plan.compute_snr(cat, **kw, single_exp_time=t, num_exposures=max(1, math.ceil(rec['total_s'] / t)))['chosen']
    return {'status': status, 'exp': int(rec['exp_s']), 'count': int(rec['frames']), 'elapsed': int(rec['elapsed_s']),
            'snr': round(float(rec['snr']), 1), 'sat_s': round(t_sat, 1)}


WHY = {'saturated': 'saturates even the shortest frame', 'unreachable': 'cannot reach the S/N (sky background)',
       'below_horizon': 'not above the horizon tonight'}


def compute(name, ra, dec, typed_mag=None, snr=DEFAULT_SNR, choice=None, day=None, detections=None):
    """The target's plan for tonight for the filters picked (choice). Raises NoMagnitude when there is nothing to
    compute it from."""
    snr = float(snr or DEFAULT_SNR)
    picked = selection(choice)
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
    usable = [sf for sf in picked if filters[sf]['exp']]
    plan = [{'filter': sf, 'exp': filters[sf]['exp'], 'count': filters[sf]['count']} for sf in usable]
    total = sum(filters[sf]['elapsed'] for sf in usable)
    if alt < MIN_ALT_DEG:
        notes.append(f'highest tonight only {alt:.0f}°')
    return {'computed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'night': (day or datetime.now(TZ8).date()).isoformat(),
            'when': when.isoformat(), 'alt': round(alt, 1), 'snr': snr, 'selected': picked, 'total_s': total,
            'filters': filters, 'options': options, 'plan': plan, 'too_long': total > MAX_TOTAL_S,
            'max_total_s': MAX_TOTAL_S, 'min_exp_s': MIN_EXP_S, 'notes': notes, 'latest': _latest(mags)}


def _latest(mags):
    """The newest detection the plan was computed from ({'mag', 'filter', 'mjd', 'source'}), None when typed."""
    ds = [m for m in mags.values() if m.get('from') in ('own', 'other') and m.get('mjd') is not None]
    if not ds:
        return None
    d = max(ds, key=lambda m: m['mjd'])
    return {k: d.get(k) for k in ('mag', 'filter', 'mjd', 'source')}


def latest_mag(result):
    """The magnitude to show on the target (its Newest Mag): the latest detection it was computed from."""
    d = result.get('latest') or _latest(result.get('filters') or {})
    return d['mag'] if d else None


def apply(target, **kw):
    """Compute and store one target's plan (its filters follow it). Returns the result, or raises NoMagnitude."""
    from app.db.obs import set_auto_exposure_result
    res = compute(target['name'], target['ra'], target['dec'], target.get('mag'), target.get('auto_snr') or DEFAULT_SNR,
                  target.get('auto_plan'), **kw)
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
