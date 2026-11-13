"""Who may do what: actions an admin opens to more people in Admin › Permissions.

Every action has a level (the least role that may do it) plus optional extra groups and
extra people who may do it regardless of their role. Admins may always do everything.

Levels, widest first:
  login      anyone signed in, guests included
  user       users and admins (accounts that are not guests)
  great_lab  GREAT_Lab members and admins
  admin      admins only

Stored as JSON in auth.system_settings['action_permissions'] ({action: {level, groups, users}});
missing actions fall back to their default. Read through a short cache so pages that ask
several times per request do not hit the database each time.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from functools import wraps

from flask import jsonify, session

logger = logging.getLogger(__name__)

SETTING_KEY = 'action_permissions'

LEVELS = {
    'login': 'Anyone signed in (guests too)',
    'user': 'Users (not guests)',
    'great_lab': 'GREAT Lab members',
    'admin': 'Admins only',
}
_LEVEL_ORDER = ['login', 'user', 'great_lab', 'admin']

# action -> (area, label, description, default level). Order = order on the admin page.
ACTIONS = {
    'upload_spectrum': ('Objects', 'Upload spectra',
                        'Object page › Spectroscopy › Upload.', 'user'),
    'delete_spectrum': ('Objects', 'Delete spectra',
                        'Remove a whole spectrum from an object.', 'admin'),
    'upload_photometry': ('Objects', 'Upload photometry',
                          'Object page › Photometry › Upload (file or single points).', 'admin'),
    'edit_photometry': ('Objects', 'Edit / delete photometry',
                        'Object page › Photometry › Edit: remove points.', 'admin'),
}

_CACHE_TTL = 15.0
_cache = {'at': 0.0, 'value': None}
_lock = threading.Lock()


def default_rule(action: str) -> dict:
    return {'level': ACTIONS[action][3], 'groups': [], 'users': []}


def _clean_rule(action: str, raw) -> dict:
    rule = default_rule(action)
    if isinstance(raw, dict):
        if raw.get('level') in LEVELS:
            rule['level'] = raw['level']
        rule['groups'] = sorted({str(g).strip() for g in raw.get('groups') or [] if str(g).strip()})
        rule['users'] = sorted({str(u).strip().lower() for u in raw.get('users') or [] if str(u).strip()})
    return rule


def get_rules(fresh: bool = False) -> dict:
    """{action: {level, groups, users}} for every known action."""
    now = time.monotonic()
    with _lock:
        if not fresh and _cache['value'] is not None and now - _cache['at'] < _CACHE_TTL:
            return _cache['value']
    from app.db.auth import get_setting
    stored = {}
    try:
        stored = json.loads(get_setting(SETTING_KEY, '{}') or '{}')
    except (TypeError, ValueError):
        logger.warning('action_permissions setting is not valid JSON; using defaults')
    if not isinstance(stored, dict):
        stored = {}
    rules = {a: _clean_rule(a, stored.get(a)) for a in ACTIONS}
    with _lock:
        _cache.update(at=now, value=rules)
    return rules


def save_rule(action: str, rule: dict) -> dict:
    """Store one action's rule (validated); returns what was stored."""
    from app.db.auth import set_setting
    if action not in ACTIONS:
        raise KeyError(action)
    if rule.get('level') not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    rules = dict(get_rules(fresh=True))
    rules[action] = _clean_rule(action, rule)
    if not set_setting(SETTING_KEY, json.dumps(rules, sort_keys=True)):
        raise RuntimeError('could not save')
    with _lock:
        _cache.update(at=time.monotonic(), value=rules)
    return rules[action]


def explain(user: dict | None, action: str, rules: dict | None = None) -> tuple[bool, str]:
    """(allowed, why) for an account dict (session user or auth.get_users entry)."""
    if not user:
        return False, 'not signed in'
    rule = (rules or get_rules())[action]
    groups = set(user.get('groups') or [])
    email = (user.get('email') or '').lower()
    role = user.get('role') or 'guest'
    if user.get('is_admin'):
        return True, 'admin'
    level = rule['level']
    if level == 'login':
        return True, 'signed in'
    if level == 'user' and role in ('user', 'admin'):
        return True, 'user role'
    if level == 'great_lab' and (user.get('is_great_lab_member') or 'GREAT_Lab' in groups):
        return True, 'GREAT Lab member'
    hit = sorted(groups & set(rule['groups']))
    if hit:
        return True, f'group {hit[0]}'
    if email and email in rule['users']:
        return True, 'added by name'
    return False, f'needs: {LEVELS[level].lower()}'


def can(action: str, user: dict | None = None) -> bool:
    """May this account (default: the signed-in one) do ``action``?"""
    if user is None:
        user = session.get('user')
    try:
        return explain(user, action)[0]
    except Exception:
        logger.exception('permission check failed for %s', action)
        return bool(user and user.get('is_admin'))


def action_required(action: str):
    """JSON API guard: 401 when signed out, 403 when the account may not do ``action``."""
    label = ACTIONS[action][1].lower()

    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from app.core.auth import session_unverified, _unverified_response
            user = session.get('user')
            if not user:
                return jsonify({'success': False, 'error': f'Sign in to {label}.'}), 401
            if session_unverified():
                return _unverified_response()
            if not can(action, user):
                return jsonify({'success': False,
                                'error': f"Your account can't {label}. Ask an admin (Admin › Permissions)."}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorate


def init_app(app):
    """Templates call can('upload_spectrum') to show or hide controls."""
    app.jinja_env.globals['can'] = can
