"""
Authentication routes (Google OAuth, login, logout)
"""
import hmac
import logging
import re
from flask import g, session, flash, redirect, url_for, request, jsonify, render_template

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from app.db.auth import user_exists, get_users, get_user, save_user, update_user, create_group_request, group_exists, user_in_group, remove_user_from_group, get_user_group_requests, request_api_key, get_setting, get_invitations, update_invitation, get_password_hash, get_login_account, get_login_email, set_password_hash, set_google_sub, bump_session_version, generate_api_key_for_user, is_placeholder_email
from app.config import config
from app.core import rate_limit
from app.core.auth import start_user_session
from app.core.passwords import MIN_LENGTH as PASSWORD_MIN_LENGTH, password_problem, hash_password, verify_password

from flask import Blueprint
auth_bp = Blueprint('auth', __name__, template_folder='templates', static_folder='static')
from app.extensions import google  # Google OIDC client (registered in app.extensions)


@auth_bp.route('/auth/google')
def google_login():
    # Build the callback URL from the configured base URL rather than the
    # request's Host header, which is attacker-controlled (host header injection).
    redirect_uri = config.APP_BASE_URL.rstrip('/') + url_for('auth.google_callback')
    return google.authorize_redirect(redirect_uri)

def _pending_invitation_for(email: str) -> dict | None:
    """Return the pending invitation addressed to *email* (case-insensitive), if any."""
    if not email:
        return None
    try:
        for inv in get_invitations('pending'):
            if (inv.get('email') or '').strip().lower() == email.strip().lower():
                return inv
    except Exception as exc:
        logger.warning('Invitation lookup failed for %s: %s', email, exc)
    return None


@auth_bp.route('/auth/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('basic.login'))

        # Only addresses Google has verified can be trusted as an identity.
        if user_info.get('email_verified') is not True:
            logger.warning('Google login refused: email not verified (%s)', user_info.get('email'))
            flash('Your Google account email is not verified.', 'error')
            return redirect(url_for('basic.login'))
        user_email = (user_info.get('email') or '').strip().lower()
        google_sub = str(user_info.get('sub') or '').strip()
        if not user_email or not google_sub or is_placeholder_email(user_email):
            logger.warning('Google login refused: missing/invalid email or sub (%r)', user_email)
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('basic.login'))

        # Stored emails may differ in case from Google's lowercase one.
        canonical_email = get_login_email(user_email)
        existing_user_data = get_user(canonical_email) if canonical_email else None
        invitation = None

        if existing_user_data:
            user_email = existing_user_data['email']
            bound_sub = existing_user_data.get('google_sub')
            if bound_sub and bound_sub != google_sub:
                logger.warning('Google login refused for %s: Google account id does not match '
                               'the one bound to this user', user_email)
                flash('This Google account cannot sign in to that user.', 'error')
                return redirect(url_for('basic.login'))
            update_user(
                user_email,
                name=existing_user_data.get('name') or user_info.get('name'),
                picture=existing_user_data.get('picture') or user_info.get('picture'),
                last_login=datetime.now().isoformat()
            )
        else:
            is_admin = False
            role = 'guest'
            # ADMIN_EMAIL bootstrap (email_verified is required above).
            if config.ADMIN_EMAIL and user_email == config.ADMIN_EMAIL.strip().lower():
                is_admin = True
                role = 'admin'
            elif get_setting('open_registration', 'true') != 'true':
                # Closed registration: only invited addresses may create an account.
                invitation = _pending_invitation_for(user_email)
                if invitation is None:
                    logger.info('Sign-up refused for %s: registration is closed', user_email)
                    flash('Registration is currently closed. Please ask an administrator for an invitation.', 'error')
                    return redirect(url_for('basic.login'))
                is_admin = bool(invitation.get('is_admin'))
                role = 'admin' if is_admin else (invitation.get('role') or 'user')
            if not save_user(
                email=user_email,
                name=user_info.get('name'),
                picture_url=user_info.get('picture'),
                is_admin=is_admin,
                role=role,
            ):
                flash('Login failed, please try again.', 'error')
                return redirect(url_for('basic.login'))
            if invitation is not None:
                update_invitation(invitation['token'], status='accepted',
                                  accepted_at=datetime.now(timezone.utc))

        if not (existing_user_data or {}).get('google_sub'):
            set_google_sub(user_email, google_sub)

        user_data = get_user(user_email)
        if not user_data:
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('basic.login'))

        next_url = _safe_next(session.get('next_url'))
        _start_user_session(user_data, auth_method='google')
        # A Google sign-in is strongly authenticated; a pending forced password
        # change only applies to sessions that used the temporary password.
        logger.info('Google login: %s from %s', user_email, request.remote_addr)

        name = session['user']['name']
        flash('Welcome Administrator!' if session['user']['is_admin'] else f'Welcome {name}!', 'success')
        return redirect(next_url or url_for('basic.home'))

    except Exception:
        logger.exception('Google login error')
        flash('Login failed, please try again.', 'error')
        return redirect(url_for('basic.login'))

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('basic.home'))


@auth_bp.route('/account/logout-all', methods=['POST'])
def logout_all_devices():
    """End every session of the current account (all browsers/devices)."""
    if 'user' not in session:
        return redirect(url_for('basic.login'))
    email = session['user']['email']
    new_version = bump_session_version(email)
    if new_version is None:
        flash('Could not sign out other devices. Please try again.', 'error')
        return redirect(url_for('basic.profile'))
    logger.info('audit action=logout_all actor=%s target=%s ip=%s', email, email, request.remote_addr)
    session.clear()
    flash('You have been logged out on all devices.', 'info')
    return redirect(url_for('basic.login'))


# ---------------------------------------------------------------------------
# Local admin login from kinder.env (ADMIN_USERNAME / ADMIN_PASSWORD /
# ADMIN_LOCAL_EMAIL). Disabled unless all three are set. The login page no longer
# shows a separate form: /login/password falls back to it when the username is
# ADMIN_USERNAME and no DB account matches. /admin-login is kept for old clients.
# ---------------------------------------------------------------------------
_ADMIN_LOGIN_MAX_FAILURES = 5           # per client IP
_ADMIN_LOGIN_WINDOW_S = 5 * 60
_ADMIN_LOGIN_USER_MAX_FAILURES = 10     # per username, any IP
_ADMIN_LOGIN_USER_WINDOW_S = 60 * 60


def _env_admin_configured() -> bool:
    return bool(config.ADMIN_USERNAME and config.ADMIN_PASSWORD and config.ADMIN_LOCAL_EMAIL)


def _env_admin_login(username: str, password: str, client_ip: str):
    """Check the kinder.env admin credentials and start the session (a response)."""
    expected_username = config.ADMIN_USERNAME or ''
    expected_password = config.ADMIN_PASSWORD or ''
    admin_email = config.ADMIN_LOCAL_EMAIL or ''
    ip_key = f'admin_login_fail:{client_ip}'
    user_key = f'admin_login_fail_user:{username.lower()[:64]}'

    if (rate_limit.count(ip_key, _ADMIN_LOGIN_WINDOW_S) >= _ADMIN_LOGIN_MAX_FAILURES
            or rate_limit.count(user_key, _ADMIN_LOGIN_USER_WINDOW_S) >= _ADMIN_LOGIN_USER_MAX_FAILURES):
        logger.warning('Local admin login throttled (ip=%s)', client_ip)
        flash('Too many failed attempts. Please try again later.', 'error')
        return redirect(url_for('basic.login'))

    user_ok = hmac.compare_digest(username.lower().encode(), expected_username.lower().encode())
    pass_ok = hmac.compare_digest(password.encode(), expected_password.encode())
    if not (user_ok and pass_ok):
        rate_limit.hit(ip_key)
        rate_limit.hit(user_key)
        logger.warning('Failed local admin login from %s', client_ip)
        flash(_PW_GENERIC_ERROR, 'error')
        return redirect(url_for('basic.login'))

    try:
        admin_data = get_user(admin_email)
    except Exception as exc:
        logger.error('Admin login: user lookup failed: %s', exc)
        admin_data = None
    # The admin session is tied to a real auth.users row (ADMIN_LOCAL_EMAIL) — its
    # role comes from the DB, never hard-coded here.
    if not admin_data:
        logger.error('Admin login: no auth.users row for ADMIN_LOCAL_EMAIL %s', admin_email)
        flash('Login is temporarily unavailable. Please try again later.', 'error')
        return redirect(url_for('basic.login'))

    rate_limit.clear(ip_key)

    next_url = _safe_next(session.get('next_url'))
    _start_user_session(admin_data, auth_method='local_admin')   # fresh session on privilege change
    session['user']['must_change_password'] = False
    update_user(admin_email, last_login=datetime.now().isoformat())
    logger.info('Local admin login: %s from %s', admin_email, client_ip)

    flash('Welcome Administrator!' if session['user']['is_admin'] else f"Welcome {session['user']['name']}!", 'success')
    return redirect(next_url or url_for('basic.home'))


@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    username = request.form.get('username', '').strip()[:128]
    password = request.form.get('password', '')
    if not _env_admin_configured():
        flash('Local admin login is not configured.', 'error')
        return redirect(url_for('basic.login'))
    return _env_admin_login(username, password, request.remote_addr or 'unknown')


# ---------------------------------------------------------------------------
# Direct login (username or email + password) for admin-created accounts
# (no self-registration)
# ---------------------------------------------------------------------------
_PW_IP_MAX_FAILURES = 10            # per client IP
_PW_ACCOUNT_IP_MAX_FAILURES = 5     # per account + client IP (slows targeted guessing)
_PW_ACCOUNT_MAX_FAILURES = 50       # per account from all IPs (distributed guessing)
_PW_WINDOW_S = 15 * 60
_PW_CHANGE_MAX_FAILURES = 5
_PW_GENERIC_ERROR = 'Invalid username or password.'


def _safe_next(next_url):
    """Only same-site relative paths are allowed as post-login redirects."""
    if (isinstance(next_url, str) and next_url.startswith('/') and not next_url.startswith('//')
            and '\\' not in next_url and not any(c in next_url for c in '\r\n\t')):
        return next_url
    return None


def _start_user_session(user_data: dict, auth_method: str = 'password') -> None:
    """Replace the session with a fresh one for *user_data* (a get_user() dict)."""
    start_user_session(user_data, auth_method)


@auth_bp.route('/login/password', methods=['POST'])
def password_login():
    # 'username' accepts a username or an email; 'email' is the old field name.
    identifier = (request.form.get('username') or request.form.get('email') or '').strip()[:254]
    password = request.form.get('password') or ''
    client_ip = request.remote_addr or 'unknown'
    ident_key = identifier.lower()
    ip_key = f'pw_login_fail_ip:{client_ip}'
    acct_ip_key = f'pw_login_fail_acct:{ident_key}:{client_ip}'
    acct_key = f'pw_login_fail_acct_all:{ident_key}'

    if (rate_limit.count(ip_key, _PW_WINDOW_S) >= _PW_IP_MAX_FAILURES
            or (identifier and (
                rate_limit.count(acct_ip_key, _PW_WINDOW_S) >= _PW_ACCOUNT_IP_MAX_FAILURES
                or rate_limit.count(acct_key, _PW_WINDOW_S) >= _PW_ACCOUNT_MAX_FAILURES))):
        logger.warning('Password login throttled (ip=%s)', client_ip)
        flash('Too many failed attempts. Please try again in 15 minutes.', 'error')
        return redirect(url_for('basic.login'))

    try:
        account = get_login_account(identifier) if identifier else None
    except Exception as exc:
        logger.error('Password login: lookup failed: %s', exc)
        flash('Login is temporarily unavailable. Please try again later.', 'error')
        return redirect(url_for('basic.login'))

    # No DB account under that name: the kinder.env local admin (if configured).
    if (account is None and _env_admin_configured()
            and hmac.compare_digest(ident_key.encode(), (config.ADMIN_USERNAME or '').lower().encode())):
        return _env_admin_login(identifier, password, client_ip)

    canonical_email, stored_hash = account if account else (None, None)
    # verify_password always does one hash check, so unknown accounts and
    # accounts without a password fail in the same time as a wrong password.
    if not verify_password(stored_hash, password):
        rate_limit.hit(ip_key)
        if identifier:
            rate_limit.hit(acct_ip_key)
            rate_limit.hit(acct_key)
        logger.warning('Failed password login from %s', client_ip)
        flash(_PW_GENERIC_ERROR, 'error')
        return redirect(url_for('basic.login'))

    user_data = get_user(canonical_email) if canonical_email else None
    if not user_data:
        flash(_PW_GENERIC_ERROR, 'error')
        return redirect(url_for('basic.login'))

    rate_limit.clear(acct_ip_key)
    next_url = _safe_next(session.get('next_url'))
    _start_user_session(user_data, auth_method='password')
    update_user(canonical_email, last_login=datetime.now().isoformat())
    logger.info('Password login: %s from %s', canonical_email, client_ip)

    if user_data.get('must_change_password'):
        flash('Please set a new password before continuing.', 'warning')
        return redirect(url_for('auth.change_password'))
    flash(f"Welcome {session['user']['name']}!", 'success')
    return redirect(next_url or url_for('basic.home'))


@auth_bp.route('/account/password', methods=['GET', 'POST'])
def change_password():
    """Change your own password (password accounts only). Requires the current one."""
    if 'user' not in session:
        return redirect(url_for('basic.login'))
    email = session['user']['email']
    try:
        stored_hash = get_password_hash(email)
    except Exception as exc:
        logger.error('change_password lookup failed: %s', exc)
        flash('Password change is temporarily unavailable.', 'error')
        return redirect(url_for('basic.profile'))
    if not stored_hash:
        flash('Your account signs in with Google and has no password.', 'info')
        return redirect(url_for('basic.profile'))

    forced = bool(session['user'].get('must_change_password'))
    account = getattr(g, 'current_user', None) or {}
    username = account.get('username') if account.get('email') == email else None
    if request.method == 'GET':
        return render_template('change_password.html', forced=forced,
                               username=username,
                               account_email=None if is_placeholder_email(email) else email,
                               min_length=PASSWORD_MIN_LENGTH, current_path='/account/password')

    current = request.form.get('current_password') or ''
    new = request.form.get('new_password') or ''
    confirm = request.form.get('confirm_password') or ''
    fail_key = f'pw_change_fail:{email.lower()}'

    if rate_limit.count(fail_key, _PW_WINDOW_S) >= _PW_CHANGE_MAX_FAILURES:
        flash('Too many failed attempts. Please try again in 15 minutes.', 'error')
        return redirect(url_for('auth.change_password'))
    if not verify_password(stored_hash, current):
        rate_limit.hit(fail_key)
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('auth.change_password'))
    if new != confirm:
        flash('The new passwords do not match.', 'error')
        return redirect(url_for('auth.change_password'))
    problem = password_problem(new, email, username or '')
    if problem:
        flash(problem, 'error')
        return redirect(url_for('auth.change_password'))
    if verify_password(stored_hash, new):
        flash('The new password must be different from the current one.', 'error')
        return redirect(url_for('auth.change_password'))

    new_version = set_password_hash(email, hash_password(new), must_change=False)
    if new_version is None:
        flash('Could not update the password. Please try again.', 'error')
        return redirect(url_for('auth.change_password'))
    rate_limit.clear(fail_key)
    # Other sessions of this account are now invalid; keep this one.
    session['user']['session_version'] = new_version
    session['user']['must_change_password'] = False
    session.modified = True
    logger.info('Password changed by %s', email)
    flash('Password updated.', 'success')
    return redirect(url_for('basic.profile'))


_PROFILE_NAME_MAX = 80
_DATA_IMAGE_RE = re.compile(r'^data:image/(png|jpe?g);base64,[A-Za-z0-9+/=\s]+$')


def _clean_profile_name(name: str) -> str:
    return re.sub(r'[<>]', '', name or '').strip()[:_PROFILE_NAME_MAX].strip()


def _valid_profile_picture(picture: str) -> bool:
    """Empty, an https:// URL, or a base64 PNG/JPEG data URI (avatar upload)."""
    if not picture:
        return True
    if picture.startswith('https://'):
        return not any(c in picture for c in '<>"\' \t\r\n')
    return bool(_DATA_IMAGE_RE.match(picture))


@auth_bp.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user' not in session:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Not logged in'}), 401
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            name = str(data.get('name') or '').strip()
            picture = str(data.get('picture') or '').strip()
        else:
            name = request.form.get('name', '').strip()
            picture = request.form.get('picture', '').strip()

        name = _clean_profile_name(name)
        if not _valid_profile_picture(picture):
            if request.is_json:
                return jsonify({'success': False, 'error': 'Picture must be an https:// URL or a PNG/JPEG image.'}), 400
            flash('Picture must be an https:// URL or a PNG/JPEG image.', 'error')
            return redirect(url_for('basic.profile'))
        
        if not name:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Name cannot be empty.'}), 400
            flash('Name cannot be empty.', 'error')
            return redirect(url_for('basic.profile'))
        
        if user_exists(user_email):
            users = get_users()
            current_data = users[user_email]
            
            update_user(
                user_email,
                name=name,
                picture=picture or current_data.get('picture', ''),
            )
            
            session['user']['name'] = name
            # Never store large base64 strings in the session cookie (limit 4KB)
            if picture and not picture.startswith('data:image'):
                session['user']['picture'] = picture
            
            # Failsafe: if a base64 string accidentally got stuck in the session, clear it
            if (session['user'].get('picture') or '').startswith('data:image'):
                session['user']['picture'] = ''
            session.modified = True
            
            if request.is_json:
                return jsonify({'success': True, 'message': 'Profile updated successfully'})
            flash('Profile updated successfully!', 'success')
        else:
            if request.is_json:
                return jsonify({'success': False, 'error': 'User not found.'}), 404
            flash('User not found.', 'error')
            
    except Exception as e:
        logger.error('Profile update error: %s', e)
        if request.is_json:
            return jsonify({'success': False, 'error': 'Error updating profile.'}), 500
        flash('Error updating profile.', 'error')
    
    return redirect(url_for('basic.profile'))



@auth_bp.route('/api/profile/join_group', methods=['POST'])
def profile_join_group():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    group_name = (data or {}).get('group_name', '').strip()
    if not group_name:
        return jsonify({'error': 'Group name required'}), 400
    if not group_exists(group_name):
        return jsonify({'error': 'Group does not exist'}), 404
    user_email = session['user']['email']
    if user_in_group(user_email, group_name):
        return jsonify({'error': 'Already a member of this group'}), 400
    requests_map = {r['group_name']: r.get('status') for r in get_user_group_requests(user_email)}
    if requests_map.get(group_name) == 'request':
        return jsonify({'error': 'Request already pending'}), 400
    if create_group_request(user_email, group_name):
        return jsonify({'success': True, 'message': f'Request to join "{group_name}" sent. Admin will review.'})
    return jsonify({'error': 'Failed to submit request'}), 500


@auth_bp.route('/api/profile/leave_group', methods=['POST'])
def profile_leave_group():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    group_name = (data or {}).get('group_name', '').strip()
    if not group_name:
        return jsonify({'error': 'Group name required'}), 400
    user_email = session['user']['email']
    if not user_in_group(user_email, group_name):
        return jsonify({'error': 'Not a member of this group'}), 400
    if remove_user_from_group(user_email, group_name):
        return jsonify({'success': True, 'message': f'Left group "{group_name}"'})
    return jsonify({'error': 'Failed to leave group'}), 500


@auth_bp.route('/api/profile/request_api_key', methods=['POST'])
def profile_request_api_key():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    role = session['user'].get('role', 'guest')
    if role == 'guest':
        return jsonify({'error': 'Guests cannot request an API key'}), 403
    user_email = session['user']['email']
    if request_api_key(user_email):
        return jsonify({'success': True, 'message': 'Request submitted. An admin will review it.'})
    return jsonify({'error': 'Failed to submit request'}), 500


_API_KEY_REGEN_MAX = 3
_API_KEY_REGEN_WINDOW_S = 60 * 60


@auth_bp.route('/api/profile/regenerate_api_key', methods=['POST'])
def profile_regenerate_api_key():
    """Replace your own (already approved) API key. The new key is returned once."""
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'error': 'Guests cannot have an API key'}), 403
    user_email = session['user']['email']
    try:
        user_data = get_user(user_email)
    except Exception as exc:
        logger.error('regenerate_api_key lookup failed: %s', exc)
        return jsonify({'error': 'Service temporarily unavailable'}), 503
    if not user_data or not user_data.get('has_api_key'):
        return jsonify({'error': 'You do not have an API key yet. Request one first.'}), 400
    if not rate_limit.allow(f'api_key_regen:{user_email.lower()}', _API_KEY_REGEN_MAX, _API_KEY_REGEN_WINDOW_S):
        return jsonify({'error': 'Too many key regenerations. Please try again later.'}), 429
    new_key = generate_api_key_for_user(user_email)
    if not new_key:
        return jsonify({'error': 'Failed to generate a new key'}), 500
    logger.info('audit action=api_key_regenerate actor=%s target=%s ip=%s hint=%s',
                user_email, user_email, request.remote_addr, new_key[-4:])
    return jsonify({
        'success': True,
        'message': 'New API key generated. Your previous key no longer works.',
        'api_key': new_key,
        'api_key_hint': new_key[-4:],
    })
