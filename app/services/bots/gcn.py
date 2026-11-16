"""GCN bot: one Kafka consumer for GCN circulars and Einstein Probe WXT alerts (was lab_bot gcn.py + EP.py).

    gcn.circulars                          → Slack SLACK_CHANNEL_ID_GCN
    gcn.notices.einstein_probe.wxt.alert   → name EPt<yymmdd><a,b,…>, SLT script, Lulin visibility plot;
                                             judged like alert-run (robot.plan_night): observable now or later
                                             tonight → SLACK_CHANNEL_ID_CONTROL_ROOM with the script alert-run
                                             carries (#COUNT cut to the window); too low → SLACK_CHANNEL_ID_ToO
                                             (hand script only if it gets above 20°); bilingual text;
                                             both also to SLACK_CHANNEL_ID_EP_COPY when set; email to EP_EMAIL_TO;
                                             first of all published for the Lulin robot (robot.py), then pushed
                                             to GREAT Lab members' devices that take 'alerts' (Web Push)

Started by ``start()`` as a daemon thread in the background-jobs process. Credentials and channels from kinder.env.
Outputs in app/data/: gcn.json / ep.json (latest alerts), ep_observing_track.jpg, target_objects.txt (EP names),
bots/gcn_sent_ids.json (alerts already posted, so a restart never posts one twice).
"""
import json
import os
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.paths import DATA_DIR

from . import status

BOT = 'gcn'
log = status.get_logger(BOT)

GCN_JSON = DATA_DIR / 'gcn.json'
EP_JSON = DATA_DIR / 'ep.json'
PLOT_PATH = DATA_DIR / 'ep_observing_track.jpg'
TARGETS_FILE = DATA_DIR / 'target_objects.txt'
SENT_IDS_FILE = DATA_DIR / 'bots' / 'gcn_sent_ids.json'
MAX_ENTRIES = 20
MAX_SENT_IDS = 5000
HEARTBEAT_EVERY = 60
STALL_AFTER = 300            # watchdog: a listener that has not gone round its loop for this long is hung and replaced
TOPICS = ['gcn.circulars', 'gcn.notices.einstein_probe.wxt.alert']
DEFAULT_EP_EMAIL_TO = 'kinder@astro.ncu.edu.tw,amar@astro.ncu.edu.tw'


def _env(key, default=''):
    return (os.environ.get(key) or default).strip()


# ── small stores ──────────────────────────────────────────────────────────────

def _load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w') as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _append_entry(path, entry):
    entries = _load_json(path, [])
    entries = (entries if isinstance(entries, list) else []) + [entry]
    _save_json(path, entries[-MAX_ENTRIES:])


class _SentIds:
    """Alerts already posted (lab_bot's gcn_sent_ids.json format: 'circular_<id>', 'ep_<trigger time>' …)."""

    def __init__(self):
        ids = _load_json(SENT_IDS_FILE, [])
        self.ids = list(ids) if isinstance(ids, list) else []
        self.seen = set(self.ids)
        nums = [int(i.rsplit('_', 1)[-1]) for i in self.ids if isinstance(i, str) and i.startswith('circular_')
                and i.rsplit('_', 1)[-1].isdigit()]
        self.max_circular = max(nums, default=-1)

    def add(self, uid):
        if uid in self.seen:
            return
        self.seen.add(uid)
        self.ids.append(uid)
        self.ids = self.ids[-MAX_SENT_IDS:]
        try:
            _save_json(SENT_IDS_FILE, self.ids)
        except OSError as e:
            log.warning('Could not save sent ids: %s', e)


# ── Slack / email ─────────────────────────────────────────────────────────────

def _send_slack(client, channel, text, file_path=None):
    if not channel:
        return False
    from slack_sdk.errors import SlackApiError
    try:
        client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as e:
        status.event(BOT, f'Slack post to {channel} failed: {e.response.get("error")}', level='error', count=False)
        return False
    if file_path and os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
        try:
            client.files_upload_v2(channel=channel, file=str(file_path))
        except SlackApiError as e:
            log.warning('Slack plot upload to %s failed: %s', channel, e.response.get('error'))
    return True


def _send_email(subject, body):
    sender, password = _env('SENDER_EMAIL'), _env('SENDER_PASSWORD')
    receivers = [r.strip() for r in _env('EP_EMAIL_TO', DEFAULT_EP_EMAIL_TO).split(',') if r.strip()]
    if not (sender and password and receivers):
        log.warning('EP email skipped: SENDER_EMAIL / SENDER_PASSWORD / EP_EMAIL_TO not set')
        return
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = ', '.join(receivers)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        with smtplib.SMTP(_env('SMTP_SERVER', 'smtp.gmail.com'), int(_env('SMTP_PORT', '587'))) as srv:
            srv.starttls()
            srv.login(sender, password)
            srv.sendmail(sender, receivers, msg.as_string())
        log.info('EP email sent to %s', ', '.join(receivers))
    except Exception as e:
        status.event(BOT, f'EP email failed: {e}', level='error', count=False)


# ── GCN circulars ─────────────────────────────────────────────────────────────

def _remove_skymap(obj):
    if isinstance(obj, dict):
        for k in [k for k in obj if 'skymap' in k.lower()]:
            del obj[k]
        for v in obj.values():
            _remove_skymap(v)
    elif isinstance(obj, list):
        for v in obj:
            _remove_skymap(v)


def format_circular(data):
    """Slack text of a circular (lab_bot gcn.py format)."""
    _remove_skymap(data)
    lines = []
    if 'subject' in data and 'body' in data:
        if 'circularId' in data:
            lines.append(f"===================== *Circular ID:* {data['circularId']} =====================")
        lines.append(f"*{data.get('subject')}*")
        if 'eventId' in data:
            lines.append(f"*Event ID:* {data['eventId']}")
        if 'submitter' in data:
            lines.append(f"*Submitter:* {data['submitter']}")
        lines.append(f"\n{data['body']}")
    else:
        for key, val in data.items():
            if key == '$schema':
                continue
            if isinstance(val, (dict, list)):
                lines.append(f"*{key}:*\n```\n{json.dumps(val, indent=2)}\n```")
            else:
                lines.append(f'*{key}:* {val}')
    return '\n'.join(lines)


def _alert_uid(data, topic, offset):
    for key, prefix in (('circularId', 'circular'), ('trigger_num', 'trigger'), ('id', 'id')):
        if key in data:
            return f'{prefix}_{data[key]}'
    return f'{topic}_{offset}'


def handle_circular(raw, client, sent, offset=None):
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {}
    uid = _alert_uid(data, 'gcn.circulars', offset)
    cid = data.get('circularId')
    try:
        cid_num = int(cid)
    except (TypeError, ValueError):
        cid_num = None
    if cid_num is not None and cid_num < sent.max_circular:
        log.info('Skip older circular %s (newest posted: %s)', cid_num, sent.max_circular)
        return
    if uid in sent.seen:
        log.info('Skip circular already posted: %s', uid)
        return
    text = format_circular(data) if data else raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
    _send_slack(client, _env('SLACK_CHANNEL_ID_GCN'), text)
    sent.add(uid)
    if cid_num is not None:
        sent.max_circular = max(sent.max_circular, cid_num)
    _append_entry(GCN_JSON, {'received_at': status.now_iso(), 'circularId': cid, 'subject': data.get('subject', ''),
                             'text': text[:2000]})
    status.event(BOT, f"Circular {cid or uid}: {data.get('subject', '(no subject)')}")


# ── Einstein Probe ────────────────────────────────────────────────────────────

def _next_ep_name(yymmdd):
    """EPt<yymmdd><a, b, …>: the letter counts this UTC day's names already in target_objects.txt."""
    names = _target_names()
    n = sum(1 for t in names if t.startswith(f'EPt{yymmdd}'))
    return f'EPt{yymmdd}{chr(ord("a") + n)}'


def _target_names():
    try:
        with open(TARGETS_FILE, encoding='utf-8') as fh:
            return [ln.strip() for ln in fh if ln.strip() and not ln.startswith('#')]
    except OSError:
        return []


def _add_target(name):
    if name in _target_names():
        return
    os.makedirs(os.path.dirname(TARGETS_FILE), exist_ok=True)
    with open(TARGETS_FILE, 'a', encoding='utf-8') as fh:
        if fh.tell() == 0:
            fh.write('# 觀測目標清單 - 自動更新\n# 格式: 每行一個目標名稱\n\n')
        fh.write(f'{name}\n')


def slt_script(name, ra, dec):
    return (';===SLT URGENT Priority!!===\n\n'
            '#BINNING 1\n'
            '#FILTER rp_Astrodon_2018\n'
            '#INTERVAL 300\n'
            '#COUNT 24\n'
            ';# mag: >22 mag\n'
            f'{name}\t{ra}\t{dec}\n'
            '#WAITFOR 1\n')


_NOTE = ('Note: This is an auto message. If observed, or for anything urgent, please call Janet or Amar on Slack '
         '(or by phone). LOT may also observe it; please wait for confirmation and use SLT first.\n'
         '註：這是自動訊息。觀測了或有任何緊急狀況，請在 Slack（或用手機）打給 Janet 或 Amar。'
         'LOT 可能也會觀測，詳細請等待人員確認，先用 SLT 觀測，謝謝！')
_RUN_API = '/api/v1/robot/alert-run'


def _tw(dt):
    """HH:MM at Lulin (UTC+8)."""
    from datetime import timedelta
    return (dt + timedelta(hours=8)).strftime('%H:%M')


def _hours(seconds):
    return f'≈ {seconds / 60:.0f} min' if seconds < 5400 else f'≈ {seconds / 3600:.1f} h'


def _hours_zh(seconds):
    return f'約 {seconds / 60:.0f} 分鐘' if seconds < 5400 else f'約 {seconds / 3600:.1f} 小時'


def _interval(script):
    from .robot import _INTERVAL_RE
    m = _INTERVAL_RE.findall(script or '')
    return int(float(m[0])) if m else 300


def _plan_lines(plan, upto=False):
    """The 'Plan:' line in English and Chinese for 'now' / 'later'."""
    from .robot import FRAME_OVERHEAD_S, RUN_END_ALT
    iv, n = _interval(plan['script']), plan['count']
    secs = n * (iv + FRAME_OVERHEAD_S)
    until = _tw(plan['until'])
    if upto:
        en_end = f"{_tw(plan['start'])} – {until} (UTC+8). Fewer frames if it starts later."
        zh_end = f"{_tw(plan['start'])} – {until}（台灣時間）；越晚開始張數越少。"
    elif plan['until_reason'] == 'alt':
        en_end = f'until {until} (UTC+8), when it sinks below {RUN_END_ALT:g}°.'
        zh_end = f'拍到 {until}（台灣時間），之後仰角低於 {RUN_END_ALT:g}°。'
    else:
        en_end = f'until {until} (UTC+8), 30 min after astronomical dawn.'
        zh_end = f'拍到 {until}（台灣時間），天文曙光後 30 分鐘。'
    up_en, up_zh = ('up to ', '最多 ') if upto else ('', '')
    return (f'Plan: SLT rp, {up_en}*{iv} s × {n}* ({_hours(secs)}), {en_end}\n'
            f'計畫：SLT rp，{up_zh}*{iv} 秒 × {n} 張*（{_hours_zh(secs)}），{zh_end}')


def ep_message(name, ra, dec, plan):
    """Bilingual Slack text for an Einstein Probe alert, from robot.plan_night(): 'now' and 'later' go to the control
    room with the script alert-run will carry; 'low' goes to the ToO channel, with a hand script only when the
    target at least gets above RUN_END_ALT."""
    from .robot import RUN_END_ALT, RUN_MIN_ALT
    moon = plan.get('moon_sep')
    if plan['kind'] == 'now':
        return (f':rotating_light: *{name}* — Einstein Probe alert: observable from Lulin *now*\n'
                f'EP 警報：鹿林*現在*就能拍\n'
                f"Altitude {plan['alt_now']:.0f}° now, Moon {moon:.0f}° away.\n"
                f"目前仰角 {plan['alt_now']:.0f}°，月距 {moon:.0f}°。\n"
                + _plan_lines(plan) + '\n'
                'If weather permits, please observe it now with SLT as First Priority.\n'
                '可以的話請 *立即！馬上！立刻！* 用 SLT 優先觀測，謝謝！！\n'
                f'This script is already on the robot\'s alert-run API ({_RUN_API}).\n'
                '這份 script 已經在機器人的 alert-run API 上。\n'
                f"```\n{plan['script']}```\n" + _NOTE)
    if plan['kind'] == 'later':
        t0 = _tw(plan['start'])
        return (f'*{name}* — Einstein Probe alert: we can trigger it tonight\n'
                f'EP 警報：今晚可以拍\n'
                f'Not yet: it is dark and above {RUN_MIN_ALT:g}° from {t0} (UTC+8). Moon {moon:.0f}° away.\n'
                f'現在還不行：{t0}（台灣時間）起天黑且仰角超過 {RUN_MIN_ALT:g}° 才能拍。月距 {moon:.0f}°。\n'
                + _plan_lines(plan, upto=True) + '\n'
                'If weather permits, please include it in tonight\'s observing list using SLT as First Priority.\n'
                '可以的話請把它排進今晚的觀測清單，用 SLT 優先觀測，謝謝！！\n'
                f'From {t0} the robot\'s alert-run API ({_RUN_API}) will carry this script, '
                'with the count set by the time left.\n'
                f'{t0} 起機器人的 alert-run API 會更新成這份 script，張數依剩餘時間計算。\n'
                f"```\n{plan['script']}```\n" + _NOTE)
    peak = plan['max_alt']
    if peak >= RUN_MIN_ALT:            # high enough, but not one frame of dark time left
        why_en, why_zh = 'too little dark time is left tonight', '今晚剩下的天黑時間不夠拍'
    else:
        why_en, why_zh = (f'too low at Lulin tonight', '今晚在鹿林仰角太低')
    lines = [f'*{name}* — Einstein Probe alert: {why_en}, we will not observe it',
             f'EP 警報：{why_zh}，不拍']
    if peak < RUN_MIN_ALT:
        if plan.get('never_high'):
            d = f"{plan['dec_deg']:+.0f}".replace('-', '−')
            ctx_en = f'Dec {d}°: it never gets above {RUN_MIN_ALT:g}° from Lulin'
            ctx_zh = f'Dec {d}°，在鹿林永遠到不了 {RUN_MIN_ALT:g}°'
        else:
            ctx_en, ctx_zh = 'it is high only in daytime this time of year', '這個季節只在白天升高'
        if peak >= RUN_END_ALT:
            lines += [f'It peaks at only {peak:.0f}° in the dark ({ctx_en}).',
                      f'今晚天黑時最高只到 {peak:.0f}°（{ctx_zh}）。']
        elif peak < 0:
            lines += [f'It stays below the horizon in the dark ({ctx_en}).',
                      f'今晚天黑時都在地平線以下（{ctx_zh}）。']
        else:
            lines += [f'It peaks at only {peak:.0f}° in the dark, too low to observe ({ctx_en}).',
                      f'今晚天黑時最高只有 {peak:.0f}°，無法觀測（{ctx_zh}）。']
    if plan.get('script') and peak >= RUN_END_ALT:
        secs = (plan['until'] - plan['start']).total_seconds()
        lines += [f'The alert-run API will not take it. To try it by hand, this SLT script fits the {_hours(secs)[2:]} '
                  f'it spends above {RUN_END_ALT:g}°:',
                  f'alert-run API 不會拍它。想手動試拍的話，下面的 SLT script 已依它在 {RUN_END_ALT:g}° 以上的 '
                  f'{_hours_zh(secs)[2:]}調整：',
                  f"```\n{plan['script']}```"]
    else:
        lines += ['The alert-run API will not take it.', 'alert-run API 不會拍它。']
    lines += [f'RA {ra}, Dec {dec}, Moon {moon:.0f}° away.', f'月距 {moon:.0f}°。']
    return '\n'.join(lines)


def ep_message_fallback(name, ra, dec, script):
    """When the night plan cannot be computed: the full script to the control room, visibility left to people."""
    return (f':rotating_light: *{name}* — Einstein Probe alert (visibility not computed, please check the plot)\n'
            f'EP 警報（無法計算可觀測時間，請看 visibility plot）\n'
            'If weather permits, please include it in tonight\'s observing list using SLT as First Priority.\n'
            '可以的話請 *立即！馬上！立刻！* 用 SLT 優先觀測，謝謝！！\n'
            f'RA {ra}, Dec {dec}\n```\n{script}```\n' + _NOTE)


def _ep_plot(name, ra, dec, day=None):
    """The same Lulin visibility plot as a Daily / Direct Trigger (the plan's night, Moon distance in the legend)."""
    from app.services.planning.trigger_send import render_trigger_plot
    return render_trigger_plot([{'name': name, 'ra': ra, 'dec': dec}], savepath=str(PLOT_PATH), label=name, day=day)


def handle_ep(raw, client, sent):
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    data = json.loads(raw)
    trigger_time = data.get('trigger_time') or ''
    uid = f'ep_{trigger_time}' if trigger_time else None
    if uid and uid in sent.seen:
        log.info('Skip EP alert already posted: %s', trigger_time)
        return
    coord = SkyCoord(ra=float(data.get('ra')) * u.degree, dec=float(data.get('dec')) * u.degree, frame='icrs')
    ra = coord.ra.to_string(unit=u.hourangle, sep=':', precision=2)
    dec = coord.dec.to_string(unit=u.degree, sep=':', precision=2)
    yymmdd = datetime.fromisoformat(trigger_time.replace('Z', '+00:00')).strftime('%y%m%d')

    now = datetime.now(timezone.utc)
    name = _next_ep_name(yymmdd)
    _add_target(name)
    script = slt_script(name, ra, dec)
    from . import robot  # first: the Lulin robot polls for it (GET /api/v1/robot/alert, /alert-run)
    robot_id = robot.publish(uid or f'ep_{name}', 'einstein_probe', name, ra, dec, script,
                             trigger_time=trigger_time, log=log)
    try:
        plan = robot.plan_night(ra, dec, script, now)
        if plan['kind'] == 'now':
            plan['alt_now'] = robot.run_window(ra, dec, now)['alt_now']
    except Exception as e:  # never hold the alert back over the maths: post it as observable now, full script
        log.warning('EP plan for %s not computed: %s', name, e)
        plan = None
    from app.services.notifications import webpush  # next: GREAT Lab phones (in the background, never raises)
    webpush.push_ep_alert(name, ra, dec, plan=plan, log=log)
    if plan is None:
        text = ep_message_fallback(name, ra, dec, script)
        kind = 'now'
    else:
        text = ep_message(name, ra, dec, plan)
        kind = plan['kind']

    from app.services.planning.trigger_send import _TAIPEI, _trigger_day_key
    night = (plan or {}).get('start') or now        # the plot shows the plan's night (after dawn: the coming one)
    plot = _ep_plot(name, ra, dec, day=_trigger_day_key(night.astimezone(_TAIPEI)))
    if not plot:
        log.warning('EP visibility plot failed for %s (see the web log)', name)

    main = _env('SLACK_CHANNEL_ID_ToO') if kind == 'low' else _env('SLACK_CHANNEL_ID_CONTROL_ROOM')
    _send_slack(client, main, text, plot)
    copy = _env('SLACK_CHANNEL_ID_EP_COPY')
    if copy and copy != main:
        _send_slack(client, copy, text, plot)
    _send_email('Attention! EP Alert', json.dumps(data, indent=4))

    if uid:
        sent.add(uid)
    _append_entry(EP_JSON, {'received_at': now.isoformat(timespec='seconds'), 'object_name': name, 'ra': ra, 'dec': dec,
                            'trigger_time': trigger_time, 'script': script, 'plan': kind,
                            'max_alt': (plan or {}).get('max_alt')})
    status.event(BOT, f'Einstein Probe alert {name} at RA {ra}, Dec {dec}'
                      f' → {kind}: {"ToO (too low)" if kind == "low" else "control room"}'
                      + (f', robot alert #{robot_id}' if robot_id else ''))


# ── listener ──────────────────────────────────────────────────────────────────

def _consumer():
    from gcn_kafka import Consumer
    return Consumer(config={'auto.offset.reset': 'latest', 'broker.address.family': 'v4'},  # IPv4: avoids IPv6 routing issues
                    client_id=_env('GCN_CLIENT_ID'), client_secret=_env('GCN_CLIENT_SECRET'), domain='gcn.nasa.gov')


def _missing_settings():
    return [k for k in ('GCN_CLIENT_ID', 'GCN_CLIENT_SECRET', 'SLACK_BOT_TOKEN', 'SLACK_CHANNEL_ID_GCN') if not _env(k)]


def setup_problem():
    missing = _missing_settings()
    return ('Missing in kinder.env: ' + ', '.join(missing)) if missing else ''


def _loop(gen=0):
    from slack_sdk import WebClient
    global _last_beat

    missing = _missing_settings()
    if missing:
        status.update(BOT, state='stopped', detail={'setup': 'Missing in kinder.env: ' + ', '.join(missing)})
        status.event(BOT, 'Not started: missing ' + ', '.join(missing), level='error', count=False)
        return
    status.update(BOT, state='listening', pid=os.getpid(), started_at=status.now_iso(), heartbeat_at=status.now_iso(),
                  detail={'topics': TOPICS})
    client = WebClient(token=_env('SLACK_BOT_TOKEN'))
    sent = _SentIds()
    backoff = 5
    while True:
        try:
            consumer = _consumer()
            consumer.subscribe(TOPICS)
            log.info('Listening to %s', ', '.join(TOPICS))
            backoff = 5
            last_beat = 0.0
            while True:
                if gen != _gen:                     # the watchdog replaced this (hung) thread
                    consumer.close()
                    log.warning('Replaced listener thread stops')
                    return
                _last_beat = time.monotonic()
                if time.monotonic() - last_beat >= HEARTBEAT_EVERY:
                    status.heartbeat(BOT, state='listening', pid=os.getpid())
                    last_beat = time.monotonic()
                for message in consumer.consume(timeout=1):
                    if message.error():
                        log.warning('Kafka: %s', message.error())
                        continue
                    topic = message.topic()
                    try:
                        if topic == 'gcn.circulars':
                            handle_circular(message.value(), client, sent, message.offset())
                        elif 'einstein_probe' in topic:
                            handle_ep(message.value(), client, sent)
                    except Exception as e:
                        log.exception('Handling %s failed', topic)
                        status.event(BOT, f'Handling a {topic} message failed: {e}', level='error', count=False)
        except Exception as e:
            status.event(BOT, f'Kafka connection lost: {e}; retrying in {backoff} s', level='error', count=False)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


_thread = None
_thread_lock = threading.Lock()
_gen = 0                     # bumped when the watchdog replaces a hung thread; the old one returns when it wakes
_last_beat = 0.0             # monotonic time the listener last went round its loop


def start(replace=False):
    """Start the listener thread once per process (``replace``: also when the current one is alive but hung)."""
    global _thread, _gen, _last_beat
    with _thread_lock:
        if _thread is not None and _thread.is_alive() and not replace:
            return
        _gen += 1
        _last_beat = time.monotonic()
        _thread = threading.Thread(target=_loop, args=(_gen,), name='bot-gcn', daemon=True)
        _thread.start()


def watchdog():
    """Every minute in the process that owns the bots: start the listener again if its thread died, or replace it
    when it has not gone round its loop for STALL_AFTER seconds (stuck in Kafka or in a handler)."""
    if _missing_settings():
        return                                 # _loop records the setup problem once; nothing to restart
    stuck = time.monotonic() - _last_beat
    if _thread is None or not _thread.is_alive():
        status.event(BOT, 'Listener was not running: started again', level='warn', count=False)
        start()
    elif stuck > STALL_AFTER:
        status.event(BOT, f'Listener stuck for {stuck:.0f} s: started a new one', level='warn', count=False)
        start(replace=True)
