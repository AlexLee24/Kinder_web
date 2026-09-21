"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — page_perms (split from private_area_routes.py)."""
from flask import request, jsonify
from app.db.auth import get_page_groups, set_page_groups
from . import private_area_bp
from .helpers import _PRIVATE_PAGES, _PRIVATE_PAGE_LABELS, _get_page_extra_groups, is_admin_user


# ===============================================================================
# PRIVATE AREA
# ===============================================================================

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['GET'])
def api_get_private_page_perms():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    perms = {p: _get_page_extra_groups(p) for p in _PRIVATE_PAGES}
    return jsonify({'success': True, 'perms': perms, 'pages': _PRIVATE_PAGES, 'labels': _PRIVATE_PAGE_LABELS})

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['POST'])
def api_add_private_page_perm():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    page = str(data.get('page', '')).strip()
    group_name = str(data.get('group_name', '')).strip()
    if page not in _PRIVATE_PAGES or not group_name:
        return jsonify({'error': 'Invalid page or group'}), 400
    current = get_page_groups(page)
    if group_name not in current:
        current.append(group_name)
    if set_page_groups(page, current):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save'}), 500

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['DELETE'])
def api_remove_private_page_perm():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    page = str(data.get('page', '')).strip()
    group_name = str(data.get('group_name', '')).strip()
    if page not in _PRIVATE_PAGES or not group_name:
        return jsonify({'error': 'Invalid page or group'}), 400
    current = [g for g in get_page_groups(page) if g != group_name]
    if set_page_groups(page, current):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save'}), 500
