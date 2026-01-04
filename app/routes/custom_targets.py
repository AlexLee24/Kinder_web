from flask import render_template, request, jsonify, session, redirect, url_for
from modules.postgres_database import get_db_connection
from modules.database import get_setting, set_setting, get_users, get_groups
from functools import wraps
import json

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or not session['user'].get('is_admin'):
            # For API requests, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Access denied. Admin privileges required.'}), 403
            # For page requests, redirect or show error
            return render_template('error.html', message="Access Denied: Admin privileges required."), 403
        return f(*args, **kwargs)
    return decorated_function

def register_custom_targets_routes(app):
    @app.route('/custom_targets')
    def custom_targets_page():
        if 'user' not in session:
            return redirect(url_for('login'))
            
        user = session['user']
        is_admin = user.get('is_admin', False)
        
        # Check access
        if not is_admin:
            # Get permissions
            allowed_users = json.loads(get_setting('custom_targets_allowed_users', '[]'))
            allowed_groups = json.loads(get_setting('custom_targets_allowed_groups', '[]'))
            
            # Check if user is explicitly allowed
            if user['email'] in allowed_users:
                pass # Allowed
            else:
                # Check if user is in an allowed group
                user_groups = user.get('groups', [])
                if not any(group in allowed_groups for group in user_groups):
                    return render_template('error.html', message="Access Denied: You do not have permission to view this page."), 403
            
        return render_template('custom_targets.html', current_path='/custom_targets', is_admin=is_admin)

    @app.route('/api/custom_targets/permissions', methods=['GET'])
    @admin_required
    def get_permissions():
        try:
            users = get_users()
            groups = get_groups()
            
            allowed_users = json.loads(get_setting('custom_targets_allowed_users', '[]'))
            allowed_groups = json.loads(get_setting('custom_targets_allowed_groups', '[]'))
            
            # Format users for frontend
            users_list = []
            for email, u in users.items():
                users_list.append({
                    'email': email,
                    'name': u['name'],
                    'is_admin': u.get('is_admin', False)
                })
                
            # Format groups
            groups_list = list(groups.keys())
            
            return jsonify({
                'success': True,
                'users': users_list,
                'groups': groups_list,
                'allowed_users': allowed_users,
                'allowed_groups': allowed_groups
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/custom_targets/permissions', methods=['POST'])
    @admin_required
    def save_permissions():
        try:
            data = request.get_json()
            allowed_users = data.get('allowed_users', [])
            allowed_groups = data.get('allowed_groups', [])
            
            set_setting('custom_targets_allowed_users', json.dumps(allowed_users))
            set_setting('custom_targets_allowed_groups', json.dumps(allowed_groups))
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/custom_targets', methods=['GET'])
    def get_custom_targets():
        # Allow read access to everyone (or restrict if needed, but planner needs it)
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, name, ra, declination, mag, priority, note, 
                           is_auto_exposure, filters, exposures, counts, created_at 
                    FROM custom_targets 
                    ORDER BY created_at DESC
                """)
                rows = cursor.fetchall()
                
                targets = []
                for row in rows:
                    targets.append({
                        'id': row[0],
                        'name': row[1],
                        'ra': row[2],
                        'dec': row[3],
                        'mag': row[4],
                        'priority': row[5],
                        'note': row[6],
                        'is_auto_exposure': row[7],
                        'filters': row[8],
                        'exposures': row[9],
                        'counts': row[10],
                        'created_at': row[11].isoformat() if row[11] else None
                    })
                
                return jsonify({'success': True, 'targets': targets})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/custom_targets/add', methods=['POST'])
    @admin_required
    def add_custom_target():
        try:
            data = request.get_json()
            name = data.get('name')
            ra = data.get('ra')
            dec = data.get('dec')
            mag = data.get('mag')
            priority = data.get('priority', 'Normal')
            note = data.get('note', '')
            
            is_auto = data.get('is_auto_exposure', True)
            filters = data.get('filters', '')
            exposures = data.get('exposures', '')
            counts = data.get('counts', '')
            
            if not name or not ra or not dec:
                return jsonify({'success': False, 'error': 'Name, RA, and Dec are required'}), 400
                
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO custom_targets 
                       (name, ra, declination, mag, priority, note, is_auto_exposure, filters, exposures, counts) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                       RETURNING id""",
                    (name, ra, dec, mag, priority, note, is_auto, filters, exposures, counts)
                )
                new_id = cursor.fetchone()[0]
                conn.commit()
                
            return jsonify({'success': True, 'id': new_id})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/custom_targets/delete/<int:target_id>', methods=['DELETE'])
    @admin_required
    def delete_custom_target(target_id):
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM custom_targets WHERE id = %s", (target_id,))
                conn.commit()
                
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
