"""Admin › Bots (/admin/bots): state, recent events and logs of the lab bots (app/services/bots), Run now / Stop."""
import threading
from datetime import datetime, timezone

from flask import jsonify, render_template, request

from app.config import config
from app.core.auth import admin_required, admin_required_page

from . import admin_bp
from .helpers import audit


def _view():
    from app.services.bots import reduction, setup_problems, status
    bots = status.view(debug=config.DEBUG, setup=setup_problems())
    for b in bots:
        if b['id'] == 'reduction':
            b['schedule'] = reduction.schedule_label()
            ext = reduction.external_runs() if b['health'] != 'busy' else []
            if ext:                                    # started by the folder owner's cron, not by Kinder
                b['health'], b['health_label'] = 'busy', f"Running outside Kinder ({ext[0]['script']})"
                b['external'] = ext
    return bots


@admin_bp.route('/admin/bots')
@admin_required_page
def bots_page():
    return render_template('admin_bots.html', current_path='/admin/bots', bots=_view(), debug=config.DEBUG)


@admin_bp.route('/admin/bots/status')
@admin_required
def bots_status():
    return jsonify({'bots': _view(), 'now': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'debug': config.DEBUG})


@admin_bp.route('/admin/bots/<bot_id>/log')
@admin_required
def bot_log(bot_id):
    from app.services.bots import status
    if not status.known(bot_id):
        return jsonify({'error': 'Unknown bot'}), 404
    offset = request.args.get('offset', type=int)
    return jsonify(status.read_log(bot_id, offset if offset is not None and offset >= 0 else None))


@admin_bp.route('/admin/bots/<bot_id>/run', methods=['POST'])
@admin_required
def bot_run(bot_id):
    from app.services.bots import BY_ID, astronote, obs_log, reduction
    bot = BY_ID.get(bot_id)
    if not bot or not bot.can_run:
        return jsonify({'error': 'This bot cannot be run by hand'}), 400
    audit('bot_run', bot_id)
    if bot_id == 'detect':                              # ?kind=followups (the daily 04:00 job) or recent (objects TNS touched in 2 h)
        from .detect import start_detect_run
        res, code = start_detect_run('recent' if request.args.get('kind') == 'recent' else 'followups', hours=2.0)
        return (jsonify({'ok': True, 'message': res['message']}) if res['success'] else jsonify({'error': res['message']})), code
    if bot_id == 'reduction':
        res = reduction.start_now()
        return jsonify(res), (409 if res.get('error') else 200)
    fn = {'astronote': astronote.run, 'obs_log': obs_log.run}[bot_id]
    threading.Thread(target=fn, name=f'manual-bot-{bot_id}', daemon=True).start()
    return jsonify({'ok': True, 'message': 'Started.'})


@admin_bp.route('/admin/bots/reduction/stop', methods=['POST'])
@admin_required
def bot_reduction_stop():
    from app.services.bots import reduction
    audit('bot_stop', 'reduction')
    res = reduction.stop()
    return jsonify(res), (409 if res.get('error') else 200)


@admin_bp.route('/admin/bots/reduction/overview')
@admin_required
def bot_reduction_overview():
    from app.services.bots import reduction
    return jsonify(reduction.overview(max_age=0 if request.args.get('fresh') else 60))


@admin_bp.route('/admin/bots/detect/overview')
@admin_required
def bot_detect_overview():
    from app.services.bots import detect as detect_bot
    return jsonify(detect_bot.overview())
