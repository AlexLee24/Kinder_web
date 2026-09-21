"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — epessto (split from private_area_routes.py)."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from flask import render_template, redirect, url_for, session, flash, request, jsonify, send_file
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from . import private_area_bp
from .helpers import (
    _EPESSTO_ROOM_LIVE_HOURS,
    _EPESSTO_ROOM_SESSION_KEY,
    _cleanup_epessto_stale_rooms,
    _collect_epessto_all_files,
    _epessto_can_manage_members,
    _generate_epessto_room_id,
    _get_active_epessto_room_id,
    _get_epessto_actor,
    _get_epessto_image_dir,
    _get_epessto_upload_dir,
    _get_epessto_user_identity,
    _load_epessto_store,
    _new_epessto_room,
    _normalize_epessto_target_state,
    _parse_epessto_filename,
    _parse_utc_iso,
    _save_epessto_store,
    _serialize_epessto_upload,
    _serialize_from_filenames,
    _touch_epessto_room,
    _upsert_epessto_room_member,
    can_access_page,
    can_view_private_area,
)


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
