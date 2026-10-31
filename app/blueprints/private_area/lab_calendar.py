"""Private area: Lab › Calendar — the group's calendar (meetings, observing runs, deadlines, travel …) together with
the Lulin LOT schedule, which app/services/lab_calendar.py copies from Lulin's Google calendar.

Members add events here (the one who added an event, or an admin, can change or delete it) and subscribe to it in
Google / Apple / Outlook with a personal secret link: /lab_calendar/feed/<token>.ics needs no login, so it checks
that the link's owner may still see the page. Daily Trigger's Calendar button reads /api/lab_calendar/events.
"""
import logging
from datetime import date, datetime, timedelta

from flask import Response, abort, flash, jsonify, redirect, render_template, request, session, url_for

from app.config import config
from app.core import rate_limit

from . import private_area_bp
from .helpers import can_access_page, user_can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'lab_calendar'


def _denied():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Please log in.'}), 401
    if not can_access_page(PAGE_KEY):
        return jsonify({'success': False, 'error': 'Access denied.'}), 403
    return None


def _site_root():
    """Absolute links for the feed: the public address (never the request's Host) outside DEBUG."""
    return (request.host_url if config.DEBUG else config.APP_BASE_URL).rstrip('/')


def _feed_urls(token):
    http = f'{_site_root()}/lab_calendar/feed/{token}.ics'
    return {'http': http, 'webcal': 'webcal://' + http.split('://', 1)[1]}


def _can_edit(row):
    """The one who added it, the member on duty (to swap a Trigger duty) or an admin."""
    u = session.get('user') or {}
    me = (u.get('email') or '').lower()
    return row and row['source'] == 'lab' and (u.get('is_admin') or (row.get('created_by') or '').lower() == me
                                               or (row.get('assignee_email') or '').lower() == me)


def _duty_denied(fields, row=None):
    """Members put only themselves on Trigger duty; admins put anyone. A 403 response, or None when allowed."""
    u = session.get('user') or {}
    if u.get('is_admin'):
        return None
    me = (u.get('email') or '').lower()
    new = (fields.get('assignee_email') or '').lower() if fields.get('category') == 'trigger' else ''
    old = (row.get('assignee_email') or '').lower() if row and row.get('category') == 'trigger' else ''
    if (new and new != me) or (old and old != me and new != old):
        return jsonify({'success': False, 'error': 'Only admins can put someone else on Trigger duty. '
                                                   'Volunteer for a week yourself instead.'}), 403
    return None


def _members():
    """{email: name} of the people who can take Trigger duty: GREAT Lab members and admins, by name."""
    from app.db.auth import get_users
    from app.services.notifications.webpush import is_member
    people = [(e, u.get('display_name') or u.get('name') or e) for e, u in get_users().items()
              if is_member(u) and not u.get('has_placeholder_email')]
    return dict(sorted(people, key=lambda p: p[1].lower()))


@private_area_bp.route('/lab_calendar')
def lab_calendar():
    if 'user' not in session:
        flash('Please log in to see the lab calendar.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page(PAGE_KEY):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    from app.services import lab_calendar as cal

    src = request.args.get('src', 'all')
    if src not in ('all', 'lab', 'lulin'):
        src = 'all'
    kind = request.args.get('type', 'all')
    if kind != 'all' and kind not in cal.CATEGORIES:
        kind = 'all'
    if kind != 'all':
        src = cal.CATEGORIES[kind]['source']
    q = (request.args.get('q') or '').strip()[:100]

    cal.sync_lulin_if_stale()
    today = datetime.now(cal.TZ).date()
    evs = cal.events(today)
    duties = [e for e in evs if e['category'] == 'trigger' and e['end_d'] >= today]
    # the next 8 duty weeks (Monday–Sunday) from this one, from every event (not only the filtered ones)
    duty_weeks = [dict(w, label=cal.week_label(w['monday']), gaps_label=', '.join(d.strftime('%a') for d in w['gaps']))
                  for w in cal.duty_weeks(evs, cal.week_monday(today), 8)]
    reminders = _reminders(today)
    duty_tonight = []                  # one line per member on duty tonight, with how the sunset push went
    for e in duties:
        if e['is_today'] and not any(d['email'] == e['assignee_email'] for d in duty_tonight):
            r = reminders.get((today.isoformat(), e['assignee_email']))
            status = 'reminder at sunset'
            if r:
                status = {'sent': f"reminded on {r['devices']} device{'s' if r['devices'] != 1 else ''}",
                          'already_sent': 'trigger already sent', 'no_device': 'bell only: push off',
                          'pending': 'sending…'}.get(r['outcome'], status)
            duty_tonight.append({'id': e['id'], 'email': e['assignee_email'], 'name': e['assignee_name'],
                                 'status': status, 'ok': bool(r) and r['outcome'] != 'no_device'})
    if src != 'all':
        evs = [e for e in evs if e['source'] == src]
    if kind != 'all':
        evs = [e for e in evs if e['category'] == kind]
    if q:
        ql = q.lower()
        evs = [e for e in evs if any(ql in (e.get(k) or '').lower() for k in ('title', 'description', 'location'))]

    lab_first = lambda e: 0 if e['source'] == 'lab' else 1   # noqa: E731
    today_evs = sorted((e for e in evs if e['is_today']), key=lab_first)
    soon_evs = sorted((e for e in evs if not e['is_today'] and e['days_left'] > 0),
                      key=lambda e: (e['d'], lab_first(e)))[:5]

    # The month view and the list are drawn by lab_calendar.js from one compact payload (each event once, each
    # occurrence as dates only), from the earliest month with an event (or this month) to the last one
    this_month = today.replace(day=1)
    first = min([this_month] + [e['d'].replace(day=1) for e in evs])
    last = max([(this_month + timedelta(days=62)).replace(day=1)] + [e['d'].replace(day=1) for e in evs])

    user = session['user']
    members = _members()
    return render_template(
        'lab_calendar.html', current_path='/lab_calendar',
        today_events=today_evs, soon_events=soon_evs, today_date=today,
        past_n=sum(1 for e in evs if e['is_past']), total=len(evs),
        categories=cal.CATEGORIES, sources=cal.SOURCES, lab_categories=cal.LAB_CATEGORIES,
        repeat_labels=cal.REPEAT_LABELS, src=src, kind=kind, q=q,
        members=members, duty_tonight=duty_tonight,
        duty_choices={e: n for e, n in members.items()
                      if user.get('is_admin') or e.lower() == (user.get('email') or '').lower()},
        duty_weeks=duty_weeks, sunset_today=cal.lulin_sunset(today).strftime('%H:%M'),
        cal_data={**cal.compact(evs), 'today': today.isoformat(), 'this_month': this_month.strftime('%Y-%m'),
                  'first_month': first.strftime('%Y-%m'), 'last_month': last.strftime('%Y-%m'),
                  'sunset_today': cal.lulin_sunset(today).strftime('%H:%M'),
                  'reminders': {f'{d}|{e}': r for (d, e), r in reminders.items()}},
        sync=cal.sync_status(), user_email=user.get('email') or '', is_admin=bool(user.get('is_admin')))


def _reminders(today):
    from app.db import lab_calendar as db
    try:
        return db.reminders_since(today - timedelta(days=60))
    except Exception:
        logger.exception('lab calendar: reminders not read')
        return {}


@private_area_bp.route('/api/lab_calendar/events')
def api_lab_calendar_events():
    """Occurrences between ?from and ?to (YYYY-MM-DD, default today … +14 days); ?src=lab|lulin."""
    denied = _denied()
    if denied:
        return denied
    from app.services import lab_calendar as cal
    today = datetime.now(cal.TZ).date()
    try:
        lo = date.fromisoformat(request.args.get('from') or today.isoformat())
        hi = date.fromisoformat(request.args.get('to') or (today + timedelta(days=14)).isoformat())
    except ValueError:
        return jsonify({'success': False, 'error': 'from / to must be YYYY-MM-DD'}), 400
    if hi < lo or (hi - lo).days > 400:
        return jsonify({'success': False, 'error': 'The range must be 0–400 days.'}), 400
    src = request.args.get('src')
    evs = cal.events(today, past_days=max(0, (today - lo).days), future_days=max(0, (hi - today).days),
                     source=src if src in cal.SOURCES else None)
    evs = [e for e in evs if e['end_d'] >= lo and e['d'] <= hi]
    return jsonify({'success': True, 'today': today.isoformat(), 'events': [cal.to_json(e) for e in evs],
                    'sync': cal.sync_status()})


@private_area_bp.route('/api/lab_calendar/events', methods=['POST'])
def api_lab_calendar_add():
    denied = _denied()
    if denied:
        return denied
    from app.db import lab_calendar as db
    from app.services import lab_calendar as cal
    fields, err = cal.parse_form(request.get_json(silent=True) or {}, _members())
    if err:
        return jsonify({'success': False, 'error': err}), 400
    duty = _duty_denied(fields)
    if duty:
        return duty
    u = session['user']
    new_id = db.add_event(fields, u.get('email'), u.get('name') or u.get('email') or '')
    logger.info('audit action=lab_calendar_add actor=%s target=%s title=%r', u.get('email'), new_id, fields['title'])
    return jsonify({'success': True, 'id': new_id})


@private_area_bp.route('/api/lab_calendar/events/<int:event_id>', methods=['POST', 'DELETE'])
def api_lab_calendar_change(event_id):
    denied = _denied()
    if denied:
        return denied
    from app.db import lab_calendar as db
    from app.services import lab_calendar as cal
    row = db.get_event(event_id)
    if not row or row['source'] != 'lab':
        return jsonify({'success': False, 'error': 'No such event.'}), 404
    if not _can_edit(row):
        return jsonify({'success': False, 'error': 'Only the person who added it (or an admin) can change it.'}), 403
    who = session['user'].get('email')
    if request.method == 'DELETE':
        db.delete_event(event_id)
        logger.info('audit action=lab_calendar_delete actor=%s target=%s title=%r', who, event_id, row['title'])
        return jsonify({'success': True})
    fields, err = cal.parse_form(request.get_json(silent=True) or {}, _members())
    if err:
        return jsonify({'success': False, 'error': err}), 400
    duty = _duty_denied(fields, row)
    if duty:
        return duty
    db.update_event(event_id, fields)
    logger.info('audit action=lab_calendar_edit actor=%s target=%s', who, event_id)
    return jsonify({'success': True})


@private_area_bp.route('/api/lab_calendar/volunteer', methods=['POST'])
def api_lab_calendar_volunteer():
    """Put someone on Trigger duty for one week: {"week": "<its Monday>", "assignee": email, "replace": bool}.
    Members volunteer themselves for a free week (no assignee); admins may name any member, and with ``replace`` hand
    a taken week to someone else (only single-week duties: a rotation is edited as a whole). Creates one
    Monday–Sunday event. Withdraw = delete that event (the member on duty may)."""
    denied = _denied()
    if denied:
        return denied
    from app.db import lab_calendar as db
    from app.services import lab_calendar as cal
    u = session['user']
    is_admin = bool(u.get('is_admin'))
    data = request.get_json(silent=True) or {}
    members = _members()
    me = next((e for e in members if e.lower() == (u.get('email') or '').lower()), None)
    want = str(data.get('assignee') or '') or me
    email = next((e for e in members if e.lower() == want.lower()), None)
    if not email:
        if data.get('assignee'):
            return jsonify({'success': False, 'error': 'Pick a GREAT Lab member.'}), 400
        return jsonify({'success': False, 'error': 'Only GREAT Lab members take Trigger duty.'}), 403
    if email != me and not is_admin:
        return jsonify({'success': False, 'error': 'Only admins can put someone else on Trigger duty.'}), 403
    try:
        mon = date.fromisoformat(str(data.get('week') or ''))
    except ValueError:
        return jsonify({'success': False, 'error': 'Pick a week.'}), 400
    today = datetime.now(cal.TZ).date()
    if mon.weekday() != 0 or mon + timedelta(days=6) < today or mon > today + timedelta(weeks=26):
        return jsonify({'success': False, 'error': 'Pick a week (Monday) from this week to six months ahead.'}), 400
    week = cal.duty_weeks(cal.events(today=today, past_days=7, future_days=200), mon, 1)[0]
    if week['people']:
        names = ', '.join(p['name'] for p in week['people'])
        if not (is_admin and data.get('replace')):
            return jsonify({'success': False, 'error': f'{names} already has duty that week.'}), 409
        if any(p['repeat'] or not p['whole'] for p in week['people']):
            return jsonify({'success': False, 'error': f'{names} has that week as part of a rotation: open the event '
                                                       'and edit the rotation instead.'}), 409
        for p in week['people']:
            db.delete_event(p['db_id'])
    name = members[email]
    me_name = u.get('name') or u.get('email') or ''
    new_id = db.add_event({
        'category': 'trigger', 'title': f'Trigger: {name}', 'all_day': True,
        'start_at': datetime.combine(mon, datetime.min.time(), cal.TZ),
        'end_at': datetime.combine(mon + timedelta(days=7), datetime.min.time(), cal.TZ),
        'repeat': '', 'repeat_until': None, 'assignee_email': email, 'assignee_name': name,
    }, u.get('email'), me_name)
    logger.info('audit action=lab_calendar_%s actor=%s target=%s week=%s assignee=%s',
                'volunteer' if email == me else 'assign_duty', u.get('email'), new_id, mon, email)
    return jsonify({'success': True, 'id': new_id, 'name': name})


@private_area_bp.route('/api/lab_calendar/sync', methods=['POST'])
def api_lab_calendar_sync():
    """Copy the Lulin schedule now (also every 6 hours on the server)."""
    denied = _denied()
    if denied:
        return denied
    if not rate_limit.allow(f"lab_calendar_sync:{session['user'].get('email')}", 3, 60):
        return jsonify({'success': False, 'error': 'Please wait a minute before syncing again.'}), 429
    from app.services import lab_calendar as cal
    res = cal.sync_lulin()
    if res.get('error'):
        return jsonify({'success': False, 'error': res['error']}), 502
    return jsonify({'success': True, **res, 'sync': cal.sync_status()})


@private_area_bp.route('/api/lab_calendar/feed_link', methods=['POST'])
def api_lab_calendar_feed_link():
    """The member's personal subscription link; {"reset": true} replaces it (the old one stops working)."""
    denied = _denied()
    if denied:
        return denied
    from app.db import lab_calendar as db
    reset = bool((request.get_json(silent=True) or {}).get('reset'))
    token = db.feed_token(session['user']['email'], reset=reset)
    if reset:
        logger.info('audit action=lab_calendar_feed_reset actor=%s', session['user']['email'])
    return jsonify({'success': True, **_feed_urls(token)})


@private_area_bp.route('/lab_calendar/feed/<token>.ics')
def lab_calendar_feed(token):
    """The subscription feed (no login: calendar apps fetch it). ?src=lab|lulin narrows it to one source."""
    from app.db import lab_calendar as db
    from app.db.auth import get_user
    from app.services import lab_calendar as cal
    if not rate_limit.allow(f'lab_calendar_feed:{request.remote_addr}', 120, 3600):
        abort(429)
    email = db.email_for_token(token) if 16 <= len(token) <= 64 else None
    user = get_user(email) if email else None
    if not user or not user_can_access_page(user, PAGE_KEY):
        abort(404)
    src = request.args.get('src')
    body = cal.feed_ics(_site_root(), source=src if src in cal.SOURCES else None)
    resp = Response(body, content_type='text/calendar; charset=utf-8')
    resp.headers['Content-Disposition'] = 'inline; filename="great-lab-calendar.ics"'
    resp.headers['Cache-Control'] = 'private, max-age=900'
    return resp


@private_area_bp.route('/lab_calendar/event/<int:event_id>.ics')
def lab_calendar_event_ics(event_id):
    """One event (a repeating one with its repeat rule) as a file to import."""
    if 'user' not in session or not can_access_page(PAGE_KEY):
        abort(404)
    from app.db import lab_calendar as db
    from app.services import lab_calendar as cal
    row = db.get_event(event_id)
    if not row:
        abort(404)
    resp = Response(cal.event_ics(row, _site_root()), content_type='text/calendar; charset=utf-8')
    resp.headers['Content-Disposition'] = f'attachment; filename="lab-event-{event_id}.ics"'
    return resp
