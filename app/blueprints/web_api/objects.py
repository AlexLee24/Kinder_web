"""JSON API used by the marshal/object pages and external API-key clients — objects (split from web_api_routes.py)."""
import math
import urllib.parse
from datetime import datetime
from flask import request, jsonify, session
from app.db.transient import (
    get_objects_count,
    search_tns_objects,
    get_tag_statistics,
    get_filtered_stats,
    get_distinct_classifications,
    get_object_flag_status,
    update_object_flag_by_name,
    get_object_pin_status,
    toggle_object_pin,
)
from app.db import get_tns_db_connection
from app.core.request_validation import get_int_arg, get_float_arg
from app.services.photometry.download_phot import process_single_object_workflow
import logging
from app.core.auth import admin_required, login_required

logger = logging.getLogger(__name__)
from . import web_api_bp


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
                     source_group, received_date, last_modified_date, status, tag)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Object', '{}'::text[])
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
@login_required
def get_flag_status(object_name):
    """Get flag status for an object"""
        
    object_name = urllib.parse.unquote(object_name)
    is_flagged = get_object_flag_status(object_name)
    return jsonify({'is_flagged': is_flagged})

@web_api_bp.route('/api/object/<path:object_name>/toggle_flag', methods=['POST'])
@login_required
def update_flag_status(object_name):
    """Toggle flag status for an object"""
        
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
@admin_required
def toggle_pin_status(object_name):
    """Toggle pin status for an object (admin only)"""
    object_name = urllib.parse.unquote(object_name)
    new_state = toggle_object_pin(object_name)
    return jsonify({'success': True, 'is_pinned': new_state})

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
        logger.error(f"Stats API error: {str(e)}")
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
@login_required(error='Access denied', status=403)
def fetch_photometry(object_name):
    """Fetch photometry for a specific object"""
        
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
    page = get_int_arg('page', 1, min_val=1)
    per_page = get_int_arg('per_page', 50, min_val=1, max_val=500)
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

    app_mag_min = get_float_arg('app_mag_min')
    app_mag_max = get_float_arg('app_mag_max')
    redshift_min = get_float_arg('redshift_min')
    redshift_max = get_float_arg('redshift_max')

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
        logger.error(f"API error: {str(e)}")
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
@login_required(error='Access denied', status=403)
def api_get_object_tags():
    
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
        logger.error(f"Object tags API error: {str(e)}")
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
        logger.error(f"Classifications API error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'classifications': ['AT', 'Kilonova']
        }), 500
