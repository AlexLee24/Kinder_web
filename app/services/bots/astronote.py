"""AstroNote bot: new TNS AstroNotes → Slack SLACK_CHANNEL_ID_ALERT (was lab_bot astronote.py).

``run()`` is an APScheduler job (every 5 minutes): fetch the notes posted in the last 2 days and post the ones
not in app/data/bots/astronotes_sent_ids.json, oldest first. A note's id is saved before it is posted, so a
restart can never post it twice; a failed post is rolled back and retried next time. With no sent-ids file yet
(first run) every note in the window is marked as sent without posting, so the channel is not flooded.

TNS login: TNS_BOT_ID + TNS_BOT_NAME + TNS_API_KEY, or TNS_USER_ID + TNS_USERNAME (kinder.env).
"""
import json
import os
import time

import requests

from app.paths import DATA_DIR

from . import status

BOT = 'astronote'
log = status.get_logger(BOT)

LOOKBACK_DAYS = 2
TNS_LIST_URL = 'https://www.wis-tns.org/astronotes'
TNS_NOTE_URL = 'https://www.wis-tns.org/astronotes/astronote/{}'
SENT_IDS_FILE = DATA_DIR / 'bots' / 'astronotes_sent_ids.json'


def _env(key):
    return (os.environ.get(key) or '').strip()


def _auth():
    """(mode, user agent) or (None, reason)."""
    if _env('TNS_BOT_ID') and _env('TNS_API_KEY'):
        return 'bot', 'tns_marker{"tns_id":%s,"type": "bot", "name":"%s"}' % (_env('TNS_BOT_ID'), _env('TNS_BOT_NAME'))
    if _env('TNS_USER_ID') and _env('TNS_USERNAME'):
        return 'user', 'tns_marker{"tns_id":%s,"type": "user", "name":"%s"}' % (_env('TNS_USER_ID'), _env('TNS_USERNAME'))
    return None, 'TNS_BOT_ID + TNS_BOT_NAME + TNS_API_KEY (or TNS_USER_ID + TNS_USERNAME)'


def setup_problem():
    missing = [k for k in ('SLACK_BOT_TOKEN', 'SLACK_CHANNEL_ID_ALERT') if not _env(k)]
    mode, why = _auth()
    if not mode:
        missing.append(why)
    return ('Missing in kinder.env: ' + ', '.join(missing)) if missing else ''


# ── sent ids ──────────────────────────────────────────────────────────────────

def _load_sent():
    """Set of posted ids, or None before the first run."""
    try:
        with open(SENT_IDS_FILE) as fh:
            return set(json.load(fh))
    except FileNotFoundError:
        return None
    except ValueError:
        return set()


def _save_sent(ids):
    os.makedirs(SENT_IDS_FILE.parent, exist_ok=True)
    tmp = f'{SENT_IDS_FILE}.tmp'
    with open(tmp, 'w') as fh:
        json.dump(sorted(ids), fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, SENT_IDS_FILE)


# ── TNS ───────────────────────────────────────────────────────────────────────

def fetch_recent_notes():
    """{note_id: note} posted in the last LOOKBACK_DAYS."""
    mode, agent = _auth()
    params = {'posted_period_value': LOOKBACK_DAYS, 'posted_period_units': 'days', 'num_page': 50, 'page': 0,
              'format': 'json'}
    for _ in range(3):
        headers = {'User-Agent': agent}
        if mode == 'bot':
            r = requests.post(TNS_LIST_URL, params=params, headers=headers, data={'api_key': _env('TNS_API_KEY')},
                              timeout=30)
        else:
            r = requests.get(TNS_LIST_URL, params=params, headers=headers, timeout=30)
        if r.status_code == 429:
            wait = min(int(r.headers.get('x-rate-limit-reset', 60)), 120)
            log.info('TNS rate limit, waiting %s s', wait)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise RuntimeError(f'TNS HTTP {r.status_code} ({mode} login): {r.text[:200]}')
        data = r.json()
        return data if isinstance(data, dict) else {}
    raise RuntimeError('TNS kept rate-limiting the request')


# ── Slack message ─────────────────────────────────────────────────────────────

def _txt(value):
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value if v)
    return str(value).strip()


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _objects(note, limit=10):
    out = []
    for o in note.get('related_objects') or []:
        name = f"{_txt(o.get('iauname_prefix'))}{_txt(o.get('iauname'))}".strip()
        if not name:
            continue
        url = f"https://www.wis-tns.org/object/{_txt(o.get('iauname'))}"
        extras = [_txt(o.get('objtype'))]
        if _txt(o.get('redshift')):
            extras.append(f"z={_txt(o.get('redshift'))}")
        extras = ', '.join(e for e in extras if e)
        out.append(f'<{url}|{_esc(name)}>' + (f' ({_esc(extras)})' if extras else ''))
    if len(out) > limit:
        out = out[:limit] + [f'… +{len(out) - limit} more']
    return ' · '.join(out)


def build_message(note_id, note):
    """(fallback text, Slack blocks) — lab_bot's layout."""
    title = _txt(note.get('title')) or '(no title)'
    authors = _txt(note.get('authors'))
    if len(authors) > 300:
        authors = authors[:300] + ' …'
    abstract = _txt(note.get('abstract'))[:2500]
    keywords = _txt(note.get('keywords'))
    objects = _objects(note)
    meta = ' | '.join(x for x in [f':newspaper: *AstroNote {note_id}*', _esc(_txt(note.get('type'))),
                                  _esc(_txt(note.get('source_group'))), _esc(_txt(note.get('public_timestamp')))] if x)
    blocks = [{'type': 'header', 'text': {'type': 'plain_text', 'text': title[:150]}},
              {'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': meta}]}]
    if authors:
        blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': f'_{_esc(authors)}_'}]})
    if abstract:
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': _esc(abstract)}})
    if objects:
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'*Objects:* {objects}'}})
    if keywords:
        blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': f'Keywords: {_esc(keywords)}'}]})
    blocks.append({'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': 'View on TNS'},
                                                    'url': TNS_NOTE_URL.format(note_id)}]})
    return f'New AstroNote {note_id}: {title}', blocks


def _post(client, note_id, note):
    from slack_sdk.errors import SlackApiError
    fallback, blocks = build_message(note_id, note)
    try:
        client.chat_postMessage(channel=_env('SLACK_CHANNEL_ID_ALERT'), text=fallback, blocks=blocks, unfurl_links=False)
        return True
    except SlackApiError as e:
        status.event(BOT, f'Slack post of AstroNote {note_id} failed: {e.response.get("error")}', level='error', count=False)
        return False


# ── run ───────────────────────────────────────────────────────────────────────

def _poll():
    problem = setup_problem()
    status.update(BOT, detail={'setup': problem} if problem else {})
    if problem:
        raise RuntimeError(problem)
    notes = fetch_recent_notes()
    sent = _load_sent()
    if sent is None:                               # first run: remember what is there, post nothing
        _save_sent(set(notes))
        status.event(BOT, f'First run: {len(notes)} recent notes marked as already posted', count=False)
        return f'First run: {len(notes)} notes marked as posted.'
    new = sorted(((k, v) for k, v in notes.items() if k not in sent), key=lambda kv: _txt(kv[1].get('public_timestamp')))
    if not new:
        return f'{len(notes)} recent notes, nothing new.'
    from slack_sdk import WebClient
    client = WebClient(token=_env('SLACK_BOT_TOKEN'))
    posted = 0
    for note_id, note in new:
        sent.add(note_id)
        _save_sent(sent)                           # saved before posting: a restart never posts twice
        if _post(client, note_id, note):
            posted += 1
            status.event(BOT, f'AstroNote {note_id}: {_txt(note.get("title"))[:160]}')
        else:
            sent.discard(note_id)                  # retry next time
            _save_sent(sent)
        time.sleep(1.1)                            # Slack: about one message per second per channel
    return f'Posted {posted} of {len(new)} new notes.'


def run():
    return status.guarded_run(BOT, _poll)
