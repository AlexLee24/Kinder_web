"""JSON API used by the marshal/object pages and external API-key clients — observation_v1 (split from web_api_routes.py)."""
from datetime import datetime, timezone
from flask import request, jsonify
from app.core.request_validation import get_int_arg, ParamOutOfRangeError
from app.db.auth import get_user_by_api_key
from app.db.obs import (
    get_observation_targets,
    save_observation_target,
    get_observation_logs,
    upsert_observation_log,
    delete_observation_log,
)
import logging

logger = logging.getLogger(__name__)
from . import web_api_bp
from .helpers import _limit_decimal_4, _normalize_target_precision


@web_api_bp.route('/api/v1/observation_targets', methods=['GET', 'POST'])
def api_v1_observation_targets():
    """
    API: Get or add observation targets.
    Auth: X-API-Key header OR ?api_key= query param

    GET /api/v1/observation_targets?telescope=SLT|LOT
        Returns active targets. telescope param is optional.

    POST /api/v1/observation_targets
        Add a new observation target. Requires is_great_lab_member or is_admin role.
        Body (JSON):
          {
            "telescope":    "SLT",              -- required, SLT or LOT
            "name":         "SN2025abc",        -- required
            "ra":           "12:34:56.7",       -- required
            "dec":          "+12:34:56",        -- required
            "mag":          18.5,               -- optional
            "priority":     "Normal",           -- optional, Normal/High/Urgent
            "repeat_count": 0,                  -- optional
            "filters": [                        -- optional
              {"filter": "rp", "exp": 300, "count": 3}
            ],
            "plan":         "Note text",        -- optional
            "program":      "R01",              -- optional (LOT only)
            "note_gl":      "GL note"           -- optional
          }
    """
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key', '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'Missing API key. Use X-API-Key header or ?api_key= param.'}), 401

    user = get_user_by_api_key(api_key)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid API key.'}), 401

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        telescope_filter = request.args.get('telescope', '').strip().upper()
        if telescope_filter and telescope_filter not in ('SLT', 'LOT'):
            return jsonify({'success': False, 'error': 'telescope must be SLT or LOT'}), 400

        try:
            all_targets = get_observation_targets()
            all_targets = [t for t in all_targets if t.get('is_active', True)]
            all_targets = [_normalize_target_precision(t) for t in all_targets]
        except Exception as e:
            return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500

        slt = [t for t in all_targets if t['telescope'] == 'SLT']
        lot = [t for t in all_targets if t['telescope'] == 'LOT']

        resp = {
            'success': True,
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'requested_by': user.get('email'),
        }
        if telescope_filter == 'SLT':
            resp['SLT'] = slt
        elif telescope_filter == 'LOT':
            resp['LOT'] = lot
        else:
            resp['SLT'] = slt
            resp['LOT'] = lot
        return jsonify(resp)

    # ── POST ─────────────────────────────────────────────────────────────────
    is_member = user.get('is_great_lab_member', False)
    is_admin  = user.get('is_admin', False)
    if not (is_member or is_admin):
        return jsonify({'success': False, 'error': 'Forbidden: requires GREAT Lab member or admin role'}), 403

    data = request.get_json(silent=True) or {}

    telescope = (data.get('telescope') or '').strip().upper()
    name      = (data.get('name') or '').strip()
    ra        = _limit_decimal_4((data.get('ra') or '').strip())
    dec       = _limit_decimal_4((data.get('dec') or '').strip())
    mag       = _limit_decimal_4(data.get('mag'))
    # LOT never uses auto exposure
    auto_exposure = bool(data.get('auto_exposure', False))
    if telescope == 'LOT':
        auto_exposure = False

    if not telescope or telescope not in ('SLT', 'LOT'):
        return jsonify({'success': False, 'error': 'telescope is required and must be SLT or LOT'}), 400
    if not name:
        return jsonify({'success': False, 'error': 'name is required'}), 400
    if not ra or not dec:
        return jsonify({'success': False, 'error': 'ra and dec are required'}), 400

    priority = (data.get('priority') or 'Normal').strip()
    if priority not in ('Normal', 'High', 'Urgent'):
        return jsonify({'success': False, 'error': 'priority must be Normal, High, or Urgent'}), 400

    try:
        new_id = save_observation_target(
            telescope=telescope,
            name=name,
            mag=mag,
            ra=ra,
            dec=dec,
            priority=priority,
            repeat_count=int(data.get('repeat_count') or 0),
            auto_exposure=auto_exposure,
            filters=data.get('filters', []),
            plan=data.get('plan'),
            program=data.get('program'),
            note_gl=data.get('note_gl', ''),
            user_email=user.get('email')
        )
        if new_id:
            return jsonify({
                'success': True,
                'message': f'Target {name} added to {telescope}',
                'id': new_id,
                'target': {
                    'id': new_id,
                    'telescope': telescope,
                    'name': name,
                    'ra': ra,
                    'dec': dec,
                    'mag': mag,
                    'priority': priority,
                    'repeat_count': int(data.get('repeat_count') or 0),
                    'auto_exposure': auto_exposure,
                }
            }), 201
        else:
            return jsonify({'success': False, 'error': 'Failed to save target'}), 500
    except Exception as e:
        logger.error(f'api_v1_observation_targets POST error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/v1/observation_logs', methods=['GET', 'POST'])
def api_v1_observation_logs():
    """
    API: Get or upsert observation logs.
    Auth: X-API-Key header OR ?api_key= query param

    GET  /api/v1/observation_logs?year=2026&month=3
    GET  /api/v1/observation_logs?date=2026-03-09  -- Get for specific date
    POST /api/v1/observation_logs
         Body (JSON):
           {
             "target_name":    "SN2025wny",  -- required
             "telescope":      "LOT",         -- optional
             "obs_date":       "2026-03-09",  -- required (YYYY-MM-DD)
             "is_triggered":   true,          -- optional
             "trigger_filter": "rp",          -- optional
             "trigger_exp":    300,           -- optional (seconds)
             "trigger_count":  12,            -- optional (frames)
             "is_observed":    false,         -- optional
             "observed_filter": "rp",         -- optional
             "observed_exp":   300,           -- optional
             "observed_count": 12,            -- optional
             "user_name":      "Alex"         -- optional, auto-fills from API key owner
           }

    DELETE (via POST with action=delete):
         Body (JSON):
           {
             "action":      "delete",
             "target_name": "SN2025wny",
             "obs_date":    "2026-03-09"
           }
    """
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key', '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'Missing API key. Use X-API-Key header or ?api_key= param.'}), 401

    user = get_user_by_api_key(api_key)
    if not user:
        return jsonify({'success': False, 'error': 'Invalid API key.'}), 401

    try:
        if request.method == 'GET':
            year = get_int_arg('year')
            month = get_int_arg('month')
            date_str = request.args.get('date', type=str)
            
            # If a specific date is requested, ignore year/month
            if date_str:
                try:
                    target_dt = datetime.strptime(date_str, '%Y-%m-%d')
                    year, month = target_dt.year, target_dt.month
                except ValueError:
                    return jsonify({'success': False, 'error': 'date must be in YYYY-MM-DD format'}), 400
            elif not year or not month:
                return jsonify({'success': False, 'error': 'year/month or a specific date query param is required'}), 400

            logs = get_observation_logs(year, month)
            
            # Filter by exact date if date_str is provided
            if date_str:
                logs = [log for log in logs if str(log.get('obs_date', '')) == date_str]

            for log in logs:
                if log.get('obs_date') and hasattr(log['obs_date'], 'strftime'):
                    log['obs_date'] = log['obs_date'].strftime('%Y-%m-%d')

            return jsonify({
                'success': True,
                'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'requested_by': user.get('email'),
                'query_params': {'year': year, 'month': month, 'date': date_str},
                'logs': logs
            })

        elif request.method == 'POST':
            data = request.get_json(silent=True) or {}
            action = data.get('action', 'upsert')

            target_name = data.get('target_name', '').strip()
            telescope_hint = data.get('telescope', '').strip().upper()
            obs_date = data.get('obs_date', '').strip()

            if not target_name or not obs_date:
                return jsonify({'success': False, 'error': 'target_name and obs_date are required'}), 400

            # Validate obs_date format
            try:
                datetime.strptime(obs_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'success': False, 'error': 'obs_date must be YYYY-MM-DD format'}), 400

            if action == 'delete':
                ok = delete_observation_log(target_name, obs_date)
                if ok:
                    return jsonify({'success': True, 'message': f'Log deleted for {target_name} on {obs_date}'})
                else:
                    return jsonify({'success': False, 'error': 'Failed to delete log or log not found'}), 500
            else:
                import json as _json
                def _norm_filter(val):
                    """Accept list[dict] or plain string; always store as JSON string."""
                    if not val:
                        return None
                    if isinstance(val, list):
                        return _json.dumps(val)
                    return str(val)  # legacy plain string kept as-is

                is_triggered = bool(data.get('is_triggered', False))
                is_observed  = bool(data.get('is_observed', False))
                trigger_filter  = _norm_filter(data.get('trigger_filter'))
                trigger_exp     = data.get('trigger_exp') if data.get('trigger_exp') is not None else None
                trigger_count   = data.get('trigger_count') if data.get('trigger_count') is not None else None
                observed_filter = _norm_filter(data.get('observed_filter'))
                observed_exp    = data.get('observed_exp') if data.get('observed_exp') is not None else None
                observed_count  = data.get('observed_count') if data.get('observed_count') is not None else None
                # Auto-fill user_name from API key owner if not provided
                user_name = data.get('user_name') or user.get('name') or user.get('email')
                # Normalize priority; split compound "Normal - R01" -> priority + program
                _VALID_PRIORITIES = {'urgent': 'Urgent', 'high': 'High', 'normal': 'Normal', 'filler': 'Filler'}
                _raw_pri = (data.get('priority') or '').strip()
                if ' - ' in _raw_pri:
                    _pri_part, _prog_part = _raw_pri.split(' - ', 1)
                    _pri_part = _pri_part.strip()
                    _prog_part = _prog_part.strip()
                else:
                    _pri_part = _raw_pri
                    _prog_part = data.get('program', '') or ''
                priority = _VALID_PRIORITIES.get(_pri_part.lower(), _pri_part.title()) if _pri_part else None
                program = _prog_part

                ok = upsert_observation_log(
                    target_name, obs_date, user_name, is_triggered, is_observed,
                    trigger_filter, trigger_exp, trigger_count,
                    observed_filter, observed_exp, observed_count,
                    priority=priority, telescope_use=telescope_hint, program=program
                )
                if ok:
                    return jsonify({
                        'success': True,
                        'message': 'Log saved',
                        'log': {
                            'target_name': target_name,
                            'telescope': telescope_hint or None,
                            'obs_date': obs_date,
                            'user_name': user_name,
                            'is_triggered': is_triggered,
                            'trigger_filter': trigger_filter,
                            'trigger_exp': trigger_exp,
                            'trigger_count': trigger_count,
                            'is_observed': is_observed,
                            'observed_filter': observed_filter,
                            'observed_exp': observed_exp,
                            'observed_count': observed_count,
                            'priority': priority
                        }
                    })
                else:
                    return jsonify({'success': False, 'error': 'Failed to save log'}), 500

    except ParamOutOfRangeError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
