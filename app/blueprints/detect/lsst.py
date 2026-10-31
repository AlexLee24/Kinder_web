"""DETECT › LSST (/detect/lsst): ALeRCE LSST objects near a Lens or DESI galaxy,
split into "not in TNS yet" and "in TNS" (app/services/lsst/alerts.py fills the table)."""
import logging
import threading

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core.auth import admin_required
from app.services.lsst import alerce_api, alerts, lightcurve

from . import detect_bp

logger = logging.getLogger(__name__)

_VIEWS = ('pre_tns', 'in_tns', 'all')
_CATALOGS = ('all', 'lens', 'desi')
_DAYS = (3, 7, 14, 30, 90)


def _member_or_redirect():
    if 'user' not in session:
        flash('Please log in to access DETECT LSST.', 'warning')
        return redirect(url_for('basic.login'))
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        flash('Access denied. This page is not available for Guest users.', 'error')
        return redirect(url_for('basic.home'))
    return None


@detect_bp.route('/detect/lsst')
def detect_lsst():
    denied = _member_or_redirect()
    if denied:
        return denied
    view = request.args.get('view', 'pre_tns')
    view = view if view in _VIEWS else 'pre_tns'
    catalog = request.args.get('catalog', 'all')
    catalog = catalog if catalog in _CATALOGS else 'all'
    try:
        days = int(request.args.get('days', 14))
    except ValueError:
        days = 14
    days = days if days in _DAYS else 14
    try:
        rows = alerts.list_alerts(view=view, catalog=catalog, days=days)
        stats = alerts.summary(days=days)
        error = None
    except Exception as e:  # table missing / DB down: show the page, not a 500
        logger.error('DETECT LSST page: %s', e)
        rows, stats, error = [], {}, str(e)
    return render_template('detect_lsst.html', rows=rows, stats=stats, error=error,
                           view=view, catalog=catalog, days=days, day_options=_DAYS,
                           current_path='/detect/lsst')


@detect_bp.route('/api/detect/lsst/lightcurve/<int:oid>')
def detect_lsst_lightcurve(oid):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        points = lightcurve.lightcurve_points(alerce_api.lightcurve(oid))
    except Exception as e:
        return jsonify({'error': str(e)}), 502
    return jsonify({'oid': oid, 'points': [
        {'mjd': m, 'mag': mag, 'mag_err': err, 'filter': f} for m, mag, err, f in points]})


@detect_bp.route('/api/detect/lsst/run', methods=['POST'])
@admin_required
def detect_lsst_run():
    if alerts.is_running():
        return jsonify({'success': False, 'message': 'Already running'}), 409
    threading.Thread(target=alerts.run_watch, name='lsst-watch-manual', daemon=True).start()
    return jsonify({'success': True, 'message': 'LSST watch started; reload in a few minutes.'})
