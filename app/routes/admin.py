"""
Admin routes for the Kinder web application.
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify, current_app
from authlib.common.security import generate_token
from datetime import datetime
import os
import re

from modules.web_postgres_database import (
    get_users, update_user, delete_user, user_exists,
    get_groups, create_group, delete_group, group_exists,
    add_user_to_group, remove_user_from_group, user_in_group,
    get_invitations, create_invitation, get_invitation, update_invitation,
    delete_invitation, clean_accepted_invitations,
    check_data_consistency, clean_data_consistency,
    get_setting, set_setting,
    get_group_requests, update_group_request_status, get_group_request, delete_group_request
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
    # USER MANAGEMENT (Direct Add)
    # ===============================================================================
    @app.route('/admin/add-user', methods=['POST'])
    def add_user():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
            
        data = request.get_json()
        email = data.get('email', '').strip()
        role = data.get('role', 'user')
        name = data.get('name', '').strip()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
            
        if user_exists(email):
            # If user already exists, maybe just update their role
            from modules.web_postgres_database import update_user
            update_user(email, is_admin=(role == 'admin'), role=role)
            return jsonify({'success': True, 'message': 'User already existed, role updated.'})
            
        # Create new user directly in database
        from modules.web_postgres_database import save_user
        
        is_admin = (role == 'admin')
        if not name:
            name = email.split('@')[0]
            
        if save_user(
            email=email,
            name=name,
            picture='/static/img/default-avatar.png',  # Default picture
            is_admin=is_admin,
            role=role,
            invited_at=datetime.utcnow().isoformat(),
            last_login=None
        ):
            return jsonify({'success': True, 'message': 'User added successfully'})
        else:
            return jsonify({'error': 'Failed to add user to database'}), 500

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
        group_requests = get_group_requests('pending')
        
        current_user_email = session['user']['email']
        
        # Get settings
        open_registration = get_setting('open_registration', 'true') == 'true'
        
        return render_template('admin.html', 
                             current_path='/admin',
                             users=users,
                             groups=groups,
                             invitations=invitations,
                             group_requests=group_requests,
                             current_user_email=current_user_email,
                             open_registration=open_registration)

    @app.route('/admin/group-requests/<int:request_id>/<action>', methods=['POST'])
    def handle_group_request(request_id, action):
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
            
        req = get_group_request(request_id)
        if not req:
            return jsonify({'error': 'Request not found'}), 404
            
        if action == 'approve':
            if add_user_to_group(req['user_email'], req['group_name']):
                update_group_request_status(request_id, 'approved')
                return jsonify({'success': True, 'message': 'Request approved'})
            return jsonify({'error': 'Failed to add user to group'}), 500
            
        elif action == 'reject':
            update_group_request_status(request_id, 'rejected')
            return jsonify({'success': True, 'message': 'Request rejected'})
            
        return jsonify({'error': 'Invalid action'}), 400

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

    # ===============================================================================
    # MANUAL BACKUP
    # ===============================================================================
    @app.route('/admin/backup-now', methods=['POST'])
    def backup_now():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        try:
            from modules.backup import run_daily_backup
            run_daily_backup(force=True)
            return jsonify({'success': True, 'message': 'Backup completed successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ===============================================================================
    # DOCUMENT RESOURCE MANAGEMENT
    # ===============================================================================
    @app.route('/admin/documents/clean-images', methods=['POST'])
    def clean_unused_images():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
            
        try:
            tutorials_dir = os.path.join(current_app.root_path, 'static', 'tutorials')
            images_dir = os.path.join(tutorials_dir, 'images')
            
            if not os.path.exists(images_dir):
                return jsonify({'success': True, 'message': 'No images directory found', 'cleaned_count': 0})
                
            # 1. Collect all images on disk
            all_images = set(os.listdir(images_dir))
            
            # 2. Extract referenced images from all markdown files
            used_images = set()
            for filename in os.listdir(tutorials_dir):
                if filename.endswith('.md'):
                    filepath = os.path.join(tutorials_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Match formats like markdown image ![](images/xxx.png) or HTML <img src=".../images/xxx.png">
                        # But more simply, check if image name exists in text
                        for img in all_images:
                            if img in content:
                                used_images.add(img)
                                
            # 3. Determine unused images
            unused_images = all_images - used_images
            
            # 4. Remove unused images
            cleaned_count = 0
            for img in unused_images:
                try:
                    os.remove(os.path.join(images_dir, img))
                    cleaned_count += 1
                except Exception as e:
                    print(f"Error removing image {img}: {e}")
                    
            return jsonify({
                'success': True,
                'message': f'Cleaned {cleaned_count} unused image(s)',
                'cleaned_count': cleaned_count
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ===============================================================================
    # PHOTOMETRY SCHEDULER
    # ===============================================================================
    @app.route('/admin/run-photometry-fetch', methods=['POST'])
    def run_photometry_fetch():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403

        from modules.phot_scheduler import fetch_inbox_photometry, is_running
        import threading

        if is_running():
            return jsonify({'success': False, 'message': 'Photometry fetch is already running'}), 409

        def _run():
            fetch_inbox_photometry()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return jsonify({'success': True, 'message': 'Photometry fetch started in background'})

    @app.route('/admin/photometry-fetch-status')
    def photometry_fetch_status():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403

        from modules.phot_scheduler import is_running, get_progress
        progress = get_progress()
        return jsonify({'running': is_running(), **progress})
