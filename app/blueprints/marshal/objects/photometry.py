"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — photometry (split from object_routes.py)."""
import math
import urllib.parse
from flask import session, request, jsonify, Response
from app.db.transient import search_tns_objects, TNSObjectDB
from app.core.request_validation import get_float_arg
from app.db.auth import check_object_access, filter_by_source_permissions
from app.services.photometry.data_processing import DataVisualization
from app.services.astro import ext_M_calculator
import os as _os
import logging
from app.core.auth import admin_required, login_required

logger = logging.getLogger(__name__)
from . import objects_bp
from .helpers import sanitize_for_json


@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry')
def get_object_photometry(year, letters):
    object_name = f"{year}{letters}"
    user = session.get('user', {})
    user_email = user.get('email') if user else None
    user_groups = user.get('groups', []) if user else []
    is_admin = user.get('is_admin', False) if user else False

    logger.info("[Photometry] fetch request: object=%s user=%s", object_name, user_email or 'guest')
    try:
        TNSObjectDB.sync_last_photometry_date(object_name)
        photometry = TNSObjectDB.get_photometry(object_name)
        photometry = sanitize_for_json(photometry)
        photometry = filter_by_source_permissions(
            object_name, 'phot', photometry,
            user_email=user_email, user_groups=user_groups, is_admin=is_admin
        )
        logger.info("[Photometry] fetched OK: object=%s points=%d user=%s",
                    object_name, len(photometry), user_email or 'guest')
        return jsonify({'success': True, 'photometry': photometry, 'count': len(photometry)})
    except Exception as e:
        logger.error("[Photometry] fetch error: object=%s error=%s", object_name, str(e))
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry', methods=['POST'])
@admin_required
def upload_photometry(year, letters):
    
    object_name = f"{year}{letters}"
    data = request.get_json()
    
    try:
        point_id = TNSObjectDB.add_photometry_point(
            object_name=object_name,
            mjd=float(data.get('mjd')),
            magnitude=float(data.get('magnitude')) if data.get('magnitude') else None,
            magnitude_error=float(data.get('magnitude_error')) if data.get('magnitude_error') else None,
            filter_name=data.get('filter'),
            telescope=data.get('telescope')
        )
        
        return jsonify({
            'success': True,
            'message': 'Photometry point added successfully',
            'id': point_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/batch', methods=['POST'])
@admin_required
def upload_photometry_batch(year, letters):
    object_name = f"{year}{letters}"
    data = request.get_json()
    points = data.get('points', [])
    if not points:
        return jsonify({'error': 'No points provided'}), 400
    try:
        inserted = TNSObjectDB.add_photometry_batch(object_name, points)
        return jsonify({'success': True, 'inserted': inserted, 'total': len(points)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/photometry/<int:point_id>', methods=['DELETE'])
@admin_required
def delete_photometry_point(point_id):
    
    try:
        if TNSObjectDB.delete_photometry_point(point_id):
            return jsonify({
                'success': True,
                'message': 'Photometry point deleted successfully'
            })
        else:
            return jsonify({'error': 'Photometry point not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/download')
@login_required(error='Access denied', status=403)
def download_photometry(year, letters):
    """Download photometry as .dat file with optional filters."""

    object_name = f"{year}{letters}"

    telescopes_param = request.args.get('telescopes', '')
    filters_param    = request.args.get('filters', '')
    mjd_min          = get_float_arg('mjd_min')
    mjd_max          = get_float_arg('mjd_max')
    include_nondet   = request.args.get('include_nondet', 'true').lower() != 'false'

    sel_telescopes = {t.strip() for t in telescopes_param.split(',') if t.strip()}
    sel_filters    = {f.strip() for f in filters_param.split(',') if f.strip()}

    try:
        phot = TNSObjectDB.get_photometry(object_name)

        rows = []
        for p in phot:
            if sel_telescopes and (p.get('telescope') or '') not in sel_telescopes:
                continue
            if sel_filters and (p.get('filter') or '') not in sel_filters:
                continue
            if mjd_min is not None and p.get('mjd', 0) < mjd_min:
                continue
            if mjd_max is not None and p.get('mjd', 0) > mjd_max:
                continue
            is_upper = p.get('magnitude_error') is None
            if not include_nondet and is_upper:
                continue
            rows.append(p)

        lines = [
            f"# {object_name} photometry",
            "# MJD magnitude error filter telescope",
        ]
        for p in rows:
            mjd  = p.get('mjd', '')
            mag  = p.get('magnitude')
            err  = p.get('magnitude_error')
            flt  = p.get('filter') or ''
            tel  = p.get('telescope') or 'Unknown'
            is_upper = err is None
            if is_upper:
                mag_str = f">{mag:.6f}" if mag is not None else ">nan"
                err_str = "nan"
            else:
                mag_str = f"{mag:.6f}" if mag is not None else "nan"
                err_str = f"{err:.6f}"
            lines.append(f"{mjd:.6f}  {mag_str}  {err_str}  {flt}  {tel}")

        content = '\n'.join(lines) + '\n'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{object_name}_phot.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/plot')
def get_object_photometry_plot(year, letters):
    object_name = f"{year}{letters}"

    user = session.get('user')
    user_email = user.get('email', '') if user else None
    user_groups = user.get('groups', []) if user else []
    is_admin = user.get('is_admin', False) if user else False

    logger.info("[Photometry/plot] request: object=%s user=%s", object_name, user_email or 'guest')

    if user and not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})

    try:
        # Get object data for redshift, ra, and dec
        results = search_tns_objects(search_term=object_name, limit=1)
        obj_data = results[0] if results else {}
        redshift = obj_data.get('redshift')
        ra = obj_data.get('ra')
        dec = obj_data.get('declination')

        photometry_data = TNSObjectDB.get_photometry(object_name)

        if not photometry_data:
            logger.info("[Photometry/plot] no data: object=%s", object_name)
            return jsonify({'success': True, 'plot_html': None, 'message': 'No photometry data available'})

        # Filter by source permissions — public points visible to everyone
        photometry_data = filter_by_source_permissions(
            object_name, 'phot', photometry_data,
            user_email=user_email, user_groups=user_groups, is_admin=is_admin
        )

        if not photometry_data:
            return jsonify({'success': True, 'plot_json': None,
                            'message': 'Login to view photometry', 'data_count': 0})

        apply_extinction = request.args.get('extinction', 'true').lower() == 'true'
        apply_k_corr = request.args.get('k_corr', 'true').lower() == 'true'

        logger.info("[Photometry/plot] plotting: object=%s points=%d z=%s extinction=%s k_corr=%s",
                    object_name, len(photometry_data), redshift, apply_extinction, apply_k_corr)

        plot_json = DataVisualization.create_photometry_plot_from_db(
            photometry_data,
            redshift=redshift,
            ra=ra,
            dec=dec,
            apply_extinction=apply_extinction,
            apply_k_corr=apply_k_corr,
            as_json=True
        )

        # Compute distance modulus for KN model overlay
        _dist_mod2 = 0.0
        if redshift:
            try:
                _z2 = float(redshift)
                if _z2 > 0:
                    if ext_M_calculator:
                        _d2, _ = ext_M_calculator.z_to_lmd(_z2)
                        if isinstance(_d2, (int, float)):
                            _dist_mod2 = 5 * math.log10(_d2 * 1e6) - 5
                    else:
                        _dist_mod2 = 5 * math.log10((299792.458 * _z2 / 70.0) * 1e6) - 5
            except Exception:
                _dist_mod2 = 0.0

        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(photometry_data),
            'distance_modulus': round(_dist_mod2, 4),
            'redshift': redshift,
        })
    except Exception as e:
        logger.error("[Photometry/plot] error: object=%s error=%s", object_name, str(e))
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry')
def get_object_photometry_generic(object_name):
    object_name = urllib.parse.unquote(object_name)
    user = session.get('user', {})
    user_email = user.get('email') if user else None
    user_groups = user.get('groups', []) if user else []
    is_admin = user.get('is_admin', False) if user else False
    logger.info("[Photometry] fetch request: object=%s user=%s", object_name, user_email or 'guest')
    try:
        TNSObjectDB.sync_last_photometry_date(object_name)
        photometry = TNSObjectDB.get_photometry(object_name)
        photometry = sanitize_for_json(photometry)
        photometry = filter_by_source_permissions(
            object_name, 'phot', photometry,
            user_email=user_email, user_groups=user_groups, is_admin=is_admin
        )
        logger.info("[Photometry] fetched OK: object=%s points=%d user=%s",
                    object_name, len(photometry), user_email or 'guest')
        return jsonify({'success': True, 'photometry': photometry, 'count': len(photometry)})
    except Exception as e:
        logger.error("[Photometry] fetch error: object=%s error=%s", object_name, str(e))
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry', methods=['POST'])
@admin_required
def upload_photometry_generic(object_name):
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    try:
        point_id = TNSObjectDB.add_photometry_point(
            object_name=object_name,
            mjd=float(data.get('mjd')),
            magnitude=float(data.get('magnitude')) if data.get('magnitude') else None,
            magnitude_error=float(data.get('magnitude_error')) if data.get('magnitude_error') else None,
            filter_name=data.get('filter'),
            telescope=data.get('telescope')
        )
        return jsonify({'success': True, 'message': 'Photometry point added successfully', 'id': point_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry/batch', methods=['POST'])
@admin_required
def upload_photometry_batch_generic(object_name):
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    points = data.get('points', [])
    if not points:
        return jsonify({'error': 'No points provided'}), 400
    try:
        inserted = TNSObjectDB.add_photometry_batch(object_name, points)
        return jsonify({'success': True, 'inserted': inserted, 'total': len(points)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry/download')
@login_required(error='Access denied', status=403)
def download_photometry_generic(object_name):
    object_name = urllib.parse.unquote(object_name)

    telescopes_param = request.args.get('telescopes', '')
    filters_param    = request.args.get('filters', '')
    mjd_min          = get_float_arg('mjd_min')
    mjd_max          = get_float_arg('mjd_max')
    include_nondet   = request.args.get('include_nondet', 'true').lower() != 'false'

    sel_telescopes = {t.strip() for t in telescopes_param.split(',') if t.strip()}
    sel_filters    = {f.strip() for f in filters_param.split(',') if f.strip()}

    try:
        phot = TNSObjectDB.get_photometry(object_name)
        rows = []
        for p in phot:
            if sel_telescopes and (p.get('telescope') or '') not in sel_telescopes:
                continue
            if sel_filters and (p.get('filter') or '') not in sel_filters:
                continue
            if mjd_min is not None and p.get('mjd', 0) < mjd_min:
                continue
            if mjd_max is not None and p.get('mjd', 0) > mjd_max:
                continue
            if not include_nondet and p.get('magnitude_error') is None:
                continue
            rows.append(p)

        lines = [f"# {object_name} photometry", "# MJD magnitude error filter telescope"]
        for p in rows:
            mjd = p.get('mjd', '')
            mag = p.get('magnitude')
            err = p.get('magnitude_error')
            flt = p.get('filter') or ''
            tel = p.get('telescope') or 'Unknown'
            if err is None:
                mag_str = f">{mag:.6f}" if mag is not None else ">nan"
                err_str = "nan"
            else:
                mag_str = f"{mag:.6f}" if mag is not None else "nan"
                err_str = f"{err:.6f}"
            lines.append(f"{mjd:.6f}  {mag_str}  {err_str}  {flt}  {tel}")

        content = '\n'.join(lines) + '\n'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{object_name}_phot.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry/plot')
def get_object_photometry_plot_generic(object_name):
    object_name = urllib.parse.unquote(object_name)

    user = session.get('user')
    user_email = user.get('email', '') if user else None
    user_groups = user.get('groups', []) if user else []
    is_admin = user.get('is_admin', False) if user else False

    logger.info("[Photometry/plot] request: object=%s user=%s", object_name, user_email or 'guest')

    try:
        if user and not check_object_access(object_name, user_email):
            return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})

        results = search_tns_objects(search_term=object_name, limit=1)

        if not results:
            return jsonify({'success': False, 'error': f'Object {object_name} not found'}), 404

        photometry_data = TNSObjectDB.get_photometry(object_name)

        if not photometry_data:
            logger.info("[Photometry/plot] no data: object=%s", object_name)
            return jsonify({'success': True, 'plot_html': None,
                            'message': 'No photometry data available for this object'})

        # Filter by source permissions — public points visible to everyone
        photometry_data = filter_by_source_permissions(
            object_name, 'phot', photometry_data,
            user_email=user_email, user_groups=user_groups, is_admin=is_admin
        )

        if not photometry_data:
            return jsonify({'success': True, 'plot_json': None,
                            'message': 'Login to view photometry', 'data_count': 0})

        # Get redshift, ra, dec from object data
        redshift = results[0].get('redshift')
        ra = results[0].get('ra')
        dec = results[0].get('declination')

        apply_extinction = request.args.get('extinction', 'true').lower() == 'true'
        apply_k_corr = request.args.get('k_corr', 'true').lower() == 'true'

        logger.info("[Photometry/plot] plotting: object=%s points=%d z=%s extinction=%s k_corr=%s",
                    object_name, len(photometry_data), redshift, apply_extinction, apply_k_corr)

        plot_json = DataVisualization.create_photometry_plot_from_db(
            photometry_data,
            redshift=redshift,
            ra=ra,
            dec=dec,
            apply_extinction=apply_extinction,
            apply_k_corr=apply_k_corr,
            as_json=True
        )

        # Compute distance modulus for KN model overlay
        _dist_mod = 0.0
        if redshift:
            try:
                _z = float(redshift)
                if _z > 0:
                    if ext_M_calculator:
                        _d_mpc, _ = ext_M_calculator.z_to_lmd(_z)
                        if isinstance(_d_mpc, (int, float)):
                            _dist_mod = 5 * math.log10(_d_mpc * 1e6) - 5
                    else:
                        _d_mpc = (299792.458 * _z) / 70.0
                        _dist_mod = 5 * math.log10(_d_mpc * 1e6) - 5
            except Exception:
                _dist_mod = 0.0

        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(photometry_data),
            'distance_modulus': round(_dist_mod, 4),
            'redshift': redshift,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error("[Photometry/plot] error: object=%s error=%s", object_name, str(e))
        return jsonify({'success': False, 'error': str(e)}), 500

_KN_MODEL_CACHE = None

def _parse_kn_model():
    global _KN_MODEL_CACHE
    if _KN_MODEL_CACHE is not None:
        return _KN_MODEL_CACHE
    from app.paths import RESOURCES_DIR
    path = _os.path.join(RESOURCES_DIR, 'kn_lc_mag.txt')
    filters = {}
    current_filter = None
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                # Check for filter header: "# Filter: sdss::g"
                if line.startswith('# Filter:'):
                    raw = line.split(':', 1)[1].strip()
                    # sdss::g → g
                    current_filter = raw.split('::')[-1] if '::' in raw else raw
                    filters[current_filter] = {'time': [], 'min': [], 'median': [], 'max': []}
                continue
            if current_filter is None:
                continue
            parts = line.split()
            if len(parts) == 4:
                try:
                    t, mn, med, mx = map(float, parts)
                    filters[current_filter]['time'].append(t)
                    filters[current_filter]['min'].append(mn)
                    filters[current_filter]['median'].append(med)
                    filters[current_filter]['max'].append(mx)
                except ValueError:
                    pass
    _KN_MODEL_CACHE = filters
    return filters

@objects_bp.route('/api/kn_model')
@login_required(error='Access denied', status=403)
def api_kn_model():
    try:
        return jsonify({'success': True, 'model': _parse_kn_model()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
