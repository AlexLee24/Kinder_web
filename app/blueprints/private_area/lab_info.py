"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — lab_info (split from private_area_routes.py)."""
import os
from urllib.parse import urlparse
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
    # Member directory is used by the Daily Trigger page (observer dropdown) and Lab Info.
    if not (can_access_page('daily_trigger') or can_access_page('greatlab_info')):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    users = get_users()
    members = []
    for email, u in users.items():
        if u.get('role') in ['user', 'admin', 'guest']:
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

_GL_MAX_SECTIONS = 100
_GL_MAX_CARDS = 200
_GL_MAX_LINKS = 500
_GL_MAX_STR = 2000


def _gl_str(value, field, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise ValueError(f'{field} must be a string')
    if len(value) > _GL_MAX_STR:
        raise ValueError(f'{field} is too long')
    if required and not value.strip():
        raise ValueError(f'{field} is required')
    return value


def _gl_url(value):
    url = _gl_str(value, 'link url').strip()
    if not url or url.startswith('#') or (url.startswith('/') and not url.startswith('//')):
        return url or '#'
    if urlparse(url).scheme.lower() not in ('http', 'https') or any(ord(ch) < 32 for ch in url):
        raise ValueError('link url must start with http:// or https://')
    return url


def _validate_greatlab_links(data):
    """Validate/normalise the Lab Info links structure: [{title, cards: [{title, links: [{url, title, desc}]}]}].

    Returns (clean_data, error_message).
    """
    try:
        if not isinstance(data, list) or len(data) > _GL_MAX_SECTIONS:
            raise ValueError('data must be a list of sections')
        clean = []
        for section in data:
            if not isinstance(section, dict):
                raise ValueError('each section must be an object')
            cards = section.get('cards', [])
            if not isinstance(cards, list) or len(cards) > _GL_MAX_CARDS:
                raise ValueError('section cards must be a list')
            clean_cards = []
            for card in cards:
                if not isinstance(card, dict):
                    raise ValueError('each card must be an object')
                links = card.get('links', [])
                if not isinstance(links, list) or len(links) > _GL_MAX_LINKS:
                    raise ValueError('card links must be a list')
                clean_links = []
                for link in links:
                    if not isinstance(link, dict):
                        raise ValueError('each link must be an object')
                    clean_links.append({
                        'url': _gl_url(link.get('url')),
                        'title': _gl_str(link.get('title'), 'link title'),
                        'desc': _gl_str(link.get('desc'), 'link desc'),
                    })
                clean_cards.append({'title': _gl_str(card.get('title'), 'card title'), 'links': clean_links})
            clean.append({'title': _gl_str(section.get('title'), 'section title'), 'cards': clean_cards})
        return clean, None
    except ValueError as exc:
        return None, str(exc)


def get_greatlab_links_path():
    return os.path.join(private_area_bp.root_path, 'data', 'greatlab_links.json')

@private_area_bp.route('/api/greatlab_links', methods=['GET', 'POST'])
@login_required
def api_greatlab_links():
    if not can_access_page('greatlab_info'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

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
            
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'success': False, 'error': 'Invalid JSON body'}), 400
        data, err = _validate_greatlab_links(body.get('data', []))
        if err:
            return jsonify({'success': False, 'error': err}), 400
        os.makedirs(os.path.dirname(links_path), exist_ok=True)

        tmp_path = f"{links_path}.tmp.{os.getpid()}"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, links_path)

        return jsonify({'success': True})
