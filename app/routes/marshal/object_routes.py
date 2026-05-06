"""
Object routes for the Kinder web application.
"""
import re
import math
import logging
import urllib.parse
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify, Response
import requests as _requests

logger = logging.getLogger(__name__)

from modules.database.transient import (
    search_tns_objects, update_object_status, update_object_activity,
    TNSObjectDB, update_object_abs_mag
)
from modules.database import get_db_connection, get_tns_db_connection, OBJECT_COMPAT_COLS
from modules.database.auth import (
    get_all_groups, get_object_permissions, grant_object_permission,
    revoke_object_permission, check_object_access,
    get_source_permissions, set_source_permissions_batch, filter_by_source_permissions
)
from modules.database.catalog import get_ned_cache, upsert_ned_cache
from modules.data_processing import DataVisualization
from modules import ext_M_calculator


from flask import Blueprint
objects_bp = Blueprint('marshal_bp', __name__)
"""Register object routes with the Flask app"""

# ===============================================================================
# OBJECT DETAILS
# ===============================================================================
@objects_bp.route('/object/<path:object_name>')
def object_detail_generic(object_name):
    """Generic object detail route for all object names"""
    try:
        object_name = urllib.parse.unquote(object_name)

        # Build visibility context
        user = session.get('user', {})
        role = user.get('role', 'guest') if user else 'guest'
        is_admin = user.get('is_admin', False) if user else False
        is_logged_in = bool(user)
        can_see_restricted = is_admin or role in ('user', 'admin')
        visibility = {
            'detect': can_see_restricted,
            'spectroscopy': can_see_restricted,
            'comments': can_see_restricted,
            'tags': can_see_restricted,
            'peak_abs_mag': can_see_restricted,
            'phot_controls': is_logged_in,
        }

        # Log view
        user_email = user.get('email') if user else None
        TNSObjectDB.log_object_view(object_name, user_email)
        
        # Update absolute magnitude and brightest mag
        update_object_abs_mag(object_name)
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        # Exact match queries (try multiple variants)
        tag_logic = """
        CASE o.status
            WHEN 'Finish'    THEN 'finished'
            WHEN 'Follow-up' THEN 'followup'
            WHEN 'Snoozed'   THEN 'snoozed'
            ELSE 'object'
        END as tag
        """
        
        exact_queries = [
            # Full name match (case insensitive)
            f"""SELECT o.obj_id AS objid, o.name_prefix, o.name, o.ra, o.dec AS declination,
                      o.redshift, NULL::int AS typeid, o.type,
                      NULL::int AS reporting_groupid, o.report_group AS reporting_group,
                      NULL::int AS source_groupid, o.source_group,
                      to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS discoverydate,
                      o.discovery_mag AS discoverymag, o.discovery_filter AS discmagfilter,
                      o.discovery_filter AS filter, array_to_string(o.reporters, ', ') AS reporters,
                      to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS time_received,
                      COALESCE(o.internal_name,'') AS internal_names, o.discovery_ADS AS discovery_ads_bibcode,
                      o.class_ADS AS class_ads_bibcodes,
                      to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS creationdate,
                      to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS lastmodified,
                      o.brightest_mag, o.brightest_abs_mag, array_to_string(o.tag, ', ') AS tags,
                      {tag_logic}
               FROM transient.objects o
               WHERE (COALESCE(o.name_prefix, '') || COALESCE(o.name, '')) ILIKE %s""",
            # Name only match (case insensitive)
            f"""SELECT o.obj_id AS objid, o.name_prefix, o.name, o.ra, o.dec AS declination,
                      o.redshift, NULL::int AS typeid, o.type,
                      NULL::int AS reporting_groupid, o.report_group AS reporting_group,
                      NULL::int AS source_groupid, o.source_group,
                      to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS discoverydate,
                      o.discovery_mag AS discoverymag, o.discovery_filter AS discmagfilter,
                      o.discovery_filter AS filter, array_to_string(o.reporters, ', ') AS reporters,
                      to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS time_received,
                      COALESCE(o.internal_name,'') AS internal_names, o.discovery_ADS AS discovery_ads_bibcode,
                      o.class_ADS AS class_ads_bibcodes,
                      to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS creationdate,
                      to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS lastmodified,
                      o.brightest_mag, o.brightest_abs_mag, array_to_string(o.tag, ', ') AS tags,
                      {tag_logic}
               FROM transient.objects o
               WHERE o.name ILIKE %s"""
        ]
        
        matching_obj = None
        for i, query in enumerate(exact_queries):
            cursor.execute(query, (object_name,))
            result = cursor.fetchone()
            if result:
                columns = [desc[0] for desc in cursor.description]
                matching_obj = dict(zip(columns, result))
                break

        # If exact match found but URL includes prefix, redirect to name-only canonical URL
        # e.g. /object/AT2025abc → /object/2025abc
        if matching_obj:
            prefix    = (matching_obj.get('name_prefix') or '').strip()
            name_only = (matching_obj.get('name') or '').strip()
            if prefix and object_name.lower() != name_only.lower():
                conn.close()
                return redirect(url_for('marshal_bp.object_detail_generic', object_name=name_only))

        # If still no match, try internal_names (e.g. ZTF ID) and tags (e.g. EP name)
        if not matching_obj:
            alias_query = """
                SELECT name_prefix, name
                FROM transient.objects
                WHERE internal_name ILIKE %s
                   OR EXISTS (
                       SELECT 1 FROM unnest(tag) t(v)
                       WHERE trim(t.v) ILIKE %s
                   )
                ORDER BY discovery_date DESC NULLS LAST
                LIMIT 1
            """
            cursor.execute(alias_query, (f'%{object_name}%', object_name))
            alias_result = cursor.fetchone()
            if alias_result:
                # Redirect to name-only (no prefix) canonical URL
                canonical = (alias_result[1] or '').strip()
                conn.close()
                return redirect(url_for('marshal_bp.object_detail_generic', object_name=canonical))

        conn.close()

        # If no exact match, fall back to fuzzy search
        if not matching_obj:
            results = search_tns_objects(search_term=object_name, limit=50)

            # Find exact match in fuzzy results
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                name_only = obj.get('name', '').strip()

                if (full_name.lower() == object_name.lower() or
                        name_only.lower() == object_name.lower()):
                    matching_obj = obj
                    break
                    
        
        if not matching_obj:
            flash(f'Object {object_name} not found.', 'error')
            return redirect(url_for('marshal.marshal'))
        
        # Values are already calculated by update_object_abs_mag and fetched from DB
        # No need to recalculate here

        # Calculate distance if redshift is available
        if matching_obj and matching_obj.get('redshift') is not None:
            try:
                from modules.astronomy_calculator import calculate_redshift_distance
                z = float(matching_obj['redshift'])
                if z > 0:
                    dist_result = calculate_redshift_distance(z)
                    matching_obj['distance_mpc'] = dist_result.get('distance_mpc')
            except Exception as e:
                print(f"Error calculating distance: {e}")

        # Convert datetime objects to strings for template compatibility
        if matching_obj:
            for key, value in matching_obj.items():
                if isinstance(value, datetime):
                    matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('object_detail.html', 
                             current_path='/object',
                             object_data=matching_obj,
                             object_name=object_name,
                             visibility=visibility)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Error loading object data.', 'error')
        return redirect(url_for('marshal.marshal'))

@objects_bp.route('/object/<int:year><string:letters>')
def object_detail_tns_format(year, letters):
    try:
        # Construct TNS-style name from year and letters
        object_name = f"{year}{letters}"

        # Build visibility context
        user = session.get('user', {})
        role = user.get('role', 'guest') if user else 'guest'
        is_admin = user.get('is_admin', False) if user else False
        is_logged_in = bool(user)
        can_see_restricted = is_admin or role in ('user', 'admin')
        visibility = {
            'detect': can_see_restricted,
            'spectroscopy': can_see_restricted,
            'comments': can_see_restricted,
            'tags': can_see_restricted,
            'peak_abs_mag': can_see_restricted,
            'phot_controls': is_logged_in,
        }

        # Log view
        user_email = user.get('email') if user else None
        TNSObjectDB.log_object_view(object_name, user_email)
        
        # Update absolute magnitude and brightest mag
        update_object_abs_mag(object_name)
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        tag_logic = """
        CASE o.status
            WHEN 'Finish'    THEN 'finished'
            WHEN 'Follow-up' THEN 'followup'
            WHEN 'Snoozed'   THEN 'snoozed'
            ELSE 'object'
        END as tag
        """
        
        # Exact match query - match name exactly (case insensitive)
        exact_query = f"""SELECT {OBJECT_COMPAT_COLS}
               FROM transient.objects o
               WHERE o.name ILIKE %s"""
        
        cursor.execute(exact_query, (object_name,))
        result = cursor.fetchone()
        matching_obj = None
        
        if result:
            columns = [desc[0] for desc in cursor.description]
            matching_obj = dict(zip(columns, result))
        
        conn.close()
        
        # If no exact match, fall back to fuzzy search
        if not matching_obj:
            results = search_tns_objects(search_term=object_name, limit=50)
            
            # Find exact match based on year + letters pattern
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                name_only = obj.get('name', '').strip()
                
                # Strategy 1: Direct match on name only
                if name_only.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 2: Direct match on full name
                if full_name.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 3: Extract year and letters from full name using regex
                match = re.search(r'(\d{4})([a-zA-Z]+)$', name_only)
                if match:
                    extracted_name = f"{match.group(1)}{match.group(2)}"
                    if extracted_name.lower() == object_name.lower():
                        matching_obj = obj
                        break
        
        if not matching_obj:
            flash(f'Object {object_name} not found.', 'error')
            return redirect(url_for('marshal.marshal'))
        
        # Values are already calculated by update_object_abs_mag and fetched from DB
        # No need to recalculate here

        # Calculate distance if redshift is available
        if matching_obj and matching_obj.get('redshift') is not None:
            try:
                from modules.astronomy_calculator import calculate_redshift_distance
                z = float(matching_obj['redshift'])
                if z > 0:
                    dist_result = calculate_redshift_distance(z)
                    matching_obj['distance_mpc'] = dist_result.get('distance_mpc')
            except Exception as e:
                print(f"Error calculating distance: {e}")

        # Convert datetime objects to strings for template compatibility
        if matching_obj:
            for key, value in matching_obj.items():
                if isinstance(value, datetime):
                    matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('object_detail.html', 
                             current_path='/object',
                             object_data=matching_obj,
                             object_name=object_name,
                             visibility=visibility)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Error loading object data.', 'error')
        return redirect(url_for('marshal.marshal'))

# ===============================================================================
# OBJECT API ENDPOINTS
# ===============================================================================
@objects_bp.route('/api/object/<int:year><alpha:letters>')
def api_get_object_tns_format(year, letters):
    
    try:
        object_name = f"{year}{letters}"
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()  
        cursor = conn.cursor()
        
        # Exact match query - match name exactly (case insensitive)
        cursor.execute(f"""
            SELECT {OBJECT_COMPAT_COLS}
            FROM transient.objects o
            WHERE o.name ILIKE %s
        """, (object_name,))
        
        result = cursor.fetchone()
        matching_obj = None
        
        if result:
            columns = [desc[0] for desc in cursor.description]
            matching_obj = dict(zip(columns, result))
        
        conn.close()
        
        # If no exact match, fall back to fuzzy search
        if not matching_obj:
            results = search_tns_objects(search_term=object_name, limit=50)
            
            # Find exact match
            for obj in results:
                name_only = obj.get('name', '').strip()
                
                # Strategy 1: Direct match on name only
                if name_only.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 2: Extract year and letters using regex with end anchor
                match = re.search(r'(\d{4})([a-zA-Z]+)$', name_only)
                if match and match.group(1) == str(year) and match.group(2).lower() == letters.lower():
                    matching_obj = obj
                    break
        
        if not matching_obj:
            return jsonify({'success': False, 'error': 'Object not found'}), 404
        
        return jsonify({
            'success': True,
            'object': matching_obj
        })
        
    except Exception as e:
        marshal_bp.logger.error(f"Error fetching TNS object {year}{letters}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/status', methods=['POST'])
def api_update_object_status_tns_format(year, letters):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status or new_status not in ['object', 'followup', 'finished', 'snoozed']:
            return jsonify({'error': 'Invalid status'}), 400
        
        object_name = f"{year}{letters}"
        
        # Find the actual object in database
        results = search_tns_objects(search_term=object_name, limit=10)
        matching_obj = None
        
        for obj in results:
            full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
            match = re.search(r'(\d{4})([a-zA-Z]+)', full_name)
            if match and match.group(1) == str(year) and match.group(2).lower() == letters.lower():
                matching_obj = obj
                break
        
        if not matching_obj:
            return jsonify({'error': 'Object not found'}), 404
        
        # Update object status using full name
        full_object_name = (matching_obj.get('name_prefix', '') + matching_obj.get('name', '')).strip()
        
        if update_object_status(full_object_name, new_status):
            return jsonify({
                'success': True,
                'message': f'Status updated to {new_status}'
            })
        else:
            return jsonify({'error': 'Failed to update status'}), 500
        
    except Exception as e:
        marshal_bp.logger.error(f"Error updating status for {year}{letters}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@objects_bp.route('/api/object/<object_name>')
def get_object_api(object_name):
    """API endpoint to get object data by name"""
    try:
        object_name = urllib.parse.unquote(object_name)
        
        # Update absolute magnitude and brightest mag before fetching
        update_object_abs_mag(object_name)
        
        # First try exact match
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        # Get exact match using SQL - try multiple queries
        exact_queries = [
            # Full name match (prefix + name)
            f"""SELECT {OBJECT_COMPAT_COLS}
            FROM transient.objects o
            WHERE (COALESCE(o.name_prefix, '') || COALESCE(o.name, '')) ILIKE %s""",
            # Name only match (exact)
            f"""SELECT {OBJECT_COMPAT_COLS}
            FROM transient.objects o
            WHERE o.name ILIKE %s"""
        ]
        
        exact_result = None
        for query in exact_queries:
            cursor.execute(query, (object_name,))
            exact_result = cursor.fetchone()
            if exact_result:
                break
        
        conn.close()
        
        if exact_result:
            columns = [desc[0] for desc in cursor.description]
            obj = dict(zip(columns, exact_result))
        else:
            # Fallback to search function with more results
            results = search_tns_objects(search_term=object_name, limit=50)
            
            # Find exact match in results
            obj = None
            for result in results:
                full_name = (result.get('name_prefix', '') + result.get('name', '')).strip()
                name_only = result.get('name', '').strip()
                
                if (full_name.lower() == object_name.lower() or 
                    name_only.lower() == object_name.lower()):
                    obj = result
                    break
            
            if not obj:
                return jsonify({'error': 'Object not found'}), 404
        
        full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
        if not full_name and obj.get('name'):
            full_name = obj.get('name')
        
        return jsonify({
            'success': True,
            'object': obj,
            'full_name': full_name
        })
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@objects_bp.route('/api/object/<object_name>/edit', methods=['POST'])
def api_edit_object(object_name):
    """Edit object data"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied - Admin privileges required'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request body'}), 400

        obj_id = data.get('objid')

        conn = get_tns_db_connection()
        cursor = conn.cursor()

        # If no objid, resolve from URL param (object_name)
        if not obj_id:
            cursor.execute(
                "SELECT obj_id FROM transient.objects WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
                (urllib.parse.unquote(object_name), urllib.parse.unquote(object_name))
            )
            row = cursor.fetchone()
            if row:
                obj_id = row[0]

        if not obj_id:
            conn.close()
            return jsonify({'error': 'Object ID (objid) is required and could not be resolved'}), 400

        updates = {}

        # redshift
        if 'redshift' in data:
            v = data['redshift']
            if v is not None and v != '':
                try:
                    v = float(v)
                    if v < 0:
                        conn.close()
                        return jsonify({'error': 'Redshift must be positive'}), 400
                except (ValueError, TypeError):
                    conn.close()
                    return jsonify({'error': 'Invalid redshift value'}), 400
            else:
                v = None
            updates['redshift'] = v

        # internal_name (new schema column name)
        if 'internal_names' in data:
            v = data['internal_names']
            updates['internal_name'] = v.strip() if isinstance(v, str) and v.strip() else None

        # tag (array in new schema — convert from comma-separated string)
        if 'tags' in data:
            v = data['tags']
            if isinstance(v, str) and v.strip():
                # Allow only alphanumeric, comma, space, hyphen, underscore
                import re as _re
                if not _re.match(r'^[A-Za-z0-9,\s\-_]+$', v.strip()):
                    conn.close()
                    return jsonify({'error': 'Tags contain invalid characters'}), 400
                updates['tag'] = [t.strip() for t in v.split(',') if t.strip()]
            else:
                # Keep NOT NULL contract on transient.objects.tag when clearing tags.
                updates['tag'] = []

        if not updates:
            conn.close()
            return jsonify({'error': 'No valid fields to update'}), 400

        set_clauses = [f"{k} = %s" for k in updates.keys()]
        params = list(updates.values()) + [int(obj_id)]

        cursor.execute(
            f"UPDATE transient.objects SET {', '.join(set_clauses)} WHERE obj_id = %s",
            params
        )
        rows_affected = cursor.rowcount

        if rows_affected == 0:
            conn.rollback()
            conn.close()
            return jsonify({'error': 'Object not found'}), 404

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Object updated successfully',
            'updated_fields': list(updates.keys())
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@objects_bp.route('/api/object/<object_name>/delete', methods=['DELETE'])
def api_delete_object(object_name):
    """Delete object from database"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied - Admin privileges required'}), 403
    
    try:
        object_name = urllib.parse.unquote(object_name)
        
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        # First check if object exists
        cursor.execute("""
            SELECT name_prefix, name, type
            FROM transient.objects
            WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
               OR name = %s
        """, (object_name, object_name))
        
        existing_object = cursor.fetchone()
        if not existing_object:
            conn.close()
            return jsonify({'error': 'Object not found'}), 404
        
        # Delete from transient.objects (CASCADE will handle related rows if FK set up)
        cursor.execute("""
            DELETE FROM transient.objects
            WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
               OR name = %s
        """, (object_name, object_name))
        
        rows_affected = cursor.rowcount
        
        if rows_affected == 0:
            conn.close()
            return jsonify({'error': 'Failed to delete object'}), 500
        
        # Clean up related data explicitly
        try:
            obj_name = existing_object[1] or object_name
            cursor.execute(
                "DELETE FROM transient.photometry WHERE obj_id IN "
                "(SELECT obj_id FROM transient.objects WHERE name = %s)",
                (obj_name,)
            )
            cursor.execute(
                "DELETE FROM transient.spectroscopy WHERE obj_id IN "
                "(SELECT obj_id FROM transient.objects WHERE name = %s)",
                (obj_name,)
            )
            cursor.execute(
                "DELETE FROM transient.comments WHERE obj_id IN "
                "(SELECT obj_id FROM transient.objects WHERE name = %s)",
                (obj_name,)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Object {object_name} deleted successfully',
            'object_name': object_name
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@objects_bp.route('/api/object/<object_name>/status', methods=['POST'])
def api_update_object_status_generic(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status or new_status not in ['object', 'followup', 'finished', 'snoozed', 'clear']:
            return jsonify({'error': 'Invalid status'}), 400
        
        object_name = urllib.parse.unquote(object_name)
        
        if update_object_status(object_name, new_status):
            return jsonify({
                'success': True,
                'message': f'Status updated to {new_status}'
            })
        else:
            return jsonify({'error': 'Failed to update status in database'}), 500
        
    except Exception as e:
        marshal_bp.logger.error(f"Error updating status for {object_name}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ===============================================================================
# OBJECT DATA API
# ===============================================================================
def sanitize_for_json(data):
    """Convert NaN and Inf values to None for JSON serialization"""
    import math
    if isinstance(data, list):
        return [sanitize_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {key: sanitize_for_json(value) for key, value in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    return data

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry')
def get_object_photometry(year, letters):
    object_name = f"{year}{letters}"
    user = session.get('user', {})
    user_email = user.get('email') if user else None
    is_admin = user.get('is_admin', False) if user else False

    try:
        TNSObjectDB.sync_last_photometry_date(object_name)
        photometry = TNSObjectDB.get_photometry(object_name)
        photometry = sanitize_for_json(photometry)
        photometry = filter_by_source_permissions(
            object_name, 'phot', photometry,
            user_email=user_email, is_admin=is_admin
        )
        return jsonify({'success': True, 'photometry': photometry, 'count': len(photometry)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy')
def get_object_spectroscopy(year, letters):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    object_name = f"{year}{letters}"
    
    try:
        spectra_list = TNSObjectDB.get_spectrum_list(object_name)
        return jsonify({
            'success': True,
            'spectra': spectra_list,
            'count': len(spectra_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/<spectrum_id>')
def get_spectrum_data(year, letters, spectrum_id):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    object_name = f"{year}{letters}"
    
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT s.wavelength, s.intensity
            FROM transient.spectroscopy s
            JOIN transient.objects o ON s.obj_id = o.obj_id
            WHERE o.name ILIKE %s AND s.source = %s
            ORDER BY s.wavelength ASC
        ''', (object_name, spectrum_id))
        
        results = cursor.fetchall()
        conn.close()
        
        wavelengths = [row[0] for row in results]
        intensities = [row[1] for row in results]
        
        return jsonify({
            'success': True,
            'wavelength': wavelengths,
            'intensity': intensities,
            'spectrum_id': spectrum_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry', methods=['POST'])
def upload_photometry(year, letters):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    object_name = f"{year}{letters}"
    data = request.get_json()
    
    try:
        point_id = TNSObjectDB.add_photometry_point(
            object_name=object_name,
            mjd=float(data.get('mjd')),
            magnitude=float(data.get('magnitude')) if data.get('magnitude') else None,
            magnitude_error=float(data.get('magnitude_error')) if data.get('magnitude_error') else None,
            filter_name=data.get('filter'),
            telescope=data.get('telescope')
        )
        
        return jsonify({
            'success': True,
            'message': 'Photometry point added successfully',
            'id': point_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/batch', methods=['POST'])
def upload_photometry_batch(year, letters):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = f"{year}{letters}"
    data = request.get_json()
    points = data.get('points', [])
    if not points:
        return jsonify({'error': 'No points provided'}), 400
    try:
        inserted = TNSObjectDB.add_photometry_batch(object_name, points)
        return jsonify({'success': True, 'inserted': inserted, 'total': len(points)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<string:object_name>/spectroscopy', methods=['POST'])
def upload_spectroscopy_generic(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
        
    data = request.get_json()
    
    try:
        spectrum_id = TNSObjectDB.add_spectrum_data(
            object_name=object_name,
            wavelength_data=data.get('wavelength', []),
            intensity_data=data.get('intensity', []),
            phase=float(data.get('phase')) if data.get('phase') else None,
            telescope=data.get('telescope'),
            spectrum_id=data.get('spectrum_id')
        )
        
        return jsonify({
            'success': True,
            'message': 'Spectrum data added successfully',
            'spectrum_id': spectrum_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy', methods=['POST'])
def upload_spectroscopy(year, letters):
    object_name = f"{year}{letters}"
    return upload_spectroscopy_generic(object_name)

@objects_bp.route('/api/photometry/<int:point_id>', methods=['DELETE'])
def delete_photometry_point(point_id):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        if TNSObjectDB.delete_photometry_point(point_id):
            return jsonify({
                'success': True,
                'message': 'Photometry point deleted successfully'
            })
        else:
            return jsonify({'error': 'Photometry point not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/spectrum/<spectrum_id>', methods=['DELETE'])
def delete_spectrum(spectrum_id):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        if TNSObjectDB.delete_spectrum(spectrum_id):
            return jsonify({
                'success': True,
                'message': 'Spectrum deleted successfully'
            })
        else:
            return jsonify({'error': 'Spectrum not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/download')
def download_photometry(year, letters):
    """Download photometry as .dat file with optional filters."""
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403

    object_name = f"{year}{letters}"

    telescopes_param = request.args.get('telescopes', '')
    filters_param    = request.args.get('filters', '')
    mjd_min          = request.args.get('mjd_min', type=float)
    mjd_max          = request.args.get('mjd_max', type=float)
    include_nondet   = request.args.get('include_nondet', 'true').lower() != 'false'

    sel_telescopes = {t.strip() for t in telescopes_param.split(',') if t.strip()}
    sel_filters    = {f.strip() for f in filters_param.split(',') if f.strip()}

    try:
        phot = TNSObjectDB.get_photometry(object_name)

        rows = []
        for p in phot:
            if sel_telescopes and (p.get('telescope') or '') not in sel_telescopes:
                continue
            if sel_filters and (p.get('filter') or '') not in sel_filters:
                continue
            if mjd_min is not None and p.get('mjd', 0) < mjd_min:
                continue
            if mjd_max is not None and p.get('mjd', 0) > mjd_max:
                continue
            is_upper = p.get('magnitude_error') is None
            if not include_nondet and is_upper:
                continue
            rows.append(p)

        lines = [
            f"# {object_name} photometry",
            "# MJD magnitude error filter telescope",
        ]
        for p in rows:
            mjd  = p.get('mjd', '')
            mag  = p.get('magnitude')
            err  = p.get('magnitude_error')
            flt  = p.get('filter') or ''
            tel  = p.get('telescope') or 'Unknown'
            is_upper = err is None
            if is_upper:
                mag_str = f">{mag:.6f}" if mag is not None else ">nan"
                err_str = "nan"
            else:
                mag_str = f"{mag:.6f}" if mag is not None else "nan"
                err_str = f"{err:.6f}"
            lines.append(f"{mjd:.6f}  {mag_str}  {err_str}  {flt}  {tel}")

        content = '\n'.join(lines) + '\n'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{object_name}_phot.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/spectrum/<path:spectrum_id>/download')
def download_spectrum_file(spectrum_id):
    """Download a single spectrum as .dat file."""
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403

    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT o.name AS object_name, s.wavelength, s.intensity, s.source AS telescope, s."MJD" AS phase
            FROM transient.spectroscopy s
            JOIN transient.objects o ON s.obj_id = o.obj_id
            WHERE s.source = %s
            ORDER BY s.wavelength ASC
        ''', (spectrum_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({'error': 'Spectrum not found'}), 404

        obj   = rows[0][0]
        tel   = rows[0][3] or 'Unknown'
        phase = rows[0][4]

        lines = [
            f"# {obj} spectrum  id={spectrum_id}",
            f"# Telescope: {tel}",
        ]
        if phase is not None:
            lines.append(f"# Phase: {phase}")
        lines.append("# wavelength intensity")
        for _, wl, intens, _, _ in rows:
            lines.append(f"{wl:.4f}  {intens:.8g}")

        content = '\n'.join(lines) + '\n'
        safe_id = re.sub(r'[^\w\-]', '_', spectrum_id)
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{obj}_spec_{safe_id}.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<int:year><alpha:letters>/photometry/plot')
def get_object_photometry_plot(year, letters):
    object_name = f"{year}{letters}"

    user = session.get('user')
    user_email = user.get('email', '') if user else None
    is_admin = user.get('is_admin', False) if user else False

    if user and not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})

    try:
        # Get object data for redshift, ra, and dec
        results = search_tns_objects(search_term=object_name, limit=1)
        obj_data = results[0] if results else {}
        redshift = obj_data.get('redshift')
        ra = obj_data.get('ra')
        dec = obj_data.get('declination')

        photometry_data = TNSObjectDB.get_photometry(object_name)

        if not photometry_data:
            return jsonify({'success': True, 'plot_html': None, 'message': 'No photometry data available'})

        # Filter by source permissions — public points visible to everyone
        photometry_data = filter_by_source_permissions(
            object_name, 'phot', photometry_data,
            user_email=user_email, is_admin=is_admin
        )

        if not photometry_data:
            return jsonify({'success': True, 'plot_json': None,
                            'message': 'Login to view photometry', 'data_count': 0})

        apply_extinction = request.args.get('extinction', 'true').lower() == 'true'
        apply_k_corr = request.args.get('k_corr', 'true').lower() == 'true'

        plot_json = DataVisualization.create_photometry_plot_from_db(
            photometry_data,
            redshift=redshift,
            ra=ra,
            dec=dec,
            apply_extinction=apply_extinction,
            apply_k_corr=apply_k_corr,
            as_json=True
        )

        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(photometry_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/plot')
def get_object_spectrum_plot(year, letters):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    object_name = f"{year}{letters}"
    
    # Check permissions
    user_email = session['user'].get('email', '')
    if not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})
        
    spectrum_id = request.args.get('spectrum_id')
    
    try:
        spectrum_data = TNSObjectDB.get_spectroscopy(object_name)
        
        if not spectrum_data:
            return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'No spectrum data available'
            })
        
        if spectrum_id:
            # Show specific spectrum
            plot_html = DataVisualization.create_spectrum_plot_from_db(spectrum_data, spectrum_id)
        else:
            # Show all spectra overview
            plot_html = DataVisualization.create_spectrum_list_plot_from_db(spectrum_data)
        
        return jsonify({
            'success': True,
            'plot_html': plot_html,
            'data_count': len(spectrum_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/photometry')
def get_object_photometry_generic(object_name):
    object_name = urllib.parse.unquote(object_name)
    user = session.get('user', {})
    user_email = user.get('email') if user else None
    is_admin = user.get('is_admin', False) if user else False
    try:
        TNSObjectDB.sync_last_photometry_date(object_name)
        photometry = TNSObjectDB.get_photometry(object_name)
        photometry = sanitize_for_json(photometry)
        photometry = filter_by_source_permissions(
            object_name, 'phot', photometry,
            user_email=user_email, is_admin=is_admin
        )
        return jsonify({'success': True, 'photometry': photometry, 'count': len(photometry)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/photometry', methods=['POST'])
def upload_photometry_generic(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    try:
        point_id = TNSObjectDB.add_photometry_point(
            object_name=object_name,
            mjd=float(data.get('mjd')),
            magnitude=float(data.get('magnitude')) if data.get('magnitude') else None,
            magnitude_error=float(data.get('magnitude_error')) if data.get('magnitude_error') else None,
            filter_name=data.get('filter'),
            telescope=data.get('telescope')
        )
        return jsonify({'success': True, 'message': 'Photometry point added successfully', 'id': point_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/photometry/batch', methods=['POST'])
def upload_photometry_batch_generic(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    points = data.get('points', [])
    if not points:
        return jsonify({'error': 'No points provided'}), 400
    try:
        inserted = TNSObjectDB.add_photometry_batch(object_name, points)
        return jsonify({'success': True, 'inserted': inserted, 'total': len(points)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/photometry/download')
def download_photometry_generic(object_name):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)

    telescopes_param = request.args.get('telescopes', '')
    filters_param    = request.args.get('filters', '')
    mjd_min          = request.args.get('mjd_min', type=float)
    mjd_max          = request.args.get('mjd_max', type=float)
    include_nondet   = request.args.get('include_nondet', 'true').lower() != 'false'

    sel_telescopes = {t.strip() for t in telescopes_param.split(',') if t.strip()}
    sel_filters    = {f.strip() for f in filters_param.split(',') if f.strip()}

    try:
        phot = TNSObjectDB.get_photometry(object_name)
        rows = []
        for p in phot:
            if sel_telescopes and (p.get('telescope') or '') not in sel_telescopes:
                continue
            if sel_filters and (p.get('filter') or '') not in sel_filters:
                continue
            if mjd_min is not None and p.get('mjd', 0) < mjd_min:
                continue
            if mjd_max is not None and p.get('mjd', 0) > mjd_max:
                continue
            if not include_nondet and p.get('magnitude_error') is None:
                continue
            rows.append(p)

        lines = [f"# {object_name} photometry", "# MJD magnitude error filter telescope"]
        for p in rows:
            mjd = p.get('mjd', '')
            mag = p.get('magnitude')
            err = p.get('magnitude_error')
            flt = p.get('filter') or ''
            tel = p.get('telescope') or 'Unknown'
            if err is None:
                mag_str = f">{mag:.6f}" if mag is not None else ">nan"
                err_str = "nan"
            else:
                mag_str = f"{mag:.6f}" if mag is not None else "nan"
                err_str = f"{err:.6f}"
            lines.append(f"{mjd:.6f}  {mag_str}  {err_str}  {flt}  {tel}")

        content = '\n'.join(lines) + '\n'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{object_name}_phot.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/photometry/plot')
def get_object_photometry_plot_generic(object_name):
    object_name = urllib.parse.unquote(object_name)

    user = session.get('user')
    user_email = user.get('email', '') if user else None
    is_admin = user.get('is_admin', False) if user else False

    try:
        if user and not check_object_access(object_name, user_email):
            return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})

        results = search_tns_objects(search_term=object_name, limit=1)

        if not results:
            return jsonify({'success': False, 'error': f'Object {object_name} not found'}), 404

        photometry_data = TNSObjectDB.get_photometry(object_name)

        if not photometry_data:
            return jsonify({'success': True, 'plot_html': None,
                            'message': 'No photometry data available for this object'})

        # Filter by source permissions — public points visible to everyone
        photometry_data = filter_by_source_permissions(
            object_name, 'phot', photometry_data,
            user_email=user_email, is_admin=is_admin
        )

        if not photometry_data:
            return jsonify({'success': True, 'plot_json': None,
                            'message': 'Login to view photometry', 'data_count': 0})

        # Get redshift, ra, dec from object data
        redshift = results[0].get('redshift')
        ra = results[0].get('ra')
        dec = results[0].get('declination')

        apply_extinction = request.args.get('extinction', 'true').lower() == 'true'
        apply_k_corr = request.args.get('k_corr', 'true').lower() == 'true'

        plot_json = DataVisualization.create_photometry_plot_from_db(
            photometry_data,
            redshift=redshift,
            ra=ra,
            dec=dec,
            apply_extinction=apply_extinction,
            apply_k_corr=apply_k_corr,
            as_json=True
        )

        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(photometry_data)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/spectrum/plot')
def get_object_spectrum_plot_generic(object_name):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    object_name = urllib.parse.unquote(object_name)
    
    # Check permissions
    user_email = session['user'].get('email', '')
    if not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})
        
    spectrum_id = request.args.get('spectrum_id')
    
    try:
        results = search_tns_objects(search_term=object_name, limit=1)
        
        if not results:
            return jsonify({
                'success': False,
                'error': f'Object {object_name} not found'
            }), 404
        
        spectrum_data = TNSObjectDB.get_spectroscopy(object_name)
        
        if not spectrum_data:
            return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'No spectrum data available for this object'
            })
        
        if spectrum_id:
            # Show specific spectrum
            plot_html = DataVisualization.create_spectrum_plot_from_db(spectrum_data, spectrum_id)
        else:
            # Show all spectra overview
            plot_html = DataVisualization.create_spectrum_list_plot_from_db(spectrum_data)
        
        return jsonify({
            'success': True,
            'plot_html': plot_html,
            'data_count': len(spectrum_data)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ===============================================================================
# COMMENTS
# ===============================================================================
@objects_bp.route('/api/object/<object_name>/comments')
def get_object_comments(object_name):
    if 'user' not in session:
        return jsonify({'success': True, 'comments': [], 'count': 0})
    
    try:
        object_name = urllib.parse.unquote(object_name)
        
        # Check permissions
        user_email = session['user'].get('email', '')
        if not check_object_access(object_name, user_email):
            return jsonify({
                'success': True,
                'comments': [],
                'count': 0,
                'message': 'Access denied'
            })
        
        # Use PostgreSQL database for comments
        comments = TNSObjectDB.get_comments(object_name)
        
        return jsonify({
            'success': True,
            'comments': comments,
            'count': len(comments)
        })
    except Exception as e:
        marshal_bp.logger.error(f"Error getting comments for {object_name}: {str(e)}")
        return jsonify({'error': 'Failed to get comments'}), 500

@objects_bp.route('/api/object/<object_name>/comments', methods=['POST'])
def add_object_comment(object_name):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({'error': 'Comment content is required'}), 400
        
        if len(content) > 1000:
            return jsonify({'error': 'Comment is too long (maximum 1000 characters)'}), 400
        
        user = session['user']
        # Use PostgreSQL database for comments
        comment_id = TNSObjectDB.add_comment(
            object_name=object_name,
            user_email=user['email'],
            user_name=user['name'],
            user_picture=user.get('picture', ''),
            content=content
        )
        
        return jsonify({
            'success': True,
            'message': 'Comment added successfully',
            'comment_id': comment_id
        })
        
    except Exception as e:
        marshal_bp.logger.error(f"Error adding comment for {object_name}: {str(e)}")
        return jsonify({'error': 'Failed to add comment'}), 500

@objects_bp.route('/api/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(comment_id):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Check if comment exists using PostgreSQL
        comment = TNSObjectDB.get_comment_by_id(comment_id)
        if not comment:
            return jsonify({'error': 'Comment not found'}), 404
        
        if TNSObjectDB.delete_comment(comment_id):
            return jsonify({
                'success': True,
                'message': 'Comment deleted successfully'
            })
        else:
            return jsonify({'error': 'Failed to delete comment'}), 500
    except Exception as e:
        marshal_bp.logger.error(f"Error deleting comment {comment_id}: {str(e)}")
        return jsonify({'error': 'Failed to delete comment'}), 500

@objects_bp.route('/api/comments/<int:comment_id>', methods=['PUT', 'PATCH'])
def update_comment(comment_id):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
        
    try:
        # Check if comment exists
        comment = TNSObjectDB.get_comment_by_id(comment_id)
        if not comment:
            return jsonify({'error': 'Comment not found'}), 404
            
        # Only admin or the comment author can edit
        if not session['user'].get('is_admin') and session['user'].get('email') != comment['user_email']:
            return jsonify({'error': 'Access denied: You can only edit your own comments'}), 403
            
        data = request.get_json()
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({'error': 'Comment content is required'}), 400
            
        if len(content) > 1000:
            return jsonify({'error': 'Comment is too long (maximum 1000 characters)'}), 400
            
        if TNSObjectDB.update_comment(comment_id, content):
            return jsonify({
                'success': True,
                'message': 'Comment updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to update comment'}), 500
    except Exception as e:
        marshal_bp.logger.error(f"Error updating comment {comment_id}: {str(e)}")
        return jsonify({'error': 'Failed to update comment'}), 500

# ===============================================================================
# SOURCE PERMISSIONS (per telescope/instrument access control)
# ===============================================================================
@objects_bp.route('/api/object/<object_name>/sources')
def get_object_sources(object_name):
    """Return unique phot/spec sources (telescopes) for an object."""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT COALESCE(p.telescope, 'Unknown') as src "
            "FROM transient.photometry p "
            "JOIN transient.objects o ON p.obj_id = o.obj_id "
            "WHERE o.name ILIKE %s ORDER BY src",
            (object_name,)
        )
        phot_sources = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT DISTINCT COALESCE(s.source, 'Unknown') as src "
            "FROM transient.spectroscopy s "
            "JOIN transient.objects o ON s.obj_id = o.obj_id "
            "WHERE o.name ILIKE %s ORDER BY src",
            (object_name,)
        )
        spec_sources = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'phot_sources': phot_sources, 'spec_sources': spec_sources})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/source-permissions')
def get_source_permissions_api(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    try:
        perms = get_source_permissions(object_name)
        return jsonify({'success': True, 'permissions': perms})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@objects_bp.route('/api/object/<object_name>/source-permissions/batch', methods=['POST'])
def set_source_permissions_batch_api(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    if not data or 'permissions' not in data:
        return jsonify({'error': 'Missing permissions list'}), 400
    try:
        set_source_permissions_batch(object_name, data['permissions'])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===============================================================================
# PERMISSIONS
# ===============================================================================
@objects_bp.route('/api/groups')
def get_groups_api():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        groups = get_all_groups()
        return jsonify({
            'success': True,
            'groups': groups
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions')
def get_object_permissions_api(object_name):
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        object_name = urllib.parse.unquote(object_name)
        permissions = get_object_permissions(object_name)
        return jsonify({
            'success': True,
            'permissions': permissions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions', methods=['POST'])
def add_object_permission_api(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if grant_object_permission(object_name, group_name, session['user']['email']):
            return jsonify({
                'success': True,
                'message': 'Permission granted successfully'
            })
        else:
            return jsonify({'error': 'Failed to grant permission (maybe already exists)'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions', methods=['DELETE'])
def remove_object_permission_api(object_name):
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if revoke_object_permission(object_name, group_name):
            return jsonify({
                'success': True,
                'message': 'Permission revoked successfully'
            })
        else:
            return jsonify({'error': 'Permission not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
    except Exception as e:
        marshal_bp.logger.error(f"Error deleting comment {comment_id}: {str(e)}")
        return jsonify({'error': 'Failed to delete comment'}), 500


# ============================================================
# NED Cone Search Proxy
# ============================================================
def _get_current_ned_host_name(target_name: str) -> str | None:
    """Return current NED host name for target, or None if not set."""
    if not target_name:
        return None
    try:
        conn = get_tns_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT obj_id FROM transient.objects "
            "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
            (target_name, target_name)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return None

        obj_id = row[0]
        cur.execute(
            "SELECT name FROM transient.cross_matches "
            "WHERE obj_id = %s AND catalog = 'NED' AND is_host = TRUE "
            "ORDER BY updated_date DESC NULLS LAST, match_id DESC LIMIT 1",
            (obj_id,)
        )
        h = cur.fetchone()
        conn.close()
        return h[0] if h and h[0] else None
    except Exception as e:
        logger.warning("[NED] read current host failed for %s: %s", target_name, e)
        return None


@objects_bp.route('/api/ned/cone')
def ned_cone_search():
    """Proxy NED cone search to avoid CORS.
    Query params: ra, dec, radius_arcsec (default 60), object_name, force (0/1)
    """
    try:
        ra     = float(request.args.get('ra', 0))
        dec    = float(request.args.get('dec', 0))
        radius = float(request.args.get('radius_arcsec', 60))
        object_name = request.args.get('object_name', '').strip()
        force       = request.args.get('force', '0').strip() not in ('0', 'false', '')
        current_host = _get_current_ned_host_name(object_name) if object_name else None

        logger.info(
            "[NED] cone search start ra=%.6f dec=%.6f radius_arcsec=%.1f",
            ra, dec, radius
        )

        # --- Try DB cache first (unless force=true) ---
        if not force and object_name:
            cached = get_ned_cache(object_name, radius)
            if cached is not None:
                logger.info("[NED] cache hit for %s r=%.1f count=%d",
                            object_name, radius, cached['result_count'])
                return jsonify({
                    'success': True,
                    'count': cached['result_count'],
                    'results': cached['results'],
                    'from_cache': True,
                    'searched_at': cached.get('searched_at'),
                    'current_host': current_host,
                })

        radius_arcmin = radius / 60.0
        url = (
            "https://ned.ipac.caltech.edu/cgi-bin/objsearch"
            f"?lon={ra}d&lat={dec}d"
            f"&radius={radius_arcmin:.4f}"
            "&search_type=Near+Position+Search"
            "&in_csys=Equatorial&in_equinox=J2000.0"
            "&out_csys=Equatorial&out_equinox=J2000.0"
            "&obj_sort=Distance+to+search+center"
            "&of=ascii_bar&zv_breaker=30000.0&list_limit=500&img_stamp=NO"
            "&z_constraint=Unconstrained&nmp_op=ANY"
        )
        resp = _requests.get(url, timeout=60, headers={'User-Agent': 'KinderWeb/1.0'})
        logger.info("[NED] upstream status=%s", resp.status_code)
        resp.raise_for_status()

        def _norm(s):
            return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

        def _first_float(s):
            if s is None:
                return None
            m = re.search(r'[-+]?\d+(?:\.\d+)?', str(s))
            return float(m.group(0)) if m else None

        def _parse_ra_deg(s):
            if s is None:
                return None
            raw = str(s).strip()
            if not raw:
                return None
            v = _first_float(raw)
            # Decimal degrees from NED are usually in [0, 360].
            if v is not None and 0.0 <= v <= 360.0 and len(raw.split()) == 1 and ':' not in raw:
                return v
            toks = [t for t in re.split(r'[:\s]+', raw) if t]
            if len(toks) >= 3:
                try:
                    h = float(toks[0]); m = float(toks[1]); sec = float(toks[2])
                    return (h + m / 60.0 + sec / 3600.0) * 15.0
                except ValueError:
                    return None
            return v

        def _parse_dec_deg(s):
            if s is None:
                return None
            raw = str(s).strip()
            if not raw:
                return None
            v = _first_float(raw)
            if v is not None and -90.0 <= v <= 90.0 and len(raw.split()) == 1 and ':' not in raw:
                return v
            toks = [t for t in re.split(r'[:\s]+', raw.replace('+', ' +').replace('-', ' -')) if t]
            if len(toks) >= 3:
                try:
                    d = float(toks[0]); m = float(toks[1]); sec = float(toks[2])
                    sign = -1.0 if d < 0 else 1.0
                    return sign * (abs(d) + m / 60.0 + sec / 3600.0)
                except ValueError:
                    return None
            return v

        lines = [ln.rstrip('\n') for ln in resp.text.splitlines()]
        header = None
        for ln in lines:
            if '|' not in ln:
                continue
            cols = [c.strip() for c in ln.split('|')]
            keyline = ' '.join(cols).lower()
            if ('object' in keyline and 'name' in keyline and 'ra' in keyline and 'dec' in keyline):
                header = cols
                break

        # Fallback to legacy index if header cannot be detected
        if not header:
            header = ['No.', 'Object Name', 'RA', 'DEC', 'Type', 'Velocity', 'Redshift', 'z flag', 'Magnitude']

        idx = {}
        for i, col in enumerate(header):
            n = _norm(col)
            if n in ('no', 'number', 'sep', 'separation') and 'distance' not in idx:
                idx['distance'] = i
            if ('object' in n and 'name' in n) or n in ('objname', 'name'):
                idx['objname'] = i
            if n.startswith('ra') and 'ra' not in idx:
                idx['ra'] = i
            if n.startswith('dec') and 'dec' not in idx:
                idx['dec'] = i
            if n in ('type', 'objtype', 'objecttype') and 'type' not in idx:
                idx['type'] = i
            if ('redshift' in n and 'flag' not in n) or n in ('z',):
                if 'redshift' not in idx:
                    idx['redshift'] = i
            if ('redshift' in n and 'flag' in n) or n in ('zflag', 'redshiftflag'):
                idx['redshift_type'] = i

        def _get(cols, key):
            i = idx.get(key)
            if i is None or i >= len(cols):
                return ''
            return cols[i].strip()

        results = []
        for ln in lines:
            line = ln.strip()
            if not line or '|' not in line:
                continue
            if line.startswith('#'):
                continue
            cols = [c.strip() for c in ln.split('|')]
            joined = ' '.join(cols).lower()
            if 'object name' in joined and 'ra' in joined and 'dec' in joined:
                continue
            if all((not c or set(c) <= set('-=')) for c in cols):
                continue

            objname = _get(cols, 'objname')
            if not objname:
                continue

            ra_val = _parse_ra_deg(_get(cols, 'ra'))
            dec_val = _parse_dec_deg(_get(cols, 'dec'))
            if ra_val is None or dec_val is None:
                continue

            obj = {
                'objname': objname,
                'ra': ra_val,
                'dec': dec_val,
                'type': _get(cols, 'type') or '',
                'redshift': _first_float(_get(cols, 'redshift')),
                'redshift_type': _get(cols, 'redshift_type') or '',
                'distance_arcmin': _first_float(_get(cols, 'distance')),
            }
            results.append(obj)

        sample = [
            {
                'name': r.get('objname', ''),
                'ra': r.get('ra'),
                'dec': r.get('dec'),
                'z': r.get('redshift'),
                'z_flag': r.get('redshift_type', ''),
            }
            for r in results[:3]
        ]
        logger.info(
            "[NED] parsed count=%d sample=%s",
            len(results),
            sample
        )

        # --- Write to DB cache ---
        if object_name:
            try:
                upsert_ned_cache(object_name, ra, dec, radius, results)
                logger.info("[NED] cached %d results for %s r=%.1f",
                            len(results), object_name, radius)
            except Exception as _ce:
                logger.warning("[NED] cache write failed: %s", _ce)

        return jsonify({'success': True, 'count': len(results), 'results': results,
                'from_cache': False, 'current_host': current_host})

    except _requests.Timeout as e:
        logger.warning("[NED] upstream timed out: %s", e)
        return jsonify({'success': False, 'error': f'NED request timed out: {e}'}), 502
    except _requests.RequestException as e:
        logger.error("[NED] upstream request failed: %s", e)
        return jsonify({'success': False, 'error': f'NED request failed: {e}'}), 502
    except Exception as e:
        logger.exception("[NED] cone search error")
        return jsonify({'success': False, 'error': str(e)}), 500


@objects_bp.route('/api/ned/set_host', methods=['POST'])
def ned_set_host():
    """Set selected NED object as host and conditionally update transient redshift.

    Redshift update rule:
    - only update transient.objects.redshift if z flag starts with uppercase 'S'.
    """
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        target_name = str(data.get('target_name') or '').strip()
        host_name = str(data.get('host_name') or '').strip()
        host_type = str(data.get('type') or '').strip()
        z_flag = str(data.get('redshift_type') or '').strip()
        redshift_raw = data.get('redshift')
        distance_arcmin_raw = data.get('distance_arcmin')

        if not target_name or not host_name:
            return jsonify({'success': False, 'error': 'Missing target_name or host_name'}), 400

        redshift_val = None
        if redshift_raw not in (None, ''):
            try:
                redshift_val = float(redshift_raw)
            except (ValueError, TypeError):
                redshift_val = None

        separation_arcsec = None
        if distance_arcmin_raw not in (None, ''):
            try:
                separation_arcsec = float(distance_arcmin_raw) * 60.0
            except (ValueError, TypeError):
                separation_arcsec = None

        should_update_redshift = (z_flag.startswith('S') and redshift_val is not None)

        conn = get_tns_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT obj_id FROM transient.objects "
            "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
            (target_name, target_name)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'error': f'Object not found: {target_name}'}), 404

        obj_id = row[0]

        # Reset previous host flags for this object.
        cur.execute(
            "UPDATE transient.cross_matches SET is_host = FALSE WHERE obj_id = %s",
            (obj_id,)
        )

        note = f"NED host set manually; type={host_type or '-'}; z_flag={z_flag or '-'}"
        cur.execute(
            """
            UPDATE transient.cross_matches
               SET is_host = TRUE,
                   separation = %s,
                   redshift = %s,
                   updated_date = NOW(),
                   note = %s,
                   status = 'Manual-NED',
                   error_message = NULL
             WHERE obj_id = %s AND catalog = 'NED' AND name = %s
            """,
            (separation_arcsec, redshift_val, note, obj_id, host_name)
        )

        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO transient.cross_matches
                    (obj_id, name, catalog, separation, redshift, is_host,
                     updated_date, note, status, run_date, error_message)
                VALUES
                    (%s, %s, 'NED', %s, %s, TRUE,
                     NOW(), %s, 'Manual-NED', NOW(), NULL)
                """,
                (obj_id, host_name, separation_arcsec, redshift_val, note)
            )

        updated_redshift = False
        if should_update_redshift:
            cur.execute(
                "UPDATE transient.objects SET redshift = %s WHERE obj_id = %s",
                (redshift_val, obj_id)
            )
            updated_redshift = True

        conn.commit()
        conn.close()

        logger.info(
            "[NED] set_host target=%s host=%s z=%.6f z_flag=%s updated_redshift=%s",
            target_name, host_name,
            redshift_val if redshift_val is not None else float('nan'),
            z_flag or '-',
            updated_redshift
        )

        return jsonify({
            'success': True,
            'updated_redshift': updated_redshift,
            'redshift': redshift_val if updated_redshift else None,
            'host_name': host_name,
            'z_flag': z_flag,
        })

    except Exception as e:
        logger.exception("[NED] set_host error")
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500


@objects_bp.route('/api/ned/unset_host', methods=['POST'])
def ned_unset_host():
    """Unset NED host flag for target object."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    conn = None
    try:
        data = request.get_json(silent=True) or {}
        target_name = str(data.get('target_name') or '').strip()
        if not target_name:
            return jsonify({'success': False, 'error': 'Missing target_name'}), 400

        conn = get_tns_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT obj_id FROM transient.objects "
            "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
            (target_name, target_name)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            conn = None
            return jsonify({'success': False, 'error': f'Object not found: {target_name}'}), 404

        obj_id = row[0]
        cur.execute(
            "UPDATE transient.cross_matches SET is_host = FALSE, updated_date = NOW() "
            "WHERE obj_id = %s AND catalog = 'NED' AND is_host = TRUE",
            (obj_id,)
        )
        cleared = cur.rowcount
        conn.commit()
        conn.close()
        conn = None

        logger.info("[NED] unset_host target=%s cleared_rows=%d", target_name, cleared)
        return jsonify({'success': True, 'cleared': cleared})
    except Exception as e:
        logger.exception("[NED] unset_host error")
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
