"""
Calendar routes for the Kinder web application.
"""
import logging
import os
import re
import secrets
import shutil

logger = logging.getLogger(__name__)
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from flask import render_template, redirect, url_for, session, flash, request, jsonify, Response, abort, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from modules.database.auth import get_users, user_exists, get_groups, get_page_groups, set_page_groups



from flask import Blueprint
private_area_bp = Blueprint('private_area', __name__, template_folder='templates', static_folder='static')
"""Register calendar routes with the Flask app"""

tutorials_dir = os.path.join(os.path.dirname(__file__), 'tutorials')
tutorials_env_path = os.path.join(tutorials_dir, '.env')
allowed_image_ext = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

def ensure_tutorials_dir():
    os.makedirs(tutorials_dir, exist_ok=True)

def can_view_documents():
    if 'user' not in session:
        return False
    return can_access_page('documents')

def is_admin_user():
    return 'user' in session and bool(session['user'].get('is_admin', False))

import json

def get_documents_metadata():
    meta_path = os.path.join(tutorials_dir, 'metadata.json')
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'pinned': [], 'order': []}

def save_documents_metadata(metadata):
    ensure_tutorials_dir()
    meta_path = os.path.join(tutorials_dir, 'metadata.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)

def read_documents_env():
    config = {
        'DOCUMENTS_EDITABLE': 'true',
        'IMPORTANT_MESSAGE': ''
    }

    if os.path.exists(tutorials_env_path):
        with open(tutorials_env_path, 'r', encoding='utf-8') as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    return config

def write_documents_env(updates):
    ensure_tutorials_dir()
    config = read_documents_env()
    config.update(updates)
    with open(tutorials_env_path, 'w', encoding='utf-8') as env_file:
        env_file.write(f"DOCUMENTS_EDITABLE={config.get('DOCUMENTS_EDITABLE', 'true')}\n")
        env_file.write(f"IMPORTANT_MESSAGE={config.get('IMPORTANT_MESSAGE', '')}\n")

def documents_editable():
    config = read_documents_env()
    return str(config.get('DOCUMENTS_EDITABLE', 'true')).lower() == 'true'

def sanitize_document_filename(filename):
    safe = secure_filename(filename or '')
    if not safe:
        return None
    if not safe.lower().endswith('.md'):
        safe = f"{safe}.md"
    return safe


def can_view_private_area():
    if 'user' not in session:
        return False
    return session['user'].get('is_great_lab_member', False) or session['user'].get('is_admin', False)


# ---------------------------------------------------------------------------
# Per-page permission helpers
# ---------------------------------------------------------------------------
_PRIVATE_PAGES = ['daily_trigger', 'greatlab_info', 'epessto_support', 'documents']
_PRIVATE_PAGE_LABELS = {
    'daily_trigger': 'Daily Trigger',
    'greatlab_info': 'Lab Info',
    'epessto_support': 'ePessto++ Support',
    'documents': 'Documents',
}


def _get_page_extra_groups(page_key: str) -> list:
    """Return list of extra group names (beyond GREAT_Lab) that can access the page."""
    return get_page_groups(page_key)


def can_access_page(page_key: str) -> bool:
    """Check if the current session user can access the given private page."""
    if 'user' not in session:
        return False
    user = session['user']
    if user.get('is_admin', False) or user.get('is_great_lab_member', False):
        return True
    user_groups = set(user.get('groups', []))
    allowed = set(get_page_groups(page_key))
    return bool(user_groups & allowed)


_EPESSTO_DATE_RE = re.compile(r'^20\d{6}$')
_EPESSTO_ROOM_SESSION_KEY = 'epessto_room_id'
_EPESSTO_ROOM_IDLE_DELETE_HOURS = 24
_EPESSTO_ROOM_LIVE_HOURS = 1


def _get_epessto_upload_root_dir():
    d = os.path.join(private_area_bp.root_path, 'data', 'epessto_uploads')
    os.makedirs(d, exist_ok=True)
    return d


def _get_epessto_upload_dir(room_id=None):
    if room_id:
        d = os.path.join(_get_epessto_upload_root_dir(), 'rooms', room_id, 'files')
    else:
        d = os.path.join(_get_epessto_upload_root_dir(), 'files')
    os.makedirs(d, exist_ok=True)
    return d


def _get_epessto_image_dir(room_id=None):
    if room_id:
        d = os.path.join(_get_epessto_upload_root_dir(), 'rooms', room_id, 'images')
    else:
        d = os.path.join(_get_epessto_upload_root_dir(), 'images')
    os.makedirs(d, exist_ok=True)
    return d


def _get_epessto_sessions_path():
    return os.path.join(private_area_bp.root_path, 'data', 'epessto_sessions.json')


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_epessto_actor():
    user = session.get('user') or {}
    actor = str(user.get('email') or user.get('name') or user.get('username') or 'unknown').strip()
    return actor or 'unknown'


def _get_epessto_user_identity():
    user = session.get('user') or {}
    email = str(user.get('email') or user.get('name') or user.get('username') or '').strip().lower()
    display_name = str(user.get('name') or user.get('email') or user.get('username') or 'unknown').strip()
    is_admin = bool(user.get('is_admin', False))
    return {
        'email': email,
        'display_name': display_name,
        'is_admin': is_admin,
    }


def _parse_utc_iso(iso_text):
    try:
        if not iso_text:
            return None
        return datetime.fromisoformat(str(iso_text).replace('Z', '+00:00'))
    except Exception:
        return None


def _new_epessto_room(password, room_name, created_by):
    now_iso = _utc_now_iso()
    actor = str(created_by or 'unknown')
    return {
        'room_name': str(room_name or '').strip(),
        'password_hash': generate_password_hash(str(password or '')),
        'created_by': actor,
        'updated_by': actor,
        'invite_token': secrets.token_urlsafe(24),
        'members': {
            actor.lower(): {
                'email': actor.lower(),
                'display_name': actor,
                'is_admin': bool(session.get('user', {}).get('is_admin', False)),
                'joined_at': now_iso,
                'last_seen': now_iso,
            }
        },
        'kicked_users': [],
        'created_at': now_iso,
        'updated_at': now_iso,
        'batches': [],
        'target_state': {}
    }


def _load_epessto_store():
    path = _get_epessto_sessions_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {'rooms': {}}

                # Backward compatible migration from old single-room shape.
                if 'rooms' not in data:
                    migrated = {
                        'rooms': {
                            'legacy': {
                                'room_name': 'Legacy Room',
                                'password_hash': '',
                                'created_by': 'legacy',
                                'updated_by': 'legacy',
                                'invite_token': secrets.token_urlsafe(24),
                                'members': {},
                                'kicked_users': [],
                                'created_at': _utc_now_iso(),
                                'updated_at': _utc_now_iso(),
                                'batches': data.get('batches', []) if isinstance(data.get('batches'), list) else [],
                                'target_state': data.get('target_state', {}) if isinstance(data.get('target_state'), dict) else {}
                            }
                        }
                    }
                    return migrated

                rooms = data.get('rooms', {})
                if not isinstance(rooms, dict):
                    rooms = {}
                normalized_rooms = {}
                for room_id, room in rooms.items():
                    if not isinstance(room, dict):
                        continue
                    members = room.get('members', {})
                    if not isinstance(members, dict):
                        members = {}
                    normalized_members = {}
                    for mk, mv in members.items():
                        if not isinstance(mv, dict):
                            continue
                        mem_email = str(mv.get('email', mk) or mk).strip().lower()
                        if not mem_email:
                            continue
                        normalized_members[mem_email] = {
                            'email': mem_email,
                            'display_name': str(mv.get('display_name') or mem_email),
                            'is_admin': bool(mv.get('is_admin', False)),
                            'joined_at': str(mv.get('joined_at') or _utc_now_iso()),
                            'last_seen': str(mv.get('last_seen') or _utc_now_iso()),
                        }

                    kicked_users = room.get('kicked_users', [])
                    if not isinstance(kicked_users, list):
                        kicked_users = []
                    kicked_users = [str(x).strip().lower() for x in kicked_users if str(x).strip()]

                    normalized_rooms[str(room_id)] = {
                        'room_name': str(room.get('room_name', room_id) or room_id),
                        'password_hash': str(room.get('password_hash', '') or ''),
                        'created_by': str(room.get('created_by', 'unknown') or 'unknown'),
                        'updated_by': str(room.get('updated_by', room.get('created_by', 'unknown')) or 'unknown'),
                        'invite_token': str(room.get('invite_token') or secrets.token_urlsafe(24)),
                        'members': normalized_members,
                        'kicked_users': kicked_users,
                        'created_at': str(room.get('created_at') or _utc_now_iso()),
                        'updated_at': str(room.get('updated_at') or _utc_now_iso()),
                        'batches': room.get('batches', []) if isinstance(room.get('batches'), list) else [],
                        'target_state': room.get('target_state', {}) if isinstance(room.get('target_state'), dict) else {}
                    }
                return {'rooms': normalized_rooms}
        except Exception:
            pass
    return {'rooms': {}}


def _save_epessto_store(data):
    path = _get_epessto_sessions_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = data or {}
    if 'rooms' not in data or not isinstance(data.get('rooms'), dict):
        data['rooms'] = {}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _touch_epessto_room(room, actor=None):
    room['updated_at'] = _utc_now_iso()
    if actor is not None:
        room['updated_by'] = str(actor or 'unknown')


def _upsert_epessto_room_member(room):
    ident = _get_epessto_user_identity()
    email = ident['email']
    if not email:
        return
    now_iso = _utc_now_iso()
    room.setdefault('members', {})
    member = room['members'].get(email) or {
        'email': email,
        'display_name': ident['display_name'] or email,
        'is_admin': ident['is_admin'],
        'joined_at': now_iso,
    }
    member['display_name'] = ident['display_name'] or member.get('display_name') or email
    member['is_admin'] = bool(ident['is_admin'])
    member['last_seen'] = now_iso
    room['members'][email] = member


def _epessto_can_manage_members(room):
    ident = _get_epessto_user_identity()
    return bool(ident['is_admin']) or ident['email'] == str(room.get('created_by', '') or '').strip().lower()


def _get_active_epessto_room_id():
    room_id = str(session.get(_EPESSTO_ROOM_SESSION_KEY, '') or '').strip()
    return room_id


def _delete_epessto_room_storage(room_id):
    room_root = os.path.join(_get_epessto_upload_root_dir(), 'rooms', room_id)
    if os.path.isdir(room_root):
        shutil.rmtree(room_root, ignore_errors=True)


def _cleanup_epessto_stale_rooms(store):
    rooms = store.get('rooms', {})
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_EPESSTO_ROOM_IDLE_DELETE_HOURS)
    removed = []
    for room_id, room in list(rooms.items()):
        updated_at = _parse_utc_iso(room.get('updated_at'))
        if not updated_at:
            updated_at = _parse_utc_iso(room.get('created_at'))
        if not updated_at or updated_at < cutoff:
            removed.append(room_id)
    for room_id in removed:
        rooms.pop(room_id, None)
        _delete_epessto_room_storage(room_id)
    return bool(removed)


def _generate_epessto_room_id(existing_ids):
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    for _ in range(50):
        room_id = ''.join(secrets.choice(alphabet) for _ in range(6))
        if room_id not in existing_ids:
            return room_id
    raise RuntimeError('Unable to generate unique room id')


def _collect_epessto_all_files(sessions):
    seen = set()
    all_files = []
    for batch in sessions.get('batches', []):
        for fn in batch.get('files', []):
            if fn not in seen:
                seen.add(fn)
                all_files.append(fn)
    return all_files


def _normalize_epessto_target_state(raw):
    raw = raw or {}
    images = raw.get('images', [])
    if not isinstance(images, list):
        images = []
    normalized_images = []
    for item in images:
        if isinstance(item, dict):
            fn = str(item.get('filename', '') or '').strip()
            if fn:
                normalized_images.append({'filename': fn})

    app_text = str(raw.get('app', '') or '').strip()
    if not app_text:
        app_custom = str(raw.get('app_custom', '') or '').strip()
        app_selected = raw.get('app_selected', [])
        if isinstance(app_selected, list):
            app_text = ', '.join([str(v).strip() for v in app_selected if str(v).strip()])
        if app_custom:
            app_text = (app_text + ', ' + app_custom).strip(', ').strip()

    return {
        'host': str(raw.get('host', '') or ''),
        'z_from_host': str(raw.get('z_from_host', '') or ''),
        'z_estimate': str(raw.get('z_estimate', '') or ''),
        'type': str(raw.get('type', '') or ''),
        'phase': str(raw.get('phase', '') or ''),
        'app': app_text,
        'images': normalized_images,
        'completed': bool(raw.get('completed', False)),
        'discuss': bool(raw.get('discuss', False)),
    }


def _parse_epessto_filename(filename):
    """
    Parse ePessto++ pipeline filename:
        t{TransientName}_{YYYYMMDD}_{grism}_{...}.asci
    Example:
        tAT2026law_20260504_Gr13_Free_slit1.0_1_f.asci
        -> target_name='AT2026law', observed_date=date(2026,5,4), grism='Gr13'
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    # Strip leading 't'/'T' prefix used by ePessto pipeline
    raw = stem[1:] if stem and stem[0].lower() == 't' else stem
    parts = raw.split('_')

    # Find first YYYYMMDD token
    date_idx = None
    observed_date = None
    for i, part in enumerate(parts):
        if _EPESSTO_DATE_RE.match(part):
            try:
                observed_date = datetime.strptime(part, '%Y%m%d').date()
                date_idx = i
                break
            except ValueError:
                continue

    if date_idx is not None and date_idx >= 1:
        target_name = parts[0]
        after = parts[date_idx + 1:]
        grism = after[0] if after else None
        obs_meta = '_'.join(after[1:]) if len(after) > 1 else ''
    else:
        # Fallback for non-standard names
        target_name = parts[0] if parts else stem
        grism = None
        obs_meta = ''

    return {
        'target_name': target_name,
        'observed_date': observed_date,
        'grism': grism or '',
        'obs_meta': obs_meta,
    }


def _serialize_from_filenames(filenames, sessions_data=None):
    """Build targets/summary dict from a list of plain filenames (no FileStorage)."""
    today = datetime.now().date()
    targets = {}
    sessions_data = sessions_data or {'target_state': {}}
    target_state = sessions_data.get('target_state', {})

    for filename in filenames:
        if not filename.lower().endswith('.asci'):
            continue
        parsed = _parse_epessto_filename(filename)
        target_name = parsed['target_name']
        observed_date = parsed['observed_date']
        grism = parsed['grism']
        obs_meta = parsed['obs_meta']
        target_key = target_name.lower().strip()
        is_today = observed_date == today

        if target_key not in targets:
            stored_state = _normalize_epessto_target_state(target_state.get(target_key, {}))
            targets[target_key] = {
                'target_name': target_name,
                'target_key': target_key,
                'is_done_today': bool(stored_state.get('completed', False)),
                'is_discuss': bool(stored_state.get('discuss', False)),
                'dates': set(),
                'grisms': set(),
                'files': [],
                'user_fields': stored_state,
            }

        if observed_date:
            targets[target_key]['dates'].add(observed_date.isoformat())
        if grism:
            targets[target_key]['grisms'].add(grism)
        targets[target_key]['files'].append({
            'filename': filename,
            'observed_on': observed_date.isoformat() if observed_date else None,
            'is_today': is_today,
            'grism': grism,
            'obs_meta': obs_meta,
        })

    target_items = []
    for item in targets.values():
        item['dates'] = sorted(item['dates'])
        item['grisms'] = sorted(item['grisms'])
        item['files'].sort(key=lambda x: x['filename'].lower())
        item['file_count'] = len(item['files'])
        target_items.append(item)

    target_items.sort(key=lambda x: x['target_name'].lower())

    done_count = sum(1 for t in target_items if t['is_done_today'])
    total_count = len(target_items)
    total_files = sum(t['file_count'] for t in target_items)

    # Prune stale target states that are no longer present in session files.
    active_keys = {t['target_key'] for t in target_items}
    stale_keys = [k for k in list(target_state.keys()) if k not in active_keys]
    if stale_keys:
        for key in stale_keys:
            target_state.pop(key, None)
        sessions_data['target_state'] = target_state

    return {
        'summary': {
            'today_date': today.isoformat(),
            'total_files': total_files,
            'done_targets': done_count,
            'total_targets': total_count,
            'remaining_targets': max(total_count - done_count, 0)
        },
        'targets': target_items
    }


def _serialize_epessto_upload(files, room_id, room_data):
    """Save uploaded FileStorage objects to disk, record batch in sessions.json."""
    upload_dir = _get_epessto_upload_dir(room_id)
    batch_id = uuid.uuid4().hex
    batch_files = []

    for file_storage in files:
        filename = (file_storage.filename or '').strip()
        if not filename or not filename.lower().endswith('.asci'):
            continue
        safe_name = secure_filename(filename)
        if not safe_name:
            continue
        save_path = os.path.join(upload_dir, safe_name)
        file_storage.save(save_path)
        batch_files.append(safe_name)

    if batch_files:
        room_data['batches'].append({
            'batch_id': batch_id,
            'uploaded_at': _utc_now_iso(),
            'files': batch_files
        })
        _touch_epessto_room(room_data, _get_epessto_actor())

    all_files = _collect_epessto_all_files(room_data)

    return _serialize_from_filenames(all_files, room_data)

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


@private_area_bp.route('/daily_trigger')
def daily_trigger():
    if 'user' not in session:
        flash('Please log in to access daily trigger.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    
    if not can_access_page('daily_trigger'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    all_groups = []
    if session['user'].get('is_admin', False):
        groups_dict = get_groups()
        all_groups = list(groups_dict.keys())
    
    return render_template('daily_trigger.html', current_path='/daily_trigger', all_groups=all_groups, api_key=session['user'].get('api_key') or '')

@private_area_bp.route('/greatlab_info')
def greatlab_info():
    if 'user' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('basic.login'))

    if not can_access_page('greatlab_info'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))

    return render_template('greatlab_info.html', current_path='/greatlab_info')


@private_area_bp.route('/epessto_support')
def epessto_support_page():
    if 'user' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('basic.login'))

    if not can_access_page('epessto_support'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))

    return render_template('epessto_support.html', current_path='/epessto_support')


def _get_epessto_room_or_response(require_room=True):
    store = _load_epessto_store()
    if _cleanup_epessto_stale_rooms(store):
        _save_epessto_store(store)

    room_id = _get_active_epessto_room_id()
    room = store.get('rooms', {}).get(room_id) if room_id else None

    if room:
        ident = _get_epessto_user_identity()
        kicked = set(str(x).strip().lower() for x in room.get('kicked_users', []))
        if ident['email'] and ident['email'] in kicked:
            session.pop(_EPESSTO_ROOM_SESSION_KEY, None)
            return None, None, None, (jsonify({'error': 'You were removed from this room'}), 403)

        _upsert_epessto_room_member(room)
        _touch_epessto_room(room, _get_epessto_actor())
        _save_epessto_store(store)

    if require_room and (not room_id or not room):
        return None, None, None, (jsonify({'error': 'No room joined'}), 401)
    return store, room_id, room, None


@private_area_bp.route('/api/epessto_support/rooms/live', methods=['GET'])
def api_epessto_support_live_rooms():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, _, _, _ = _get_epessto_room_or_response(require_room=False)
    now = datetime.now(timezone.utc)
    live_cutoff = now - timedelta(hours=_EPESSTO_ROOM_LIVE_HOURS)
    live = []
    for room_id, room in store.get('rooms', {}).items():
        updated_at = _parse_utc_iso(room.get('updated_at')) or _parse_utc_iso(room.get('created_at'))
        if updated_at and updated_at >= live_cutoff:
            live.append({
                'room_id': room_id,
                'room_name': room.get('room_name') or room_id,
                'updated_by': room.get('updated_by') or room.get('created_by') or 'unknown',
                'updated_at': room.get('updated_at')
            })
    live.sort(key=lambda x: x.get('updated_at') or '', reverse=True)
    return jsonify({'success': True, 'rooms': live})


@private_area_bp.route('/api/epessto_support/rooms/create', methods=['POST'])
def api_epessto_support_create_room():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    room_name = str(payload.get('room_name', '') or '').strip()
    password = str(payload.get('password', '') or '')
    if not room_name:
        return jsonify({'error': 'room_name is required'}), 400
    if not password:
        return jsonify({'error': 'password is required'}), 400

    store, _, _, _ = _get_epessto_room_or_response(require_room=False)
    room_id = _generate_epessto_room_id(set(store.get('rooms', {}).keys()))
    actor = _get_epessto_actor()
    store.setdefault('rooms', {})[room_id] = _new_epessto_room(password, room_name, actor)
    _save_epessto_store(store)
    session[_EPESSTO_ROOM_SESSION_KEY] = room_id
    return jsonify({
        'success': True,
        'room_id': room_id,
        'room_name': room_name,
        'invite_token': store['rooms'][room_id].get('invite_token') or ''
    })


@private_area_bp.route('/api/epessto_support/rooms/join', methods=['POST'])
def api_epessto_support_join_room():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    room_id = str(payload.get('room_id', '') or '').strip().upper()
    password = str(payload.get('password', '') or '')
    if not room_id or not password:
        return jsonify({'error': 'room_id and password are required'}), 400

    store, _, _, _ = _get_epessto_room_or_response(require_room=False)
    room = store.get('rooms', {}).get(room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    pwd_hash = str(room.get('password_hash', '') or '')
    valid = False
    if pwd_hash:
        try:
            valid = check_password_hash(pwd_hash, password)
        except Exception:
            valid = False
    else:
        valid = False
    if not valid:
        return jsonify({'error': 'Invalid password'}), 401

    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)
    session[_EPESSTO_ROOM_SESSION_KEY] = room_id
    return jsonify({
        'success': True,
        'room_id': room_id,
        'room_name': room.get('room_name') or room_id,
        'invite_token': room.get('invite_token') or ''
    })


@private_area_bp.route('/api/epessto_support/room/current', methods=['GET'])
def api_epessto_support_current_room():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403
    store, room_id, room, _ = _get_epessto_room_or_response(require_room=False)
    if not room_id or not room:
        return jsonify({'success': True, 'joined': False, 'room_id': None})
    return jsonify({
        'success': True,
        'joined': True,
        'room_id': room_id,
        'room_name': room.get('room_name') or room_id,
        'invite_token': room.get('invite_token') or '',
        'updated_at': room.get('updated_at')
    })


@private_area_bp.route('/api/epessto_support/room/leave', methods=['POST'])
def api_epessto_support_leave_room():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403
    session.pop(_EPESSTO_ROOM_SESSION_KEY, None)
    return jsonify({'success': True})


@private_area_bp.route('/api/epessto_support/room/members', methods=['GET'])
def api_epessto_support_room_members():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    _, _, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    ident = _get_epessto_user_identity()
    can_manage = _epessto_can_manage_members(room)
    owner_email = str(room.get('created_by', '') or '').strip().lower()

    members = []
    for email, member in (room.get('members') or {}).items():
        if not isinstance(member, dict):
            continue
        mem_email = str(email or member.get('email') or '').strip().lower()
        if not mem_email:
            continue
        is_owner = mem_email == owner_email
        is_admin = bool(member.get('is_admin', False))
        is_self = mem_email == ident['email']
        members.append({
            'email': mem_email,
            'display_name': str(member.get('display_name') or mem_email),
            'is_owner': is_owner,
            'is_admin': is_admin,
            'joined_at': member.get('joined_at'),
            'last_seen': member.get('last_seen'),
            'is_self': is_self,
            'can_kick': bool(can_manage and (not is_owner) and (not is_self)),
        })

    members.sort(key=lambda x: (not x['is_owner'], not x['is_admin'], x['display_name'].lower()))
    return jsonify({'success': True, 'can_manage': can_manage, 'members': members})


@private_area_bp.route('/api/epessto_support/room/kick', methods=['POST'])
def api_epessto_support_room_kick():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, _, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    if not _epessto_can_manage_members(room):
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    member_email = str(payload.get('member_email') or '').strip().lower()
    if not member_email:
        return jsonify({'error': 'member_email is required'}), 400

    owner_email = str(room.get('created_by', '') or '').strip().lower()
    self_email = _get_epessto_user_identity().get('email', '')
    if member_email == owner_email:
        return jsonify({'error': 'Cannot kick room creator'}), 400
    if member_email == self_email:
        return jsonify({'error': 'Cannot kick yourself'}), 400

    room.setdefault('members', {})
    room['members'].pop(member_email, None)
    room.setdefault('kicked_users', [])
    if member_email not in room['kicked_users']:
        room['kicked_users'].append(member_email)

    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)
    return jsonify({'success': True})


@private_area_bp.route('/api/epessto_support/rooms/join_by_invite', methods=['POST'])
def api_epessto_support_join_by_invite():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    invite_token = str(payload.get('invite_token') or '').strip()
    if not invite_token:
        return jsonify({'error': 'invite_token is required'}), 400

    store, _, _, _ = _get_epessto_room_or_response(require_room=False)
    matched = None
    for room_id, room in store.get('rooms', {}).items():
        if str(room.get('invite_token') or '') == invite_token:
            matched = (room_id, room)
            break

    if not matched:
        return jsonify({'error': 'Invalid invite link'}), 404

    room_id, room = matched
    ident = _get_epessto_user_identity()
    kicked = set(str(x).strip().lower() for x in room.get('kicked_users', []))
    if ident['email'] in kicked:
        room['kicked_users'] = [x for x in room.get('kicked_users', []) if str(x).strip().lower() != ident['email']]

    _upsert_epessto_room_member(room)
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)

    session[_EPESSTO_ROOM_SESSION_KEY] = room_id
    return jsonify({
        'success': True,
        'room_id': room_id,
        'room_name': room.get('room_name') or room_id,
        'invite_token': room.get('invite_token') or ''
    })


@private_area_bp.route('/api/epessto_support/upload', methods=['POST'])
def api_epessto_support_upload():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, room_id, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    payload = _serialize_epessto_upload(files, room_id, room)
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)
    payload['batches'] = room.get('batches', [])
    return jsonify({'success': True, **payload})


@private_area_bp.route('/api/epessto_support/session', methods=['GET'])
def api_epessto_support_session():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    _, _, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    all_files = _collect_epessto_all_files(room)

    if not all_files:
        return jsonify({'success': True, 'summary': None, 'targets': [], 'batches': []})

    payload = _serialize_from_filenames(all_files, room)
    payload['batches'] = room.get('batches', [])
    return jsonify({'success': True, **payload})


@private_area_bp.route('/api/epessto_support/target_state', methods=['POST'])
def api_epessto_support_target_state():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, _, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    target_key = str(payload.get('target_key', '')).strip().lower()
    if not target_key:
        return jsonify({'error': 'target_key is required'}), 400

    current = _normalize_epessto_target_state(room.get('target_state', {}).get(target_key, {}))

    updates = payload.get('updates') or {}
    if not isinstance(updates, dict):
        return jsonify({'error': 'updates must be an object'}), 400

    if 'host' in updates:
        current['host'] = str(updates.get('host') or '')
    if 'z_from_host' in updates:
        current['z_from_host'] = str(updates.get('z_from_host') or '')
    if 'z_estimate' in updates:
        current['z_estimate'] = str(updates.get('z_estimate') or '')
    if 'type' in updates:
        current['type'] = str(updates.get('type') or '')
    if 'phase' in updates:
        current['phase'] = str(updates.get('phase') or '')
    if 'app' in updates:
        current['app'] = str(updates.get('app') or '')
    if 'completed' in updates:
        current['completed'] = bool(updates.get('completed'))
    if 'discuss' in updates:
        current['discuss'] = bool(updates.get('discuss'))

    # Done/Discuss are mutually exclusive.
    if current.get('completed'):
        current['discuss'] = False
    elif current.get('discuss'):
        current['completed'] = False

    room.setdefault('target_state', {})
    room['target_state'][target_key] = current
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)

    all_files = _collect_epessto_all_files(room)
    if not all_files:
        return jsonify({'success': True, 'summary': None, 'targets': [], 'batches': []})

    data = _serialize_from_filenames(all_files, room)
    data['batches'] = room.get('batches', [])
    return jsonify({'success': True, **data})


@private_area_bp.route('/api/epessto_support/target', methods=['DELETE'])
def api_epessto_support_remove_target():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, room_id, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    target_key = str(payload.get('target_key', '')).strip().lower()
    if not target_key:
        return jsonify({'error': 'target_key is required'}), 400

    upload_dir = _get_epessto_upload_dir(room_id)
    removed = 0

    # Remove target files from batches and disk.
    kept_batches = []
    for batch in room.get('batches', []):
        keep_files = []
        for fn in batch.get('files', []):
            safe = os.path.basename(str(fn or ''))
            if not safe:
                continue
            parsed = _parse_epessto_filename(safe)
            file_target_key = str(parsed.get('target_name', '')).strip().lower()
            if file_target_key == target_key:
                fp = os.path.join(upload_dir, safe)
                if os.path.isfile(fp):
                    os.remove(fp)
                    removed += 1
            else:
                keep_files.append(safe)

        if keep_files:
            batch['files'] = keep_files
            kept_batches.append(batch)

    room['batches'] = kept_batches

    # Remove target-linked images and target state.
    state = room.get('target_state', {}).get(target_key, {})
    images = state.get('images', []) if isinstance(state, dict) else []
    for image in images:
        filename = str(image.get('filename', '')).strip()
        if not filename:
            continue
        fp = os.path.join(_get_epessto_image_dir(room_id), os.path.basename(filename))
        if os.path.isfile(fp):
            os.remove(fp)
            removed += 1

    room.setdefault('target_state', {})
    room['target_state'].pop(target_key, None)
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)

    all_files = _collect_epessto_all_files(room)
    if not all_files:
        return jsonify({'success': True, 'removed': removed, 'summary': None, 'targets': [], 'batches': []})

    data = _serialize_from_filenames(all_files, room)
    data['batches'] = room.get('batches', [])
    return jsonify({'success': True, 'removed': removed, **data})


@private_area_bp.route('/api/epessto_support/target_image', methods=['POST'])
def api_epessto_support_target_image_upload():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, room_id, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    target_key = str(request.form.get('target_key', '')).strip().lower()
    image_file = request.files.get('image')
    if not target_key:
        return jsonify({'error': 'target_key is required'}), 400
    if image_file is None or not image_file.filename:
        return jsonify({'error': 'image is required'}), 400

    ext = os.path.splitext(image_file.filename)[1].lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        return jsonify({'error': 'unsupported image type'}), 400

    current = _normalize_epessto_target_state(room.get('target_state', {}).get(target_key, {}))
    images = current.get('images', [])
    if len(images) >= 4:
        return jsonify({'error': 'max 4 images per target'}), 400

    image_dir = _get_epessto_image_dir(room_id)
    filename = secure_filename(f"{target_key}_{uuid.uuid4().hex}{ext}")
    save_path = os.path.join(image_dir, filename)
    image_file.save(save_path)

    images.append({'filename': filename})
    current['images'] = images
    room.setdefault('target_state', {})
    room['target_state'][target_key] = current
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)

    all_files = _collect_epessto_all_files(room)
    if not all_files:
        return jsonify({'success': True, 'summary': None, 'targets': [], 'batches': []})

    data = _serialize_from_filenames(all_files, room)
    data['batches'] = room.get('batches', [])
    return jsonify({'success': True, **data})


@private_area_bp.route('/api/epessto_support/target_image', methods=['DELETE'])
def api_epessto_support_target_image_delete():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, room_id, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    target_key = str(payload.get('target_key', '')).strip().lower()
    filename = str(payload.get('filename', '')).strip()
    if not target_key or not filename:
        return jsonify({'error': 'target_key and filename are required'}), 400

    current = _normalize_epessto_target_state(room.get('target_state', {}).get(target_key, {}))
    images = current.get('images', [])
    current['images'] = [img for img in images if img.get('filename') != filename]

    room.setdefault('target_state', {})
    room['target_state'][target_key] = current
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)

    safe_name = os.path.basename(filename)
    image_path = os.path.join(_get_epessto_image_dir(room_id), safe_name)
    if os.path.isfile(image_path):
        os.remove(image_path)

    all_files = _collect_epessto_all_files(room)
    if not all_files:
        return jsonify({'success': True, 'summary': None, 'targets': [], 'batches': []})

    data = _serialize_from_filenames(all_files, room)
    data['batches'] = room.get('batches', [])
    return jsonify({'success': True, **data})


@private_area_bp.route('/api/epessto_support/image/<path:filename>', methods=['GET'])
def api_epessto_support_image_file(filename):
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    _, room_id, _, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    safe_name = os.path.basename(filename)
    image_path = os.path.join(_get_epessto_image_dir(room_id), safe_name)
    if not os.path.isfile(image_path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(image_path)


@private_area_bp.route('/api/epessto_support/clear', methods=['DELETE'])
def api_epessto_support_clear():
    if not can_view_private_area():
        return jsonify({'error': 'Forbidden'}), 403

    store, room_id, room, err = _get_epessto_room_or_response(require_room=True)
    if err:
        return err

    upload_dir = _get_epessto_upload_dir(room_id)
    removed = 0
    for batch in room.get('batches', []):
        for fn in batch.get('files', []):
            # Prevent path traversal
            safe = os.path.basename(fn)
            fp = os.path.join(upload_dir, safe)
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1

    for _, state in room.get('target_state', {}).items():
        images = state.get('images', []) if isinstance(state, dict) else []
        for image in images:
            filename = str(image.get('filename', '')).strip()
            if not filename:
                continue
            fp = os.path.join(_get_epessto_image_dir(room_id), os.path.basename(filename))
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1

    room['batches'] = []
    room['target_state'] = {}
    _touch_epessto_room(room, _get_epessto_actor())
    _save_epessto_store(store)
    return jsonify({'success': True, 'removed': removed})

@private_area_bp.route('/documents')
def documents_list():
    if 'user' not in session:
        flash('Please log in to access documents.', 'warning')
        return redirect(url_for('basic.login'))
    
    if not can_access_page('documents'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    is_admin = session['user'].get('is_admin', False)
        
    ensure_tutorials_dir()
    md_files = []
    if os.path.exists(tutorials_dir):
        for f in os.listdir(tutorials_dir):
            if f.endswith('.md'):
                name = f[:-3] # remove .md
                md_files.append({"filename": f, "title": name.replace('_', ' ').title()})
    
    metadata = get_documents_metadata()
    pinned = metadata.get('pinned', [])
    order = metadata.get('order', [])
    
    for f in md_files:
        f['is_pinned'] = f['filename'] in pinned
        try:
            f['order_idx'] = order.index(f['filename'])
        except ValueError:
            f['order_idx'] = 999999
            
    md_files.sort(key=lambda x: (not x['is_pinned'], x['order_idx'], x['title']))

    env_config = read_documents_env()
    important_message = env_config.get('IMPORTANT_MESSAGE', '')
    
    return render_template(
        'documents.html',
        current_path='/documents',
        documents=md_files,
        is_admin=is_admin,
        documents_editable=documents_editable(),
        important_message=important_message
    )

@private_area_bp.route('/documents/<filename>')
def document_view(filename):
    if 'user' not in session:
        flash('Please log in to access documents.', 'warning')
        return redirect(url_for('basic.login'))
        
    if not can_access_page('documents'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    is_admin = session['user'].get('is_admin', False)
        
    safe_filename = sanitize_document_filename(filename)
    if not safe_filename:
        abort(404)

    file_path = os.path.join(tutorials_dir, safe_filename)
    if not os.path.exists(file_path):
        abort(404)

    env_config = read_documents_env()
    important_message = env_config.get('IMPORTANT_MESSAGE', '')

    return render_template(
        'document_view.html',
        current_path='/documents',
        filename=safe_filename,
        title=safe_filename[:-3].replace('_', ' ').title(),
        is_admin=is_admin,
        documents_editable=documents_editable(),
        important_message=important_message
    )

@private_area_bp.route('/api/documents/metadata', methods=['POST'])
def api_documents_metadata():
    if not is_admin_user() and not documents_editable():
        return jsonify({'error': 'Forbidden'}), 403
        
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid request'}), 400
        
    metadata = get_documents_metadata()
    
    if 'pinned' in data:
        metadata['pinned'] = data['pinned']
    if 'order' in data:
        metadata['order'] = data['order']
        
    save_documents_metadata(metadata)
    return jsonify({'success': True})

@private_area_bp.route('/api/documents/settings', methods=['GET', 'POST'])
def api_documents_settings():
    if not can_view_documents():
        return jsonify({'error': 'Forbidden'}), 403

    if request.method == 'GET':
        config = read_documents_env()
        return jsonify({
            'success': True,
            'documents_editable': str(config.get('DOCUMENTS_EDITABLE', 'true')).lower() == 'true',
            'important_message': config.get('IMPORTANT_MESSAGE', ''),
            'is_admin': is_admin_user()
        })

    if not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403

    data = request.get_json(silent=True) or {}
    editable = bool(data.get('documents_editable', True))
    important_message = str(data.get('important_message', '')).strip()
    write_documents_env({
        'DOCUMENTS_EDITABLE': 'true' if editable else 'false',
        'IMPORTANT_MESSAGE': important_message
    })

    return jsonify({'success': True})

@private_area_bp.route('/api/documents/create', methods=['POST'])
def api_documents_create():
    if not can_view_documents() or not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    if not documents_editable():
        return jsonify({'error': 'Editing is disabled'}), 403

    data = request.get_json(silent=True) or {}
    filename = sanitize_document_filename(data.get('filename', ''))
    content = str(data.get('content', '')).strip()

    if not filename:
        return jsonify({'error': 'Invalid filename'}), 400

    ensure_tutorials_dir()
    file_path = os.path.join(tutorials_dir, filename)
    if os.path.exists(file_path):
        return jsonify({'error': 'Document already exists'}), 409

    with open(file_path, 'w', encoding='utf-8') as doc_file:
        doc_file.write(content if content else f"# {filename[:-3].replace('_', ' ').title()}\n\n")

    return jsonify({'success': True, 'filename': filename})

@private_area_bp.route('/api/documents/<filename>/content', methods=['GET', 'PUT'])
def api_documents_content(filename):
    if not can_view_documents():
        return jsonify({'error': 'Forbidden'}), 403

    safe_filename = sanitize_document_filename(filename)
    if not safe_filename:
        return jsonify({'error': 'Invalid filename'}), 400

    file_path = os.path.join(tutorials_dir, safe_filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'Document not found'}), 404

    if request.method == 'GET':
        with open(file_path, 'r', encoding='utf-8') as doc_file:
            raw_content = doc_file.read()
        
        # Replace {{hide=KEY}} with actual values from env
        if '{{hide=' in raw_content:
            env_config = read_documents_env()
            import re
            def replace_secret(match):
                key = match.group(1).strip()
                # Return actual value if it exists, otherwise keep placeholder or visually show it's missing
                return env_config.get(key, f"[{key} NOT FOUND IN ENV]")
            
            content = re.sub(r'\{\{hide=(.*?)\}\}', replace_secret, raw_content)
        else:
            content = raw_content

        return jsonify({
            'success': True, 
            'content': content,
            'raw_content': raw_content # send raw so editor shows {{hide=KEY}}
        })

    if not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    if not documents_editable():
        return jsonify({'error': 'Editing is disabled'}), 403

    data = request.get_json(silent=True) or {}
    content = str(data.get('content', ''))
    with open(file_path, 'w', encoding='utf-8') as doc_file:
        doc_file.write(content)

    return jsonify({'success': True})

@private_area_bp.route('/api/documents/upload-image', methods=['POST'])
def api_documents_upload_image():
    if not can_view_documents() or not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    if not documents_editable():
        return jsonify({'error': 'Editing is disabled'}), 403

    if 'image' not in request.files:
        return jsonify({'error': 'Missing image file'}), 400

    image = request.files['image']
    raw_name = secure_filename(image.filename or '')
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in allowed_image_ext:
        return jsonify({'error': 'Unsupported image type'}), 400

    images_dir = os.path.join(tutorials_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)
    image_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    image_path = os.path.join(images_dir, image_name)
    image.save(image_path)

    static_path = f"/tutorials/images/{image_name}"
    return jsonify({
        'success': True,
        'image_url': static_path,
        'markdown': f"![]({static_path})"
    })


@private_area_bp.route('/tutorials/images/<path:filename>')
def serve_tutorial_image(filename):
    """Serve images stored in private_area/tutorials/images/."""
    if '..' in filename or filename.startswith('/'):
        abort(400)
    from flask import send_from_directory
    images_dir = os.path.join(tutorials_dir, 'images')
    return send_from_directory(images_dir, filename)


from modules.database.obs import save_observation_target, get_observation_targets, delete_observation_target, update_observation_target

@private_area_bp.route('/api/members', methods=['GET'])
def api_members():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from modules.database.auth import get_users
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
def api_greatlab_links():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
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

@private_area_bp.route('/api/targets', methods=['GET', 'POST'])
def api_observation_targets():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    
    if request.method == 'GET':
        targets = get_observation_targets(active_only=False)
        return jsonify({'success': True, 'targets': targets})
        
    elif request.method == 'POST':
        if not (is_great_lab or is_admin):
            return jsonify({'error': 'Forbidden'}), 403
            
        data = request.json
        new_id = save_observation_target(
            telescope=data.get('telescope'),
            name=data.get('name'),
            mag=data.get('mag'),
            ra=data.get('ra'),
            dec=data.get('dec'),
            priority=data.get('priority'),
            repeat_count=data.get('repeat_count', 0),
            auto_exposure=data.get('auto_exposure', True),
            filters=data.get('filters', []),
            plan=data.get('plan'),
            program=data.get('program'),
            note_gl=data.get('note_gl', ''),
            user_email=session['user']['email']
        )
        
        if new_id:
            return jsonify({'success': True, 'id': new_id})
        else:
            return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['DELETE'])
def api_observation_target_delete(target_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    if delete_observation_target(target_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>/toggle', methods=['PUT'])
def api_observation_target_toggle(target_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    data = request.json
    is_active = data.get('is_active')
    if is_active is None:
        return jsonify({'error': 'is_active field required'}), 400
        
    from modules.database.obs import update_observation_target_status
    if update_observation_target_status(target_id, bool(is_active)):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['PUT'])
def api_observation_target_update(target_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403
        
    data = request.json
    if update_observation_target(
        target_id=target_id,
        telescope=data.get('telescope'),
        name=data.get('name'),
        mag=data.get('mag'),
        ra=data.get('ra'),
        dec=data.get('dec'),
        priority=data.get('priority'),
        repeat_count=data.get('repeat_count', 0),
        auto_exposure=data.get('auto_exposure', False),
        filters=data.get('filters', []),
        plan=data.get('plan'),
        program=data.get('program'),
        note_gl=data.get('note_gl', '')
    ):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500


@private_area_bp.route('/api/targets/update-mags', methods=['POST'])
def api_update_target_mags():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    import threading
    from modules.phot_scheduler import update_target_mags

    def _run():
        update_target_mags()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Magnitude update started'})

@private_area_bp.route('/api/search_target')
def api_search_target():
    """Search TNS objects by name for autocomplete"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'results': []})
    
    try:
        from modules.database.transient import search_tns_objects
        rows = search_tns_objects(search_term=q, limit=15, sort_by='discoverydate', sort_order='desc')
        results = []
        for r in rows:
            results.append({
                'name': r['name'],
                'prefix': r.get('name_prefix') or '',
                'reporting_group': r.get('reporting_group') or '',
                'source_group': r.get('source_group') or '',
                'ra': r.get('ra'),
                'dec': r.get('declination'),
                'redshift': r.get('redshift'),
                'mag': r.get('brightest_mag') or r.get('discoverymag'),
                'type': r.get('type') or '',
                'internal_names': r.get('internal_names') or '',
            })
        return jsonify({'results': results})
    except Exception as e:
        logger.error('Search error: %s', e)
        return jsonify({'results': []})

@private_area_bp.route('/api/auto_exposure')
def api_auto_exposure():
    """Return auto exposure config from observation_script lookup table"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    mag = request.args.get('mag', '').strip()
    telescope = request.args.get('telescope', 'SLT').strip()
    if not mag:
        return jsonify({'error': 'mag parameter required'}), 400

    try:
        from modules.observation_script import exposure_time
        result = exposure_time(mag)
        if isinstance(result, str):
            # "Too faint to observe" or "Invalid magnitude"
            return jsonify({'error': result})

        # result is dict like {"up": "60sec*1", "gp": "30sec*1", ...}
        filters = []
        for filt, val in result.items():
            parts = val.replace('sec*', ' ').split()
            exp = int(parts[0])
            count = int(parts[1])
            filters.append({'filter': filt, 'exp': exp, 'count': count})

        return jsonify({'success': True, 'filters': filters, 'telescope': telescope})
    except Exception as e:
        logger.error('Auto exposure error: %s', e)
        return jsonify({'error': str(e)}), 500

@private_area_bp.route('/private/calendar')
def private_calendar():
    if 'user' not in session:
        flash('Please log in to access calendar.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    
    if not (is_great_lab or is_admin):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
        
    return render_template('private_calendar.html', current_path='/private/calendar')

@private_area_bp.route('/private/telescope')
def private_telescope():
    if 'user' not in session:
        flash('Please log in to access telescope management.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    if not user_exists(user_email):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    users = get_users()
    user_data = users.get(user_email, {})
    user_groups = user_data.get('groups', [])
    
    if 'GREAT_Lab' not in user_groups:
        flash('Access denied. GREAT Lab members only.', 'error')
        return redirect(url_for('basic.home'))
    
    return render_template('private_telescope.html', current_path='/private/telescope')

@private_area_bp.route('/private/projects')
def private_projects():
    if 'user' not in session:
        flash('Please log in to access projects.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    if not user_exists(user_email):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    users = get_users()
    user_data = users.get(user_email, {})
    user_groups = user_data.get('groups', [])
    
    if 'GREAT_Lab' not in user_groups:
        flash('Access denied. GREAT Lab members only.', 'error')
        return redirect(url_for('basic.home'))
    
    return render_template('private_projects.html', current_path='/private/projects')

@private_area_bp.route('/private/resources')
def private_resources():
    if 'user' not in session:
        flash('Please log in to access resources.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    if not user_exists(user_email):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    
    users = get_users()
    user_data = users.get(user_email, {})
    user_groups = user_data.get('groups', [])
    
    if 'GREAT_Lab' not in user_groups:
        flash('Access denied. GREAT Lab members only.', 'error')
        return redirect(url_for('basic.home'))
    
    return render_template('private_resources.html', current_path='/private/resources')

# ===============================================================================
# DEBUG ROUTES
# ===============================================================================
@private_area_bp.route('/debug/database')
def debug_database():
    if 'user' not in session or not session['user'].get('is_admin'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        from modules.database import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transient.objects")
            total_count = cursor.fetchone()[0]
            cursor.execute("SELECT name_prefix, name, obj_id FROM transient.objects LIMIT 10")
            sample_objects = cursor.fetchall()
            cursor.close()
        return jsonify({
            'total_objects': total_count,
            'sample_objects': [list(r) for r in sample_objects],
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# @private_area_bp.route('/debug/object/<object_name>')
# Debug object tag route - disabled (old tns_database function)
# @private_area_bp.route('/api/debug-object-tag/<object_name>')
# def debug_object_tag_route(object_name):
#     if 'user' not in session or not session['user'].get('is_admin'):
#         return jsonify({'error': 'Access denied'}), 403
#     
#     try:
#         object_name = urllib.parse.unquote(object_name)
#         return jsonify({
#             'success': True,
#             'object_name': object_name,
#             'message': 'Debug function disabled - using PostgreSQL now'
#         })
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

@private_area_bp.route('/api/observation_log_months', methods=['GET'])
def api_get_observation_log_months():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        from modules.database.obs import get_observation_log_months
        months = get_observation_log_months()
        return jsonify({'success': True, 'months': months})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@private_area_bp.route('/api/observation_logs', methods=['GET', 'POST'])
def api_get_observation_logs():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            year = request.args.get('year', type=int)
            month = request.args.get('month', type=int)
            if not year or not month:
                return jsonify({'success': False, 'error': 'Year and month are required'}), 400
                
            from modules.database.obs import get_observation_logs
            logs = get_observation_logs(year, month)
            
            # Keep compatibility with both date objects and already-normalized strings.
            for log in logs:
                if getattr(log.get('obs_date'), 'strftime', None):
                    log['obs_date'] = log['obs_date'].strftime('%Y-%m-%d')
                    
            return jsonify({'success': True, 'logs': logs})
        elif request.method == 'POST':
            data = request.json
            action = (data.get('action') or '').strip().lower()
            target_name = (data.get('target_name') or '').strip()
            obs_date = data.get('obs_date')
            telescope_use = data.get('telescope_use')

            if action == 'delete':
                if not target_name or not obs_date:
                    return jsonify({'success': False, 'error': 'Target Name and Date required'}), 400
                from modules.database.obs import delete_observation_log
                deleted = delete_observation_log(target_name, obs_date, telescope_use)
                if deleted:
                    return jsonify({'success': True})
                return jsonify({'success': False, 'error': 'Log not found or failed to delete'}), 404

            # Auto-fill user_name from session if not provided
            user_name = data.get('user_name') or session['user'].get('name') or session['user'].get('email')
            is_triggered = data.get('is_triggered', False)
            is_observed = data.get('is_observed', False)
            import json as _json
            def _norm_filter(val):
                if not val:
                    return None
                if isinstance(val, list):
                    return _json.dumps(val)
                return str(val)
            trigger_filter  = _norm_filter(data.get('trigger_filter'))
            observed_filter = _norm_filter(data.get('observed_filter'))
            priority = data.get('priority') or None
            telescope_use = data.get('telescope_use') or None

            # Backward compatibility: older clients may still send target_id
            if not target_name and data.get('target_id'):
                from modules.database.obs import get_observation_targets
                tid = int(data.get('target_id'))
                t = next((x for x in get_observation_targets() if x.get('id') == tid), None)
                if t:
                    target_name = (t.get('name') or '').strip()
            
            if not target_name or not obs_date:
                return jsonify({'success': False, 'error': 'Target Name and Date required'}), 400
                
            from modules.database.obs import upsert_observation_log
            success = upsert_observation_log(
                target_name, obs_date, user_name, is_triggered, is_observed,
                trigger_filter,
                data.get('trigger_exp') if data.get('trigger_exp') is not None else None,
                data.get('trigger_count') if data.get('trigger_count') is not None else None,
                observed_filter,
                data.get('observed_exp') if data.get('observed_exp') is not None else None,
                data.get('observed_count') if data.get('observed_count') is not None else None,
                priority=priority,
                telescope_use=telescope_use,
                repeat_count=int(data.get('repeat_count') or 0)
            )
            
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'Failed to save log'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

