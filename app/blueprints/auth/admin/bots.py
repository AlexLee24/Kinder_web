"""Admin › Bots (/admin/bots): state, recent events and logs of the lab bots (app/services/bots), Run now / Stop."""
import threading
from datetime import datetime, timezone

from flask import jsonify, render_template, request

from app.config import config
from app.core.auth import admin_required, admin_required_page

from . import admin_bp
from .helpers import audit


def _setup_problems():
    """What each bot is missing right now (settings, folders), so the page shows it before the first run."""
    from app.services.bots import astronote, gcn, obs_log, reduction
    raw = obs_log.raw_dir()
    out = {'gcn': gcn.setup_problem(), 'astronote': astronote.setup_problem(), 'reduction': reduction.setup_problem(),
           'obs_log': '' if raw and raw.is_dir() else f'Raw frame folder not found: {raw or "(not set)"} — set OBS_RAW_DIR or REDUCTION_PIPELINE_DIR.'}
    return {k: v for k, v in out.items() if v}


def _view():
    from app.services.bots import reduction, status
    bots = status.view(debug=config.DEBUG, setup=_setup_problems())
    for b in bots:
        if b['id'] == 'reduction':
            b['schedule'] = reduction.schedule_label()
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
