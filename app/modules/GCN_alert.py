"""GCN alert listener — merged GCN circulars + Einstein Probe WXT handler.
Runs as a background daemon thread launched by main.py.
Outputs:
  data/gcn.json  — last 5 GCN circulars
  data/ep.json   — last 5 EP WXT alerts
Credentials loaded from kinder.env via environment variables.
"""
import json
import logging
import os
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import ephem
import matplotlib
matplotlib.use('Agg')

from astropy.coordinates import SkyCoord
from astropy import units as u
from gcn_kafka import Consumer
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import modules.obsplan as obs

logger = logging.getLogger("gcn_alert")

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR   = os.path.join(_MODULE_DIR, '..', 'data')
GCN_JSON    = os.path.join(_DATA_DIR, 'gcn.json')
EP_JSON     = os.path.join(_DATA_DIR, 'ep.json')
PLOT_PATH   = os.path.join(_DATA_DIR, 'ep_observing_track.jpg')
MAX_ENTRIES = 5

_GCN_TOPICS = [
    'gcn.circulars',
    'gcn.notices.einstein_probe.wxt.alert',
]

# ---------------------------------------------------------------------------
# JSON store helpers
# ---------------------------------------------------------------------------
def _load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return []

def _save_json(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(entries[-MAX_ENTRIES:], f, indent=2, ensure_ascii=False)

def _append_entry(path, entry):
    entries = _load_json(path)
    entries.append(entry)
    _save_json(path, entries)

# ---------------------------------------------------------------------------
# Skymap removal
# ---------------------------------------------------------------------------
def _remove_skymap_recursive(obj):
    if isinstance(obj, dict):
        for k in [k for k in obj if 'skymap' in k.lower()]:
            del obj[k]
        for v in obj.values():
            _remove_skymap_recursive(v)
    elif isinstance(obj, list):
        for item in obj:
            _remove_skymap_recursive(item)

# ---------------------------------------------------------------------------
# Slack helpers
# ---------------------------------------------------------------------------
def _send_slack(slack_client, channel, message, file_path=None):
    try:
        slack_client.chat_postMessage(channel=channel, text=message)
        if file_path and os.path.isfile(file_path):
            slack_client.files_upload_v2(channel=channel, file=file_path)
    except SlackApiError as e:
        logger.error(f"Slack send failed: {e.response['error']}")

# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------
def _send_email(smtp_server, smtp_port, sender, password, receivers, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From']    = sender
        msg['To']      = ', '.join(receivers)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(smtp_server, smtp_port) as srv:
            srv.starttls()
            srv.login(sender, password)
            srv.sendmail(sender, receivers, msg.as_string())
        logger.info("Email sent.")
    except Exception as e:
        logger.error(f"Email send failed: {e}")

# ---------------------------------------------------------------------------
# GCN circular handler
# ---------------------------------------------------------------------------
def _format_circular(raw_value):
    try:
        data = json.loads(raw_value)
        _remove_skymap_recursive(data)
        lines = []
        if 'subject' in data and 'body' in data:
            lines.append(f"*{data.get('subject')}*")
            for key in ('eventId', 'submitter', 'circularId'):
                if key in data:
                    lines.append(f"*{key}:* {data[key]}")
            lines.append(f"\n{data['body']}")
        else:
            for key, val in data.items():
                if key == '$schema':
                    continue
                if isinstance(val, (dict, list)):
                    lines.append(f"*{key}:*\n```\n{json.dumps(val, indent=2)}\n```")
                else:
                    lines.append(f"*{key}:* {val}")
        return '\n'.join(lines)
    except Exception:
        return raw_value

def _handle_circular(raw_value, slack_client, channel_gcn):
    text = _format_circular(raw_value)
    _send_slack(slack_client, channel_gcn, text)
    entry = {'received_at': datetime.now(timezone.utc).isoformat(), 'text': text[:2000]}
    try:
        data = json.loads(raw_value)
        entry['subject']    = data.get('subject', '')
        entry['circularId'] = data.get('circularId', '')
    except Exception:
        pass
    _append_entry(GCN_JSON, entry)
    logger.info(f"GCN circular stored: {entry.get('subject', '(no subject)')}")

# ---------------------------------------------------------------------------
# EP WXT alert handler
# ---------------------------------------------------------------------------
def _convert_trigger_time(trigger_time_str):
    dt_utc = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
    return dt_utc.strftime('%Y-%m-%d'), dt_utc.strftime('%y%m%d')

def _extract_ep_fields(raw_value):
    data  = json.loads(raw_value)
    ra    = float(data.get('ra',  0))
    dec   = float(data.get('dec', 0))
    coord = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame='icrs')
    ra_hms  = coord.ra.to_string(unit=u.hourangle, sep=':', precision=2)
    dec_dms = coord.dec.to_string(unit=u.degree,   sep=':', precision=2)
    Y_m_d, Ymd = _convert_trigger_time(data.get('trigger_time', ''))
    return Y_m_d, Ymd, ra_hms, dec_dms, data

def _generate_obs_plot(date, object_name, ra, dec):
    label  = f"{object_name}\nRA: {ra}\nDEC: {dec}"
    target = obs.create_ephem_target(label, ra, dec)
    lulin  = obs.create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)
    obs.calculate_twilight_times(lulin, '2024/01/01 23:59:00')
    next_date       = (datetime.strptime(date, '%Y-%m-%d') + timedelta(days=1)).date()
    obs_start_local = obs.dt_naive_to_dt_aware(ephem.Date(f'{date} 17:00:00').datetime(), 'Asia/Taipei')
    obs_end_local   = obs.dt_naive_to_dt_aware(ephem.Date(f'{next_date} 09:00:00').datetime(), 'Asia/Taipei')
    obs.plot_night_observing_tracks(
        [target], lulin, obs_start_local, obs_end_local,
        simpletracks=True, toptime='local', timezone='calculate',
        n_steps=1000, savepath=PLOT_PATH
    )
    return PLOT_PATH

def _generate_slt_script(object_name, ra, dec):
    return (
        f";===SLT URGENT Priority!!===\n\n"
        f"#BINNING 1\n"
        f"#FILTER rp_Astrodon_2018\n"
        f"#INTERVAL 300\n"
        f"#COUNT 24\n"
        f";# mag: >22 mag\n"
        f"{object_name}\t{ra}\t{dec}\n"
        f"#WAITFOR 1\n"
    )

def _handle_ep_alert(raw_value, slack_client, channel_too, channel_gcn,
                     smtp_server, smtp_port, sender_email, sender_password,
                     email_receivers, suffix_state):
    Y_m_d, Ymd, ra, dec, raw_data = _extract_ep_fields(raw_value)
    utc_now  = datetime.now(timezone.utc)
    is_night = not (10 <= utc_now.hour < 22)

    if Ymd == suffix_state['day']:
        suffix_state['count'] += 1
    else:
        suffix_state['day']   = Ymd
        suffix_state['count'] = 0
    suffix      = chr(ord('a') + suffix_state['count'])
    object_name = f"EP{Ymd}{suffix}"

    script = _generate_slt_script(object_name, ra, dec)
    notice = (
        "If weather permits, please include the following object in tonight's observing list using SLT as First Priority\n"
        "可以的話請 *立即！馬上！立刻！* 馬上觀測，謝謝！！\n"
        "Object visibility plot有時候不會正常傳送出去，請見諒\n"
        f"```\n{script}```\n"
        "Note: LOT可能也會要觀測，詳細請等待人員確認，先使用SLT觀測，謝謝！"
    )
    if not is_night:
        notice = f"We can trigger the observation of {object_name} tonight.\n{'='*35}\n" + notice

    plot_file = None
    try:
        plot_file = _generate_obs_plot(Y_m_d, object_name, ra, dec)
    except Exception as e:
        logger.warning(f"Plot generation failed: {e}")

    _send_slack(slack_client, channel_too, notice, plot_file)
    if channel_gcn and channel_gcn != channel_too:
        _send_slack(slack_client, channel_gcn, notice, plot_file)

    _send_email(smtp_server, smtp_port, sender_email, sender_password,
                email_receivers, "Attention! EP Alert", json.dumps(raw_data, indent=4))

    entry = {
        'received_at':  utc_now.isoformat(),
        'object_name':  object_name,
        'ra':           ra,
        'dec':          dec,
        'trigger_time': raw_data.get('trigger_time', ''),
        'script':       script,
    }
    _append_entry(EP_JSON, entry)
    logger.info(f"EP alert stored: {object_name} RA={ra} DEC={dec}")

# ---------------------------------------------------------------------------
# Main listener loop (runs in background thread)
# ---------------------------------------------------------------------------
def _listener_loop():
    client_id       = os.environ.get('GCN_CLIENT_ID', '')
    client_secret   = os.environ.get('GCN_CLIENT_SECRET', '')
    slack_token     = os.environ.get('SLACK_BOT_TOKEN', '')
    ch_gcn          = os.environ.get('SLACK_CHANNEL_ID_GCN', '')
    ch_too          = os.environ.get('SLACK_CHANNEL_ID_ToO', '')
    smtp_server     = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port       = int(os.environ.get('SMTP_PORT', 587))
    sender_email    = os.environ.get('SENDER_EMAIL', '')
    sender_pass     = os.environ.get('SENDER_PASSWORD', '')
    email_receivers = ['kinder@astro.ncu.edu.tw', 'amar@astro.ncu.edu.tw']

    if not client_id or not client_secret:
        logger.error("GCN_CLIENT_ID / GCN_CLIENT_SECRET not set — GCN listener not started.")
        return

    slack_client = WebClient(token=slack_token)
    consumer = Consumer(
        config={'auto.offset.reset': 'latest'},
        client_id=client_id,
        client_secret=client_secret,
        domain='gcn.nasa.gov',
    )
    consumer.subscribe(_GCN_TOPICS)
    logger.info("GCN listener started, subscribed to: " + ', '.join(_GCN_TOPICS))

    suffix_state = {'day': None, 'count': 0}

    while True:
        try:
            for message in consumer.consume(timeout=1):
                if message.error():
                    logger.warning(f"GCN consumer error: {message.error()}")
                    continue
                topic     = message.topic()
                raw_value = message.value()
                logger.debug(f"topic={topic} offset={message.offset()}")
                if topic == 'gcn.circulars':
                    _handle_circular(raw_value, slack_client, ch_gcn)
                elif 'einstein_probe' in topic:
                    _handle_ep_alert(
                        raw_value, slack_client, ch_too, ch_gcn,
                        smtp_server, smtp_port, sender_email, sender_pass,
                        email_receivers, suffix_state,
                    )
        except Exception as e:
            logger.exception(f"GCN listener loop error: {e}")

# ---------------------------------------------------------------------------
# Public entry point — called from main.py
# ---------------------------------------------------------------------------
_thread      = None
_thread_lock = threading.Lock()

def start_gcn_listener(log_dir=None):
    """Start GCN listener as a daemon thread. Safe to call multiple times."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            logger.info("GCN listener already running.")
            return
        if log_dir and not logger.handlers:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, 'gcn_alert.log'))
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(fh)
            logger.setLevel(logging.INFO)
        _thread = threading.Thread(target=_listener_loop, name='gcn_alert', daemon=True)
        _thread.start()
        logger.info("GCN listener thread started.")
