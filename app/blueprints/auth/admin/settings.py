"""Admin panel actions — settings (split from admin_routes.py)."""
from flask import request, jsonify
from app.db.auth import (
    get_groups,
    set_setting,
    get_default_source_permissions,
    set_default_source_permissions_batch,
)
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp


@admin_bp.route('/admin/settings/save', methods=['POST'])
@admin_required
def save_settings():
        
    data = request.get_json()
    key = data.get('key')
    value = data.get('value')
    
    if not key:
        return jsonify({'error': 'Key is required'}), 400
        
    if set_setting(key, value):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to save setting'}), 500

# ===============================================================================
# DEFAULT SOURCE PERMISSIONS
# ===============================================================================

@admin_bp.route('/admin/default-source-permissions')
@admin_required
def get_default_source_perms():
    raw = get_default_source_permissions()
    groups_dict = get_groups()
    id_to_name = {info.get('group_id'): name for name, info in groups_dict.items()}

    def _to_js(p):
        perm = p.get('permission', 'public')
        group_ids = p.get('groups') or []
        group_names = [id_to_name[gid] for gid in group_ids if gid in id_to_name]
        if perm == 'public':
            return {'source_name': p['source'], 'is_public': True, 'allowed_groups': None}
        elif perm == 'login':
            return {'source_name': p['source'], 'is_public': False, 'allowed_groups': None}
        else:  # 'groups' — empty array = blocked, non-empty = specific groups
            return {'source_name': p['source'], 'is_public': False, 'allowed_groups': group_names}

    return jsonify({'success': True, 'permissions': [_to_js(p) for p in raw]})

@admin_bp.route('/admin/default-source-permissions', methods=['POST'])
@admin_required
def save_default_source_perms():
    data = request.get_json(silent=True) or {}
    perms_list = data.get('permissions', [])
    if not isinstance(perms_list, list):
        return jsonify({'error': 'Invalid payload'}), 400

    groups_dict = get_groups()
    name_to_id = {name: info.get('group_id') for name, info in groups_dict.items()}

    def _to_db(p):
        is_public = bool(p.get('is_public', False))
        allowed = p.get('allowed_groups')  # None | [] | [names]
        if is_public:
            return {'source': p['source_name'], 'permission': 'public', 'groups': []}
        elif allowed is None:
            return {'source': p['source_name'], 'permission': 'login', 'groups': []}
        else:
            ids = [name_to_id[n] for n in (allowed or []) if n in name_to_id]
            return {'source': p['source_name'], 'permission': 'groups', 'groups': ids}

    set_default_source_permissions_batch([_to_db(p) for p in perms_list])
    return jsonify({'success': True})

@admin_bp.route('/admin/sources/search')
@admin_required
def search_sources():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify({'success': True, 'sources': []})
    try:
        from app.db import get_db_connection as tns_conn
        with tns_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT DISTINCT source FROM transient.photometry
                       WHERE source ILIKE %s AND source IS NOT NULL
                       ORDER BY source LIMIT 20''',
                    (f'%{q}%',)
                )
                sources = [row[0] for row in cursor.fetchall()]
        return jsonify({'success': True, 'sources': sources})
    except Exception as e:
        logger.error(f'sources/search error: {e}')
        return jsonify({'success': True, 'sources': []})

@admin_bp.route('/admin/sources/all')
@admin_required
def all_sources():
    """Return all distinct photometry + spectroscopy sources for the admin dropdown."""
    try:
        from app.db import get_db_connection as tns_conn
        with tns_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT DISTINCT source FROM transient.photometry
                       WHERE source IS NOT NULL
                       UNION
                       SELECT DISTINCT source FROM transient.spectroscopy
                       WHERE source IS NOT NULL
                       ORDER BY source'''
                )
                sources = [row[0] for row in cursor.fetchall()]
        return jsonify({'success': True, 'sources': sources})
    except Exception as e:
        logger.error(f'sources/all error: {e}')
        return jsonify({'success': True, 'sources': []})
