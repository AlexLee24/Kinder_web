"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — api (split from object_routes.py)."""
import re
import urllib.parse
from flask import session, request, jsonify
from app.db.transient import (
    search_tns_objects,
    update_object_status,
    update_object_abs_mag,
)
from app.db import get_tns_db_connection, OBJECT_COMPAT_COLS
import logging
from app.core.auth import admin_required
from app.db.auth import check_object_access

logger = logging.getLogger(__name__)
from . import objects_bp


def _can_read_object(obj) -> bool:
    """Object-level permission check for the session user (anonymous included)."""
    user = session.get('user') or {}
    return check_object_access((obj.get('name') or '').strip(), user.get('email'))


# ===============================================================================
# OBJECT API ENDPOINTS
# ===============================================================================
@objects_bp.route('/api/object/<int:year><alpha:letters>')
def api_get_object_tns_format(year, letters):
    
    try:
        object_name = f"{year}{letters}"
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()
        try:
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
        finally:
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

        if not _can_read_object(matching_obj):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        return jsonify({
            'success': True,
            'object': matching_obj
        })
        
    except Exception as e:
        logger.error(f"Error fetching TNS object {year}{letters}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/status', methods=['POST'])
@admin_required
def api_update_object_status_tns_format(year, letters):
    
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
        logger.error(f"Error updating status for {year}{letters}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@objects_bp.route('/api/object/<object_name>')
def get_object_api(object_name):
    """API endpoint to get object data by name"""
    try:
        object_name = urllib.parse.unquote(object_name)
        
        # Update absolute magnitude and brightest mag before fetching
        update_object_abs_mag(object_name)
        
        # First try exact match
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
        columns = []
        conn = get_tns_db_connection()
        try:
            cursor = conn.cursor()
            for query in exact_queries:
                cursor.execute(query, (object_name,))
                exact_result = cursor.fetchone()
                if exact_result:
                    columns = [desc[0] for desc in cursor.description]
                    break
        finally:
            conn.close()

        if exact_result:
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

        if not _can_read_object(obj):
            return jsonify({'success': False, 'error': 'Access denied'}), 403
        
        full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
        if not full_name and obj.get('name'):
            full_name = obj.get('name')
        
        return jsonify({
            'success': True,
            'object': obj,
            'full_name': full_name
        })
            
    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Internal server error'
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
        try:
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
                return jsonify({'error': 'Object ID (objid) is required and could not be resolved'}), 400

            updates = {}

            # redshift
            if 'redshift' in data:
                v = data['redshift']
                if v is not None and v != '':
                    try:
                        v = float(v)
                        if v < 0:
                            return jsonify({'error': 'Redshift must be positive'}), 400
                    except (ValueError, TypeError):
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
                        return jsonify({'error': 'Tags contain invalid characters'}), 400
                    updates['tag'] = [t.strip() for t in v.split(',') if t.strip()]
                else:
                    # Keep NOT NULL contract on transient.objects.tag when clearing tags.
                    updates['tag'] = []

            if not updates:
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
                return jsonify({'error': 'Object not found'}), 404

            conn.commit()

            return jsonify({
                'success': True,
                'message': 'Object updated successfully',
                'updated_fields': list(updates.keys())
            })
        finally:
            conn.close()

    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Database error'}), 500

@objects_bp.route('/api/object/<object_name>/delete', methods=['DELETE'])
def api_delete_object(object_name):
    """Delete object from database"""
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied - Admin privileges required'}), 403
    
    object_name = urllib.parse.unquote(object_name)
    try:
        conn = get_tns_db_connection()
    except Exception:
        logger.exception("delete object: cannot get DB connection")
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor()

        # Resolve every matching object (prefix+name or bare name)
        cursor.execute("""
            SELECT obj_id
            FROM transient.objects
            WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
               OR name = %s
        """, (object_name, object_name))
        obj_ids = [r[0] for r in cursor.fetchall()]
        if not obj_ids:
            return jsonify({'error': 'Object not found'}), 404

        # Children first (FKs cascade too, but be explicit), then the object itself,
        # all in one transaction.
        for table in ('photometry', 'spectroscopy', 'comments', 'cross_matches',
                      'target_images', 'custom_targets', 'object_views',
                      'object_views_detail'):
            cursor.execute("SAVEPOINT child_delete")
            try:
                cursor.execute(
                    f"DELETE FROM transient.{table} WHERE obj_id = ANY(%s)",
                    (obj_ids,)
                )
                cursor.execute("RELEASE SAVEPOINT child_delete")
            except Exception as child_err:
                # Optional table missing on an older DB: skip it, keep the transaction usable.
                cursor.execute("ROLLBACK TO SAVEPOINT child_delete")
                logger.warning("delete object %s: skipping %s: %s", object_name, table, child_err)

        cursor.execute("DELETE FROM transient.objects WHERE obj_id = ANY(%s)", (obj_ids,))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'error': 'Failed to delete object'}), 500

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'Object {object_name} deleted successfully',
            'object_name': object_name
        })

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("Error deleting object %s", object_name)
        return jsonify({'error': 'Database error'}), 500
    finally:
        conn.close()

@objects_bp.route('/api/object/<object_name>/status', methods=['POST'])
@admin_required
def api_update_object_status_generic(object_name):
    
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
        logger.error(f"Error updating status for {object_name}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500
