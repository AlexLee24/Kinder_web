"""Admin › Push (/admin/push), after EAU_Web's push broadcast + push devices pages: who has push on (and who has not),
their devices, a test push to one device or one person, and messages to me / GREAT Lab / admins / a group / everyone /
picked people. Sending: app/services/notifications/webpush.py; tables: app/db/push.py."""
import logging

from flask import jsonify, render_template, request, session

from app.core.auth import admin_required, admin_required_page

from . import admin_bp
from .helpers import audit

logger = logging.getLogger(__name__)

TARGETS = {
    'me': 'Only me',
    'members': 'GREAT Lab members',
    'admins': 'Admins',
    'group': 'A group',
    'all': 'Everyone with push',
    'users': 'Picked people',
}


def _clean_url(u):
    u = (u or '').strip()[:500]
    if not u:
        return ''
    if (u.startswith('/') and not u.startswith('//')) or u.startswith(('https://', 'http://')):
        return u
    return None


def _people():
    """Every account with its push devices: [{usr_id, email, name, picture, groups, is_admin, is_member, devices}]."""
    from app.db import push as db
    from app.db.auth import get_users
    from app.services.notifications import webpush
    by_user = {}
    for s in db.subscriptions():
        plat, browser = webpush.device_label(s['user_agent'], s['endpoint'])
        by_user.setdefault(s['usr_id'], []).append({
            'id': s['id'], 'platform': plat, 'browser': browser, 'host': s['endpoint'].split('/')[2],
            'created_at': s['created_at'].isoformat(timespec='seconds') if s['created_at'] else '',
            'last_ok_at': s['last_ok_at'].isoformat(timespec='seconds') if s['last_ok_at'] else '',
            'fail_count': s['fail_count'], 'last_error': s['last_error'] or '', 'user_agent': s['user_agent'] or '',
        })
    people = []
    for email, u in get_users().items():
        groups = u.get('groups') or []
        people.append({
            'usr_id': u['usr_id'], 'email': email, 'name': u.get('display_name') or u.get('name') or email,
            'picture': u.get('picture') or '', 'groups': groups, 'is_admin': bool(u.get('is_admin')),
            'is_member': 'GREAT_Lab' in groups or bool(u.get('is_admin')),
            'placeholder_email': bool(u.get('has_placeholder_email')),
            'devices': by_user.get(u['usr_id'], []),
        })
    people.sort(key=lambda p: (not p['devices'], not p['is_member'], p['name'].lower()))
    return people


def _resolve(target, usr_ids, group, people):
    """Account ids a message goes to."""
    me = (session.get('user') or {}).get('email')
    if target == 'me':
        return [p['usr_id'] for p in people if p['email'] == me]
    if target == 'members':
        return [p['usr_id'] for p in people if p['is_member']]
    if target == 'admins':
        return [p['usr_id'] for p in people if p['is_admin']]
    if target == 'group':
        return [p['usr_id'] for p in people if group and group in p['groups']]
    if target == 'all':
        return [p['usr_id'] for p in people if p['devices']]
    if target == 'users':
        wanted = {int(i) for i in usr_ids or [] if str(i).isdigit()}
        return [p['usr_id'] for p in people if p['usr_id'] in wanted]
    return []


def _estimate(ids, people):
    idset = set(ids)
    chosen = [p for p in people if p['usr_id'] in idset]
    return {'recipients': len(chosen), 'with_push': sum(1 for p in chosen if p['devices']),
            'devices': sum(len(p['devices']) for p in chosen)}


@admin_bp.route('/admin/push')
@admin_required_page
def push_page():
    from app.db import push as db
    from app.db.auth import get_groups
    from app.services.notifications import webpush
    people = _people()
    members = [p for p in people if p['is_member']]
    devices = [d for p in people for d in p['devices']]
    plats = {}
    for d in devices:
        plats[d['platform']] = plats.get(d['platform'], 0) + 1
    summary = {
        'people': len(people), 'people_on': sum(1 for p in people if p['devices']),
        'members': len(members), 'members_on': sum(1 for p in members if p['devices']),
        'devices': len(devices), 'failing': sum(1 for d in devices if d['fail_count']),
        'never_ok': sum(1 for d in devices if not d['last_ok_at']),
        'platforms': sorted(plats.items(), key=lambda x: -x[1]),
    }
    return render_template('admin_push.html', current_path='/admin/push', people=people, summary=summary,
                           history=db.recent_broadcasts(), targets=TARGETS, groups=sorted(get_groups().keys()),
                           push_on=webpush.enabled(), me=(session.get('user') or {}).get('email'))


@admin_bp.route('/admin/push/preview', methods=['POST'])
@admin_required
def push_preview():
    data = request.get_json(silent=True) or {}
    people = _people()
    ids = _resolve(data.get('target'), data.get('usr_ids'), data.get('group'), people)
    return jsonify({'ok': True, **_estimate(ids, people)})


@admin_bp.route('/admin/push/send', methods=['POST'])
@admin_required
def push_send():
    from app.db import push as db
    from app.services.notifications import webpush
    data = request.get_json(silent=True) or {}
    if not webpush.enabled():
        return jsonify({'ok': False, 'error': 'Push is not set up: add the VAPID keys to kinder.env.'}), 503
    title = str(data.get('title') or '').strip()[:120]
    body = str(data.get('body') or '').strip()[:500]
    url = _clean_url(data.get('url'))
    target = data.get('target') if data.get('target') in TARGETS else None
    if not title:
        return jsonify({'ok': False, 'error': 'Write a title.'}), 400
    if url is None:
        return jsonify({'ok': False, 'error': 'The link must be a Kinder path (/…) or an http(s) address.'}), 400
    if not target:
        return jsonify({'ok': False, 'error': 'Choose who gets it.'}), 400
    people = _people()
    group = str(data.get('group') or '')
    ids = _resolve(target, data.get('usr_ids'), group, people)
    est = _estimate(ids, people)
    if not est['devices']:
        return jsonify({'ok': False, 'error': 'Nobody in that list has push turned on.'}), 400
    desc = ''
    if target == 'users':
        idset = set(ids)
        desc = ', '.join(p['name'] for p in people if p['usr_id'] in idset)
    elif target == 'group':
        desc = group
    me = (session.get('user') or {}).get('email')
    bid = db.add_broadcast(me, title, body, url, target, desc, est['recipients'], est['devices'])
    webpush.send_to_users(ids, title, body, url or '/', broadcast_id=bid)
    audit('push_send', target, f'broadcast={bid} recipients={est["recipients"]} devices={est["devices"]}')
    return jsonify({'ok': True, 'id': bid, **est})


@admin_bp.route('/admin/push/device/<int:sub_id>/test', methods=['POST'])
@admin_required
def push_device_test(sub_id):
    """A test push to one device; waits for the push service's answer."""
    from app.db import push as db
    from app.services.notifications import webpush
    if not webpush.enabled():
        return jsonify({'ok': False, 'error': 'Push is not set up on this server.'}), 503
    subs = db.subscriptions(sub_id=sub_id)
    if not subs:
        return jsonify({'ok': False, 'error': 'That device is gone.'}), 404
    ok, msg = webpush.send_one(subs[0], webpush.payload('Kinder test notification',
                                                        'An admin sent this test to check push on this device.', '/'))
    audit('push_test_device', str(sub_id), 'ok' if ok else msg)
    return jsonify({'ok': ok, 'message': msg})


@admin_bp.route('/admin/push/user/<int:usr_id>/test', methods=['POST'])
@admin_required
def push_user_test(usr_id):
    """A test push to every device of one person."""
    from app.services.notifications import webpush
    if not webpush.enabled():
        return jsonify({'ok': False, 'error': 'Push is not set up on this server.'}), 503
    ok, bad = webpush.send_to_users([usr_id], 'Kinder test notification',
                                    'An admin sent this test to check push on your devices.', '/', wait=True)
    audit('push_test_user', str(usr_id), f'delivered={ok} failed={bad}')
    return jsonify({'ok': ok > 0, 'delivered': ok, 'failed': bad})


@admin_bp.route('/admin/push/device/<int:sub_id>/delete', methods=['POST'])
@admin_required
def push_device_delete(sub_id):
    from app.db import push as db
    ok = db.delete(sub_id)
    audit('push_device_delete', str(sub_id))
    return jsonify({'ok': ok})
