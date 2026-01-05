from flask import render_template, request, jsonify, flash, redirect, url_for, session, send_file
from modules.postgres_database import get_cross_match_results, update_cross_match_flag, get_available_dates, tns_object_db, get_target_image, set_cross_match_host, update_tns_redshift, unset_cross_match_host
from modules.data_processing import DataVisualization
from modules.ext_M_calculator import apm_to_abm, get_extinction
import json
import io

def register_detect_results_routes(app):
    @app.route('/detect_image/<target_name>')
    def detect_image(target_name):
        if 'user' not in session:
            return "Unauthorized", 401
            
        image_data = get_target_image(target_name)
        if image_data:
            return send_file(
                io.BytesIO(image_data),
                mimetype='image/png',
                as_attachment=False,
                download_name=f'{target_name}_marked.png'
            )
        else:
            return "Image not found", 404

    @app.route('/api/set_host', methods=['POST'])
    def set_host():
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
            
        data = request.json
        match_id = data.get('match_id')
        target_name = data.get('target_name')
        redshift = data.get('redshift')
        source = data.get('source')
        
        if not match_id or not target_name:
            return jsonify({'success': False, 'message': 'Missing parameters'})
            
        # 1. Update cross_match_results (set is_host)
        if set_cross_match_host(match_id, target_name):
            # 2. Update tns_objects redshift
            if redshift is not None:
                try:
                    # Format to 3 decimal places
                    z_val = float(redshift)
                    z_str = f"{z_val:.3f}"
                except (ValueError, TypeError):
                    z_str = str(redshift)
                
                # User requested 3 decimal places, no source
                redshift_str = z_str
                update_tns_redshift(target_name, redshift_str)
                return jsonify({'success': True})
            return jsonify({'success': True, 'message': 'Host set, but no redshift to update'})
        else:
            return jsonify({'success': False, 'message': 'Database error'})

    @app.route('/api/unset_host', methods=['POST'])
    def unset_host():
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
            
        data = request.json
        target_name = data.get('target_name')
        
        if not target_name:
            return jsonify({'success': False, 'message': 'Missing parameters'})
            
        if unset_cross_match_host(target_name):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Database error'})

    @app.route('/detect')
    def detect_results():
        if 'user' not in session:
            flash('Please log in to access Detect Results.', 'warning')
            return redirect(url_for('login'))
            
        # Get date from query parameter
        selected_date = request.args.get('detect_results')
        
        # Get available dates for the dropdown
        available_dates = get_available_dates()
        latest_date = available_dates[0] if available_dates else None
        
        # If no date selected, render the homepage
        if not selected_date:
            return render_template('detect_home.html', 
                                   latest_date=latest_date, 
                                   current_path='/detect')
            
        results = get_cross_match_results(date=selected_date)
        
        # Group results by target
        results_by_target = {}
        for row in results:
            # Parse match_data if needed
            if isinstance(row.get('match_data'), str):
                try:
                    row['match_data'] = json.loads(row['match_data'])
                except:
                    pass
            
            t_name = row.get('target_name')
            if not t_name: continue
            
            if t_name not in results_by_target:
                results_by_target[t_name] = []
            results_by_target[t_name].append(row)
            
        final_target_list = []
        target_cache = {} # Cache to avoid repeated DB calls for same target
        
        for target_name, matches in results_by_target.items():
            # Sort matches by separation
            matches.sort(key=lambda x: float(x.get('separation_arcsec', 9999)))
            
            # Fetch common data (photometry, tns_details)
            if target_name not in target_cache:
                photometry = tns_object_db.get_photometry(target_name)
                for point in photometry:
                    if 'created_at' in point:
                        point['created_at'] = str(point['created_at'])
                    if 'updated_at' in point:
                        point['updated_at'] = str(point['updated_at'])
                
                tns_details = tns_object_db.get_object_details(target_name)
                target_cache[target_name] = {
                    'photometry': photometry,
                    'tns_details': tns_details
                }
            
            photometry = target_cache[target_name]['photometry']
            tns_details = target_cache[target_name]['tns_details']
            
            processed_matches = []
            for row in matches:
                match_data = row.get('match_data', {})
                
                # Normalize TNS Info
                if tns_details:
                    row['tns_info'] = {
                        'discoverydate': tns_details.get('discoverydate', 'N/A'),
                        'internal_names': tns_details.get('internal_names', 'N/A'),
                        'ra': tns_details.get('ra', 'N/A'),
                        'dec': tns_details.get('declination', 'N/A')
                    }
                else:
                    row['tns_info'] = {
                        'discoverydate': match_data.get('tns_discoverydate', 'N/A'),
                        'internal_names': match_data.get('tns_internal_names', 'N/A'),
                        'ra': match_data.get('tns_ra', 'N/A'),
                        'dec': match_data.get('tns_dec', 'N/A')
                    }
                
                # Redshift from THIS match
                redshift = match_data.get('Z') or match_data.get('z') or match_data.get('redshift') or match_data.get('z(s)')
                try:
                    redshift = float(redshift) if redshift is not None else None
                except (ValueError, TypeError):
                    redshift = None
                row['z'] = redshift
                
                # RA/Dec for plot (TNS coords preferred)
                ra = row['tns_info']['ra']
                dec = row['tns_info']['dec']
                try:
                    ra = float(ra) if ra != 'N/A' else None
                    dec = float(dec) if dec != 'N/A' else None
                except:
                    ra, dec = None, None

                # Absolute Magnitude Calculation (per match)
                calc_z = redshift
                calculated_abs_mag = None
                if calc_z is not None and photometry and ra is not None and dec is not None:
                    try:
                        brightest_point = None
                        min_mag = float('inf')
                        for point in photometry:
                            mag = point.get('magnitude')
                            if mag is not None:
                                try:
                                    mag_val = float(mag)
                                    if mag_val < min_mag:
                                        min_mag = mag_val
                                        brightest_point = point
                                except:
                                    continue
                        
                        if brightest_point:
                            filter_name = brightest_point.get('filter', 'V')
                            extinction = get_extinction(ra, dec, filter_name)
                            calculated_abs_mag = apm_to_abm(min_mag, calc_z, extinction)
                            if isinstance(calculated_abs_mag, dict):
                                calculated_abs_mag = None
                    except Exception as e:
                        print(f"Error calculating abs mag for {target_name}: {e}")
                
                if calculated_abs_mag is not None:
                    row['abs_mag'] = calculated_abs_mag
                else:
                    abs_mag = match_data.get('brightest_abs_mag')
                    try:
                        abs_mag = float(abs_mag) if abs_mag is not None else None
                    except (ValueError, TypeError):
                        abs_mag = None
                    row['abs_mag'] = abs_mag
                    
                row['is_flagged'] = bool(row.get('flag'))
                row['flag_id'] = row.get('id')
                row['is_host'] = bool(row.get('is_host'))
                processed_matches.append(row)
            
            # Create Target Object
            if not processed_matches:
                continue
                
            best_match = processed_matches[0]
            
            # Generate plot for the target (using best match's Z for reference)
            plot_html = None
            try:
                ra = best_match['tns_info']['ra']
                dec = best_match['tns_info']['dec']
                ra = float(ra) if ra != 'N/A' else None
                dec = float(dec) if dec != 'N/A' else None
                
                plot_html = DataVisualization.create_photometry_plot_from_db(
                    photometry, best_match.get('z'), ra, dec
                )
            except Exception as e:
                print(f"Error generating plot for {target_name}: {e}")
            
            target_obj = {
                'target_name': target_name,
                'id': best_match.get('id'),
                'tns_info': best_match.get('tns_info'),
                'plot_html': plot_html,
                'matches': processed_matches,
                'best_match': best_match,
                'is_flagged': best_match.get('is_flagged'),
                'flag_id': best_match.get('flag_id')
            }
            final_target_list.append(target_obj)
        
        # Sort by target name
        final_target_list.sort(key=lambda x: x['target_name'])
        
        # Summary results (best match from each target)
        summary_results = [t['best_match'] for t in final_target_list]
            
        return render_template('detect_results.html', 
                             results=final_target_list, 
                             summary_results=summary_results,
                             current_path='/detect',
                             available_dates=available_dates,
                             selected_date=selected_date)

    @app.route('/api/toggle_flag', methods=['POST'])
    def toggle_flag():
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
            
        data = request.json
        result_id = data.get('id')
        flag_value = data.get('flag')
        
        if update_cross_match_flag(result_id, flag_value):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Database error'})
