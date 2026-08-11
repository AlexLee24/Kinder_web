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
            else:
                logger.info('trigger_send: status reset — stored day=%s, current trigger day=%s',
                            stored.get('day'), day_key)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('trigger_send: could not read status file %s: %s', _STATUS_PATH, e)
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
    logger.info('trigger_send: mark_sent telescope=%s sent_by=%s -> %s', telescope, sent_by, status[telescope])
    return status


def _log_slack_response(step, resp):
    """Logs whether Slack actually accepted the call — a 200 HTTP response from
    the requests layer does NOT mean the message landed; slack_sdk raises
    SlackApiError when `ok` is false, but logging the raw response here means
    a *silent* delivery problem (e.g. bot not in channel, wrong channel id)
    leaves a trail instead of nothing at all."""
    try:
        logger.info('trigger_send: %s response ok=%s data=%s', step, resp.get('ok'), dict(resp.data))
    except Exception:
        logger.info('trigger_send: %s response (could not introspect)', step)


def send_to_slack(greeting, script_body, image_path=None):
    """Posts the trigger message to the Control Room channel (or the test
    channel when DEBUG is enabled): `greeting` via chat.postMessage (the plain
    text post that was already proven reliable before the .txt-attachment
    change — relying on files_upload_v2's initial_comment to carry the text
    instead turned out to silently not deliver, likely a scope/permission gap
    between plain chat:write and the file-upload-and-share flow), then the
    ACP script (.txt) and the visibility plot as follow-up file shares
    threaded under that message, so they still read as one conversation."""
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
    logger.info('trigger_send: sending to channel=%s (DEBUG=%s)', channel, config.DEBUG)

    client = WebClient(token=token)

    import tempfile
    txt_path = None
    try:
        post_resp = client.chat_postMessage(channel=channel, text=greeting)
        _log_slack_response('greeting post', post_resp)
        thread_ts = post_resp.get('ts')

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tf:
            tf.write(script_body)
            txt_path = tf.name

        # snippet_type='text' tells Slack to render this inline as an expandable
        # text preview rather than a plain "download this file" card.
        resp1 = client.files_upload_v2(
            channel=channel, thread_ts=thread_ts,
            file=txt_path, filename='trigger_script.txt', title='Trigger Script',
            snippet_type='text',
        )
        _log_slack_response('script upload', resp1)

        if image_path and os.path.isfile(image_path):
            resp2 = client.files_upload_v2(
                channel=channel, thread_ts=thread_ts, file=image_path,
                filename='visibility_plot.jpg', title='Visibility Plot',
            )
            _log_slack_response('plot upload', resp2)
    except SlackApiError as e:
        raise RuntimeError(f"Slack send failed: {e.response['error']}")
    finally:
        if txt_path:
            try:
                os.unlink(txt_path)
            except OSError:
                pass
