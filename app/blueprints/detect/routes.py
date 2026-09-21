"""DETECT host screening pages and review APIs — routes (split from detect_routes.py)."""
from flask import render_template, request, jsonify, flash, redirect, url_for, session, send_file
from app.db.transient import (
    update_cross_match_flag,
    tns_object_db,
    get_target_image,
    get_detect_image_by_id,
    set_cross_match_host,
    set_object_redshift,
    reject_cross_match_hosts,
    release_cross_match_host,
    update_object_status,
    get_detect_metadata,
    get_detect_overview,
)
import io
import urllib.parse
import time
import logging

logger = logging.getLogger(__name__)
from . import detect_bp
from .cache import (
    _detect_page_is_building,
    _get_detect_lc_cache,
    _get_detect_page_payload_swr,
    _log_detect_cache_stats,
    _set_detect_lc_cache,
    _soft_invalidate_page_cache,
    _start_detect_page_build,
    _start_tracker_build,
)
from .helpers import _TRACKER_CACHE
from .payload import _build_detect_lc_payload, _parse_float_or_none


@detect_bp.route('/detect_image/<target_name>')
def detect_image(target_name):
    if 'user' not in session:
        return "Unauthorized", 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return "Unauthorized", 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return "Unauthorized", 401
        
    image_data = get_target_image(target_name)
    if image_data:
        return send_file(
            io.BytesIO(image_data),
            mimetype='image/png',
            as_attachment=False,
            download_name=f'{target_name}_marked.png'
        )
    else:
        return "Image not found", 404

@detect_bp.route('/detect_image_by_id/<int:image_id>')
def detect_image_by_id(image_id):
    if 'user' not in session:
        return "Unauthorized", 401
    image_data = get_detect_image_by_id(image_id)
    if image_data:
        if request.args.get('trim') == '1':
            image_data = _trim_figure_margins(image_data)
        return send_file(
            io.BytesIO(image_data),
            mimetype='image/png',
            as_attachment=False,
        )
    return "Image not found", 404


def _trim_figure_margins(png_bytes: bytes) -> bytes:
    """Crop a matplotlib finder figure to its image block: drop the white background,
    title lines and axis margins, keeping the survey cut-out (and its overlays) untouched.
    Falls back to the original bytes on any error."""
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(io.BytesIO(png_bytes)).convert('RGB')
        a = np.asarray(im)
        dark = a.mean(axis=2) < 200                     # anything that is not the white figure background
        rows = np.where(dark.mean(axis=1) > 0.5)[0]     # rows/cols that are mostly image, not text
        cols = np.where(dark.mean(axis=0) > 0.5)[0]
        if len(rows) < 50 or len(cols) < 50:
            return png_bytes
        box = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
        out = io.BytesIO()
        im.crop(box).save(out, format='PNG', optimize=True)
        return out.getvalue()
    except Exception as exc:  # pragma: no cover
        logger.warning("detect image trim failed: %s", exc)
        return png_bytes

@detect_bp.route('/api/set_host', methods=['POST'])
def set_host():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    data = request.json
    match_id = data.get('match_id')
    target_name = data.get('target_name')
    redshift = data.get('redshift')
    status = data.get('status', 'followup')          # 'followup' | 'snoozed' | 'keep'

    if not match_id or not target_name:
        return jsonify({'success': False, 'message': 'Missing parameters'})
    if status not in ('followup', 'snoozed', 'keep'):
        return jsonify({'success': False, 'message': 'Invalid status'})

    # 1. cross_matches: is_host + the person's pin (DETECT keeps it on re-runs)
    if set_cross_match_host(match_id, target_name, session['user'].get('email')):
        # 2. object status is the reviewer's call
        if status != 'keep':
            update_object_status(target_name, status)
        _soft_invalidate_page_cache()
        _TRACKER_CACHE['expires_at'] = 0.0
        _start_tracker_build()
        # 3. the host's z becomes the object's z
        z_val = _parse_float_or_none(redshift)
        if z_val is not None:
            set_object_redshift(target_name, z_val)            # full precision; DETECT keeps M_abs
            return jsonify({'success': True})
        return jsonify({'success': True, 'message': 'Host set, but no redshift to update'})
    else:
        return jsonify({'success': False, 'message': 'Database error'})

@detect_bp.route('/api/unset_host', methods=['POST'])
def unset_host():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json
    target_name = data.get('target_name')

    if not target_name:
        return jsonify({'success': False, 'message': 'Missing parameters'})

    # Reopen: the person's decision is withdrawn, the rule's host stays visible.
    if release_cross_match_host(target_name):
        # Reset object status back to Inbox so it leaves the Follow-up tracker
        update_object_status(target_name, 'object')
        # Invalidate both caches so next page load gets fresh data
        _soft_invalidate_page_cache()
        _TRACKER_CACHE['expires_at'] = 0.0
        _start_tracker_build()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Database error'})

@detect_bp.route('/api/get_object_status')
def get_object_status_api():
    """Lightweight endpoint: return current obj_status for one target."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    target_name = request.args.get('name', '').strip()
    if not target_name:
        return jsonify({'success': False, 'message': 'Missing name'})
    obj_details = tns_object_db.get_object_details(target_name)
    raw_status  = (obj_details or {}).get('status', '') or ''
    _NORM = {'Follow-up': 'followup', 'Finish': 'finished',
             'Inbox': 'object', 'Snoozed': 'snoozed'}
    obj_status = _NORM.get(raw_status, raw_status.lower() or 'object')
    return jsonify({'success': True, 'obj_status': obj_status})

@detect_bp.route('/api/set_object_status', methods=['POST'])
def set_object_status():
    """Set object status from DETECT page. Accepts 'finished' or 'followup'."""
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json
    target_name = data.get('target_name')
    status = data.get('status')  # 'finished', 'followup', or 'object' (reset to Inbox)

    if not target_name or status not in ('finished', 'followup', 'object', 'snoozed'):
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'})

    if update_object_status(target_name, status):
        # Invalidate page cache so next load gets fresh data
        _soft_invalidate_page_cache()
        # Soft-invalidate tracker cache: keep stale value for SWR, trigger bg rebuild
        _TRACKER_CACHE['expires_at'] = 0.0
        _start_tracker_build()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Database error'})

@detect_bp.route('/api/mark_no_host', methods=['POST'])
def mark_no_host():
    """Mark target as having no host: cross_match is_host=False, status=Snoozed."""
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.json
    target_name = data.get('target_name')
    if not target_name:
        return jsonify({'success': False, 'message': 'Missing parameters'})

    # Every candidate rejected by this person; DETECT honours that on re-runs.
    reject_cross_match_hosts(target_name, session['user'].get('email'))
    # Set status to Snoozed
    if update_object_status(target_name, 'snoozed'):
        _soft_invalidate_page_cache()
        _TRACKER_CACHE['expires_at'] = 0.0
        _start_tracker_build()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Database error'})

@detect_bp.route('/detect')
def detect_results():
    if 'user' not in session:
        flash('Please log in to access Detect Results.', 'warning')
        return redirect(url_for('basic.login'))
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        flash('Access denied. This page is not available for Guest users.', 'error')
        return redirect(url_for('basic.home'))
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        flash('Access denied. This page is not available for Guest users.', 'error')
        return redirect(url_for('basic.home'))
        
    # Get date from query parameter
    selected_date = request.args.get('detect_results')
    
    # Single cached call for both available_dates and daily_counts (Marshal pattern)
    metadata = get_detect_metadata()
    available_dates = metadata.get('available_dates') or []
    latest_date = available_dates[0] if available_dates else None

    # If no date selected, render the homepage
    if not selected_date:
        daily_counts = metadata.get('daily_counts', [])
        # Prefetch latest date in background to keep first detailed load responsive.
        if latest_date:
            cached_latest, _ = _get_detect_page_payload_swr(latest_date)
            if cached_latest is None and not _detect_page_is_building(latest_date):
                _start_detect_page_build(latest_date)
        return render_template('detect_home.html',
                               latest_date=latest_date,
                               daily_counts=daily_counts,
                               overview=get_detect_overview(),
                               current_path='/detect')

    payload, is_fresh = _get_detect_page_payload_swr(selected_date)
    if payload:
        logger.info('[DETECT] serving cached payload date=%s fresh=%s', selected_date, is_fresh)
        return render_template('detect_results.html', **payload)

    if not _detect_page_is_building(selected_date):
        _start_detect_page_build(selected_date)

    # Fast fallback page while heavy payload builds in background.
    return render_template('detect_results_loading.html',
                           selected_date=selected_date,
                           available_dates=available_dates,
                           current_path='/detect')

@detect_bp.route('/api/detect/followup_tracker')
def followup_tracker_api():
    """SWR-cached endpoint: instant on repeat calls, refreshes in background."""
    if 'user' not in session:
        return jsonify({'success': False}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False}), 401

    now         = time.time()
    cached_val  = _TRACKER_CACHE['value']
    is_fresh    = cached_val is not None and now < _TRACKER_CACHE['expires_at']

    if cached_val is not None:
        # SWR: return stale data immediately, refresh in background if expired
        if not is_fresh:
            _start_tracker_build()
        return jsonify({'success': True, 'tracker': cached_val, 'cached': True,
                        'fresh': is_fresh})

    # Cold cache: return empty immediately and start background build.
    # Client will poll again; avoids blocking for 10-20 s on first call.
    _start_tracker_build()
    return jsonify({'success': True, 'tracker': [], 'cached': False,
                    'building': True, 'message': 'Building tracker, please retry shortly.'})

@detect_bp.route('/api/detect/cache_status')
def detect_cache_status_api():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    selected_date = request.args.get('detect_results', '').strip()
    if not selected_date:
        return jsonify({'success': False, 'message': 'Missing detect_results date'}), 400

    payload, fresh = _get_detect_page_payload_swr(selected_date)
    building = _detect_page_is_building(selected_date)

    if payload is None and not building:
        _start_detect_page_build(selected_date)
        building = True

    _log_detect_cache_stats('cache-status', selected_date=selected_date)

    return jsonify({
        'success': True,
        'ready': payload is not None,
        'fresh': fresh,
        'building': building,
    })

@detect_bp.route('/api/detect/lightcurve/<path:target_name>')
def detect_lightcurve_api(target_name):
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    target_name = urllib.parse.unquote(target_name or '').strip()
    if not target_name:
        return jsonify({'success': False, 'message': 'Missing target name'}), 400

    force_refresh = request.args.get('refresh', '0').lower() in ('1', 'true', 'yes')

    cached_lc = _get_detect_lc_cache(target_name)
    if not force_refresh and cached_lc is not None:
        cached = dict(cached_lc)
        cached['cached'] = True
        _log_detect_cache_stats('lc-hit', target_name=target_name)
        return jsonify(cached)

    _log_detect_cache_stats('lc-miss', target_name=target_name)

    try:
        payload = _build_detect_lc_payload(target_name)
        payload['cached'] = False
        _set_detect_lc_cache(target_name, payload)
        _log_detect_cache_stats('lc-build-complete', target_name=target_name)

        return jsonify(payload)
    except Exception as e:
        logger.error('Error loading LC for %s: %s', target_name, e)
        return jsonify({'success': False, 'message': str(e)}), 500

@detect_bp.route('/detect/archives')
def detect_archives():
    if 'user' not in session:
        flash('Please log in to access Detect Archives.', 'warning')
        return redirect(url_for('basic.login'))
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        flash('Access denied. This page is not available for Guest users.', 'error')
        return redirect(url_for('basic.home'))
    daily_counts = get_detect_metadata().get('daily_counts', [])
    return render_template('detect_archives.html',
                           daily_counts=daily_counts,
                           current_path='/detect/archives')

@detect_bp.route('/api/toggle_flag', methods=['POST'])
def toggle_flag():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    data = request.json
    result_id = data.get('id')
    flag_value = data.get('flag')
    
    if update_cross_match_flag(result_id, flag_value):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Database error'})
