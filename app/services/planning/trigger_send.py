import os
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta

try:
    import fcntl
except ImportError:  # non-POSIX
    fcntl = None

import pytz
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import config

logger = logging.getLogger(__name__)

from app.paths import DATA_DIR
_STATUS_DIR = str(DATA_DIR)
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


@contextmanager
def _status_lock(exclusive=True):
    """flock on a side file so read-modify-write of the status file is serialised
    across gunicorn workers (a no-op where fcntl is unavailable)."""
    os.makedirs(_STATUS_DIR, exist_ok=True)
    with open(_STATUS_PATH + '.lock', 'a+') as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _read_status(day_key):
    """Read the status file for *day_key*. Raises JSONDecodeError / OSError."""
    status = {'day': day_key, 'SLT': None}
    if os.path.isfile(_STATUS_PATH):
        with open(_STATUS_PATH, 'r', encoding='utf-8') as f:
            stored = json.load(f)
        if stored.get('day') == day_key:
            for k, v in stored.items():
                if k != 'day':
                    status[k] = v
        else:
            logger.info('trigger_send: status reset — stored day=%s, current trigger day=%s',
                        stored.get('day'), day_key)
    return status


def get_send_status():
    """Returns {'day': ..., 'SLT': {...} or None, 'LOT:R01': {...}, ...}.
    LOT programs are stored as separate keys like 'LOT:R01', 'LOT:R07'.
    Automatically resets once the trigger day rolls over."""
    day_key = _trigger_day_key()
    try:
        return _read_status(day_key)
    except (json.JSONDecodeError, OSError) as e:
        # Most likely caught a writer mid-update: retry once under the lock rather
        # than silently reporting "not sent".
        logger.info('trigger_send: status read failed (%s), retrying under lock', e)
    with _status_lock(exclusive=False):
        try:
            return _read_status(day_key)
        except (json.JSONDecodeError, OSError) as e:
            # Genuinely unreadable (writes are atomic now, so not a torn read). Log it
            # loudly; the next mark_sent rewrites the file.
            logger.error('trigger_send: could not read status file %s: %s', _STATUS_PATH, e)
            return {'day': day_key, 'SLT': None}


def mark_sent(telescope, sent_by, program=''):
    if telescope not in ('SLT', 'LOT'):
        raise ValueError(f'Invalid telescope: {telescope}')
    os.makedirs(_STATUS_DIR, exist_ok=True)
    key = f'{telescope}:{program}' if telescope == 'LOT' and program else telescope
    with _status_lock(exclusive=True):
        day_key = _trigger_day_key()
        try:
            status = _read_status(day_key)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('trigger_send: could not read status file %s: %s', _STATUS_PATH, e)
            status = {'day': day_key, 'SLT': None}
        status[key] = {
            'sent_by': sent_by,
            'sent_at': datetime.now(_TAIPEI).strftime('%Y-%m-%d %H:%M:%S'),
        }
        tmp = f'{_STATUS_PATH}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
        os.replace(tmp, _STATUS_PATH)
    logger.info('trigger_send: mark_sent key=%s sent_by=%s -> %s', key, sent_by, status[key])
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


def _slack_upload_and_share(client, channel, file_path, filename, title, thread_ts=None, initial_comment=None,
                            snippet_type=None):
    """Drives Slack's 3-step external upload flow explicitly (get an upload URL,
    PUT the bytes, then completeUploadExternal with channel_id set), instead of
    the files_upload_v2 convenience wrapper.

    Why: files_upload_v2 was returning ok=True for the upload, but the returned
    file object had channels=[] / groups=[] / ims=[] — meaning Slack accepted
    and stored the file but never actually shared it into the channel, so
    nothing appeared even though the API call "succeeded". Calling
    files_completeUploadExternal ourselves guarantees channel_id is passed to
    the step that actually posts the file into the channel."""
    file_size = os.path.getsize(file_path)

    url_kwargs = {'filename': filename, 'length': file_size}
    if snippet_type:
        url_kwargs['snippet_type'] = snippet_type
    url_resp = client.files_getUploadURLExternal(**url_kwargs)
    logger.info('trigger_send: got upload URL for %s (file_id=%s)', filename, url_resp.get('file_id'))
    upload_url = url_resp['upload_url']
    file_id = url_resp['file_id']

    with open(file_path, 'rb') as f:
        put_resp = requests.post(upload_url, files={'file': (filename, f)}, timeout=30)
    put_resp.raise_for_status()
    logger.info('trigger_send: uploaded bytes for %s (file_id=%s, %d bytes, http_status=%d)',
                filename, file_id, file_size, put_resp.status_code)

    complete_kwargs = {'files': [{'id': file_id, 'title': title}], 'channel_id': channel}
    if thread_ts:
        complete_kwargs['thread_ts'] = thread_ts
    if initial_comment:
        complete_kwargs['initial_comment'] = initial_comment

    complete_resp = client.files_completeUploadExternal(**complete_kwargs)
    _log_slack_response(f'{filename} completeUploadExternal', complete_resp)
    return complete_resp


def send_to_slack(greeting, script_body, image_path=None):
    """Posts three separate, independent top-level messages to the Control Room
    channel (or the test channel when DEBUG is enabled) — not a thread/reply:
    1) the greeting via chat.postMessage, 2) the ACP script as a .txt share,
    3) the visibility plot as an image share."""
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

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tf:
            tf.write(script_body)
            txt_path = tf.name

        _slack_upload_and_share(client, channel, txt_path, 'trigger_script.txt', 'Trigger Script',
                                snippet_type='text')

        if image_path and os.path.isfile(image_path):
            _slack_upload_and_share(client, channel, image_path, 'visibility_plot.jpg', 'Visibility Plot')
    except SlackApiError as e:
        raise RuntimeError(f"Slack send failed: {e.response['error']}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"Slack file upload (HTTP) failed: {e}") from e
    finally:
        if txt_path:
            try:
                os.unlink(txt_path)
            except OSError:
                pass
