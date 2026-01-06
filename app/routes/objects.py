"""
Object routes for the Kinder web application.
"""
import re
import math
import urllib.parse
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify

from modules.postgres_database import (
    search_tns_objects, update_object_status, update_object_activity, get_tns_db_connection,
    TNSObjectDB
)
from modules.database import (
    get_all_groups, get_object_permissions, grant_object_permission, 
    revoke_object_permission, check_object_access
)
from modules.data_processing import DataVisualization
from modules import ext_M_calculator


def register_object_routes(app):
    """Register object routes with the Flask app"""
    
    # ===============================================================================
    # OBJECT DETAILS
    # ===============================================================================
    @app.route('/object/<path:object_name>')
    def object_detail_generic(object_name):
        """Generic object detail route for all object names"""
        if 'user' not in session:
            flash('Please log in to access object data.', 'warning')
            return redirect(url_for('login'))
        
        try:
            object_name = urllib.parse.unquote(object_name)
            
            # Update absolute magnitude and brightest mag
            from modules.postgres_database import update_object_abs_mag
            update_object_abs_mag(object_name)
            
            # Try exact match first using direct SQL query
            from modules.postgres_database import get_tns_db_connection
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Exact match queries (try multiple variants)
            tag_logic = """
            CASE 
                WHEN finish_follow = 1 THEN 'finished'
                WHEN follow = 1 THEN 'followup'
                WHEN snoozed = 1 THEN 'snoozed'
                ELSE 'object'
            END as tag
            """
            
            exact_queries = [
                # Full name match (case insensitive)
                f"""SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                          reporting_groupid, reporting_group, source_groupid, source_group,
                          discoverydate, discoverymag, discmagfilter, filter, reporters,
                          time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                          creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                          {tag_logic}
                   FROM tns_objects 
                   WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) ILIKE %s""",
                # Name only match (case insensitive)
                f"""SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                          reporting_groupid, reporting_group, source_groupid, source_group,
                          discoverydate, discoverymag, discmagfilter, filter, reporters,
                          time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                          creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                          {tag_logic}
                   FROM tns_objects 
                   WHERE name ILIKE %s"""
            ]
            
            matching_obj = None
            for i, query in enumerate(exact_queries):
                cursor.execute(query, (object_name,))
                result = cursor.fetchone()
                if result:
                    columns = [desc[0] for desc in cursor.description]
                    matching_obj = dict(zip(columns, result))
                    break
            
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
                return redirect(url_for('marshal'))
            
            # Values are already calculated by update_object_abs_mag and fetched from DB
            # No need to recalculate here

            # Convert datetime objects to strings for template compatibility
            if matching_obj:
                for key, value in matching_obj.items():
                    if isinstance(value, datetime):
                        matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
            
            return render_template('object_detail.html', 
                                 current_path='/object',
                                 object_data=matching_obj,
                                 object_name=object_name)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash('Error loading object data.', 'error')
            return redirect(url_for('marshal'))

    @app.route('/object/<int:year><alpha:letters>')
    def object_detail_tns_format(year, letters):
        if 'user' not in session:
            flash('Please log in to access object data.', 'warning')
            return redirect(url_for('login'))
        
        try:
            # Construct TNS-style name from year and letters
            object_name = f"{year}{letters}"
            
            # Update absolute magnitude and brightest mag
            from modules.postgres_database import update_object_abs_mag
            update_object_abs_mag(object_name)
            
            # Try exact match first using direct SQL query
            from modules.postgres_database import get_tns_db_connection
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            tag_logic = """
            CASE 
                WHEN finish_follow = 1 THEN 'finished'
                WHEN follow = 1 THEN 'followup'
                WHEN snoozed = 1 THEN 'snoozed'
                ELSE 'object'
            END as tag
            """
            
            # Exact match query - match name exactly (case insensitive)
            exact_query = f"""SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                          reporting_groupid, reporting_group, source_groupid, source_group,
                          discoverydate, discoverymag, discmagfilter, filter, reporters,
                          time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                          creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                          {tag_logic}
                   FROM tns_objects 
                   WHERE name ILIKE %s"""
            
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
                return redirect(url_for('marshal'))
            
            # Values are already calculated by update_object_abs_mag and fetched from DB
            # No need to recalculate here

            # Convert datetime objects to strings for template compatibility
            if matching_obj:
                for key, value in matching_obj.items():
                    if isinstance(value, datetime):
                        matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
            
            return render_template('object_detail.html', 
                                 current_path='/object',
                                 object_data=matching_obj,
                                 object_name=object_name)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash('Error loading object data.', 'error')
            return redirect(url_for('marshal'))

    # ===============================================================================
    # OBJECT API ENDPOINTS
    # ===============================================================================
    @app.route('/api/object/<int:year><alpha:letters>')
    def api_get_object_tns_format(year, letters):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            object_name = f"{year}{letters}"
            
            # Try exact match first using direct SQL query
            from modules.postgres_database import get_tns_db_connection
            conn = get_tns_db_connection()  
            cursor = conn.cursor()
            
            # Exact match query - match name exactly (case insensitive)
            cursor.execute("""
                SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                       reporting_groupid, reporting_group, source_groupid, source_group,
                       discoverydate, discoverymag, discmagfilter, filter, reporters,
                       time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                       creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                       CASE 
                            WHEN finish_follow = 1 THEN 'finished'
                            WHEN follow = 1 THEN 'followup'
                            WHEN snoozed = 1 THEN 'snoozed'
                            ELSE 'object'
                       END as tag
                FROM tns_objects 
                WHERE name ILIKE %s
            """, (object_name,))
            
            result = cursor.fetchone()
            matching_obj = None
            
            if result:
                columns = ['objid', 'name_prefix', 'name', 'ra', 'declination', 'redshift', 'typeid', 'type',
                          'reporting_groupid', 'reporting_group', 'source_groupid', 'source_group',
                          'discoverydate', 'discoverymag', 'discmagfilter', 'filter', 'reporters',
                          'time_received', 'internal_names', 'discovery_ads_bibcode', 'class_ads_bibcodes',
                          'creationdate', 'lastmodified', 'brightest_mag', 'brightest_abs_mag', 'tag']
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
            app.logger.error(f"Error fetching TNS object {year}{letters}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/object/<int:year><alpha:letters>/status', methods=['POST'])
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
            app.logger.error(f"Error updating status for {year}{letters}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/object/<object_name>')
    def get_object_api(object_name):
        """API endpoint to get object data by name"""
        try:
            object_name = urllib.parse.unquote(object_name)
            
            # Update absolute magnitude and brightest mag before fetching
            from modules.postgres_database import update_object_abs_mag
            update_object_abs_mag(object_name)
            
            # First try exact match
            from modules.postgres_database import get_tns_db_connection
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Get exact match using SQL - try multiple queries
            exact_queries = [
                # Full name match (prefix + name)
                """SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                       reporting_groupid, reporting_group, source_groupid, source_group,
                       discoverydate, discoverymag, discmagfilter, filter, reporters,
                       time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                       creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                       CASE 
                            WHEN finish_follow = 1 THEN 'finished'
                            WHEN follow = 1 THEN 'followup'
                            WHEN snoozed = 1 THEN 'snoozed'
                            ELSE 'object'
                       END as tag
                FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) ILIKE %s""",
                # Name only match (exact)
                """SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                       reporting_groupid, reporting_group, source_groupid, source_group,
                       discoverydate, discoverymag, discmagfilter, filter, reporters,
                       time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                       creationdate, lastmodified, brightest_mag, brightest_abs_mag,
                       CASE 
                            WHEN finish_follow = 1 THEN 'finished'
                            WHEN follow = 1 THEN 'followup'
                            WHEN snoozed = 1 THEN 'snoozed'
                            ELSE 'object'
                       END as tag
                FROM tns_objects 
                WHERE name ILIKE %s"""
            ]
            
            exact_result = None
            for query in exact_queries:
                cursor.execute(query, (object_name,))
                exact_result = cursor.fetchone()
                if exact_result:
                    break
            
            conn.close()
            
            if exact_result:
                # Convert to dictionary
                columns = ['objid', 'name_prefix', 'name', 'ra', 'declination', 'redshift', 'typeid', 'type',
                          'reporting_groupid', 'reporting_group', 'source_groupid', 'source_group',
                          'discoverydate', 'discoverymag', 'discmagfilter', 'filter', 'reporters',
                          'time_received', 'internal_names', 'discovery_ads_bibcode', 'class_ads_bibcodes',
                          'creationdate', 'lastmodified', 'brightest_mag', 'brightest_abs_mag', 'tag']
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

    @app.route('/api/object/<object_name>/edit', methods=['POST'])
    def api_edit_object(object_name):
        """Edit object data"""
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied - Admin privileges required'}), 403
        
        try:
            object_name = urllib.parse.unquote(object_name)
            data = request.get_json()
            
            # Validate input data
            updates = {}
            
            # Basic fields that can be updated - ONLY Redshift allowed now
            updatable_fields = ['redshift']
            
            for field in updatable_fields:
                if field in data:
                    value = data[field]
                    
                    # Validate specific fields
                    if field == 'redshift':
                        if value and value != '':
                            try:
                                value = float(value)
                                if value < 0:
                                    return jsonify({'error': 'Redshift must be positive'}), 400
                            except (ValueError, TypeError):
                                return jsonify({'error': f'Invalid value for {field}'}), 400
                        else:
                            value = None
                    
                    updates[field] = value
            
            if not updates:
                return jsonify({'error': 'No valid fields to update'}), 400
            
            # Update database
            from modules.postgres_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Build update query
            set_clauses = []
            params = []
            
            for field, value in updates.items():
                set_clauses.append(f"{field} = %s")
                params.append(value)
            
            # NOTE: We explicitly DO NOT update lastmodified or updated_at
            
            params.append(object_name)  # For WHERE clause
            
            update_query = f"""
                UPDATE tns_objects 
                SET {', '.join(set_clauses)}
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
            """
            
            cursor.execute(update_query, params)
            rows_affected = cursor.rowcount
            
            if rows_affected == 0:
                conn.close()
                return jsonify({'error': 'Object not found'}), 404
            
            conn.commit()
            conn.close()
            
            # Update activity timestamp
            update_object_activity(object_name, "data_edit")
            
            updated_fields = list(updates.keys())
            
            return jsonify({
                'success': True,
                'message': f'Object {object_name} updated successfully',
                'updated_fields': updated_fields
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Database error: {str(e)}'}), 500

    @app.route('/api/object/<object_name>/delete', methods=['DELETE'])
    def api_delete_object(object_name):
        """Delete object from database"""
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied - Admin privileges required'}), 403
        
        try:
            object_name = urllib.parse.unquote(object_name)
            
            from modules.postgres_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # First check if object exists
            cursor.execute("""
                SELECT name_prefix, name, type, discoverydate 
                FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
            """, (object_name,))
            
            existing_object = cursor.fetchone()
            if not existing_object:
                conn.close()
                return jsonify({'error': 'Object not found'}), 404
            
            # Delete from tns_objects table
            cursor.execute("""
                DELETE FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
            """, (object_name,))
            
            rows_affected = cursor.rowcount
            
            if rows_affected == 0:
                conn.close()
                return jsonify({'error': 'Failed to delete object'}), 500
            
            # Also delete related data from PostgreSQL database
            try:
                # Delete photometry data
                cursor.execute("DELETE FROM photometry WHERE object_name = %s", (object_name,))
                deleted_photometry = cursor.rowcount
                
                cursor.execute("DELETE FROM spectroscopy WHERE object_name = %s", (object_name,))
                deleted_spectroscopy = cursor.rowcount
                
                cursor.execute("DELETE FROM comments WHERE object_name = %s", (object_name,))
                deleted_comments = cursor.rowcount
                
                conn.commit()
                conn.close()
                
            except Exception:
                # Continue with main deletion even if related data deletion fails
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

    @app.route('/api/object/<object_name>/status', methods=['POST'])
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
            app.logger.error(f"Error updating status for {object_name}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # ===============================================================================
    # OBJECT DATA API
    # ===============================================================================
    @app.route('/api/object/<int:year><alpha:letters>/photometry')
    def get_object_photometry(year, letters):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = f"{year}{letters}"
        
        try:
            # Sync last photometry date to ensure consistency
            TNSObjectDB.sync_last_photometry_date(object_name)
            
            photometry = TNSObjectDB.get_photometry(object_name)
            return jsonify({
                'success': True,
                'photometry': photometry,
                'count': len(photometry)
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/object/<int:year><alpha:letters>/spectroscopy')
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

    @app.route('/api/object/<int:year><alpha:letters>/spectrum/<spectrum_id>')
    def get_spectrum_data(year, letters, spectrum_id):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = f"{year}{letters}"
        
        try:
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT wavelength, intensity FROM spectroscopy 
                WHERE object_name = %s AND spectrum_id = %s
                ORDER BY wavelength ASC
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

    @app.route('/api/object/<int:year><alpha:letters>/photometry', methods=['POST'])
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

    @app.route('/api/object/<int:year><alpha:letters>/spectroscopy', methods=['POST'])
    def upload_spectroscopy(year, letters):
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = f"{year}{letters}"
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

    @app.route('/api/photometry/<int:point_id>', methods=['DELETE'])
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

    @app.route('/api/spectrum/<spectrum_id>', methods=['DELETE'])
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

    @app.route('/api/object/<int:year><alpha:letters>/photometry/plot')
    def get_object_photometry_plot(year, letters):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = f"{year}{letters}"
        
        # Check permissions
        if not check_object_access(object_name, session['user']['email']):
             return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'Access denied: You do not have permission to view this data.'
            })
        
        try:
            # Get object data for redshift, ra, and dec
            results = search_tns_objects(search_term=object_name, limit=1)
            obj_data = results[0] if results else {}
            redshift = obj_data.get('redshift')
            ra = obj_data.get('ra')
            dec = obj_data.get('declination')
            
            photometry_data = TNSObjectDB.get_photometry(object_name)
            
            if not photometry_data:
                return jsonify({
                    'success': True,
                    'plot_html': None,
                    'message': 'No photometry data available'
                })
            
            plot_html = DataVisualization.create_photometry_plot_from_db(photometry_data, redshift=redshift, ra=ra, dec=dec)
            
            return jsonify({
                'success': True,
                'plot_html': plot_html,
                'data_count': len(photometry_data)
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/object/<int:year><alpha:letters>/spectrum/plot')
    def get_object_spectrum_plot(year, letters):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = f"{year}{letters}"
        
        # Check permissions
        if not check_object_access(object_name, session['user']['email']):
             return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'Access denied: You do not have permission to view this data.'
            })
            
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

    @app.route('/api/object/<object_name>/photometry/plot')
    def get_object_photometry_plot_generic(object_name):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            object_name = urllib.parse.unquote(object_name)
            
            # Check permissions
            if not check_object_access(object_name, session['user']['email']):
                 return jsonify({
                    'success': True,
                    'plot_html': None,
                    'message': 'Access denied: You do not have permission to view this data.'
                })
            
            results = search_tns_objects(search_term=object_name, limit=1)
            
            if not results:
                return jsonify({
                    'success': False,
                    'error': f'Object {object_name} not found'
                }), 404
            
            photometry_data = TNSObjectDB.get_photometry(object_name)
            
            if not photometry_data:
                return jsonify({
                    'success': True,
                    'plot_html': None,
                    'message': 'No photometry data available for this object'
                })
            
            # Get redshift from object data
            redshift = results[0].get('redshift')
            
            plot_html = DataVisualization.create_photometry_plot_from_db(photometry_data, redshift=redshift)
            
            return jsonify({
                'success': True,
                'plot_html': plot_html,
                'data_count': len(photometry_data)
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/object/<object_name>/spectrum/plot')
    def get_object_spectrum_plot_generic(object_name):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        object_name = urllib.parse.unquote(object_name)
        
        # Check permissions
        if not check_object_access(object_name, session['user']['email']):
             return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'Access denied: You do not have permission to view this data.'
            })
            
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
    @app.route('/api/object/<object_name>/comments')
    def get_object_comments(object_name):
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            object_name = urllib.parse.unquote(object_name)
            
            # Check permissions
            if not check_object_access(object_name, session['user']['email']):
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
            app.logger.error(f"Error getting comments for {object_name}: {str(e)}")
            return jsonify({'error': 'Failed to get comments'}), 500

    @app.route('/api/object/<object_name>/comments', methods=['POST'])
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
            app.logger.error(f"Error adding comment for {object_name}: {str(e)}")
            return jsonify({'error': 'Failed to add comment'}), 500

    @app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
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
            app.logger.error(f"Error deleting comment {comment_id}: {str(e)}")
            return jsonify({'error': 'Failed to delete comment'}), 500

    # ===============================================================================
    # PERMISSIONS
    # ===============================================================================
    @app.route('/api/groups')
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

    @app.route('/api/object/<object_name>/permissions')
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

    @app.route('/api/object/<object_name>/permissions', methods=['POST'])
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

    @app.route('/api/object/<object_name>/permissions', methods=['DELETE'])
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
            app.logger.error(f"Error deleting comment {comment_id}: {str(e)}")
            return jsonify({'error': 'Failed to delete comment'}), 500
