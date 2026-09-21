"""Admin panel actions — users (split from admin_routes.py)."""
from flask import session, request, jsonify
from app.db.auth import (
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


# ===============================================================================
# USER MANAGEMENT (Direct Add)
# ===============================================================================
@admin_bp.route('/admin/add-user', methods=['POST'])
@admin_required
def add_user():
        
    data = request.get_json()
    email = data.get('email', '').strip()
    role = data.get('role', 'user')
    name = data.get('name', '').strip()
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400
        
    if user_exists(email):
        # If user already exists, maybe just update their role
        from app.db.auth import update_user
        update_user(email, role=role)
        return jsonify({'success': True, 'message': 'User already existed, role updated.'})
        
    # Create new user directly in database
    from app.db.auth import save_user
    
    is_admin = (role == 'admin')
    if not name:
        name = email.split('@')[0]
        
    if save_user(email=email, name=name, picture_url='', is_admin=is_admin, role=role):
        return jsonify({'success': True, 'message': 'User added successfully'})
    else:
        return jsonify({'error': 'Failed to add user to database'}), 500

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
