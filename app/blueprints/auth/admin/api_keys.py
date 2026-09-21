"""Admin panel actions — api_keys (split from admin_routes.py)."""
from flask import request, jsonify
from app.db.auth import generate_api_key_for_user, revoke_api_key
from . import admin_bp
from app.core.auth import admin_required


@admin_bp.route('/admin/api-key/issue', methods=['POST'])
@admin_required
def admin_issue_api_key():
    email = (request.get_json(silent=True) or {}).get('email', '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400
    new_key = generate_api_key_for_user(email)
    if not new_key:
        return jsonify({'error': 'Failed to generate key or user not found'}), 500
    return jsonify({'success': True, 'message': f'API key issued for {email}'})

@admin_bp.route('/admin/api-key/revoke', methods=['POST'])
@admin_required
def admin_revoke_api_key():
    email = (request.get_json(silent=True) or {}).get('email', '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400
    ok = revoke_api_key(email)
    if not ok:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'success': True, 'message': f'API key revoked for {email}'})
