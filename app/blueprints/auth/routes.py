"""
Authentication routes (Google OAuth, login, logout)
"""
import hmac
import logging
import re
from flask import session, flash, redirect, url_for, request, jsonify, render_template

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from app.db.auth import user_exists, get_users, get_user, save_user, update_user, create_group_request, group_exists, user_in_group, remove_user_from_group, get_user_group_requests, request_api_key, get_setting, get_invitations, update_invitation, get_password_hash, get_login_email, set_password_hash
from app.config import config
from app.core import rate_limit
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
    user_groups = []
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')

        if user_info:
            user_email = user_info.get('email')
            
            is_admin = False
            role = 'guest'
            is_great_lab_member = False
            existing_user_data = None
            invitation = None
            
            if user_exists(user_email):
                users = get_users()
                existing_user_data = users[user_email]
                is_admin = existing_user_data.get('is_admin', False)
                role = existing_user_data.get('role', 'guest')
                user_groups = existing_user_data.get('groups', [])
                is_great_lab_member = 'GREAT_Lab' in user_groups or is_admin
            else:
                user_groups = []
                invitation = None
                if user_email == config.ADMIN_EMAIL:
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
            
            display_name = user_info.get('name')
            display_picture = user_info.get('picture')
            
            if existing_user_data:
                display_name = existing_user_data.get('name') or user_info.get('name')
                display_picture = existing_user_data.get('picture') or user_info.get('picture')
                
            # Prevent huge base64 strings in session cookie (limit 4KB)
            session_picture = display_picture
            if session_picture and session_picture.startswith('data:image'):
                session_picture = user_info.get('picture') # fallback to google picture for cookie
            
            session.permanent = True
            session['user'] = {
                'email': user_email,
                'name': display_name,
                'picture': session_picture,
                'is_admin': is_admin,
                'role': role,
                'is_great_lab_member': is_great_lab_member,
                'groups': user_groups,
                'api_key': existing_user_data.get('api_key') if existing_user_data else None
            }

            flash_message = 'Welcome Administrator!' if is_admin else f'Welcome {display_name}!'
            flash(flash_message, 'success')
            
            if user_exists(user_email):
                update_user(
                    user_email,
                    name=existing_user_data.get('name') or user_info.get('name'),
                    picture=existing_user_data.get('picture') or user_info.get('picture'),
                    last_login=datetime.now().isoformat()
                )
            else:
                save_user(
                    email=user_email,
                    name=user_info.get('name'),
                    picture_url=user_info.get('picture'),
                    is_admin=is_admin,
                    role=role,
                )
                if invitation is not None:
                    update_invitation(invitation['token'], status='accepted',
                                      accepted_at=datetime.now(timezone.utc))
            
            next_url = session.pop('next_url', None)
            if next_url:
                return redirect(next_url)
            
            return redirect(url_for('basic.home'))
        else:
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('basic.login'))
            
    except Exception as e:
        logger.error('Login error: %s', e)
        flash('Login failed, please try again.', 'error')
        return redirect(url_for('basic.login'))

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('basic.home'))


# Per-IP failed-login throttle for the local admin login (shared across workers).
_ADMIN_LOGIN_MAX_FAILURES = 5
_ADMIN_LOGIN_WINDOW_S = 5 * 60


def _admin_login_blocked(ip: str) -> bool:
    return rate_limit.count(f'admin_login_fail:{ip}', _ADMIN_LOGIN_WINDOW_S) >= _ADMIN_LOGIN_MAX_FAILURES


def _admin_login_record_failure(ip: str) -> None:
    rate_limit.hit(f'admin_login_fail:{ip}')


@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    client_ip = request.remote_addr or 'unknown'

    expected_username = config.ADMIN_USERNAME or ''
    expected_password = config.ADMIN_PASSWORD or ''
    admin_email = config.ADMIN_LOCAL_EMAIL or ''

    # Local admin login is disabled unless fully configured.
    if not expected_username or not expected_password or not admin_email:
        flash('Local admin login is not configured.', 'error')
        return redirect(url_for('basic.login'))

    if _admin_login_blocked(client_ip):
        logger.warning('Admin login throttled for %s', client_ip)
        flash('Too many failed attempts. Please try again later.', 'error')
        return redirect(url_for('basic.login'))

    user_ok = hmac.compare_digest(username.lower().encode(), expected_username.lower().encode())
    pass_ok = hmac.compare_digest(password.encode(), expected_password.encode())
    if not (user_ok and pass_ok):
        _admin_login_record_failure(client_ip)
        logger.warning('Failed admin login from %s', client_ip)
        flash('Invalid admin credentials.', 'error')
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
        flash('Admin account not found in the database.', 'error')
        return redirect(url_for('basic.login'))

    rate_limit.clear(f'admin_login_fail:{client_ip}')

    next_url = _safe_next(session.get('next_url'))
    _start_user_session(admin_data)   # fresh session on privilege change
    session['user']['auth_method'] = 'local_admin'
    session['user']['must_change_password'] = False
    update_user(admin_email, last_login=datetime.now().isoformat())

    flash('Welcome Administrator!' if session['user']['is_admin'] else f"Welcome {session['user']['name']}!", 'success')
    return redirect(next_url or url_for('basic.home'))


# ---------------------------------------------------------------------------
# Password login for admin-created accounts (no self-registration)
# ---------------------------------------------------------------------------
_PW_IP_MAX_FAILURES = 10          # per client IP
_PW_ACCOUNT_MAX_FAILURES = 5      # per account (slows targeted guessing)
_PW_WINDOW_S = 15 * 60
_PW_GENERIC_ERROR = 'Invalid email or password.'


def _safe_next(next_url):
    """Only same-site relative paths are allowed as post-login redirects."""
    if next_url and next_url.startswith('/') and not next_url.startswith('//') and '\\' not in next_url:
        return next_url
    return None


def _start_user_session(user_data: dict) -> None:
    """Replace the session with a fresh one for *user_data* (a get_user() dict)."""
    session.clear()   # new session on login: no fixation, no leftovers
    session.permanent = True
    user_groups = user_data.get('groups', [])
    is_admin = bool(user_data.get('is_admin', False))
    picture = user_data.get('picture')
    if picture and picture.startswith('data:image'):
        picture = None   # keep base64 out of the 4 KB cookie
    session['user'] = {
        'email': user_data['email'],
        'name': user_data.get('name') or user_data['email'].split('@')[0],
        'picture': picture,
        'is_admin': is_admin,
        'role': user_data.get('role', 'guest'),
        'is_great_lab_member': 'GREAT_Lab' in user_groups or is_admin,
        'groups': user_groups,
        'api_key': user_data.get('api_key'),
        'auth_method': 'password',
        'session_version': int(user_data.get('session_version') or 0),
        'must_change_password': bool(user_data.get('must_change_password')),
    }


@auth_bp.route('/login/password', methods=['POST'])
def password_login():
    email = (request.form.get('email') or '').strip()[:254]
    password = request.form.get('password') or ''
    client_ip = request.remote_addr or 'unknown'
    ip_key = f'pw_login_fail_ip:{client_ip}'
    acct_key = f'pw_login_fail_acct:{email.lower()}'

    if (rate_limit.count(ip_key, _PW_WINDOW_S) >= _PW_IP_MAX_FAILURES
            or (email and rate_limit.count(acct_key, _PW_WINDOW_S) >= _PW_ACCOUNT_MAX_FAILURES)):
        logger.warning('Password login throttled (ip=%s)', client_ip)
        flash('Too many failed attempts. Please try again in 15 minutes.', 'error')
        return redirect(url_for('basic.login'))

    try:
        stored_hash = get_password_hash(email) if email else None
    except Exception as exc:
        logger.error('Password login: lookup failed: %s', exc)
        flash('Login is temporarily unavailable. Please try again later.', 'error')
        return redirect(url_for('basic.login'))

    # verify_password always does one hash check, so unknown accounts and
    # accounts without a password fail in the same time as a wrong password.
    if not verify_password(stored_hash, password):
        rate_limit.hit(ip_key)
        if email:
            rate_limit.hit(acct_key)
        logger.warning('Failed password login from %s', client_ip)
        flash(_PW_GENERIC_ERROR, 'error')
        return redirect(url_for('basic.login'))

    canonical_email = get_login_email(email)
    user_data = get_user(canonical_email) if canonical_email else None
    if not user_data:
        flash(_PW_GENERIC_ERROR, 'error')
        return redirect(url_for('basic.login'))

    rate_limit.clear(acct_key)
    next_url = _safe_next(session.get('next_url'))
    _start_user_session(user_data)
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
    if request.method == 'GET':
        return render_template('change_password.html', forced=forced,
                               min_length=PASSWORD_MIN_LENGTH, current_path='/account/password')

    current = request.form.get('current_password') or ''
    new = request.form.get('new_password') or ''
    confirm = request.form.get('confirm_password') or ''
    fail_key = f'pw_change_fail:{email.lower()}'

    if rate_limit.count(fail_key, _PW_WINDOW_S) >= _PW_ACCOUNT_MAX_FAILURES:
        flash('Too many failed attempts. Please try again in 15 minutes.', 'error')
        return redirect(url_for('auth.change_password'))
    if not verify_password(stored_hash, current):
        rate_limit.hit(fail_key)
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('auth.change_password'))
    if new != confirm:
        flash('The new passwords do not match.', 'error')
        return redirect(url_for('auth.change_password'))
    problem = password_problem(new, email)
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
