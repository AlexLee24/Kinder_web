"""
API routes for the Kinder web application.
"""
import logging
import math
import re

logger = logging.getLogger(__name__)
import urllib.parse
from datetime import datetime, timezone
from flask import request, jsonify, session

from modules.database.transient import (
    get_tns_statistics, get_objects_count, search_tns_objects,
    get_tag_statistics, get_filtered_stats, get_distinct_classifications,
    update_object_status, update_object_activity, get_auto_snooze_stats,
    get_object_flag_status, update_object_flag_by_name,
    get_object_pin_status, toggle_object_pin
)
from modules.database import get_db_connection, get_tns_db_connection, OBJECT_COMPAT_COLS
from modules.database.auth import (
    generate_api_key_for_user, get_user_by_api_key
)
from modules.database.obs import (
    get_observation_targets, save_observation_target,
    get_observation_logs, upsert_observation_log, delete_observation_log
)
from modules.Manual_tns_download_snoozed import download_TNS_api_hr, addin_database, auto_snoozed
from modules.download_phot import process_single_object_workflow
from modules.data_processing import DataVisualization
import pathlib


from flask import Blueprint
web_api_bp = Blueprint('web_api', __name__, template_folder='templates', static_folder='static')
"""Register API routes with the Flask app"""


def _limit_decimal_4(value):
    """Limit decimal precision to at most 4 digits after decimal point."""
    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return value
        return round(float(value), 4)

    if isinstance(value, str):
        s = value.strip()
        # Keep sexagesimal or non-numeric strings unchanged.
        if ':' in s:
            return value
        if re.fullmatch(r'[-+]?\d+(\.\d+)?', s):
            n = float(s)
            if math.isfinite(n):
                return f"{n:.4f}".rstrip('0').rstrip('.')
        return value

    return value


def _normalize_target_precision(target: dict) -> dict:
    out = dict(target or {})
    out['ra'] = _limit_decimal_4(out.get('ra'))
    out['dec'] = _limit_decimal_4(out.get('dec'))
    out['mag'] = _limit_decimal_4(out.get('mag'))

    filters = out.get('filters') or []
    if isinstance(filters, list):
        normalized_filters = []
        for f in filters:
            if isinstance(f, dict):
                ff = dict(f)
                ff['exp'] = _limit_decimal_4(ff.get('exp'))
                normalized_filters.append(ff)
            else:
                normalized_filters.append(f)
        out['filters'] = normalized_filters
    return out

# ===============================================================================
# OBJECT MANAGEMENT API
# ===============================================================================
@web_api_bp.route('/api/generate_key', methods=['POST'])
def generate_key():
    if 'user' not in session or session['user'].get('role') == 'guest':
        return jsonify({'success': False, 'error': 'API keys are only available for authorized users.'}), 403

    email = session['user']['email']
    new_key = generate_api_key_for_user(email)
    
    if new_key:
        session['user']['api_key'] = new_key
        session.modified = True
        return jsonify({'success': True, 'api_key': new_key})
    else:
        return jsonify({'success': False, 'error': 'Failed to generate API key.'}), 500

@web_api_bp.route('/api/test', methods=['GET', 'POST'])
def api_test():
    # Authentication via header
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return jsonify({'success': False, 'error': 'Missing API Key in headers (X-API-Key)'}), 401
        
    user = get_user_by_api_key(api_key)
    
    if not user:
        return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
    # Return testing information
    return jsonify({
        'success': True,
        'message': 'API Authentication successful!',
        'user': {
            'name': user.get('name'),
            'email': user.get('email'),
            'role': user.get('role', 'user'),
            'is_admin': user.get('is_admin', False),
            'groups': user.get('groups', [])
        }
    })

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
            auto_exposure=bool(data.get('auto_exposure', True)),
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
            year = request.args.get('year', type=int)
            month = request.args.get('month', type=int)
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

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/object/<object_name>/detect_cross_match', methods=['GET'])
def trigger_detect_cross_match(object_name):
    try:
        from modules.detect_cross_match import has_detect_run, get_detect_results_for_target, run_all_detect, save_detect_results
        import re as _re
        object_name = urllib.parse.unquote(object_name).strip()
        # Normalize: strip AT/SN prefix (allow optional spaces, case-insensitive)
        _m = _re.match(r'^(?:AT|SN)\s*(\d.+)$', object_name, flags=_re.IGNORECASE)
        if _m:
            object_name = _m.group(1)

        # Resolve canonical object name from DB (case-insensitive) for stable downstream queries.
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT obj_id, name, ra, dec FROM transient.objects "
                    "WHERE lower(name) = lower(%s) LIMIT 1",
                    (object_name,)
                )
                row = cur.fetchone()

        if not row:
            return jsonify({'success': False, 'error': 'Object not found in database'}), 404

        obj_id, canonical_name, ra, dec = row
        object_name = canonical_name
        
        force_param = (request.args.get('force') or '').strip().lower()
        # Default: DB-first. Only re-run when force=true (Run/Refresh button).
        force = (force_param == 'true')

        # ── DB-first path ──────────────────────────────────────────────────
        if not force and has_detect_run(object_name):
            results = get_detect_results_for_target(object_name)
            from modules.database.transient import get_detect_images as _get_imgs
            imgs = _get_imgs(canonical_name)
            return jsonify({'success': True, 'ran_now': False, 'results': results,
                            'detect_image_id': imgs[0]['image_id'] if imgs else None})

        # ── Run path (force=true, or first time) ───────────────────────────
        if force:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM transient.cross_matches WHERE obj_id = %s", (obj_id,))
                    conn.commit()

        # Execute cross match
        new_results = run_all_detect(object_name, float(ra), float(dec))
        
        # Save results
        save_detect_results(object_name, new_results)
        
        # Fetch formatted results
        final_results = get_detect_results_for_target(object_name)
        
        # Auto-generate finder chart from in-memory results (have ra/dec)
        detect_image_id = None
        try:
            import json as _json2
            from modules.detect_image import create_marked_image
            from modules.database.transient import save_detect_image as _save_img
            _LENS_PFX = ('LENS', 'SLACS', 'BELLS', 'HOLISMOKES',
                         'GAIA_GRAL', 'DES_SV', 'CASTLES', 'ONLINE_LENS', 'SUGOHGI')
            coord_list = []
            for r in new_results:
                md = {}
                try:
                    raw = r.get('match_data') or {}
                    md = _json2.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass
                ra_m  = md.get('ra')  or md.get('_RAJ2000')
                dec_m = md.get('dec') or md.get('_DEJ2000')
                if ra_m is None or dec_m is None:
                    continue
                cat = (r.get('catalog_name') or '').upper()
                src_type = ('DESI' if cat == 'DESI'
                            else 'Lens' if any(cat.startswith(p) for p in _LENS_PFX)
                            else 'VizieR')
                z = md.get('z') or md.get('z_lens') or md.get('z_spec')
                coord_list.append({
                    'ra':       float(ra_m),
                    'dec':      float(dec_m),
                    'redshift': float(z) if z is not None else 'N/A',
                    'name':     r.get('catalog_name', '?'),
                    'type':     src_type,
                })
            img_bytes = create_marked_image(
                obj_name=object_name,
                target_ra=float(ra),
                target_dec=float(dec),
                coord_list=coord_list,
                fov_arcsec=90,
            )
            detect_image_id = _save_img(object_name, 'detect_combined', img_bytes)
        except Exception as img_e:
            logger.warning('Auto-generate detect image failed for %s: %s', object_name, img_e)
        
        return jsonify({'success': True, 'ran_now': True, 'results': final_results,
                        'detect_image_id': detect_image_id})
        
    except Exception as e:
        logger.error(f'Error running detect for {object_name}: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500


@web_api_bp.route('/api/object/<object_name>/detect_images', methods=['GET'])
def list_detect_images(object_name):
    """Return list of DETECT finder-chart image metadata for the object."""
    try:
        from modules.database.transient import get_detect_images
        name = urllib.parse.unquote(object_name).strip()
        images = get_detect_images(name)
        return jsonify({'success': True, 'images': images})
    except Exception as e:
        logger.error('list_detect_images %s: %s', object_name, e)
        return jsonify({'success': False, 'error': str(e)}), 500


@web_api_bp.route('/api/object/<object_name>/detect_images/generate', methods=['POST'])
def generate_detect_images(object_name):
    """Generate a finder-chart image from stored DETECT results and save to DB."""
    try:
        from modules.detect_cross_match import run_all_detect
        from modules.detect_image import create_marked_image
        from modules.database.transient import save_detect_image, get_detect_images
        from psycopg2.extras import RealDictCursor

        name = urllib.parse.unquote(object_name).strip()

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT obj_id, name, ra, dec FROM transient.objects "
                    "WHERE lower(name) = lower(%s) LIMIT 1",
                    (name,)
                )
                row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Object not found'}), 404
        obj_id, canonical_name, target_ra, target_dec = row

        _LENS_PFX = ('LENS', 'SLACS', 'BELLS', 'HOLISMOKES', 'SUGOHGI',
                     'GAIA_GRAL', 'DES_SV', 'CASTLES', 'ONLINE_LENS')

        # Read match_ra / match_dec directly — these are explicit columns set when saving
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Ensure columns exist (in case of old schema)
                cur.execute("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_ra  DOUBLE PRECISION")
                cur.execute("ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_dec DOUBLE PRECISION")
                cur.execute(
                    "SELECT catalog AS catalog_name, separation, redshift, match_ra, match_dec "
                    "FROM transient.cross_matches "
                    "WHERE obj_id = %s AND catalog != 'DETECT_STATUS_RUN' "
                    "ORDER BY separation ASC",
                    (obj_id,)
                )
                matches = cur.fetchall()

        def _row_to_coord(r):
            ra_m, dec_m = r.get('match_ra'), r.get('match_dec')
            if ra_m is None or dec_m is None:
                return None
            cat = (r.get('catalog_name') or '').upper()
            src_type = ('DESI' if cat == 'DESI'
                        else 'Lens' if any(cat.startswith(p) for p in _LENS_PFX)
                        else 'VizieR')
            z = r.get('redshift')
            return {
                'ra':       float(ra_m),
                'dec':      float(dec_m),
                'redshift': float(z) if z is not None else 'N/A',
                'name':     r.get('catalog_name', '?'),
                'type':     src_type,
            }

        coord_list = [c for c in (_row_to_coord(r) for r in matches) if c is not None]

        # Fallback 1: parse match_data JSON for records that have it but match_ra/dec is NULL
        if not coord_list:
            import json as _json
            logger.info('generate_detect_images: match_ra/dec all NULL, trying match_data JSON: %s', canonical_name)
            with get_db_connection() as conn2:
                with conn2.cursor(cursor_factory=RealDictCursor) as cur2:
                    cur2.execute(
                        "ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS match_data JSONB"
                    )
                    cur2.execute(
                        "SELECT catalog AS catalog_name, separation, redshift, match_data "
                        "FROM transient.cross_matches "
                        "WHERE obj_id = %s AND catalog != 'DETECT_STATUS_RUN' "
                        "ORDER BY separation ASC",
                        (obj_id,)
                    )
                    md_rows = cur2.fetchall()
            for r in md_rows:
                md = {}
                try:
                    raw = r.get('match_data') or {}
                    md = _json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    pass
                ra_m  = md.get('ra')  or md.get('_RAJ2000')
                dec_m = md.get('dec') or md.get('_DEJ2000')
                if ra_m is None or dec_m is None:
                    continue
                try:
                    ra_m, dec_m = float(ra_m), float(dec_m)
                except (TypeError, ValueError):
                    continue
                cat = (r.get('catalog_name') or '').upper()
                src_type = ('DESI' if cat == 'DESI'
                            else 'Lens' if any(cat.startswith(p) for p in _LENS_PFX)
                            else 'VizieR')
                z = r.get('redshift') or md.get('z') or md.get('z_lens') or md.get('z_spec')
                coord_list.append({
                    'ra':       ra_m,
                    'dec':      dec_m,
                    'redshift': float(z) if z is not None else 'N/A',
                    'name':     r.get('catalog_name', '?'),
                    'type':     src_type,
                })

        # Fallback 2: re-run CM in-memory (old records with no match_data either)
        if not coord_list:
            import json as _json
            logger.info('generate_detect_images: no coords in DB at all, re-running CM: %s', canonical_name)
            fresh = run_all_detect(canonical_name, float(target_ra), float(target_dec))
            for r in fresh:
                md = {}
                try:
                    raw = r.get('match_data') or {}
                    md = _json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    pass
                ra_m  = md.get('ra')  or md.get('_RAJ2000')
                dec_m = md.get('dec') or md.get('_DEJ2000')
                if ra_m is None or dec_m is None:
                    continue
                try:
                    ra_m, dec_m = float(ra_m), float(dec_m)
                except (TypeError, ValueError):
                    continue
                cat = (r.get('catalog_name') or '').upper()
                src_type = ('DESI' if cat == 'DESI'
                            else 'Lens' if any(cat.startswith(p) for p in _LENS_PFX)
                            else 'VizieR')
                z = md.get('z') or md.get('z_lens') or md.get('z_spec')
                coord_list.append({
                    'ra':       ra_m,
                    'dec':      dec_m,
                    'redshift': float(z) if z is not None else 'N/A',
                    'name':     r.get('catalog_name', '?'),
                    'type':     src_type,
                })

        image_bytes = create_marked_image(
            obj_name=canonical_name,
            target_ra=float(target_ra),
            target_dec=float(target_dec),
            coord_list=coord_list,
            fov_arcsec=90,
        )
        image_id = save_detect_image(canonical_name, 'detect_combined', image_bytes)
        images = get_detect_images(canonical_name)
        return jsonify({'success': True, 'images': images, 'detect_image_id': image_id})

    except Exception as e:
        logger.error('generate_detect_images %s: %s', object_name, e)
        return jsonify({'success': False, 'error': str(e)}), 500


@web_api_bp.route('/api/objects', methods=['POST'])
def add_object():
    """Add a new object to the database"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied - Admin privileges required'}), 403
    
    try:
        data = request.get_json()
        
        required_fields = ['name', 'ra', 'dec']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        object_name = str(data['name']).strip()
        ra = float(data['ra'])
        dec = float(data['dec'])
        object_type = str(data.get('type', 'AT')).strip()
        magnitude = data.get('magnitude')
        discovery_date = data.get('discovery_date')
        source = (data.get('source') or '').strip() or 'Manual Entry'
        
        if not (0 <= ra < 360):
            return jsonify({'error': 'RA must be between 0 and 360 degrees'}), 400
        
        if not (-90 <= dec <= 90):
            return jsonify({'error': 'DEC must be between -90 and 90 degrees'}), 400
        
        if magnitude is not None:
            try:
                magnitude = float(magnitude)
                if not (-5 <= magnitude <= 30):
                    return jsonify({'error': 'Magnitude should be between -5 and 30'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid magnitude value'}), 400
        
        if len(object_name) < 3:
            return jsonify({'error': 'Object name must be at least 3 characters'}), 400
        
        existing_objects = search_tns_objects(search_term=object_name, limit=1)
        if existing_objects:
            return jsonify({'error': f'Object {object_name} already exists in database'}), 400
        
        if discovery_date:
            try:
                disc_dt = datetime.strptime(discovery_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Invalid discovery date format. Use YYYY-MM-DD'}), 400
        else:
            disc_dt = datetime.now()
            discovery_date = disc_dt.strftime('%Y-%m-%d')
        
        # Convert to MJD: days since 1858-11-17
        from datetime import date as _date
        _epoch = _date(1858, 11, 17)
        disc_mjd = (disc_dt.date() - _epoch).days
        now_mjd  = (datetime.now().date() - _epoch).days
        
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO transient.objects
               (name, name_prefix, type, ra, dec, discovery_mag, discovery_date,
                source_group, received_date, last_modified_date, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Object')
               RETURNING obj_id""",
            (object_name, '', object_type, ra, dec,
             magnitude, disc_mjd,
             source or 'Manual Entry',
             now_mjd, now_mjd)
        )
        new_obj_id = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Object {object_name} added successfully',
            'object_name': object_name,
            'objid': new_obj_id
        })
        
    except ValueError as e:
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@web_api_bp.route('/api/object/<path:object_name>/flag_status', methods=['GET'])
def get_flag_status(object_name):
    """Get flag status for an object"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    object_name = urllib.parse.unquote(object_name)
    is_flagged = get_object_flag_status(object_name)
    return jsonify({'is_flagged': is_flagged})

@web_api_bp.route('/api/object/<path:object_name>/toggle_flag', methods=['POST'])
def update_flag_status(object_name):
    """Toggle flag status for an object"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    flag_status = data.get('flag')
    
    if flag_status is None:
        return jsonify({'error': 'Missing flag status'}), 400
        
    success = update_object_flag_by_name(object_name, flag_status)
    if success:
        return jsonify({'success': True, 'is_flagged': flag_status})
    else:
        return jsonify({'error': 'Database error'}), 500

@web_api_bp.route('/api/object/<path:object_name>/pin_status', methods=['GET'])
def get_pin_status(object_name):
    """Get pin status for an object"""
    if 'user' not in session:
        return jsonify({'is_pinned': False})
    object_name = urllib.parse.unquote(object_name)
    is_pinned = get_object_pin_status(object_name)
    return jsonify({'is_pinned': is_pinned})

@web_api_bp.route('/api/object/<path:object_name>/toggle_pin', methods=['POST'])
def toggle_pin_status(object_name):
    """Toggle pin status for an object (admin only)"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    new_state = toggle_object_pin(object_name)
    return jsonify({'success': True, 'is_pinned': new_state})

@web_api_bp.route('/api/auto-snooze/manual-run', methods=['POST'])
def manual_auto_snooze():
    """Manually trigger auto-snooze check"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        # Run auto-snooze
        success = auto_snoozed(datetime.now(timezone.utc), debug=True)
        
        if success:
            # Get updated stats
            stats = get_auto_snooze_stats()
            return jsonify({
                'success': True,
                'snoozed_count': stats.get('snoozed_count', 0),
                'finished_count': stats.get('finished_count', 0),
                'message': 'Auto-snooze completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Auto-snooze failed'
            }), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/stats')
def api_get_stats():
    if 'user' not in session:
        return jsonify({'success': True, 'stats': {
            'inbox_count': 0, 'followup_count': 0, 'finished_count': 0,
            'snoozed_count': 0, 'flag_count': 0, 'at_count': 0,
            'classified_count': 0, 'total_count': 0
        }})
    
    try:
        total_count = get_objects_count()
        at_count = get_objects_count(object_type='AT')
        classified_count = total_count - at_count
        
        tag_stats = get_tag_statistics()
        
        stats = {
            'inbox_count': tag_stats.get('object', 0),
            'followup_count': tag_stats.get('followup', 0),
            'finished_count': tag_stats.get('finished', 0),
            'snoozed_count': tag_stats.get('snoozed', 0),
            'flag_count': tag_stats.get('flag', 0),
            'at_count': at_count,
            'classified_count': classified_count,
            'total_count': total_count
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        web_api_bp.logger.error(f"Stats API error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'stats': {
                'inbox_count': 0,
                'followup_count': 0,
                'finished_count': 0,
                'snoozed_count': 0,
                'flag_count': 0,
                'at_count': 0,
                'classified_count': 0,
                'total_count': 0
            }
        }), 500

@web_api_bp.route('/api/object/<path:object_name>/fetch_photometry', methods=['POST'])
def fetch_photometry(object_name):
    """Fetch photometry for a specific object"""
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
        
    try:
        object_name = urllib.parse.unquote(object_name)
        logger.info('Fetching photometry for %s', object_name)
        
        # Run the workflow
        process_single_object_workflow(object_name)
        
        return jsonify({
            'success': True,
            'message': f'Photometry fetch completed for {object_name}'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/objects')
def api_get_objects():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'discoverydate')
    sort_order = request.args.get('sort_order', 'desc')
    search = request.args.get('search', '')
    classification = request.args.get('classification', '')
    tag = request.args.get('tag', '')
    
    # Handle optional parameters that might be empty strings
    date_from = request.args.get('date_from', '')
    date_from = date_from if date_from else None
    
    date_to = request.args.get('date_to', '')
    date_to = date_to if date_to else None
    
    app_mag_min = request.args.get('app_mag_min', '')
    app_mag_min = float(app_mag_min) if app_mag_min else None
    
    app_mag_max = request.args.get('app_mag_max', '')
    app_mag_max = float(app_mag_max) if app_mag_max else None
    
    redshift_min = request.args.get('redshift_min', '')
    redshift_min = float(redshift_min) if redshift_min else None
    
    redshift_max = request.args.get('redshift_max', '')
    redshift_max = float(redshift_max) if redshift_max else None
    
    discoverer = request.args.get('discoverer', '')
    
    try:
        objects = search_tns_objects(
            search_term=search, 
            object_type=classification,
            limit=per_page, 
            offset=(page-1)*per_page,
            sort_by=sort_by, 
            sort_order=sort_order,
            date_from=date_from,
            date_to=date_to,
            tag=tag,
            app_mag_min=app_mag_min,
            app_mag_max=app_mag_max,
            redshift_min=redshift_min,
            redshift_max=redshift_max,
            discoverer=discoverer
        )
        
        total = get_objects_count(
            search_term=search, 
            object_type=classification,
            tag=tag,
            date_from=date_from,
            date_to=date_to,
            app_mag_min=app_mag_min,
            app_mag_max=app_mag_max,
            redshift_min=redshift_min,
            redshift_max=redshift_max,
            discoverer=discoverer
        )
        
        stats = get_filtered_stats(
            search_term=search, 
            object_type=classification,
            tag=tag,
            date_from=date_from,
            date_to=date_to,
            app_mag_min=app_mag_min,
            app_mag_max=app_mag_max,
            redshift_min=redshift_min,
            redshift_max=redshift_max,
            discoverer=discoverer
        )
        
        return jsonify({
            'objects': objects,
            'total': total,
            'total_pages': math.ceil(total / per_page) if total > 0 else 0,
            'page': page,
            'per_page': per_page,
            'stats': stats
        })
    except Exception as e:
        web_api_bp.logger.error(f"API error: {str(e)}")
        return jsonify({
            'objects': [],
            'total': 0,
            'total_pages': 0,
            'page': page,
            'per_page': per_page,
            'stats': {
                'inbox_count': 0,
                'followup_count': 0,
                'finished_count': 0,
                'snoozed_count': 0,
                'at_count': 0, 
                'classified_count': 0
            },
            'error': str(e)
        }), 500

@web_api_bp.route('/api/object-tags', methods=['POST'])
def api_get_object_tags():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        object_names = data.get('object_names', [])
        
        if not object_names:
            return jsonify({'success': True, 'tags': {}})
        
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        placeholders = ','.join(['%s' for _ in object_names])
        
        cursor.execute(f'''
            SELECT o.name,
                   array_to_string(o.tag, ', ') AS tags,
                   CASE o.status
                        WHEN 'Finish'    THEN 'finished'
                        WHEN 'Follow-up' THEN 'followup'
                        WHEN 'Snoozed'   THEN 'snoozed'
                        ELSE 'object'
                   END AS tag
            FROM transient.objects o
            WHERE o.name IN ({placeholders})
        ''', tuple(object_names))
        
        results = cursor.fetchall()
        conn.close()
        
        tag_mapping = {}
        tags_mapping = {}
        for name, obj_tags, tag in results:
            tag_mapping[name] = tag
            tags_mapping[name] = obj_tags
        
        for name in object_names:
            if name not in tag_mapping:
                tag_mapping[name] = 'object'
            if name not in tags_mapping:
                tags_mapping[name] = None
        
        return jsonify({
            'success': True,
            'tags': tag_mapping,
            'object_tags': tags_mapping
        })
        
    except Exception as e:
        web_api_bp.logger.error(f"Object tags API error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@web_api_bp.route('/api/classifications')
def api_get_classifications():
    if 'user' not in session:
        return jsonify({'success': True, 'classifications': []})
    
    try:
        classifications = get_distinct_classifications()
        
        return jsonify({
            'success': True,
            'classifications': classifications
        })
    except Exception as e:
        web_api_bp.logger.error(f"Classifications API error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'classifications': ['AT', 'Kilonova']
        }), 500

# ===============================================================================
# TNS DATA MANAGEMENT
# ===============================================================================
@web_api_bp.route('/api/tns/manual-download', methods=['POST'])
def manual_tns_download():
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json() or {}
        hour_offset = data.get('hour_offset', 0)
        
        # Download TNS data
        utc_now = datetime.now(timezone.utc)
        utc_hr = f"{(utc_now.hour - hour_offset) % 24:02d}"
        
        download_success = download_TNS_api_hr(utc_hr, debug=True)
        
        if not download_success:
            return jsonify({'error': 'Download failed'}), 500
        
        # Import to database — resolve absolute path relative to this file
        # web_api_routes.py -> web_api/ -> routes/ -> app/ -> data/
        SAVE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "tns_api_download_work"
        work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
        
        import_success = addin_database(work_csv, debug=True)
        
        if import_success:
            stats = get_tns_statistics()
            recent = stats.get('recent_downloads', [])
            latest = recent[0] if recent else {}
            
            return jsonify({
                'success': True,
                'message': f'Successfully downloaded and imported TNS data',
                'imported_count': latest.get('imported_count', 0),
                'updated_count': latest.get('updated_count', 0)
            })
        else:
            return jsonify({'error': 'Import failed'}), 500
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@web_api_bp.route('/api/tns/search', methods=['POST'])
def search_tns():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').strip()
        object_type = data.get('object_type', '').strip()
        limit = min(int(data.get('limit', 100)), 1000)
        
        results = search_tns_objects(search_term, object_type, limit)
        
        return jsonify({
            'success': True,
            'results': results,
            'count': len(results)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@web_api_bp.route('/api/tns/stats')
def tns_stats_api():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        stats = get_tns_statistics()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@web_api_bp.route('/api/auto-snooze/status')
def auto_snooze_status():
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        stats = get_auto_snooze_stats()
        return jsonify({
            'success': True, 
            'status': {
                'snoozed_count': stats.get('snoozed_count', 0),
                'finished_count': stats.get('finished_count', 0)
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@web_api_bp.route('/api/auto-snooze/stats')
def auto_snooze_stats_api():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        stats = get_auto_snooze_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
