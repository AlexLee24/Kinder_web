"""Admin System page (/admin/system): host and process performance, disks, folder sizes,
including the reduction pipeline's folder. Numbers come from app/services/system/monitor.py."""
import logging

from flask import Blueprint, jsonify, redirect, render_template, session, url_for

from app.services.system import monitor

logger = logging.getLogger(__name__)

system_status_bp = Blueprint('system_status', __name__, template_folder='templates')


def _is_admin():
    return 'user' in session and bool(session['user'].get('is_admin', False))


@system_status_bp.route('/admin/system')
def system_page():
    if not _is_admin():
        return redirect(url_for('basic.home'))
    return render_template('system_status.html', current_path='/admin/system')


@system_status_bp.route('/api/admin/system/status')
def api_system_status():
    if not _is_admin():
        return jsonify({'error': 'Access denied'}), 403
    return jsonify({'success': True, **monitor.snapshot()})


@system_status_bp.route('/api/admin/system/sizes', methods=['POST'])
def api_system_sizes():
    """Recount folder sizes now (in the background)."""
    if not _is_admin():
        return jsonify({'error': 'Access denied'}), 403
    started = monitor.refresh_sizes(force=True)
    logger.info('admin: %s asked for a folder size recount (started=%s)', session['user'].get('email'), started)
    return jsonify({'success': True, 'started': started})
