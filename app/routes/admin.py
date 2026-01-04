"""
Admin routes for the Kinder web application.
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify
from authlib.common.security import generate_token
from datetime import datetime

from modules.database import (
    get_users, update_user, delete_user, user_exists,
    get_groups, create_group, delete_group, group_exists,
    add_user_to_group, remove_user_from_group, user_in_group,
    get_invitations, create_invitation, get_invitation, update_invitation,
    delete_invitation, clean_accepted_invitations,
    check_data_consistency, clean_data_consistency,
    get_setting, set_setting
)
from modules.email_utils import send_invitation_email


def update_user_session_groups(user_email):
    """Helper function to update user session with current group information"""
    if 'user' in session and session['user']['email'] == user_email:
        users = get_users()
        if user_email in users:
            session['user']['groups'] = users[user_email].get('groups', [])


def register_admin_routes(app):
    """Register admin routes with the Flask app"""
    
    # ===============================================================================
    # INVITATION SYSTEM
    # ===============================================================================
    @app.route('/admin/invite-user', methods=['POST'])
    def invite_user():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        email = data.get('email', '').strip()
        is_admin = data.get('is_admin', False)
        send_email = data.get('send_email', False)
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        if user_exists(email):
            return jsonify({'error': 'User already exists'}), 400
        
        token = generate_token()
        
        if not create_invitation(token, email, is_admin, session['user']['email']):
            return jsonify({'error': 'Failed to create invitation'}), 500
        
        email_sent = False
        if send_email:
            invitation_link = url_for('accept_invitation', token=token, _external=True)
            email_sent = send_invitation_email(email, invitation_link)
        
        return jsonify({
            'success': True, 
            'message': 'Invitation created successfully',
            'email_sent': email_sent,
            'invitation_token': token
        })

    @app.route('/invitation/<token>')
    def accept_invitation(token):
        invitation = get_invitation(token)
        
        if not invitation:
            flash('Invalid or expired invitation.', 'error')
            return redirect(url_for('home'))
        
        if invitation['status'] != 'pending':
            flash('This invitation has already been used.', 'warning')
            return redirect(url_for('home'))
        
        if 'user' not in session:
            session['pending_invitation'] = token
            flash('Please log in to accept the invitation.', 'info')
            return redirect(url_for('login'))
        
        if session['user']['email'] != invitation['email']:
            flash('This invitation is for a different email address.', 'error')
            return redirect(url_for('home'))
        
        user_email = session['user']['email']
        
        if user_exists(user_email):
            update_user(
                user_email,
                is_admin=invitation['is_admin'],
                invited_at=invitation['invited_at']
            )
        else:
            from modules.database import save_user
            save_user(
                email=user_email,
                name=session['user']['name'],
                picture=session['user']['picture'],
                is_admin=invitation['is_admin'],
                invited_at=invitation['invited_at'],
                last_login=datetime.now().isoformat()
            )
        
        session['user']['is_admin'] = invitation['is_admin']
        update_user_session_groups(user_email)
        delete_invitation(token)
        session.pop('pending_invitation', None)
        
        admin_msg = " with administrator privileges" if invitation['is_admin'] else ""
        flash(f'Successfully joined the platform{admin_msg}!', 'success')
        return redirect(url_for('profile'))

    @app.route('/admin/delete-invitation', methods=['POST'])
    def delete_invitation_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        token = data.get('token')
        
        if not token:
            return jsonify({'error': 'Invitation token is required'}), 400
        
        if delete_invitation(token):
            return jsonify({'success': True, 'message': 'Invitation deleted successfully'})
        else:
            return jsonify({'error': 'Failed to delete invitation or invitation not found'}), 500

    @app.route('/admin/clean-invitations', methods=['POST'])
    def clean_invitations():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        cleaned_count = clean_accepted_invitations()
        
        return jsonify({
            'success': True, 
            'message': f'Cleaned {cleaned_count} accepted invitations',
            'cleaned_count': cleaned_count
        })

    # ===============================================================================
    # ADMIN PANEL
    # ===============================================================================
    @app.route('/admin')
    def admin_panel():
        if 'user' not in session or not session['user'].get('is_admin'):
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        groups = get_groups()
        invitations = get_invitations()
        
        current_user_email = session['user']['email']
        
        # Get settings
        custom_targets_public = get_setting('custom_targets_public_access', 'false') == 'true'
        
        return render_template('admin.html', 
                             current_path='/admin',
                             users=users,
                             groups=groups,
                             invitations=invitations,
                             current_user_email=current_user_email,
                             custom_targets_public=custom_targets_public)

    @app.route('/admin/settings/save', methods=['POST'])
    def save_settings():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
            
        data = request.get_json()
        key = data.get('key')
        value = data.get('value')
        
        if not key:
            return jsonify({'error': 'Key is required'}), 400
            
        if set_setting(key, value):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to save setting'}), 500

    # ===============================================================================
    # USER MANAGEMENT
    # ===============================================================================
    @app.route('/admin/toggle-admin', methods=['POST'])
    def toggle_admin_status():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    @app.route('/admin/delete-user', methods=['POST'])
    def delete_user_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    # ===============================================================================
    # GROUP MANAGEMENT
    # ===============================================================================
    @app.route('/admin/create-group', methods=['POST'])
    def create_group_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        group_name = data.get('name', '').strip()
        group_description = data.get('description', '').strip()
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if group_exists(group_name):
            return jsonify({'error': 'Group already exists'}), 400
        
        if create_group(group_name, group_description, session['user']['email']):
            return jsonify({'success': True, 'message': 'Group created successfully'})
        else:
            return jsonify({'error': 'Failed to create group'}), 500

    @app.route('/admin/delete-group', methods=['POST'])
    def delete_group_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if not group_exists(group_name):
            return jsonify({'error': 'Group does not exist'}), 400
        
        if delete_group(group_name):
            return jsonify({'success': True, 'message': 'Group deleted successfully'})
        else:
            return jsonify({'error': 'Failed to delete group'}), 500

    # ===============================================================================
    # GROUP MEMBERSHIP MANAGEMENT
    # ===============================================================================
    @app.route('/admin/add-to-group', methods=['POST'])
    def add_user_to_group_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        user_email = data.get('user_email')
        group_name = data.get('group_name')
        
        if not user_email or not group_name:
            return jsonify({'error': 'User email and group name are required'}), 400
        
        if not user_exists(user_email):
            return jsonify({'error': 'User does not exist'}), 400
        
        if not group_exists(group_name):
            return jsonify({'error': 'Group does not exist'}), 400
        
        if user_in_group(user_email, group_name):
            return jsonify({'error': 'User is already in this group'}), 400
        
        if add_user_to_group(user_email, group_name):
            update_user_session_groups(user_email)
            return jsonify({'success': True, 'message': 'User added to group successfully'})
        else:
            return jsonify({'error': 'Failed to add user to group'}), 500

    @app.route('/admin/remove-from-group', methods=['POST'])
    def remove_user_from_group_route():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json()
        user_email = data.get('user_email')
        group_name = data.get('group_name')
        
        if not user_email or not group_name:
            return jsonify({'error': 'User email and group name are required'}), 400
        
        if not user_exists(user_email) or not group_exists(group_name):
            return jsonify({'error': 'User or group does not exist'}), 400
        
        if remove_user_from_group(user_email, group_name):
            update_user_session_groups(user_email)
            return jsonify({'success': True, 'message': 'User removed from group successfully'})
        else:
            return jsonify({'error': 'Failed to remove user from group'}), 500

    @app.route('/admin/user-groups/<user_email>')
    def get_user_groups(user_email):
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    @app.route('/admin/batch-update-groups', methods=['POST'])
    def batch_update_groups():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    @app.route('/admin/available-users/<group_name>')
    def get_available_users(group_name):
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    @app.route('/admin/add-multiple-to-group', methods=['POST'])
    def add_multiple_to_group():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
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

    # ===============================================================================
    # DATA CONSISTENCY MANAGEMENT
    # ===============================================================================
    @app.route('/admin/check-consistency')
    def check_consistency():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        issues = check_data_consistency()
        
        return jsonify({
            'success': True,
            'issues': issues,
            'has_issues': issues['total_issues'] > 0
        })

    @app.route('/admin/clean-consistency', methods=['POST'])
    def clean_consistency():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        cleaned_count = clean_data_consistency()
        
        return jsonify({
            'success': True,
            'message': f'Cleaned {cleaned_count} data consistency issues',
            'cleaned_count': cleaned_count
        })
