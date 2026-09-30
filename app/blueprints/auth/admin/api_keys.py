"""Admin panel actions — api_keys (split from admin_routes.py).

Keys are stored hashed; a newly issued key is returned ONCE in the JSON response
(``api_key``) so the admin UI can show it, and is never retrievable again."""
from flask import request, jsonify
from app.db.auth import generate_api_key_for_user, get_user, revoke_api_key
from . import admin_bp
from .helpers import audit, privileged_target_denied
from app.core.auth import admin_required


@admin_bp.route('/admin/api-key/issue', methods=['POST'])
@admin_required
def admin_issue_api_key():
    email = str((request.get_json(silent=True) or {}).get('email') or '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400
    target = get_user(email)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    # The issuing admin sees the key, i.e. could act as that account via the API.
    denied = privileged_target_denied(email, "issue an API key for another admin")
    if denied:
        return denied
    new_key = generate_api_key_for_user(email)
    if not new_key:
        return jsonify({'error': 'Failed to generate key'}), 500
    audit('api_key_issue', email, f"replaced={bool(target.get('has_api_key'))} hint={new_key[-4:]}")
    return jsonify({
        'success': True,
        'message': f'API key issued for {email}',
        'api_key': new_key,
        'api_key_hint': new_key[-4:],
    })

@admin_bp.route('/admin/api-key/revoke', methods=['POST'])
@admin_required
def admin_revoke_api_key():
    email = str((request.get_json(silent=True) or {}).get('email') or '').strip()
    if not email:
        return jsonify({'error': 'email required'}), 400
    ok = revoke_api_key(email)
    if not ok:
        return jsonify({'error': 'User not found'}), 404
    audit('api_key_revoke', email)
    return jsonify({'success': True, 'message': f'API key revoked for {email}'})
