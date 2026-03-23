import logging
from flask import render_template, request, jsonify, flash, redirect, url_for, session, send_file

logger = logging.getLogger(__name__)
from modules.postgres_database import get_cross_match_results, update_cross_match_flag, get_available_dates, get_daily_match_counts, tns_object_db, get_target_image, set_cross_match_host, update_tns_redshift, unset_cross_match_host
from modules.data_processing import DataVisualization
from modules.ext_M_calculator import apm_to_abm, get_extinction
import json
import io

def register_detect_results_routes(app):
    @app.route('/detect_image/<target_name>')
    def detect_image(target_name):
        if 'user' not in session:
            return "Unauthorized", 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            return "Unauthorized", 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
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
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
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
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
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
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            flash('Access denied. This page is not available for Guest users.', 'error')
            return redirect(url_for('home'))
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            flash('Access denied. This page is not available for Guest users.', 'error')
            return redirect(url_for('home'))
            
        # Get date from query parameter
        selected_date = request.args.get('detect_results')
        
        # Get available dates for the dropdown
        available_dates = get_available_dates()
        latest_date = available_dates[0] if available_dates else None
        
        # If no date selected, render the homepage
        if not selected_date:
            daily_counts = get_daily_match_counts()
            return render_template('detect_home.html',
                                   latest_date=latest_date,
                                   daily_counts=daily_counts,
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
                redshift = None
                for z_key in ['Z', 'z', 'redshift', 'z(s)', 'z_spec', 'z_phot']:
                    if z_key in match_data and match_data[z_key] is not None and match_data[z_key] != '':
                        redshift = match_data[z_key]
                        break
                        
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

                # Absolute Magnitude Calculation (per match) using latest point
                calc_z = redshift
                calculated_abs_mag = None
                
                has_mag_data = bool(photometry) or (tns_details and tns_details.get('discoverymag') is not None)
                
                import sys
                import os
                is_debug = os.getenv('DEBUG', 'False').lower() in ('true', '1')
                if is_debug:
                    print(f"[DEBUG] Target {target_name} match: z={calc_z}, photometry_len={len(photometry) if photometry else 0}, has_tns_mag={tns_details.get('discoverymag') if tns_details else None}, RA={ra}, DEC={dec}", file=sys.stderr, flush=True)
                    logger.info(f"[DEBUG-LOGGER] Target {target_name} match: z={calc_z}, photometry_len={len(photometry) if photometry else 0}, has_tns_mag={tns_details.get('discoverymag') if tns_details else None}, RA={ra}, DEC={dec}")

                if calc_z is not None and has_mag_data and ra is not None and dec is not None:
                    try:
                        latest_mag = None
                        filter_name = 'V'
                        
                        if photometry:
                            for point in reversed(photometry):
                                mag = point.get('magnitude')
                                if mag is not None:
                                    try:
                                        latest_mag = float(mag)
                                        filter_name = point.get('filter', 'V')
                                        break
                                    except:
                                        continue
                            if is_debug:
                                print(f"[DEBUG] Target {target_name} using photometry latest_mag: {latest_mag} filter: {filter_name}", file=sys.stderr, flush=True)
                        else:
                            try:
                                latest_mag = float(tns_details.get('discoverymag'))
                                filter_name = tns_details.get('filter', 'V')
                            except:
                                latest_mag = None
                            if is_debug:
                                print(f"[DEBUG] Target {target_name} using TNS discoverymag: {latest_mag} filter: {filter_name}", file=sys.stderr, flush=True)

                        if latest_mag is not None:
                            extinction = get_extinction(ra, dec, filter_name)
                            if hasattr(extinction, 'item'):
                                extinction = extinction.item()
                            calculated_abs_mag = apm_to_abm(latest_mag, calc_z, extinction)
                            if is_debug:
                                print(f"[DEBUG] Target {target_name} calc abs_mag: ext={extinction}, result={calculated_abs_mag}", file=sys.stderr, flush=True)
                                logger.info(f"[DEBUG-LOGGER] Target {target_name} calc abs_mag: ext={extinction}, result={calculated_abs_mag}")
                            if isinstance(calculated_abs_mag, dict):
                                if is_debug:
                                    print(f"[DEBUG] Target {target_name} calc error: {calculated_abs_mag}", file=sys.stderr, flush=True)
                                calculated_abs_mag = None
                    except Exception as e:
                        logger.error('Error calculating abs mag for %s: %s', target_name, e)
                        if is_debug:
                            print(f"[DEBUG] Error calculating abs mag: {e}", file=sys.stderr, flush=True)
                else:
                    if is_debug:
                        print(f"[DEBUG] Target {target_name} skipped calc. Details: z={calc_z}, has_mag_data={has_mag_data}, ra={ra}, dec={dec}", file=sys.stderr, flush=True)
                        logger.info(f"[DEBUG-LOGGER] Target {target_name} skipped calc.")
                
                if calculated_abs_mag is not None:
                    row['abs_mag'] = calculated_abs_mag
                    if is_debug:
                        print(f"[DEBUG] Target {target_name} SET final abs_mag: {calculated_abs_mag}", file=sys.stderr, flush=True)
                else:
                    abs_mag = match_data.get('brightest_abs_mag') # fallback or empty
                    if not abs_mag:
                        abs_mag = match_data.get('latest_abs_mag') # if it exists
                    try:
                        abs_mag = float(abs_mag) if abs_mag is not None else None
                    except (ValueError, TypeError):
                        abs_mag = None
                    row['abs_mag'] = abs_mag
                    if is_debug:
                        print(f"[DEBUG] Target {target_name} FALLBACK abs_mag: {abs_mag}", file=sys.stderr, flush=True)
                    
                row['is_flagged'] = bool(row.get('flag'))
                row['flag_id'] = row.get('id')
                row['is_host'] = bool(row.get('is_host'))
                processed_matches.append(row)
            
            # Create Target Object
            if not processed_matches:
                continue
                
            best_match = processed_matches[0]
            
            # Generate plot for the target (using best match's Z for reference)
            plot_json = None
            try:
                ra = best_match['tns_info']['ra']
                dec = best_match['tns_info']['dec']
                ra = float(ra) if ra != 'N/A' else None
                dec = float(dec) if dec != 'N/A' else None
                
                plot_json = DataVisualization.create_photometry_plot_from_db(
                    photometry, best_match.get('z'), ra, dec, as_json=True
                )
            except Exception as e:
                logger.error('Error generating plot for %s: %s', target_name, e)
            
            target_obj = {
                'target_name': target_name,
                'id': best_match.get('id'),
                'tns_info': best_match.get('tns_info'),
                'plot_json': plot_json,
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
        
        daily_counts = get_daily_match_counts()
            
        return render_template('detect_results.html', 
                             results=final_target_list, 
                             summary_results=summary_results,
                             current_path='/detect',
                             available_dates=available_dates,
                             daily_counts=daily_counts,
                             selected_date=selected_date)

    @app.route('/detect/archives')
    def detect_archives():
        if 'user' not in session:
            flash('Please log in to access Detect Archives.', 'warning')
            return redirect(url_for('login'))
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            flash('Access denied. This page is not available for Guest users.', 'error')
            return redirect(url_for('home'))
        daily_counts = get_daily_match_counts()
        return render_template('detect_archives.html',
                               daily_counts=daily_counts,
                               current_path='/detect/archives')

    @app.route('/api/toggle_flag', methods=['POST'])
    def toggle_flag():
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        elif session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
            
        data = request.json
        result_id = data.get('id')
        flag_value = data.get('flag')
        
        if update_cross_match_flag(result_id, flag_value):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Database error'})
