"""
Astronomy tools routes for the Kinder web application.
"""
import os
import re
import io
import json
import traceback
import base64
import ephem
import uuid
import time
import pytz
import numpy as np
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Ellipse, Polygon
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from flask import render_template, request, jsonify, session, abort, redirect, url_for
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.vizier import Vizier

from modules.astronomy_calculator import calculate_redshift_distance, calculate_absolute_magnitude
from modules.date_converter import convert_mjd_to_date, convert_jd_to_date, convert_common_date_to_jd
from modules.coordinate_converter import (
    convert_ra_hms_to_decimal, convert_ra_decimal_to_hms,
    convert_dec_dms_to_decimal, convert_dec_decimal_to_dms
)
from modules import obsplan as obs
from modules.observation_script import get_followup_targets_json, process_observation_request


from flask import Blueprint
astronomy_tools_bp = Blueprint('astronomy_tools', __name__, template_folder='templates', static_folder='static')
"""Register astronomy tools routes with the Flask app"""

# ===============================================================================
# ASTRONOMY TOOLS
# ===============================================================================
@astronomy_tools_bp.route('/astronomy_tools')
def astronomy_tools():
    return render_template('astronomy_tools.html', current_path='/astronomy_tools')

@astronomy_tools_bp.route('/observation_planner')
def observation_planner():
    return render_template('observation_planner.html', current_path='/observation_planner')

@astronomy_tools_bp.route('/mount_torque')
def mount_torque():
    return render_template('mount_torque.html', current_path='/mount_torque')

@astronomy_tools_bp.route('/mount_3d')
def mount_3d():
    return render_template('mount_3d.html', current_path='/mount_3d')

@astronomy_tools_bp.route('/lc_plotter')
def lc_plotter():
    from modules.filter_colors import all_colors
    from flask import session as flask_session
    user_email = flask_session.get('user', {}).get('email', '')
    return render_template('lc_plotter.html', current_path='/lc_plotter',
                           filter_colors=all_colors(), user_email=user_email)

@astronomy_tools_bp.route('/lc_plotter/mw_extinction', methods=['POST'])
def lc_plotter_mw_extinction():
    """Return per-filter Milky Way extinction A using SFD E(B-V) + SF11 ratios."""
    data = request.get_json(silent=True) or {}
    ra  = data.get('ra')
    dec = data.get('dec')
    filters = data.get('filters', [])
    if ra is None or dec is None:
        return jsonify({'error': 'ra and dec required'}), 400
    try:
        ra = float(ra); dec = float(dec)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid ra/dec'}), 400
    if not (0 <= ra <= 360) or not (-90 <= dec <= 90):
        return jsonify({'error': 'ra/dec out of range'}), 400
    from modules.ext_M_calculator import get_extinction
    result = {}
    for f in filters[:60]:
        if not isinstance(f, str) or len(f) > 20:
            continue
        try:
            result[f] = round(float(get_extinction(ra, dec, f)), 4)
        except Exception:
            result[f] = None
    return jsonify(result)

_SHARE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'shared_plots')
_SHARE_ID_RE = re.compile(r'^[a-f0-9]{24}$')
_SHARE_TTL_SECS = 60 * 86400  # 60 days

@astronomy_tools_bp.route('/lc_plotter/share', methods=['POST'])
def lc_plotter_share():
    if request.content_length and request.content_length > 8 * 1024 * 1024:
        return jsonify({'error': 'Payload too large'}), 413
    payload = request.get_json(silent=True)
    if not payload or 'traces' not in payload or 'layout' not in payload:
        return jsonify({'error': 'Invalid payload'}), 400
    os.makedirs(_SHARE_DIR, exist_ok=True)
    share_id = uuid.uuid4().hex[:24]
    path = os.path.join(_SHARE_DIR, f'{share_id}.json')
    raw_pw = (payload.get('password') or '').strip()
    pw_hash = generate_password_hash(raw_pw) if raw_pw else None
    with open(path, 'w') as f:
        json.dump({
            'traces': payload['traces'],
            'layout': payload['layout'],
            'isStatic': bool(payload.get('isStatic', False)),
            'created_at': time.time(),
            'password_hash': pw_hash,
        }, f)
    return jsonify({'id': share_id})

@astronomy_tools_bp.route('/lc_plotter/shared/<share_id>', methods=['GET', 'POST'])
def lc_plotter_shared(share_id):
    if not _SHARE_ID_RE.match(share_id):
        abort(404)
    path = os.path.join(_SHARE_DIR, f'{share_id}.json')
    if not os.path.isfile(path):
        abort(404)
    with open(path) as f:
        data = json.load(f)
    # Check 60-day expiry
    if time.time() - data.get('created_at', 0) > _SHARE_TTL_SECS:
        abort(410)
    has_password = bool(data.get('password_hash'))
    session_key = f'lcp_unlock_{share_id}'
    if request.method == 'POST':
        if not has_password:
            abort(400)
        entered = request.form.get('password', '')
        if check_password_hash(data['password_hash'], entered):
            session[session_key] = True
            return redirect(url_for('astronomy_tools.lc_plotter_shared', share_id=share_id))
        return render_template('shared_plot.html',
                               traces=None, layout=None,
                               is_static=data.get('isStatic', False),
                               share_id=share_id,
                               has_password=True, password_error=True, unlocked=False)
    # GET
    if has_password and not session.get(session_key):
        return render_template('shared_plot.html',
                               traces=None, layout=None,
                               is_static=data.get('isStatic', False),
                               share_id=share_id,
                               has_password=True, password_error=False, unlocked=False)
    return render_template('shared_plot.html',
                           traces=data['traces'],
                           layout=data['layout'],
                           is_static=data.get('isStatic', False),
                           share_id=share_id,
                           has_password=has_password, password_error=False, unlocked=True)

@astronomy_tools_bp.route('/calculate_redshift', methods=['POST'])
def calculate_redshift():
    try:
        data = request.get_json()
        redshift = float(data.get('redshift', 0))
        redshift_error = float(data.get('redshift_error')) if data.get('redshift_error') else None
        
        result = calculate_redshift_distance(redshift, redshift_error)
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@astronomy_tools_bp.route('/calculate_absolute_magnitude', methods=['POST'])
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

@astronomy_tools_bp.route('/convert_date', methods=['POST'])
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

@astronomy_tools_bp.route('/convert_ra', methods=['POST'])
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

@astronomy_tools_bp.route('/convert_dec', methods=['POST'])
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

@astronomy_tools_bp.route('/telescope_simulator')
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

# Absolute path to planners/ov_plot/ (sibling blueprint folder)
_PLANNERS_OV_PLOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'planners', 'ov_plot')
)

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
                'altitudes': alts,
                'azimuths': azs,
                'transit_time_utc': transit_str,
                'transit_time_local': transit_local_str,
                'moon_separation': moon_sep
            })

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
        from modules.database.transient import search_tns_objects
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

# ===============================================================================
# FINDING CHART
# ===============================================================================
@astronomy_tools_bp.route('/finding_chart')
def finding_chart():
    return render_template('finding_chart.html', current_path='/finding_chart')

@astronomy_tools_bp.route('/api/finding_chart', methods=['POST'])
def generate_finding_chart():
    """
    Generate a finding chart PNG and return base64 encoded image.
    Fetches base image from DSS/DESI LS/Pan-STARRS, overlays
    target marker and nearby bright star annotations.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # ---- Parse parameters ----
        target_name = data.get('name', 'Target')
        ra_str = data.get('ra', '')
        dec_str = data.get('dec', '')
        survey = data.get('survey', 'DSS2 Red')
        fov_arcmin = float(data.get('fov', 10))
        invert = data.get('invert', False)
        mag_limit = float(data.get('mag_limit', 15.0))
        name_limit = float(data.get('name_limit', 10.0))
        show_mag   = data.get('show_mag', True)
        show_names = data.get('show_names', True)
        _ms = data.get('max_stars')
        max_stars  = int(_ms) if _ms else None
        show_slit       = data.get('show_slit', False)
        slit_length     = float(data.get('slit_length', 20.0))
        slit_width      = float(data.get('slit_width', 1.5))
        slit_pa         = float(data.get('slit_pa', 0.0))
        logs_pre = [f'[INFO] show_mag={show_mag}  show_names={show_names}  max_stars={max_stars}']

        # Resolve coordinates — auto-detect format
        def _parse_coord(ra_s, dec_s):
            """Try every sensible unit combination; return SkyCoord or raise."""
            ra_s  = str(ra_s).strip()
            dec_s = str(dec_s).strip()
            # Heuristic: if RA string is a plain decimal number (no colon / h / m)
            # it is degrees, not hourangle.
            import re as _re
            ra_is_decimal  = bool(_re.match(r'^[+-]?[\d]+\.?[\d]*$', ra_s))
            dec_is_decimal = bool(_re.match(r'^[+-]?[\d]+\.?[\d]*$', dec_s))
            attempts = []
            if ra_is_decimal and dec_is_decimal:
                # Both plain numbers → degrees first
                attempts = [
                    (u.deg, u.deg),
                    (u.hourangle, u.deg),
                ]
            else:
                # Has colons / letters → HMS/DMS first
                attempts = [
                    (u.hourangle, u.deg),
                    (u.deg, u.deg),
                ]
            for ra_unit, dec_unit in attempts:
                try:
                    return SkyCoord(ra_s, dec_s, unit=(ra_unit, dec_unit))
                except Exception:
                    continue
            raise ValueError(f'Cannot parse coordinates: RA={ra_s!r} Dec={dec_s!r}')

        try:
            if ra_str or dec_str:
                coord = _parse_coord(ra_str, dec_str)
            else:
                coord = SkyCoord.from_name(target_name)
        except Exception:
            try:
                coord = SkyCoord.from_name(target_name)
            except Exception:
                return jsonify({'error': f'Cannot parse coordinates: RA={ra_str} Dec={dec_str}'}), 400

        ra_deg = coord.ra.deg
        dec_deg = coord.dec.deg

        logs = logs_pre
        logs.append(f'[INFO] Target: {target_name}  RA={ra_deg:.5f}  Dec={dec_deg:.5f}')
        logs.append(f'[INFO] Survey={survey}  FOV={fov_arcmin}\' Invert={invert}')

        # ---- Fetch base image ----
        img_data, fetch_logs = _fetch_survey_image(survey, ra_deg, dec_deg, fov_arcmin)
        logs.extend(fetch_logs)
        if img_data is None:
            logs.append(f'[ERROR] Failed to fetch image from {survey}')
            return jsonify({'error': f'Failed to fetch image from {survey}', 'logs': logs}), 500

        img = Image.open(io.BytesIO(img_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        logs.append(f'[OK] Image loaded: {img.size[0]}x{img.size[1]} px')

        if invert and 'color' not in survey.lower():
            img_arr = np.array(img)
            img_arr = 255 - img_arr
            img = Image.fromarray(img_arr)
            logs.append('[INFO] Image inverted')

        # ---- Query nearby bright stars from UCAC4 ----
        star_data, band_used, star_logs = _query_nearby_stars(ra_deg, dec_deg, fov_arcmin, mag_limit)
        logs.extend(star_logs)

        # ---- Render the finding chart ----
        png_b64 = _render_finding_chart(
            img, ra_deg, dec_deg, fov_arcmin, target_name,
            star_data, band_used, mag_limit, name_limit, invert, survey,
            show_mag=show_mag, show_names=show_names, max_stars=max_stars,
            show_slit=show_slit, slit_length=slit_length,
            slit_width=slit_width, slit_pa=slit_pa
        )
        logs.append('[OK] Chart rendered successfully')

        return jsonify({
            'success': True,
            'image': png_b64,
            'ra_deg': round(ra_deg, 6),
            'dec_deg': round(dec_deg, 6),
            'fov_arcmin': fov_arcmin,
            'logs': logs
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'logs': [f'[ERROR] {str(e)}']}), 500


def _derotate_fits(raw, header):
    """Read WCS rotation from FITS header and rotate image to North-up.
    Returns (rotated_array, angle_degrees_applied)."""
    angle_applied = 0.0
    try:
        import warnings
        from astropy.wcs import WCS, FITSFixedWarning
        from scipy.ndimage import rotate as nd_rotate
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FITSFixedWarning)
            wcs = WCS(header, naxis=2)
        ny, nx = raw.shape
        cx, cy = nx / 2.0, ny / 2.0
        # In a numpy array from astropy FITS, row index increases = moving North
        # (FITS pixel y increases = Dec increases for standard WCS)
        c_ra, c_dec = wcs.all_pix2world([[cx, cy]], 0)[0]
        n_ra, n_dec = wcs.all_pix2world([[cx, cy + 1]], 0)[0]
        delta_ra_sky = (n_ra - c_ra) * np.cos(np.radians(c_dec))
        delta_dec    = n_dec - c_dec
        # Angle from "up" to North; positive = image rotated CW on sky
        angle = np.degrees(np.arctan2(delta_ra_sky, delta_dec))
        if abs(angle) > 0.05:
            fill_val = float(np.nanmedian(raw[np.isfinite(raw)]))
            # FLIP_TOP_BOTTOM (applied after) inverts chirality, so negate angle here
            raw = nd_rotate(raw, -angle, reshape=False, cval=fill_val, order=1)
            angle_applied = angle
    except Exception as exc:
        pass  # fallback: no rotation
    return raw, angle_applied


def _fits_to_png(fits_data_2d, fits_header=None, use_zscale=False):
    """Normalize a 2-D float FITS array and return a PIL RGB image (N-up).
    use_zscale=True: ZScale interval + asinh stretch (DESI single-band).
    use_zscale=False: simple percentile linear stretch (DSS).
    If fits_header is provided, de-rotate to North-up before normalization.
    Returns (PIL Image, angle_degrees_applied)."""
    data = fits_data_2d.astype(float)
    angle_applied = 0.0
    if fits_header is not None:
        data, angle_applied = _derotate_fits(data, fits_header)

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        out = np.zeros_like(data, dtype=np.uint8)
    elif use_zscale:
        try:
            from astropy.visualization import ZScaleInterval, AsinhStretch, ImageNormalize
            # contrast=0.35: moderate dynamic range; a=0.5: gentle non-linearity
            norm = ImageNormalize(finite, interval=ZScaleInterval(contrast=0.25),
                                  stretch=AsinhStretch(a=1.0))
            out = np.clip(norm(data) * 255, 0, 255).astype(np.uint8)
        except Exception:
            vmin = np.percentile(finite, 2.0)
            vmax = np.percentile(finite, 98.0)
            if vmax <= vmin:
                vmax = vmin + 1
            out = np.clip((data - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)
    else:
        # Linear stretch for DSS
        vmin = np.percentile(finite, 0.5)
        vmax = np.percentile(finite, 99.5)
        if vmax <= vmin:
            vmax = vmin + 1
        out = np.clip((data - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)

    img_pil = Image.fromarray(out, mode='L').convert('RGB')
    img_pil = img_pil.transpose(Image.FLIP_TOP_BOTTOM)  # FITS is South-up
    return img_pil, angle_applied


def _fetch_survey_image(survey, ra_deg, dec_deg, fov_arcmin):
    """Fetch cutout image bytes from the selected survey.
    Returns (bytes_or_None, list_of_log_strings)."""
    timeout = 45
    logs = []
    try:
        # ------------------------------------------------------------------ DSS
        if survey.startswith('DSS'):
            survey_map = {
                'DSS2 Red':  'poss2ukstu_red',
                'DSS2 Blue': 'poss2ukstu_blue',
                'DSS2 IR':   'poss2ukstu_ir',
                'DSS':       'poss1_red',
                'DSS1':      'poss1_red',
            }
            dss_name = survey_map.get(survey, 'poss2ukstu_red')
            url = (
                f'https://archive.stsci.edu/cgi-bin/dss_search'
                f'?v={dss_name}&r={ra_deg}&d={dec_deg}&e=J2000'
                f'&h={fov_arcmin}&w={fov_arcmin}&f=fits&c=gz&fov=NONE&v3='
            )
            logs.append(f'[DSS] GET {url[:80]}...')
            r = requests.get(url, timeout=timeout)
            logs.append(f'[DSS] HTTP {r.status_code}  size={len(r.content)} bytes')
            if r.status_code == 200:
                import gzip
                from astropy.io import fits as afits
                try:
                    fits_raw = gzip.decompress(r.content)
                except Exception:
                    fits_raw = r.content
                hdu = afits.open(io.BytesIO(fits_raw))
                img_pil, rot_ang = _fits_to_png(hdu[0].data, fits_header=hdu[0].header, use_zscale=False)
                logs.append(f'[DSS] WCS de-rotation applied: {rot_ang:.3f} deg')
                buf = io.BytesIO()
                img_pil.save(buf, format='PNG')
                return buf.getvalue(), logs
            logs.append(f'[DSS] ERROR: non-200 response')
            return None, logs

        # --------------------------------------------------------------- DESI LS
        elif survey.startswith('DESI'):
            layer = 'ls-dr10'
            pixscale = fov_arcmin * 60 / 900  # arcsec/pixel for 900 px
            if 'color' in survey:
                url = (
                    f'https://www.legacysurvey.org/viewer/cutout.jpg'
                    f'?ra={ra_deg}&dec={dec_deg}&size=900&layer={layer}&pixscale={pixscale:.4f}'
                )
                logs.append(f'[DESI] GET color JPG  pixscale={pixscale:.4f}"')
                r = requests.get(url, timeout=timeout)
                logs.append(f'[DESI] HTTP {r.status_code}  size={len(r.content)} bytes')
                return (r.content if r.status_code == 200 else None), logs
            else:
                band = survey.split('-')[-1].lower()
                url = (
                    f'https://www.legacysurvey.org/viewer/cutout.fits'
                    f'?ra={ra_deg}&dec={dec_deg}&size=900&layer={layer}'
                    f'&pixscale={pixscale:.4f}&bands={band}'
                )
                logs.append(f'[DESI] GET {band}-band FITS  pixscale={pixscale:.4f}"')
                r = requests.get(url, timeout=timeout)
                logs.append(f'[DESI] HTTP {r.status_code}  size={len(r.content)} bytes')
                if r.status_code == 200:
                    from astropy.io import fits as afits
                    hdu = afits.open(io.BytesIO(r.content))
                    raw = hdu[0].data
                    if raw.ndim == 3:
                        raw = raw[0]
                    img_pil, rot_ang = _fits_to_png(raw, fits_header=hdu[0].header, use_zscale=True)
                    logs.append(f'[DESI] WCS de-rotation applied: {rot_ang:.3f} deg')
                    buf = io.BytesIO()
                    img_pil.save(buf, format='PNG')
                    return buf.getvalue(), logs
                logs.append('[DESI] ERROR: non-200 response')
                return None, logs

        # ------------------------------------------------------------------ PS1
        elif survey.startswith('PS1'):
            size_px = 900
            # PS1 native resolution is 0.25"/pixel; size param in fitscut.cgi is native pixels
            src_px = max(240, int(fov_arcmin * 60 / 0.25))
            if 'color' in survey:
                filters = 'gri'
            else:
                filters = survey.split('-')[-1].lower()

            # Step 1: resolve actual image filenames
            fn_url = (
                f'https://ps1images.stsci.edu/cgi-bin/ps1filenames.py'
                f'?ra={ra_deg}&dec={dec_deg}&filters={filters}&type=stack'
            )
            logs.append(f'[PS1] Querying filenames: filters={filters}')
            fr = requests.get(fn_url, timeout=timeout)
            logs.append(f'[PS1] Filenames HTTP {fr.status_code}')
            if fr.status_code != 200 or not fr.text.strip():
                logs.append('[PS1] ERROR: filenames query failed')
                return None, logs

            lines = [l for l in fr.text.strip().split('\n') if l.strip()]
            if len(lines) < 2:
                logs.append('[PS1] ERROR: no images found at this position (outside PS1 footprint?)')
                return None, logs

            header = lines[0].split()
            rows = []
            for l in lines[1:]:
                parts = l.split()
                if len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))
            if not rows:
                logs.append('[PS1] ERROR: empty filename table')
                return None, logs

            file_map = {row.get('filter', ''): row.get('filename', '') for row in rows}
            logs.append(f'[PS1] Available bands: {list(file_map.keys())}')

            if 'color' in survey:
                r_f = file_map.get('r', file_map.get('i', ''))
                g_f = file_map.get('i', file_map.get('r', ''))
                b_f = file_map.get('g', '')
                if not all([r_f, g_f, b_f]):
                    logs.append(f'[PS1] ERROR: missing bands for color — {file_map}')
                    return None, logs
                cut_url = (
                    f'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
                    f'?ra={ra_deg}&dec={dec_deg}&size={src_px}&format=jpg'
                    f'&output_size={size_px}&red={r_f}&green={g_f}&blue={b_f}'
                )
                logs.append('[PS1] Fetching color cutout (JPG)')
                cr = requests.get(cut_url, timeout=timeout)
                logs.append(f'[PS1] Cutout HTTP {cr.status_code}  size={len(cr.content)} bytes')
                return (cr.content if cr.status_code == 200 else None), logs
            else:
                fname = file_map.get(filters, '')
                if not fname:
                    logs.append(f'[PS1] ERROR: band {filters} not available')
                    return None, logs
                cut_url = (
                    f'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
                    f'?ra={ra_deg}&dec={dec_deg}&size={src_px}&format=jpg'
                    f'&output_size={size_px}&red={fname}'
                )
                logs.append(f'[PS1] Fetching {filters}-band cutout (JPG, as grayscale red channel)')
                cr = requests.get(cut_url, timeout=timeout)
                logs.append(f'[PS1] Cutout HTTP {cr.status_code}  size={len(cr.content)} bytes')
                return (cr.content if cr.status_code == 200 else None), logs

        logs.append(f'[ERROR] Unknown survey: {survey}')
        return None, logs
    except Exception as e:
        traceback.print_exc()
        logs.append(f'[ERROR] Exception: {e}')
        return None, logs


def _query_nearby_stars(ra_deg, dec_deg, fov_arcmin, mag_limit):
    """Multi-catalog star query: Tycho-2 (bright) + UCAC4 (faint) + SIMBAD names.
    Returns (stars_list, dominant_band_str, logs_list)."""
    logs = []
    stars = {}  # key: (ra4, dec4) for spatial dedup
    coord  = SkyCoord(ra_deg, dec_deg, unit='deg')
    radius = (fov_arcmin / 2) * u.arcmin

    # ── 1. Tycho-2: complete to V~11.5, good for bright/saturated stars ──────
    try:
        tyc_lim = min(mag_limit, 13.0)
        logs.append(f'[Vizier] Querying Tycho-2  mag<{tyc_lim}  r={fov_arcmin/2:.1f}\'')
        v_tyc = Vizier(
            columns=['RAmdeg', 'DEmdeg', 'VTmag', 'BTmag', 'TYC1', 'TYC2', 'TYC3', 'HIP'],
            column_filters={'VTmag': f'<{tyc_lim}'},
            row_limit=400)
        res = v_tyc.query_region(coord, radius=radius, catalog='I/259/tyc2')
        n_tyc = 0
        if res and len(res) > 0:
            tbl  = res[0]
            cols = tbl.colnames
            for row in tbl:
                try:
                    vt = float(row['VTmag']) if 'VTmag' in cols else np.nan
                    bt = float(row['BTmag']) if 'BTmag' in cols else np.nan
                    if not np.isfinite(vt):
                        continue
                    # Standard Tycho → Johnson V: V = VT − 0.090*(BT−VT)
                    if np.isfinite(bt):
                        mag  = round(vt - 0.090 * (bt - vt), 2)
                        band = 'V'
                    else:
                        mag  = round(vt, 2)
                        band = 'VT'
                    if mag >= mag_limit:
                        continue
                    ra_s  = float(row['RAmdeg'])
                    dec_s = float(row['DEmdeg'])
                    try:
                        hip_val = float(row['HIP']) if 'HIP' in cols else np.nan
                        hip = str(int(hip_val)) if np.isfinite(hip_val) else ''
                    except Exception:
                        hip = ''
                    tyc_id = (f"TYC {row['TYC1']}-{row['TYC2']}-{row['TYC3']}"
                              if 'TYC1' in cols else '')
                    star_id = f'HIP {hip}' if hip else tyc_id
                    key = (round(ra_s, 4), round(dec_s, 4))
                    stars[key] = {'ra': ra_s, 'dec': dec_s, 'mag': mag,
                                  'band': band, 'id': star_id, 'name': ''}
                    n_tyc += 1
                except Exception:
                    continue
        logs.append(f'[Vizier] Tycho-2 found {n_tyc} stars')
    except Exception as e:
        logs.append(f'[Vizier] Tycho-2 ERROR: {e}')

    # ── 2. UCAC4: adds faint stars not covered by Tycho-2 ───────────────────
    PRIORITY   = [('V', 'Vmag'), ('r', 'rmag'), ('R', 'f.mag')]
    tycho_snap = list(stars.values())   # snapshot before UCAC4 loop
    n_ucac     = 0
    try:
        logs.append(f'[Vizier] Querying UCAC4  mag<{mag_limit}  r={fov_arcmin/2:.1f}\'')
        v_uc = Vizier(columns=['RAJ2000', 'DEJ2000', 'Vmag', 'rmag', 'f.mag', 'UCAC4'],
                      row_limit=500)
        res_uc = v_uc.query_region(coord, radius=radius, catalog='I/322A')
        if res_uc and len(res_uc) > 0:
            tbl   = res_uc[0]
            acols = tbl.colnames
            for row in tbl:
                try:
                    chosen_mag, chosen_label = None, None
                    for label, col in PRIORITY:
                        if col in acols:
                            try:
                                raw = row[col]
                                # Skip masked / None values before float()
                                if hasattr(raw, '_fill_value') or raw is None:
                                    continue
                                val = float(raw)
                                if np.isfinite(val) and val < mag_limit:
                                    chosen_mag = round(val, 2)
                                    chosen_label = label
                                    break
                            except (ValueError, TypeError):
                                continue
                    if chosen_mag is None:
                        continue
                    ra_s  = float(row['RAJ2000'])
                    dec_s = float(row['DEJ2000'])
                    cos_d = np.cos(np.radians(dec_s))
                    # Skip if within 3" of any Tycho-2 star (already covered)
                    matched = any(
                        ((ra_s - ev['ra']) * cos_d)**2 + (dec_s - ev['dec'])**2 < (3/3600)**2
                        for ev in tycho_snap
                    )
                    if not matched:
                        key = (round(ra_s, 4), round(dec_s, 4))
                        stars[key] = {
                            'ra': ra_s, 'dec': dec_s,
                            'mag': chosen_mag, 'band': chosen_label,
                            'id': str(row['UCAC4']) if 'UCAC4' in acols else '',
                            'name': '',
                        }
                        n_ucac += 1
                except Exception:
                    continue
        logs.append(f'[Vizier] UCAC4 added {n_ucac}  total={len(stars)}')
    except Exception as e:
        logs.append(f'[Vizier] UCAC4 ERROR: {e}')

    # ── 3. SIMBAD: fetch common names for matched stars ──────────────────────
    try:
        from astroquery.simbad import Simbad
        sim = Simbad()
        sim.TIMEOUT = 25
        logs.append(f'[SIMBAD] Querying names  r={fov_arcmin/2:.1f}\'')
        sim_res = sim.query_region(coord, radius=radius)
        if sim_res is not None and len(sim_res) > 0:
            n_named = 0
            star_list_snap = list(stars.items())
            for row in sim_res:
                try:
                    sc = SkyCoord(ra=str(row['RA']), dec=str(row['DEC']),
                                  unit=(u.hourangle, u.deg))
                    s_ra, s_dec = sc.ra.deg, sc.dec.deg
                except Exception:
                    continue
                main_id = str(row['MAIN_ID']).strip()
                # Clean prefixes: "* ", "V* ", "** " → Bayer/Flamsteed/proper name
                clean = re.sub(r'^(V\*|\*\*|\*)\s*', '', main_id).strip()
                if not clean:
                    clean = main_id
                cos_d = np.cos(np.radians(s_dec))
                best_key, best_d2 = None, (5 / 3600) ** 2   # 5" threshold
                for k, sv in star_list_snap:
                    d2 = ((sv['ra'] - s_ra) * cos_d)**2 + (sv['dec'] - s_dec)**2
                    if d2 < best_d2:
                        best_d2, best_key = d2, k
                if best_key is not None:
                    stars[best_key]['name'] = clean
                    n_named += 1
            logs.append(f'[SIMBAD] Named {n_named} stars')
    except Exception as e:
        logs.append(f'[SIMBAD] WARN: {e}')

    star_list   = list(stars.values())
    band_counts = {}
    for s in star_list:
        band_counts[s['band']] = band_counts.get(s['band'], 0) + 1
    dominant = max(band_counts, key=band_counts.get) if band_counts else 'V'
    logs.append(f'[Stars] Total {len(star_list)}  bands={band_counts}')
    return star_list, dominant, logs


def _render_finding_chart(img, ra_deg, dec_deg, fov_arcmin, target_name,
                          star_data, mag_band, mag_limit, name_limit, invert, survey,
                          show_mag=True, show_names=True, max_stars=None,
                          show_slit=False, slit_length=20.0, slit_width=1.5, slit_pa=0.0):
    """Render the finding chart with matplotlib and return base64 PNG."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=120)

    # Determine color scheme based on invert
    is_single_filter = survey not in ['DESI-color', 'PS1-color']
    if invert and is_single_filter:
        marker_color = 'red'
        text_color = 'black'
        star_color = 'blue'
        crosshair_color = 'red'
        compass_color = 'black'
    else:
        marker_color = '#00FF00'
        text_color = 'white'
        star_color = '#FFD700'
        crosshair_color = '#00FF00'
        compass_color = 'white'

    # cos(dec) correction: on sky, 1 arcmin in RA = 1/cos(dec) degrees
    cos_dec = np.cos(np.radians(dec_deg))
    cos_dec = max(cos_dec, 1e-6)  # guard near poles

    # Display image
    # The survey returns a square image (fov_arcmin x fov_arcmin on sky).
    # In RA/Dec degree space, the RA width = fov / cos(dec) because
    # 1 sky-arcmin in RA = (1/cos(dec)) degree of RA.
    half_fov_dec = fov_arcmin / 2.0 / 60.0          # degrees in Dec
    half_fov_ra  = half_fov_dec / cos_dec            # degrees in RA
    extent = [ra_deg + half_fov_ra, ra_deg - half_fov_ra,
              dec_deg - half_fov_dec, dec_deg + half_fov_dec]
    ax.imshow(img, extent=extent, aspect='auto', origin='upper')
    # Set aspect so the sky image appears square on screen
    ax.set_aspect(1.0 / cos_dec)

    # Helper: sky_arcfrac -> RA-degree offset and Dec-degree offset
    # e.g. sky_frac(0.06) = 6% of fov in sky angular units
    def ra_off(sky_frac):
        return fov_arcmin / 60.0 * sky_frac / cos_dec

    def dec_off(sky_frac):
        return fov_arcmin / 60.0 * sky_frac

    # Crosshair on target
    ch_len = dec_off(0.06)
    ch_gap = dec_off(0.015)
    ra_ch_len = ra_off(0.06)
    ra_ch_gap = ra_off(0.015)
    ax.plot([ra_deg - ra_ch_gap, ra_deg - ra_ch_len], [dec_deg, dec_deg], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg + ra_ch_gap, ra_deg + ra_ch_len], [dec_deg, dec_deg], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg, ra_deg], [dec_deg - ch_gap, dec_deg - ch_len], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg, ra_deg], [dec_deg + ch_gap, dec_deg + ch_len], '-', color=crosshair_color, lw=1.5)

    # Circle around target (Ellipse because RA/Dec axes have different scales)
    circle_sky = dec_off(0.035)  # radius in sky degrees
    ell = Ellipse((ra_deg, dec_deg),
                  width=circle_sky / cos_dec * 2,
                  height=circle_sky * 2,
                  fill=False, edgecolor=crosshair_color, lw=1.5, ls='--')
    ax.add_patch(ell)

    # Target name label
    offset_dec = dec_off(0.05)
    ax.text(ra_deg, dec_deg + offset_dec, target_name,
            color=marker_color, fontsize=11, fontweight='bold',
            ha='center', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='black' if not invert else 'white',
                      alpha=0.6, edgecolor='none'))

    # Plot nearby stars
    # --- Slit overlay ---
    if show_slit:
        slit_color = '#FF6600' if not (invert and is_single_filter) else '#CC4400'
        pa_rad = np.radians(slit_pa)
        # Half dimensions in sky angular degrees
        hl = slit_length / 2.0 / 3600.0    # half-length
        hw = slit_width  / 2.0 / 3600.0    # half-width
        # Slit long-axis unit vector in (East_sky, North_sky):
        #   East = sin(PA), North = cos(PA)
        # Slit perp unit vector: (cos(PA), -sin(PA))
        sin_pa, cos_pa = np.sin(pa_rad), np.cos(pa_rad)
        # 4 corners in (East_sky_deg, North_sky_deg)
        corners_sky = [
            ( hl*sin_pa + hw*cos_pa,  hl*cos_pa - hw*sin_pa),
            ( hl*sin_pa - hw*cos_pa,  hl*cos_pa + hw*sin_pa),
            (-hl*sin_pa - hw*cos_pa, -hl*cos_pa + hw*sin_pa),
            (-hl*sin_pa + hw*cos_pa, -hl*cos_pa - hw*sin_pa),
        ]
        # Convert to RA/Dec: East offset / cos_dec = RA offset
        corners_radec = np.array(
            [(ra_deg + e / cos_dec, dec_deg + n) for e, n in corners_sky]
        )
        slit_poly = Polygon(corners_radec, closed=True, linewidth=2.0,
                            edgecolor=slit_color, facecolor=slit_color,
                            alpha=0.18, transform=ax.transData)
        ax.add_patch(slit_poly)
        slit_border = Polygon(corners_radec, closed=True, linewidth=2.0,
                              edgecolor=slit_color, facecolor='none',
                              transform=ax.transData)
        ax.add_patch(slit_border)
        # Center line along slit long axis
        ax.plot(
            [ra_deg - hl*sin_pa/cos_dec, ra_deg + hl*sin_pa/cos_dec],
            [dec_deg - hl*cos_pa,        dec_deg + hl*cos_pa],
            '-', color=slit_color, lw=0.8, alpha=0.7
        )
        # PA label near top of slit
        label_ra  = ra_deg + (hl + dec_off(0.04)) * sin_pa / cos_dec
        label_dec = dec_deg + (hl + dec_off(0.04)) * cos_pa
        ax.text(label_ra, label_dec,
                f'PA={slit_pa:.1f}°\n{slit_width}"×{slit_length}"',
                color=slit_color, fontsize=8, fontweight='bold',
                ha='center', va='bottom',
                bbox=dict(boxstyle='round,pad=0.18',
                          facecolor='black' if not (invert and is_single_filter) else 'white',
                          alpha=0.55, edgecolor='none'))

    visible_stars = sorted(star_data, key=lambda s: s['mag'])
    if max_stars is not None:
        visible_stars = visible_stars[:max_stars]

    for star in visible_stars:
        s_ra, s_dec, s_mag = star['ra'], star['dec'], star['mag']
        # Skip if too close to target (< 3 arcsec on sky)
        sep = np.sqrt(((s_ra - ra_deg) * cos_dec)**2 + (s_dec - dec_deg)**2) * 3600
        if sep < 3:
            continue

        # Star marker — skip if no annotation is shown at all
        if show_mag or show_names:
            msize = max(2, min(8, (mag_limit - s_mag) * 0.8))
            ax.plot(s_ra, s_dec, 'o', color=star_color, markersize=msize,
                    markerfacecolor='none', markeredgewidth=0.8)

        label_offset_ra  = ra_off(0.014)
        label_offset_dec = dec_off(0.014)
        band_label = star.get('band', '')

        # Magnitude label
        if show_mag:
            ax.text(s_ra + label_offset_ra, s_dec + label_offset_dec,
                    f"{s_mag:.1f}({band_label})",
                    color=star_color, fontsize=9, fontweight='semibold', alpha=0.95,
                    ha='left', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.12',
                              facecolor='black' if not (invert and is_single_filter) else 'white',
                              alpha=0.4, edgecolor='none'))

        # Name label for bright stars — prefer SIMBAD name, fall back to catalog id
        if show_names and s_mag < name_limit:
            display_name = star.get('name') or star.get('id', '')
            if display_name:
                ax.text(s_ra + label_offset_ra, s_dec - label_offset_dec,
                        display_name, color=text_color, fontsize=7.5, alpha=0.8,
                        ha='left', va='top')

    # Compass (N/E arrows) in top-left corner
    cx = extent[0] - ra_off(0.08)
    cy = extent[3] - dec_off(0.08)
    arrow_len_dec = dec_off(0.08)
    arrow_len_ra  = ra_off(0.08)
    # N arrow (up in Dec)
    ax.annotate('', xy=(cx, cy + arrow_len_dec), xytext=(cx, cy),
                arrowprops=dict(arrowstyle='->', color=compass_color, lw=1.5))
    ax.text(cx, cy + arrow_len_dec * 1.15, 'N', color=compass_color, fontsize=9,
            fontweight='bold', ha='center', va='bottom')
    # E arrow (increasing RA to the right visually since extent is RA-decreasing left)
    ax.annotate('', xy=(cx + arrow_len_ra, cy), xytext=(cx, cy),
                arrowprops=dict(arrowstyle='->', color=compass_color, lw=1.5))
    ax.text(cx + arrow_len_ra * 1.15, cy, 'E', color=compass_color, fontsize=9,
            fontweight='bold', ha='left', va='center')

    # Scale bar in bottom-left (angular scale, shown in Dec-direction length)
    scale_len_arcmin = _nice_scale_bar(fov_arcmin)
    scale_len_deg = scale_len_arcmin / 60.0 / cos_dec  # RA-direction length
    bar_x = extent[1] + ra_off(0.08)
    bar_y = extent[2] + dec_off(0.06)
    tick_h = dec_off(0.008)
    ax.plot([bar_x, bar_x + scale_len_deg], [bar_y, bar_y], '-', color=compass_color, lw=2)
    ax.plot([bar_x, bar_x], [bar_y - tick_h, bar_y + tick_h], '-', color=compass_color, lw=1.5)
    ax.plot([bar_x + scale_len_deg, bar_x + scale_len_deg], [bar_y - tick_h, bar_y + tick_h],
            '-', color=compass_color, lw=1.5)
    scale_text = f"{scale_len_arcmin:.0f}'" if scale_len_arcmin >= 1 else f'{scale_len_arcmin * 60:.0f}"'
    ax.text(bar_x + scale_len_deg / 2, bar_y + dec_off(0.015),
            scale_text, color=compass_color, fontsize=8, ha='center', va='bottom')

    # Info text in top-right
    coord_sc = SkyCoord(ra_deg, dec_deg, unit='deg')
    ra_hms = coord_sc.ra.to_string(u.hour, sep=':', precision=2)
    dec_dms = coord_sc.dec.to_string(u.deg, sep=':', precision=1, alwayssign=True)
    info_lines = [
        f'RA: {ra_hms}  Dec: {dec_dms}',
        f"FOV: {fov_arcmin:.1f}'  Survey: {survey}",
    ]
    info_x = extent[1] + ra_off(0.03)
    info_y = extent[3] - dec_off(0.03)
    for i, line in enumerate(info_lines):
        ax.text(info_x, info_y - i * fov_arcmin / 60.0 * 0.035, line,
                color=text_color, fontsize=7.5,
                ha='left', va='top', family='monospace',
                bbox=dict(boxstyle='round,pad=0.15',
                          facecolor='black' if not invert else 'white',
                          alpha=0.5, edgecolor='none'))

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel('RA [deg]', fontsize=9, color='gray')
    ax.set_ylabel('Dec [deg]', fontsize=9, color='gray')
    ax.tick_params(labelsize=7, colors='gray')

    # Suppress scientific notation; auto decimal places based on axis range
    import math
    from matplotlib.ticker import FuncFormatter
    def _adaptive_fmt(rng):
        # e.g. rng=0.5° → 4 dp, rng=5° → 3 dp, rng=0.05° → 5 dp
        n = max(1, int(math.ceil(-math.log10(max(rng, 1e-9)))) + 2)
        return FuncFormatter(lambda v, _: f'{v:.{n}f}')
    ax.xaxis.set_major_formatter(_adaptive_fmt(abs(extent[1] - extent[0])))
    ax.yaxis.set_major_formatter(_adaptive_fmt(abs(extent[3] - extent[2])))

    fig.patch.set_facecolor('black' if not (invert and is_single_filter) else '#f5f5f5')
    ax.set_facecolor('black' if not (invert and is_single_filter) else '#f5f5f5')
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def _nice_scale_bar(fov_arcmin):
    """Pick a nice round scale bar length."""
    target = fov_arcmin * 0.2
    nice_values = [0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 15, 20, 30, 60]
    for v in nice_values:
        if v >= target * 0.5:
            return v
    return nice_values[-1]
