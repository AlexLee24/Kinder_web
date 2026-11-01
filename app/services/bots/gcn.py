"""GCN bot: one Kafka consumer for GCN circulars and Einstein Probe WXT alerts (was lab_bot gcn.py + EP.py).

    gcn.circulars                          → Slack SLACK_CHANNEL_ID_GCN
    gcn.notices.einstein_probe.wxt.alert   → name EPt<yymmdd><a,b,…>, SLT script, Lulin visibility plot;
                                             Slack: Lulin night (10–22 UTC) SLACK_CHANNEL_ID_CONTROL_ROOM,
                                             otherwise SLACK_CHANNEL_ID_ToO with "We can trigger … tonight";
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


def ep_message(name, ra, dec, lulin_night):
    """Slack text (lab_bot EP.py wording). Outside the Lulin night it opens with "We can trigger … tonight"."""
    msg = ("If weather permits, please include the following object in tonight's observing list using SLT as First Priority\n"
           '可以的話請 *立即！馬上！立刻！* 馬上觀測，謝謝！！\n'
           'Object visibility plot有時候不會正常傳送出去，請見諒\n'
           f'```\n{slt_script(name, ra, dec)}```\n'
           'Note: This is an auto message. If observed, or have any urgent inquiries, please Call Janet or Amar at Slack(phone number).'
           'Note: 這是自動訊息. 如果觀測了或是有任何緊急訊息, 請打給 Janet 或 Amar 在 Slack(或手機號碼).'
           'Note: LOT可能也會要觀測，詳細請等待人員確認，先使用SLT觀測，謝謝！')
    if not lulin_night:
        msg = f'We can trigger the observation of {name} tonight.\n' + '=' * 35 + '\n' + msg
    return msg


def _ep_plot(name, ra, dec):
    """The same Lulin visibility plot as a Daily / Direct Trigger (tonight, Moon distance in the legend)."""
    from app.services.planning.trigger_send import render_trigger_plot
    return render_trigger_plot([{'name': name, 'ra': ra, 'dec': dec}], savepath=str(PLOT_PATH), label=name)


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
    lulin_night = 10 <= now.hour < 22              # Lulin (UTC+8) 18:00–06:00
    name = _next_ep_name(yymmdd)
    _add_target(name)
    from . import robot  # first: the Lulin robot polls for it (GET /api/v1/robot/alert)
    robot_id = robot.publish(uid or f'ep_{name}', 'einstein_probe', name, ra, dec, slt_script(name, ra, dec),
                             trigger_time=trigger_time, log=log)
    from app.services.notifications import webpush  # next: GREAT Lab phones (in the background, never raises)
    webpush.push_ep_alert(name, ra, dec, log=log)
    text = ep_message(name, ra, dec, lulin_night)

    plot = _ep_plot(name, ra, dec)
    if not plot:
        log.warning('EP visibility plot failed for %s (see the web log)', name)

    main = _env('SLACK_CHANNEL_ID_CONTROL_ROOM') if lulin_night else _env('SLACK_CHANNEL_ID_ToO')
    _send_slack(client, main, text, plot)
    copy = _env('SLACK_CHANNEL_ID_EP_COPY')
    if copy and copy != main:
        _send_slack(client, copy, text, plot)
    _send_email('Attention! EP Alert', json.dumps(data, indent=4))

    if uid:
        sent.add(uid)
    _append_entry(EP_JSON, {'received_at': now.isoformat(timespec='seconds'), 'object_name': name, 'ra': ra, 'dec': dec,
                            'trigger_time': trigger_time, 'script': slt_script(name, ra, dec)})
    status.event(BOT, f'Einstein Probe alert {name} at RA {ra}, Dec {dec}'
                      f' → {"control room (night)" if lulin_night else "ToO (day)"}'
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
