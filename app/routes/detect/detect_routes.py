import logging
import math
import os
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from flask import render_template, request, jsonify, flash, redirect, url_for, session, send_file

logger = logging.getLogger(__name__)
from modules.database.transient import (get_cross_match_results, update_cross_match_flag, get_available_dates,
    get_daily_match_counts, tns_object_db, get_target_image, get_detect_image_by_id, set_cross_match_host,
    update_tns_redshift, set_object_redshift, unset_cross_match_host, reject_cross_match_hosts, release_cross_match_host,
    update_object_status,
    get_followup_objects_for_tracking,
    get_photometry_batch, get_object_details_batch, get_latest_photometry_for_names,
    get_detect_metadata, get_detect_page_data, get_detect_lc_data, get_detect_overview)
from modules.data_processing import DataVisualization
from modules.ext_M_calculator import apm_to_abm, get_extinction   # DETECT's calculator (shim)
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


def _fmt(v, nd=2, dash='—'):
    v = _safe_float(v)
    return dash if v is None else f'{v:.{nd}f}'


def _match_rule(md: dict, is_host: bool) -> dict:
    """What DETECT's host rule (v1, DLR) concluded about one candidate row,
    reduced to a label the reviewer can read in the candidate table."""
    d_dlr   = _safe_float(md.get('d_dlr'))
    d_max   = _safe_float(md.get('d_dlr_max'))
    rank    = md.get('host_rank')
    is_lens = str(md.get('origin_catalog_name') or '').strip() != '' or 'z_lens' in md or 'lens_probability' in md
    if md.get('host_user') is True:
        kind, label = 'host', 'HOST · chosen by ' + str(md.get('host_user_by') or 'a reviewer')
    elif is_host:
        kind, label = 'host', 'HOST · rule v1'
    elif md.get('shares_host_galaxy'):
        kind, label = 'shred', 'part of the host galaxy'
    elif md.get('host_member'):
        kind, label = 'member', f'member #{rank}' if rank else 'member'
    elif md.get('host_tentative'):
        kind, label = 'tentative', 'tentative (just outside the limit)'
    elif d_dlr is not None and d_max is not None:
        kind, label = 'outside', f'outside (> {2 * d_max:g} d_DLR)'
    elif is_lens:
        kind, label = 'lens', 'lens catalogue'
    else:
        kind, label = 'nomodel', 'no galaxy model'
    mass = _safe_float(md.get('mass_cg'))
    return {
        'kind': kind, 'label': label, 'rank': rank,
        'd_dlr': d_dlr, 'd_dlr_max': d_max,
        'ambiguous': bool(md.get('ambiguous_host')),
        'z_conflict': bool(md.get('host_z_conflict')),
        'spectype': str(md.get('spectype') or ''),
        'morph': str(md.get('tractor_type') or md.get('morphtype') or ''),
        'survey': str(md.get('survey') or ''), 'program': str(md.get('program') or ''),
        'zwarn': md.get('zwarn'),
        'release': str(md.get('data_release') or ''),
        'mag_r': _safe_float(md.get('mag_r')),
        'logmass': (round(math.log10(mass), 2) if mass and mass > 0 else None),
        'w1w2': _safe_float(md.get('w1_w2_vega')),
        'wise_agn': bool(md.get('wise_agn_stern12')),
        'fibre_only': md.get('ls_photometry') is False,
        'center_sep': _safe_float(md.get('center_sep_arcsec')),
        'offset_kpc': _safe_float(md.get('offset_kpc')),
        'shape_source': str(md.get('shape_source') or ''),
        'host_user': md.get('host_user'),
        'host_user_by': md.get('host_user_by'),
    }


def _detect_verdict(screen: dict | None, matches: list, host_match: dict | None) -> dict:
    """DETECT's conclusion for one object as a headline + what the reviewer should do.

    kind: 'user' (a person already decided), 'confirmed', 'review', 'none'."""
    f = (screen or {}).get('flags') or {}
    hs = (screen or {}).get('host_status') or ('none' if not host_match else 'confirmed')
    hm = (host_match or {}).get('rule') or {}
    hz = _safe_float((host_match or {}).get('z'))

    def host_line():
        parts = [f"{hm.get('spectype') or 'spec'} z = {_fmt(hz, 4)}" if hz is not None else 'spectrum without z']
        if hm.get('d_dlr') is not None:
            lim = f" (limit {hm['d_dlr_max']:g}{', ' + hm['morph'] if hm.get('morph') else ''})" if hm.get('d_dlr_max') else ''
            parts.append(f"d_DLR {hm['d_dlr']:.2f}{lim}")
        if hm.get('center_sep') is not None:
            parts.append(f"{hm['center_sep']:.1f}″ from the centre")
        if hm.get('offset_kpc') is not None:
            parts.append(f"{hm['offset_kpc']:.1f} kpc")
        return ' · '.join(parts)

    if screen is None:
        return {'kind': 'unscreened',
                'headline': 'Cross-match only — DETECT has not screened this object (no host rule, no score, no tags). '
                            'The is_host flag here comes from the marshal\'s own auto-run.',
                'hint': 'Wait for the next DETECT run, or judge from the image and the candidate table.'}
    if host_match and hm.get('host_user') is True:
        return {'kind': 'user',
                'headline': f"Host chosen by {hm.get('host_user_by') or 'a reviewer'}: {host_match['catalog_name']} · {host_line()}",
                'hint': 'Decide Follow-up or Done. Pick another row to change the host, Reopen to hand it back to the pipeline.'}
    if not host_match and any((m.get('rule') or {}).get('host_user') is False for m in matches):
        by = next((m['rule'].get('host_user_by') for m in matches if m['rule'].get('host_user_by')), None)
        return {'kind': 'user',
                'headline': f"Marked as no host{' by ' + by if by else ''}.",
                'hint': 'Set host on a row if you change your mind, or Reopen.'}

    if hs == 'confirmed' and host_match:
        return {'kind': 'confirmed',
                'headline': f"Host found · {host_match['catalog_name']} · {host_line()}",
                'hint': 'Check the image, then Follow-up or Done (either accepts the host). Set host on another row if the rule picked the wrong galaxy.'}

    if hs == 'review':
        if host_match and hm.get('z_conflict'):
            zs = sorted({_fmt(m.get('z'), 4) for m in matches if m.get('z') is not None and (m.get('rule') or {}).get('z_conflict')})
            return {'kind': 'review',
                    'headline': f"Two spectra on the host galaxy disagree (z = {', '.join(zs)}) — a foreground/background blend, or DESI's own spectrum of the transient.",
                    'hint': 'Set host on the row whose z belongs to the galaxy; otherwise No host.'}
        if host_match and hm.get('ambiguous'):
            runner = next((m for m in matches if (m.get('rule') or {}).get('rank') == 2), None)
            r2 = f" vs #2 d_DLR {runner['rule']['d_dlr']:.2f} (z = {_fmt(runner.get('z'), 4)})" if runner and runner['rule'].get('d_dlr') is not None else ''
            return {'kind': 'review',
                    'headline': f"Two galaxies almost equally close: #1 d_DLR {_fmt(hm.get('d_dlr'))}{r2}. The rule picked #1 ({host_line()}).",
                    'hint': 'Look at the image: Follow-up / Done accepts #1, or Set host on #2, or No host.'}
        if f.get('host_tentative') or (not host_match and any((m.get('rule') or {}).get('kind') == 'tentative' for m in matches)):
            t = next((m for m in matches if (m.get('rule') or {}).get('kind') == 'tentative'), None)
            td = (t or {}).get('rule') or {}
            what = 'galaxy' if str(td.get('spectype') or 'GALAXY').upper() == 'GALAXY' else f"{td.get('spectype')} spectrum"
            return {'kind': 'review',
                    'headline': f"Nearest {what} is just outside the host limit: d_DLR {_fmt(td.get('d_dlr'))} > {td.get('d_dlr_max') or '?'} (within 2× the limit)"
                                + (f", z = {_fmt(t.get('z'), 4)}" if t and t.get('z') is not None else '') + '.',
                    'hint': 'If the image shows it in the galaxy\'s outskirts, Set host on that row; otherwise No host.'}
        return {'kind': 'review',
                'headline': 'The host rule could not settle on one galaxy.',
                'hint': 'Pick the host in the candidate table, or No host.'}

    # none
    if matches:
        dl = [(m.get('rule') or {}).get('d_dlr') for m in matches if (m.get('rule') or {}).get('d_dlr') is not None]
        nearest = f", nearest d_DLR {min(dl):.1f}" if dl else ''
        return {'kind': 'none',
                'headline': f"{len(matches)} spectrum{'s' if len(matches) != 1 else ''} within the search radius but none contains the transient{nearest}.",
                'hint': 'Usually No host. Set host on a row only if the image clearly disagrees.'}
    return {'kind': 'none', 'headline': 'No spectroscopic galaxy near the transient.', 'hint': 'Nothing to decide; No host closes it.'}


_HOST_STATUS_ORDER = {'review': 0, 'confirmed': 1, 'none': 2, 'unscreened': 3}
UNMATCHED_RECENT_DAYS = 60      # older unmatched objects are TNS edits of old reports, listed apart
_STATUS_NORM = {'Follow-up': 'followup', 'Finish': 'finished', 'Inbox': 'object', 'Snoozed': 'snoozed'}


_SCREEN_KEYS = ('score', 'host_status', 'tags', 'abs_mag', 'abs_mag_band', 'abs_mag_source', 'abs_mag_discovery',
                'peak_mag', 'peak_filter', 'peak_mjd', 'peak_source', 'n_phot', 'z', 'z_source', 'd_dlr',
                'center_sep_arcsec', 'offset_kpc', 'host', 'host_user', 'host_user_by', 'morph', 'mass_cg',
                'sfr_cg', 'known_galactic', 'known_agn', 'tns_type', 'lens_match', 'star_sep', 'run_date')


def _screen_public(s: dict | None) -> dict:
    """The subset of a detect_screen row the page needs, JSON-safe. Every key is
    present (None when DETECT has not screened the object) so templates can
    test `is not none` without guarding."""
    if not s:
        empty = dict.fromkeys(_SCREEN_KEYS)
        empty.update({'score': 0, 'tags': [], 'known_galactic': False, 'known_agn': False, 'lens_match': 0})
        return empty
    f = s.get('flags') or {}
    return {
        'score': int(s.get('score') or 0),
        'host_status': s.get('host_status') or 'none',
        'tags': [t for t in (s.get('tags') or []) if not str(t).startswith('Host-')],
        'abs_mag': _safe_float(s.get('abs_mag')),
        'abs_mag_band': s.get('abs_mag_band'),
        'abs_mag_source': s.get('abs_mag_source'),
        'abs_mag_discovery': _safe_float(s.get('abs_mag_discovery')),
        'peak_mag': _safe_float(s.get('peak_mag')),
        'peak_filter': s.get('peak_filter'),
        'peak_mjd': _safe_float(s.get('peak_mjd')),
        'peak_source': f.get('peak_source'),
        'n_phot': f.get('n_phot'),
        'z': _safe_float(s.get('z')),
        'z_source': s.get('z_source'),
        'd_dlr': _safe_float(s.get('d_dlr')),
        'center_sep_arcsec': _safe_float(s.get('center_sep_arcsec')),
        'offset_kpc': _safe_float(s.get('offset_kpc')),
        'host': f.get('host'),
        'host_user': f.get('host_user'),
        'host_user_by': f.get('host_user_by'),
        'morph': f.get('morphtype'),
        'mass_cg': _safe_float(f.get('mass_cg')),
        'sfr_cg': _safe_float(f.get('sfr_cg')),
        'known_galactic': bool(f.get('known_galactic')),
        'known_agn': bool(f.get('known_agn')),
        'tns_type': f.get('tns_type'),
        'lens_match': f.get('lens_match') or 0,
        'star_sep': _safe_float(f.get('desi_star_within_arcsec')),
        'run_date': s.get('run_date'),
    }


def _assemble_detect_payload(selected_date):
    t0 = time.perf_counter()

    # ── Metadata: available_dates + daily_counts (cached, 1 conn or 0 if fresh) ──
    metadata = get_detect_metadata()
    available_dates = metadata.get('available_dates', [])
    daily_counts    = metadata.get('daily_counts', [])
    screen_counts   = (metadata.get('screen_counts') or {}).get(selected_date) or {}
    t_meta = time.perf_counter()

    # ── All page data in a SINGLE DB connection (cross-matches + details + phot + screen) ──
    page_data = get_detect_page_data(selected_date)
    results        = page_data.get('results', [])
    details_batch  = page_data.get('details_batch', {})
    latest_phot    = page_data.get('latest_phot', {})
    screen_batch   = page_data.get('screen_batch', {})
    screen_only    = page_data.get('screen_only', [])
    wake_notes     = page_data.get('wake_notes', {})
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
        matches.sort(key=lambda x: float(x.get('separation_arcsec') or 9999))
        latest_point = latest_phot.get(target_name)
        tns_details = details_batch.get(target_name)
        screen_raw = screen_batch.get(target_name)
        screen = _screen_public(screen_raw)

        processed_matches = []
        for row in matches:
            match_data = row.get('match_data') or {}
            if isinstance(match_data, str):
                try:
                    match_data = json.loads(match_data)
                except Exception:
                    match_data = {}
            row['match_data'] = match_data

            if tns_details:
                row['tns_info'] = {
                    'discoverydate': tns_details.get('discoverydate', 'N/A'),
                    'internal_names': tns_details.get('internal_names', 'N/A'),
                    'ra': tns_details.get('ra', 'N/A'),
                    'dec': tns_details.get('declination', 'N/A'),
                    'type': tns_details.get('type') or '',
                    'tns_z': _safe_float(tns_details.get('redshift')),
                }
            else:
                row['tns_info'] = {
                    'discoverydate': match_data.get('tns_discoverydate', 'N/A'),
                    'internal_names': match_data.get('tns_internal_names', 'N/A'),
                    'ra': match_data.get('tns_ra', 'N/A'),
                    'dec': match_data.get('tns_dec', 'N/A'),
                    'type': match_data.get('type') or '',
                    'tns_z': None,
                }

            redshift = _safe_float(row.get('z'))
            if redshift is None:
                for z_key in ['Z', 'z', 'redshift', 'z(s)', 'z_spec', 'z_phot', 'z_lens']:
                    if z_key in match_data and match_data[z_key] is not None and match_data[z_key] != '':
                        redshift = _safe_float(match_data[z_key])
                        if redshift is not None:
                            break
            row['z'] = redshift
            row['abs_mag'] = None
            row['is_flagged'] = bool(row.get('flag'))
            row['flag_id'] = row.get('id')
            row['is_host'] = bool(row.get('is_host'))
            row['rule'] = _match_rule(match_data, row['is_host'])
            processed_matches.append(row)

        if not processed_matches:
            continue

        # Apparent magnitude for the per-candidate M(z): DETECT's peak detection when
        # it has one, else the marshal's latest point / discovery mag.
        latest_mag, filter_name, target_ra, target_dec = _detect_abs_mag_inputs(
            latest_point, tns_details, processed_matches[0].get('tns_info'))
        if screen.get('peak_mag') is not None:
            latest_mag, filter_name = screen['peak_mag'], screen.get('peak_filter') or filter_name
        extinction = None
        if latest_mag is not None and target_ra is not None and target_dec is not None:
            try:
                extinction = get_extinction(target_ra, target_dec, filter_name)
                if hasattr(extinction, 'item'):
                    extinction = extinction.item()
            except Exception as e:
                logger.error('DETECT extinction calculation error for %s: %s', target_name, e)

        for match in processed_matches:
            match['abs_mag'] = _calculate_detect_abs_mag(
                target_name, latest_mag, match.get('z'), extinction, match.get('catalog_name') or '')

        host_match = next((m for m in processed_matches if m.get('is_host')), None)
        if host_match is not None and screen.get('abs_mag') is not None and host_match.get('abs_mag') is None:
            host_match['abs_mag'] = screen['abs_mag']            # same z; DETECT already did the sum

        # Candidate order: the host, then rule members by rank, then tentative, then the rest.
        _kind_order = {'host': 0, 'shred': 1, 'member': 2, 'tentative': 3, 'outside': 4, 'lens': 5, 'nomodel': 6}
        processed_matches.sort(key=lambda m: (_kind_order.get(m['rule']['kind'], 9),
                                              m['rule'].get('rank') or 99,
                                              float(m.get('separation_arcsec') or 9999)))

        best_match = host_match or processed_matches[0]
        target_has_host = host_match is not None
        raw_status = (tns_details or {}).get('status', '') or ''
        obj_status = _STATUS_NORM.get(raw_status, raw_status.lower() or 'object')
        verdict = _detect_verdict(screen_raw, processed_matches, host_match)
        host_status = screen.get('host_status') or ('unscreened' if screen_raw is None else ('confirmed' if target_has_host else 'none'))

        target_obj = {
            'target_name': target_name,
            'id': best_match.get('id'),
            'tns_info': best_match.get('tns_info'),
            'matches': processed_matches,
            'best_match': best_match,
            'host_match': host_match,
            'is_flagged': best_match.get('is_flagged'),
            'flag_id': best_match.get('flag_id'),
            'is_host': target_has_host,
            'target_is_host': target_has_host,
            'host_match_id': host_match.get('id') if host_match else None,
            'host_pinned': bool(host_match and host_match['rule'].get('host_user') is True),
            'host_rejected': bool(not host_match and any(m['rule'].get('host_user') is False for m in processed_matches)),
            'obj_status': obj_status,
            'host_status': host_status,
            'score': screen.get('score') or 0,
            'screen': screen,
            'verdict': verdict,
            'wake_note': wake_notes.get(target_name),
            'z': screen['z'] if screen.get('z') is not None else best_match.get('z'),
            'abs_mag': screen['abs_mag'] if screen.get('abs_mag') is not None else best_match.get('abs_mag'),
            # no host: z and M above are "if candidate #1 were the host"
            'hypothetical': host_match is None and screen.get('z') is None and best_match.get('z') is not None,
        }
        final_target_list.append(target_obj)

    t_build = time.perf_counter()
    # Queue order: what still needs a person first (Inbox), grouped by what kind of
    # decision it needs (judgement > accept a confirmed host > no host), best score
    # first; then Follow-up; resolved objects (Done / No host) sink to the bottom.
    final_target_list.sort(key=lambda x: (
        x['obj_status'] in ('finished', 'snoozed'),
        x['obj_status'] == 'followup',
        _HOST_STATUS_ORDER.get(x['host_status'], 2),
        -int(x.get('score') or 0),
        x['target_name'],
    ))

    summary_results = []
    for t in final_target_list:
        row = dict(t['best_match'])
        row['target_is_host'] = t.get('is_host', False)
        row['obj_status'] = t.get('obj_status', 'object')
        summary_results.append(row)

    # Objects DETECT screened that day that matched nothing (host_status 'none'):
    # listed compactly so the reviewer sees the whole day, no decision needed.
    none_list = []
    old_list = []
    recent_cut = (datetime.now(timezone.utc) - timedelta(days=UNMATCHED_RECENT_DAYS)).strftime('%Y-%m-%d')
    for s in screen_only:
        pub = _screen_public(s)
        disc = s.get('discoverydate') or ''
        (none_list if (not disc or disc >= recent_cut) else old_list).append({
            'target_name': str(s.get('name') or ''),
            'type': str(s.get('tns_type') or ''),
            'obj_status': _STATUS_NORM.get(s.get('obj_status') or '', (s.get('obj_status') or 'object').lower()),
            'discoverydate': s.get('discoverydate') or '—',
            'ra': _safe_float(s.get('ra')), 'dec': _safe_float(s.get('dec')),
            'score': pub.get('score', 0), 'tags': pub.get('tags', []),
            'z': pub.get('z'), 'z_source': pub.get('z_source'),
            'abs_mag': pub.get('abs_mag'), 'abs_mag_band': pub.get('abs_mag_band'),
            'wake_note': wake_notes.get(s.get('name')),
        })
    none_list.sort(key=lambda x: (-x['score'], x['target_name']))
    old_list.sort(key=lambda x: (x['discoverydate'] or '', x['target_name']), reverse=True)

    t_counts = time.perf_counter()

    counts = {
        'targets': len(final_target_list),
        'pending': sum(1 for t in final_target_list if t['obj_status'] == 'object'),
        'review': sum(1 for t in final_target_list if t['host_status'] == 'review'),
        'confirmed': sum(1 for t in final_target_list if t['host_status'] == 'confirmed'),
        'nohost': sum(1 for t in final_target_list if t['host_status'] == 'none'),
        'followup': sum(1 for t in final_target_list if t['obj_status'] == 'followup'),
        'done': sum(1 for t in final_target_list if t['obj_status'] in ('finished', 'snoozed')),
        'screened': screen_counts.get('total') or (len(final_target_list) + len(none_list) + len(old_list)),
        'unmatched': len(none_list),
        'old': len(old_list),
        'last_run': screen_counts.get('last_run'),
    }

    # ── Compact JSON-safe data for client-side rendering ─────────────────
    cards_data = []
    for t in final_target_list:
        ti = t.get('tns_info') or {}
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
                'obj_id':            str(md.get('TARGETID') or md.get('id') or ''),
                'grade':             str(md.get('grade') or md.get('Grade') or ''),
                'lens_prob':         _safe_float(md.get('lens_probability') or md.get('LENS_PROBABILITY')),
                'rule':              m.get('rule'),
            })
        cards_data.append({
            'target_name': str(t['target_name']),
            'tns_info': {
                'discoverydate':  str(ti.get('discoverydate') or '—'),
                'internal_names': str(ti.get('internal_names') or ''),
                'ra':             str(ti.get('ra') or ''),
                'dec':            str(ti.get('dec') or ''),
                'type':           str(ti.get('type') or ''),
                'tns_z':          ti.get('tns_z'),
            },
            'z':          _safe_float(t.get('z')),
            'abs_mag':    _safe_float(t.get('abs_mag')),
            'obj_status': str(t.get('obj_status', 'object')),
            'host_status': t.get('host_status'),
            'is_host':    bool(t.get('is_host', False)),
            'host_match_id': t.get('host_match_id'),
            'host_pinned': t.get('host_pinned'),
            'host_rejected': t.get('host_rejected'),
            'is_flagged': bool(t.get('is_flagged')),
            'flag_id':    t.get('flag_id'),
            'score':      t.get('score'),
            'hypothetical': bool(t.get('hypothetical')),
            'wake_note':  t.get('wake_note'),
            'screen':     t.get('screen'),
            'verdict':    t.get('verdict'),
            'matches':    matches_clean,
        })

    logger.info(
        '[DETECT-BUILD] date=%s results=%d targets=%d unmatched=%d timings: meta=%.3fs query=%.3fs build=%.3fs total=%.3fs',
        selected_date, len(results), len(final_target_list), len(none_list),
        t_meta - t0, t_query - t_meta, t_build - t_query, t_counts - t0,
    )

    return {
        'results':        final_target_list,
        'summary_results': summary_results,
        'cards_data':     cards_data,
        'none_list':      none_list,
        'old_list':       old_list,
        'unmatched_recent_days': UNMATCHED_RECENT_DAYS,
        'counts':         counts,
        'current_path':   '/detect',
        'available_dates': available_dates,
        'daily_counts':   daily_counts,
        'selected_date':  selected_date,
    }


# ── Follow-up tracker: SWR cache (expensive abs_mag computation) ──────────
_TRACKER_CACHE: dict = {'expires_at': 0.0, 'value': None}
_TRACKER_CACHE_TTL = int(os.getenv('DETECT_TRACKER_CACHE_TTL', '300'))  # 5 min default


def _build_tracker_data() -> list:
    """Follow-up objects with DETECT's latest verdict (transient.detect_screen).
    DETECT re-screens Follow-up objects daily, so no magnitudes are recomputed here."""
    followup_raw = get_followup_objects_for_tracking()
    if not followup_raw:
        return []

    _NORM2 = {'Follow-up': 'followup', 'Finish': 'finished', 'Inbox': 'object', 'Snoozed': 'snoozed'}
    tracker = []
    for fu in followup_raw:
        if _NORM2.get(fu.get('status', '') or '', 'object') == 'finished':
            continue
        fu_z = None
        for z_src in (fu.get('match_z'), fu.get('redshift')):
            fu_z = _safe_float(z_src)
            if fu_z is not None:
                break
        sep = fu.get('separation_arcsec')
        tracker.append({
            'name':              fu['name'],
            'z':                 fu_z,
            'abs_mag':           _safe_float(fu.get('detect_abs_mag')),
            'abs_mag_source':    fu.get('detect_abs_mag_source'),
            'abs_mag_band':      fu.get('detect_abs_mag_band'),
            'catalog_name':      fu.get('catalog_name') or '—',
            'separation_arcsec': float(sep) if sep is not None else None,
            'discoverydate':     fu.get('discoverydate') or '—',
            'obj_status':        _NORM2.get(fu.get('status', '') or '', 'object'),
            'score':             fu.get('detect_score'),
            'host_status':       fu.get('detect_host_status'),
            'tags':              [t for t in (fu.get('detect_tags') or []) if not str(t).startswith('Host-')],
            'detect_run_date':   fu.get('detect_run_date'),
        })

    tracker.sort(key=lambda x: (-(x['score'] or 0), x['abs_mag'] is None, x['abs_mag'] if x['abs_mag'] is not None else 0))
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
