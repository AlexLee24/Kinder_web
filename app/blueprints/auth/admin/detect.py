"""Admin panel actions — detect (split from admin_routes.py)."""
from flask import request, jsonify
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp
from .helpers import _detect_manual


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

@admin_bp.route('/admin/detect-run', methods=['POST'])
@admin_required
def detect_run():
    """kind: 'followups' | 'recent' (hours) | 'names' (comma / space separated)."""
    from app.services.detect import detect_pipeline
    if not detect_pipeline.ENABLED:
        return jsonify({'success': False, 'message': 'DETECT is disabled in this instance (DETECT_IN_WEB=0)'}), 503
    if _detect_manual['running'] or detect_pipeline.is_running():
        return jsonify({'success': False, 'message': 'A DETECT run is already in progress'}), 409

    import re as _re
    import threading
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    names = [n for n in _re.split(r'[\s,;]+', str(data.get('names') or '')) if n]
    try:
        hours = float(data.get('hours') or 2)
    except (TypeError, ValueError):
        hours = 2.0
    if kind == 'names' and not names:
        return jsonify({'success': False, 'message': 'Give at least one object name'}), 400
    if kind not in ('followups', 'recent', 'names'):
        return jsonify({'success': False, 'message': 'Unknown run kind'}), 400

    def _run():
        _detect_manual['running'] = True
        _detect_manual['message'] = 'Running...'
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
            _detect_manual['message'] = f'Error: {e}'
        finally:
            _detect_manual['running'] = False

    threading.Thread(target=_run, daemon=True, name='detect_manual').start()
    what = {'followups': 'Follow-up re-screen', 'recent': f'objects TNS touched in the last {hours:g} h',
            'names': f'{len(names)} object(s)'}[kind]
    return jsonify({'success': True, 'message': f'DETECT started: {what}'})
