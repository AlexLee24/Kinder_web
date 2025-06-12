# ===============================================================================
# IMPORTS AND CONFIGURATION
# ===============================================================================
from flask import Flask, render_template, redirect, url_for, session, flash, request, jsonify
from authlib.integrations.flask_client import OAuth
from authlib.common.security import generate_token
import os
import re
import ephem
import math
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

import modules.obsplan as obs
from modules.config import config
from modules.database import (
    init_database, get_users, save_user, update_user, delete_user, user_exists,
    get_groups, create_group, delete_group, group_exists,
    add_user_to_group, remove_user_from_group, user_in_group,
    get_invitations, create_invitation, get_invitation, update_invitation,
    delete_invitation, clean_accepted_invitations,
    check_data_consistency, clean_data_consistency
)
from modules.email_utils import send_invitation_email
from modules.astronomy_calculator import calculate_redshift_distance, calculate_absolute_magnitude
from modules.date_converter import convert_mjd_to_date, convert_jd_to_date, convert_common_date_to_jd
from modules.coordinate_converter import (
    convert_ra_hms_to_decimal, convert_ra_decimal_to_hms,
    convert_dec_dms_to_decimal, convert_dec_decimal_to_dms
)
from modules.tns_scheduler import tns_scheduler
from modules.tns_database import init_tns_database, get_tns_statistics, search_tns_objects, get_filtered_stats, get_objects_count


app = Flask(__name__, template_folder='html', static_folder='static')
app.secret_key = config.SECRET_KEY

init_database()
init_tns_database()
tns_scheduler.start_scheduler()


# ===============================================================================
# OAUTH CONFIGURATION
# ===============================================================================
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# ===============================================================================
# BASIC ROUTES
# ===============================================================================
@app.route('/')
def home():
    return render_template('home.html', current_path='/')

@app.route('/login')
def login():
    return render_template('login.html', current_path='/login')

@app.route('/profile')
def profile():
    if 'user' not in session:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('login'))
    
    user_email = session['user']['email']
    user_groups = []
    user_data = None
    
    if user_exists(user_email):
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        session['user']['name'] = user_data.get('name', session['user']['name'])
        session['user']['picture'] = user_data.get('picture', session['user']['picture'])
        session['user']['is_admin'] = user_data.get('is_admin', False)
    
    return render_template('profile.html', 
                         current_path='/profile',
                         user_groups=user_groups,
                         user_data=user_data)

# ===============================================================================
# AUTHENTICATION ROUTES
# ===============================================================================
@app.route('/auth/google')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if user_info:
            user_email = user_info.get('email')
            
            is_admin = False
            existing_user_data = None
            
            if user_exists(user_email):
                users = get_users()
                existing_user_data = users[user_email]
                is_admin = existing_user_data.get('is_admin', False)
            else:
                if user_email == config.ADMIN_EMAIL:
                    is_admin = True
            
            # Use existing user data if available
            display_name = user_info.get('name')
            display_picture = user_info.get('picture')
            
            if existing_user_data:
                display_name = existing_user_data.get('name', user_info.get('name'))
                display_picture = existing_user_data.get('picture', user_info.get('picture'))
            
            session['user'] = {
                'email': user_email,
                'name': display_name,
                'picture': display_picture,
                'is_admin': is_admin
            }
            
            flash_message = 'Welcome Administrator!' if is_admin else f'Welcome {display_name}!'
            flash(flash_message, 'success')
            
            if user_exists(user_email):
                update_user(
                    user_email,
                    name=existing_user_data.get('name', user_info.get('name')),
                    picture=existing_user_data.get('picture', user_info.get('picture')),
                    last_login=datetime.now().isoformat()
                )
            else:
                save_user(
                    email=user_email,
                    name=user_info.get('name'),
                    picture=user_info.get('picture'),
                    is_admin=is_admin,
                    last_login=datetime.now().isoformat(),
                    invited_at=datetime.now().isoformat()
                )
            
            if 'pending_invitation' in session:
                return redirect(url_for('accept_invitation', token=session['pending_invitation']))
            
            return redirect(url_for('home'))
        else:
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('login'))
            
    except Exception as e:
        print(f"OAuth error: {e}")
        flash('An error occurred during login, please try again.', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out.', 'info')
    return redirect(url_for('home'))

# ===============================================================================
# USER PROFILE MANAGEMENT
# ===============================================================================
@app.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    new_name = data.get('name', '').strip()
    
    if not new_name:
        return jsonify({'error': 'Name is required'}), 400
    
    if len(new_name) > 100:
        return jsonify({'error': 'Name is too long (maximum 100 characters)'}), 400
    
    user_email = session['user']['email']
    
    try:
        if not user_exists(user_email):
            save_user(
                email=user_email,
                name=new_name,
                picture=session['user'].get('picture', ''),
                is_admin=session['user'].get('is_admin', False),
                last_login=datetime.now().isoformat(),
                invited_at=datetime.now().isoformat()
            )
        else:
            if not update_user(user_email, name=new_name):
                return jsonify({'error': 'Failed to update name in database'}), 500
        
        session['user']['name'] = new_name
        session.modified = True 
        
        return jsonify({'success': True, 'message': 'Name updated successfully'})
        
    except Exception as e:
        print(f"Profile update error: {e}") 
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

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
        save_user(
            email=user_email,
            name=session['user']['name'],
            picture=session['user']['picture'],
            is_admin=invitation['is_admin'],
            invited_at=invitation['invited_at'],
            last_login=datetime.now().isoformat()
        )
    
    session['user']['is_admin'] = invitation['is_admin']
    
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
    
    return render_template('admin.html', 
                         current_path='/admin',
                         users=users,
                         groups=groups,
                         invitations=invitations,
                         current_user_email=current_user_email)

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
# ASTRONOMY TOOLS
# ===============================================================================
@app.route('/astronomy_tools')
def astronomy_tools():
    return render_template('astronomy_tools.html', current_path='/astronomy_tools')

@app.route('/calculate_redshift', methods=['POST'])
def calculate_redshift():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        redshift = float(data.get('redshift', 0))
        redshift_error = float(data.get('redshift_error')) if data.get('redshift_error') else None
        
        result = calculate_redshift_distance(redshift, redshift_error)
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/calculate_absolute_magnitude', methods=['POST'])
def calculate_absolute_magnitude_route():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        apparent_magnitude = float(data.get('apparent_magnitude'))
        redshift = float(data.get('redshift'))
        extinction = float(data.get('extinction', 0))
        
        result = calculate_absolute_magnitude(apparent_magnitude, redshift, extinction)
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/convert_date', methods=['POST'])
def convert_date():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        mjd = data.get('mjd')
        jd = data.get('jd')
        common_date = data.get('common_date')
        
        if mjd:
            result = convert_mjd_to_date(float(mjd))
        elif jd:
            result = convert_jd_to_date(float(jd))
        elif common_date:
            result = convert_common_date_to_jd(common_date)
        else:
            return jsonify({'error': 'Please provide at least one date value'}), 400
        
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/convert_ra', methods=['POST'])
def convert_ra():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        ra_hms = data.get('ra_hms')
        ra_decimal = data.get('ra_decimal')
        
        if ra_hms:
            result = convert_ra_hms_to_decimal(ra_hms)
        elif ra_decimal is not None:
            result = convert_ra_decimal_to_hms(float(ra_decimal))
        else:
            return jsonify({'error': 'Please provide either HMS or decimal value'}), 400
        
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/convert_dec', methods=['POST'])
def convert_dec():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        dec_dms = data.get('dec_dms')
        dec_decimal = data.get('dec_decimal')
        
        if dec_dms:
            result = convert_dec_dms_to_decimal(dec_dms)
        elif dec_decimal is not None:
            result = convert_dec_decimal_to_dms(float(dec_decimal))
        else:
            return jsonify({'error': 'Please provide either DMS or decimal value'}), 400
        
        return jsonify({'success': True, 'result': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ===============================================================================
# Obs plan
# ===============================================================================
@app.route('/object_plot.html')
def object_plot():
    return render_template('object_plot.html', current_path='/object_plot.html')

def enforce_max_files(folder, max_files):
    """Create folder if it doesn't exist and clean old files"""
    try:
        # Create folder if it doesn't exist
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
            print(f"Created folder: {folder}")
            return  # No files to clean if folder didn't exist
        
        # Get list of files in folder
        try:
            all_items = os.listdir(folder)
            files = [os.path.join(folder, f) for f in all_items 
                    if os.path.isfile(os.path.join(folder, f))]
        except OSError as e:
            print(f"Error listing files in {folder}: {e}")
            return
        
        print(f"Found {len(files)} files in {folder}")
        
        # Clean old files if necessary
        if len(files) > max_files:
            try:
                files.sort(key=os.path.getmtime)  
                files_to_delete = files[:len(files) - max_files]
                
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        print(f"Deleted old file: {os.path.basename(file_path)}")
                    except OSError as e:
                        print(f"Could not delete {file_path}: {e}")
                        
                print(f"Cleaned {len(files_to_delete)} old files")
                        
            except Exception as e:
                print(f"Error during file cleanup: {e}")
                
    except Exception as e:
        print(f"Error in enforce_max_files: {e}")
        raise

def parse_coordinate(coord_str):
    """Parse coordinate in degrees:minutes:seconds format to decimal degrees"""
    parts = coord_str.split(':')
    if len(parts) != 3:
        return float(coord_str)  # Assume it's already decimal
    
    degrees = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    
    # Handle negative coordinates
    sign = 1 if degrees >= 0 else -1
    decimal = abs(degrees) + minutes/60.0 + seconds/3600.0
    return sign * decimal

@app.route("/generate_plot", methods=["POST"])
def generate_plot():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Log incoming request for debugging
        print(f"Generate plot request received from user: {session['user']['email']}")
        
        target_list = []
        plot_folder = os.path.join(app.root_path, "static", "ov_plot")
        unique_filename = f"observing_tracks_{uuid.uuid4().hex}.jpg"
        
        # Ensure plot folder exists and clean old files
        try:
            enforce_max_files(plot_folder, max_files=10)
            print(f"Plot folder prepared: {plot_folder}")
        except Exception as e:
            print(f"Error preparing plot folder: {e}")
            return jsonify({'error': f'Failed to prepare plot folder: {str(e)}'}), 500
        
        # Get and validate request data
        data = request.get_json()
        if not data:
            print("No JSON data received in request")
            return jsonify({'error': 'No data provided'}), 400
        
        print(f"Request data received: {data}")
        
        date = data.get("date")
        observer = data.get("telescope", "Observer")  # Default value
        location = data.get("location")
        timezone = data.get("timezone")
        targets = data.get("targets")
        
        # Validate required fields
        if not date:
            print("Date is missing")
            return jsonify({'error': 'Date is required'}), 400
        if not location:
            print("Location is missing")
            return jsonify({'error': 'Location is required'}), 400
        if not targets or not isinstance(targets, list):
            print(f"Invalid targets: {targets}")
            return jsonify({'error': 'Targets list is required'}), 400
        if not timezone:
            print("Timezone is missing")
            return jsonify({'error': 'Timezone is required'}), 400
        
        print(f"Basic validation passed. Date: {date}, Location: {location}, Timezone: {timezone}, Targets count: {len(targets)}")
        
        # Process date
        try:
            date = date.replace("-", "")
            if len(date) != 8:
                print(f"Invalid date format: {date}")
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            print(f"Date processed: {date}")
        except Exception as e:
            print(f"Date processing error: {e}")
            return jsonify({'error': f'Date processing error: {str(e)}'}), 400
        
        # Process timezone
        try:
            timezone_int = int(timezone)
            timezone_name = obs.get_timezone_name(timezone_int)
            print(f"Timezone processed: {timezone_int} -> {timezone_name}")
        except (ValueError, TypeError) as e:
            print(f"Timezone error: {e}")
            return jsonify({'error': f'Invalid timezone: {str(e)}'}), 400
        except Exception as e:
            print(f"Timezone processing error: {e}")
            return jsonify({'error': f'Timezone processing error: {str(e)}'}), 400
        
        # Process targets
        print("Processing targets...")
        for i, target in enumerate(targets):
            if not isinstance(target, dict):
                print(f"Invalid target format at index {i}: {target}")
                return jsonify({'error': f'Invalid target format at index {i}'}), 400
            
            name = target.get('object_name', f'Target_{i+1}')
            ra = target.get('ra')
            dec = target.get('dec')
            
            print(f"Processing target {i}: {name}, RA: {ra}, Dec: {dec}")
            
            if not ra or not dec:
                print(f"Missing coordinates for target {name}")
                return jsonify({'error': f'RA and Dec are required for target {name}'}), 400
            
            # Clean RA format
            try:
                ra_clean = re.sub(r"[hH]", ":", str(ra))
                ra_clean = re.sub(r"[mM]", ":", ra_clean)
                ra_clean = re.sub(r"[sS]", "", ra_clean).strip()
                
                # Clean Dec format
                dec_clean = re.sub(r"[dD°]", ":", str(dec))
                dec_clean = re.sub(r"[mM′']", ":", dec_clean)
                dec_clean = re.sub(r"[sS″\"]", "", dec_clean).strip()
                
                print(f"Cleaned coordinates - RA: {ra_clean}, Dec: {dec_clean}")
                
                ephem_target = obs.create_ephem_target(name, ra_clean, dec_clean)
                target_list.append(ephem_target)
                print(f"Target {name} created successfully")
                
            except Exception as e:
                print(f"Error creating target {name}: {e}")
                return jsonify({'error': f'Invalid coordinates for target {name}: {str(e)}'}), 400
        
        print(f"All {len(target_list)} targets processed successfully")
        
        # Process observer/location
        try:
            location_parts = location.split()
            if len(location_parts) != 3:
                print(f"Invalid location format: {location}")
                return jsonify({'error': 'Location must have longitude, latitude, and altitude (space-separated)'}), 400
            
            longitude_str, latitude_str, altitude_str = location_parts
            
            # Parse coordinates (could be decimal or DMS format)
            longitude = parse_coordinate(longitude_str)
            latitude = parse_coordinate(latitude_str)
            altitude = float(altitude_str)
            
            print(f"Location parsed - Lon: {longitude}, Lat: {latitude}, Alt: {altitude}")
            
            obs_site = obs.create_ephem_observer(observer, longitude, latitude, altitude)
            print(f"Observer site created: {observer}")
            
        except (ValueError, TypeError, IndexError) as e:
            print(f"Location processing error: {e}")
            return jsonify({'error': f'Invalid location format: {str(e)}'}), 400
        
        # Process observation dates
        try:
            obs_date = str(int(date))
            next_obs_date = str(int(date) + 1)
            
            obs_date_formatted = f"{obs_date[:4]}/{obs_date[4:6]}/{obs_date[6:]}"
            next_obs_date_formatted = f"{next_obs_date[:4]}/{next_obs_date[4:6]}/{next_obs_date[6:]}"
            
            print(f"Date range: {obs_date_formatted} to {next_obs_date_formatted}")
            
            obs_start = ephem.Date(f'{obs_date_formatted} 17:00:00')
            obs_end = ephem.Date(f'{next_obs_date_formatted} 09:00:00')
            
            obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), timezone_name)
            obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), timezone_name)
            
            print(f"Observation times set: {obs_start_local_dt} to {obs_end_local_dt}")
            
        except Exception as e:
            print(f"Date processing error: {e}")
            return jsonify({'error': f'Error processing dates: {str(e)}'}), 400
        
        # Generate plot
        plot_path = os.path.join(plot_folder, unique_filename)
        print(f"Generating plot at: {plot_path}")
        
        try:
            obs.plot_night_observing_tracks(
                target_list, obs_site, obs_start_local_dt, obs_end_local_dt, 
                simpletracks=True, toptime='local', timezone='calculate', 
                n_steps=1000, savepath=plot_path
            )
            print("Plot generation completed")
            
        except Exception as e:
            print(f"Plot generation error: {e}")
            return jsonify({'error': f'Error generating plot: {str(e)}'}), 500
        
        # Verify plot was created
        if not os.path.exists(plot_path):
            print(f"Plot file not found at: {plot_path}")
            return jsonify({'error': 'Plot generation failed - file not created'}), 500
        
        plot_url = f"/static/ov_plot/{unique_filename}"
        success_message = f"Successfully generated plot for {len(target_list)} targets"
        
        print(f"Plot generated successfully: {plot_url}")
        
        return jsonify({
            "success": True, 
            "plot_url": plot_url,
            "message": success_message
        })
        
    except Exception as e:
        error_message = f"Unexpected error in generate_plot: {str(e)}"
        print(error_message)
        import traceback
        traceback.print_exc()
        return jsonify({'error': error_message}), 500

# ===============================================================================
# MARSHAL
# ===============================================================================
@app.route('/marshal')
def marshal():
    if 'user' not in session:
        flash('Please log in to access Marshal.', 'warning')
        return redirect(url_for('login'))
    
    try:
        # Get initial counts for statistics
        total_count = get_objects_count()
        at_count = get_objects_count(object_type='AT')
        classified_count = total_count - at_count
        
        # Get only high-level statistics without loading all objects
        tns_stats = get_tns_statistics()
        
        # Format last sync data properly
        last_sync_data = None
        if tns_stats.get('recent_downloads') and len(tns_stats['recent_downloads']) > 0:
            recent_download = tns_stats['recent_downloads'][0]
            if recent_download.get('download_time'):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(recent_download['download_time'].replace('Z', '+00:00'))
                    last_sync_data = {
                        'time': dt.strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'status': recent_download.get('status', 'unknown'),
                        'imported': recent_download.get('records_imported', 0),
                        'updated': recent_download.get('records_updated', 0),
                        'errors': recent_download.get('error_message', '')
                    }
                except:
                    last_sync_data = {
                        'time': recent_download.get('download_time', 'Unknown'),
                        'status': recent_download.get('status', 'unknown'),
                        'imported': recent_download.get('records_imported', 0),
                        'updated': recent_download.get('records_updated', 0),
                        'errors': recent_download.get('error_message', '')
                    }
        
        # Load initial objects for display (limited to avoid performance issues)
        initial_objects = []
        if total_count <= 5000:  # Only load initial data if reasonable amount
            initial_objects = search_tns_objects(limit=100, sort_by='discoverydate', sort_order='desc')
        
        return render_template('marshal.html', 
                             current_path='/marshal',
                             objects=initial_objects,
                             tns_stats=tns_stats,
                             at_count=at_count,
                             classified_count=classified_count,
                             inbox_count=total_count,
                             followup_count=0,
                             finished_count=0,
                             snoozed_count=0,
                             last_sync=last_sync_data,
                             total_count=total_count)
        
    except Exception as e:
        print(f"Error loading Marshal data: {e}")
        flash('Error loading transient data.', 'error')
        return render_template('marshal.html', 
                             current_path='/marshal',
                             objects=[],
                             tns_stats={},
                             at_count=0,
                             classified_count=0,
                             inbox_count=0,
                             followup_count=0,
                             finished_count=0,
                             snoozed_count=0,
                             last_sync=None,
                             total_count=0)

@app.route('/object/<object_name>')
def object_data(object_name):
    if 'user' not in session:
        flash('Please log in to access object data.', 'warning')
        return redirect(url_for('login'))
    
    try:
        results = search_tns_objects(search_term=object_name, limit=1)
        
        if not results:
            flash(f'Object {object_name} not found.', 'error')
            return redirect(url_for('marshal'))
        
        obj = results[0]
        
        return render_template('object_detail.html', 
                             current_path='/object',
                             obj=obj,
                             object_name=object_name)
        
    except Exception as e:
        print(f"Error loading object data for {object_name}: {e}")
        flash('Error loading object data.', 'error')
        return redirect(url_for('marshal'))

@app.route('/api/objects')
def api_get_objects():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'discoverydate')
    sort_order = request.args.get('sort_order', 'desc')
    search = request.args.get('search', '')
    classification = request.args.get('classification', '')
    tag = request.args.get('tag', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    try:
        # 從資料庫搜尋
        objects = search_tns_objects(
            search_term=search, 
            object_type=classification,
            limit=per_page, 
            offset=(page-1)*per_page,
            sort_by=sort_by, 
            sort_order=sort_order,
            date_from=date_from,
            date_to=date_to,
            tag=tag
        )
        
        # 取得總數
        total = get_objects_count(
            search_term=search, 
            object_type=classification,
            tag=tag,
            date_from=date_from,
            date_to=date_to
        )
        
        # 取得統計資料
        stats = get_filtered_stats(
            search_term=search, 
            object_type=classification,
            tag=tag,
            date_from=date_from,
            date_to=date_to
        )
        
        return jsonify({
            'objects': objects,
            'total': total,
            'total_pages': math.ceil(total / per_page) if total > 0 else 0,
            'page': page,
            'per_page': per_page,
            'stats': stats
        })
    except Exception as e:
        app.logger.error(f"API error: {str(e)}")
        return jsonify({
            'objects': [],
            'total': 0,
            'total_pages': 0,
            'page': page,
            'per_page': per_page,
            'stats': {
                'inbox_count': 0,
                'followup_count': 0,
                'finished_count': 0,
                'snoozed_count': 0,
                'at_count': 0, 
                'classified_count': 0
            },
            'error': str(e)
        }), 500

@app.route('/api/classifications')
def api_get_classifications():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        from modules.tns_database import get_distinct_classifications
        classifications = get_distinct_classifications()
        
        return jsonify({
            'success': True,
            'classifications': classifications
        })
    except Exception as e:
        app.logger.error(f"Classifications API error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'classifications': ['AT', 'SN Ia', 'SN II', 'SN Ib/c']  # Default classifications
        }), 500

# ===============================================================================
# TNS DATA MANAGEMENT
# ===============================================================================
@app.route('/api/tns/manual-download', methods=['POST'])
def manual_tns_download():
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json() or {}
        hour_offset = data.get('hour_offset', 0)
        
        result = tns_scheduler.manual_download(hour_offset)
        
        return jsonify({
            'success': True,
            'message': f'Successfully processed {result["total_processed"]} TNS objects ({result["imported"]} new, {result["updated"]} updated)',
            'imported_count': result['imported'],
            'updated_count': result['updated'],
            'total_processed': result['total_processed']
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tns/search', methods=['POST'])
def search_tns():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').strip()
        object_type = data.get('object_type', '').strip()
        limit = min(int(data.get('limit', 100)), 1000)  # Max 1000 results
        
        results = search_tns_objects(search_term, object_type, limit)
        
        return jsonify({
            'success': True,
            'results': results,
            'count': len(results)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tns/stats')
def tns_stats_api():
    if 'user' not in session:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        stats = get_tns_statistics()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===============================================================================
# APPLICATION STARTUP
# ===============================================================================
import atexit
atexit.register(lambda: tns_scheduler.stop_scheduler())
if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        ssl_context="adhoc"
    )