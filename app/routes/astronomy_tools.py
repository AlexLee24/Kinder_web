"""
Astronomy tools routes for the Kinder web application.
"""
import os
import re
import ephem
import uuid
from flask import render_template, request, jsonify, session

from modules.astronomy_calculator import calculate_redshift_distance, calculate_absolute_magnitude
from modules.date_converter import convert_mjd_to_date, convert_jd_to_date, convert_common_date_to_jd
from modules.coordinate_converter import (
    convert_ra_hms_to_decimal, convert_ra_decimal_to_hms,
    convert_dec_dms_to_decimal, convert_dec_decimal_to_dms
)
from modules import obsplan as obs


def register_astronomy_routes(app):
    """Register astronomy tools routes with the Flask app"""
    
    # ===============================================================================
    # ASTRONOMY TOOLS
    # ===============================================================================
    @app.route('/astronomy_tools')
    def astronomy_tools():
        return render_template('astronomy_tools.html', current_path='/astronomy_tools')
    
    @app.route('/mount_torque')
    def mount_torque():
        return render_template('mount_torque.html', current_path='/mount_torque')

    @app.route('/calculate_redshift', methods=['POST'])
    def calculate_redshift():
        try:
            data = request.get_json()
            redshift = float(data.get('redshift', 0))
            redshift_error = float(data.get('redshift_error')) if data.get('redshift_error') else None
            
            result = calculate_redshift_distance(redshift, redshift_error)
            return jsonify({'success': True, 'result': result})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/calculate_absolute_magnitude', methods=['POST'])
    def calculate_absolute_magnitude_route():
        try:
            data = request.get_json()
            apparent_magnitude = float(data.get('apparent_magnitude'))
            redshift = float(data.get('redshift'))
            extinction = float(data.get('extinction', 0))
            
            result = calculate_absolute_magnitude(apparent_magnitude, redshift, extinction)
            return jsonify({'success': True, 'result': result})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/convert_date', methods=['POST'])
    def convert_date():
        try:
            data = request.get_json()
            mjd = data.get('mjd')
            jd = data.get('jd')
            common_date = data.get('common_date')
            
            if mjd:
                result = convert_mjd_to_date(float(mjd))
            elif jd:
                result = convert_jd_to_date(float(jd))
            elif common_date:
                result = convert_common_date_to_jd(common_date)
            else:
                return jsonify({'error': 'Please provide at least one date value'}), 400
            
            return jsonify({'success': True, 'result': result})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/convert_ra', methods=['POST'])
    def convert_ra():
        try:
            data = request.get_json()
            ra_hms = data.get('ra_hms')
            ra_decimal = data.get('ra_decimal')
            
            if ra_hms:
                result = convert_ra_hms_to_decimal(ra_hms)
            elif ra_decimal is not None:
                result = convert_ra_decimal_to_hms(float(ra_decimal))
            else:
                return jsonify({'error': 'Please provide either HMS or decimal value'}), 400
            
            return jsonify({'success': True, 'result': result})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/convert_dec', methods=['POST'])
    def convert_dec():
        try:
            data = request.get_json()
            dec_dms = data.get('dec_dms')
            dec_decimal = data.get('dec_decimal')
            
            if dec_dms:
                result = convert_dec_dms_to_decimal(dec_dms)
            elif dec_decimal is not None:
                result = convert_dec_decimal_to_dms(float(dec_decimal))
            else:
                return jsonify({'error': 'Please provide either DMS or decimal value'}), 400
            
            return jsonify({'success': True, 'result': result})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    # ===============================================================================
    # OBSERVATION PLANNING
    # ===============================================================================
    @app.route('/object_plot.html')
    @app.route('/object_plot')
    def object_plot():
        return render_template('object_plot.html', current_path='/object_plot.html')

    @app.route('/telescope_simulator')
    def telescope_simulator():
        return render_template('telescope_simulator.html', current_path='/telescope_simulator')

    def enforce_max_files(folder, max_files):
        """Create folder if it doesn't exist and clean old files"""
        try:
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
                return
            
            try:
                all_items = os.listdir(folder)
                files = [os.path.join(folder, f) for f in all_items 
                        if os.path.isfile(os.path.join(folder, f))]
            except OSError as e:
                return
            
            if len(files) > max_files:
                try:
                    files.sort(key=os.path.getmtime)  
                    files_to_delete = files[:len(files) - max_files]
                    
                    for file_path in files_to_delete:
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                            
                except Exception:
                    pass
                    
        except Exception:
            raise

    def parse_coordinate(coord_str):
        """Parse coordinate in degrees:minutes:seconds format to decimal degrees"""
        parts = coord_str.split(':')
        if len(parts) != 3:
            return float(coord_str)
        
        degrees = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        
        sign = 1 if degrees >= 0 else -1
        decimal = abs(degrees) + minutes/60.0 + seconds/3600.0
        return sign * decimal

    @app.route("/generate_plot", methods=["POST"])
    def generate_plot():
        try:
            target_list = []
            plot_folder = os.path.join(app.root_path, "static", "ov_plot")
            unique_filename = f"observing_tracks_{uuid.uuid4().hex}.jpg"
            
            try:
                enforce_max_files(plot_folder, max_files=10)
            except Exception as e:
                return jsonify({'error': f'Failed to prepare plot folder: {str(e)}'}), 500
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            date = data.get("date")
            observer = data.get("telescope", "Observer")
            location = data.get("location")
            timezone = data.get("timezone")
            targets = data.get("targets")
            
            if not date:
                return jsonify({'error': 'Date is required'}), 400
            if not location:
                return jsonify({'error': 'Location is required'}), 400
            if not targets or not isinstance(targets, list):
                return jsonify({'error': 'Targets list is required'}), 400
            if not timezone:
                return jsonify({'error': 'Timezone is required'}), 400
            
            try:
                date = date.replace("-", "")
                if len(date) != 8:
                    return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            except Exception as e:
                return jsonify({'error': f'Date processing error: {str(e)}'}), 400
            
            try:
                timezone_int = int(timezone)
                timezone_name = obs.get_timezone_name(timezone_int)
            except (ValueError, TypeError) as e:
                return jsonify({'error': f'Invalid timezone: {str(e)}'}), 400
            except Exception as e:
                return jsonify({'error': f'Timezone processing error: {str(e)}'}), 400
            
            for i, target in enumerate(targets):
                if not isinstance(target, dict):
                    return jsonify({'error': f'Invalid target format at index {i}'}), 400
                
                name = target.get('object_name', f'Target_{i+1}')
                ra = target.get('ra')
                dec = target.get('dec')
                
                if not ra or not dec:
                    return jsonify({'error': f'RA and Dec are required for target {name}'}), 400
                
                try:
                    ra_clean = re.sub(r"[hH]", ":", str(ra))
                    ra_clean = re.sub(r"[mM]", ":", ra_clean)
                    ra_clean = re.sub(r"[sS]", "", ra_clean).strip()
                    
                    dec_clean = re.sub(r"[dD°]", ":", str(dec))
                    dec_clean = re.sub(r"[mM′']", ":", dec_clean)
                    dec_clean = re.sub(r"[sS″\"]", "", dec_clean).strip()
                    
                    ephem_target = obs.create_ephem_target(name, ra_clean, dec_clean)
                    target_list.append(ephem_target)
                    
                except Exception as e:
                    return jsonify({'error': f'Invalid coordinates for target {name}: {str(e)}'}), 400
            
            try:
                location_parts = location.split()
                if len(location_parts) != 3:
                    return jsonify({'error': 'Location must have longitude, latitude, and altitude (space-separated)'}), 400
                
                longitude_str, latitude_str, altitude_str = location_parts
                
                longitude = parse_coordinate(longitude_str)
                latitude = parse_coordinate(latitude_str)
                altitude = float(altitude_str)
                
                obs_site = obs.create_ephem_observer(observer, longitude, latitude, altitude)
                
            except (ValueError, TypeError, IndexError) as e:
                return jsonify({'error': f'Invalid location format: {str(e)}'}), 400
            
            try:
                obs_date = str(int(date))
                next_obs_date = str(int(date) + 1)
                
                obs_date_formatted = f"{obs_date[:4]}/{obs_date[4:6]}/{obs_date[6:]}"
                next_obs_date_formatted = f"{next_obs_date[:4]}/{next_obs_date[4:6]}/{next_obs_date[6:]}"
                
                obs_start = ephem.Date(f'{obs_date_formatted} 17:00:00')
                obs_end = ephem.Date(f'{next_obs_date_formatted} 09:00:00')
                
                obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), timezone_name)
                obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), timezone_name)
                
            except Exception as e:
                return jsonify({'error': f'Error processing dates: {str(e)}'}), 400
            
            plot_path = os.path.join(plot_folder, unique_filename)
            
            try:
                obs.plot_night_observing_tracks(
                    target_list, obs_site, obs_start_local_dt, obs_end_local_dt, 
                    simpletracks=True, toptime='local', timezone='calculate', 
                    n_steps=1000, savepath=plot_path
                )
                
            except Exception as e:
                return jsonify({'error': f'Error generating plot: {str(e)}'}), 500
            
            if not os.path.exists(plot_path):
                return jsonify({'error': 'Plot generation failed - file not created'}), 500
            
            plot_url = f"/static/ov_plot/{unique_filename}"
            success_message = f"Successfully generated plot for {len(target_list)} targets"
            
            return jsonify({
                "success": True, 
                "plot_url": plot_url,
                "message": success_message
            })
            
        except Exception as e:
            error_message = f"Unexpected error in generate_plot: {str(e)}"
            import traceback
            traceback.print_exc()
            return jsonify({'error': error_message}), 500
