"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — tools (split from astronomy_tools_routes.py)."""
from flask import render_template, request, jsonify
from app.services.astro.astronomy_calculator import calculate_redshift_distance, calculate_absolute_magnitude
from app.services.astro.date_converter import (
    convert_mjd_to_date,
    convert_jd_to_date,
    convert_common_date_to_jd,
)
from app.services.astro.coordinate_converter import (
    convert_ra_hms_to_decimal,
    convert_ra_decimal_to_hms,
    convert_dec_dms_to_decimal,
    convert_dec_decimal_to_dms,
)
from . import astronomy_tools_bp


# ===============================================================================
# ASTRONOMY TOOLS
# ===============================================================================
@astronomy_tools_bp.route('/astronomy_tools')
def astronomy_tools():
    return render_template('astronomy_tools.html', current_path='/astronomy_tools')

@astronomy_tools_bp.route('/mount_torque')
def mount_torque():
    return render_template('mount_torque.html', current_path='/mount_torque')

@astronomy_tools_bp.route('/mount_3d')
def mount_3d():
    return render_template('mount_3d.html', current_path='/mount_3d')

@astronomy_tools_bp.route('/calculate_redshift', methods=['POST'])
def calculate_redshift():
    try:
        data = request.get_json()
        redshift = float(data.get('redshift', 0))
        redshift_error = float(data.get('redshift_error')) if data.get('redshift_error') else None
        H0 = float(data.get('H0', 67.7))
        Om0 = float(data.get('Om0', 0.309))
        Tcmb0 = float(data.get('Tcmb0', 2.725))

        result = calculate_redshift_distance(redshift, redshift_error, H0=H0, Om0=Om0, Tcmb0=Tcmb0)
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
        H0 = float(data.get('H0', 67.7))
        Om0 = float(data.get('Om0', 0.309))
        Tcmb0 = float(data.get('Tcmb0', 2.725))

        result = calculate_absolute_magnitude(apparent_magnitude, redshift, extinction, H0=H0, Om0=Om0, Tcmb0=Tcmb0)
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
