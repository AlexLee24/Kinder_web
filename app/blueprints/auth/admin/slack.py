"""Admin › Slack (/admin/slack), alongside Admin › Push: post a message of your own to one of Kinder's Slack channels
(or any channel id the bot is in), starting from a blank message or a ready-made one filled with today's data —
open Trigger duty weeks, who is on duty this week, tonight's trigger, members who have not turned push on. Every
message is edited before it goes; the last ones are kept (auth.system_settings ``admin_slack:history``) for Reuse."""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from flask import jsonify, render_template, request, session

from app.core.auth import admin_required, admin_required_page

from . import admin_bp
from .helpers import audit

logger = logging.getLogger(__name__)

# (env key, label, what goes there) — the channels Kinder already posts to.
CHANNELS = [
    ('SLACK_CHANNEL_ID_TRIGGER_DUTY', 'Trigger duty', 'Friday / Sunday duty checks'),
    ('SLACK_CHANNEL_ID_CONTROL_ROOM', 'Control room', 'Daily Trigger; EP alerts at night'),
    ('SLACK_CHANNEL_ID_ToO', 'ToO', 'EP alerts during the Lulin day'),
    ('SLACK_CHANNEL_ID_ALERT', 'Alerts', 'TNS AstroNotes'),
    ('SLACK_CHANNEL_ID_GCN', 'GCN', 'GCN circulars'),
    ('SLACK_CHANNEL_ID_EP_COPY', 'EP copy', 'a copy of every EP alert'),
]
CHANNEL_ID_RE = re.compile(r'^[CGD][A-Z0-9]{6,20}$')
HISTORY_KEY = 'admin_slack:history'
HISTORY_N = 30
MAX_TEXT = 3000


def _channel_id(key):
    if key == 'SLACK_CHANNEL_ID_TRIGGER_DUTY':
        from app.services.lab_calendar import DUTY_SLACK_CHANNEL
        return DUTY_SLACK_CHANNEL
    return os.getenv(key, '').strip()


def _channels():
    return [{'key': k, 'label': label, 'what': what, 'id': _channel_id(k)} for k, label, what in CHANNELS]


def _history():
    from app.db.auth import get_setting
    try:
        return json.loads(get_setting(HISTORY_KEY) or '[]')
    except ValueError:
        return []


def _remember(entry):
    from app.db.auth import set_setting
    set_setting(HISTORY_KEY, json.dumps(([entry] + _history())[:HISTORY_N]))


# ── Ready-made messages (each built from today's data; a failing one says why instead) ──

def _base_url():
    from app.config import config
    return config.APP_BASE_URL.rstrip('/')


def _tpl_duty_open():
    from app.services import lab_calendar as lc
    today = datetime.now(lc.TZ).date()
    first = lc.week_monday(today) + timedelta(weeks=1)
    weeks = lc.duty_weeks(lc.events(today=today, past_days=0, future_days=60), first, 4)
    lines = []
    for w in weeks:
        if not w['gaps']:
            continue
        if not w['people']:
            lines.append(f"• {lc.week_label(w['monday'])}: nobody yet")
        else:
            lines.append(f"• {lc.week_label(w['monday'])}: open on " + ', '.join(d.strftime('%a %-d') for d in w['gaps']))
    url = f'{_base_url()}/lab_calendar'
    if not lines:
        return (f":white_check_mark: *Trigger duty is covered*\nEvery night until {weeks[-1]['sunday'].strftime('%a %-d %b')} "
                f"has someone on Trigger duty. Thank you! Schedule: <{url}|Lab › Calendar>.")
    return (":rotating_light: *Trigger duty: weeks still open*\nThese weeks still need someone on Trigger duty:\n"
            + '\n'.join(lines)
            + f"\nPlease pick one up on Kinder: <{url}|Lab › Calendar> → Trigger duty → *Volunteer*.")


def _tpl_duty_week():
    from app.services import lab_calendar as lc
    today = datetime.now(lc.TZ).date()
    mon = lc.week_monday(today)
    week = lc.duty_weeks(lc.events(today=today, past_days=7, future_days=7), mon, 1)[0]
    who = ', '.join(p['name'] for p in week['people']) or 'nobody yet'
    text = (f":calendar: *Trigger duty this week ({lc.week_label(mon)})*: {who}\n"
            f"Sunset at Lulin tonight {lc.lulin_sunset(today).strftime('%H:%M')}. Kinder pushes the person on duty at sunset.")
    left = [d for d in week['gaps'] if d >= today]        # nights already past do not need anyone now
    if left:
        text += '\nStill open: ' + ', '.join(d.strftime('%a %-d') for d in left) + \
                f" — sign up on <{_base_url()}/lab_calendar|Lab › Calendar>."
    return text


def _tpl_trigger_tonight():
    from app.services import lab_calendar as lc
    today = datetime.now(lc.TZ).date()
    duty = ', '.join(d['name'] for d in lc.duty_on(today)) or 'nobody'
    closed = lc.lot_closed(today)
    what = 'the SLT script' if closed else 'the SLT / LOT script'
    text = (f":telescope: *Tonight's trigger*\nSunset at Lulin {lc.lulin_sunset(today).strftime('%H:%M')}. On duty: {duty}.\n"
            f"Please send {what} from <{_base_url()}/daily_trigger|Daily Trigger>.")
    if closed:
        text += f"\nLOT is closed tonight ({'; '.join(closed)})."
    return text


def _tpl_push_on():
    from .push import _people
    off = []
    for p in _people():           # members without a device; accounts without a real email are not people
        if p['is_member'] and not p['devices'] and not p['placeholder_email'] and p['name'] not in off:
            off.append(p['name'])
    url = _base_url()
    text = (":bell: *Turn on Kinder notifications*\n"
            "Kinder can notify your phone or computer: Trigger duty at sunset, EP alerts, lab events. To turn it on:\n"
            f"1. Open <{url}|Kinder> and sign in.\n"
            "2. iPhone / iPad: in Safari tap Share → *Add to Home Screen*, then open Kinder from that icon "
            "(notifications only work there, iOS 16.4 or later).\n"
            f"3. Go to <{url}/settings#push|Settings → Push notifications> and turn it on.")
    if off:
        text += '\nNot on yet: ' + ', '.join(off) + '.'
    return text


TEMPLATES = [
    # key, label, default channel, builder
    ('duty_open', 'Trigger duty: open weeks', 'SLACK_CHANNEL_ID_TRIGGER_DUTY', _tpl_duty_open),
    ('duty_week', 'Trigger duty: this week', 'SLACK_CHANNEL_ID_TRIGGER_DUTY', _tpl_duty_week),
    ('trigger_tonight', "Tonight's trigger", 'SLACK_CHANNEL_ID_CONTROL_ROOM', _tpl_trigger_tonight),
    ('push_on', 'Turn on notifications', 'SLACK_CHANNEL_ID_CONTROL_ROOM', _tpl_push_on),
]


def _templates():
    out = []
    for key, label, channel, build in TEMPLATES:
        try:
            text = build()
        except Exception as e:
            logger.exception('admin slack template %s', key)
            text = f'(Could not fill this one in: {e})'
        out.append({'key': key, 'label': label, 'channel': channel, 'text': text})
    return out


# ── Routes ──

@admin_bp.route('/admin/slack')
@admin_required_page
def slack_page():
    return render_template('admin_slack.html', current_path='/admin/slack', channels=_channels(),
                           templates=_templates(), history=_history(),
                           slack_on=bool(os.getenv('SLACK_BOT_TOKEN', '').strip()))


@admin_bp.route('/admin/slack/send', methods=['POST'])
@admin_required
def slack_send():
    from slack_sdk import WebClient
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '').strip()
    key = str(data.get('channel') or '')
    if not text:
        return jsonify({'ok': False, 'error': 'Write a message.'}), 400
    if len(text) > MAX_TEXT:
        return jsonify({'ok': False, 'error': f'Keep it under {MAX_TEXT} characters.'}), 400
    if key == 'custom':
        channel, label = str(data.get('channel_id') or '').strip().upper(), 'Other'
        if not CHANNEL_ID_RE.match(channel):
            return jsonify({'ok': False, 'error': 'A channel id looks like C0123ABCD.'}), 400
    else:
        known = {c['key']: c for c in _channels()}
        if key not in known:
            return jsonify({'ok': False, 'error': 'Choose a channel.'}), 400
        channel, label = known[key]['id'], known[key]['label']
        if not channel:
            return jsonify({'ok': False, 'error': f'{key} is not set in kinder.env.'}), 400
    token = os.getenv('SLACK_BOT_TOKEN', '').strip()
    if not token:
        return jsonify({'ok': False, 'error': 'SLACK_BOT_TOKEN is not set on this server.'}), 503
    try:
        resp = WebClient(token=token).chat_postMessage(channel=channel, text=text, unfurl_links=False)
    except Exception as e:
        err = getattr(getattr(e, 'response', None), 'data', {}) or {}
        msg = err.get('error') or str(e)
        audit('slack_send', channel, f'failed={msg}')
        hint = ' Invite the Kinder bot to that channel first.' if msg in ('not_in_channel', 'channel_not_found') else ''
        return jsonify({'ok': False, 'error': f'Slack refused it: {msg}.{hint}'}), 502
    me = (session.get('user') or {}).get('email')
    _remember({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'by': me, 'channel': channel,
               'channel_key': key, 'label': label, 'template': str(data.get('template') or '')[:40], 'text': text})
    audit('slack_send', channel, f'chars={len(text)} template={data.get("template") or "-"}')
    return jsonify({'ok': True, 'channel': label, 'ts': resp.get('ts')})
