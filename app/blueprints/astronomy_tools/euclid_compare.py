"""Tools › Euclid (/euclid): Euclid DR1 / Q1 cutouts at any position, 2–4 panels next to Legacy Survey DR10 / DR11.

* GET /euclid?q=…&fov=30&p=vis,nisp,dr10,dr11      the page (euclid_compare.html + js/euclid_compare.js)
* GET /api/euclid/resolve?q=…                       {ra, dec, source, name?}
* GET /api/euclid/coverage?ra=&dec=                 {covered, release, tile, bands} or {covered: false, reason}
* GET /api/euclid/pixels?ra=&dec=&fov=&band=        raw float32 (FITS row order) + X-Width/X-Height/X-Target-X/Y
* GET /api/euclid/survey?ra=&dec=&fov=&key=dr10     Legacy Survey JPEG (cached proxy; the viewer rate-limits)
Data: app/services/astro/euclid_cutout.py.
"""
import logging

from flask import jsonify, make_response, render_template, request, send_file

from app.services.astro import euclid_cutout as ec

from . import astronomy_tools_bp
from .helpers import _client_ip, _rate_ok_burst

logger = logging.getLogger(__name__)

PANEL_SOURCES = ['vis', 'nisp', 'nisp_y', 'nisp_j', 'nisp_h', 'dr10', 'dr11']
DEFAULT_PANELS = ['vis', 'nisp', 'dr10', 'dr11']


def _pos():
    try:
        ra, dec = float(request.args['ra']), float(request.args['dec'])
    except (KeyError, TypeError, ValueError):
        raise ec.EuclidError('ra and dec (degrees) are required.')
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise ec.EuclidError('ra must be in [0, 360) and dec in [-90, 90].')
    return round(ra, 6), round(dec, 6)


def _fov():
    try:
        fov = int(request.args.get('fov', 30))
    except ValueError:
        fov = 30
    return fov if fov in ec.FOV_CHOICES else 30


def _limited(key, burst, interval):
    return not _rate_ok_burst(_client_ip(), f'euclid_{key}', burst, interval)


def _error(e):
    return jsonify({'error': str(e)}), getattr(e, 'status', 500)


@astronomy_tools_bp.route('/euclid')
def euclid_compare():
    panels = [p for p in (request.args.get('p') or '').split(',') if p in PANEL_SOURCES][:4]
    if len(panels) < 2:
        panels = DEFAULT_PANELS
    return render_template('euclid_compare.html', current_path='/euclid', q=(request.args.get('q') or '')[:100],
                           fov=_fov(), fov_choices=ec.FOV_CHOICES, panels=panels, default_panels=DEFAULT_PANELS)


@astronomy_tools_bp.route('/api/euclid/resolve')
def euclid_resolve_api():
    if _limited('resolve', 20, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        return jsonify(ec.resolve(request.args.get('q', '')))
    except ec.EuclidError as e:
        return _error(e)


@astronomy_tools_bp.route('/api/euclid/coverage')
def euclid_coverage_api():
    if _limited('coverage', 20, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        ra, dec = _pos()
        cov = ec.coverage(ra, dec)
    except ec.EuclidError as e:
        return _error(e)
    except Exception:
        logger.exception('[EUCLID] coverage failed')
        return jsonify({'error': 'Euclid coverage check failed; see the server log.'}), 500
    return jsonify({k: v for k, v in cov.items() if k != 'mosaics'})


@astronomy_tools_bp.route('/api/euclid/pixels')
def euclid_pixels_api():
    if _limited('pixels', 40, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        ra, dec = _pos()
        data, px, py, binning = ec.pixels(ra, dec, _fov(), request.args.get('band', ''))
    except ec.EuclidError as e:
        return _error(e)
    except Exception:
        logger.exception('[EUCLID] pixels failed')
        return jsonify({'error': 'Euclid cutout failed; see the server log.'}), 500
    resp = make_response(data.tobytes())
    resp.headers.update({
        'Content-Type': 'application/octet-stream', 'Cache-Control': 'private, max-age=86400',
        'X-Width': str(data.shape[1]), 'X-Height': str(data.shape[0]),
        'X-Target-X': f'{px:.2f}', 'X-Target-Y': f'{py:.2f}', 'X-Binning': str(binning),
    })
    return resp


@astronomy_tools_bp.route('/api/euclid/survey')
def euclid_survey_api():
    if _limited('survey', 40, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        ra, dec = _pos()
        path = ec.survey_jpeg(ra, dec, _fov(), request.args.get('key', ''))
    except ec.EuclidError as e:
        return _error(e)
    resp = send_file(path, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp
