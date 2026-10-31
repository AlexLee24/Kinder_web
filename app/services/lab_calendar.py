"""Lab calendar (Lab › Calendar): event shaping, repeats, the iCalendar feed and the Lulin schedule sync.

Two sources, one list (rows in obs.lab_calendar_events, app/db/lab_calendar.py):
  lab    events the group adds on the page (meetings, observing runs, deadlines, travel …), may repeat
  lulin  the NCU Lulin LOT schedule — the Google calendar Daily Trigger used to embed. ``sync_lulin()`` copies its
         public iCal feed (LULIN_CALENDAR_ICS) every 6 hours (scheduler job ``lab_calendar_lulin_sync``) and on
         "Sync now"; rows are matched by the Google UID, so edits and removals there show up here.

Members subscribe with a personal secret link (/lab_calendar/feed/<token>.ics); the feed is RFC 5545 text built
here. Dates are Taiwan time (UTC+8, no DST).

Trigger duty (category 'trigger', one member per event, all day; a week of duty is a 7-day event, a rotation of N
people is N events repeating every N weeks): ``send_trigger_reminders()`` runs every 5 minutes (scheduler job
``lab_trigger_reminder``) and, once the Sun has set at Lulin, pushes "Trigger duty tonight" to that member's devices
that take 'trigger' (Web Push) — unless the night's SLT trigger was already sent from Daily Trigger.
Duty weeks run Monday to Sunday: members volunteer for a free week on the page (one 7-day event), and every Friday
``check_duty_weeks()`` (job ``lab_trigger_duty_check``) posts to Slack (SLACK_CHANNEL_ID_TRIGGER_DUTY) when nobody
covers the week after next.
"""
import calendar
import json
import logging
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=8))
SITE_DOMAIN = 'kinder.astro.ncu.edu.tw'

LULIN_ICS_URL = os.getenv(
    'LULIN_CALENDAR_ICS',
    'https://calendar.google.com/calendar/ical/lottac2014%40gm.astro.ncu.edu.tw/public/basic.ics')
LULIN_KEEP_DAYS = 730          # Lulin events older than this are not copied (the feed goes back to 2016)
SYNC_STATUS_KEY = 'lab_calendar:lulin_sync'

# key → label, colour (lc-c-<colour> in lab_calendar.css), source
CATEGORIES = {
    'trigger':   {'label': 'Trigger duty',      'color': 'gold',   'source': 'lab'},
    'meeting':   {'label': 'Group meeting',     'color': 'blue',   'source': 'lab'},
    'observing': {'label': 'Observing',         'color': 'amber',  'source': 'lab'},
    'talk':      {'label': 'Talk / Seminar',    'color': 'purple', 'source': 'lab'},
    'deadline':  {'label': 'Deadline',          'color': 'red',    'source': 'lab'},
    'travel':    {'label': 'Conference / Trip', 'color': 'green',  'source': 'lab'},
    'away':      {'label': 'Leave / Away',      'color': 'slate',  'source': 'lab'},
    'other':     {'label': 'Other',             'color': 'pink',   'source': 'lab'},
    'lulin':     {'label': 'Lulin LOT',         'color': 'teal',   'source': 'lulin'},
}
SOURCES = {'lab': 'GREAT Lab', 'lulin': 'Lulin LOT'}
LAB_CATEGORIES = [k for k, v in CATEGORIES.items() if v['source'] == 'lab']
REPEAT_LABELS = {'': 'Does not repeat', 'weekly': 'Every week', 'biweekly': 'Every 2 weeks', '3weekly': 'Every 3 weeks',
                 '4weekly': 'Every 4 weeks', 'monthly': 'Every month'}
_REPEAT_WEEKS = {'weekly': 1, 'biweekly': 2, '3weekly': 3, '4weekly': 4}
LULIN = ('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)
FEED_NAMES = {None: 'GREAT Lab Calendar', 'lab': 'GREAT Lab Calendar (lab only)', 'lulin': 'Lulin LOT Schedule'}


# ── Occurrences ──

def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _occurrence_starts(row, until):
    """Start datetimes of a row's occurrences up to ``until`` (a date). One for a non-repeating event."""
    st = row['start_at'].astimezone(TZ)
    rep = row.get('repeat') or ''
    if not rep:
        return [st]
    last = min(until, row['repeat_until']) if row.get('repeat_until') else until
    out, i = [], 0
    while i < 1000:
        cur = _add_months(st, i) if rep == 'monthly' else st + timedelta(weeks=i * _REPEAT_WEEKS.get(rep, 1))
        if cur.date() > last:
            break
        out.append(cur)
        i += 1
    return out


def _fmt_time(dt):
    return dt.astimezone(TZ).strftime('%H:%M')


def _item(row, start, today):
    """One occurrence as the dict the page, the JSON API and the feed use."""
    st = start.astimezone(TZ)
    length = row['end_at'] - row['start_at']
    en = (st + length).astimezone(TZ)
    if row['all_day']:
        end_d = (en - timedelta(seconds=1)).date() if en > st else st.date()
        time_label = ''
    else:
        end_d = en.date()
        if en.date() == st.date():
            time_label = f'{_fmt_time(st)}–{_fmt_time(en)}' if en > st else _fmt_time(st)
        else:
            time_label = f'{st.strftime("%m/%d")} {_fmt_time(st)} – {en.strftime("%m/%d")} {_fmt_time(en)}'
    d = st.date()
    end_d = max(end_d, d)
    cat = CATEGORIES.get(row['category']) or CATEGORIES['other']
    rep = row.get('repeat') or ''
    return {
        'id': f"{row['id']}-{d.strftime('%Y%m%d')}" if rep else str(row['id']),
        'db_id': row['id'], 'source': row['source'], 'uid': row.get('uid'),
        'category': row['category'], 'cat': cat,
        'title': row['title'], 'description': row.get('description') or '',
        'location': row.get('location') or '', 'url': row.get('url') or '',
        'all_day': bool(row['all_day']), 'start_at': st, 'end_at': en,
        'd': d, 'end_d': end_d, 'time_label': time_label,
        'repeat': rep, 'repeat_label': REPEAT_LABELS.get(rep, '') if rep else '',
        'repeat_until': row.get('repeat_until'),
        'series_start': row['start_at'].astimezone(TZ), 'series_end': row['end_at'].astimezone(TZ),
        'assignee_email': row.get('assignee_email') or '', 'assignee_name': row.get('assignee_name') or '',
        'created_by': row.get('created_by') or '', 'created_by_name': row.get('created_by_name') or '',
        'days_left': (d - today).days,
        'is_past': end_d < today, 'is_today': d <= today <= end_d,
    }


def events(today=None, past_days=60, future_days=480, source=None):
    """Occurrences from ``past_days`` ago to ``future_days`` ahead, sorted (all-day first within a day)."""
    from app.db import lab_calendar as db
    today = today or datetime.now(TZ).date()
    lo, hi = today - timedelta(days=past_days), today + timedelta(days=future_days)
    out = []
    for row in db.list_events(source=source, since=datetime.combine(lo, datetime.min.time(), TZ)):
        for st in _occurrence_starts(row, hi):
            it = _item(row, st, today)
            if it['end_d'] >= lo and it['d'] <= hi:
                out.append(it)
    out.sort(key=lambda e: (e['d'], 0 if e['all_day'] else 1, e['start_at'], e['source'] != 'lab', e['title']))
    return out


def to_json(e):
    """An occurrence for the page script / JSON API (dates as ISO strings)."""
    return {
        'id': e['id'], 'db_id': e['db_id'], 'source': e['source'], 'category': e['category'],
        'category_label': e['cat']['label'], 'color': e['cat']['color'],
        'title': e['title'], 'description': e['description'], 'location': e['location'], 'url': e['url'],
        'all_day': e['all_day'], 'date': e['d'].isoformat(), 'end_date': e['end_d'].isoformat(),
        'start': e['start_at'].isoformat(), 'end': e['end_at'].isoformat(), 'time_label': e['time_label'],
        'repeat': e['repeat'], 'repeat_label': e['repeat_label'],
        'repeat_until': e['repeat_until'].isoformat() if e['repeat_until'] else '',
        'series_start': e['series_start'].isoformat(), 'series_end': e['series_end'].isoformat(),
        'assignee_email': e['assignee_email'], 'assignee_name': e['assignee_name'],
        'created_by': e['created_by'], 'created_by_name': e['created_by_name'],
        'days_left': e['days_left'], 'is_past': e['is_past'], 'is_today': e['is_today'],
    }


def compact(evs):
    """The page payload: {'series': {db_id: fields shared by every occurrence}, 'occ': [[id, db_id, date, end_date,
    time_label, start, end], …]} — a weekly meeting is sent once, not once per week."""
    series, occ = {}, []
    for e in evs:
        if e['db_id'] not in series:
            j = to_json(e)
            series[e['db_id']] = {k: j[k] for k in (
                'source', 'category', 'category_label', 'color', 'title', 'description', 'location', 'url', 'all_day',
                'repeat', 'repeat_label', 'repeat_until', 'series_start', 'series_end', 'assignee_email',
                'assignee_name', 'created_by', 'created_by_name')}
        occ.append([e['id'], e['db_id'], e['d'].isoformat(), e['end_d'].isoformat(), e['time_label'],
                    e['start_at'].isoformat(), e['end_at'].isoformat()])
    return {'series': series, 'occ': occ}


# ── iCalendar output ──

def _ics_escape(text):
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\n').replace('\n', '\\n')


def _fold(line):
    """RFC 5545: at most 75 octets a line, continuation lines start with one space."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line
    out, cur = [], b''
    for ch in line:
        b = ch.encode('utf-8')
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode('utf-8'))
            cur = b
        else:
            cur += b
    out.append(cur.decode('utf-8'))
    return '\r\n '.join(out)


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def vevent_lines(row, site_root='', alarm_minutes=30):
    """VEVENT lines for one row (a repeating event is one VEVENT with an RRULE)."""
    stamp = _utc(datetime.now(timezone.utc))
    uid = f"lulin-{row['uid']}" if row['source'] == 'lulin' and row.get('uid') else f"lab-{row['id']}@{SITE_DOMAIN}"
    lines = ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{stamp}']
    st, en = row['start_at'].astimezone(TZ), row['end_at'].astimezone(TZ)
    if row['all_day']:
        last = (en - timedelta(seconds=1)).date() if en > st else st.date()
        lines.append(f"DTSTART;VALUE=DATE:{st.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(max(last, st.date()) + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        lines.append(f'DTSTART:{_utc(st)}')
        lines.append(f'DTEND:{_utc(en if en > st else st + timedelta(hours=1))}')
    rep = row.get('repeat') or ''
    if rep:
        rule = 'FREQ=MONTHLY' if rep == 'monthly' else 'FREQ=WEEKLY' + (
            f';INTERVAL={_REPEAT_WEEKS[rep]}' if _REPEAT_WEEKS.get(rep, 1) > 1 else '')
        if row.get('repeat_until'):
            # UNTIL must match DTSTART's type: a date for all-day events, a UTC time (end of that day) otherwise
            ru = row['repeat_until']
            rule += (f";UNTIL={ru.strftime('%Y%m%d')}" if row['all_day']
                     else f";UNTIL={_utc(datetime.combine(ru, datetime.max.time().replace(microsecond=0), TZ))}")
        lines.append(f'RRULE:{rule}')
    cat = CATEGORIES.get(row['category']) or CATEGORIES['other']
    summary = row['title'] if row['source'] == 'lab' else f"LOT: {row['title']}"
    lines.append(f'SUMMARY:{_ics_escape(summary)}')
    desc = row.get('description') or ''
    if row.get('assignee_name'):
        desc = f"On duty: {row['assignee_name']}" + ('\n\n' + desc if desc else '')
    if row['source'] == 'lab' and row.get('created_by_name'):
        desc = (desc + '\n\n' if desc else '') + f"Added by {row['created_by_name']}"
    if desc:
        lines.append(f'DESCRIPTION:{_ics_escape(desc)}')
    if row.get('location'):
        lines.append(f"LOCATION:{_ics_escape(row['location'])}")
    link = row.get('url') or ''
    if link.startswith('/') and site_root:
        link = site_root.rstrip('/') + link
    if link:
        lines.append(f'URL:{link}')
    lines.append(f"CATEGORIES:{_ics_escape(cat['label'])}")
    if row['all_day']:
        lines.append('TRANSP:TRANSPARENT')      # all-day entries do not mark the subscriber busy
    elif alarm_minutes:
        lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_ics_escape(summary)}',
                  f'TRIGGER:-PT{int(alarm_minutes)}M', 'END:VALARM']
    lines.append('END:VEVENT')
    return lines


def _wrap(lines, name=None, refresh='PT1H'):
    head = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//GREAT Lab//Kinder Calendar//EN', 'CALSCALE:GREGORIAN',
            'METHOD:PUBLISH']
    if name:
        head += [f'X-WR-CALNAME:{_ics_escape(name)}', 'X-WR-TIMEZONE:Asia/Taipei',
                 f'REFRESH-INTERVAL;VALUE=DURATION:{refresh}', f'X-PUBLISHED-TTL:{refresh}']
    return '\r\n'.join(_fold(ln) for ln in head + lines + ['END:VCALENDAR']) + '\r\n'


def feed_ics(site_root='', source=None, past_days=400):
    """The whole subscribable calendar (``source`` 'lab' / 'lulin' / None for both)."""
    from app.db import lab_calendar as db
    since = datetime.now(TZ) - timedelta(days=past_days)
    lines = []
    for row in db.list_events(source=source, since=since):
        lines += vevent_lines(row, site_root)
    return _wrap(lines, name=FEED_NAMES[source])


def event_ics(row, site_root=''):
    return _wrap(vevent_lines(row, site_root))


# ── iCalendar input (the Lulin Google calendar) ──

def _unescape(v):
    return re.sub(r'\\([\\;,nN])', lambda m: '\n' if m.group(1) in 'nN' else m.group(1), v)


def _parse_dt(value, params):
    """(datetime, all_day) for a DTSTART/DTEND value."""
    if params.get('VALUE') == 'DATE' or re.fullmatch(r'\d{8}', value):
        d = datetime.strptime(value[:8], '%Y%m%d')
        return d.replace(tzinfo=TZ), True
    if value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc), False
    tz = TZ
    if params.get('TZID'):
        try:
            tz = ZoneInfo(params['TZID'])
        except Exception:
            tz = TZ
    return datetime.strptime(value[:15], '%Y%m%dT%H%M%S').replace(tzinfo=tz), False


def parse_ics(text):
    """VEVENTs of an iCalendar text as dicts (uid, title, description, location, url, all_day, start_at, end_at,
    rrule). Cancelled events are dropped; RRULEs are kept only as a flag (the Lulin calendar has none)."""
    text = re.sub(r'\r?\n[ \t]', '', text.replace('\r\n', '\n'))
    out, cur = [], None
    for line in text.split('\n'):
        if line == 'BEGIN:VEVENT':
            cur = {}
            continue
        if line == 'END:VEVENT':
            if cur is not None:
                out.append(cur)
            cur = None
            continue
        if cur is None or ':' not in line:
            continue
        head, value = line.split(':', 1)
        name, *ps = head.split(';')
        params = dict(p.split('=', 1) for p in ps if '=' in p)
        name = name.upper()
        if name in ('DTSTART', 'DTEND'):
            try:
                cur[name] = _parse_dt(value.strip(), params)
            except ValueError:
                pass
        elif name in ('SUMMARY', 'DESCRIPTION', 'LOCATION', 'UID', 'STATUS', 'URL', 'RRULE'):
            cur[name] = _unescape(value) if name in ('SUMMARY', 'DESCRIPTION', 'LOCATION') else value.strip()
    events_ = []
    for v in out:
        if not v.get('UID') or 'DTSTART' not in v or (v.get('STATUS') or '').upper() == 'CANCELLED':
            continue
        st, all_day = v['DTSTART']
        if 'DTEND' in v:
            en = v['DTEND'][0]
        else:
            en = st + (timedelta(days=1) if all_day else timedelta(0))
        events_.append({
            'uid': v['UID'], 'title': (v.get('SUMMARY') or '').strip() or '(no title)',
            'description': (v.get('DESCRIPTION') or '').strip(), 'location': (v.get('LOCATION') or '').strip(),
            'url': v.get('URL') or '', 'all_day': all_day, 'start_at': st, 'end_at': max(en, st),
            'rrule': v.get('RRULE') or '',
        })
    return events_


_sync_lock = threading.Lock()


def sync_status():
    from app.db.auth import get_setting
    try:
        return json.loads(get_setting(SYNC_STATUS_KEY) or '{}')
    except ValueError:
        return {}


def _save_status(d):
    from app.db.auth import set_setting
    set_setting(SYNC_STATUS_KEY, json.dumps(d))


def sync_lulin():
    """Copy the Lulin LOT Google calendar into obs.lab_calendar_events (source 'lulin').
    Returns {'count', 'added', 'updated', 'removed'} or {'error': ...}; the result is also kept for the page."""
    import requests

    from app.db import lab_calendar as db

    if not _sync_lock.acquire(blocking=False):
        return {'error': 'A sync is already running.'}
    now = datetime.now(timezone.utc)
    try:
        try:
            r = requests.get(LULIN_ICS_URL, timeout=30, headers={'User-Agent': 'Kinder lab calendar'})
            r.raise_for_status()
            if 'BEGIN:VCALENDAR' not in r.text[:200]:
                raise ValueError('the response is not an iCalendar file')
            parsed = parse_ics(r.text)
        except Exception as exc:
            logger.warning('Lulin calendar fetch failed: %s', exc)
            res = {'error': f'Could not read the Lulin calendar: {type(exc).__name__}'}
            _save_status({**sync_status(), 'at': now.isoformat(timespec='seconds'), 'ok': False, 'error': res['error']})
            return res
        cutoff = datetime.now(TZ) - timedelta(days=LULIN_KEEP_DAYS)
        rows = [{**e, 'category': 'lulin'} for e in parsed if e['end_at'] >= cutoff]
        stats = db.replace_source('lulin', rows)
        res = {'count': len(rows), **stats}
        _save_status({'at': now.isoformat(timespec='seconds'), 'ok': True, 'error': '', **res})
        logger.info('Lulin calendar synced: %s', res)
        return res
    finally:
        _sync_lock.release()


def sync_lulin_if_stale(max_age_hours=12):
    """Start a background sync when the last good one is older than ``max_age_hours`` (or never ran).
    For DEBUG / one-process setups where the scheduler job does not run."""
    st = sync_status()
    try:
        last = datetime.fromisoformat(st['at']) if st.get('ok') else None
    except (KeyError, ValueError):
        last = None
    if last and datetime.now(timezone.utc) - last < timedelta(hours=max_age_hours):
        return False
    if _sync_lock.locked():
        return False
    threading.Thread(target=sync_lulin, name='lab-calendar-lulin-sync', daemon=True).start()
    return True


def parse_form(data, members=None):
    """Validate the page's add / edit form. ``members``: {email: name} of the people who can take Trigger duty.
    Returns (fields, error)."""
    category = str(data.get('category') or 'other')
    if category not in LAB_CATEGORIES:
        return None, 'Unknown category.'
    title = str(data.get('title') or '').strip()
    assignee_email = assignee_name = None
    if category == 'trigger':
        assignee_email = str(data.get('assignee') or '').strip()
        if assignee_email not in (members or {}):
            return None, 'Choose who is on Trigger duty.'
        assignee_name = members[assignee_email]
        title = title or f'Trigger: {assignee_name}'
    if not title:
        return None, 'Give the event a title.'
    if len(title) > 200:
        return None, 'The title is too long (200 characters at most).'
    all_day = bool(data.get('all_day')) or category == 'trigger'      # a duty is for whole nights
    try:
        d0 = date.fromisoformat(str(data.get('date') or ''))
        d1 = date.fromisoformat(str(data.get('end_date') or '') or d0.isoformat())
    except ValueError:
        return None, 'Pick a valid date.'
    if all_day:
        if d1 < d0:
            return None, 'The end date is before the start date.'
        if (d1 - d0).days > 366:
            return None, 'An event can last at most a year.'
        start_at = datetime.combine(d0, datetime.min.time(), TZ)
        end_at = datetime.combine(d1 + timedelta(days=1), datetime.min.time(), TZ)
    else:
        try:
            t0 = datetime.strptime(str(data.get('start_time') or ''), '%H:%M').time()
            t1 = datetime.strptime(str(data.get('end_time') or '') or str(data.get('start_time')), '%H:%M').time()
        except ValueError:
            return None, 'Pick a valid time.'
        start_at = datetime.combine(d0, t0, TZ)
        end_at = datetime.combine(d1, t1, TZ)
        if end_at < start_at:
            return None, 'The event ends before it starts.'
        if end_at - start_at > timedelta(days=60):
            return None, 'A timed event can last at most 60 days.'
    repeat = str(data.get('repeat') or '')
    if repeat not in REPEAT_LABELS:
        return None, 'Unknown repeat option.'
    repeat_until = None
    if repeat and data.get('repeat_until'):
        try:
            repeat_until = date.fromisoformat(str(data['repeat_until']))
        except ValueError:
            return None, 'Pick a valid "repeat until" date.'
        if repeat_until < d0:
            return None, '"Repeat until" is before the first day.'
    url = str(data.get('url') or '').strip()
    if url and not re.match(r'^(https?://\S|/(?!/))', url):
        return None, 'The link must start with http:// or https://.'
    return {
        'category': category, 'title': title,
        'description': str(data.get('description') or '').strip()[:4000],
        'location': str(data.get('location') or '').strip()[:300], 'url': url[:1000],
        'all_day': all_day, 'start_at': start_at, 'end_at': end_at,
        'repeat': repeat, 'repeat_until': repeat_until,
        'assignee_email': assignee_email, 'assignee_name': assignee_name,
    }, None


# ── Trigger duty: who is on duty, duty weeks (Mon–Sun), Lulin sunset, the reminder, the Friday check ──

DUTY_SLACK_CHANNEL = os.getenv('SLACK_CHANNEL_ID_TRIGGER_DUTY', 'C06BT4DALM6')
DUTY_CHECK_KEY = 'lab_calendar:duty_check'


def week_monday(day):
    return day - timedelta(days=day.weekday())


def duty_weeks(occurrences, first_monday, n=8):
    """Coverage of ``n`` duty weeks (Monday–Sunday) from ``first_monday``, from the occurrences of ``events()``:
    [{'monday', 'sunday', 'people': [{'email', 'name', 'id', 'db_id', 'repeat', 'whole'}], 'gaps': [dates]}].
    ``whole``: that occurrence is exactly this Monday–Sunday."""
    duty = [e for e in occurrences if e['category'] == 'trigger' and e['assignee_email']]
    weeks = []
    for w in range(n):
        mon = first_monday + timedelta(weeks=w)
        days = [mon + timedelta(days=i) for i in range(7)]
        people, covered = [], set()
        for e in duty:
            on = [d for d in days if e['d'] <= d <= e['end_d']]
            if not on:
                continue
            covered.update(on)
            if not any(p['email'] == e['assignee_email'] for p in people):
                people.append({'email': e['assignee_email'], 'name': e['assignee_name'] or e['assignee_email'],
                               'id': e['id'], 'db_id': e['db_id'], 'repeat': e['repeat'],
                               'whole': e['d'] == mon and e['end_d'] == days[-1]})
        weeks.append({'monday': mon, 'sunday': days[-1], 'people': people,
                      'gaps': [d for d in days if d not in covered]})
    return weeks


def week_label(mon):
    sun = mon + timedelta(days=6)
    if mon.month == sun.month:
        return f"{mon.strftime('%a %-d')} – {sun.strftime('%a %-d %b')}"
    return f"{mon.strftime('%a %-d %b')} – {sun.strftime('%a %-d %b')}"


def _post_slack(channel, text):
    from slack_sdk import WebClient
    token = os.getenv('SLACK_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('SLACK_BOT_TOKEN is not set')
    resp = WebClient(token=token).chat_postMessage(channel=channel, text=text, unfurl_links=False)
    if not resp.get('ok'):
        raise RuntimeError(f"Slack refused the message: {resp.get('error')}")


def check_duty_weeks(today=None, post=True):
    """Fridays: if any night of the week after next (Monday in 10 days) has no Trigger duty, post a reminder to
    the Slack channel asking members to volunteer on Lab › Calendar. Posts at most once a day. Returns what it did."""
    from app.config import config
    from app.db.auth import get_setting, set_setting

    today = today or datetime.now(TZ).date()
    mon = week_monday(today) + timedelta(weeks=2)
    week = duty_weeks(events(today=today, past_days=0, future_days=30), mon, 1)[0]
    res = {'week': mon.isoformat(), 'people': [p['name'] for p in week['people']],
           'gaps': [d.isoformat() for d in week['gaps']], 'posted': False}
    if not week['gaps']:
        return res
    url = f"{config.APP_BASE_URL.rstrip('/')}/lab_calendar"
    if not week['people']:
        text = (f":rotating_light: *Trigger duty needed for {week_label(mon)}*\n"
                f"Nobody has signed up for Trigger duty that week yet. Please pick it up on Kinder: "
                f"<{url}|Lab › Calendar> → Trigger duty → *Volunteer*.")
    else:
        nights = ', '.join(d.strftime('%a %-d %b') for d in week['gaps'])
        text = (f":rotating_light: *Trigger duty still open for {week_label(mon)}*\n"
                f"No one is on duty on {nights}. Please sign up on Kinder: <{url}|Lab › Calendar> → Trigger duty.")
    res['text'] = text
    if not post:
        return res
    if get_setting(DUTY_CHECK_KEY) == today.isoformat():
        res['skipped'] = 'already posted today'
        return res
    _post_slack(DUTY_SLACK_CHANNEL, text)
    set_setting(DUTY_CHECK_KEY, today.isoformat())
    res['posted'] = True
    logger.info('Trigger duty check: posted to %s for the week of %s', DUTY_SLACK_CHANNEL, mon)
    return res


def duty_on(day):
    """Trigger duty occurrences covering ``day`` (a date): [{'email', 'name', 'event_id', 'title'}]."""
    out = []
    for e in events(today=day, past_days=400, future_days=1):
        if e['category'] == 'trigger' and e['assignee_email'] and e['d'] <= day <= e['end_d']:
            if not any(o['email'] == e['assignee_email'] for o in out):
                out.append({'email': e['assignee_email'], 'name': e['assignee_name'] or e['assignee_email'],
                            'event_id': e['db_id'], 'title': e['title']})
    return out


_sunset_cache = {}


def lulin_sunset(day):
    """Sunset at Lulin on ``day`` (Taiwan date) as an aware datetime (UTC+8); cached per day."""
    if day not in _sunset_cache:
        import ephem
        obs = ephem.Observer()
        obs.lon, obs.lat, obs.elevation = LULIN[1], LULIN[2], LULIN[3]
        obs.date = ephem.Date(datetime(day.year, day.month, day.day, 4, 0))       # local noon (04:00 UTC)
        t = obs.next_setting(ephem.Sun()).datetime().replace(tzinfo=timezone.utc)
        if len(_sunset_cache) > 30:
            _sunset_cache.clear()
        _sunset_cache[day] = t.astimezone(TZ)
    return _sunset_cache[day]


def _slt_sent_tonight():
    """True when tonight's SLT trigger was already sent from Daily Trigger."""
    try:
        from app.services.planning.trigger_send import get_send_status
        return bool(get_send_status().get('SLT'))
    except Exception:
        return False


def send_trigger_reminders(now=None, force=False):
    """Push "Trigger duty tonight" to today's duty once the Sun has set at Lulin (until midnight). Each (night,
    member) is handled once. ``force``: ignore the sunset (tests / the admin button). Returns what it did."""
    from app.db import lab_calendar as db
    from app.db.auth import get_user
    from app.services.notifications import webpush

    now = (now or datetime.now(TZ)).astimezone(TZ)
    day = now.date()
    sunset = lulin_sunset(day)
    if not force and now < sunset:
        return {'day': day.isoformat(), 'sunset': sunset.isoformat(timespec='minutes'), 'waiting': True}
    done = []
    for duty in duty_on(day):
        if not db.claim_reminder(day, duty['email'], duty['event_id']):
            continue
        if _slt_sent_tonight():
            db.finish_reminder(day, duty['email'], 'already_sent')
            done.append({**duty, 'outcome': 'already_sent'})
            continue
        user = get_user(duty['email'])
        n = 0
        if user and webpush.enabled():
            first = (duty['name'] or '').split(' ')[0] or 'there'
            n = webpush.send_to_users(
                [user['usr_id']], 'Trigger duty tonight',
                f"Hi {first}, you are on Trigger duty tonight. Sunset at Lulin {sunset.strftime('%H:%M')}: "
                'open Daily Trigger and send the SLT / LOT script.', '/daily_trigger', category='trigger')
        db.finish_reminder(day, duty['email'], 'sent' if n else 'no_device', n)
        logger.info('Trigger duty reminder %s %s: %s device(s)', day, duty['email'], n)
        done.append({**duty, 'outcome': 'sent' if n else 'no_device', 'devices': n})
    return {'day': day.isoformat(), 'sunset': sunset.isoformat(timespec='minutes'), 'reminded': done}
