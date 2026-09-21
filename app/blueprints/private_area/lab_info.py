"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — lab_info (split from private_area_routes.py)."""
import os
from flask import render_template, redirect, url_for, session, flash, request, jsonify
from app.db.auth import get_users
import json
from . import private_area_bp
from .helpers import can_access_page
from app.core.auth import login_required


@private_area_bp.route('/greatlab_info')
def greatlab_info():
    if 'user' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('basic.login'))

    if not can_access_page('greatlab_info'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))

    return render_template('greatlab_info.html', current_path='/greatlab_info')

@private_area_bp.route('/api/members', methods=['GET'])
@login_required
def api_members():
    
    users = get_users()
    members = []
    for email, u in users.items():
        if u.get('role') in ['user', 'admin', 'guest'] or True:
            members.append({
                'email': email,
                'name': u.get('name', ''),
                'picture': u.get('picture', '')
            })
    # Sort by name
    members.sort(key=lambda x: x['name'])
    return jsonify({'success': True, 'members': members})

# ===============================================================================
# GREAT LAB INFO
# ===============================================================================

def get_greatlab_links_path():
    return os.path.join(private_area_bp.root_path, 'data', 'greatlab_links.json')

@private_area_bp.route('/api/greatlab_links', methods=['GET', 'POST'])
@login_required
def api_greatlab_links():
        
    links_path = get_greatlab_links_path()
    
    if request.method == 'GET':
        if os.path.exists(links_path):
            with open(links_path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    return jsonify({'success': True, 'data': data})
                except json.JSONDecodeError:
                    pass
        
        # Default preset if file not found or corrupted
        default_data = [
            {
                "title": "Telescopes & Facilities",
                "cards": [
                    {
                        "title": "Lulin Observatory",
                        "links": [
                            {
                                "url": "https://www.lulin.ncu.edu.tw/weather/",
                                "title": "Lulin weather/status",
                                "desc": "NCU Lulin Observatory"
                            }
                        ]
                    }
                ]
            }
        ]
        return jsonify({'success': True, 'data': default_data})
        
    elif request.method == 'POST':
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if not (is_great_lab or is_admin):
            return jsonify({'error': 'Forbidden. GREAT Lab members only.'}), 403
            
        data = request.json.get('data', [])
        os.makedirs(os.path.dirname(links_path), exist_ok=True)
        
        with open(links_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        return jsonify({'success': True})
