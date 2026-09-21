"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — permissions (split from object_routes.py)."""
import urllib.parse
from flask import session, request, jsonify
from app.db import get_tns_db_connection
from app.db.auth import (
    get_all_groups,
    get_object_permissions,
    grant_object_permission,
    revoke_object_permission,
    get_source_permissions,
    set_source_permissions_batch,
    get_default_source_permissions,
)
from . import objects_bp
from app.core.auth import admin_required, login_required


# ===============================================================================
# SOURCE PERMISSIONS (per telescope/instrument access control)
# ===============================================================================
@objects_bp.route('/api/object/<object_name>/sources')
@admin_required
def get_object_sources(object_name):
    """Return unique phot/spec sources for an object."""
    object_name = urllib.parse.unquote(object_name)
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT COALESCE(p.source, 'Unknown') as src "
            "FROM transient.photometry p "
            "JOIN transient.objects o ON p.obj_id = o.obj_id "
            "WHERE o.name ILIKE %s ORDER BY src",
            (object_name,)
        )
        phot_sources = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT DISTINCT COALESCE(s.source, 'Unknown') as src "
            "FROM transient.spectroscopy s "
            "JOIN transient.objects o ON s.obj_id = o.obj_id "
            "WHERE o.name ILIKE %s ORDER BY src",
            (object_name,)
        )
        spec_sources = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({'success': True, 'phot_sources': phot_sources, 'spec_sources': spec_sources})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/source-permissions')
@admin_required
def get_source_permissions_api(object_name):
    object_name = urllib.parse.unquote(object_name)
    try:
        raw_perms = get_source_permissions(object_name, 'phot') + get_source_permissions(object_name, 'spec')
        # Convert per-object allowed_groups INT[] → group names
        raw_defaults = get_default_source_permissions()
        groups_dict = get_all_groups()
        id_to_name = {info.get('group_id'): name for name, info in groups_dict.items()}

        perms = []
        for p in raw_perms:
            ag = p.get('allowed_groups')  # None = login override, [] = blocked, [ids] = specific groups
            if ag is None:
                ag_names = None
            else:
                ag_names = [id_to_name[gid] for gid in ag if gid in id_to_name]
            perms.append({**p, 'allowed_groups': ag_names})

        defaults = []
        for p in raw_defaults:
            perm = p.get('permission', 'login')
            group_names = [id_to_name[gid] for gid in (p.get('groups') or []) if gid in id_to_name]
            if perm == 'public':
                defaults.append({'source': p['source'], 'permission': 'public', 'allowed_groups': None})
            elif perm == 'login':
                defaults.append({'source': p['source'], 'permission': 'login', 'allowed_groups': None})
            else:  # 'groups'
                defaults.append({'source': p['source'], 'permission': 'groups', 'allowed_groups': group_names})
        return jsonify({'success': True, 'permissions': perms, 'defaults': defaults})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/source-permissions/batch', methods=['POST'])
@admin_required
def set_source_permissions_batch_api(object_name):
    object_name = urllib.parse.unquote(object_name)
    data = request.get_json()
    if not data or 'permissions' not in data:
        return jsonify({'error': 'Missing permissions list'}), 400
    try:
        # Build name→id map for group name conversion
        groups_dict = get_all_groups()
        name_to_id = {name: info.get('group_id') for name, info in groups_dict.items()}

        perms_by_type = {}
        for p in data['permissions']:
            dt = p.get('data_type', 'phot')
            # Convert allowed_groups names → INT[] IDs
            # None means public/login (no group restriction)
            # [] means blocked (empty list kept as [])
            # [names...] means specific groups
            ag_names_raw = p.get('allowed_groups')
            if ag_names_raw is None:
                ag_ids_final = None
            else:
                ag_ids_final = [name_to_id[n] for n in ag_names_raw if n in name_to_id]
            perms_by_type.setdefault(dt, []).append({
                **p,
                'allowed_groups': ag_ids_final
            })
        for dt, perms in perms_by_type.items():
            set_source_permissions_batch(object_name, dt, perms)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===============================================================================
# PERMISSIONS
# ===============================================================================
@objects_bp.route('/api/groups')
@login_required(error='Access denied', status=403)
def get_groups_api():

    try:
        groups_dict = get_all_groups()
        # get_all_groups returns dict[name→info]; JS expects a list
        groups_list = [{'name': name, **info} for name, info in groups_dict.items()]
        return jsonify({
            'success': True,
            'groups': groups_list
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions')
@login_required(error='Access denied', status=403)
def get_object_permissions_api(object_name):
    
    try:
        object_name = urllib.parse.unquote(object_name)
        permissions = get_object_permissions(object_name)
        return jsonify({
            'success': True,
            'permissions': permissions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions', methods=['POST'])
@admin_required
def add_object_permission_api(object_name):
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if grant_object_permission(object_name, group_name, session['user']['email']):
            return jsonify({
                'success': True,
                'message': 'Permission granted successfully'
            })
        else:
            return jsonify({'error': 'Failed to grant permission (maybe already exists)'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@objects_bp.route('/api/object/<object_name>/permissions', methods=['DELETE'])
@admin_required
def remove_object_permission_api(object_name):
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        group_name = data.get('group_name')
        
        if not group_name:
            return jsonify({'error': 'Group name is required'}), 400
        
        if revoke_object_permission(object_name, group_name):
            return jsonify({
                'success': True,
                'message': 'Permission revoked successfully'
            })
        else:
            return jsonify({'error': 'Permission not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
