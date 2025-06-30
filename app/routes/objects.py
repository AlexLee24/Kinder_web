"""
Object routes for the Kinder web application.
"""
import re
import urllib.parse
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify

from modules.tns_database import (
    search_tns_objects, update_object_status, update_object_activity
)
from modules.object_data import object_db
from modules.data_processing import DataVisualization


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
            
            # Try exact match first using direct SQL query
            from modules.tns_database import get_tns_db_connection
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Exact match queries (try multiple variants)
            exact_queries = [
                # Full name match (case insensitive)
                """SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                          reporting_groupid, reporting_group, source_groupid, source_group,
                          discoverydate, discoverymag, discmagfilter, filter, reporters,
                          time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                          creationdate, lastmodified, imported_at, updated_at, update_count,
                          COALESCE(tag, 'object') as tag
                   FROM tns_objects 
                   WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ? COLLATE NOCASE""",
                # Name only match (case insensitive)
                """SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                          reporting_groupid, reporting_group, source_groupid, source_group,
                          discoverydate, discoverymag, discmagfilter, filter, reporters,
                          time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                          creationdate, lastmodified, imported_at, updated_at, update_count,
                          COALESCE(tag, 'object') as tag
                   FROM tns_objects 
                   WHERE name = ? COLLATE NOCASE"""
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
            
            # Search for object by constructed name
            results = search_tns_objects(search_term=object_name, limit=10)
            
            # Find exact match based on year + letters pattern
            matching_obj = None
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                
                # Try multiple matching strategies
                # Strategy 1: Direct match
                if full_name.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 2: Extract year and letters from full name using regex
                match = re.search(r'(\d{4})([a-zA-Z]+)', full_name)
                if match:
                    extracted_name = f"{match.group(1)}{match.group(2)}"
                    if extracted_name.lower() == object_name.lower():
                        matching_obj = obj
                        break
            
            if not matching_obj:
                flash(f'Object {object_name} not found.', 'error')
                return redirect(url_for('marshal'))
            
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
            
            # Search for object by name pattern
            results = search_tns_objects(search_term=object_name, limit=10)
            
            # Find exact match
            matching_obj = None
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                match = re.search(r'(\d{4})([a-zA-Z]+)', full_name)
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
            
            # First try exact match
            from modules.tns_database import get_tns_db_connection
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Get exact match using SQL
            cursor.execute("""
                SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
                       reporting_groupid, reporting_group, source_groupid, source_group,
                       discoverydate, discoverymag, discmagfilter, filter, reporters,
                       time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                       creationdate, lastmodified, imported_at, updated_at, update_count,
                       COALESCE(tag, 'object') as tag
                FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ? COLLATE NOCASE
            """, (object_name,))
            
            exact_result = cursor.fetchone()
            conn.close()
            
            if exact_result:
                # Convert to dictionary
                columns = ['objid', 'name_prefix', 'name', 'ra', 'declination', 'redshift', 'typeid', 'type',
                          'reporting_groupid', 'reporting_group', 'source_groupid', 'source_group',
                          'discoverydate', 'discoverymag', 'discmagfilter', 'filter', 'reporters',
                          'time_received', 'internal_names', 'discovery_ads_bibcode', 'class_ads_bibcodes',
                          'creationdate', 'lastmodified', 'imported_at', 'updated_at', 'update_count', 'tag']
                obj = dict(zip(columns, exact_result))
            else:
                # Fallback to search function
                results = search_tns_objects(search_term=object_name, limit=1)
                if not results or len(results) == 0:
                    return jsonify({'error': 'Object not found'}), 404
                
                obj = results[0]
            
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
            
            # Basic fields that can be updated
            updatable_fields = [
                'type', 'ra', 'declination', 'redshift', 'discoverymag', 
                'discoveryfilter', 'discoverydate', 'source_group', 
                'reporting_group', 'remarks'
            ]
            
            for field in updatable_fields:
                if field in data:
                    value = data[field]
                    
                    # Validate specific fields
                    if field in ['ra', 'declination', 'redshift', 'discoverymag']:
                        if value and value != '':
                            try:
                                value = float(value)
                                if field == 'ra' and not (0 <= value < 360):
                                    return jsonify({'error': 'RA must be between 0 and 360 degrees'}), 400
                                if field == 'declination' and not (-90 <= value <= 90):
                                    return jsonify({'error': 'Dec must be between -90 and 90 degrees'}), 400
                                if field == 'redshift' and value < 0:
                                    return jsonify({'error': 'Redshift must be positive'}), 400
                                if field == 'discoverymag' and not (-5 <= value <= 30):
                                    return jsonify({'error': 'Magnitude should be between -5 and 30'}), 400
                            except (ValueError, TypeError):
                                return jsonify({'error': f'Invalid value for {field}'}), 400
                        else:
                            value = None
                    
                    elif field == 'discoverydate':
                        if value and value != '':
                            try:
                                # Validate date format
                                datetime.strptime(value, '%Y-%m-%d')
                            except ValueError:
                                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
                        else:
                            value = None
                    
                    elif field in ['type', 'discoveryfilter', 'source_group', 'reporting_group', 'remarks']:
                        if value and len(str(value).strip()) > 200:
                            return jsonify({'error': f'{field} is too long (maximum 200 characters)'}), 400
                        value = str(value).strip() if value else None
                    
                    updates[field] = value
            
            if not updates:
                return jsonify({'error': 'No valid fields to update'}), 400
            
            # Update database
            from modules.tns_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Build update query
            set_clauses = []
            params = []
            
            for field, value in updates.items():
                set_clauses.append(f"{field} = ?")
                params.append(value)
            
            # Add lastmodified timestamp
            set_clauses.append("lastmodified = CURRENT_TIMESTAMP")
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            params.append(object_name)  # For WHERE clause
            
            update_query = f"""
                UPDATE tns_objects 
                SET {', '.join(set_clauses)}
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?
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
            
            from modules.tns_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # First check if object exists
            cursor.execute("""
                SELECT name_prefix, name, type, discoverydate 
                FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?
            """, (object_name,))
            
            existing_object = cursor.fetchone()
            if not existing_object:
                conn.close()
                return jsonify({'error': 'Object not found'}), 404
            
            # Delete from tns_objects table
            cursor.execute("""
                DELETE FROM tns_objects 
                WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?
            """, (object_name,))
            
            rows_affected = cursor.rowcount
            
            if rows_affected == 0:
                conn.close()
                return jsonify({'error': 'Failed to delete object'}), 500
            
            # Also delete related data from object_data database
            try:
                # Delete photometry data
                phot_conn = object_db.get_connection()
                phot_cursor = phot_conn.cursor()
                
                phot_cursor.execute("DELETE FROM photometry WHERE object_name = ?", (object_name,))
                deleted_photometry = phot_cursor.rowcount
                
                phot_cursor.execute("DELETE FROM spectroscopy WHERE object_name = ?", (object_name,))
                deleted_spectroscopy = phot_cursor.rowcount
                
                phot_cursor.execute("DELETE FROM comments WHERE object_name = ?", (object_name,))
                deleted_comments = phot_cursor.rowcount
                
                phot_conn.commit()
                phot_conn.close()
                
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
            
            if not new_status or new_status not in ['object', 'followup', 'finished', 'snoozed']:
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
            photometry = object_db.get_photometry(object_name)
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
            spectra_list = object_db.get_spectrum_list(object_name)
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
            conn = object_db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT wavelength, intensity FROM spectroscopy 
                WHERE object_name = ? AND spectrum_id = ?
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
            point_id = object_db.add_photometry_point(
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
            spectrum_id = object_db.add_spectrum_data(
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
            if object_db.delete_photometry_point(point_id):
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
            if object_db.delete_spectrum(spectrum_id):
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
        
        try:
            photometry_data = object_db.get_photometry(object_name)
            
            if not photometry_data:
                return jsonify({
                    'success': True,
                    'plot_html': None,
                    'message': 'No photometry data available'
                })
            
            plot_html = DataVisualization.create_photometry_plot_from_db(photometry_data)
            
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
        spectrum_id = request.args.get('spectrum_id')
        
        try:
            spectrum_data = object_db.get_spectroscopy(object_name)
            
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
            
            results = search_tns_objects(search_term=object_name, limit=1)
            
            if not results:
                return jsonify({
                    'success': False,
                    'error': f'Object {object_name} not found'
                }), 404
            
            photometry_data = object_db.get_photometry(object_name)
            
            if not photometry_data:
                return jsonify({
                    'success': True,
                    'plot_html': None,
                    'message': 'No photometry data available for this object'
                })
            
            plot_html = DataVisualization.create_photometry_plot_from_db(photometry_data)
            
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
        spectrum_id = request.args.get('spectrum_id')
        
        try:
            results = search_tns_objects(search_term=object_name, limit=1)
            
            if not results:
                return jsonify({
                    'success': False,
                    'error': f'Object {object_name} not found'
                }), 404
            
            spectrum_data = object_db.get_spectroscopy(object_name)
            
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
            comments = object_db.get_comments(object_name)
            
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
            comment_id = object_db.add_comment(
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
            # Check if comment exists
            comment = object_db.get_comment_by_id(comment_id)
            if not comment:
                return jsonify({'error': 'Comment not found'}), 404
            
            if object_db.delete_comment(comment_id):
                return jsonify({
                    'success': True,
                    'message': 'Comment deleted successfully'
                })
            else:
                return jsonify({'error': 'Failed to delete comment'}), 500
            
        except Exception as e:
            app.logger.error(f"Error deleting comment {comment_id}: {str(e)}")
            return jsonify({'error': 'Failed to delete comment'}), 500
