"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — daily_trigger (split from private_area_routes.py)."""
import json
import logging
import os

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.config import config
from app.db.auth import get_groups

logger = logging.getLogger(__name__)
from . import private_area_bp
from .helpers import can_access_page


@private_area_bp.route('/daily_trigger')
def daily_trigger():
    if 'user' not in session:
        flash('Please log in to access daily trigger.', 'warning')
        return redirect(url_for('basic.login'))

    user_email = session['user']['email']

    if not can_access_page('daily_trigger'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))

    all_groups = []
    if session['user'].get('is_admin', False):
        groups_dict = get_groups()
        all_groups = list(groups_dict.keys())

    user_display_name = session['user'].get('name') or user_email

    duty = tonight_duty()
    from app.services.lab_calendar import lot_closed_tonight

    return render_template('daily_trigger.html', current_path='/daily_trigger', all_groups=all_groups,
                            user_display_name=user_display_name, user_email=user_email,
                            app_debug=config.DEBUG, duty=duty, lot_closed=lot_closed_tonight(),
                            on_duty=any(d['email'].lower() == user_email.lower() for d in duty),
                            duty_lock=duty_lock(duty))


def tonight_duty():
    """Tonight's Trigger duty from Lab › Calendar (the trigger night turns over at 08:00): [{'email', 'name', …}]."""
    try:
        from datetime import date as _date

        from app.services import lab_calendar
        from app.services.planning.trigger_send import _trigger_day_key
        return lab_calendar.duty_on(_date.fromisoformat(_trigger_day_key()))
    except Exception:
        logger.exception('daily_trigger: Trigger duty not read')
        return []


def duty_lock(duty=None):
    """Names of tonight's Trigger duty when the signed-in user may not send a whole trigger, else [].
    Only the person on duty this week (or an admin) sends the Daily / Direct Trigger; everyone else can still
    send a single target. With nobody on duty there is no lock, so a night is never left without a trigger."""
    user = session.get('user') or {}
    if user.get('is_admin'):
        return []
    duty = tonight_duty() if duty is None else duty
    me = (user.get('email') or '').lower()
    if not duty or any(d['email'].lower() == me for d in duty):
        return []
    return [d['name'] for d in duty]


def duty_locked_response(requester):
    """403 when the requester is not tonight's Trigger duty (duty_lock), else None."""
    names = duty_lock()
    if not names:
        return None
    logger.warning('Trigger send refused — %s is not on Trigger duty tonight (%s)', requester, ', '.join(names))
    return jsonify({'success': False, 'duty_lock': names,
                    'error': f"Only tonight's Trigger duty ({', '.join(names)}) or an admin can send the trigger. "
                             'You can still trigger a single target (Trigger this target, on its row).'}), 403

@private_area_bp.route('/daily_trigger/send_status', methods=['GET'])
def daily_trigger_send_status():
    if 'user' not in session or not can_access_page('daily_trigger'):
        return jsonify({'error': 'Forbidden'}), 403
    from app.services.planning.trigger_send import get_send_status
    status = get_send_status()
    logger.info('daily_trigger_send_status: requested_by=%s status=%s',
                session['user'].get('email'), status)
    return jsonify({'success': True, 'status': status})

@private_area_bp.route('/daily_trigger/send_message', methods=['POST'])
def daily_trigger_send_message():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Please log in.'}), 401
    if not can_access_page('daily_trigger'):
        return jsonify({'success': False, 'error': 'Access denied.'}), 403

    requester = session['user'].get('email') or session['user'].get('name') or 'unknown'

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Invalid JSON body'}), 400
    telescope = str(data.get('telescope', '')).strip().upper()
    program = str(data.get('program', '')).strip()
    greeting = str(data.get('greeting', ''))
    script = str(data.get('script', ''))
    targets = data.get('targets') or []
    if not isinstance(targets, list) or not all(isinstance(t, dict) for t in targets):
        return jsonify({'success': False, 'error': 'targets must be a list of objects'}), 400
    if len(targets) > 200:
        return jsonify({'success': False, 'error': 'Too many targets'}), 400
    target_names = [t.get('name') for t in targets]
    should_mark_sent = bool(data.get('mark_sent', True))

    logger.info('daily_trigger_send_message: request by=%s telescope=%s program=%s targets=%s '
                'greeting_chars=%d script_chars=%d mark_sent=%s',
                requester, telescope, program, target_names, len(greeting), len(script), should_mark_sent)

    if telescope not in ('SLT', 'LOT'):
        logger.warning('daily_trigger_send_message: rejected — invalid telescope %r (by=%s)', telescope, requester)
        return jsonify({'success': False, 'error': 'Invalid telescope'}), 400
    if telescope == 'LOT':
        denied = lot_closed_response(requester, data.get('lot_closed_confirmed'))
        if denied:
            return denied
    # A single target (mark_sent False, one target) is open to everyone; the whole trigger is the duty's.
    if should_mark_sent or len(targets) != 1:
        denied = duty_locked_response(requester)
        if denied:
            return denied
    if not script.strip():
        logger.warning('daily_trigger_send_message: rejected — empty script (by=%s telescope=%s)', requester, telescope)
        return jsonify({'success': False, 'error': 'Script message is empty'}), 400

    # Render the visibility plot fresh, right now, from the exact target list
    # being sent — rather than trusting a plot_url generated earlier in the 3-step
    # confirmation flow. That file lives in a shared folder capped at 10 images
    # (enforce_max_files in astronomy_tools_routes.py); any other /generate_plot
    # call — from any user, anywhere on the site — during the pauses between
    # confirmation steps could evict it before Send actually fires, silently
    # sending the message with no plot attached.
    image_path = _render_trigger_visibility_image(telescope, targets)
    logger.info('daily_trigger_send_message: visibility image=%s', image_path or '(none)')

    try:
        from app.services.planning.trigger_send import mark_sent, send_to_slack
        send_to_slack(greeting, script, image_path=image_path)
        logger.info('daily_trigger_send_message: Slack send call completed by=%s telescope=%s', requester, telescope)
    except Exception:
        logger.exception('daily_trigger_send_message: Slack send failed by=%s telescope=%s', requester, telescope)
        return jsonify({'success': False, 'error': 'Slack send failed; see server log.'}), 500
    finally:
        if image_path:
            try:
                os.unlink(image_path)
                logger.info('daily_trigger_send_message: cleaned up temp image %s', image_path)
            except OSError as e:
                logger.warning('daily_trigger_send_message: could not delete temp image %s: %s', image_path, e)

    sent_by = session['user'].get('name') or session['user'].get('email') or 'unknown'
    if should_mark_sent:
        status = mark_sent(telescope, sent_by, program=program)
        logger.info('daily_trigger_send_message: marked sent telescope=%s program=%s by=%s status=%s', telescope, program, sent_by, status)
    else:
        from app.services.planning.trigger_send import get_send_status
        status = get_send_status()
        logger.info('daily_trigger_send_message: single-target send, not marking telescope status (current=%s)', status)

    # Best-effort: record each triggered target in the Observation Log. A failure
    # here shouldn't be reported as a failed send — the Slack message already went
    # out — so problems are collected as warnings instead of aborting the request.
    log_warnings = _log_triggered_targets(telescope, targets, sent_by)
    logger.info('daily_trigger_send_message: observation log warnings=%s', log_warnings or '(none)')

    return jsonify({'success': True, 'status': status, 'log_warnings': log_warnings})

LOT_CLOSED_CONFIRMS = 3   # times the page asks before a LOT send on a night the Lulin schedule closes LOT


def lot_closed_response(requester, confirmed=None):
    """409 when tonight's Lulin schedule closes LOT to triggers (Lab › Calendar, lab_calendar.lot_closed) and the
    sender has not confirmed it LOT_CLOSED_CONFIRMS times on the page (``confirmed`` = that count), else None."""
    from app.services.lab_calendar import lot_closed_tonight
    closed = lot_closed_tonight()
    if not closed:
        return None
    try:
        confirmed = int(confirmed or 0)
    except (TypeError, ValueError):
        confirmed = 0
    if confirmed >= LOT_CLOSED_CONFIRMS:
        logger.warning('LOT send on a closed night (%s), confirmed %d times by=%s', '; '.join(closed), confirmed,
                       requester)
        return None
    logger.warning('LOT send refused — LOT closed tonight (%s), not confirmed by=%s', '; '.join(closed), requester)
    return jsonify({'success': False, 'lot_closed': closed, 'confirms_needed': LOT_CLOSED_CONFIRMS,
                    'error': f"LOT is closed to triggers tonight (Lulin schedule: {'; '.join(closed)}). "
                             f'Confirm {LOT_CLOSED_CONFIRMS} times to send LOT anyway.'}), 409

def _render_trigger_visibility_image(telescope, targets):
    """Fresh visibility JPG for the targets (trigger_send.render_trigger_plot), in a private temp file the caller
    deletes. None if nothing is plottable or rendering fails — the send still goes through with the text alone."""
    from app.services.planning.trigger_send import render_trigger_plot
    return render_trigger_plot(targets, label=telescope)

def _log_triggered_targets(telescope, targets, sent_by):
    from app.db.obs import upsert_observation_log
    from app.services.planning.trigger_script import exposure_time as _auto_exposure_time
    from app.services.planning.trigger_send import _trigger_day_key

    obs_date = _trigger_day_key()
    warnings = []
    succeeded = []
    skipped = []

    logger.info('log_triggered_targets: start telescope=%s obs_date=%s sent_by=%s target_count=%d',
                telescope, obs_date, sent_by, len(targets))

    for t in targets:
        name = str(t.get('name') or '').strip()
        if not name:
            logger.warning('log_triggered_targets: skipping target with no name: %r', t)
            continue

        try:
            if t.get('auto_exp'):
                exp_map = _auto_exposure_time(t.get('mag'))
                if not isinstance(exp_map, dict):
                    # Invalid/too-faint magnitude — that target's script block was
                    # just a comment, nothing was actually scheduled to trigger.
                    logger.warning('log_triggered_targets: %s skipped — invalid/too-faint mag %r (auto-exp result: %r)',
                                   name, t.get('mag'), exp_map)
                    skipped.append(name)
                    continue
                filter_list = [
                    {'filter': fname, 'exp': int(spec.split('sec*')[0]), 'count': int(spec.split('sec*')[1])}
                    for fname, spec in exp_map.items()
                ]
            else:
                filters = [f.strip() for f in str(t.get('filter_input') or '').split(',') if f.strip()]
                exps = [e.strip() for e in str(t.get('exp_time') or '').split(',') if e.strip()]
                counts = [c.strip() for c in str(t.get('count') or '').split(',') if c.strip()]
                filter_list = [
                    {'filter': f, 'exp': int(exps[i]) if i < len(exps) else 0,
                     'count': int(counts[i]) if i < len(counts) else 1}
                    for i, f in enumerate(filters)
                ]

            trigger_filter_json = json.dumps(filter_list) if filter_list else None

            ok = upsert_observation_log(
                name, obs_date, sent_by, True, False,
                trigger_filter_json, None, None,
                None, None, None,
                priority=t.get('priority') or 'Normal',
                telescope_use=telescope,
                repeat_count=int(t.get('repeat') or 0),
                program=t.get('program') or None,
            )
            if ok:
                logger.info('log_triggered_targets: %s logged ok (priority=%s filters=%s)',
                            name, t.get('priority'), filter_list)
                succeeded.append(name)
            else:
                logger.warning('log_triggered_targets: upsert_observation_log returned falsy for %s', name)
                warnings.append(f'{name}: failed to save log entry')
        except Exception:
            logger.exception('log_triggered_targets: failed for %s', name)
            warnings.append(f'{name}: failed to save log entry')

    logger.info('log_triggered_targets: done telescope=%s succeeded=%s skipped=%s warnings=%s',
                telescope, succeeded, skipped, warnings)
    return warnings
