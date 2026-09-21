"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — helpers (split from private_area_routes.py)."""
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from flask import session
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from app.db.auth import get_page_groups
import json
from . import private_area_bp


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
    # Write every key back: the file also holds the secrets used by {{hide=KEY}} in documents.
    with open(tutorials_env_path, 'w', encoding='utf-8') as env_file:
        for key, value in config.items():
            env_file.write(f"{key}={value}\n")

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
