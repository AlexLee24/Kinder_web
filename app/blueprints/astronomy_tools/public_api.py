"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — public_api (split from astronomy_tools_routes.py)."""
import os
import re
import io
import traceback
import base64
import ephem
import numpy as np
from PIL import Image
from flask import render_template, request, jsonify, Response
from app.services.astro.astronomy_calculator import calculate_redshift_distance, calculate_absolute_magnitude
from app.core.request_validation import get_int_arg, get_float_arg
from app.services.astro.date_converter import (
    convert_mjd_to_date,
    convert_jd_to_date,
    convert_common_date_to_jd,
)
from app.services.astro.coordinate_converter import (
    convert_ra_hms_to_decimal,
    convert_ra_decimal_to_hms,
    convert_dec_dms_to_decimal,
    convert_dec_decimal_to_dms,
)
from app.services.planning import obsplan as obs
from . import astronomy_tools_bp
from .finding_chart import _resolve_target_coord
from .finding_chart_render import _fetch_survey_image, _query_nearby_stars, _render_finding_chart
from .helpers import _API_DOCS, _FINDING_CHART_SURVEYS, _client_ip, _rate_ok
from .planner import parse_coordinate


@astronomy_tools_bp.route('/api', methods=['GET'])
def api_index():
    if request.headers.get('Accept', '').startswith('application/json') or request.args.get('format') == 'json':
        return jsonify(_API_DOCS)
    return render_template('api_docs.html', current_path='/api')

@astronomy_tools_bp.route('/api/distance', methods=['GET'])
def api_distance():
    ip = _client_ip()
    if not _rate_ok(ip, 'distance'):
        return jsonify({'error': 'Rate limit exceeded — max 1 request/second per IP.'}), 429

    z_raw = request.args.get('z')
    if not z_raw:
        return jsonify({
            'error': "Missing required parameter 'z' (redshift).",
            'example': '/api/distance?z=0.039&m=15.3',
        }), 400

    try:
        z      = get_float_arg('z')
        z_err  = get_float_arg('z_err')
        m      = get_float_arg('m')
        A      = get_float_arg('A',     0)
        H0     = get_float_arg('H0',    67.7)
        Om0    = get_float_arg('Om0',   0.309)
        Tcmb0  = get_float_arg('Tcmb0', 2.725)
    except ValueError as e:
        return jsonify({'error': f'Invalid parameter value: {e}'}), 400

    try:
        out = {
            'input': {'z': z, 'z_err': z_err, 'm': m, 'A': A},
            'cosmology': {'H0': H0, 'Om0': Om0, 'Tcmb0': Tcmb0,
                          'reference': 'Planck 2018 (A&A 641 A6)'},
            'distance': calculate_redshift_distance(z, z_err, H0=H0, Om0=Om0, Tcmb0=Tcmb0),
        }
        if m is not None:
            out['magnitude'] = calculate_absolute_magnitude(m, z, A, H0=H0, Om0=Om0, Tcmb0=Tcmb0)
        return jsonify({'success': True, 'result': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@astronomy_tools_bp.route('/api/coords', methods=['GET'])
def api_coords():
    ip = _client_ip()
    if not _rate_ok(ip, 'coords'):
        return jsonify({'error': 'Rate limit exceeded — max 1 request/second per IP.'}), 429

    ra_hms  = request.args.get('ra_hms')
    ra_deg  = request.args.get('ra_deg')
    dec_dms = request.args.get('dec_dms')
    dec_deg = request.args.get('dec_deg')

    if not any([ra_hms, ra_deg, dec_dms, dec_deg]):
        return jsonify({
            'error': 'Provide at least one of: ra_hms, ra_deg, dec_dms, dec_deg',
            'example': '/api/coords?ra_hms=12:34:56.78&dec_dms=-23:45:12.34',
        }), 400

    result = {}
    try:
        if ra_hms:
            result.update(convert_ra_hms_to_decimal(ra_hms))
        elif ra_deg:
            result.update(convert_ra_decimal_to_hms(float(ra_deg)))

        if dec_dms:
            result.update(convert_dec_dms_to_decimal(dec_dms))
        elif dec_deg:
            result.update(convert_dec_decimal_to_dms(float(dec_deg)))
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'success': True, 'result': result})

@astronomy_tools_bp.route('/api/date', methods=['GET'])
def api_date():
    ip = _client_ip()
    if not _rate_ok(ip, 'date'):
        return jsonify({'error': 'Rate limit exceeded — max 1 request/second per IP.'}), 429

    mjd  = request.args.get('mjd')
    jd   = request.args.get('jd')
    date = request.args.get('date')

    if not any([mjd, jd, date]):
        return jsonify({
            'error': "Provide one of: mjd, jd, date",
            'example': '/api/date?mjd=59000.5',
        }), 400

    try:
        if mjd:
            result = convert_mjd_to_date(float(mjd))
        elif jd:
            result = convert_jd_to_date(float(jd))
        else:
            result = convert_common_date_to_jd(date)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@astronomy_tools_bp.route('/api/finding_chart/surveys', methods=['GET'])
def api_finding_chart_surveys():
    """Return the list of available image surveys for /api/finding_chart/image."""
    return jsonify({
        'success': True,
        'default': 'DESI-color',
        'surveys': _FINDING_CHART_SURVEYS,
    })

def _db_lookup_coords(obj_name: str):
    """Look up an object by name in the transient DB.
    Returns (ra_str, dec_str, full_name) or raises ValueError if not found."""
    from app.db import get_tns_db_connection, OBJECT_COMPAT_COLS
    from app.db.transient import search_tns_objects

    conn = get_tns_db_connection()
    cur  = conn.cursor()
    row  = None
    for q in [
        f"SELECT {OBJECT_COMPAT_COLS} FROM transient.objects o WHERE (COALESCE(o.name_prefix,'') || COALESCE(o.name,'')) ILIKE %s",
        f"SELECT {OBJECT_COMPAT_COLS} FROM transient.objects o WHERE o.name ILIKE %s",
    ]:
        cur.execute(q, (obj_name,))
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            row  = dict(zip(cols, row))
            break
    conn.close()

    if not row:
        for r in search_tns_objects(search_term=obj_name, limit=20):
            pref = (r.get('name_prefix') or '').strip()
            nm   = (r.get('name') or '').strip()
            if (pref + nm).lower() == obj_name.lower() or nm.lower() == obj_name.lower():
                row = r
                break

    if not row:
        raise ValueError(f'Object "{obj_name}" not found in database.')

    ra  = row.get('ra')
    dec = row.get('declination') or row.get('dec')
    if ra is None or dec is None:
        raise ValueError(f'Object "{obj_name}" has no coordinates in database.')

    pref      = (row.get('name_prefix') or '').strip()
    name_only = (row.get('name') or '').strip()
    full      = (pref + name_only) if (pref or name_only) else obj_name
    return str(ra), str(dec), full

@astronomy_tools_bp.route('/api/finding_chart/image', methods=['GET'])
def api_finding_chart_image():
    """Return a finding chart as a PNG image (Content-Type: image/png). Rate limit: 1/30s."""
    ip = _client_ip()
    if not _rate_ok(ip, 'fc_image', interval=30.0):
        return Response('Rate limit exceeded — max 1 request per 30 seconds per IP.', 429, mimetype='text/plain')

    obj_name = request.args.get('obj_name', '').strip()
    ra_raw   = request.args.get('ra',  '').strip()
    dec_raw  = request.args.get('dec', '').strip()

    # obj_name → look up RA/Dec from DB
    db_full_name = None
    if obj_name:
        try:
            ra_raw, dec_raw, db_full_name = _db_lookup_coords(obj_name)
        except ValueError as e:
            return Response(str(e), 404, mimetype='text/plain')

    if not ra_raw or not dec_raw:
        return Response(
            "Provide ra+dec, or obj_name to look up coordinates from the database.\n"
            "Example: /api/finding_chart/image?obj_name=2025wny\n"
            "Example: /api/finding_chart/image?ra=12:34:56.78&dec=-23:45:12.34",
            400, mimetype='text/plain')

    # name = display label on chart; defaults to db full name or obj_name, then 'Target'
    name       = request.args.get('name', '').strip() or db_full_name or obj_name or 'Target'
    survey     = request.args.get('survey', 'DESI-color').strip()
    fov        = get_float_arg('fov', 10)
    invert     = request.args.get('invert', '0') == '1'
    mag_limit  = get_float_arg('mag_limit', 15)
    name_limit = get_float_arg('name_limit', 10)
    show_mag   = request.args.get('show_mag',   '1') != '0'
    show_names = request.args.get('show_names', '1') != '0'

    try:
        coord   = _resolve_target_coord(name, ra_raw, dec_raw)
        ra_deg  = coord.ra.deg
        dec_deg = coord.dec.deg
    except Exception as e:
        return Response(f'Invalid coordinates: {e}', 400, mimetype='text/plain')

    try:
        img_data, _ = _fetch_survey_image(survey, ra_deg, dec_deg, fov)
        if img_data is None:
            return Response(f'Failed to fetch image from survey "{survey}".', 500, mimetype='text/plain')

        img = Image.open(io.BytesIO(img_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        is_single = 'color' not in survey.lower()
        if invert and is_single:
            img = Image.fromarray(255 - np.array(img))

        star_data, band_used, _ = _query_nearby_stars(ra_deg, dec_deg, fov, mag_limit)

        png_b64 = _render_finding_chart(
            img, ra_deg, dec_deg, fov, name,
            star_data, band_used, mag_limit, name_limit, invert, survey,
            show_mag=show_mag, show_names=show_names,
        )
        png_bytes = base64.b64decode(png_b64)

        safe = re.sub(r'[^\w.-]', '_', name)[:40]
        return Response(
            png_bytes,
            mimetype='image/png',
            headers={'Content-Disposition': f'inline; filename="finding_chart_{safe}.png"'},
        )
    except Exception as e:
        traceback.print_exc()
        return Response(f'Error generating chart: {e}', 500, mimetype='text/plain')

@astronomy_tools_bp.route('/api/visibility/image', methods=['GET'])
def api_visibility_image():
    """Return a nightly visibility plot as a JPEG image. Rate limit: 1/15s."""
    ip = _client_ip()
    if not _rate_ok(ip, 'vis_image', interval=15.0):
        return Response('Rate limit exceeded — max 1 request per 15 seconds per IP.', 429, mimetype='text/plain')

    date_raw = request.args.get('date', '').strip()
    obj_name = request.args.get('obj_name', '').strip()
    ra_raw   = request.args.get('ra',   '').strip()
    dec_raw  = request.args.get('dec',  '').strip()

    # obj_name → look up RA/Dec from DB
    db_full_name = None
    if obj_name:
        try:
            ra_raw, dec_raw, db_full_name = _db_lookup_coords(obj_name)
        except ValueError as e:
            return Response(str(e), 404, mimetype='text/plain')

    if not date_raw:
        return Response("Missing required parameter: date (YYYY-MM-DD)", 400, mimetype='text/plain')
    if not ra_raw or not dec_raw:
        return Response(
            "Provide ra+dec, or obj_name to look up coordinates from the database.\n"
            "Example: /api/visibility/image?date=2026-06-07&obj_name=2025wny",
            400, mimetype='text/plain')

    name    = request.args.get('name', '').strip() or db_full_name or obj_name or 'Target'
    lon_raw = request.args.get('lon', '120:52:21.5').strip()
    lat_raw = request.args.get('lat', '23:28:10.0').strip()
    alt_m   = get_float_arg('alt', 2800)
    tz_off  = get_int_arg('tz', 8)

    try:
        date_clean = date_raw.replace('-', '').replace('/', '')
        if len(date_clean) != 8:
            return Response('date must be YYYY-MM-DD', 400, mimetype='text/plain')

        next_d      = str(int(date_clean) + 1)
        obs_date_f  = f"{date_clean[:4]}/{date_clean[4:6]}/{date_clean[6:]}"
        next_date_f = f"{next_d[:4]}/{next_d[4:6]}/{next_d[6:]}"

        ra_c  = re.sub(r'[hH]', ':', re.sub(r'[mM]', ':', re.sub(r'[sS]', '', str(ra_raw)))).strip()
        dec_c = re.sub(r'[dD°]', ':', re.sub(r"[mM′']", ':', re.sub(r'[sS″"]', '', str(dec_raw)))).strip()

        ephem_target = obs.create_ephem_target(name, ra_c, dec_c)

        timezone_name = obs.get_timezone_name(tz_off)
        if not timezone_name:
            return Response(f'Invalid timezone offset: {tz_off}', 400, mimetype='text/plain')

        lon_f = parse_coordinate(lon_raw)
        lat_f = parse_coordinate(lat_raw)
        obs_site = obs.create_ephem_observer(name, lon_f, lat_f, alt_m)

        obs_start = ephem.Date(f'{obs_date_f} 17:00:00')
        obs_end   = ephem.Date(f'{next_date_f} 09:00:00')
        start_loc = obs.dt_naive_to_dt_aware(obs_start.datetime(), timezone_name)
        end_loc   = obs.dt_naive_to_dt_aware(obs_end.datetime(),   timezone_name)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
            tmp_path = tf.name
        try:
            obs.plot_night_observing_tracks(
                [ephem_target], obs_site, start_loc, end_loc,
                simpletracks=True, toptime='local', timezone='calculate',
                n_steps=500, savepath=tmp_path,
            )
            with open(tmp_path, 'rb') as fh:
                img_bytes = fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        safe = re.sub(r'[^\w.-]', '_', name)[:40]
        return Response(
            img_bytes,
            mimetype='image/jpeg',
            headers={'Content-Disposition': f'inline; filename="visibility_{date_raw}_{safe}.jpg"'},
        )
    except Exception as e:
        traceback.print_exc()
        return Response(f'Error generating plot: {e}', 500, mimetype='text/plain')

@astronomy_tools_bp.route('/api/objects/<path:object_name>', methods=['GET'])
def api_public_object(object_name):
    """Public object API.
    No key  → metadata only (name, coords, redshift, type, etc.).
    api_key → + photometry + spectroscopy filtered by caller's access permissions.
    Rate limit: 1 req/s per IP.
    """
    ip = _client_ip()
    if not _rate_ok(ip, 'obj_lookup'):
        return jsonify({'error': 'Rate limit exceeded — max 1 request/second per IP.'}), 429

    import urllib.parse as _urlparse
    import math as _math

    object_name = _urlparse.unquote(object_name).strip()

    # Optional API key
    api_key = request.args.get('api_key', '').strip()
    auth_user = None
    if api_key:
        from app.db.auth import get_user_by_api_key as _get_user
        auth_user = _get_user(api_key)
        if not auth_user:
            return jsonify({'error': 'Invalid API key.'}), 401

    def _san(v):
        """Recursively sanitize NaN/Inf for JSON serialization."""
        if isinstance(v, list):
            return [_san(x) for x in v]
        if isinstance(v, dict):
            return {k: _san(w) for k, w in v.items()}
        if isinstance(v, float) and not _math.isfinite(v):
            return None
        return v

    def _build_meta(obj):
        """Extract the most useful public fields from the raw DB row."""
        prefix  = (obj.get('name_prefix') or '').strip()
        name    = (obj.get('name') or '').strip()
        full    = prefix + name if (prefix or name) else obj.get('full_name', '')
        ra_deg  = obj.get('ra')
        dec_deg = obj.get('declination') or obj.get('dec')
        # HMS/DMS conversion (best-effort, no crash)
        ra_hms, dec_dms = None, None
        try:
            from app.services.astro.coordinate_converter import (
                convert_ra_decimal_to_hms, convert_dec_decimal_to_dms
            )
            if ra_deg is not None:
                ra_hms  = convert_ra_decimal_to_hms(float(ra_deg)).get('ra_hms')
            if dec_deg is not None:
                dec_dms = convert_dec_decimal_to_dms(float(dec_deg)).get('dec_dms')
        except Exception:
            pass
        redshift     = obj.get('redshift')
        distance_mpc = obj.get('distance_mpc')
        if distance_mpc is None and redshift is not None:
            try:
                dist_result  = calculate_redshift_distance(float(redshift))
                distance_mpc = dist_result.get('distance_mpc')
            except Exception:
                pass

        return {
            'name':              full,
            'name_prefix':       prefix or None,
            'type':              obj.get('type') or obj.get('object_type'),
            'ra_deg':            float(ra_deg)  if ra_deg  is not None else None,
            'dec_deg':           float(dec_deg) if dec_deg is not None else None,
            'ra_hms':            ra_hms,
            'dec_dms':           dec_dms,
            'discovery_date':    str(obj.get('discoverydate') or obj.get('discovery_date') or '')[:10] or None,
            'discovery_mag':     obj.get('discoverymag') or obj.get('discovery_mag'),
            'reporting_group':   obj.get('reporting_group') or obj.get('source_group'),
            'redshift':          redshift,
            'distance_mpc':      round(distance_mpc, 2) if distance_mpc is not None else None,
            'brightest_abs_mag': obj.get('brightest_abs_mag'),
            'internal_names':    obj.get('internal_names'),
            'status':            obj.get('tag') or obj.get('status'),
            'tags':              obj.get('tags'),
        }

    try:
        from app.db import get_tns_db_connection, OBJECT_COMPAT_COLS
        from app.db.transient import search_tns_objects

        conn = get_tns_db_connection()
        cur  = conn.cursor()
        obj  = None
        for q in [
            f"SELECT {OBJECT_COMPAT_COLS} FROM transient.objects o WHERE (COALESCE(o.name_prefix,'') || COALESCE(o.name,'')) ILIKE %s",
            f"SELECT {OBJECT_COMPAT_COLS} FROM transient.objects o WHERE o.name ILIKE %s",
        ]:
            cur.execute(q, (object_name,))
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                obj  = dict(zip(cols, row))
                break
        conn.close()

        if not obj:
            for r in search_tns_objects(search_term=object_name, limit=50):
                pref = (r.get('name_prefix') or '').strip()
                nm   = (r.get('name') or '').strip()
                if (pref + nm).lower() == object_name.lower() or nm.lower() == object_name.lower():
                    obj = r
                    break

        if not obj:
            return jsonify({'error': f'Object "{object_name}" not found.'}), 404

        obj  = _san(obj)
        meta = _san(_build_meta(obj))
        full_name = meta['name'] or object_name

        out = {
            'success':  True,
            'name':     full_name,
            'metadata': meta,
        }

        if auth_user:
            from app.db.transient import TNSObjectDB
            from app.db.auth import filter_by_source_permissions

            user_email  = auth_user.get('email')
            user_groups = auth_user.get('groups', [])
            is_admin    = auth_user.get('is_admin', False)

            try:
                phot = TNSObjectDB.get_photometry(full_name)
                phot = _san(phot)
                phot = filter_by_source_permissions(
                    full_name, 'phot', phot,
                    user_email=user_email, user_groups=user_groups, is_admin=is_admin,
                )
                out['photometry']       = phot
                out['photometry_count'] = len(phot)
            except Exception as pe:
                out['photometry_error'] = str(pe)

            try:
                spectra = TNSObjectDB.get_spectrum_list(full_name)
                spectra = _san(spectra)
                spectra = filter_by_source_permissions(
                    full_name, 'spec', spectra,
                    user_email=user_email, user_groups=user_groups, is_admin=is_admin,
                )
                out['spectra']       = spectra
                out['spectra_count'] = len(spectra)
            except Exception as se:
                out['spectra_error'] = str(se)

            out['requested_by'] = user_email

        return jsonify(out)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
