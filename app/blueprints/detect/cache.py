"""DETECT host screening pages and review APIs — cache (split from detect_routes.py)."""
from app.db.transient import get_followup_objects_for_tracking, get_detect_metadata
import time
import threading
import logging

logger = logging.getLogger(__name__)
from .helpers import (
    _DETECT_LC_CACHE,
    _DETECT_LC_CACHE_MAX_SIZE,
    _DETECT_LC_CACHE_STATS,
    _DETECT_PAGE_BUILDING,
    _DETECT_PAGE_CACHE,
    _DETECT_PAGE_CACHE_LOCK,
    _DETECT_PAGE_CACHE_MAX_SIZE,
    _DETECT_PAGE_CACHE_STATS,
    _DETECT_PAGE_CACHE_TTL_SEC,
    _DETECT_PAGE_PREWARM_DAYS,
    _TRACKER_CACHE,
    _TRACKER_CACHE_TTL,
)
from .payload import _assemble_detect_payload, _safe_float


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
