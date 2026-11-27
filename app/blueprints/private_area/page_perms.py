"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — page_perms (split from private_area_routes.py)."""
from flask import request, jsonify
from app.db.auth import set_page_groups
from . import private_area_bp
from . import lab_pages
from .helpers import (PAGE_LEVELS, _PRIVATE_PAGES, _PRIVATE_PAGE_LABELS, _get_page_extra_groups, is_admin_user,
                      page_level, set_page_level)

# 'lab' (the whole Lab section) is set like a page, with the levels of lab_pages.LEVELS (no 'Same as Lab').
_KEYS = [lab_pages.LAB_KEY] + list(_PRIVATE_PAGES)


def _valid_level(page, level):
    return level in (lab_pages.LEVELS if page == lab_pages.LAB_KEY else PAGE_LEVELS)


# ===============================================================================
# PRIVATE AREA
# ===============================================================================

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['GET'])
def api_get_private_page_perms():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    perms = {p: _get_page_extra_groups(p) for p in _KEYS}
    nav = [{'key': gk, 'label': gl, 'pages': [{'key': k, 'label': vl, 'href': h} for h, vl, k in views]}
           for gk, _i, gl, views in lab_pages.LAB_NAV]
    return jsonify({'success': True, 'perms': perms, 'pages': _PRIVATE_PAGES, 'labels': _PRIVATE_PAGE_LABELS,
                    'nav': nav, 'levels': {p: page_level(p) for p in _KEYS}, 'level_labels': PAGE_LEVELS,
                    'lab_level_labels': lab_pages.LEVELS})


@private_area_bp.route('/api/admin/private_area/page_level', methods=['POST'])
def api_set_private_page_level():
    """Who opens a private page besides its added groups: {"page": key, "level": "member" | "admin"}."""
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    page, level = str(data.get('page', '')).strip(), str(data.get('level', '')).strip()
    if page not in _KEYS or not _valid_level(page, level):
        return jsonify({'error': 'Invalid page or level'}), 400
    if set_page_level(page, level):
        return jsonify({'success': True, 'level': level})
    return jsonify({'error': 'Failed to save'}), 500

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['POST'])
def api_add_private_page_perm():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    page = str(data.get('page', '')).strip()
    group_name = str(data.get('group_name', '')).strip()
    if page not in _KEYS or not group_name:
        return jsonify({'error': 'Invalid page or group'}), 400
    current = _get_page_extra_groups(page)
    if group_name not in current:
        current.append(group_name)
    if set_page_groups(page, current):
        lab_pages.forget_cached()
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save'}), 500

@private_area_bp.route('/api/admin/private_area/page_perms', methods=['DELETE'])
def api_remove_private_page_perm():
    if not is_admin_user():
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True) or {}
    page = str(data.get('page', '')).strip()
    group_name = str(data.get('group_name', '')).strip()
    if page not in _KEYS or not group_name:
        return jsonify({'error': 'Invalid page or group'}), 400
    current = [g for g in _get_page_extra_groups(page) if g != group_name]
    if set_page_groups(page, current):
        lab_pages.forget_cached()
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save'}), 500
