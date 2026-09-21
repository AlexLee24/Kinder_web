"""JSON API used by the marshal/object pages and external API-key clients — keys (split from web_api_routes.py)."""
from flask import request, jsonify
from app.db.auth import get_user_by_api_key
from . import web_api_bp


# ===============================================================================
# OBJECT MANAGEMENT API
# ===============================================================================
@web_api_bp.route('/api/generate_key', methods=['POST'])
def generate_key():
    return jsonify({
        'success': False,
        'error': 'Self-service key generation is disabled. Please request a key from your profile page; an admin will issue it.'
    }), 403

@web_api_bp.route('/api/test', methods=['GET', 'POST'])
def api_test():
    # Authentication via header
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return jsonify({'success': False, 'error': 'Missing API Key in headers (X-API-Key)'}), 401
        
    user = get_user_by_api_key(api_key)
    
    if not user:
        return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
    # Return testing information
    return jsonify({
        'success': True,
        'message': 'API Authentication successful!',
        'user': {
            'name': user.get('name'),
            'email': user.get('email'),
            'role': user.get('role', 'user'),
            'is_admin': user.get('is_admin', False),
            'groups': user.get('groups', [])
        }
    })
