"""Session/user helpers shared by every blueprint.

Who is logged in lives in ``session['user']`` (a signed client-side cookie) with the keys
``email, name, picture, is_admin, role, is_great_lab_member, groups, auth_method,
session_version, must_change_password, iat, last_seen``. API keys are never stored in
the session (they are kept hashed in the DB and shown only once when issued).
``start_user_session`` builds it at login; ``refresh_user_session`` (installed as a
``before_request`` hook) enforces the session policy and re-syncs
``is_admin`` / ``role`` / ``groups`` / ``is_great_lab_member`` / ``picture`` from the database on every request and
exposes the full user row as ``g.current_user``.

Session policy (enforced in ``refresh_user_session``):

    * ``iat`` (login time, epoch s) missing  -> legacy cookie, session cleared
    * older than ``SESSION_ABSOLUTE_MAX_S`` (30 days)              -> expired
    * idle longer than 1 h (admins) / 8 h (everyone else)          -> expired
    * ``session_version`` differs from the DB (password change, "log out all
      devices", admin force-logout)                                -> revoked
    * ``last_seen`` is re-written at most once per minute (cookie churn)
    * DB unreachable -> ``g.session_unverified = True``; admin checks then fail
      closed with 503 instead of trusting the cookie.

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
import time
from functools import wraps

from flask import current_app, flash, g, jsonify, make_response, redirect, request, session, url_for

from app.db.auth import get_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session policy
# ---------------------------------------------------------------------------

SESSION_ABSOLUTE_MAX_S = 30 * 24 * 3600   # matches PERMANENT_SESSION_LIFETIME
SESSION_IDLE_USER_S = 8 * 3600
SESSION_IDLE_ADMIN_S = 1 * 3600
LAST_SEEN_WRITE_INTERVAL_S = 60           # limit Set-Cookie churn


def idle_limit_seconds(is_admin: bool) -> int:
    return SESSION_IDLE_ADMIN_S if is_admin else SESSION_IDLE_USER_S


def start_user_session(user_data: dict, auth_method: str) -> None:
    """Replace the session with a fresh one for *user_data* (a get_user() dict).

    Used by every login path (Google, username/password, local admin). Clearing
    first prevents session fixation and drops leftovers from a previous user."""
    session.clear()
    session.permanent = True
    now = int(time.time())
    user_groups = list(user_data.get('groups') or [])
    is_admin_flag = bool(user_data.get('is_admin', False))
    picture = user_data.get('picture')
    if picture and picture.startswith('data:image'):
        picture = None   # keep base64 out of the 4 KB cookie
    email = user_data['email']
    session['user'] = {
        'email': email,
        'name': user_data.get('name') or user_data.get('username') or email.split('@')[0],
        'picture': picture,
        'is_admin': is_admin_flag,
        'role': user_data.get('role', 'guest'),
        'is_great_lab_member': 'GREAT_Lab' in user_groups or is_admin_flag,
        'groups': user_groups,
        'auth_method': auth_method,
        'session_version': int(user_data.get('session_version') or 0),
        'must_change_password': bool(user_data.get('must_change_password')),
        'iat': now,
        'last_seen': now,
    }


def _session_expiry_reason(user: dict, now: float) -> str | None:
    """Why the session in *user* is no longer valid (None if it still is)."""
    iat = user.get('iat')
    if not isinstance(iat, (int, float)):
        return 'legacy'
    if now - iat > SESSION_ABSOLUTE_MAX_S or iat - now > 300:
        return 'absolute'
    last_seen = user.get('last_seen')
    if not isinstance(last_seen, (int, float)):
        last_seen = iat
    if now - last_seen > idle_limit_seconds(bool(user.get('is_admin'))):
        return 'idle'
    return None


def _wants_json() -> bool:
    return request.path.startswith('/api/') or request.is_json


def _session_expired_response(reason: str):
    """Clear the session; HTML gets flash + redirect to login, API/JSON a 401."""
    email = (session.get('user') or {}).get('email')
    logger.info("Session of %s ended (%s)", email, reason)
    session.clear()
    if _wants_json():
        return jsonify({'error': 'Session expired, please log in again'}), 401
    if request.method == 'GET' and request.endpoint != 'basic.login':
        # Come back here after logging in again (validated by _safe_next on use).
        target = request.full_path if request.query_string else request.path
        if target.startswith('/') and not target.startswith('//'):
            session['next_url'] = target
    flash('Your session has expired. Please log in again.', 'info')
    return redirect(url_for('basic.login'))


# ---------------------------------------------------------------------------
# Session sync (before_request)
# ---------------------------------------------------------------------------

_SESSION_SKIP_PATHS = ('/static', '/csp-report')
_LOGIN_FLOW_ENDPOINTS = frozenset({
    'basic.login', 'auth.password_login', 'auth.admin_login', 'auth.google_login',
    'auth.google_callback', 'auth.logout',
})


def refresh_user_session():
    """Enforce the session policy and refresh user data from the database
    on every request (registered globally)."""
    if 'user' not in session:
        return
    if request.path.startswith(_SESSION_SKIP_PATHS):
        return

    user_email = session['user'].get('email')
    if not user_email:
        session.clear()
        return

    now = time.time()
    reason = _session_expiry_reason(session['user'], now)
    if reason and request.endpoint in _LOGIN_FLOW_ENDPOINTS:
        # Logging in / out with a stale cookie: just drop it and carry on.
        session.clear()
        return
    if reason == 'legacy':
        # Cookie issued before the session policy existed: log it out quietly
        # (one forced re-login after deploy).
        logger.info("refresh_user_session: clearing legacy session of %s", user_email)
        session.clear()
        return
    if reason:
        return _session_expired_response(reason)

    try:
        user_data = get_user(user_email)  # includes groups via single extra query
    except Exception as exc:
        # DB down: the cookie cannot be checked against the DB (revocation, role
        # changes). Keep it for ordinary pages, but admin checks fail closed.
        logger.warning("refresh_user_session: database unavailable, session unverified: %s", exc)
        g.session_unverified = True
        return

    if not user_data:
        # The account was deleted: the session must not outlive it.
        # (Tests use synthetic personas that have no DB row.)
        if not current_app.testing:
            logger.info("refresh_user_session: user %s no longer exists; clearing session", user_email)
            session.clear()
        return

    # Password reset / change, "log out all devices" and admin force-logout bump
    # session_version: older sessions end here.
    db_version = int(user_data.get('session_version') or 0)
    try:
        session_version = int(session['user'].get('session_version'))
    except (TypeError, ValueError):
        session_version = None
    if session_version != db_version:
        logger.info("refresh_user_session: session of %s revoked (session_version changed)", user_email)
        session.clear()
        return _session_revoked_response()

    g.current_user = user_data

    # Sliding idle window: remember activity, at most once a minute.
    last_seen = session['user'].get('last_seen')
    if not isinstance(last_seen, (int, float)) or now - last_seen >= LAST_SEEN_WRITE_INTERVAL_S:
        session['user']['last_seen'] = int(now)
        session.modified = True

    # Sync the forced-password-change flag (set when an admin creates/resets a password)
    must_change = bool(user_data.get('must_change_password')) and bool(user_data.get('has_password'))
    if session['user'].get('must_change_password') != must_change:
        session['user']['must_change_password'] = must_change
        session.modified = True
    # Only sessions that signed in with the temporary password are held back;
    # a Google sign-in of the same account is already strongly authenticated.
    if must_change and session['user'].get('auth_method') == 'password':
        blocked = _enforce_password_change()
        if blocked is not None:
            return blocked

    # Sync is_admin
    current_is_admin = user_data.get('is_admin', False)
    if session['user'].get('is_admin') != current_is_admin:
        session['user']['is_admin'] = current_is_admin
        session.modified = True

    # Sync role (used by is_guest())
    current_role = user_data.get('role', 'guest')
    if session['user'].get('role') != current_role:
        session['user']['role'] = current_role
        session.modified = True

    # Sync groups / GREATLab membership
    user_groups = list(user_data.get('groups', []))
    if session['user'].get('groups') != user_groups:
        session['user']['groups'] = user_groups
        session.modified = True
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


# Endpoints still reachable while a password change is pending.
_PASSWORD_CHANGE_ALLOWED = {'auth.change_password', 'auth.logout', 'static', 'basic.login'}


def _enforce_password_change():
    """Until an admin-issued password is replaced, only the change-password page works."""
    endpoint = request.endpoint or ''
    if endpoint in _PASSWORD_CHANGE_ALLOWED or endpoint.endswith('.static'):
        return None
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({'error': 'Password change required'}), 403
    return redirect(url_for('auth.change_password'))


def _session_revoked_response():
    if _wants_json():
        return jsonify({'error': 'Session expired, please log in again'}), 401
    flash('Your session has ended (password changed or signed out on all devices). '
          'Please log in again.', 'info')
    return redirect(url_for('basic.login'))


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


def session_unverified() -> bool:
    """True when this request's session could not be checked against the DB."""
    return bool(g.get('session_unverified'))


def is_admin() -> bool:
    """Admin check for authorization; False (fail closed) while the DB is down."""
    if session_unverified():
        return False
    u = session.get('user')
    return bool(u and u.get('is_admin', False))


def _unverified_response(json_body: bool = True):
    msg = 'Service temporarily unavailable (cannot verify your session). Please try again shortly.'
    if json_body:
        return jsonify({'error': msg}), 503
    resp = make_response(msg, 503)
    resp.mimetype = 'text/plain'
    return resp


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
            if session_unverified():
                return _unverified_response()
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
        if session_unverified() and (session.get('user') or {}).get('is_admin'):
            return _unverified_response(json_body=False)
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
