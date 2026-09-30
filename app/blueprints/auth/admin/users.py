"""Admin panel actions — users (split from admin_routes.py)."""
import logging
import re

from flask import session, request, jsonify
from app.core.passwords import hash_password, password_problem
from app.db.auth import (
    get_login_email,
    get_user,
    save_user,
    set_password_hash,
    get_users,
    update_user,
    delete_user,
    user_exists,
    get_groups,
    group_exists,
    add_user_to_group,
    remove_user_from_group,
    user_in_group,
    update_group_request_status,
    get_group_request,
    bump_session_version,
    is_placeholder_email,
    placeholder_email_for,
    set_username,
    username_taken,
    valid_username,
)
from . import admin_bp
from .helpers import audit, privileged_target_denied, update_user_session_groups
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r'^[^@\s<>"\']+@[^@\s<>"\']+\.[^@\s<>"\']+$')


# ===============================================================================
# USER MANAGEMENT (Direct Add)
# ===============================================================================
@admin_bp.route('/admin/add-user', methods=['POST'])
@admin_required
def add_user():
    """Create an account. Only admins reach this route; there is no public sign-up.

    Either (a) a direct-login account: ``username`` + ``password`` (``email``
    optional — a ``<username>@users.invalid`` placeholder is stored without one),
    or (b) a Google-only account: ``email`` alone (no username / password). For
    (b) an existing email keeps the old behaviour: its role is updated."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    username = str(data.get('username') or '').strip()
    role = data.get('role', 'user')
    name = str(data.get('name') or '').strip()[:80]
    password = data.get('password') or ''
    must_change = bool(data.get('must_change_password', True))

    if role not in ('guest', 'user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400
    if email and (not _EMAIL_RE.match(email) or len(email) > 254):
        return jsonify({'error': 'Invalid email address'}), 400
    if email and is_placeholder_email(email):
        return jsonify({'error': 'This email domain is reserved'}), 400
    if password and not username:
        return jsonify({'error': 'A username is required for a direct-login account'}), 400
    if username and not valid_username(username):
        return jsonify({'error': 'Username must be 3–32 characters: letters, digits, . _ -'}), 400
    if username and not password and not email:
        return jsonify({'error': 'A password is required for a direct-login account'}), 400
    if not username and not email:
        return jsonify({'error': 'Enter a username and password, or an email for a Google-only account'}), 400
    if password:
        problem = password_problem(password, email, username)
        if problem:
            return jsonify({'error': problem}), 400

    existing_email = get_login_email(email) if email else None
    if username:
        if username_taken(username):
            return jsonify({'error': 'This username is already taken'}), 409
        if existing_email:
            return jsonify({'error': 'A user with this email already exists. Use "Set password" on their row instead.'}), 409
        if not email:
            email = placeholder_email_for(username)
            if get_login_email(email):
                return jsonify({'error': 'This username is already taken'}), 409
    elif existing_email:
        if existing_email == session['user']['email']:
            return jsonify({'error': 'Cannot change your own role'}), 400
        denied = privileged_target_denied(existing_email, "change another admin's role")
        if denied:
            return denied
        old_role = (get_user(existing_email) or {}).get('role')
        update_user(existing_email, role=role)
        audit('update_role', existing_email, f'{old_role}->{role} via=add_user')
        return jsonify({'success': True, 'message': 'User already existed, role updated.'})

    default_name = username or email.split('@')[0]
    name = re.sub(r'[<>]', '', name).strip() or default_name

    if not save_user(email=email, name=name, picture_url='', is_admin=(role == 'admin'), role=role,
                     username=username or None):
        return jsonify({'error': 'Failed to add user to database'}), 500
    if password:
        if set_password_hash(email, hash_password(password), must_change=must_change) is None:
            return jsonify({'error': 'User created, but setting the password failed'}), 500
    audit('add_user', email, f'username={username or "-"} role={role} direct_login={bool(password)}')
    return jsonify({'success': True, 'message': 'User added successfully'})


@admin_bp.route('/admin/set-password', methods=['POST'])
@admin_required
def admin_set_password():
    """Set or reset a user's password; logs out all of that user's sessions.

    A user without a username must be given one here (``username``): direct login
    signs in by username."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    new_username = str(data.get('username') or '').strip()
    password = data.get('password') or ''
    must_change = bool(data.get('must_change_password', True))

    target = get_login_email(email) if email else None
    if not target:
        return jsonify({'error': 'User not found'}), 404
    denied = _password_management_denied(target)
    if denied:
        return denied
    target_user = get_user(target) or {}
    username = target_user.get('username')
    if not username:
        if not valid_username(new_username):
            return jsonify({'error': 'Username must be 3–32 characters: letters, digits, . _ -'}), 400
        if username_taken(new_username, exclude_email=target):
            return jsonify({'error': 'This username is already taken'}), 409
    problem = password_problem(password, target, username or new_username)
    if problem:
        return jsonify({'error': problem}), 400
    if not username:
        if not set_username(target, new_username):
            return jsonify({'error': 'Could not set the username (maybe already taken)'}), 409
        audit('set_username', target, f'username={new_username}')

    new_version = set_password_hash(target, hash_password(password), must_change=must_change)
    if new_version is None:
        return jsonify({'error': 'Failed to set password'}), 500
    _keep_own_session(target, new_version, must_change)
    audit('set_password', target, f'must_change={must_change}')
    return jsonify({'success': True, 'message': f'Password set for {target}. Their other sessions were logged out.'})


@admin_bp.route('/admin/clear-password', methods=['POST'])
@admin_required
def admin_clear_password():
    """Disable password login for a user (they can still use Google)."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    target = get_login_email(email) if email else None
    if not target:
        return jsonify({'error': 'User not found'}), 404
    denied = _password_management_denied(target)
    if denied:
        return denied
    new_version = set_password_hash(target, None)
    if new_version is None:
        return jsonify({'error': 'Failed to remove password'}), 500
    _keep_own_session(target, new_version, False)
    audit('clear_password', target)
    return jsonify({'success': True, 'message': f'Password login disabled for {target}.'})


def _password_management_denied(target_email):
    """Setting another admin's password would let you log in as them, so only a
    super admin may do that (anyone may manage their own password)."""
    return privileged_target_denied(target_email, "manage another admin's password")


def _keep_own_session(target_email, new_version, must_change):
    """An admin changing their own password keeps the current session alive."""
    if session['user'].get('email') == target_email:
        session['user']['session_version'] = new_version
        session['user']['must_change_password'] = bool(must_change)
        session.modified = True


@admin_bp.route('/admin/group-requests/<action>', methods=['POST'])
@admin_required
def handle_group_request(action):
    """Approve/reject a join request. Body: {"email": ..., "group_name": ...}.
    A request is a row in auth.usr_group with status 'request'; approving sets 'joined'."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    group_name = (data.get('group_name') or '').strip()
    if not email or not group_name:
        return jsonify({'error': 'email and group_name required'}), 400
    req = get_group_request(email, group_name)
    if not req:
        return jsonify({'error': 'Request not found'}), 404
    if req.get('status') != 'request':
        # Only pending requests can be approved/rejected (don't touch memberships).
        return jsonify({'error': 'No pending request for this user and group'}), 400

    if action == 'approve':
        if update_group_request_status(email, group_name, 'joined'):
            audit('group_add', email, f'group={group_name} via=request')
            return jsonify({'success': True, 'message': 'Request approved'})
        return jsonify({'error': 'Failed to add user to group'}), 500

    elif action == 'reject':
        update_group_request_status(email, group_name, 'rejected')
        return jsonify({'success': True, 'message': 'Request rejected'})

    return jsonify({'error': 'Invalid action'}), 400

# ===============================================================================
# USER MANAGEMENT
# ===============================================================================
@admin_bp.route('/admin/update-role', methods=['POST'])
@admin_required
def update_user_role():
    data = request.get_json(silent=True) or {}
    user_email = data.get('user_email')
    new_role = data.get('role')
    if not user_email or new_role not in ('guest', 'user', 'admin'):
        return jsonify({'error': 'Invalid parameters'}), 400
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot change your own role'}), 400
    target = get_user(user_email)
    if not target:
        return jsonify({'error': 'User does not exist'}), 404
    denied = privileged_target_denied(user_email, "change another admin's role")
    if denied:
        return denied
    if update_user(user_email, role=new_role):
        audit('update_role', user_email, f"{target.get('role')}->{new_role}")
        return jsonify({'success': True, 'message': f'Role updated to {new_role}'})
    return jsonify({'error': 'Failed to update role'}), 500

@admin_bp.route('/admin/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin_status():
    
    data = request.get_json(silent=True) or {}
    user_email = data.get('user_email')
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot change your own admin status'}), 400
    
    target = get_user(user_email)
    if not target:
        return jsonify({'error': 'User does not exist'}), 400
    
    current_admin_status = bool(target.get('is_admin', False))
    new_admin_status = not current_admin_status
    # Demoting an admin (or touching a super admin) is super-admin only.
    denied = privileged_target_denied(user_email, "change another admin's admin status")
    if denied:
        return denied
    
    if update_user(user_email, is_admin=new_admin_status):
        audit('toggle_admin', user_email, f'is_admin={current_admin_status}->{new_admin_status}')
        status = "promoted to admin" if new_admin_status else "removed from admin"
        return jsonify({'success': True, 'message': f'User {status} successfully'})
    else:
        return jsonify({'error': 'Failed to update admin status'}), 500

@admin_bp.route('/admin/delete-user', methods=['POST'])
@admin_required
def delete_user_route():
    
    data = request.get_json(silent=True) or {}
    user_email = data.get('user_email')
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    target = get_user(user_email)
    if not target:
        return jsonify({'error': 'User does not exist'}), 400
    denied = privileged_target_denied(user_email, 'delete an admin account')
    if denied:
        return denied
    
    if delete_user(user_email):
        audit('delete_user', user_email, f"role={target.get('role')}")
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    else:
        return jsonify({'error': 'Failed to delete user'}), 500

@admin_bp.route('/admin/user-groups/<user_email>')
@admin_required
def get_user_groups(user_email):
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    users = get_users()
    groups = get_groups()
    
    user_groups = users[user_email].get('groups', [])
    all_groups = list(groups.keys())
    available_groups = [g for g in all_groups if g not in user_groups]
    
    return jsonify({
        'success': True,
        'user_groups': user_groups,
        'available_groups': available_groups,
        'all_groups': all_groups
    })

@admin_bp.route('/admin/batch-update-groups', methods=['POST'])
@admin_required
def batch_update_groups():
    
    data = request.get_json(silent=True) or {}
    user_email = data.get('user_email')
    new_groups = data.get('groups', [])
    if not isinstance(new_groups, list):
        return jsonify({'error': 'groups must be a list'}), 400
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    users = get_users()
    current_groups = users[user_email].get('groups', [])
    
    for group in current_groups:
        if group not in new_groups:
            if remove_user_from_group(user_email, group):
                audit('group_remove', user_email, f'group={group}')
    
    for group in new_groups:
        if group not in current_groups:
            if group_exists(group):
                if add_user_to_group(user_email, group):
                    audit('group_add', user_email, f'group={group}')
    
    update_user_session_groups(user_email)
    
    return jsonify({'success': True, 'message': 'Groups updated successfully'})

@admin_bp.route('/admin/available-users/<group_name>')
@admin_required
def get_available_users(group_name):
    
    if not group_exists(group_name):
        return jsonify({'error': 'Group does not exist'}), 400
    
    users = get_users()
    groups = get_groups()
    
    group_members = groups[group_name].get('members', [])
    available_users = []
    
    for email, user in users.items():
        if email not in group_members:
            available_users.append({
                'email': email,
                'name': user.get('name', 'Unknown'),
                'picture': user.get('picture', '/static/img/default-avatar.png')
            })
    
    return jsonify({
        'success': True,
        'available_users': available_users
    })

@admin_bp.route('/admin/add-multiple-to-group', methods=['POST'])
@admin_required
def add_multiple_to_group():
    
    data = request.get_json(silent=True) or {}
    group_name = data.get('group_name')
    user_emails = data.get('user_emails', [])
    if not isinstance(user_emails, list):
        return jsonify({'error': 'user_emails must be a list'}), 400
    
    if not group_name or not user_emails:
        return jsonify({'error': 'Group name and user emails are required'}), 400
    
    if not group_exists(group_name):
        return jsonify({'error': 'Group does not exist'}), 400
    
    added_count = 0
    errors = []
    
    for user_email in user_emails:
        if not user_exists(user_email):
            errors.append(f'User {user_email} does not exist')
            continue
        
        if user_in_group(user_email, group_name):
            errors.append(f'User {user_email} is already in this group')
            continue
        
        if add_user_to_group(user_email, group_name):
            audit('group_add', user_email, f'group={group_name}')
            added_count += 1
        else:
            errors.append(f'Failed to add user {user_email} to group')
    
    if added_count > 0:
        message = f'Successfully added {added_count} users to group'
        if errors:
            message += f'. {len(errors)} errors occurred.'
        return jsonify({
            'success': True, 
            'message': message,
            'added_count': added_count,
            'errors': errors
        })
    else:
        return jsonify({'error': 'No users were added. ' + '; '.join(errors)}), 400


@admin_bp.route('/admin/force-logout', methods=['POST'])
@admin_required
def admin_force_logout():
    """End every session of a user ("log out all devices" on their behalf)."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    target = get_login_email(email) if email else None
    if not target:
        return jsonify({'error': 'User not found'}), 404
    denied = privileged_target_denied(target, "log out another admin")
    if denied:
        return denied
    new_version = bump_session_version(target)
    if new_version is None:
        return jsonify({'error': 'Failed to log out the user'}), 500
    audit('force_logout', target, f'session_version->{new_version}')
    if target == session['user'].get('email'):
        session.clear()
        return jsonify({'success': True, 'message': 'All your sessions were logged out.', 'self': True})
    return jsonify({'success': True, 'message': f'All sessions of {target} were logged out.'})
