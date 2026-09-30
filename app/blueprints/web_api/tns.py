"""JSON API used by the marshal/object pages and external API-key clients — tns (split from web_api_routes.py)."""
from datetime import datetime, timezone
from flask import request, jsonify, session
from app.db.transient import get_tns_statistics, search_tns_objects, get_auto_snooze_stats
from app.services.tns.manual_tns_download import download_TNS_api_hr, addin_database, auto_snoozed
from . import web_api_bp
from app.core.auth import admin_required, login_required
import logging

logger = logging.getLogger(__name__)


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

# ===============================================================================
# TNS DATA MANAGEMENT
# ===============================================================================
@web_api_bp.route('/api/tns/manual-download', methods=['POST'])
@admin_required
def manual_tns_download():
    
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    try:
        hour_offset = int(data.get('hour_offset', 0) or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'hour_offset must be an integer'}), 400

    work_csv = None
    try:
        from app.services.tns.auto_tns_download import new_work_csv_path

        # Download TNS data into a private CSV so concurrent imports never share a file
        utc_now = datetime.now(timezone.utc)
        utc_hr = f"{(utc_now.hour - hour_offset) % 24:02d}"

        work_csv = new_work_csv_path(f"manual{utc_hr}")
        downloaded = download_TNS_api_hr(utc_hr, debug=True, dest=work_csv)

        if not downloaded:
            return jsonify({'error': 'Download failed'}), 500

        import_success = addin_database(downloaded, debug=True)
        
        if import_success:
            stats = get_tns_statistics()
            recent = stats.get('recent_downloads', [])
            latest = recent[0] if recent else {}
            
            return jsonify({
                'success': True,
                'message': 'Successfully downloaded and imported TNS data',
                'imported_count': latest.get('imported_count', 0),
                'updated_count': latest.get('updated_count', 0)
            })
        else:
            return jsonify({'error': 'Import failed'}), 500
        
    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'TNS download/import failed'}), 500
    finally:
        if work_csv is not None:
            try:
                work_csv.unlink(missing_ok=True)
            except Exception as cleanup_err:
                logger.warning("manual TNS download: could not remove %s: %s", work_csv, cleanup_err)

@web_api_bp.route('/api/tns/search', methods=['POST'])
@login_required(error='Access denied', status=403)
def search_tns():
    
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object body required'}), 400
    search_term = data.get('search_term', '')
    object_type = data.get('object_type', '')
    if not isinstance(search_term, str) or not isinstance(object_type, str):
        return jsonify({'error': 'search_term and object_type must be strings'}), 400
    search_term = search_term.strip()
    object_type = object_type.strip()
    try:
        limit = int(data.get('limit', 100))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 1000))

    try:
        user = session.get('user') or {}
        results = search_tns_objects(
            search_term, object_type, limit,
            apply_permissions=True,
            viewer_email=user.get('email'),
            viewer_is_admin=bool(user.get('is_admin')),
        )
        
        return jsonify({
            'success': True,
            'results': results,
            'count': len(results)
        })
        
    except Exception as e:
        logger.error("tns search error: %s", e)
        return jsonify({'error': 'Search failed'}), 500

@web_api_bp.route('/api/tns/stats')
@login_required(error='Access denied', status=403)
def tns_stats_api():
    
    try:
        stats = get_tns_statistics()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error("tns stats error: %s", e)
        return jsonify({'error': 'Failed to load stats'}), 500

@web_api_bp.route('/api/auto-snooze/status')
@admin_required
def auto_snooze_status():
    
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
@login_required(error='Access denied', status=403)
def auto_snooze_stats_api():
    
    try:
        stats = get_auto_snooze_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error("auto-snooze stats error: %s", e)
        return jsonify({'error': 'Failed to load stats'}), 500
