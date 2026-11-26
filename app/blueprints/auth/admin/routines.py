"""Admin › Routines (/admin/routines): every scheduled job (app/services/jobs/routines.py) with its schedule,
next run, last runs and log, Run now; plus the manual maintenance tools that used to be the Jobs tab."""
from datetime import datetime, timezone

from flask import jsonify, render_template, request

from app.config import config
from app.core.auth import admin_required, admin_required_page

from . import admin_bp
from .helpers import audit


@admin_bp.route('/admin/routines')
@admin_required_page
def routines_page():
    from app.services.jobs import routines
    return render_template('admin_routines.html', current_path='/admin/routines', routines=routines.view(config.DEBUG),
                           groups=routines.GROUPS, debug=config.DEBUG)


@admin_bp.route('/admin/routines/status')
@admin_required
def routines_status():
    from app.services.jobs import routines
    return jsonify({'routines': routines.view(config.DEBUG), 'groups': list(routines.GROUPS),
                    'now': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'debug': config.DEBUG})


@admin_bp.route('/admin/routines/<rid>/log')
@admin_required
def routine_log(rid):
    from app.services.jobs import routines
    if rid not in routines.BY_ID:
        return jsonify({'error': 'Unknown routine'}), 404
    offset = request.args.get('offset', type=int)
    return jsonify(routines.read_log(rid, offset if offset is not None and offset >= 0 else None))


@admin_bp.route('/admin/routines/<rid>/run', methods=['POST'])
@admin_required
def routine_run(rid):
    from app.services.jobs import routines
    if rid not in routines.BY_ID:
        return jsonify({'error': 'Unknown routine'}), 404
    audit('routine_run', rid)
    res = routines.start_now(rid)
    return jsonify(res), (409 if res.get('error') else 200)
