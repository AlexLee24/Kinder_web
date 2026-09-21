"""Admin panel actions — groups (split from admin_routes.py)."""
from flask import session, request, jsonify
from app.db.auth import (
    user_exists,
    create_group,
    delete_group,
    group_exists,
    add_user_to_group,
    remove_user_from_group,
    user_in_group,
)
from . import admin_bp
from .helpers import update_user_session_groups
from app.core.auth import admin_required


# ===============================================================================
# GROUP MANAGEMENT
# ===============================================================================
@admin_bp.route('/admin/create-group', methods=['POST'])
@admin_required
def create_group_route():
    
    data = request.get_json()
    group_name = data.get('name', '').strip()
    group_description = data.get('description', '').strip()
    
    if not group_name:
        return jsonify({'error': 'Group name is required'}), 400
    
    if group_exists(group_name):
        return jsonify({'error': 'Group already exists'}), 400
    
    if create_group(group_name, group_description, session['user']['email']):
        return jsonify({'success': True, 'message': 'Group created successfully'})
    else:
        return jsonify({'error': 'Failed to create group'}), 500

@admin_bp.route('/admin/delete-group', methods=['POST'])
@admin_required
def delete_group_route():
    
    data = request.get_json()
    group_name = data.get('group_name')
    
    if not group_name:
        return jsonify({'error': 'Group name is required'}), 400
    
    if not group_exists(group_name):
        return jsonify({'error': 'Group does not exist'}), 400
    
    if delete_group(group_name):
        return jsonify({'success': True, 'message': 'Group deleted successfully'})
    else:
        return jsonify({'error': 'Failed to delete group'}), 500

# ===============================================================================
# GROUP MEMBERSHIP MANAGEMENT
# ===============================================================================
@admin_bp.route('/admin/add-to-group', methods=['POST'])
@admin_required
def add_user_to_group_route():
    
    data = request.get_json()
    user_email = data.get('user_email')
    group_name = data.get('group_name')
    
    if not user_email or not group_name:
        return jsonify({'error': 'User email and group name are required'}), 400
    
    if not user_exists(user_email):
        return jsonify({'error': 'User does not exist'}), 400
    
    if not group_exists(group_name):
        return jsonify({'error': 'Group does not exist'}), 400
    
    if user_in_group(user_email, group_name):
        return jsonify({'error': 'User is already in this group'}), 400
    
    if add_user_to_group(user_email, group_name):
        update_user_session_groups(user_email)
        return jsonify({'success': True, 'message': 'User added to group successfully'})
    else:
        return jsonify({'error': 'Failed to add user to group'}), 500

@admin_bp.route('/admin/remove-from-group', methods=['POST'])
@admin_required
def remove_user_from_group_route():
    
    data = request.get_json()
    user_email = data.get('user_email')
    group_name = data.get('group_name')
    
    if not user_email or not group_name:
        return jsonify({'error': 'User email and group name are required'}), 400
    
    if not user_exists(user_email) or not group_exists(group_name):
        return jsonify({'error': 'User or group does not exist'}), 400
    
    if remove_user_from_group(user_email, group_name):
        update_user_session_groups(user_email)
        return jsonify({'success': True, 'message': 'User removed from group successfully'})
    else:
        return jsonify({'error': 'Failed to remove user from group'}), 500
