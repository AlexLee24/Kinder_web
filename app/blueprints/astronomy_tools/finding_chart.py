"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — finding_chart (split from astronomy_tools_routes.py)."""
import re
import io
import traceback
import numpy as np
from PIL import Image
from flask import render_template, request, jsonify, Response
from astropy.coordinates import SkyCoord
import astropy.units as u
from . import astronomy_tools_bp
from .finding_chart_render import (
    _fetch_survey_fits,
    _fetch_survey_image,
    _query_nearby_stars,
    _render_finding_chart,
)


# ===============================================================================
# FINDING CHART
# ===============================================================================
@astronomy_tools_bp.route('/finding_chart')
def finding_chart():
    return render_template('finding_chart.html', current_path='/finding_chart')

def _resolve_target_coord(target_name, ra_str, dec_str):
    """Resolve target coordinates from RA/Dec strings or object name."""
    def _parse_coord(ra_s, dec_s):
        """Try sensible unit combinations; return SkyCoord or raise."""
        ra_s = str(ra_s).strip()
        dec_s = str(dec_s).strip()
        ra_is_decimal = bool(re.match(r'^[+-]?[\d]+\.?[\d]*$', ra_s))
        dec_is_decimal = bool(re.match(r'^[+-]?[\d]+\.?[\d]*$', dec_s))
        if ra_is_decimal and dec_is_decimal:
            attempts = [(u.deg, u.deg), (u.hourangle, u.deg)]
        else:
            attempts = [(u.hourangle, u.deg), (u.deg, u.deg)]
        for ra_unit, dec_unit in attempts:
            try:
                return SkyCoord(ra_s, dec_s, unit=(ra_unit, dec_unit))
            except Exception:
                continue
        raise ValueError(f'Cannot parse coordinates: RA={ra_s!r} Dec={dec_s!r}')

    if ra_str or dec_str:
        try:
            return _parse_coord(ra_str, dec_str)
        except Exception:
            if not target_name:
                raise
    if target_name:
        return SkyCoord.from_name(target_name)
    raise ValueError(f'Cannot parse coordinates: RA={ra_str} Dec={dec_str}')

def _safe_chart_basename(name):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', str(name or 'target')).strip('_')
    return safe or 'target'

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

        try:
            coord = _resolve_target_coord(target_name, ra_str, dec_str)
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

@astronomy_tools_bp.route('/api/finding_chart/fits', methods=['POST'])
def download_finding_chart_fits():
    """Download FOV-matched raw FITS cutout with WCS metadata when available."""
    try:
        data = request.get_json(silent=True) or {}
        target_name = data.get('name', 'target')
        ra_str = data.get('ra', '')
        dec_str = data.get('dec', '')
        survey = data.get('survey', 'DSS2 Red')
        fov_arcmin = float(data.get('fov', 10))

        try:
            coord = _resolve_target_coord(target_name, ra_str, dec_str)
        except Exception:
            return jsonify({'error': f'Cannot parse coordinates: RA={ra_str} Dec={dec_str}'}), 400

        ra_deg = coord.ra.deg
        dec_deg = coord.dec.deg

        fits_bytes, logs = _fetch_survey_fits(survey, ra_deg, dec_deg, fov_arcmin)
        if not fits_bytes:
            return jsonify({
                'error': f'Raw FITS is unavailable for survey {survey}',
                'logs': logs,
            }), 400

        survey_tag = _safe_chart_basename(survey).lower()
        target_tag = _safe_chart_basename(target_name)
        filename = f'{target_tag}_{survey_tag}_{fov_arcmin:.1f}arcmin.fits'

        response = Response(fits_bytes, mimetype='application/fits')
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'logs': [f'[ERROR] {str(e)}']}), 500
