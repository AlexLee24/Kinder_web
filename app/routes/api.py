"""
API routes for the Kinder web application.
"""
import math
import urllib.parse
from datetime import datetime
from flask import request, jsonify, session

from modules.tns_database import (
    get_tns_statistics, get_objects_count, search_tns_objects,
    get_tag_statistics, get_filtered_stats, get_distinct_classifications,
    update_object_status, update_object_activity, get_auto_snooze_stats
)
from modules.tns_scheduler import tns_scheduler
from modules.auto_snooze_scheduler import auto_snooze_scheduler
from modules.object_data import object_db
from modules.data_processing import DataVisualization


def register_api_routes(app):
    """Register API routes with the Flask app"""
    
    # ===============================================================================
    # OBJECT MANAGEMENT API
    # ===============================================================================
    @app.route('/api/objects', methods=['POST'])
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
            
            from modules.tns_database import get_tns_db_connection
            import uuid
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            objid = str(uuid.uuid4())
            
            if discovery_date:
                try:
                    datetime.strptime(discovery_date, '%Y-%m-%d')
                except ValueError:
                    return jsonify({'error': 'Invalid discovery date format. Use YYYY-MM-DD'}), 400
            else:
                discovery_date = datetime.now().strftime('%Y-%m-%d')
            
            insert_query = '''
            INSERT INTO tns_objects (
                objid, name, name_prefix, type, ra, declination, 
                discoverymag, discoverydate, source_group, 
                time_received, lastmodified, tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            
            current_time = datetime.now().isoformat()
            
            cursor.execute(insert_query, (
                objid,
                object_name,
                '',
                object_type,
                ra,
                dec,
                magnitude,
                discovery_date,
                source or 'Manual Entry',
                current_time,
                current_time,
                'object'
            ))
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': f'Object {object_name} added successfully',
                'object_name': object_name,
                'objid': objid
            })
            
        except ValueError as e:
            return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Database error: {str(e)}'}), 500

    @app.route('/api/auto-snooze/manual-run', methods=['POST'])
    def manual_auto_snooze():
        """Manually trigger auto-snooze check"""
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'success': False, 'error': 'Admin access required'}), 403
        
        try:
            result = auto_snooze_scheduler.manual_auto_snooze()
            
            if isinstance(result, dict):
                return jsonify({
                    'success': True,
                    'snoozed_count': result.get('snoozed_count', 0),
                    'unsnoozed_count': result.get('unsnoozed_count', 0),
                    'total_processed': result.get('total_processed', 0)
                })
            else:
                return jsonify({
                    'success': True,
                    'total_processed': result,
                    'snoozed_count': 0,
                    'unsnoozed_count': 0
                })
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/stats')
    def api_get_stats():
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
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
                'at_count': at_count,
                'classified_count': classified_count,
                'total_count': total_count
            }
            
            return jsonify({
                'success': True,
                'stats': stats
            })
            
        except Exception as e:
            app.logger.error(f"Stats API error: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e),
                'stats': {
                    'inbox_count': 0,
                    'followup_count': 0,
                    'finished_count': 0,
                    'snoozed_count': 0,
                    'at_count': 0,
                    'classified_count': 0,
                    'total_count': 0
                }
            }), 500

    @app.route('/api/objects')
    def api_get_objects():
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        sort_by = request.args.get('sort_by', 'discoverydate')
        sort_order = request.args.get('sort_order', 'desc')
        search = request.args.get('search', '')
        classification = request.args.get('classification', '')
        tag = request.args.get('tag', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        app_mag_min = request.args.get('app_mag_min', '')
        app_mag_max = request.args.get('app_mag_max', '')
        redshift_min = request.args.get('redshift_min', '')
        redshift_max = request.args.get('redshift_max', '')
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
            app.logger.error(f"API error: {str(e)}")
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

    @app.route('/api/object-tags', methods=['POST'])
    def api_get_object_tags():
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            data = request.get_json()
            object_names = data.get('object_names', [])
            
            if not object_names:
                return jsonify({'success': True, 'tags': {}})
            
            from modules.tns_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            placeholders = ','.join(['?' for _ in object_names])
            
            cursor.execute(f'''
                SELECT name, COALESCE(tag, 'object') as tag
                FROM tns_objects 
                WHERE name IN ({placeholders})
            ''', object_names)
            
            results = cursor.fetchall()
            conn.close()
            
            tag_mapping = {}
            for name, tag in results:
                tag_mapping[name] = tag
            
            for name in object_names:
                if name not in tag_mapping:
                    tag_mapping[name] = 'object'
            
            return jsonify({
                'success': True,
                'tags': tag_mapping
            })
            
        except Exception as e:
            app.logger.error(f"Object tags API error: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/classifications')
    def api_get_classifications():
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            classifications = get_distinct_classifications()
            
            return jsonify({
                'success': True,
                'classifications': classifications
            })
        except Exception as e:
            app.logger.error(f"Classifications API error: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e),
                'classifications': ['AT', 'Kilonova']
            }), 500

    # ===============================================================================
    # TNS DATA MANAGEMENT
    # ===============================================================================
    @app.route('/api/tns/manual-download', methods=['POST'])
    def manual_tns_download():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            data = request.get_json() or {}
            hour_offset = data.get('hour_offset', 0)
            
            result = tns_scheduler.manual_download(hour_offset)
            
            return jsonify({
                'success': True,
                'message': f'Successfully processed {result["total_processed"]} TNS objects ({result["imported"]} new, {result["updated"]} updated)',
                'imported_count': result['imported'],
                'updated_count': result['updated'],
                'total_processed': result['total_processed']
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/tns/search', methods=['POST'])
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

    @app.route('/api/tns/stats')
    def tns_stats_api():
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            stats = get_tns_statistics()
            return jsonify({'success': True, 'stats': stats})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/auto-snooze/status')
    def auto_snooze_status():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            status = auto_snooze_scheduler.get_status()
            return jsonify({'success': True, 'status': status})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/auto-snooze/stats')
    def auto_snooze_stats_api():
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            stats = get_auto_snooze_stats()
            return jsonify({'success': True, 'stats': stats})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
