"""Session/user helpers shared by every blueprint.

Who is logged in lives in ``session['user']`` (a signed client-side cookie) with the keys
``email, name, picture, is_admin, role, is_great_lab_member, groups, api_key``.
``refresh_user_session`` (installed as a ``before_request`` hook) re-syncs
``is_admin`` / ``is_great_lab_member`` / ``picture`` from the database on every request and
exposes the full user row as ``g.current_user``.

Permission levels used across the site (from weakest to strongest):

    logged in          -> ``current_user()`` is not None
    non-guest          -> ``is_non_guest()``   (role != 'guest', or admin)
    GREAT_Lab / admin  -> ``is_great_lab_member()``
    admin              -> ``is_admin()``

The ``*_required`` decorators below wrap those checks for new code. Existing routes still
carry their own inline checks (there are ~240 of them with slightly different failure
responses); convert them gradually, never change the failure response of an endpoint the
frontend already depends on without checking the JS.
"""
import logging
from functools import wraps

from flask import flash, g, jsonify, redirect, request, session, url_for

from app.db.auth import get_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session sync (before_request)
# ---------------------------------------------------------------------------

def refresh_user_session():
    """Refresh user session data from database on every request (registered globally)."""
    if 'user' not in session:
        return
    if request.path.startswith('/static'):
        return

    user_email = session['user']['email']
    try:
        user_data = get_user(user_email)  # includes groups via single extra query
    except Exception as exc:
        logger.warning("refresh_user_session skipped because database is unavailable: %s", exc)
        return

    if not user_data:
        return

    g.current_user = user_data

    # Sync is_admin
    current_is_admin = user_data.get('is_admin', False)
    if session['user'].get('is_admin') != current_is_admin:
        session['user']['is_admin'] = current_is_admin
        session.modified = True

    # Sync groups / GREATLab membership
    user_groups = user_data.get('groups', [])
    is_great_lab_member = 'GREAT_Lab' in user_groups or current_is_admin
    if session['user'].get('is_great_lab_member') != is_great_lab_member:
        session['user']['is_great_lab_member'] = is_great_lab_member
        session.modified = True

    # Sync picture — DB is the source of truth.
    # Never store base64 in the session cookie (4KB limit); templates use g.current_user.picture instead.
    db_picture = user_data.get('picture') or ''
    session_picture = session['user'].get('picture') or ''
    if not db_picture.startswith('data:image') and db_picture != session_picture:
        session['user']['picture'] = db_picture
        session.modified = True
    # If session accidentally has base64, clear it (g.current_user.picture is used for display)
    if session_picture.startswith('data:image'):
        session['user']['picture'] = ''
        session.modified = True


def update_user_session_groups(user_email):
    """Re-read the user's groups into the session (call after group membership changes)."""
    if 'user' in session and session['user']['email'] == user_email:
        try:
            user_data = get_user(user_email)
        except Exception as exc:
            logger.warning("update_user_session_groups skipped because database is unavailable: %s", exc)
            return
        user_groups = user_data.get('groups', []) if user_data else []

        session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups or session['user'].get('is_admin', False)
        session['user']['groups'] = user_groups
        session.modified = True


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def current_user():
    """The session user dict, or None when nobody is logged in."""
    return session.get('user')


def is_logged_in() -> bool:
    return 'user' in session


def is_admin() -> bool:
    u = session.get('user')
    return bool(u and u.get('is_admin', False))


def is_guest() -> bool:
    u = session.get('user')
    return bool(u and u.get('role', 'guest') == 'guest' and not u.get('is_admin', False))


def is_non_guest() -> bool:
    return is_logged_in() and not is_guest()


def is_great_lab_member() -> bool:
    u = session.get('user')
    return bool(u and (u.get('is_great_lab_member', False) or u.get('is_admin', False)))


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------
#
# JSON endpoints (the vast majority of routes):
#
#     @bp.route('/api/thing')          # the route decorator stays outermost
#     @login_required                  # -> {'error': 'Unauthorized'} 401 when not logged in
#     def thing(): ...
#
#     @admin_required                  # -> {'error': 'Access denied'} 403 unless is_admin
#     @login_required(error='Access denied', status=403)   # legacy variant used by some routes
#
# HTML pages: use ``login_required_page`` / ``admin_required_page`` (flash + redirect).
#
# These reproduce, byte for byte, the inline checks that the routes used before the
# 2026-09 refactor; the endpoint name is preserved by functools.wraps.

def login_required(view=None, *, error='Unauthorized', status=401):
    """JSON API guard: requires ``session['user']``; otherwise ``{'error': error}`` with ``status``."""
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if 'user' not in session:
                return jsonify({'error': error}), status
            return fn(*args, **kwargs)
        return wrapper
    return decorate(view) if view is not None else decorate


def admin_required(view=None, *, error='Access denied', status=403):
    """JSON API guard: requires an admin session; otherwise ``{'error': error}`` with ``status``."""
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if 'user' not in session or not session['user'].get('is_admin'):
                return jsonify({'error': error}), status
            return fn(*args, **kwargs)
        return wrapper
    return decorate(view) if view is not None else decorate


def login_required_page(view):
    """HTML page guard: flash + redirect to the login page when nobody is logged in."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('basic.login'))
        return view(*args, **kwargs)
    return wrapper


def admin_required_page(view):
    """HTML page guard: flash + redirect home unless the session user is an admin."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('basic.home'))
        return view(*args, **kwargs)
    return wrapper


def great_lab_required_page(view):
    """HTML page guard: GREAT_Lab members or admins only."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('basic.login'))
        if not is_great_lab_member():
            flash('Access denied. This page is only available to GREAT Lab members.', 'error')
            return redirect(url_for('basic.home'))
        return view(*args, **kwargs)
    return wrapper
