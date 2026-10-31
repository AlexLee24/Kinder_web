"""Web Push to phones and desktops (after EAU_Web's modules/messaging/webpush.py).

Members turn push on per device in Settings (js/push.js → /api/push/*) and tick which CATEGORIES it takes; the
browser's PushSubscription is stored in auth.push_subscriptions (app/db/push.py). Admins see who has it on and send
from Admin › Push; the GCN bot pushes Einstein Probe alerts (push_ep_alert). /sw.js shows the notification and opens
``url`` when it is tapped.

Keys: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in kinder.env (make a pair with scripts/gen_vapid_keys.py). Every server
that sends must use the same pair: subscriptions are tied to the public key, so changing it means every member has
to turn push on again. VAPID_SUBJECT is the contact the push services see (mailto: or https:).

iPhone / iPad: only after "Add to Home Screen", opened from that icon (iOS 16.4+). Android and desktop Chrome, Edge,
Firefox and Safari work in the browser.
"""
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.config import config  # noqa: F401  -- loads kinder.env

logger = logging.getLogger(__name__)

# Kinds of push; each device ticks the ones it wants in Settings (all by default). members: offered (and sent) only
# to GREAT Lab members and admins.
CATEGORIES = {
    'announce': {'label': 'Messages from the Kinder admins', 'members': False},
    'alerts':   {'label': 'Einstein Probe alerts (from the GCN bot)', 'members': True},
    'trigger':  {'label': 'My Trigger duty reminders (at Lulin sunset)', 'members': True},
}
APP_NAME = 'Kinder'
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='webpush')


def public_key():
    return os.getenv('VAPID_PUBLIC_KEY', '').strip()


def enabled():
    return bool(public_key() and os.getenv('VAPID_PRIVATE_KEY', '').strip())


def _subject():
    sub = os.getenv('VAPID_SUBJECT') or config.APP_BASE_URL or ''
    return sub if sub.startswith(('https:', 'mailto:')) else 'mailto:' + (config.ADMIN_EMAIL or 'admin@localhost')


def is_member(user):
    """GREAT Lab member or admin (a dict from app.db.auth.get_user / get_users)."""
    return bool(user) and ('GREAT_Lab' in (user.get('groups') or []) or bool(user.get('is_admin')))


def categories_for(user):
    """{key: label} of the categories this account can take."""
    member = is_member(user)
    return {k: v['label'] for k, v in CATEGORIES.items() if member or not v['members']}


def member_ids():
    """usr_id of every GREAT Lab member and admin."""
    from app.db.auth import get_users
    return [u['usr_id'] for u in get_users().values() if is_member(u)]


def valid_subscription(sub):
    """The browser's PushSubscription.toJSON(): {'endpoint': 'https://…', 'keys': {'p256dh', 'auth'}}."""
    if not isinstance(sub, dict):
        return None
    endpoint = str(sub.get('endpoint') or '')
    keys = sub.get('keys') if isinstance(sub.get('keys'), dict) else {}
    p256dh, auth = str(keys.get('p256dh') or ''), str(keys.get('auth') or '')
    if not endpoint.startswith('https://') or len(endpoint) > 1000 or not p256dh or not auth \
            or len(p256dh) > 200 or len(auth) > 100:
        return None
    return endpoint, p256dh, auth


def payload(title, body='', url='/', tag=None):
    return {'title': (title or APP_NAME)[:120], 'body': (body or '')[:500], 'url': url or '/',
            'tag': tag or 'kinder-' + uuid.uuid4().hex[:10]}


def send_one(sub, data):
    """Send to one subscription row now. Returns (ok, message); a dead subscription is deleted."""
    from pywebpush import WebPushException, webpush

    from app.db import push as db
    try:
        webpush(subscription_info={'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}},
                data=json.dumps(data, ensure_ascii=False),
                vapid_private_key=os.getenv('VAPID_PRIVATE_KEY', '').strip(),
                vapid_claims={'sub': _subject()},
                headers={'Urgency': 'high'},          # otherwise Android may hold it back while the phone dozes
                ttl=24 * 3600, timeout=10)
        db.mark_ok(sub['id'])
        return True, 'Delivered to the push service'
    except WebPushException as exc:
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
        gone = code in (404, 410)
        removed = db.mark_failed(sub['id'], f'HTTP {code}' if code else str(exc)[:200], gone)
        logger.info('webpush failed sub=%s code=%s gone=%s', sub['id'], code, gone)
        if gone:
            return False, 'The device turned push off (subscription expired): removed'
        return False, f'Push service refused it (HTTP {code})' + (' — removed after repeated failures' if removed else '')
    except Exception as exc:
        db.mark_failed(sub['id'], f'{type(exc).__name__}: {exc}'[:200], False)
        logger.warning('webpush error sub=%s: %s', sub['id'], exc)
        return False, f'Could not reach the push service ({type(exc).__name__})'


def _send_all(subs, data, broadcast_id=None):
    ok = bad = 0
    for s in subs:
        if send_one(s, data)[0]:
            ok += 1
        else:
            bad += 1
    if broadcast_id is not None:
        try:
            from app.db import push as db
            db.finish_broadcast(broadcast_id, ok, bad)
        except Exception:
            logger.exception('webpush: could not record broadcast %s', broadcast_id)
    return ok, bad


def send_to_users(usr_ids, title, body='', url='/', category='announce', broadcast_id=None, wait=False):
    """Push to every device of these accounts that takes ``category`` (None: every device, for tests). In the
    background unless ``wait``;
    returns the number of devices it goes to (with ``wait``: (delivered, failed))."""
    from app.db import push as db
    if not enabled() or not usr_ids:
        return (0, 0) if wait else 0
    subs = db.subscriptions(usr_ids=usr_ids, category=category)
    data = payload(title, body, url)
    if wait:
        return _send_all(subs, data, broadcast_id)
    try:
        _pool.submit(_send_all, subs, data, broadcast_id)
    except RuntimeError:            # interpreter shutting down
        pass
    return len(subs)


def device_label(user_agent, endpoint=''):
    """(platform, browser) for people, e.g. ('iPhone', 'Home Screen app'), ('Mac', 'Chrome')."""
    ua = user_agent or ''
    if 'iPhone' in ua:
        plat = 'iPhone'
    elif 'iPad' in ua or ('Macintosh' in ua and 'Mobile/' in ua):
        plat = 'iPad'
    elif 'Android' in ua:
        plat = 'Android'
    elif 'Windows' in ua:
        plat = 'Windows'
    elif 'Macintosh' in ua or 'Mac OS X' in ua:
        plat = 'Mac'
    elif 'Linux' in ua or 'CrOS' in ua:
        plat = 'Linux'
    else:
        plat = 'Other'
    if plat in ('iPhone', 'iPad') and 'Safari/' not in ua:
        browser = 'Home Screen app'          # iOS only subscribes from the Home Screen app, whose UA has no Safari/
    elif 'Edg/' in ua:
        browser = 'Edge'
    elif 'Firefox/' in ua or 'FxiOS' in ua:
        browser = 'Firefox'
    elif 'SamsungBrowser' in ua:
        browser = 'Samsung Internet'
    elif 'OPR/' in ua:
        browser = 'Opera'
    elif 'Chrome/' in ua or 'CriOS' in ua:
        browser = 'Chrome'
    elif 'Safari/' in ua or 'web.push.apple.com' in (endpoint or ''):
        browser = 'Safari'
    else:
        browser = 'Browser'
    return plat, browser


def push_ep_alert(name, ra, dec, log=None):
    """Einstein Probe alert (app/services/bots/gcn.py) → every GREAT Lab member's devices that take 'alerts'.
    Never raises: the Slack post and the robot must not wait on it."""
    try:
        if not enabled():
            return 0
        try:
            from app.services.bots.robot import MIN_ALT, visibility_tonight
            vis = visibility_tonight(name, ra, dec)
            if vis.get('observable'):
                when = f"observable tonight from Lulin (max alt {vis['max_alt']:.0f}°)"
            elif vis.get('max_alt') is not None:
                when = f"stays below {MIN_ALT:.0f}° tonight (max {vis['max_alt']:.0f}°)"
            else:
                when = 'not observable for the rest of tonight'
        except Exception:
            when = ''
        body = f'RA {ra}  Dec {dec}' + (f' · {when}' if when else '') + ' · SLT script in Slack'
        n = send_to_users(member_ids(), f'Einstein Probe alert {name}', body, '/bots', category='alerts')
        if log:
            log.info('EP alert %s pushed to %d device(s)', name, n)
        return n
    except Exception as exc:
        logger.warning('EP alert push failed for %s: %s', name, exc)
        return 0
