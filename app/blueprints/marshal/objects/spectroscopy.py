"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — spectroscopy (split from object_routes.py)."""
import re
import urllib.parse
from flask import session, request, jsonify, Response
from app.db.transient import (
    search_tns_objects,
    TNSObjectDB,
    _parse_spectrum_id,
    _build_spectrum_label,
    _format_spectrum_observation_label,
    _phase_from_stored_value,
)
from app.db import get_tns_db_connection
from app.db.auth import check_object_access
from app.services.photometry.data_processing import DataVisualization
import logging
from app.core.auth import admin_required, login_required

logger = logging.getLogger(__name__)
from . import objects_bp


@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy')
@login_required(error='Access denied', status=403)
def get_object_spectroscopy(year, letters):
    
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

@objects_bp.route('/api/object/<object_name>/spectroscopy')
@login_required(error='Access denied', status=403)
def get_object_spectroscopy_generic(object_name):

    object_name = urllib.parse.unquote(object_name)

    try:
        spectra_list = TNSObjectDB.get_spectrum_list(object_name)
        return jsonify({
            'success': True,
            'spectra': spectra_list,
            'count': len(spectra_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/<spectrum_id>')
@login_required(error='Access denied', status=403)
def get_spectrum_data(year, letters, spectrum_id):
    
    object_name = f"{year}{letters}"
    
    try:
        source_name, observation_mjd = _parse_spectrum_id(spectrum_id)
        conn = get_tns_db_connection()
        cursor = conn.cursor()

        if observation_mjd is None:
            cursor.execute('''
                SELECT s.wavelength, s.intensity
                FROM transient.spectroscopy s
                JOIN transient.objects o ON s.obj_id = o.obj_id
                WHERE o.name ILIKE %s AND s.source = %s
                ORDER BY s.wavelength ASC
            ''', (object_name, source_name))
        else:
            cursor.execute('''
                SELECT s.wavelength, s.intensity
                FROM transient.spectroscopy s
                JOIN transient.objects o ON s.obj_id = o.obj_id
                WHERE o.name ILIKE %s AND s.source = %s AND ABS(s."MJD" - %s) < 1e-6
                ORDER BY s.wavelength ASC
            ''', (object_name, source_name, observation_mjd))
        
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

@objects_bp.route('/api/object/<string:object_name>/spectroscopy', methods=['POST'])
@admin_required
def upload_spectroscopy_generic(object_name):

    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    
    try:
        spectrum_id = TNSObjectDB.add_spectrum_data(
            object_name=object_name,
            wavelength_data=data.get('wavelength', []),
            intensity_data=data.get('intensity', []),
            phase=float(data.get('phase')) if data.get('phase') else None,
            telescope=data.get('telescope'),
            spectrum_id=data.get('spectrum_id'),
            original_filename=data.get('original_filename'),
            observation_date=data.get('observation_date')
        )
        
        return jsonify({
            'success': True,
            'message': 'Spectrum data added successfully',
            'spectrum_id': spectrum_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy', methods=['POST'])
def upload_spectroscopy(year, letters):
    object_name = f"{year}{letters}"
    return upload_spectroscopy_generic(object_name)

@objects_bp.route('/api/spectrum/<spectrum_id>', methods=['DELETE'])
@admin_required
def delete_spectrum(spectrum_id):
    
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

@objects_bp.route('/api/spectrum/<path:spectrum_id>/download')
@login_required(error='Access denied', status=403)
def download_spectrum_file(spectrum_id):
    """Download a single spectrum as .dat file."""

    try:
        source_name, observation_mjd = _parse_spectrum_id(spectrum_id)
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        if observation_mjd is None:
            cursor.execute('''
                SELECT o.name AS object_name, s.wavelength, s.intensity, s.source AS telescope, s."MJD" AS observation_mjd
                FROM transient.spectroscopy s
                JOIN transient.objects o ON s.obj_id = o.obj_id
                WHERE s.source = %s
                ORDER BY s.wavelength ASC
            ''', (source_name,))
        else:
            cursor.execute('''
                SELECT o.name AS object_name, s.wavelength, s.intensity, s.source AS telescope, s."MJD" AS observation_mjd
                FROM transient.spectroscopy s
                JOIN transient.objects o ON s.obj_id = o.obj_id
                WHERE s.source = %s AND ABS(s."MJD" - %s) < 1e-6
                ORDER BY s.wavelength ASC
            ''', (source_name, observation_mjd))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({'error': 'Spectrum not found'}), 404

        obj = rows[0][0]
        tel = rows[0][3] or 'Unknown'
        obs_mjd = rows[0][4]
        phase = _phase_from_stored_value(obs_mjd)
        spectrum_label = _build_spectrum_label(tel, obs_mjd)
        observation_label = _format_spectrum_observation_label(obs_mjd)

        lines = [
            f"# {obj} spectrum  id={spectrum_id}",
            f"# Label: {spectrum_label}",
            f"# Telescope: {tel}",
        ]
        if phase is not None:
            lines.append(f"# Phase: {phase}")
        elif observation_label:
            lines.append(f"# Observation date: {observation_label}")
        lines.append("# wavelength intensity")
        for _, wl, intens, _, _ in rows:
            lines.append(f"{wl:.4f}  {intens:.8g}")

        content = '\n'.join(lines) + '\n'
        safe_id = re.sub(r'[^\w\-]+', '_', spectrum_label).strip('_') or 'spectrum'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{obj}_spec_{safe_id}.dat"'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/spectral-lines')
@login_required(error='Access denied', status=403)
def get_spectral_lines():
    """Return NIST atomic spectral line data for the spectrum viewer.

    Returns cached data if available; triggers a background build and returns
    an empty list on first call (client falls back to built-in hardcoded lines).
    """
    try:
        from app.services.astro.spectral_lines import get_spectral_lines as _get_lines
        lines = _get_lines()
        return jsonify({
            'success': True,
            'source': 'nist' if lines else 'building',
            'count': len(lines),
            'lines': lines,
        })
    except Exception as exc:
        logger.error('get_spectral_lines error: %s', exc)
        return jsonify({'success': False, 'lines': [], 'source': 'error'}), 200

@objects_bp.route('/api/spectral-lines/rebuild', methods=['POST'])
@admin_required
def rebuild_spectral_lines():
    """Admin endpoint to force-rebuild the NIST spectral lines cache."""
    try:
        from app.services.astro.spectral_lines import warm_cache_async
        warm_cache_async()
        return jsonify({'success': True, 'message': 'Rebuild started in background'})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/plot')
@login_required(error='Access denied', status=403)
def get_object_spectrum_plot(year, letters):
    
    object_name = f"{year}{letters}"
    
    # Check permissions
    user_email = session['user'].get('email', '')
    if not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})
        
    spectrum_id = request.args.get('spectrum_id')
    rest_frame  = request.args.get('rest_frame', 'false').lower() in ('1', 'true')
    normalise   = request.args.get('normalise',  'false').lower() in ('1', 'true')
    stack       = request.args.get('stack',      'false').lower() in ('1', 'true')
    
    try:
        redshift = None
        results = search_tns_objects(search_term=object_name, limit=1)
        if results:
            redshift = results[0].get('redshift')
        spectrum_data = TNSObjectDB.get_spectroscopy(object_name)
        
        if not spectrum_data:
            return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'No spectrum data available'
            })
        
        if spectrum_id:
            plot_html = DataVisualization.create_spectrum_plot_from_db(
                spectrum_data, spectrum_id,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise)
        else:
            plot_html = DataVisualization.create_spectrum_list_plot_from_db(
                spectrum_data,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, stack=stack)
        
        return jsonify({
            'success': True,
            'plot_html': plot_html,
            'data_count': len(spectrum_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/spectrum/plot')
@login_required(error='Access denied', status=403)
def get_object_spectrum_plot_generic(object_name):
    
    object_name = urllib.parse.unquote(object_name)
    
    # Check permissions
    user_email = session['user'].get('email', '')
    if not check_object_access(object_name, user_email):
        return jsonify({'success': True, 'plot_html': None, 'message': 'Access denied.'})
        
    spectrum_id = request.args.get('spectrum_id')
    rest_frame  = request.args.get('rest_frame', 'false').lower() in ('1', 'true')
    normalise   = request.args.get('normalise',  'false').lower() in ('1', 'true')
    stack       = request.args.get('stack',      'false').lower() in ('1', 'true')
    
    try:
        results = search_tns_objects(search_term=object_name, limit=1)
        
        if not results:
            return jsonify({
                'success': False,
                'error': f'Object {object_name} not found'
            }), 404
        
        redshift = results[0].get('redshift')
        spectrum_data = TNSObjectDB.get_spectroscopy(object_name)
        
        if not spectrum_data:
            return jsonify({
                'success': True,
                'plot_html': None,
                'message': 'No spectrum data available for this object'
            })
        
        if spectrum_id:
            plot_html = DataVisualization.create_spectrum_plot_from_db(
                spectrum_data, spectrum_id,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise)
        else:
            plot_html = DataVisualization.create_spectrum_list_plot_from_db(
                spectrum_data,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, stack=stack)
        
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
