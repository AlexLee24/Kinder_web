"""The bell in the top bar (js/notify.js, after EAU_Web's notification centre): the signed-in user's notifications
from auth.notifications (app/db/notifications.py). Written by app/services/notifications/webpush.py together with the
push. Registered on basic_bp (imported by the package __init__)."""
from flask import abort, jsonify, redirect, request, session, url_for

from .push import _usr_id
from .routes import basic_bp

ICONS = {'announce': 'megaphone', 'alerts': 'bolt', 'trigger': 'send'}


def _login_needed():
    return jsonify(ok=False, error='Please log in.'), 401


def _ids(data):
    ids = data.get('ids')
    return [int(i) for i in ids if str(i).isdigit()] if isinstance(ids, list) else []


@basic_bp.route('/api/notifications')
def api_notifications():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import notifications as inbox
    limit = min(max(request.args.get('limit', 30, type=int), 1), 100)
    items = [{'id': n['id'], 'kind': n['kind'], 'icon': ICONS.get(n['kind'], 'bell'), 'title': n['title'],
              'body': n['body'], 'created_at': n['created_at'].isoformat(timespec='seconds'),
              'is_read': n['read_at'] is not None, 'has_link': bool(n['url'])} for n in inbox.recent(uid, limit)]
    return jsonify(ok=True, items=items, unread=inbox.unread_count(uid))


@basic_bp.route('/api/notifications/count')
def api_notifications_count():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import notifications as inbox
    return jsonify(ok=True, unread=inbox.unread_count(uid))


@basic_bp.route('/api/notifications/read', methods=['POST'])
def api_notifications_read():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import notifications as inbox
    data = request.get_json(silent=True) or {}
    inbox.mark_read(uid, None if data.get('all') else _ids(data))
    return jsonify(ok=True, unread=inbox.unread_count(uid))


@basic_bp.route('/api/notifications/delete', methods=['POST'])
def api_notifications_delete():
    uid = _usr_id()
    if not uid:
        return _login_needed()
    from app.db import notifications as inbox
    data = request.get_json(silent=True) or {}
    inbox.delete(uid, _ids(data), read=bool(data.get('read')))
    return jsonify(ok=True, unread=inbox.unread_count(uid))


@basic_bp.route('/notifications/<int:notif_id>')
def notification_open(notif_id):
    """A bell entry (or its push) was opened: mark it read and go to its link."""
    if 'user' not in session:
        return redirect(url_for('basic.login'))
    uid = _usr_id()
    from app.db import notifications as inbox
    url = inbox.open_one(uid, notif_id) if uid else None
    if url is None:
        abort(404)
    if not url or not (url.startswith(('https://', 'http://')) or (url.startswith('/') and not url.startswith('//'))):
        url = '/'
    return redirect(url)
