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

    # Tonight's Trigger duty from Lab › Calendar (the trigger night turns over at 08:00)
    duty = []
    try:
        from datetime import date as _date

        from app.services import lab_calendar
        from app.services.planning.trigger_send import _trigger_day_key
        duty = lab_calendar.duty_on(_date.fromisoformat(_trigger_day_key()))
    except Exception:
        logger.exception('daily_trigger: Trigger duty not read')

    return render_template('daily_trigger.html', current_path='/daily_trigger', all_groups=all_groups,
                            user_display_name=user_display_name, user_email=user_email,
                            app_debug=config.DEBUG, duty=duty,
                            on_duty=any(d['email'].lower() == user_email.lower() for d in duty))

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
