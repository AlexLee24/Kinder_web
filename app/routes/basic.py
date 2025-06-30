"""
Basic routes (home, login page, profile)
"""
from flask import render_template, redirect, url_for, session, flash

def register_basic_routes(app):
    
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
        
        from modules.database import user_exists, get_users
        if user_exists(user_email):
            users = get_users()
            user_data = users.get(user_email, {})
            user_groups = user_data.get('groups', [])
            
            session['user']['name'] = user_data.get('name', session['user']['name'])
            session['user']['picture'] = user_data.get('picture', session['user']['picture'])
            session['user']['is_admin'] = user_data.get('is_admin', False)
            session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups
        
        return render_template('profile.html', 
                             current_path='/profile',
                             user_groups=user_groups,
                             user_data=user_data)
