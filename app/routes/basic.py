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

    @app.route('/games')
    def games():
        return render_template('games.html', current_path='/games')

    import os, json
    from datetime import datetime
    
    LEADERBOARD_FILE = os.path.join('app', 'data', '1a2b_leaderboard.json')

    @app.route('/api/games/leaderboard', methods=['GET'])
    def get_leaderboard():
        if os.path.exists(LEADERBOARD_FILE):
            with open(LEADERBOARD_FILE, 'r') as f:
                try:
                    data = json.load(f)
                except:
                    data = []
        else:
            data = []
        
        # Sort by attempts (ascending)
        data.sort(key=lambda x: x['attempts'])
        return jsonify(data[:10])  # Return top 10

    @app.route('/api/games/leaderboard', methods=['POST'])
    def submit_score():
        data = request.json
        attempts = data.get('attempts')
        
        if not attempts or not isinstance(attempts, int):
            return jsonify({'success': False, 'error': 'Invalid attempts'}), 400
            
        name = session.get('user', {}).get('name', 'User') if 'user' in session else 'User'
        
        record = {
            'name': name,
            'attempts': attempts,
            'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        records = []
        if os.path.exists(LEADERBOARD_FILE):
            with open(LEADERBOARD_FILE, 'r') as f:
                try:
                    records = json.load(f)
                except:
                    pass
                    
        records.append(record)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(LEADERBOARD_FILE), exist_ok=True)
        
        with open(LEADERBOARD_FILE, 'w') as f:
            json.dump(records, f)
            
        return jsonify({'success': True})

    @app.route('/profile')
    def profile():
        if 'user' not in session:
            flash('Please log in to view your profile.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        user_groups = []
        user_data = None
        
        from modules.web_postgres_database import user_exists, get_users, get_groups, get_user_group_requests
        all_groups = []
        user_requests = {}
        if user_exists(user_email):
            users = get_users()
            user_data = users.get(user_email, {})
            user_groups = user_data.get('groups', [])
            user_requests = get_user_group_requests(user_email)
            
            session['user']['name'] = user_data.get('name', session['user']['name'])
            session['user']['picture'] = user_data.get('picture', session['user']['picture'])
            session['user']['is_admin'] = user_data.get('is_admin', False)
            from modules.web_postgres_database import check_object_access
            session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups or check_object_access('greatlab_routes', session['user']['email'])
            
            # Fetch all available groups to display
            groups_dict = get_groups()
            for g_name, g_data in groups_dict.items():
                all_groups.append({
                    'name': g_name,
                    'description': g_data.get('description', ''),
                    'member_count': len(g_data.get('members', [])),
                    'is_member': g_name in user_groups,
                    'request_status': user_requests.get(g_name)
                })
        
        return render_template('profile.html', 
                             current_path='/profile',
                             user_groups=user_groups,
                             user_data=user_data,
                             all_groups=all_groups)

    from flask import request, jsonify
    from modules.web_postgres_database import create_group_request, remove_user_from_group, group_exists

    @app.route('/api/profile/join_group', methods=['POST'])
    def api_join_group():
        if 'user' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
            
        data = request.json
        group_name = data.get('group_name')
        
        if not group_name or not group_exists(group_name):
            return jsonify({'success': False, 'error': 'Invalid group name'}), 400
            
        user_email = session['user']['email']
        if create_group_request(user_email, group_name):
            return jsonify({'success': True, 'message': f'Request to join {group_name} sent.'})
        else:
            return jsonify({'success': False, 'error': 'Request already exists or failed to create.'})

    @app.route('/api/profile/leave_group', methods=['POST'])
    def api_leave_group():
        if 'user' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
            
        data = request.json
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'success': False, 'error': 'Group name required'}), 400
            
        user_email = session['user']['email']
        if remove_user_from_group(user_email, group_name):
            return jsonify({'success': True, 'message': f'Left {group_name}.'})
        else:
            return jsonify({'success': False, 'error': 'Failed to leave group.'})
