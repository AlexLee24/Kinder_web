"""Admin panel actions — detect (split from admin_routes.py)."""
from flask import request, jsonify
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp
from .helpers import _detect_manual, _claim_task, _start_claimed_task


@admin_bp.route('/admin/detect-status')
@admin_required
def detect_status():
    from app.services.detect import detect_pipeline
    from app.services.jobs import job_status as _js
    st = detect_pipeline.status()
    # completed runs from any worker (this process only knows its own)
    st['recent_jobs'] = {k: v for k, v in _js.get_all().items() if k.startswith('detect_')}
    st['manual'] = dict(_detect_manual)
    return jsonify(st)

def start_detect_run(kind, names=None, hours=2.0):
    """Start a manual DETECT run in the background: kind 'followups' | 'recent' (hours) | 'names' (a list).
    Returns ({'success', 'message'}, http status); used by the old admin panel and by Admin › Bots."""
    from app.services.detect import detect_pipeline
    names = names or []
    if not detect_pipeline.ENABLED:
        return {'success': False, 'message': 'DETECT is disabled in this instance (DETECT_IN_WEB=0)'}, 503
    if _detect_manual['running'] or detect_pipeline.is_running():
        return {'success': False, 'message': 'A DETECT run is already in progress'}, 409
    if kind == 'names' and not names:
        return {'success': False, 'message': 'Give at least one object name'}, 400
    if kind not in ('followups', 'recent', 'names'):
        return {'success': False, 'message': 'Unknown run kind'}, 400

    def _run():
        try:
            if kind == 'followups':
                counts = detect_pipeline.run_followups()
            elif kind == 'recent':
                counts = detect_pipeline.run_recent(hours)
            else:
                counts = detect_pipeline.run_for_names(names, label='manual')
            try:
                from app.blueprints.detect.cache import _soft_invalidate_page_cache
                _soft_invalidate_page_cache()
            except Exception:
                pass
            _detect_manual['message'] = 'Done: ' + ', '.join(f'{k} {v}' for k, v in (counts or {}).items())
            logger.info('[DETECT Manual] %s by admin: %s', kind, counts)
        except Exception as e:
            logger.exception('[DETECT Manual] %s failed: %s', kind, e)
            _detect_manual['message'] = 'Error (see server log)'
        finally:
            _detect_manual['running'] = False

    if not _claim_task(_detect_manual):
        return {'success': False, 'message': 'A DETECT run is already in progress'}, 409
    _start_claimed_task(_detect_manual, _run, name='detect_manual')
    what = {'followups': 'Follow-up re-screen', 'recent': f'objects TNS touched in the last {hours:g} h',
            'names': f'{len(names)} object(s)'}[kind]
    return {'success': True, 'message': f'DETECT started: {what}'}, 200


@admin_bp.route('/admin/detect-run', methods=['POST'])
@admin_required
def detect_run():
    """kind: 'followups' | 'recent' (hours) | 'names' (comma / space separated)."""
    import re as _re
    data = request.get_json(silent=True) or {}
    names = [n for n in _re.split(r'[\s,;]+', str(data.get('names') or '')) if n]
    try:
        hours = float(data.get('hours') or 2)
    except (TypeError, ValueError):
        hours = 2.0
    payload, code = start_detect_run((data.get('kind') or '').strip(), names, hours)
    return jsonify(payload), code
