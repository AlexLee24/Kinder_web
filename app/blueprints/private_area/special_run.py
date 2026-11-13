"""Lab › Special Run: one-off science runs and lab tools. Tabs: Euclid-SLSN, Lens Simulator; each tab is its own
private page (Admin › Permissions: who opens it — GREAT Lab members or admins only — plus added groups).
Lens Simulator starts as admins only.

* GET  /special_run                              → the first tab the user may open
* GET  /special_run/lens_sim                     Lens Simulator (special_run_lens_sim.html + js/lens_sim.js, all in-browser)
* GET  /special_run/euclid_slsn                  page (special_run_euclid_slsn.html)
* POST /api/special_run/euclid_slsn/run          start the background run ({"refresh": true} re-downloads cutouts)
* GET  /api/special_run/euclid_slsn/status       progress (state.json) + results (results.json)
* GET  /special_run/euclid_slsn/file/<slug>/<f>  host.png or <band>.fits
* GET  /api/special_run/euclid_slsn/pixels/<slug>/<band>  raw float32 for the in-browser STF stretch
* GET  /special_run/euclid_slsn/ls/<slug>/<dr10|dr11>.jpg  Legacy Survey comparison (cached proxy)
* GET  /special_run/euclid_slsn/download.zip     every PNG + FITS + results.json
"""
import io
import logging
import re
import zipfile

from flask import (abort, flash, jsonify, make_response, redirect, render_template, request, send_file,
                   send_from_directory, session, url_for)

from app.services.special_run import euclid_slsn

from . import private_area_bp
from .helpers import can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'special_run_euclid_slsn'
LENS_KEY = 'special_run_lens_sim'
_FILE = re.compile(r'^(host\.png|(VIS|NIR_Y|NIR_J|NIR_H)\.fits|LS_dr1[01]\.jpg)$')
_SLUG = re.compile(r'^[A-Za-z0-9_.+-]{1,80}$')


def _deny_page():
    if 'user' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('basic.login'))
    flash('Access denied.', 'error')
    return redirect(url_for('basic.home'))


@private_area_bp.route('/special_run')
def special_run():
    for key, endpoint in ((PAGE_KEY, 'special_run_euclid_slsn'), (LENS_KEY, 'special_run_lens_sim')):
        if can_access_page(key):
            return redirect(url_for(f'private_area.{endpoint}'))
    return _deny_page()


@private_area_bp.route('/special_run/lens_sim')
def special_run_lens_sim():
    if not can_access_page(LENS_KEY):
        return _deny_page()
    return render_template('special_run_lens_sim.html', current_path='/special_run/lens_sim')


@private_area_bp.route('/special_run/euclid_slsn')
def special_run_euclid_slsn():
    if not can_access_page(PAGE_KEY):
        return _deny_page()
    return render_template('special_run_euclid_slsn.html', current_path='/special_run/euclid_slsn',
                           cutout_arcsec=int(euclid_slsn.CUTOUT_ARCSEC * 2))


@private_area_bp.route('/api/special_run/euclid_slsn/run', methods=['POST'])
def special_run_euclid_slsn_run():
    if not can_access_page(PAGE_KEY):
        return jsonify({'error': 'Forbidden'}), 403
    body = request.get_json(silent=True) or {}
    started = euclid_slsn.start(refresh=bool(body.get('refresh')))
    if not started:
        return jsonify({'error': 'A run is already in progress.'}), 409
    logger.info('[EUCLID-SLSN] run started by %s', session['user'].get('email'))
    return jsonify({'success': True})


@private_area_bp.route('/api/special_run/euclid_slsn/status')
def special_run_euclid_slsn_status():
    if not can_access_page(PAGE_KEY):
        return jsonify({'error': 'Forbidden'}), 403
    resp = jsonify({'status': euclid_slsn.status(), 'results': euclid_slsn.results()})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@private_area_bp.route('/special_run/euclid_slsn/file/<slug>/<fname>')
def special_run_euclid_slsn_file(slug, fname):
    if not can_access_page(PAGE_KEY):
        abort(403)
    if not _SLUG.match(slug) or not _FILE.match(fname):
        abort(404)
    resp = send_from_directory(euclid_slsn.OUT_DIR / slug, fname, as_attachment=fname.endswith('.fits'),
                               download_name=f'{slug}_{fname}' if fname.endswith('.fits') else None)
    resp.headers['Cache-Control'] = 'private, no-cache'
    return resp


@private_area_bp.route('/api/special_run/euclid_slsn/pixels/<slug>/<band>')
def special_run_euclid_slsn_pixels(slug, band):
    """Raw float32 cutout (row 0 = bottom, FITS order) for the in-browser stretch; size + target pixel in headers."""
    if not can_access_page(PAGE_KEY):
        abort(403)
    if not _SLUG.match(slug) or band not in euclid_slsn.BANDS:
        abort(404)
    got = euclid_slsn.pixels(slug, band)
    if got is None:
        abort(404)
    data, px, py = got
    resp = make_response(data.tobytes())
    resp.headers.update({
        'Content-Type': 'application/octet-stream', 'Cache-Control': 'private, max-age=3600',
        'X-Width': str(data.shape[1]), 'X-Height': str(data.shape[0]),
        'X-Target-X': '' if px is None else f'{px:.2f}', 'X-Target-Y': '' if py is None else f'{py:.2f}',
    })
    return resp


@private_area_bp.route('/special_run/euclid_slsn/ls/<slug>/<key>.jpg')
def special_run_euclid_slsn_ls(slug, key):
    """Legacy Survey DR10 / DR11 comparison JPEG, fetched once (serially, the viewer rate-limits) then cached."""
    if not can_access_page(PAGE_KEY):
        abort(403)
    if not _SLUG.match(slug) or key not in euclid_slsn.LS_LAYERS:
        abort(404)
    path = euclid_slsn.ls_cutout(slug, key)
    if path is None:
        abort(404)
    resp = send_file(path, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp


@private_area_bp.route('/special_run/euclid_slsn/download.zip')
def special_run_euclid_slsn_zip():
    if not can_access_page(PAGE_KEY):
        abort(403)
    res = euclid_slsn.results()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if euclid_slsn.RESULTS_FILE.exists():
            z.write(euclid_slsn.RESULTS_FILE, 'euclid_slsn/results.json')
        for r in res.get('covered', []):
            d = euclid_slsn.OUT_DIR / r['slug']
            for f in sorted(d.glob('*')):
                if _FILE.match(f.name):
                    z.write(f, f"euclid_slsn/{r['slug']}/{f.name}")
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name='euclid_slsn_hosts.zip')
