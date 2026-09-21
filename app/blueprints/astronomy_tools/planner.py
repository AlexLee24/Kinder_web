"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — planner (split from astronomy_tools_routes.py)."""
import os
import re
import ephem
import uuid
import pytz
import numpy as np
from flask import render_template, request, jsonify
from app.services.planning import obsplan as obs
from app.services.planning.observation_script import get_followup_targets_json, process_observation_request
import logging

logger = logging.getLogger(__name__)
from . import astronomy_tools_bp
from .helpers import _PLANNERS_OV_PLOT_DIR


@astronomy_tools_bp.route('/observation_planner')
def observation_planner():
    return render_template('observation_planner.html', current_path='/observation_planner')

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

@astronomy_tools_bp.route("/generate_plot", methods=["POST"])
def generate_plot():
    try:
        target_list = []
        plot_folder = _PLANNERS_OV_PLOT_DIR
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
            date = date.replace("-", "").replace("/", "")
            if len(date) != 8:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD or YYYY/MM/DD'}), 400
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
        
        plot_url = f"/ov_plot/{unique_filename}"
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

# ===============================================================================
# INTERACTIVE VISIBILITY PLANNER
# ===============================================================================
@astronomy_tools_bp.route('/interactive_planner')
def interactive_planner():
    return render_template('interactive_planner.html', current_path='/interactive_planner')

@astronomy_tools_bp.route('/api/visibility_data', methods=['POST'])
def visibility_data():
    """
    Compute visibility data for targets and return JSON for client-side plotting.
    Returns altitude/azimuth arrays, sun/moon tracks, twilight times, etc.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        date = data.get('date')
        location = data.get('location')
        timezone_offset = data.get('timezone')
        targets = data.get('targets', [])
        observer_name = data.get('telescope', 'Observer')
        n_steps = min(int(data.get('n_steps', 300)), 500)

        if not date or not location or timezone_offset is None:
            return jsonify({'error': 'date, location, timezone are required'}), 400

        # Parse timezone
        try:
            timezone_int = int(timezone_offset)
            timezone_name = obs.get_timezone_name(timezone_int)
            if timezone_name is None:
                return jsonify({'error': f'Unsupported timezone offset: {timezone_int}'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid timezone offset'}), 400

        # Parse location
        try:
            location_parts = location.split()
            if len(location_parts) != 3:
                return jsonify({'error': 'Location must have lon, lat, alt'}), 400
            longitude = parse_coordinate(location_parts[0])
            latitude = parse_coordinate(location_parts[1])
            altitude = float(location_parts[2])
            obs_site = obs.create_ephem_observer(observer_name, longitude, latitude, altitude)
        except Exception as e:
            return jsonify({'error': f'Invalid location: {str(e)}'}), 400

        # Parse date and create observation window (local 17:00 to next day 09:00)
        try:
            date_clean = date.replace('-', '').replace('/', '')
            if len(date_clean) != 8:
                return jsonify({'error': 'Invalid date format'}), 400
            next_date = str(int(date_clean) + 1)
            obs_date_fmt = f"{date_clean[:4]}/{date_clean[4:6]}/{date_clean[6:]}"
            next_date_fmt = f"{next_date[:4]}/{next_date[4:6]}/{next_date[6:]}"
            obs_start_ephem = ephem.Date(f'{obs_date_fmt} 17:00:00')
            obs_end_ephem = ephem.Date(f'{next_date_fmt} 09:00:00')
            obs_start_local = obs.dt_naive_to_dt_aware(obs_start_ephem.datetime(), timezone_name)
            obs_end_local = obs.dt_naive_to_dt_aware(obs_end_ephem.datetime(), timezone_name)
            obs_start = ephem.Date(obs_start_local.astimezone(pytz.utc))
            obs_end = ephem.Date(obs_end_local.astimezone(pytz.utc))
        except Exception as e:
            return jsonify({'error': f'Date processing error: {str(e)}'}), 400

        # Generate time array
        times_ephem = np.linspace(float(obs_start), float(obs_end), n_steps)
        times_iso = [ephem.Date(t).datetime().strftime('%Y-%m-%dT%H:%M:%S') for t in times_ephem]

        # Compute local times
        tz_obj = pytz.timezone(timezone_name)
        utc_tz = pytz.utc
        times_local_iso = []
        for t in times_ephem:
            dt_utc = ephem.Date(t).datetime().replace(tzinfo=utc_tz)
            dt_local = dt_utc.astimezone(tz_obj)
            times_local_iso.append(dt_local.strftime('%Y-%m-%dT%H:%M:%S'))

        # Compute sun track
        sun_alts = []
        for t in times_ephem:
            obs_site.date = t
            sun = ephem.Sun()
            sun.compute(obs_site)
            sun_alts.append(round(float(sun.alt) * 180 / np.pi, 2))

        # Compute moon track + phase
        moon_alts = []
        for t in times_ephem:
            obs_site.date = t
            moon = ephem.Moon()
            moon.compute(obs_site)
            moon_alts.append(round(float(moon.alt) * 180 / np.pi, 2))

        mean_time = (float(obs_start) + float(obs_end)) / 2.0
        moon_phase = round(obs.compute_moonphase(ephem.Date(mean_time), return_fmt='percent'), 1)

        # Compute twilight times (return both UTC and local)
        try:
            sunset, t_civil, t_naut, t_astro = obs.calculate_twilight_times(obs_site, ephem.Date(mean_time))
            def ephem_to_utc_iso(ed):
                return ephem.Date(ed).datetime().strftime('%Y-%m-%dT%H:%M:%S')
            def ephem_to_local_iso(ed):
                dt_utc = ephem.Date(ed).datetime().replace(tzinfo=utc_tz)
                dt_local = dt_utc.astimezone(tz_obj)
                return dt_local.strftime('%Y-%m-%dT%H:%M:%S')
            twilight_utc = {
                'sunset': [ephem_to_utc_iso(sunset[0]), ephem_to_utc_iso(sunset[1])],
                'civil': [ephem_to_utc_iso(t_civil[0]), ephem_to_utc_iso(t_civil[1])],
                'nautical': [ephem_to_utc_iso(t_naut[0]), ephem_to_utc_iso(t_naut[1])],
                'astronomical': [ephem_to_utc_iso(t_astro[0]), ephem_to_utc_iso(t_astro[1])]
            }
            twilight_local = {
                'sunset': [ephem_to_local_iso(sunset[0]), ephem_to_local_iso(sunset[1])],
                'civil': [ephem_to_local_iso(t_civil[0]), ephem_to_local_iso(t_civil[1])],
                'nautical': [ephem_to_local_iso(t_naut[0]), ephem_to_local_iso(t_naut[1])],
                'astronomical': [ephem_to_local_iso(t_astro[0]), ephem_to_local_iso(t_astro[1])]
            }
        except Exception:
            twilight_utc = None
            twilight_local = None

        # Compute moon rise/set
        try:
            moontimes = obs.calculate_moon_times(obs_site, obs_start, outtype='dt')
            mr_utc = moontimes[0].replace(tzinfo=utc_tz)
            ms_utc = moontimes[1].replace(tzinfo=utc_tz)
            moon_info = {
                'rise_utc': mr_utc.strftime('%H:%M'),
                'set_utc': ms_utc.strftime('%H:%M'),
                'rise_local': mr_utc.astimezone(tz_obj).strftime('%H:%M'),
                'set_local': ms_utc.astimezone(tz_obj).strftime('%H:%M'),
                'phase': moon_phase
            }
        except Exception:
            moon_info = {'rise_utc': '--', 'set_utc': '--', 'rise_local': '--', 'set_local': '--', 'phase': moon_phase}

        # Compute each target
        targets_data = []
        for i, target in enumerate(targets):
            if not isinstance(target, dict):
                continue
            name = target.get('name', f'Target_{i+1}')
            ra = target.get('ra', '')
            dec = target.get('dec', '')
            if not ra or not dec:
                continue

            try:
                # Parse RA — support decimal degrees (e.g. 186.234) or H:M:S / HhMmSs formats
                ra_str = str(ra).strip()
                if not any(c in ra_str for c in [':', 'h', 'H']):
                    try:
                        ra_deg = float(ra_str)
                        ra_h = ra_deg / 15.0
                        _h = int(ra_h); _m = int((ra_h - _h) * 60); _s = ((ra_h - _h) * 60 - _m) * 60
                        ra_clean = f"{_h}:{_m:02d}:{_s:05.2f}"
                    except ValueError:
                        ra_clean = ra_str
                else:
                    ra_clean = re.sub(r"[hH]", ":", ra_str)
                    ra_clean = re.sub(r"[mM]", ":", ra_clean)
                    ra_clean = re.sub(r"[sS]", "", ra_clean).strip()

                # Parse Dec — support decimal degrees (e.g. -12.345) or D:M:S / DdMmSs formats
                dec_str = str(dec).strip()
                dec_core = dec_str.lstrip('+-')
                if not any(c in dec_core for c in [':', 'd', 'D', '\u00b0']):
                    try:
                        dec_deg = float(dec_str)
                        sign = '-' if dec_deg < 0 else ''
                        dec_abs = abs(dec_deg)
                        _d = int(dec_abs); _m = int((dec_abs - _d) * 60); _s = ((dec_abs - _d) * 60 - _m) * 60
                        dec_clean = f"{sign}{_d}:{_m:02d}:{_s:05.2f}"
                    except ValueError:
                        dec_clean = dec_str
                else:
                    dec_clean = re.sub(r"[dD\u00b0]", ":", dec_str)
                    dec_clean = re.sub(r"[mM\u2032']", ":", dec_clean)
                    dec_clean = re.sub(r"[sS\u2033\"]", "", dec_clean).strip()

                ephem_target = obs.create_ephem_target(name, ra_clean, dec_clean)
            except Exception:
                continue

            alts = []
            azs = []
            tmp_obs = obs_site.copy()
            tmp_tar = ephem_target.copy()
            for t in times_ephem:
                tmp_obs.date = t
                tmp_tar.compute(tmp_obs)
                alts.append(round(float(tmp_tar.alt) * 180 / np.pi, 2))
                azs.append(round(float(tmp_tar.az) * 180 / np.pi, 2))

            # Transit time
            try:
                transit_str = obs.calculate_transit_time_single(
                    ephem_target, obs_site, ephem.Date(mean_time), mode='nearest', return_fmt='str'
                )
                # Convert transit UTC to local
                try:
                    from datetime import datetime as _dt
                    transit_dt_utc = _dt.strptime(transit_str, '%Y/%m/%d %H:%M:%S').replace(tzinfo=pytz.utc)
                    transit_local_str = transit_dt_utc.astimezone(tz_obj).strftime('%Y/%m/%d %H:%M:%S')
                except Exception:
                    transit_local_str = transit_str
            except Exception:
                transit_str = ''
                transit_local_str = ''

            # Moon separation at transit
            try:
                moon_sep = round(obs.moonsep_single(ephem_target, obs_site, ephem.Date(mean_time)), 1)
            except Exception:
                moon_sep = None

            targets_data.append({
                'name': name,
                'ra': ra,
                'dec': dec,
                'ra_deg': float(ephem_target._ra) * 180.0 / np.pi,
                'altitudes': alts,
                'azimuths': azs,
                'transit_time_utc': transit_str,
                'transit_time_local': transit_local_str,
                'moon_separation': moon_sep
            })

        # Order targets by RA (ascending) and number them accordingly, so the
        # plot legend/labels and the target list stay in a consistent order.
        targets_data.sort(key=lambda t: t['ra_deg'])
        for i, t in enumerate(targets_data):
            t['number'] = i + 1
            del t['ra_deg']

        return jsonify({
            'success': True,
            'times_utc': times_iso,
            'times_local': times_local_iso,
            'timezone_name': timezone_name,
            'timezone_offset': timezone_int,
            'sun_alts': sun_alts,
            'moon_alts': moon_alts,
            'moon_info': moon_info,
            'twilight_utc': twilight_utc,
            'twilight_local': twilight_local,
            'targets': targets_data,
            'obs_date': obs_date_fmt
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@astronomy_tools_bp.route('/astronomy_tools/get_followup_targets', methods=['GET'])
def get_followup_targets_route():
    try:
        data = get_followup_targets_json()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@astronomy_tools_bp.route('/astronomy_tools/generate_script', methods=['POST'])
def generate_script_route():
    try:
        data = request.get_json()
        script = process_observation_request(data)
        return jsonify({'success': True, 'script': script})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@astronomy_tools_bp.route('/astronomy_tools/generate_trigger_script', methods=['POST'])
def generate_trigger_script_route():
    """Build the Daily Trigger ACP script message (trigger_script.py format)."""
    data = request.get_json() or {}
    telescope = data.get('telescope', 'SLT')
    targets = data.get('targets', [])
    target_names = [t.get('name') for t in targets if isinstance(t, dict)]
    logger.info('generate_trigger_script: telescope=%s targets=%s', telescope, target_names)

    if not isinstance(targets, list) or not targets:
        logger.warning('generate_trigger_script: rejected — no targets provided (telescope=%s)', telescope)
        return jsonify({'success': False, 'error': 'No targets provided'}), 400

    try:
        from app.services.planning import trigger_script
        script = trigger_script.generate_full_script(targets, telescope)
        logger.info('generate_trigger_script: ok telescope=%s targets=%d script_chars=%d',
                    telescope, len(targets), len(script))
        return jsonify({'success': True, 'script': script})
    except Exception as e:
        logger.exception('generate_trigger_script: failed telescope=%s targets=%s', telescope, target_names)
        return jsonify({'success': False, 'error': str(e)}), 500

# ===============================================================================
# TARGET AUTOCOMPLETE (for visibility planner)
# ===============================================================================
@astronomy_tools_bp.route('/api/target_autocomplete')
def target_autocomplete():
    """Quick DB search returning name/ra/dec for autocomplete."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    try:
        from app.db.transient import search_tns_objects
        rows = search_tns_objects(search_term=q, limit=10)
        out = []
        for r in rows:
            prefix = r.get('name_prefix', '') or ''
            name   = (prefix + (r.get('name', '') or '')).strip()
            ra     = r.get('ra', '')
            dec    = r.get('declination', '')
            if not name or ra is None or dec is None:
                continue
            out.append({
                'name': name,
                'ra':   str(ra),
                'dec':  str(dec),
                'type': str(r.get('type', '') or prefix or ''),
                'mag':  str(r.get('discoverymag', '') or ''),
                'internal_names': str(r.get('internal_names', '') or ''),
            })
        return jsonify(out)
    except Exception as e:
        return jsonify([])
