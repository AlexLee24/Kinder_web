"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — targets (split from private_area_routes.py)."""
from flask import session, request, jsonify
from app.db.obs import (
    save_observation_target,
    get_observation_targets,
    delete_observation_target,
    update_observation_target,
)
import logging
from app.core.auth import login_required

logger = logging.getLogger(__name__)
from . import private_area_bp


@private_area_bp.route('/api/targets', methods=['GET', 'POST'])
@login_required
def api_observation_targets():
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    
    if request.method == 'GET':
        targets = get_observation_targets(active_only=False)
        return jsonify({'success': True, 'targets': targets})
        
    elif request.method == 'POST':
        if not (is_great_lab or is_admin):
            return jsonify({'error': 'Forbidden'}), 403
            
        data = request.json
        _telescope = (data.get('telescope') or '').strip().upper()
        _auto_exp = bool(data.get('auto_exposure', False))
        if _telescope == 'LOT':
            _auto_exp = False
        new_id = save_observation_target(
            telescope=data.get('telescope'),
            name=data.get('name'),
            mag=data.get('mag'),
            ra=data.get('ra'),
            dec=data.get('dec'),
            priority=data.get('priority'),
            repeat_count=data.get('repeat_count', 0),
            auto_exposure=_auto_exp,
            filters=data.get('filters', []),
            plan=data.get('plan'),
            program=data.get('program'),
            note_gl=data.get('note_gl', ''),
            user_email=session['user']['email']
        )
        
        if new_id:
            return jsonify({'success': True, 'id': new_id})
        else:
            return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['DELETE'])
@login_required
def api_observation_target_delete(target_id):
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    if delete_observation_target(target_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>/toggle', methods=['PUT'])
@login_required
def api_observation_target_toggle(target_id):
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    data = request.json
    is_active = data.get('is_active')
    if is_active is None:
        return jsonify({'error': 'is_active field required'}), 400
        
    from app.db.obs import update_observation_target_status
    if update_observation_target_status(target_id, bool(is_active)):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['PUT'])
@login_required
def api_observation_target_update(target_id):
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    data = request.json
    _tele_put = (data.get('telescope') or '').strip().upper()
    _auto_exp_put = bool(data.get('auto_exposure', False))
    if _tele_put == 'LOT':
        _auto_exp_put = False
    if update_observation_target(
        target_id=target_id,
        telescope=data.get('telescope'),
        name=data.get('name'),
        mag=data.get('mag'),
        ra=data.get('ra'),
        dec=data.get('dec'),
        priority=data.get('priority'),
        repeat_count=data.get('repeat_count', 0),
        auto_exposure=_auto_exp_put,
        filters=data.get('filters', []),
        plan=data.get('plan'),
        program=data.get('program'),
        note_gl=data.get('note_gl', '')
    ):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/update-mags', methods=['POST'])
@login_required
def api_update_target_mags():

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    import threading
    from app.services.photometry.phot_scheduler import update_target_mags

    def _run():
        update_target_mags()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Magnitude update started'})

@private_area_bp.route('/api/search_target')
@login_required
def api_search_target():
    """Search TNS objects by name for autocomplete"""
    
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'results': []})
    
    try:
        from app.db.transient import search_tns_objects
        rows = search_tns_objects(search_term=q, limit=15, sort_by='discoverydate', sort_order='desc')
        results = []
        for r in rows:
            results.append({
                'name': r['name'],
                'prefix': r.get('name_prefix') or '',
                'reporting_group': r.get('reporting_group') or '',
                'source_group': r.get('source_group') or '',
                'ra': r.get('ra'),
                'dec': r.get('declination'),
                'redshift': r.get('redshift'),
                'mag': r.get('brightest_mag') or r.get('discoverymag'),
                'type': r.get('type') or '',
                'internal_names': r.get('internal_names') or '',
            })
        return jsonify({'results': results})
    except Exception as e:
        logger.error('Search error: %s', e)
        return jsonify({'results': []})

@private_area_bp.route('/api/auto_exposure')
@login_required
def api_auto_exposure():
    """Return auto exposure config from observation_script lookup table"""

    mag = request.args.get('mag', '').strip()
    telescope = request.args.get('telescope', 'SLT').strip()
    if not mag:
        return jsonify({'error': 'mag parameter required'}), 400

    try:
        from app.services.planning.observation_script import exposure_time
        result = exposure_time(mag)
        if isinstance(result, str):
            # "Too faint to observe" or "Invalid magnitude"
            return jsonify({'error': result})

        # result is dict like {"up": "60sec*1", "gp": "30sec*1", ...}
        filters = []
        for filt, val in result.items():
            parts = val.replace('sec*', ' ').split()
            exp = int(parts[0])
            count = int(parts[1])
            filters.append({'filter': filt, 'exp': exp, 'count': count})

        return jsonify({'success': True, 'filters': filters, 'telescope': telescope})
    except Exception as e:
        logger.error('Auto exposure error: %s', e)
        return jsonify({'error': str(e)}), 500
