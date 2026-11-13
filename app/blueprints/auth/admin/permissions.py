"""Admin › Permissions (/admin/permissions): every "who may do what" setting on one page.

- Actions: who may upload / delete spectra and photometry (app/core/permissions.py).
- Check someone: what one account may do and open, with the reason.
- Private pages: extra groups per GREAT Lab page (private_area/page_perms.py API).
- Source visibility: default visibility per photometry / spectra source (settings.py API).
admin_permissions.js drives the page from the JSON in #permData.
"""
from flask import jsonify, render_template, request, session

from app.core import permissions as perms
from app.core.auth import admin_required, admin_required_page
from app.db.auth import get_groups, get_users

from . import admin_bp


def _person(email, u):
    shown = u.get('username') if u.get('has_placeholder_email') and u.get('username') else email
    return {'email': email, 'name': u.get('name') or shown, 'shown': shown,
            'role': u.get('role', 'guest'), 'groups': list(u.get('groups') or []),
            'picture': u.get('picture') or ''}


def _who(users, rules, action):
    """Emails of everyone who may do ``action`` (admins included), sorted by name."""
    out = [email for email, u in users.items() if perms.explain(dict(u, email=email), action, rules)[0]]
    return sorted(out, key=lambda e: (users[e].get('name') or e).lower())


def _private_pages():
    from app.blueprints.private_area.helpers import _PRIVATE_PAGE_LABELS, _PRIVATE_PAGES
    return _PRIVATE_PAGES, _PRIVATE_PAGE_LABELS


@admin_bp.route('/admin/permissions')
@admin_required_page
def permissions_page():
    users = get_users()
    rules = perms.get_rules(fresh=True)
    pages, labels = _private_pages()
    data = {
        'levels': [{'key': k, 'label': v} for k, v in perms.LEVELS.items()],
        'actions': [{'key': key, 'area': area, 'label': label, 'desc': desc,
                     'default': default, 'rule': rules[key], 'who': _who(users, rules, key)}
                    for key, (area, label, desc, default) in perms.ACTIONS.items()],
        'people': [_person(e, u) for e, u in sorted(users.items(), key=lambda kv: (kv[1].get('name') or kv[0]).lower())],
        'groups': sorted(get_groups().keys()),
        'pages': [{'key': p, 'label': labels.get(p, p)} for p in pages],
        'me': (session.get('user') or {}).get('email'),
    }
    return render_template('admin_permissions.html', current_path='/admin/permissions', data=data,
                           n_people=len(users), n_actions=len(perms.ACTIONS))


@admin_bp.route('/admin/permissions/action', methods=['POST'])
@admin_required
def permissions_save_action():
    body = request.get_json(silent=True) or {}
    action = body.get('action')
    if action not in perms.ACTIONS:
        return jsonify({'success': False, 'error': 'Unknown action'}), 400
    if body.get('reset'):
        rule = perms.default_rule(action)
    else:
        rule = {'level': body.get('level'), 'groups': body.get('groups') or [], 'users': body.get('users') or []}
        if not isinstance(rule['groups'], list) or not isinstance(rule['users'], list):
            return jsonify({'success': False, 'error': 'groups and users must be lists'}), 400
        users = get_users()
        unknown = [u for u in rule['users'] if str(u).lower() not in {e.lower() for e in users}]
        if unknown:
            return jsonify({'success': False, 'error': f'Unknown account: {unknown[0]}'}), 400
        groups = set(get_groups().keys())
        missing = [g for g in rule['groups'] if g not in groups]
        if missing:
            return jsonify({'success': False, 'error': f'Unknown group: {missing[0]}'}), 400
    try:
        stored = perms.save_rule(action, rule)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except RuntimeError:
        return jsonify({'success': False, 'error': 'Could not save'}), 500
    rules = perms.get_rules()
    return jsonify({'success': True, 'rule': stored, 'who': _who(get_users(), rules, action)})


@admin_bp.route('/admin/permissions/check')
@admin_required
def permissions_check():
    """What one account may do (actions) and open (private pages), with the reason."""
    email = (request.args.get('email') or '').strip()
    users = get_users()
    u = next((dict(v, email=k) for k, v in users.items() if k.lower() == email.lower()), None)
    if not u:
        return jsonify({'success': False, 'error': 'Unknown account'}), 404
    from app.blueprints.private_area.helpers import user_can_access_page
    from app.db.auth import get_page_groups
    rules = perms.get_rules()
    actions = []
    for key, (_area, label, _desc, _default) in perms.ACTIONS.items():
        ok, why = perms.explain(u, key, rules)
        actions.append({'key': key, 'label': label, 'allowed': ok, 'why': why})
    pages, labels = _private_pages()
    groups = set(u.get('groups') or [])
    page_rows = []
    for p in pages:
        ok = user_can_access_page(u, p)
        if u.get('is_admin'):
            why = 'admin'
        elif 'GREAT_Lab' in groups:
            why = 'GREAT Lab member'
        else:
            hit = sorted(groups & set(get_page_groups(p)))
            why = f'group {hit[0]}' if hit else 'not GREAT Lab, no added group'
        page_rows.append({'key': p, 'label': labels.get(p, p), 'allowed': ok, 'why': why})
    return jsonify({'success': True, 'person': _person(u['email'], u), 'is_admin': bool(u.get('is_admin')),
                    'actions': actions, 'pages': page_rows})
