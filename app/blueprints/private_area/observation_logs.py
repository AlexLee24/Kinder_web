"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — observation_logs (split from private_area_routes.py)."""
from flask import session, request, jsonify
from app.core.request_validation import get_int_arg, ParamOutOfRangeError
from . import private_area_bp


# @private_area_bp.route('/debug/object/<object_name>')
# Debug object tag route - disabled (old tns_database function)
# @private_area_bp.route('/api/debug-object-tag/<object_name>')
# def debug_object_tag_route(object_name):
#     if 'user' not in session or not session['user'].get('is_admin'):
#         return jsonify({'error': 'Access denied'}), 403
#     
#     try:
#         object_name = urllib.parse.unquote(object_name)
#         return jsonify({
#             'success': True,
#             'object_name': object_name,
#             'message': 'Debug function disabled - using PostgreSQL now'
#         })
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

@private_area_bp.route('/api/observation_log_months', methods=['GET'])
def api_get_observation_log_months():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        from app.db.obs import get_observation_log_months
        months = get_observation_log_months()
        return jsonify({'success': True, 'months': months})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@private_area_bp.route('/api/observation_logs', methods=['GET', 'POST'])
def api_get_observation_logs():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            year = get_int_arg('year')
            month = get_int_arg('month')
            if not year or not month:
                return jsonify({'success': False, 'error': 'Year and month are required'}), 400
                
            from app.db.obs import get_observation_logs
            logs = get_observation_logs(year, month)
            
            # Keep compatibility with both date objects and already-normalized strings.
            for log in logs:
                if getattr(log.get('obs_date'), 'strftime', None):
                    log['obs_date'] = log['obs_date'].strftime('%Y-%m-%d')
                    
            return jsonify({'success': True, 'logs': logs})
        elif request.method == 'POST':
            data = request.json
            action = (data.get('action') or '').strip().lower()
            target_name = (data.get('target_name') or '').strip()
            obs_date = data.get('obs_date')
            telescope_use = data.get('telescope_use')

            if action == 'delete':
                if not target_name or not obs_date:
                    return jsonify({'success': False, 'error': 'Target Name and Date required'}), 400
                from app.db.obs import delete_observation_log
                deleted = delete_observation_log(target_name, obs_date, telescope_use)
                if deleted:
                    return jsonify({'success': True})
                return jsonify({'success': False, 'error': 'Log not found or failed to delete'}), 404

            # Auto-fill user_name from session if not provided
            user_name = data.get('user_name') or session['user'].get('name') or session['user'].get('email')
            is_triggered = data.get('is_triggered', False)
            is_observed = data.get('is_observed', False)
            import json as _json
            def _norm_filter(val):
                if not val:
                    return None
                if isinstance(val, list):
                    return _json.dumps(val)
                return str(val)
            trigger_filter  = _norm_filter(data.get('trigger_filter'))
            observed_filter = _norm_filter(data.get('observed_filter'))
            priority = data.get('priority') or None
            program = (data.get('program') or '').strip() or None
            if priority and ' - ' in priority and not program:      # legacy "High - R01" form
                priority, program = [x.strip() for x in priority.split(' - ', 1)]
            telescope_use = data.get('telescope_use') or None

            # Backward compatibility: older clients may still send target_id
            if not target_name and data.get('target_id'):
                from app.db.obs import get_observation_targets
                tid = int(data.get('target_id'))
                t = next((x for x in get_observation_targets() if x.get('id') == tid), None)
                if t:
                    target_name = (t.get('name') or '').strip()
            
            if not target_name or not obs_date:
                return jsonify({'success': False, 'error': 'Target Name and Date required'}), 400
                
            from app.db.obs import upsert_observation_log
            success = upsert_observation_log(
                target_name, obs_date, user_name, is_triggered, is_observed,
                trigger_filter,
                data.get('trigger_exp') if data.get('trigger_exp') is not None else None,
                data.get('trigger_count') if data.get('trigger_count') is not None else None,
                observed_filter,
                data.get('observed_exp') if data.get('observed_exp') is not None else None,
                data.get('observed_count') if data.get('observed_count') is not None else None,
                priority=priority,
                program=program,
                telescope_use=telescope_use,
                repeat_count=int(data.get('repeat_count') or 0)
            )
            
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'Failed to save log'}), 500
    except ParamOutOfRangeError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
