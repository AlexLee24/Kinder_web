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
)
from . import admin_bp
from .helpers import update_user_session_groups
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r'^[^@\s<>"\']+@[^@\s<>"\']+\.[^@\s<>"\']+$')


# ===============================================================================
# USER MANAGEMENT (Direct Add)
# ===============================================================================
@admin_bp.route('/admin/add-user', methods=['POST'])
@admin_required
def add_user():
    """Create an account. With ``password`` it can sign in without Google.

    Only admins reach this route; there is no public sign-up for password accounts."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    role = data.get('role', 'user')
    name = str(data.get('name') or '').strip()[:80]
    password = data.get('password') or ''
    must_change = bool(data.get('must_change_password', True))

    if not email or not _EMAIL_RE.match(email) or len(email) > 254:
        return jsonify({'error': 'A valid email address is required'}), 400
    if role not in ('guest', 'user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400
    if password:
        problem = password_problem(password, email)
        if problem:
            return jsonify({'error': problem}), 400

    existing_email = get_login_email(email)
    if existing_email:
        if password:
            return jsonify({'error': 'This user already exists. Use "Set password" on their row instead.'}), 409
        update_user(existing_email, role=role)
        return jsonify({'success': True, 'message': 'User already existed, role updated.'})

    if not name:
        name = email.split('@')[0]
    name = re.sub(r'[<>]', '', name).strip() or email.split('@')[0]

    if not save_user(email=email, name=name, picture_url='', is_admin=(role == 'admin'), role=role):
        return jsonify({'error': 'Failed to add user to database'}), 500
    if password:
        if set_password_hash(email, hash_password(password), must_change=must_change) is None:
            return jsonify({'error': 'User created, but setting the password failed'}), 500
    logger.info('Admin %s created user %s (role=%s, password_login=%s)',
                session['user']['email'], email, role, bool(password))
    return jsonify({'success': True, 'message': 'User added successfully'})


@admin_bp.route('/admin/set-password', methods=['POST'])
@admin_required
def admin_set_password():
    """Set or reset a user's password; logs out all of that user's sessions."""
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip()
    password = data.get('password') or ''
    must_change = bool(data.get('must_change_password', True))

    target = get_login_email(email) if email else None
    if not target:
        return jsonify({'error': 'User not found'}), 404
    denied = _password_management_denied(target)
    if denied:
        return denied
    problem = password_problem(password, target)
    if problem:
        return jsonify({'error': problem}), 400

    new_version = set_password_hash(target, hash_password(password), must_change=must_change)
    if new_version is None:
        return jsonify({'error': 'Failed to set password'}), 500
    _keep_own_session(target, new_version, must_change)
    logger.info('Admin %s set a password for %s (must_change=%s)',
                session['user']['email'], target, must_change)
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
    logger.info('Admin %s removed password login for %s', session['user']['email'], target)
    return jsonify({'success': True, 'message': f'Password login disabled for {target}.'})


def _password_management_denied(target_email):
    """Setting another admin's password would let you log in as them, so only a
    super admin may do that (anyone may manage their own password)."""
    if target_email == session['user'].get('email'):
        return None
    target = get_user(target_email) or {}
    if not target.get('is_admin'):
        return None
    me = get_user(session['user'].get('email')) or {}
    if me.get('is_super_admin'):
        return None
    return jsonify({'error': 'Only a super admin can manage another admin\'s password.'}), 403


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
    data = request.get_json()
    user_email = data.get('user_email')
    new_role = data.get('role')
    if not user_email or new_role not in ('guest', 'user', 'admin'):
        return jsonify({'error': 'Invalid parameters'}), 400
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot change your own role'}), 400
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 404
    if update_user(user_email, role=new_role):
        return jsonify({'success': True, 'message': f'Role updated to {new_role}'})
    return jsonify({'error': 'Failed to update role'}), 500

@admin_bp.route('/admin/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin_status():
    
    data = request.get_json()
    user_email = data.get('user_email')
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot change your own admin status'}), 400
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    users = get_users()
    current_admin_status = users[user_email].get('is_admin', False)
    new_admin_status = not current_admin_status
    
    if update_user(user_email, is_admin=new_admin_status):
        status = "promoted to admin" if new_admin_status else "removed from admin"
        return jsonify({'success': True, 'message': f'User {status} successfully'})
    else:
        return jsonify({'error': 'Failed to update admin status'}), 500

@admin_bp.route('/admin/delete-user', methods=['POST'])
@admin_required
def delete_user_route():
    
    data = request.get_json()
    user_email = data.get('user_email')
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if user_email == session['user']['email']:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    if delete_user(user_email):
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
    
    data = request.get_json()
    user_email = data.get('user_email')
    new_groups = data.get('groups', [])
    
    if not user_email:
        return jsonify({'error': 'User email is required'}), 400
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    users = get_users()
    current_groups = users[user_email].get('groups', [])
    
    for group in current_groups:
        if group not in new_groups:
            remove_user_from_group(user_email, group)
    
    for group in new_groups:
        if group not in current_groups:
            if group_exists(group):
                add_user_to_group(user_email, group)
    
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
    
    data = request.get_json()
    group_name = data.get('group_name')
    user_emails = data.get('user_emails', [])
    
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
