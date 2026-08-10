import os
import json
import logging
from datetime import datetime, timedelta

import pytz
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from modules.config import config

logger = logging.getLogger(__name__)

_STATUS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
_STATUS_PATH = os.path.join(_STATUS_DIR, 'trigger_send_status.json')

_TAIPEI = pytz.timezone('Asia/Taipei')


def _trigger_day_key(now=None):
    """The Daily Trigger send status resets at 08:00 Asia/Taipei, not midnight —
    that's when the previous night's trigger window is considered over."""
    now = now or datetime.now(_TAIPEI)
    if now.tzinfo is None:
        now = _TAIPEI.localize(now)
    if now.hour < 8:
        now = now - timedelta(days=1)
    return now.strftime('%Y-%m-%d')


def get_send_status():
    """Returns {'day': ..., 'SLT': {...} or None, 'LOT': {...} or None}.
    Automatically resets (returns None entries) once the trigger day rolls over —
    no cron job needed, the reset just happens lazily on next read/write."""
    day_key = _trigger_day_key()
    status = {'day': day_key, 'SLT': None, 'LOT': None}
    if os.path.isfile(_STATUS_PATH):
        try:
            with open(_STATUS_PATH, 'r', encoding='utf-8') as f:
                stored = json.load(f)
            if stored.get('day') == day_key:
                status['SLT'] = stored.get('SLT')
                status['LOT'] = stored.get('LOT')
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('trigger_send: could not read status file: %s', e)
    return status


def mark_sent(telescope, sent_by):
    if telescope not in ('SLT', 'LOT'):
        raise ValueError(f'Invalid telescope: {telescope}')
    os.makedirs(_STATUS_DIR, exist_ok=True)
    status = get_send_status()
    status[telescope] = {
        'sent_by': sent_by,
        'sent_at': datetime.now(_TAIPEI).strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(_STATUS_PATH, 'w', encoding='utf-8') as f:
        json.dump(status, f, indent=2)
    return status


def send_to_slack(greeting, script_body, image_path=None):
    """Posts the trigger message to the Control Room channel (or the test
    channel when DEBUG is enabled): `greeting` as the message text, the ACP
    script as a .txt attachment, and the visibility plot (if any) — all as
    ONE Slack message, not separate posts."""
    token = os.environ.get('SLACK_BOT_TOKEN', '')
    if not token:
        raise RuntimeError('SLACK_BOT_TOKEN is not configured.')

    channel = (
        os.environ.get('SLACK_CHANNEL_ID_test', '')
        if config.DEBUG
        else os.environ.get('SLACK_CHANNEL_ID_CONTROL_ROOM', '')
    )
    if not channel:
        raise RuntimeError('Slack channel is not configured for this environment.')

    client = WebClient(token=token)

    import tempfile
    txt_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tf:
            tf.write(script_body)
            txt_path = tf.name

        # snippet_type='text' tells Slack to render this inline as an expandable
        # text preview rather than a plain "download this file" card.
        file_uploads = [{'file': txt_path, 'filename': 'trigger_script.txt', 'title': 'Trigger Script',
                          'snippet_type': 'text'}]
        if image_path and os.path.isfile(image_path):
            file_uploads.append({'file': image_path, 'filename': 'visibility_plot.jpg', 'title': 'Visibility Plot'})

        client.files_upload_v2(channel=channel, initial_comment=greeting, file_uploads=file_uploads)
    except SlackApiError as e:
        raise RuntimeError(f"Slack send failed: {e.response['error']}")
    finally:
        if txt_path:
            try:
                os.unlink(txt_path)
            except OSError:
                pass
