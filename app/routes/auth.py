"""
Authentication routes (Google OAuth, login, logout)
"""
from flask import session, flash, redirect, url_for, request
from datetime import datetime
from modules.database import user_exists, get_users, save_user, update_user
from modules.config import config

def register_auth_routes(app):
    # Import OAuth here to avoid circular imports
    from authlib.integrations.flask_client import OAuth
    
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

    def update_user_session_groups(user_email):
        if 'user' in session and session['user']['email'] == user_email:
            users = get_users()
            user_data = users.get(user_email, {})
            user_groups = user_data.get('groups', [])
            
            session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups
            session.modified = True

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
                is_great_lab_member = False
                existing_user_data = None
                
                if user_exists(user_email):
                    users = get_users()
                    existing_user_data = users[user_email]
                    is_admin = existing_user_data.get('is_admin', False)
                    user_groups = existing_user_data.get('groups', [])
                    is_great_lab_member = 'GREAT_Lab' in user_groups
                else:
                    if user_email == config.ADMIN_EMAIL:
                        is_admin = True
                
                display_name = user_info.get('name')
                display_picture = user_info.get('picture')
                
                if existing_user_data:
                    display_name = existing_user_data.get('name', user_info.get('name'))
                    display_picture = existing_user_data.get('picture', user_info.get('picture'))
                
                session['user'] = {
                    'email': user_email,
                    'name': display_name,
                    'picture': display_picture,
                    'is_admin': is_admin,
                    'is_great_lab_member': is_great_lab_member
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
            print(f"Login error: {e}")
            flash('Login failed, please try again.', 'error')
            return redirect(url_for('login'))

    @app.route('/logout')
    def logout():
        session.clear()
        flash('You have been logged out.', 'info')
        return redirect(url_for('home'))

    @app.route('/update-profile', methods=['POST'])
    def update_profile():
        if 'user' not in session:
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        
        try:
            name = request.form.get('name', '').strip()
            picture = request.form.get('picture', '').strip()
            
            if not name:
                flash('Name cannot be empty.', 'error')
                return redirect(url_for('profile'))
            
            if user_exists(user_email):
                users = get_users()
                current_data = users[user_email]
                
                update_user(
                    user_email,
                    name=name,
                    picture=picture or current_data.get('picture', ''),
                    is_admin=current_data.get('is_admin', False),
                    groups=current_data.get('groups', [])
                )
                
                session['user']['name'] = name
                session['user']['picture'] = picture or session['user']['picture']
                session.modified = True
                
                flash('Profile updated successfully!', 'success')
            else:
                flash('User not found.', 'error')
                
        except Exception as e:
            print(f"Profile update error: {e}")
            flash('Error updating profile.', 'error')
        
        return redirect(url_for('profile'))
    
    # Make update_user_session_groups available to other modules
    app.update_user_session_groups = update_user_session_groups
