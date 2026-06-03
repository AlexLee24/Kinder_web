import logging
import os
from collections import OrderedDict
from flask import render_template, request, jsonify, flash, redirect, url_for, session, send_file

logger = logging.getLogger(__name__)
from modules.database.transient import (get_cross_match_results, update_cross_match_flag, get_available_dates,
    get_daily_match_counts, tns_object_db, get_target_image, get_detect_image_by_id, set_cross_match_host,
    update_tns_redshift, unset_cross_match_host, update_object_status, get_followup_objects_for_tracking,
    get_photometry_batch, get_object_details_batch, get_latest_photometry_for_names,
    get_detect_metadata, get_detect_page_data, get_detect_lc_data)
from modules.data_processing import DataVisualization
from modules.ext_M_calculator import apm_to_abm, get_extinction
import json
import io
import urllib.parse
import time
import threading

from flask import Blueprint
detect_bp = Blueprint('detect', __name__, template_folder='templates', static_folder='static')

# Lightweight in-memory cache for DETECT card lightcurves.
_DETECT_LC_CACHE = OrderedDict()
_DETECT_LC_CACHE_MAX_SIZE = int(os.getenv('DETECT_LC_CACHE_MAX_SIZE', '300'))

# In-memory page cache for DETECT results by date.
_DETECT_PAGE_CACHE = OrderedDict()
_DETECT_PAGE_BUILDING = set()
_DETECT_PAGE_CACHE_LOCK = threading.Lock()
_DETECT_PAGE_CACHE_TTL_SEC = int(os.getenv('DETECT_PAGE_CACHE_TTL_SEC', '600'))
_DETECT_PAGE_CACHE_MAX_SIZE = int(os.getenv('DETECT_PAGE_CACHE_MAX_SIZE', '8'))
_DETECT_PAGE_PREWARM_DAYS = int(os.getenv('DETECT_PAGE_PREWARM_DAYS', '3'))
_DETECT_PAGE_CACHE_STATS = {'hits': 0, 'misses': 0, 'evictions': 0}
_DETECT_LC_CACHE_STATS = {'hits': 0, 'misses': 0, 'evictions': 0}


def _cache_hit_rate(stats):
    total = stats['hits'] + stats['misses']
    return (stats['hits'] / total) if total else 0.0


def _log_detect_cache_stats(context, selected_date=None, target_name=None):
    with _DETECT_PAGE_CACHE_LOCK:
        logger.info(
            '[DETECT-CACHE] %s date=%s target=%s page(hit=%.1f%% size=%d/%d evict=%d) lc(hit=%.1f%% size=%d/%d evict=%d)',
            context,
            selected_date or '-',
            target_name or '-',
            100.0 * _cache_hit_rate(_DETECT_PAGE_CACHE_STATS),
            len(_DETECT_PAGE_CACHE),
            _DETECT_PAGE_CACHE_MAX_SIZE,
            _DETECT_PAGE_CACHE_STATS['evictions'],
            100.0 * _cache_hit_rate(_DETECT_LC_CACHE_STATS),
            len(_DETECT_LC_CACHE),
            _DETECT_LC_CACHE_MAX_SIZE,
            _DETECT_LC_CACHE_STATS['evictions'],
        )


def _get_detect_page_cache(selected_date):
    with _DETECT_PAGE_CACHE_LOCK:
        entry = _DETECT_PAGE_CACHE.get(selected_date)
        if entry is not None:
            _DETECT_PAGE_CACHE.move_to_end(selected_date)
            _DETECT_PAGE_CACHE_STATS['hits'] += 1
        else:
            _DETECT_PAGE_CACHE_STATS['misses'] += 1
        return entry


def _is_detect_page_cache_fresh(entry):
    if not entry:
        return False
    return (time.time() - entry.get('built_at', 0)) < _DETECT_PAGE_CACHE_TTL_SEC


def _set_detect_page_cache(selected_date, payload):
    with _DETECT_PAGE_CACHE_LOCK:
        _DETECT_PAGE_CACHE[selected_date] = {
            'payload': payload,
            'built_at': time.time(),
        }
        _DETECT_PAGE_CACHE.move_to_end(selected_date)
        while len(_DETECT_PAGE_CACHE) > _DETECT_PAGE_CACHE_MAX_SIZE:
            evicted_key, _ = _DETECT_PAGE_CACHE.popitem(last=False)
            _DETECT_PAGE_CACHE_STATS['evictions'] += 1
            logger.info('[DETECT-CACHE] page LRU evicted date=%s size=%d/%d', evicted_key, len(_DETECT_PAGE_CACHE), _DETECT_PAGE_CACHE_MAX_SIZE)


def _detect_page_is_building(selected_date):
    with _DETECT_PAGE_CACHE_LOCK:
        return selected_date in _DETECT_PAGE_BUILDING


def _detect_page_mark_building(selected_date):
    with _DETECT_PAGE_CACHE_LOCK:
        if selected_date in _DETECT_PAGE_BUILDING:
            return False
        _DETECT_PAGE_BUILDING.add(selected_date)
        return True


def _detect_page_unmark_building(selected_date):
    with _DETECT_PAGE_CACHE_LOCK:
        _DETECT_PAGE_BUILDING.discard(selected_date)


def _start_detect_page_build(selected_date, app_obj=None, force=False):
    if not selected_date:
        return
    if not force:
        entry = _get_detect_page_cache(selected_date)
        if entry and _is_detect_page_cache_fresh(entry):
            return
    if not _detect_page_mark_building(selected_date):
        return

    if app_obj is None:
        from flask import current_app
        app_obj = current_app._get_current_object()

    def _runner():
        try:
            with app_obj.app_context():
                payload = _assemble_detect_payload(selected_date)
                _set_detect_page_cache(selected_date, payload)
                _log_detect_cache_stats('page-build-complete', selected_date=selected_date)
        except Exception as e:
            logger.error('Background DETECT cache build failed for %s: %s', selected_date, e)
        finally:
            _detect_page_unmark_building(selected_date)

    threading.Thread(target=_runner, daemon=True).start()


def _get_detect_page_payload_swr(selected_date):
    entry = _get_detect_page_cache(selected_date)
    if not entry:
        return None, False
    payload = entry.get('payload')
    is_fresh = _is_detect_page_cache_fresh(entry)
    if not is_fresh:
        _start_detect_page_build(selected_date)
    return payload, is_fresh


def _get_detect_lc_cache(target_name):
    with _DETECT_PAGE_CACHE_LOCK:
        payload = _DETECT_LC_CACHE.get(target_name)
        if payload is not None:
            _DETECT_LC_CACHE.move_to_end(target_name)
            _DETECT_LC_CACHE_STATS['hits'] += 1
        else:
            _DETECT_LC_CACHE_STATS['misses'] += 1
        return payload


def _set_detect_lc_cache(target_name, payload):
    with _DETECT_PAGE_CACHE_LOCK:
        _DETECT_LC_CACHE[target_name] = payload
        _DETECT_LC_CACHE.move_to_end(target_name)
        while len(_DETECT_LC_CACHE) > _DETECT_LC_CACHE_MAX_SIZE:
            evicted_key, _ = _DETECT_LC_CACHE.popitem(last=False)
            _DETECT_LC_CACHE_STATS['evictions'] += 1
            logger.info('[DETECT-CACHE] LC LRU evicted target=%s size=%d/%d', evicted_key, len(_DETECT_LC_CACHE), _DETECT_LC_CACHE_MAX_SIZE)


def prewarm_detect_page_cache(prewarm_days=None, refresh_latest=True, force_latest=True, app_obj=None):
    """Prewarm DETECT page cache for the latest N dates.

    Safe to call from a scheduler or manually. Starts background builds only.
    """
    if app_obj is None:
        from flask import current_app
        app_obj = current_app._get_current_object()

    prewarm_days = _DETECT_PAGE_PREWARM_DAYS if prewarm_days is None else max(0, int(prewarm_days))

    def _runner():
        with app_obj.app_context():
            available_dates = get_detect_metadata().get('available_dates') or []
            if not available_dates:
                logger.info('[DETECT-PREWARM] no available dates')
                return

            queued = []
            latest_date = available_dates[0]

            if refresh_latest and latest_date:
                _start_detect_page_build(latest_date, app_obj=app_obj, force=force_latest)
                queued.append(latest_date)

            for date in available_dates[:prewarm_days]:
                if refresh_latest and date == latest_date:
                    continue
                entry = _get_detect_page_cache(date)
                if entry and _is_detect_page_cache_fresh(entry):
                    continue
                _start_detect_page_build(date, app_obj=app_obj)
                queued.append(date)

            logger.info(
                '[DETECT-PREWARM] queued=%s latest=%s prewarm_days=%s page_cache_size=%s lc_cache_size=%s',
                queued,
                latest_date,
                prewarm_days,
                len(_DETECT_PAGE_CACHE),
                len(_DETECT_LC_CACHE),
            )
            _log_detect_cache_stats('prewarm', selected_date=latest_date)

    threading.Thread(target=_runner, daemon=True).start()
    return {'success': True, 'prewarm_days': prewarm_days, 'refresh_latest': refresh_latest, 'force_latest': force_latest}


def _parse_float_or_none(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_float(v):
    """Return a plain Python float or None. Handles Decimal, numpy, str."""
    if v is None:
        return None
    try:
        r = float(v)
        return None if r != r else r   # NaN → None
    except (TypeError, ValueError):
        return None


def _safe_coord(v):
    """Return a 4-decimal-place coordinate string, or ''."""
    if v is None:
        return ''
    try:
        return f'{float(v):.4f}'
    except (TypeError, ValueError):
        return str(v) if v else ''


def _detect_abs_mag_inputs(latest_point, tns_details, tns_info):
    latest_mag = None
    filter_name = 'V'

    if latest_point and latest_point.get('magnitude') is not None:
        latest_mag = _parse_float_or_none(latest_point.get('magnitude'))
        if latest_mag is not None:
            filter_name = latest_point.get('filter') or 'V'

    if latest_mag is None and tns_details and tns_details.get('discoverymag') is not None:
        latest_mag = _parse_float_or_none(tns_details.get('discoverymag'))
        if latest_mag is not None:
            filter_name = tns_details.get('filter') or tns_details.get('discmagfilter') or 'V'

    tns_details = tns_details or {}
    tns_info = tns_info or {}
    ra = _parse_float_or_none(tns_details.get('ra') or tns_info.get('ra'))
    dec = _parse_float_or_none(
        tns_details.get('declination') or tns_details.get('dec') or tns_info.get('dec')
    )

    return latest_mag, filter_name, ra, dec


def _calculate_detect_abs_mag(target_name, apparent_mag, redshift, extinction, catalog_name=''):
    apparent_mag = _parse_float_or_none(apparent_mag)
    redshift = _parse_float_or_none(redshift)
    extinction = _parse_float_or_none(extinction)

    if apparent_mag is None or redshift is None or redshift <= 0 or extinction is None:
        return None

    try:
        result = apm_to_abm(apparent_mag, redshift, extinction)
        return None if isinstance(result, dict) else result
    except Exception as e:
        logger.error('DETECT abs_mag calculation error for %s %s: %s', target_name, catalog_name, e)
        return None


def _build_detect_lc_payload(target_name):
    # Single DB connection for both object details and photometry (Marshal pattern)
    lc_data = get_detect_lc_data(target_name)
    details = lc_data.get('details') or {}
    photometry = lc_data.get('photometry') or []

    if not photometry:
        return {
            'success': True,
            'plot_json': None,
            'data_count': 0,
            'message': 'No photometry data available'
        }

    z = _parse_float_or_none(details.get('redshift'))
    ra = _parse_float_or_none(details.get('ra'))
    dec = _parse_float_or_none(details.get('declination'))

    plot_json = DataVisualization.create_photometry_plot_from_db(
        photometry,
        z,
        ra,
        dec,
        as_json=True,
    )

    return {
        'success': True,
        'plot_json': plot_json,
        'data_count': len(photometry),
    }
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
        return send_file(
            io.BytesIO(image_data),
            mimetype='image/png',
            as_attachment=False,
        )
    return "Image not found", 404

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
    source = data.get('source')
    
    if not match_id or not target_name:
        return jsonify({'success': False, 'message': 'Missing parameters'})
        
    # 1. Update cross_match_results (set is_host)
    if set_cross_match_host(match_id, target_name):
        # 2. Mark object as Follow-up
        update_object_status(target_name, 'followup')
        # Invalidate page cache so next load gets fresh data
        _soft_invalidate_page_cache()
        # Soft-invalidate tracker cache: keep stale value for SWR, trigger bg rebuild
        _TRACKER_CACHE['expires_at'] = 0.0
        _start_tracker_build()
        # 3. Update tns_objects redshift
        if redshift is not None:
            try:
                z_val = float(redshift)
                z_str = f"{z_val:.3f}"
            except (ValueError, TypeError):
                z_str = str(redshift)
            update_tns_redshift(target_name, z_str)
            return jsonify({'success': True})
        return jsonify({'success': True, 'message': 'Host set, but no redshift to update'})
    else:
        return jsonify({'success': False, 'message': 'Database error'})

def _soft_invalidate_page_cache():
    """Mark all cached detect pages as stale and kick off background rebuilds.
    Called after any mutation (host change, status change) so the next page
    load gets fresh data instead of the old cached payload.
    """
    with _DETECT_PAGE_CACHE_LOCK:
        dates_to_rebuild = list(_DETECT_PAGE_CACHE.keys())
        for key in dates_to_rebuild:
            if _DETECT_PAGE_CACHE.get(key):
                _DETECT_PAGE_CACHE[key]['built_at'] = 0.0
    for date in dates_to_rebuild:
        _start_detect_page_build(date)
    logger.info('[DETECT-CACHE] page cache soft-invalidated for %d dates, rebuilds started', len(dates_to_rebuild))


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

    if unset_cross_match_host(target_name):
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

    # Ensure no cross_match is flagged as host
    unset_cross_match_host(target_name)
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


def _assemble_detect_payload(selected_date):
    t0 = time.perf_counter()

    # ── Metadata: available_dates + daily_counts (cached, 1 conn or 0 if fresh) ──
    metadata = get_detect_metadata()
    available_dates = metadata.get('available_dates', [])
    daily_counts    = metadata.get('daily_counts', [])
    t_meta = time.perf_counter()

    # ── All page data in a SINGLE DB connection (cross-matches + details + phot) ──
    page_data = get_detect_page_data(selected_date)
    results        = page_data.get('results', [])
    details_batch  = page_data.get('details_batch', {})
    latest_phot    = page_data.get('latest_phot', {})
    t_query = time.perf_counter()

    # Group results by target, parse match_data
    results_by_target = {}
    for row in results:
        if isinstance(row.get('match_data'), str):
            try:
                row['match_data'] = json.loads(row['match_data'])
            except Exception:
                pass
        t_name = row.get('target_name')
        if not t_name:
            continue
        results_by_target.setdefault(t_name, []).append(row)

    t_batch = time.perf_counter()

    final_target_list = []
    for target_name, matches in results_by_target.items():
        matches.sort(key=lambda x: float(x.get('separation_arcsec', 9999)))
        latest_point = latest_phot.get(target_name)
        tns_details = details_batch.get(target_name)

        processed_matches = []
        for row in matches:
            match_data = row.get('match_data') or {}
            if isinstance(match_data, str):
                try:
                    match_data = json.loads(match_data)
                except Exception:
                    match_data = {}

            if tns_details:
                row['tns_info'] = {
                    'discoverydate': tns_details.get('discoverydate', 'N/A'),
                    'internal_names': tns_details.get('internal_names', 'N/A'),
                    'ra': tns_details.get('ra', 'N/A'),
                    'dec': tns_details.get('declination', 'N/A')
                }
            else:
                row['tns_info'] = {
                    'discoverydate': match_data.get('tns_discoverydate', 'N/A'),
                    'internal_names': match_data.get('tns_internal_names', 'N/A'),
                    'ra': match_data.get('tns_ra', 'N/A'),
                    'dec': match_data.get('tns_dec', 'N/A')
                }

            redshift = None
            db_z = row.get('z')
            if db_z is not None:
                try:
                    redshift = float(db_z)
                except (ValueError, TypeError):
                    pass
            if redshift is None:
                for z_key in ['Z', 'z', 'redshift', 'z(s)', 'z_spec', 'z_phot', 'z_lens']:
                    if z_key in match_data and match_data[z_key] is not None and match_data[z_key] != '':
                        try:
                            redshift = float(match_data[z_key])
                        except (ValueError, TypeError):
                            pass
                        if redshift is not None:
                            break
            row['z'] = redshift

            abs_mag = match_data.get('brightest_abs_mag') or match_data.get('latest_abs_mag')
            try:
                abs_mag = float(abs_mag) if abs_mag is not None else None
            except (ValueError, TypeError):
                abs_mag = None
            row['abs_mag'] = abs_mag

            row['is_flagged'] = bool(row.get('flag'))
            row['flag_id'] = row.get('id')
            row['is_host'] = bool(row.get('is_host'))
            processed_matches.append(row)

        if not processed_matches:
            continue

        latest_mag, filter_name, target_ra, target_dec = _detect_abs_mag_inputs(
            latest_point,
            tns_details,
            processed_matches[0].get('tns_info'),
        )
        extinction = None
        if latest_mag is not None and target_ra is not None and target_dec is not None:
            try:
                extinction = get_extinction(target_ra, target_dec, filter_name)
                if hasattr(extinction, 'item'):
                    extinction = extinction.item()
            except Exception as e:
                logger.error('DETECT extinction calculation error for %s: %s', target_name, e)

        for match in processed_matches:
            fresh_abs_mag = _calculate_detect_abs_mag(
                target_name,
                latest_mag,
                match.get('z'),
                extinction,
                match.get('catalog_name') or '',
            )
            if fresh_abs_mag is not None:
                match['abs_mag'] = fresh_abs_mag

        best_match = processed_matches[0]

        target_has_host = any(m.get('is_host') for m in processed_matches)
        raw_status = (tns_details or {}).get('status', '') or ''
        _NORM = {'Follow-up': 'followup', 'Finish': 'finished', 'Inbox': 'object', 'Snoozed': 'snoozed'}
        obj_status = _NORM.get(raw_status, raw_status.lower() or 'object')

        target_obj = {
            'target_name': target_name,
            'id': best_match.get('id'),
            'tns_info': best_match.get('tns_info'),
            'plot_json': None,
            'matches': processed_matches,
            'best_match': best_match,
            'is_flagged': best_match.get('is_flagged'),
            'flag_id': best_match.get('flag_id'),
            'is_host': target_has_host,
            'target_is_host': target_has_host,
            'obj_status': obj_status,
        }
        final_target_list.append(target_obj)

    t_build = time.perf_counter()
    # Resolved objects (Checked / No-Host → status finished or snoozed) sink to the
    # bottom regardless of host, since they are no longer actionable and won't
    # reappear the next day. Within each group, hosts sort first, then by name.
    final_target_list.sort(key=lambda x: (
        x.get('obj_status') in ('finished', 'snoozed'),
        not x.get('is_host', False),
        x['target_name'],
    ))

    summary_results = []
    for t in final_target_list:
        row = dict(t['best_match'])
        row['target_is_host'] = t.get('is_host', False)
        row['obj_status'] = t.get('obj_status', 'object')
        summary_results.append(row)

    t_counts = time.perf_counter()

    # ── Compact JSON-safe data for client-side rendering ─────────────────
    summary_table = []
    cards_data    = []
    for t in final_target_list:
        bm = t['best_match']
        ti = t.get('tns_info') or {}
        summary_table.append({
            'target_name':       str(t['target_name']),
            'ra':                str(ti.get('ra') or ''),
            'dec':               str(ti.get('dec') or ''),
            'catalog_name':      str(bm.get('catalog_name') or ''),
            'separation_arcsec': _safe_float(bm.get('separation_arcsec')),
            'z':                 _safe_float(bm.get('z')),
            'abs_mag':           _safe_float(bm.get('abs_mag')),
            'is_flagged':        bool(bm.get('is_flagged')),
            'flag_id':           bm.get('flag_id'),
            'is_host':           bool(t.get('is_host', False)),
            'obj_status':        str(t.get('obj_status', 'object')),
        })
        matches_clean = []
        for m in t['matches']:
            md = m.get('match_data') or {}
            matches_clean.append({
                'id':                m.get('id'),
                'catalog_name':      str(m.get('catalog_name') or ''),
                'separation_arcsec': _safe_float(m.get('separation_arcsec')),
                'z':                 _safe_float(m.get('z')),
                'abs_mag':           _safe_float(m.get('abs_mag')),
                'is_host':           bool(m.get('is_host')),
                'is_flagged':        bool(m.get('is_flagged')),
                'flag_id':           m.get('flag_id'),
                'match_ra':          _safe_coord(m.get('match_ra') or md.get('ra') or md.get('_RAJ2000')),
                'match_dec':         _safe_coord(m.get('match_dec') or md.get('dec') or md.get('_DEJ2000')),
                'obj_id':            str(md.get('id') or ''),
                'grade':             str(md.get('Grade') or ''),
                'lens_prob':         _safe_float(md.get('LENS_PROBABILITY')),
            })
        cards_data.append({
            'target_name': str(t['target_name']),
            'tns_info': {
                'discoverydate':  str(ti.get('discoverydate') or '—'),
                'internal_names': str(ti.get('internal_names') or ''),
                'ra':             str(ti.get('ra') or ''),
                'dec':            str(ti.get('dec') or ''),
            },
            'z':          _safe_float(bm.get('z')),
            'abs_mag':    _safe_float(bm.get('abs_mag')),
            'obj_status': str(t.get('obj_status', 'object')),
            'is_host':    bool(t.get('is_host', False)),
            'is_flagged': bool(bm.get('is_flagged')),
            'flag_id':    bm.get('flag_id'),
            'matches':    matches_clean,
        })

    logger.info(
        '[DETECT-BUILD] date=%s results=%d targets=%d timings: meta=%.3fs query=%.3fs build=%.3fs total=%.3fs',
        selected_date,
        len(results),
        len(final_target_list),
        t_meta - t0,
        t_query - t_meta,
        t_build - t_query,
        t_counts - t0,
    )

    return {
        'results':        final_target_list,
        'summary_results': summary_results,
        'summary_table':  summary_table,
        'cards_data':     cards_data,
        'current_path':   '/detect',
        'available_dates': available_dates,
        'daily_counts':   daily_counts,
        'selected_date':  selected_date,
    }


# ── Follow-up tracker: SWR cache (expensive abs_mag computation) ──────────
_TRACKER_CACHE: dict = {'expires_at': 0.0, 'value': None}
_TRACKER_CACHE_TTL = int(os.getenv('DETECT_TRACKER_CACHE_TTL', '300'))  # 5 min default


def _build_tracker_data() -> list:
    """Compute abs_mag for all follow-up objects. May take 10-20 s on first call."""
    followup_raw = get_followup_objects_for_tracking()
    if not followup_raw:
        return []

    names = [fu['name'] for fu in followup_raw]
    latest_phot = get_latest_photometry_for_names(names)

    _NORM2 = {'Follow-up': 'followup', 'Finish': 'finished', 'Inbox': 'object', 'Snoozed': 'snoozed'}
    tracker = []
    for fu in followup_raw:
        # Skip objects that are already Done — they no longer need follow-up attention
        if _NORM2.get(fu.get('status', '') or '', 'object') == 'finished':
            continue
        fu_name = fu['name']
        fu_z = None
        for z_src in (fu.get('match_z'), fu.get('redshift')):
            if z_src is not None:
                try:
                    fu_z = float(z_src)
                    break
                except (ValueError, TypeError):
                    pass
        try:
            fu_ra  = float(fu['ra'])         if fu.get('ra')          else None
            fu_dec = float(fu['declination']) if fu.get('declination') else None
        except (ValueError, TypeError):
            fu_ra = fu_dec = None

        fu_abs_mag = None
        if fu_z and fu_ra and fu_dec:
            lp = latest_phot.get(fu_name)
            latest_mag, filter_name = None, 'V'
            if lp and lp.get('magnitude') is not None:
                try:
                    latest_mag  = float(lp['magnitude'])
                    filter_name = lp.get('filter') or 'V'
                except (ValueError, TypeError):
                    pass
            if latest_mag is None and fu.get('discoverymag'):
                try:
                    latest_mag  = float(fu['discoverymag'])
                    filter_name = fu.get('disc_filter') or 'V'
                except (ValueError, TypeError):
                    pass
            if latest_mag is not None:
                try:
                    ext = get_extinction(fu_ra, fu_dec, filter_name)
                    if hasattr(ext, 'item'):
                        ext = ext.item()
                    result_am = apm_to_abm(latest_mag, fu_z, ext)
                    if not isinstance(result_am, dict):
                        fu_abs_mag = result_am
                except Exception as e:
                    logger.error('Tracker abs_mag %s: %s', fu_name, e)

        sep = fu.get('separation_arcsec')
        tracker.append({
            'name':              fu_name,
            'z':                 fu_z,
            'abs_mag':           _safe_float(fu_abs_mag),
            'catalog_name':      fu.get('catalog_name') or '—',
            'separation_arcsec': float(sep) if sep is not None else None,
            'discoverydate':     fu.get('discoverydate') or '—',
            'obj_status':        _NORM2.get(fu.get('status', '') or '', 'object'),
        })

    tracker.sort(key=lambda x: (x['abs_mag'] is None, x['abs_mag'] if x['abs_mag'] is not None else 0))
    return tracker


def _start_tracker_build(app_obj=None):
    """Start a background thread that rebuilds the tracker cache."""
    if app_obj is None:
        from flask import current_app
        app_obj = current_app._get_current_object()

    def _runner():
        try:
            with app_obj.app_context():
                tracker = _build_tracker_data()
                _TRACKER_CACHE['value']      = tracker
                _TRACKER_CACHE['expires_at'] = time.time() + _TRACKER_CACHE_TTL
                logger.info('[DETECT-TRACKER] background build done, %d objects', len(tracker))
        except Exception as e:
            logger.error('[DETECT-TRACKER] background build failed: %s', e)

    threading.Thread(target=_runner, daemon=True).start()


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
