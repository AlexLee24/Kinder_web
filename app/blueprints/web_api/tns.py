"""JSON API used by the marshal/object pages and external API-key clients — tns (split from web_api_routes.py)."""
from datetime import datetime, timezone
from flask import request, jsonify, session
from app.db.transient import get_tns_statistics, search_tns_objects, get_auto_snooze_stats
from app.services.tns.manual_tns_download import download_TNS_api_hr, addin_database, auto_snoozed
from . import web_api_bp
from app.core.auth import admin_required, login_required


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
    
    try:
        data = request.get_json() or {}
        hour_offset = data.get('hour_offset', 0)
        
        # Download TNS data
        utc_now = datetime.now(timezone.utc)
        utc_hr = f"{(utc_now.hour - hour_offset) % 24:02d}"
        
        download_success = download_TNS_api_hr(utc_hr, debug=True)
        
        if not download_success:
            return jsonify({'error': 'Download failed'}), 500
        
        # Import to database from the shared TNS work directory (app/data/tns_api_download_work)
        from app.paths import TNS_WORK_DIR
        SAVE_DIR = TNS_WORK_DIR
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
@login_required(error='Access denied', status=403)
def search_tns():
    
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
@login_required(error='Access denied', status=403)
def tns_stats_api():
    
    try:
        stats = get_tns_statistics()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500
