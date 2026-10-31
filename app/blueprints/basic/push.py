"""Web Push for the signed-in user (the Notifications panel of /settings, js/push.js; /sw.js re-subscribes through
/api/push/subscribe when the browser rotates a subscription). Sending lives in app/services/notifications/webpush.py,
the admin side in app/blueprints/auth/admin/push.py. Registered on basic_bp (imported by the package __init__).
"""
import logging

from flask import g, jsonify, request, session

from app.core import rate_limit

from .routes import basic_bp

logger = logging.getLogger(__name__)


def _usr_id():
    """The signed-in account's usr_id, or None."""
    email = (session.get('user') or {}).get('email')
    if not email:
        return None
    cur = getattr(g, 'current_user', None) or {}
    if cur.get('email') == email and cur.get('usr_id'):
        return cur['usr_id']
    from app.db.auth import get_user
    u = get_user(email)
    return u['usr_id'] if u else None


def _me():
    from app.db.auth import get_user
    email = (session.get('user') or {}).get('email')
    return get_user(email) if email else None


def _login_needed():
    return jsonify(ok=False, error='Please log in.'), 401


@basic_bp.route('/api/push/key')
def api_push_key():
    from app.services.notifications import webpush
    return jsonify(ok=webpush.enabled(), key=webpush.public_key(),
                   categories=list(webpush.categories_for(_me()).items()))     # [[key, label], …] in this order


@basic_bp.route('/api/push/status', methods=['POST'])
def api_push_status():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import push as db
    cats, n = db.status(uid, str((request.get_json(silent=True) or {}).get('endpoint') or ''))
    return jsonify(ok=True, subscribed=cats is not None, categories=cats or [], devices=n)


@basic_bp.route('/api/push/subscribe', methods=['POST'])
def api_push_subscribe():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import push as db
    from app.services.notifications import webpush
    if not webpush.enabled():
        return jsonify(ok=False, error='Push is not set up on this server.'), 503
    data = request.get_json(silent=True) or {}
    sub = webpush.valid_subscription(data.get('subscription'))
    if not sub:
        return jsonify(ok=False, error='Invalid subscription.'), 400
    allowed = webpush.categories_for(_me())
    asked = data.get('categories')
    old = str(data.get('old_endpoint') or '')
    if not isinstance(asked, list) and old:          # sw.js: the browser replaced the subscription — keep its choice
        asked, _ = db.status(uid, old)
    cats = [c for c in allowed if c in asked] if isinstance(asked, list) else list(allowed)   # default: all of them
    db.save(uid, *sub, cats, user_agent=request.headers.get('User-Agent', ''))
    if old and old != sub[0]:
        db.remove(uid, old)
    logger.info('push subscribe usr=%s host=%s', uid, sub[0].split('/')[2])
    return jsonify(ok=True)


@basic_bp.route('/api/push/unsubscribe', methods=['POST'])
def api_push_unsubscribe():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import push as db
    n = db.remove(uid, str((request.get_json(silent=True) or {}).get('endpoint') or ''))
    return jsonify(ok=True, removed=n)


@basic_bp.route('/api/push/test', methods=['POST'])
def api_push_test():
    """A test push to every device of the signed-in user; waits for the push services' answers."""
    uid = _usr_id()
    if not uid:
        return _login_needed()
    if not rate_limit.allow(f'push_test:{uid}', 5, 60):
        return jsonify(ok=False, error='Please wait a minute before testing again.'), 429
    from app.services.notifications import webpush
    ok, bad = webpush.send_to_users([uid], 'Kinder test notification',
                                    'If you can read this, push works on this device.', '/settings#push',
                                    category=None, wait=True)
    return jsonify(ok=ok > 0, delivered=ok, failed=bad)
