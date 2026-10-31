"""Private area: Triggers › Alerts — the lab bots' state and what they produced (GCN / EP alerts, AstroNotes, the
observation log). Read only, except that admins can cancel / restore a robot alert; running, stopping and logs stay
in Admin › Bots. The reduction pipeline is not here
(it has the Pipeline page)."""
import logging
from datetime import datetime, timezone

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.config import config

from . import private_area_bp
from .helpers import can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'bots'


def _denied():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Please log in.'}), 401
    if not can_access_page(PAGE_KEY):
        return jsonify({'success': False, 'error': 'Access denied.'}), 403
    return None


@private_area_bp.route('/bots')
def lab_bots():
    if 'user' not in session:
        flash('Please log in to see the lab bots.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page(PAGE_KEY):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    from app.services.bots import results
    return render_template('lab_bots.html', current_path='/bots', bots=results.view(debug=config.DEBUG),
                           is_admin=bool(session['user'].get('is_admin')))


@private_area_bp.route('/api/bots/status')
def api_lab_bots_status():
    denied = _denied()
    if denied:
        return denied
    from app.services.bots import results
    return jsonify({'success': True, 'bots': results.view(debug=config.DEBUG),
                    'now': datetime.now(timezone.utc).isoformat(timespec='seconds')})


@private_area_bp.route('/api/bots/<bot_id>/results')
def api_lab_bot_results(bot_id):
    denied = _denied()
    if denied:
        return denied
    from app.services.bots import results
    fn = results.RESULTS.get(bot_id)
    if not fn:
        return jsonify({'success': False, 'error': 'Unknown bot'}), 404
    try:
        return jsonify({'success': True, **fn()})
    except Exception:
        logger.exception('bot results %s failed', bot_id)
        return jsonify({'success': False, 'error': 'Could not read the results.'}), 500


@private_area_bp.route('/api/bots/robot_alerts/<int:alert_id>/status', methods=['POST'])
def api_robot_alert_status(alert_id):
    """Admins: cancel a robot alert (the Lulin robot stops seeing it in active_ids) or restore it."""
    if not session.get('user', {}).get('is_admin'):
        return jsonify({'success': False, 'error': 'Admins only.'}), 403
    new = str((request.get_json(silent=True) or {}).get('status') or '')
    if new not in ('active', 'cancelled'):
        return jsonify({'success': False, 'error': "status must be 'active' or 'cancelled'"}), 400
    from app.db.robot import set_status
    from app.services.bots import status
    who = session['user'].get('email') or 'admin'
    if not set_status(alert_id, new, who):
        return jsonify({'success': False, 'error': 'No such alert.'}), 404
    status.event('gcn', f"Robot alert #{alert_id} {'cancelled' if new == 'cancelled' else 'restored'} by {who}", count=False)
    logger.info('audit action=robot_alert_%s actor=%s target=%s', new, who, alert_id)
    return jsonify({'success': True})
