"""
Authentication routes (Google OAuth, login, logout)
"""
import logging
from flask import session, flash, redirect, url_for, request, jsonify, g

logger = logging.getLogger(__name__)
from datetime import datetime
from modules.web_postgres_database import user_exists, get_users, get_user, save_user, update_user, get_setting, get_invitation, check_object_access, create_group_request, group_exists, user_in_group, remove_user_from_group, get_user_group_requests
from modules.config import config

from flask import Blueprint
auth_bp = Blueprint('auth', __name__, template_folder='templates', static_folder='static')
# Import OAuth here to avoid circular imports
from authlib.integrations.flask_client import OAuth

# oauth logic moved to main

oauth = OAuth()
google = oauth.register(
    name='google',
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)


def refresh_user_session():
    """Refresh user session data from database on every request (registered globally)"""
    if 'user' not in session:
        return
    if request.path.startswith('/static'):
        return

    user_email = session['user']['email']
    user_data = get_user(user_email)

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
    is_great_lab_member = 'GREAT_Lab' in user_groups or check_object_access('greatlab_routes', user_email)
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
    if 'user' in session and session['user']['email'] == user_email:
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups or check_object_access('greatlab_routes', user_email)
        session.modified = True

@auth_bp.route('/auth/google')
def google_login():
    redirect_uri = url_for('auth.google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@auth_bp.route('/auth/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if user_info:
            user_email = user_info.get('email')
            
            is_admin = False
            role = 'guest'
            is_great_lab_member = False
            existing_user_data = None
            
            if user_exists(user_email):
                users = get_users()
                existing_user_data = users[user_email]
                is_admin = existing_user_data.get('is_admin', False)
                role = existing_user_data.get('role', 'guest')
                user_groups = existing_user_data.get('groups', [])
                is_great_lab_member = 'GREAT_Lab' in user_groups or check_object_access('greatlab_routes', user_email)
            else:
                if user_email == config.ADMIN_EMAIL:
                    is_admin = True
                    role = 'admin'
            
            display_name = user_info.get('name')
            display_picture = user_info.get('picture')
            
            if existing_user_data:
                display_name = existing_user_data.get('name') or user_info.get('name')
                display_picture = existing_user_data.get('picture') or user_info.get('picture')
                
            # Prevent huge base64 strings in session cookie (limit 4KB)
            session_picture = display_picture
            if session_picture and session_picture.startswith('data:image'):
                session_picture = user_info.get('picture') # fallback to google picture for cookie
            
            session['user'] = {
                'email': user_email,
                'name': display_name,
                'picture': session_picture,
                'is_admin': is_admin,
                'role': role,
                'is_great_lab_member': is_great_lab_member
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
                    picture=user_info.get('picture'),
                    is_admin=is_admin,
                    role=role,
                    last_login=datetime.now().isoformat(),
                    invited_at=datetime.now().isoformat()
                )
            
            if 'pending_invitation' in session:
                return redirect(url_for('admin.accept_invitation', token=session['pending_invitation']))
            
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

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('basic.home'))


@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    expected_username = config.ADMIN_USERNAME or ''
    expected_password = config.ADMIN_PASSWORD or ''

    if (username.lower() == expected_username.lower() and password == expected_password):
        admin_email = config.ADMIN_LOCAL_EMAIL
        admin_data = get_user(admin_email)

        if admin_data:
            user_groups = admin_data.get('groups', [])
            is_great_lab_member = 'GREAT_Lab' in user_groups or check_object_access('greatlab_routes', admin_email)
            session_picture = admin_data.get('picture')
            if session_picture and session_picture.startswith('data:image'):
                session_picture = None
            session['user'] = {
                'email': admin_email,
                'name': admin_data.get('name', 'Admin'),
                'picture': session_picture,
                'is_admin': admin_data.get('is_admin', True),
                'role': admin_data.get('role', 'admin'),
                'is_great_lab_member': is_great_lab_member
            }
            update_user(admin_email, last_login=datetime.now().isoformat())
        else:
            # Fallback if DB row not found
            session['user'] = {
                'email': admin_email,
                'name': 'Admin',
                'picture': None,
                'is_admin': True,
                'role': 'admin',
                'is_great_lab_member': True
            }

        flash('Welcome Administrator!', 'success')
        next_url = session.pop('next_url', None)
        return redirect(next_url or url_for('basic.home'))
    else:
        flash('Invalid admin credentials.', 'error')
        return redirect(url_for('basic.login'))

@auth_bp.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user' not in session:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Not logged in'}), 401
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    
    try:
        if request.is_json:
            data = request.get_json()
            name = data.get('name', '').strip()
            picture = data.get('picture', '').strip()
        else:
            name = request.form.get('name', '').strip()
            picture = request.form.get('picture', '').strip()
        
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
                is_admin=current_data.get('is_admin', False)
            )
            
            session['user']['name'] = name
            # Never store large base64 strings in the session cookie (limit 4KB)
            if picture and not picture.startswith('data:image'):
                session['user']['picture'] = picture
            
            # Failsafe: if a base64 string accidentally got stuck in the session, clear it
            if session['user'].get('picture', '').startswith('data:image'):
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

# Make update_user_session_groups available to other modules
auth_bp.update_user_session_groups = update_user_session_groups


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
    requests_map = get_user_group_requests(user_email)
    if requests_map.get(group_name) == 'pending':
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
