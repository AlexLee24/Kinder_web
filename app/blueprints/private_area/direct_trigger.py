"""Private area: Direct Trigger — tonight's change of plan.

A short target list per telescope, kept apart from the Daily Trigger targets,
that is turned into an ACP script and sent to the Control Room straight away.
The script is always built on the server from the stored list (never from text
the browser sends), and sending reuses the Daily Trigger pieces: the visibility
plot, the Slack post and the Observation Log entry. It does not mark the Daily
Trigger as sent.
"""
import logging
import os

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from . import private_area_bp
from .helpers import can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'direct_trigger'
TELESCOPES = ('SLT', 'LOT')
PRIORITIES = ('Normal', 'High', 'Urgent')
FILTERS = ('up', 'gp', 'rp', 'ip', 'zp')      # the codes trigger_script understands
MAX_TARGETS_PER_TELESCOPE = 40


def _denied():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Please log in.'}), 401
    if not can_access_page(PAGE_KEY):
        return jsonify({'success': False, 'error': 'Access denied.'}), 403
    return None


def _telescope(value):
    tel = str(value or '').strip().upper()
    return tel if tel in TELESCOPES else None


def _actor():
    user = session.get('user') or {}
    return user.get('name') or user.get('email') or 'unknown'


@private_area_bp.route('/direct_trigger')
def direct_trigger():
    if 'user' not in session:
        flash('Please log in to use Direct Trigger.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page(PAGE_KEY):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    from app.services.lab_calendar import lot_closed_tonight
    return render_template('direct_trigger.html', current_path='/direct_trigger',
                           filters=FILTERS, priorities=PRIORITIES, lot_closed=lot_closed_tonight())


@private_area_bp.route('/api/direct_trigger/targets', methods=['GET'])
def direct_trigger_list():
    denied = _denied()
    if denied:
        return denied
    from app.db.obs import list_direct_trigger_targets
    tel = _telescope(request.args.get('telescope'))
    try:
        return jsonify({'success': True, 'targets': list_direct_trigger_targets(tel)})
    except Exception:
        logger.exception('direct_trigger_list failed')
        return jsonify({'success': False, 'error': 'Could not load the list.'}), 500


def _validate_target(data):
    """Return (clean_dict, None) or (None, error message)."""
    from app.services.planning import obsplan as obs
    from app.services.planning.trigger_script import exposure_time

    tel = _telescope(data.get('telescope'))
    if not tel:
        return None, 'Choose SLT or LOT.'
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 64:
        return None, 'Target name is required (max 64 characters).'
    ra = str(data.get('ra') or '').strip()
    dec = str(data.get('dec') or '').strip()
    if not ra or not dec or len(ra) > 40 or len(dec) > 40:
        return None, 'RA and Dec are required.'
    try:
        obs.create_ephem_target(name, ra, dec)
    except Exception:
        return None, 'Could not read the coordinates. Use h:m:s / d:m:s or decimal degrees.'

    mag = str(data.get('mag') or '').strip()[:16]
    priority = str(data.get('priority') or 'Normal').strip()
    if priority not in PRIORITIES:
        return None, 'Priority must be Normal, High or Urgent.'
    try:
        repeat = int(data.get('repeat_count') or 0)
    except (TypeError, ValueError):
        return None, 'Repeat must be a whole number.'
    if not 0 <= repeat <= 20:
        return None, 'Repeat must be between 0 and 20.'
    note = str(data.get('note') or '').strip()[:200]
    program = str(data.get('program') or '').strip()[:32] if tel == 'LOT' else ''

    auto_exp = bool(data.get('auto_exp'))
    filters = []
    if auto_exp:
        if not isinstance(exposure_time(mag), dict):
            return None, 'Auto exposure needs a magnitude between 12 and 22.'
    else:
        rows = data.get('filters')
        if not isinstance(rows, list) or not rows or len(rows) > 10:
            return None, 'Add at least one filter, or use auto exposure.'
        for row in rows:
            if not isinstance(row, dict):
                return None, 'Invalid filter row.'
            f = str(row.get('filter') or '').strip()
            try:
                exp = int(row.get('exp'))
                count = int(row.get('count'))
            except (TypeError, ValueError):
                return None, 'Exposure and count must be whole numbers.'
            if f not in FILTERS:
                return None, f'Unknown filter "{f}".'
            if not 1 <= exp <= 3600 or not 1 <= count <= 50:
                return None, 'Exposure must be 1–3600 s and count 1–50.'
            filters.append({'filter': f, 'exp': exp, 'count': count})

    return {'telescope': tel, 'name': name, 'ra': ra, 'dec': dec, 'mag': mag,
            'priority': priority, 'repeat_count': repeat, 'note': note,
            'program': program, 'auto_exp': auto_exp, 'filters': filters}, None


@private_area_bp.route('/api/direct_trigger/targets', methods=['POST'])
def direct_trigger_add():
    denied = _denied()
    if denied:
        return denied
    from app.db.obs import add_direct_trigger_target, list_direct_trigger_targets
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Invalid request.'}), 400
    clean, error = _validate_target(data)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    try:
        if len(list_direct_trigger_targets(clean['telescope'])) >= MAX_TARGETS_PER_TELESCOPE:
            return jsonify({'success': False,
                            'error': f'The {clean["telescope"]} list is full ({MAX_TARGETS_PER_TELESCOPE}).'}), 400
        clean['created_by'] = _actor()
        row = add_direct_trigger_target(clean)
    except Exception:
        logger.exception('direct_trigger_add failed')
        return jsonify({'success': False, 'error': 'Could not save the target.'}), 500
    logger.info('direct_trigger_add: %s added %s to %s', clean['created_by'], clean['name'], clean['telescope'])
    return jsonify({'success': True, 'target': row})


@private_area_bp.route('/api/direct_trigger/targets/<int:target_id>', methods=['DELETE'])
def direct_trigger_delete(target_id):
    denied = _denied()
    if denied:
        return denied
    from app.db.obs import delete_direct_trigger_target
    try:
        ok = delete_direct_trigger_target(target_id)
    except Exception:
        logger.exception('direct_trigger_delete failed')
        return jsonify({'success': False, 'error': 'Could not remove the target.'}), 500
    if not ok:
        return jsonify({'success': False, 'error': 'Target not found.'}), 404
    logger.info('direct_trigger_delete: %s removed id=%s', _actor(), target_id)
    return jsonify({'success': True})


@private_area_bp.route('/api/direct_trigger/clear', methods=['POST'])
def direct_trigger_clear():
    denied = _denied()
    if denied:
        return denied
    from app.db.obs import clear_direct_trigger_targets
    tel = _telescope((request.get_json(silent=True) or {}).get('telescope'))
    if not tel:
        return jsonify({'success': False, 'error': 'Choose SLT or LOT.'}), 400
    try:
        n = clear_direct_trigger_targets(tel)
    except Exception:
        logger.exception('direct_trigger_clear failed')
        return jsonify({'success': False, 'error': 'Could not clear the list.'}), 500
    logger.info('direct_trigger_clear: %s cleared %d %s target(s)', _actor(), n, tel)
    return jsonify({'success': True, 'removed': n})


def _script_payload(rows):
    """Stored rows -> the target dicts trigger_script / the observation log expect."""
    out = []
    for t in rows:
        item = {
            'name': t['name'], 'ra': t['ra'], 'dec': t['dec'], 'mag': t.get('mag') or '',
            'priority': t.get('priority') or 'Normal',
            'priority_message': t.get('note') or '',
            'repeat': t.get('repeat_count') or 0,
            'auto_exp': bool(t.get('auto_exp')),
            'program': t.get('program') or '',
        }
        if not item['auto_exp'] and t.get('filters'):
            item['filter_input'] = ','.join(f['filter'] for f in t['filters'])
            item['exp_time'] = ','.join(str(f['exp']) for f in t['filters'])
            item['count'] = ','.join(str(f['count']) for f in t['filters'])
        out.append(item)
    order = {p: i for i, p in enumerate(('Urgent', 'High', 'Normal'))}
    out.sort(key=lambda t: (order.get(t['priority'], 9), t['name'].lower()))
    return out


def _greeting(telescope, programs):
    zh_prog = f' "{", ".join(programs)}"' if programs else ''
    en_prog = f' "{", ".join(programs)}"' if programs else ''
    return (f'您好，若天氣允許使用 {telescope}，以下為今晚臨時調整的{zh_prog}觀測目標:\n'
            f'If the weather permits to use {telescope}, here are tonight\'s updated{en_prog} '
            f'observation targets:\n\n')


def _build_message(telescope):
    """Return (rows, payload, greeting, script) for the stored list, or raise ValueError."""
    from app.db.obs import list_direct_trigger_targets
    from app.services.planning import trigger_script

    rows = list_direct_trigger_targets(telescope)
    if not rows:
        raise ValueError(f'The {telescope} list is empty.')
    payload = _script_payload(rows)
    programs = sorted({t['program'] for t in payload if t['program']}) if telescope == 'LOT' else []
    script = trigger_script.generate_full_script(payload, telescope)
    return rows, payload, _greeting(telescope, programs), script


@private_area_bp.route('/api/direct_trigger/preview', methods=['POST'])
def direct_trigger_preview():
    denied = _denied()
    if denied:
        return denied
    tel = _telescope((request.get_json(silent=True) or {}).get('telescope'))
    if not tel:
        return jsonify({'success': False, 'error': 'Choose SLT or LOT.'}), 400
    try:
        _rows, payload, greeting, script = _build_message(tel)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception:
        logger.exception('direct_trigger_preview failed')
        return jsonify({'success': False, 'error': 'Could not build the script.'}), 500
    return jsonify({'success': True, 'greeting': greeting, 'script': script, 'count': len(payload)})


@private_area_bp.route('/api/direct_trigger/send', methods=['POST'])
def direct_trigger_send():
    denied = _denied()
    if denied:
        return denied
    from app.db.obs import mark_direct_trigger_sent
    from app.services.planning.trigger_send import send_to_slack

    from .daily_trigger import _log_triggered_targets, _render_trigger_visibility_image, lot_closed_response

    tel = _telescope((request.get_json(silent=True) or {}).get('telescope'))
    if not tel:
        return jsonify({'success': False, 'error': 'Choose SLT or LOT.'}), 400
    if tel == 'LOT':
        denied = lot_closed_response(_actor())
        if denied:
            return denied
    try:
        rows, payload, greeting, script = _build_message(tel)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception:
        logger.exception('direct_trigger_send: building the script failed')
        return jsonify({'success': False, 'error': 'Could not build the script.'}), 500

    sent_by = _actor()
    logger.info('direct_trigger_send: by=%s telescope=%s targets=%s',
                sent_by, tel, [t['name'] for t in payload])
    image_path = _render_trigger_visibility_image(tel, payload)
    try:
        send_to_slack(greeting, script, image_path=image_path)
    except Exception:
        logger.exception('direct_trigger_send: Slack send failed by=%s telescope=%s', sent_by, tel)
        return jsonify({'success': False, 'error': 'Slack send failed; see the server log.'}), 500
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except OSError:
                pass

    try:
        mark_direct_trigger_sent([r['id'] for r in rows])
    except Exception:
        logger.exception('direct_trigger_send: could not record send time')
    warnings = _log_triggered_targets(tel, payload, sent_by)
    return jsonify({'success': True, 'sent': len(payload), 'log_warnings': warnings})
