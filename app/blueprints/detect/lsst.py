"""DETECT › LSST (/detect/lsst): ALeRCE LSST objects near a Lens or DESI galaxy,
split into "not in TNS yet" and "in TNS" (app/services/lsst/alerts.py fills the table)."""
import logging
import re

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.core.auth import admin_required
from app.services.lsst import alerce_api, alerts, lightcurve

from . import detect_bp

logger = logging.getLogger(__name__)

_VIEWS = ('pre_tns', 'in_tns', 'all')
_CATALOGS = ('all', 'lens', 'desi')
_DAYS = (3, 7, 14, 30, 90)


_MAX_MANUAL_DAYS = 30
# (query key, default, min, max): radii in arcsec; desi_re 0 = no half-light-radius cut
_CONE_OPTIONS = (('lens_r', alerts.LENS_RADIUS_ARCSEC, 0, 120), ('desi_r', alerts.DESI_RADIUS_ARCSEC, 0, 120),
                 ('desi_re', alerts.DESI_MAX_SEP_RE, 0, 50), ('tns_r', 10.0, 0, 120), ('alerce_r', 10.0, 0, 120))


def _member_api_denied():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Not available for Guest users'}), 403
    return None


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
    oid = request.args.get('oid', type=int)
    try:
        rows = alerts.list_alerts(view=view, catalog=catalog, days=days, oid=oid)
        stats = alerts.summary(days=days)
        error = None
    except Exception as e:  # table missing / DB down: show the page, not a 500
        logger.error('DETECT LSST page: %s', e)
        rows, stats, error = [], {}, str(e)
    return render_template('detect_lsst.html', rows=rows, stats=stats, error=error,
                           view=view, catalog=catalog, days=days, day_options=_DAYS, oid=oid,
                           alerce_url=alerce_api.explorer_url(oid) if oid else None,
                           current_path='/detect/lsst')


@detect_bp.route('/detect/lsst/<int:oid>')
def detect_lsst_object(oid):
    """Where a Daily Trigger target called LSST-<oid> points: its object page once TNS has
    it, else its row on DETECT › LSST."""
    denied = _member_or_redirect()
    if denied:
        return denied
    from app.db import get_db_connection
    with get_db_connection() as conn:
        tns = alerts.tns_name_for_oid(conn.cursor(), oid)
    if tns:
        return redirect('/object/' + re.sub(r'^(AT|SN)', '', tns))
    return redirect(url_for('detect.detect_lsst', oid=oid))


@detect_bp.route('/api/detect/lsst/lightcurve/<int:oid>')
def detect_lsst_lightcurve(oid):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        points = lightcurve.lightcurve_points(alerce_api.lightcurve(oid))
    except Exception as e:
        return jsonify({'error': str(e)}), 502
    mags = None
    rows = alerts._alerts_for_mags([oid])
    if rows:                        # a watched object: its magnitudes follow this fresh light curve
        try:
            mags = alerts.compute_mags(rows[0], points)
            alerts.save_mags(oid, mags, max((p[0] for p in points), default=None))
        except Exception as e:
            logger.warning('LSST magnitudes for %s: %s', oid, e)
    return jsonify({'oid': oid, 'mags': mags, 'points': [
        {'mjd': m, 'mag': mag, 'mag_err': err, 'filter': f} for m, mag, err, f in points]})


@detect_bp.route('/api/detect/lsst/run', methods=['POST'])
@admin_required
def detect_lsst_run():
    """Run the watch now. ``days`` (1–30) re-reads that many days instead of "since the last run"."""
    data = request.get_json(silent=True) or {}
    days = data.get('days')
    if days not in (None, ''):
        try:
            days = float(days)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'days must be a number'}), 400
        if not 0 < days <= _MAX_MANUAL_DAYS:
            return jsonify({'success': False, 'message': f'days must be 0–{_MAX_MANUAL_DAYS}'}), 400
    else:
        days = None
    if not alerts.start_manual_run(days):
        return jsonify({'success': False, 'message': 'A run is already in progress'}), 409
    return jsonify({'success': True})


@detect_bp.route('/api/detect/lsst/status')
def detect_lsst_status():
    """The current / last watch run (state, phase, log) for the page's live log."""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(alerts.run_status())


@detect_bp.route('/api/detect/lsst/crossmatch_oid', methods=['POST'])
def detect_lsst_crossmatch_oid():
    """Cross-match one LSST object by oid (also "LSST-AP-DO-<oid>" / "LSST-<oid>"); where to look next."""
    denied = _member_api_denied()
    if denied:
        return denied
    raw = str((request.get_json(silent=True) or {}).get('oid') or '')
    m = re.search(r'(\d{6,})', raw)
    if not m:
        return jsonify({'success': False, 'message': 'Enter an LSST oid (diaObjectId), e.g. 171141197314654355'}), 400
    oid = int(m.group(1))
    try:
        res = alerts.crossmatch_oid(oid)
    except Exception as e:
        logger.warning('LSST oid cross-match %s: %s', oid, e)
        return jsonify({'success': False, 'message': f'ALeRCE did not answer: {e}'}), 502
    if not res['found']:
        return jsonify({'success': False, 'message': f'ALeRCE has no LSST object {oid}'}), 404
    if res['stored']:
        return jsonify({'success': True, 'stored': True, 'url': url_for('detect.detect_lsst', oid=oid)})
    item = res['item']
    return jsonify({'success': True, 'stored': False,
                    'message': 'No lens or DESI galaxy within the watch radii; showing everything around it.',
                    'url': url_for('detect.detect_crossmatch', ra=f"{float(item['meanra']):.6f}",
                                   dec=f"{float(item['meandec']):.6f}", oid=oid)})


@detect_bp.route('/detect/crossmatch')
def detect_crossmatch():
    """DETECT › Cross-match: everything around one position (Lens, DESI, TNS, ALeRCE). Nothing is stored."""
    denied = _member_or_redirect()
    if denied:
        return denied
    form = {k: (request.args.get(k) or '').strip() for k in ('ra', 'dec', 'oid', 'zwarn')}
    opts = {}
    for key, default, lo, hi in _CONE_OPTIONS:
        try:
            val = float(request.args.get(key, default))
        except ValueError:
            val = default
        opts[key] = min(max(val, lo), hi)
    result, error = None, None
    if form['ra'] or form['dec']:
        try:
            ra, dec = alerts.parse_coords(form['ra'], form['dec'])
            result = alerts.cone_search(
                ra, dec, lens_radius=opts['lens_r'], desi_radius=opts['desi_r'],
                desi_max_sep_re=opts['desi_re'] or None, include_zwarn=form['zwarn'] == '1',
                tns_radius=opts['tns_r'], alerce_radius=opts['alerce_r'])
        except ValueError as e:
            error = f'Could not read the coordinates: {e}'
        except Exception as e:
            logger.exception('DETECT cross-match failed')
            error = f'Cross-match failed: {e}'
    return render_template('detect_crossmatch.html', form=form, opts=opts, result=result, error=error,
                           explorer_url=alerce_api.explorer_url, current_path='/detect/crossmatch')
