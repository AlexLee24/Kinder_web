"""Tools › Sky Cutouts (/sky_cutouts): 2–4 panels at any position, each from Euclid DR1 / Q1 (raw pixels, stretched in
the browser) or a colour image of another survey (Legacy Survey, HSC PDR3, Pan-STARRS1, SDSS, unWISE, GALEX, VLASS).

* GET /sky_cutouts?q=…&fov=30&p=vis,nisp,hsc,dr10  the page (euclid_compare.html + js/euclid_compare.js)
* GET /euclid?…                                     old name; redirects with the same query
API for any page (also under the old /api/euclid/… paths). Positions are ra=&dec= (deg) or q= (name / coordinates);
fov is the full width in arcsec, one of euclid_cutout.FOV_CHOICES (default 30). Errors are JSON {error} with 4xx/5xx.
* GET /api/cutouts/sources                          [{key, label, group, kind: fits|jpeg, bands?}]
* GET /api/cutouts/image?ra=&dec=&fov=&src=hsc      a JPEG of any source, north up — usable as <img src>;
                                                    Euclid sources are STF-stretched on the server
* GET /api/cutouts/resolve?q=…                      {ra, dec, source, name?}
* GET /api/cutouts/coverage?ra=&dec=                Euclid: {covered, release, tile, bands} or {covered: false, reason}
* GET /api/cutouts/pixels?ra=&dec=&fov=&band=VIS    Euclid raw float32 (FITS row order) + X-Width/X-Height/X-Target-X/Y
* GET /api/cutouts/survey?ra=&dec=&fov=&key=hsc     survey colour JPEG (cached proxy; key in euclid_cutout.SURVEYS)
Data: app/services/astro/euclid_cutout.py.
"""
import logging

from flask import jsonify, make_response, redirect, render_template, request, send_file, url_for

from app.services.astro import euclid_cutout as ec

from . import astronomy_tools_bp
from .helpers import _client_ip, _rate_ok_burst

logger = logging.getLogger(__name__)

SOURCE_GROUPS = [('Euclid', [(k, lab) for k, (lab, _) in ec.EUCLID_SOURCES.items()]),
                 ('Other surveys', list(ec.SURVEY_LABELS.items()))]
PANEL_SOURCES = [k for _, group in SOURCE_GROUPS for k, _ in group]
DEFAULT_PANELS = ['vis', 'nisp', 'hsc', 'dr10']


def _pos():
    if 'ra' not in request.args and request.args.get('q'):
        hit = ec.resolve(request.args['q'])
        return round(hit['ra'], 6), round(hit['dec'], 6)
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
def euclid_compare_old():
    return redirect(url_for('astronomy_tools.euclid_compare', **request.args), 301)


@astronomy_tools_bp.route('/sky_cutouts')
def euclid_compare():
    panels = [p for p in (request.args.get('p') or '').split(',') if p in PANEL_SOURCES][:4]
    if len(panels) < 2:
        panels = DEFAULT_PANELS
    return render_template('euclid_compare.html', current_path='/sky_cutouts', source_groups=SOURCE_GROUPS, q=(request.args.get('q') or '')[:100],
                           fov=_fov(), fov_choices=ec.FOV_CHOICES, panels=panels, default_panels=DEFAULT_PANELS)


@astronomy_tools_bp.route('/api/euclid/resolve')
@astronomy_tools_bp.route('/api/cutouts/resolve')   # url_for picks this (registered first)
def euclid_resolve_api():
    if _limited('resolve', 20, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        return jsonify(ec.resolve(request.args.get('q', '')))
    except ec.EuclidError as e:
        return _error(e)


@astronomy_tools_bp.route('/api/euclid/coverage')
@astronomy_tools_bp.route('/api/cutouts/coverage')   # url_for picks this (registered first)
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
@astronomy_tools_bp.route('/api/cutouts/pixels')   # url_for picks this (registered first)
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
@astronomy_tools_bp.route('/api/cutouts/survey')   # url_for picks this (registered first)
def euclid_survey_api():
    if _limited('survey', 40, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        ra, dec = _pos()
        path = ec.survey_jpeg(ra, dec, _fov(), request.args.get('key', ''))
    except ec.EuclidError as e:
        return _error(e)
    except Exception:
        logger.exception('[EUCLID] survey failed')
        return jsonify({'error': 'Survey cutout failed; see the server log.'}), 500
    resp = send_file(path, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp


@astronomy_tools_bp.route('/api/cutouts/sources')
def cutouts_sources_api():
    return jsonify({'sources': ec.sources(), 'fov_choices': list(ec.FOV_CHOICES)})


@astronomy_tools_bp.route('/api/cutouts/image')
def cutouts_image_api():
    if _limited('image', 60, 60.0):
        return jsonify({'error': 'Too many requests; wait a minute.'}), 429
    try:
        ra, dec = _pos()
        path = ec.image_jpeg(ra, dec, _fov(), request.args.get('src', ''))
    except ec.EuclidError as e:
        return _error(e)
    except Exception:
        logger.exception('[CUTOUTS] image failed')
        return jsonify({'error': 'Cutout failed; see the server log.'}), 500
    resp = send_file(path, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp
