"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — spectroscopy (split from object_routes.py)."""
import re
import urllib.parse
from flask import request, jsonify, Response, session
from app.db.transient import (
    search_tns_objects,
    TNSObjectDB,
    _parse_spectrum_id,
    _build_spectrum_label,
    _format_spectrum_observation_label,
    _phase_from_stored_value,
    _parse_manual_observation_date,
    _resolve_spectrum_source_and_mjd,
    spectrum_epoch_is_given,
    SpectrumUploadError,
)
from app.services.spectrum_upload import check_spectrum_points, check_observation_mjd
from app.db import get_tns_db_connection
from app.services.photometry.data_processing import DataVisualization
import logging
from app.core.auth import admin_required, login_required
from app.core.permissions import action_required

logger = logging.getLogger(__name__)
from . import objects_bp
from .helpers import non_guest_required, session_can_access_object, resolve_object_name


@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy')
@non_guest_required
def get_object_spectroscopy(year, letters):
    
    object_name = f"{year}{letters}"
    if not session_can_access_object(object_name):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        spectra_list = TNSObjectDB.get_spectrum_list(object_name)
        return jsonify({
            'success': True,
            'spectra': spectra_list,
            'count': len(spectra_list)
        })
    except Exception as e:
        logger.error("spectrum list error for %s: %s", object_name, e)
        return jsonify({'error': 'Failed to load spectra'}), 500

@objects_bp.route('/api/object/<object_name>/spectroscopy')
@non_guest_required
def get_object_spectroscopy_generic(object_name):

    object_name = urllib.parse.unquote(object_name)
    if not session_can_access_object(object_name):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    try:
        spectra_list = TNSObjectDB.get_spectrum_list(object_name)
        return jsonify({
            'success': True,
            'spectra': spectra_list,
            'count': len(spectra_list)
        })
    except Exception as e:
        logger.error("spectrum list error for %s: %s", object_name, e)
        return jsonify({'error': 'Failed to load spectra'}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/<spectrum_id>')
@non_guest_required
def get_spectrum_data(year, letters, spectrum_id):
    
    object_name = f"{year}{letters}"
    if not session_can_access_object(object_name):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        source_name, observation_mjd = _parse_spectrum_id(spectrum_id)
        conn = get_tns_db_connection()
        try:
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
        finally:
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
        logger.error("spectrum data error for %s: %s", object_name, e)
        return jsonify({'error': 'Failed to load spectrum'}), 500

@objects_bp.route('/api/object/<string:object_name>/spectroscopy', methods=['POST'])
@action_required('upload_spectrum')
def upload_spectroscopy_generic(object_name):
    """Store one uploaded spectrum. Bad uploads get 400 with every problem in ``errors``
    (``error`` joins them for older clients); 404 unknown object; 409 duplicate spectrum."""
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Expected a JSON object.'}), 400

    def _refuse(errors, status=400, warnings=None):
        return jsonify({'success': False, 'error': ' '.join(errors), 'errors': errors,
                        'warnings': warnings or []}), status

    points, errors, warnings = check_spectrum_points(data.get('wavelength'), data.get('intensity'))

    phase = data.get('phase')
    if phase not in (None, ''):
        try:
            phase = float(phase)
        except (TypeError, ValueError):
            errors.append('phase must be a number.')
            phase = None
    else:
        phase = None

    texts = {}
    for key in ('telescope', 'spectrum_id', 'original_filename', 'observation_date'):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f'{key} must be text.')
            value = None
        texts[key] = (value or '').strip() or None

    if texts['observation_date'] and not _parse_manual_observation_date(texts['observation_date']):
        errors.append('observation_date must be YYYY-MM-DD.')
    elif not spectrum_epoch_is_given(texts['spectrum_id'], texts['observation_date'],
                                     texts['original_filename'], phase):
        errors.append('Observation date is required (YYYY-MM-DD); it could not be read from the file name.')
    else:
        _, mjd = _resolve_spectrum_source_and_mjd(
            telescope=texts['telescope'], spectrum_id=texts['spectrum_id'],
            original_filename=texts['original_filename'], phase=phase,
            observation_date=texts['observation_date'])
        if mjd > 1000:  # values below are legacy phases, not epochs
            date_error = check_observation_mjd(mjd)
            if date_error:
                errors.append(date_error)

    if errors:
        return _refuse(errors, warnings=warnings)

    try:
        spectrum_id = TNSObjectDB.add_spectrum_data(
            object_name=object_name,
            wavelength_data=[p[0] for p in points],
            intensity_data=[p[1] for p in points],
            phase=phase,
            telescope=texts['telescope'],
            spectrum_id=texts['spectrum_id'],
            original_filename=texts['original_filename'],
            observation_date=texts['observation_date'],
        )
    except SpectrumUploadError as exc:
        return _refuse([str(exc)], exc.status, warnings)
    except Exception:
        logger.exception('Unhandled error in %s', request.path)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

    logger.info('spectrum %s uploaded to %s by %s (%d points)', spectrum_id, object_name,
                (session.get('user') or {}).get('email'), len(points))

    return jsonify({
        'success': True,
        'message': 'Spectrum data added successfully',
        'spectrum_id': spectrum_id,
        'points': len(points),
        'warnings': warnings,
    })

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectroscopy', methods=['POST'])
def upload_spectroscopy(year, letters):
    object_name = f"{year}{letters}"
    return upload_spectroscopy_generic(object_name)

@objects_bp.route('/api/spectrum/<spectrum_id>', methods=['DELETE'])
@action_required('delete_spectrum')
def delete_spectrum(spectrum_id):
    """Delete one spectrum of ``?object=<name>`` (required: ids are only source+MJD)."""
    object_name = (request.args.get('object') or '').strip()
    if not object_name:
        return jsonify({'error': 'Missing object parameter'}), 400
    try:
        if TNSObjectDB.delete_spectrum(spectrum_id, object_name):
            logger.info('spectrum %s of %s deleted by %s', spectrum_id, object_name,
                        (session.get('user') or {}).get('email'))
            return jsonify({
                'success': True,
                'message': 'Spectrum deleted successfully'
            })
        else:
            return jsonify({'error': 'Spectrum not found'}), 404
    except Exception:
        logger.exception('Unhandled error in %s', request.path)
        return jsonify({'error': 'Internal server error'}), 500

@objects_bp.route('/api/spectrum/<path:spectrum_id>/download')
@non_guest_required
def download_spectrum_file(spectrum_id):
    """Download a single spectrum as .dat file.

    The object is required (``?object=<name>``): spectrum ids are only
    source+MJD, so without it spectra of different objects would be merged."""

    raw_object = (request.args.get('object') or '').strip()
    if not raw_object:
        return jsonify({'error': 'Missing object parameter'}), 400

    try:
        object_name = resolve_object_name(raw_object)
        if object_name is None:
            return jsonify({'error': 'Spectrum not found'}), 404
        if not session_can_access_object(object_name):
            return jsonify({'error': 'Access denied'}), 403

        source_name, observation_mjd = _parse_spectrum_id(spectrum_id)
        conn = get_tns_db_connection()
        try:
            cursor = conn.cursor()
            if observation_mjd is None:
                cursor.execute('''
                    SELECT o.name AS object_name, s.wavelength, s.intensity, s.source AS telescope, s."MJD" AS observation_mjd
                    FROM transient.spectroscopy s
                    JOIN transient.objects o ON s.obj_id = o.obj_id
                    WHERE o.name = %s AND s.source = %s
                    ORDER BY s.wavelength ASC
                ''', (object_name, source_name))
            else:
                cursor.execute('''
                    SELECT o.name AS object_name, s.wavelength, s.intensity, s.source AS telescope, s."MJD" AS observation_mjd
                    FROM transient.spectroscopy s
                    JOIN transient.objects o ON s.obj_id = o.obj_id
                    WHERE o.name = %s AND s.source = %s AND ABS(s."MJD" - %s) < 1e-6
                    ORDER BY s.wavelength ASC
                ''', (object_name, source_name, observation_mjd))
            rows = cursor.fetchall()
        finally:
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
        safe_obj = re.sub(r'[^\w\-.]+', '_', obj or '').strip('_') or 'object'
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{safe_obj}_spec_{safe_id}.dat"'}
        )
    except Exception as e:
        logger.error("spectrum download error for %s: %s", spectrum_id, e)
        return jsonify({'error': 'Failed to build spectrum file'}), 500

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
    except Exception:
        logger.exception('rebuild_spectral_lines error')
        return jsonify({'error': 'Internal server error'}), 500

@objects_bp.route('/api/object/<int:year><alpha:letters>/spectrum/plot')
@non_guest_required
def get_object_spectrum_plot(year, letters):
    
    object_name = f"{year}{letters}"
    
    # Check permissions
    if not session_can_access_object(object_name):
        return jsonify({'success': True, 'plot_json': None, 'message': 'Access denied.'})
        
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
                'plot_json': None,
                'message': 'No spectrum data available'
            })
        
        if spectrum_id:
            plot_json = DataVisualization.create_spectrum_plot_from_db(
                spectrum_data, spectrum_id,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, as_json=True)
        else:
            plot_json = DataVisualization.create_spectrum_list_plot_from_db(
                spectrum_data,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, stack=stack, as_json=True)
        
        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(spectrum_data)
        })
    except Exception as e:
        logger.error("spectrum plot error for %s: %s", object_name, e)
        return jsonify({'error': 'Failed to build spectrum plot'}), 500

@objects_bp.route('/api/object/<object_name>/spectrum/plot')
@non_guest_required
def get_object_spectrum_plot_generic(object_name):
    
    object_name = urllib.parse.unquote(object_name)
    
    # Check permissions
    if not session_can_access_object(object_name):
        return jsonify({'success': True, 'plot_json': None, 'message': 'Access denied.'})
        
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
                'plot_json': None,
                'message': 'No spectrum data available for this object'
            })
        
        if spectrum_id:
            plot_json = DataVisualization.create_spectrum_plot_from_db(
                spectrum_data, spectrum_id,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, as_json=True)
        else:
            plot_json = DataVisualization.create_spectrum_list_plot_from_db(
                spectrum_data,
                rest_frame=rest_frame, redshift=redshift, normalise=normalise, stack=stack, as_json=True)
        
        return jsonify({
            'success': True,
            'plot_json': plot_json,
            'data_count': len(spectrum_data)
        })
    except Exception as e:
        logger.error("spectrum plot error for %s: %s", object_name, e)
        return jsonify({
            'success': False,
            'error': 'Failed to build spectrum plot'
        }), 500
