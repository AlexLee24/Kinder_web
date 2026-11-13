"""Public object query API: the Transient page's filters as CSV or JSON, no login needed.

GET /api/query            what can be queried (parameters, the types with counts, sort keys,
                          columns, limits, examples) as JSON
GET /api/query/objects    the matching objects, CSV by default (format=json for JSON)

Only object metadata is returned, never photometry or spectra. Anonymous callers see the
public objects; an ``api_key`` (or a logged-in session) widens that to what the account may
open, with the same rules as the Transient page (``_build_where(apply_permissions=True)``).
"""
import csv
import difflib
import io
import logging
import math
import re
from datetime import datetime, timezone

from flask import Response, jsonify, request, session

from app.db import get_db_connection
from app.db.transient import _build_where
from app.services.astro.coordinate_converter import convert_dec_dms_to_decimal, convert_ra_hms_to_decimal

from . import astronomy_tools_bp
from .helpers import _client_ip, _rate_ok_burst

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000
MAX_RADIUS_ARCSEC = 36000.0   # 10 degrees
DEFAULT_RADIUS_ARCSEC = 60.0

# Special values of ``type`` (as on the Transient page) besides the TNS classifications.
SPECIAL_TYPES = {
    'at': ("o.name_prefix = 'AT'", 'Unclassified (AT) objects'),
    'classified': ("o.name_prefix <> 'AT'", 'Every classified object (SN, TDE, ... prefix)'),
}

STATUSES = {'inbox': 'object', 'followup': 'followup', 'snoozed': 'snoozed'}

SORTS = {
    'discovery_date': 'o.discovery_date',
    'name':           'o.name',
    'redshift':       'o.redshift',
    'discovery_mag':  'o.discovery_mag',
    'peak_mag':       'o.brightest_mag',
    'peak_abs_mag':   'o.brightest_abs_mag',
    'last_photometry': 'o.last_phot_date',
    'distance':       None,   # cone searches only
}

# (column, description). Order = CSV column order.
COLUMNS = [
    ('name', 'Full TNS name, e.g. SN 2024abc'),
    ('type', 'TNS classification (empty when unclassified)'),
    ('ra_deg', 'Right ascension, J2000 degrees'),
    ('dec_deg', 'Declination, J2000 degrees'),
    ('ra_hms', 'Right ascension, hh:mm:ss.ss'),
    ('dec_dms', 'Declination, ±dd:mm:ss.s'),
    ('redshift', 'Redshift'),
    ('discovery_date', 'Discovery date, UTC (YYYY-MM-DD HH:MM:SS)'),
    ('discovery_mjd', 'Discovery date, MJD'),
    ('discovery_mag', 'Discovery magnitude'),
    ('discovery_filter', 'Filter of the discovery magnitude'),
    ('peak_mag', 'Brightest apparent magnitude in Kinder photometry'),
    ('peak_abs_mag', 'Brightest absolute magnitude'),
    ('last_photometry_date', 'Date of the latest photometry point, UTC'),
    ('internal_names', 'Survey / internal names'),
    ('reporting_group', 'TNS reporting group'),
    ('source_group', 'TNS discovery data source group'),
    ('status', 'Kinder follow-up status: inbox, followup or snoozed'),
    ('tags', 'Kinder tags, comma separated'),
    ('url', 'Kinder object page'),
]
CONE_COLUMN = ('separation_arcsec', 'Distance from the cone-search centre (cone searches only)')

PARAMS = {
    'type': 'Classification, case-insensitive; comma-separated for several (SLSN-I,SLSN-II). '
            'End with * for a prefix (SLSN* = every SLSN class). AT = unclassified, Classified = all classified.',
    'name': 'Part of the name or an internal name (2024abc, ZTF24, ATLAS24...)',
    'discovered_after': 'Discovered on or after this date (YYYY-MM-DD)',
    'discovered_before': 'Discovered on or before this date (YYYY-MM-DD)',
    'z_min': 'Minimum redshift', 'z_max': 'Maximum redshift',
    'mag_min': 'Discovery magnitude >=', 'mag_max': 'Discovery magnitude <=',
    'peak_mag_min': 'Peak apparent magnitude >=', 'peak_mag_max': 'Peak apparent magnitude <=',
    'peak_abs_mag_min': 'Peak absolute magnitude >=', 'peak_abs_mag_max': 'Peak absolute magnitude <=',
    'discoverer': 'Part of the reporting / source group or reporter names (ZTF, ATLAS, GOTO...)',
    'status': 'Kinder status: ' + ', '.join(STATUSES),
    'ra': 'Cone search centre RA (degrees or hh:mm:ss); needs dec',
    'dec': 'Cone search centre Dec (degrees or ±dd:mm:ss); needs ra',
    'radius': f'Cone radius in arcsec (default {DEFAULT_RADIUS_ARCSEC:g}, max {MAX_RADIUS_ARCSEC:g})',
    'sort': 'Sort key: ' + ', '.join(SORTS) + ' (default discovery_date; distance for cone searches)',
    'order': 'asc or desc (default desc; asc for distance)',
    'limit': f'Rows to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT})',
    'offset': 'Rows to skip, for paging past the limit',
    'format': 'csv (default) or json',
    'api_key': 'Optional. Your Kinder API key: also returns the restricted objects your account may open',
}
_ALIASES = {'q': 'name', 'search': 'name', 'classification': 'type',
            'date_from': 'discovered_after', 'date_to': 'discovered_before',
            'redshift_min': 'z_min', 'redshift_max': 'z_max'}

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_CORS = {'Access-Control-Allow-Origin': '*'}


class QueryError(ValueError):
    pass


def _viewer():
    """(email, is_admin, error_response). API key first, then the session; else anonymous."""
    key = (request.args.get('api_key') or request.headers.get('X-API-Key') or '').strip()
    if key:
        from app.db.auth import get_user_by_api_key
        user = get_user_by_api_key(key)
        if not user:
            return None, False, (jsonify({'error': 'Invalid API key.'}), 401, _CORS)
        return user.get('email'), bool(user.get('is_admin')), None
    u = session.get('user') or {}
    return u.get('email') or None, bool(u.get('is_admin')), None


def _visible_types(viewer_email, viewer_is_admin):
    """[(type, count)] of the classified objects this viewer may see, most common first."""
    params = []
    where = _build_where(params, apply_permissions=True, viewer_email=viewer_email,
                         viewer_is_admin=viewer_is_admin)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT o.type, COUNT(*) FROM transient.objects o WHERE {where} "
            "AND o.type IS NOT NULL AND o.type <> '' GROUP BY o.type ORDER BY COUNT(*) DESC, o.type",
            params)
        types = [(t, n) for t, n in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE o.name_prefix = 'AT') "
                    f"FROM transient.objects o WHERE {where}", params)
        total, unclassified = cur.fetchone()
    return types, total, unclassified


def _args():
    """Request args with aliases folded in; unknown names are refused (typos would
    otherwise silently return everything)."""
    out = {}
    for name, value in request.args.items():
        key = _ALIASES.get(name, name)
        if key not in PARAMS:
            close = difflib.get_close_matches(name, list(PARAMS), n=1)
            raise QueryError(f"Unknown parameter '{name}'." + (f" Did you mean '{close[0]}'?" if close else '')
                             + ' See /api/query for the list.')
        out[key] = value.strip()
    return out


def _float(args, name, lo=-math.inf, hi=math.inf):
    raw = args.get(name)
    if raw in (None, ''):
        return None
    try:
        value = float(raw)
    except ValueError:
        raise QueryError(f'{name} must be a number.') from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise QueryError(f'{name} must be between {lo:g} and {hi:g}.')
    return value


def _int(args, name, default, lo, hi):
    raw = args.get(name)
    if raw in (None, ''):
        return default
    if not raw.isdigit() or not lo <= int(raw) <= hi:
        raise QueryError(f'{name} must be a whole number from {lo} to {hi}.')
    return int(raw)


def _date(args, name):
    raw = args.get(name)
    if not raw:
        return None
    try:
        if not _DATE_RE.match(raw):
            raise ValueError
        datetime.strptime(raw, '%Y-%m-%d')
    except ValueError:
        raise QueryError(f'{name} must be a date as YYYY-MM-DD.') from None
    return raw


def _type_clause(raw, known_types, params):
    """SQL for the ``type`` filter; unknown names are refused with suggestions."""
    conds = []
    lower_known = {t.lower(): t for t in known_types}
    for item in [t.strip() for t in raw.split(',') if t.strip()]:
        low = item.lower()
        if low in SPECIAL_TYPES:
            conds.append(SPECIAL_TYPES[low][0])
        elif item.endswith('*'):
            prefix = item[:-1].strip()
            if not prefix:
                raise QueryError("type '*' needs a prefix, e.g. SLSN*.")
            conds.append("lower(o.type) LIKE %s")
            params.append(prefix.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        elif low in lower_known:
            conds.append("lower(o.type) = %s")
            params.append(low)
        else:
            close = difflib.get_close_matches(item, known_types, n=3, cutoff=0.5)
            raise QueryError(f"Unknown type '{item}'." + (f" Did you mean {', '.join(close)}?" if close else '')
                             + ' See /api/query for every type.')
    return f"({' OR '.join(conds)})" if conds else None


def _coord(raw, is_ra):
    """Degrees from decimal degrees or sexagesimal (RA in hours: hh:mm:ss, Dec ±dd:mm:ss)."""
    try:
        value = float(raw)
    except ValueError:
        try:
            value = (convert_ra_hms_to_decimal(raw)['ra_decimal'] if is_ra
                     else convert_dec_dms_to_decimal(raw)['dec_decimal'])
        except Exception:
            raise QueryError(f"{'ra' if is_ra else 'dec'} must be degrees or "
                             f"{'hh:mm:ss' if is_ra else '±dd:mm:ss'}.") from None
    if not math.isfinite(value):
        raise QueryError('ra/dec must be finite numbers.')
    return value


def _hms(deg):
    h = (deg % 360.0) / 15.0
    hh = int(h); mm = int((h - hh) * 60); ss = ((h - hh) * 60 - mm) * 60
    if ss >= 59.995:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, hh = 0, (hh + 1) % 24
    return f'{hh:02d}:{mm:02d}:{ss:05.2f}'


def _dms(deg):
    sign = '-' if deg < 0 else '+'
    d = abs(deg); dd = int(d); mm = int((d - dd) * 60); ss = ((d - dd) * 60 - mm) * 60
    if ss >= 59.95:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, dd = 0, dd + 1
    return f'{sign}{dd:02d}:{mm:02d}:{ss:04.1f}'


def _clean(v):
    return None if isinstance(v, float) and not math.isfinite(v) else v


def run_query(args, viewer_email, viewer_is_admin):
    """(rows, total, meta) for parsed request args. Raises QueryError for bad input."""
    fmt = (args.get('format') or 'csv').lower()
    if fmt not in ('csv', 'json'):
        raise QueryError('format must be csv or json.')
    status = (args.get('status') or '').lower() or None
    if status and status not in STATUSES:
        raise QueryError(f"status must be one of {', '.join(STATUSES)}.")

    params = []
    where = _build_where(
        params,
        search_term=args.get('name') or '',
        tag=STATUSES.get(status) if status else None,
        date_from=_date(args, 'discovered_after'),
        date_to=_date(args, 'discovered_before'),
        app_mag_min=_float(args, 'mag_min'), app_mag_max=_float(args, 'mag_max'),
        redshift_min=_float(args, 'z_min'), redshift_max=_float(args, 'z_max'),
        discoverer=args.get('discoverer') or None,
        brightest_mag_min=_float(args, 'peak_mag_min'), brightest_mag_max=_float(args, 'peak_mag_max'),
        brightest_abs_mag_min=_float(args, 'peak_abs_mag_min'),
        brightest_abs_mag_max=_float(args, 'peak_abs_mag_max'),
        apply_permissions=True, viewer_email=viewer_email, viewer_is_admin=viewer_is_admin,
    )
    clauses = [where]

    if args.get('type'):
        known = [t for t, _ in _visible_types(viewer_email, viewer_is_admin)[0]]
        clause = _type_clause(args['type'], known, params)
        if clause:
            clauses.append(clause)

    # Cone search (haversine, in degrees; the Dec band lets the (ra, dec) index help).
    cone = None
    if args.get('ra') or args.get('dec'):
        if not (args.get('ra') and args.get('dec')):
            raise QueryError('A cone search needs both ra and dec.')
        ra, dec = _coord(args['ra'], True), _coord(args['dec'], False)
        if not (0 <= ra < 360 and -90 <= dec <= 90):
            raise QueryError('ra must be 0–360 and dec −90–90 degrees.')
        radius = _float(args, 'radius', 0.0, MAX_RADIUS_ARCSEC)
        radius = DEFAULT_RADIUS_ARCSEC if radius is None else radius
        cone = (ra, dec, radius)
    elif args.get('radius'):
        raise QueryError('radius needs ra and dec.')

    sep_sql = ("3600 * degrees(2 * asin(LEAST(1.0, sqrt("
               "power(sin(radians(o.dec - %s) / 2), 2) + "
               "cos(radians(o.dec)) * cos(radians(%s)) * power(sin(radians(o.ra - %s) / 2), 2)))))")
    select_extra, select_params = '', []
    if cone:
        ra, dec, radius = cone
        r_deg = radius / 3600.0
        clauses.append(f"o.dec BETWEEN %s AND %s AND {sep_sql} <= %s")
        params.extend([dec - r_deg, dec + r_deg, dec, dec, ra, radius])
        select_extra = f", {sep_sql} AS separation_arcsec"
        select_params = [dec, dec, ra]

    sort = (args.get('sort') or ('distance' if cone else 'discovery_date')).lower()
    if sort not in SORTS:
        raise QueryError(f"sort must be one of {', '.join(SORTS)}.")
    if sort == 'distance' and not cone:
        raise QueryError('sort=distance needs a cone search (ra, dec).')
    order = (args.get('order') or ('asc' if sort == 'distance' else 'desc')).lower()
    if order not in ('asc', 'desc'):
        raise QueryError('order must be asc or desc.')
    order_sql = 'separation_arcsec' if sort == 'distance' else SORTS[sort]
    limit = _int(args, 'limit', DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(args, 'offset', 0, 0, 10_000_000)

    where_sql = ' AND '.join(clauses)
    query = (
        "SELECT COALESCE(o.name_prefix, '') AS name_prefix, o.name, o.type, o.ra, o.dec, o.redshift, "
        "to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') "
        "  AS discovery_date, o.discovery_date AS discovery_mjd, o.discovery_mag, o.discovery_filter, "
        "o.brightest_mag, o.brightest_abs_mag, "
        "to_char(TIMESTAMP '1858-11-17' + o.last_phot_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') "
        "  AS last_photometry_date, "
        "NULLIF(concat_ws(', ', NULLIF(o.internal_name, ''), NULLIF(o.other_name, '')), '') AS internal_names, "
        "o.report_group, o.source_group, o.status, array_to_string(o.tag, ', ') AS tags"
        f"{select_extra} FROM transient.objects o WHERE {where_sql} "
        f"ORDER BY {order_sql} {order.upper()} NULLS LAST, o.obj_id {order.upper()} LIMIT %s OFFSET %s"
    )
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM transient.objects o WHERE {where_sql}", params)
        total = cur.fetchone()[0]
        cur.execute(query, select_params + params + [limit, offset])
        cols = [d[0] for d in cur.description]
        raw_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    base = request.url_root.rstrip('/')
    status_label = {'Inbox': 'inbox', 'Follow-up': 'followup', 'Snoozed': 'snoozed', 'Finish': 'snoozed'}
    rows = []
    for r in raw_rows:
        prefix = r['name_prefix'].strip()
        ra_deg, dec_deg = _clean(r['ra']), _clean(r['dec'])
        row = {
            'name': f"{prefix} {r['name']}".strip(),
            'type': r['type'] or None,
            'ra_deg': round(ra_deg, 7) if ra_deg is not None else None,
            'dec_deg': round(dec_deg, 7) if dec_deg is not None else None,
            'ra_hms': _hms(ra_deg) if ra_deg is not None else None,
            'dec_dms': _dms(dec_deg) if dec_deg is not None else None,
            'redshift': _clean(r['redshift']),
            'discovery_date': r['discovery_date'],
            'discovery_mjd': round(r['discovery_mjd'], 5) if _clean(r['discovery_mjd']) is not None else None,
            'discovery_mag': _clean(r['discovery_mag']),
            'discovery_filter': r['discovery_filter'] or None,
            'peak_mag': _clean(r['brightest_mag']),
            'peak_abs_mag': _clean(r['brightest_abs_mag']),
            'last_photometry_date': r['last_photometry_date'],
            'internal_names': ', '.join(dict.fromkeys(
                n.strip() for n in (r['internal_names'] or '').split(',') if n.strip())) or None,
            'reporting_group': r['report_group'] or None,
            'source_group': r['source_group'] or None,
            'status': status_label.get(r['status'], 'inbox'),
            'tags': r['tags'] or None,
            'url': f"{base}/object/{r['name']}",
        }
        if cone:
            row['separation_arcsec'] = round(r['separation_arcsec'], 3)
        rows.append(row)

    meta = {'format': fmt, 'limit': limit, 'offset': offset, 'cone': cone, 'sort': sort, 'order': order}
    return rows, total, meta


@astronomy_tools_bp.route('/api/query', methods=['GET'])
def api_query_index():
    """What /api/query/objects can filter on, for this caller."""
    if not _rate_ok_burst(_client_ip(), 'query_index', 10, 10):
        return jsonify({'error': 'Rate limit exceeded — max 10 requests per 10 s.'}), 429, _CORS
    viewer_email, viewer_is_admin, err = _viewer()
    if err:
        return err
    try:
        types, total, unclassified = _visible_types(viewer_email, viewer_is_admin)
    except Exception:
        logger.exception('api_query_index failed')
        return jsonify({'error': 'Internal server error.'}), 500, _CORS
    base = request.url_root.rstrip('/')
    return jsonify({
        'api': 'Kinder object query',
        'description': 'Find transients by classification, redshift, dates, magnitudes, discoverer or '
                       'position. Returns object metadata only (no photometry or spectra).',
        'endpoint': f'{base}/api/query/objects',
        'access': 'No login needed: public objects. Add api_key to include restricted objects your account may open.',
        'visible_to_you': {'objects': total, 'unclassified_AT': unclassified, 'classified': total - unclassified,
                           'as': viewer_email or 'anonymous'},
        'rate_limit': '10 requests per 10 seconds per IP',
        'formats': ['csv', 'json'],
        'parameters': PARAMS,
        'parameter_aliases': _ALIASES,
        'types': [{'type': t, 'count': n} for t, n in types],
        'special_types': {'AT': SPECIAL_TYPES['at'][1], 'Classified': SPECIAL_TYPES['classified'][1]},
        'statuses': list(STATUSES),
        'sort_keys': list(SORTS),
        'columns': dict(COLUMNS + [CONE_COLUMN]),
        'limits': {'default_limit': DEFAULT_LIMIT, 'max_limit': MAX_LIMIT,
                   'max_radius_arcsec': MAX_RADIUS_ARCSEC},
        'examples': {
            'Every SLSN-I as CSV': f'{base}/api/query/objects?type=SLSN-I',
            'Every SLSN class as JSON': f'{base}/api/query/objects?type=SLSN*&format=json',
            'SN Ia below z = 0.02 found in 2025': f'{base}/api/query/objects?type=SN Ia'
                                                   '&z_max=0.02&discovered_after=2025-01-01'
                                                   '&discovered_before=2025-12-31',
            'Objects within 2 arcmin of a position': f'{base}/api/query/objects?ra=150.1&dec=2.2&radius=120',
            'Next page': f'{base}/api/query/objects?type=SN Ia&limit=1000&offset=1000',
        },
    }), 200, _CORS


@astronomy_tools_bp.route('/api/query/objects', methods=['GET'])
def api_query_objects():
    if not _rate_ok_burst(_client_ip(), 'query_objects', 10, 10):
        return jsonify({'error': 'Rate limit exceeded — max 10 requests per 10 s.'}), 429, _CORS
    viewer_email, viewer_is_admin, err = _viewer()
    if err:
        return err
    try:
        args = _args()
        rows, total, meta = run_query(args, viewer_email, viewer_is_admin)
    except QueryError as exc:
        return jsonify({'error': str(exc), 'help': '/api/query'}), 400, _CORS
    except Exception:
        logger.exception('api_query_objects failed')
        return jsonify({'error': 'Internal server error.'}), 500, _CORS

    more = meta['offset'] + len(rows) < total
    headers = dict(_CORS, **{'X-Total-Count': str(total), 'X-Returned-Count': str(len(rows)),
                             'Access-Control-Expose-Headers': 'X-Total-Count, X-Returned-Count, X-Next-Offset'})
    if more:
        headers['X-Next-Offset'] = str(meta['offset'] + len(rows))

    if meta['format'] == 'json':
        cone = meta['cone']
        return jsonify({
            'success': True,
            'total': total,
            'returned': len(rows),
            'offset': meta['offset'],
            'limit': meta['limit'],
            'next_offset': meta['offset'] + len(rows) if more else None,
            'query': {k: v for k, v in args.items() if k != 'api_key'},
            'cone': {'ra_deg': cone[0], 'dec_deg': cone[1], 'radius_arcsec': cone[2]} if cone else None,
            'objects': rows,
        }), 200, headers

    names = [c for c, _ in COLUMNS] + ([CONE_COLUMN[0]] if meta['cone'] else [])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=names, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    label = re.sub(r'[^\w\-]+', '_', args.get('type') or args.get('name') or 'objects').strip('_') or 'objects'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d')
    headers['Content-Disposition'] = f'attachment; filename="kinder_{label}_{stamp}.csv"'
    return Response(buf.getvalue(), mimetype='text/csv', headers=headers)
