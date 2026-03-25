"""
Basic routes (home, login page, profile)
"""
import os, json
from flask import render_template, redirect, url_for, session, flash, send_from_directory, jsonify, request, abort
from flask import Blueprint

basic_bp = Blueprint('basic', __name__, template_folder='templates', static_folder='static')

SLIDESHOW_DIR = os.path.join(os.path.dirname(__file__), 'slideshow')
SLIDESHOW_CONFIG = os.path.join(SLIDESHOW_DIR, 'slideshow_config.json')


@basic_bp.route('/slideshow/image/<filename>')
def slideshow_image(filename):
    """Serve images from the slideshow folder."""
    filename = os.path.basename(filename)  # prevent path traversal
    return send_from_directory(SLIDESHOW_DIR, filename)


@basic_bp.route('/api/slideshow')
def get_slideshow():
    """Return slideshow config as JSON, filtering enabled + existing slides."""
    if not os.path.exists(SLIDESHOW_CONFIG):
        return jsonify({'slides': [], 'interval': 6500, 'transition': 500})
    with open(SLIDESHOW_CONFIG, 'r', encoding='utf-8') as f:
        config = json.load(f)
    slides = []
    for slide in config.get('slides', []):
        if not slide.get('enabled', True):
            continue
        filepath = os.path.join(SLIDESHOW_DIR, slide['filename'])
        if os.path.exists(filepath):
            slides.append({
                'url': url_for('basic.slideshow_image', filename=slide['filename']),
                'title': slide.get('title', ''),
                'caption': slide.get('caption', ''),
                'author': slide.get('author', ''),
                'fit': bool(slide.get('fit', True)),
            })
    return jsonify({
        'slides': slides,
        'interval': config.get('interval', 6500),
        'transition': config.get('transition', 500),
    })


@basic_bp.route('/')
def home():
    return render_template('home.html', current_path='/')

@basic_bp.route('/login')
def login():
    return render_template('login.html', current_path='/login')

@basic_bp.route('/profile')
def profile():
    if 'user' not in session:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('basic.login'))
    
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

@basic_bp.route('/api/profile/join_group', methods=['POST'])
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

@basic_bp.route('/api/profile/leave_group', methods=['POST'])
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
