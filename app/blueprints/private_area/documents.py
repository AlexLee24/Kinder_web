"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — documents (split from private_area_routes.py)."""
import os
import re
import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify, abort
from werkzeug.utils import secure_filename
from app.core.auth import is_great_lab_member
from . import private_area_bp
from .helpers import (
    allowed_image_ext,
    can_access_page,
    can_view_documents,
    documents_editable,
    ensure_tutorials_dir,
    get_documents_metadata,
    is_admin_user,
    read_documents_env,
    reencode_uploaded_image,
    sanitize_document_filename,
    save_documents_metadata,
    tutorials_dir,
    write_documents_env,
)


_MAX_DOC_IMAGE_BYTES = 10 * 1024 * 1024


# Categories of the Documents feed (EAU-style news list): key → label. Unset documents show as "Guide".
DOC_CATEGORIES = {'guide': 'Guides', 'observing': 'Observing', 'pipeline': 'Data & pipeline',
                  'notice': 'Notices', 'resource': 'Resources'}
_MD_STRIP = re.compile(r'(!?\[([^\]]*)\]\([^)]*\))|[`*_>#~|]|\{\{hide=[^}]*\}\}|<[^>]+>')
_CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


def _doc_meta(metadata):
    docs = metadata.get('docs') if isinstance(metadata, dict) else None
    return docs if isinstance(docs, dict) else {}


def _plain(md_text, limit=None):
    """Markdown → one line of plain text (links keep their text)."""
    out = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '```', '|', '---')) or line.startswith('!['):
            continue
        out.append(_MD_STRIP.sub(lambda m: m.group(2) or '', line).strip())
        if limit and sum(len(x) for x in out) > limit:
            break
    text = ' '.join(x for x in out if x)
    return (text[:limit].rstrip() + '…') if limit and len(text) > limit else text


def _reading_minutes(md_text):
    plain = _plain(md_text)
    units = len(_CJK.findall(plain)) / 400 + len(_CJK.sub(' ', plain).split()) / 220
    return max(1, round(units))


def document_info(filename, metadata=None, with_body=False):
    """Everything the feed and the reader show about one document (metadata.json 'docs' + the file)."""
    metadata = get_documents_metadata() if metadata is None else metadata
    path = os.path.join(tutorials_dir, filename)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            body = fh.read()
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    m = _doc_meta(metadata).get(filename) or {}
    first_h1 = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith('# ')), '')
    title = (m.get('title') or first_h1 or filename[:-3].replace('_', ' ').title()).strip()
    pinned = filename in (metadata.get('pinned') or [])
    updated = m.get('updated') or datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
    info = {
        'filename': filename,
        'title': title,
        'summary': (m.get('summary') or '').strip(),
        'excerpt': (m.get('summary') or '').strip() or _plain(body, 320),
        'category': m.get('category') if m.get('category') in DOC_CATEGORIES else 'guide',
        'cover': m.get('cover') or '',
        'author': m.get('author') or 'GREAT Lab',
        'author_picture': m.get('author_picture') or '',
        'created': m.get('created') or updated,
        'updated': updated,
        'draft': bool(m.get('draft')),
        'is_pinned': pinned,
        'minutes': _reading_minutes(body),
        'sort_key': m.get('updated_at') or datetime.fromtimestamp(mtime).isoformat(timespec='seconds'),
    }
    info['category_label'] = DOC_CATEGORIES[info['category']]
    if with_body:
        info['body'] = body
        info['first_h1'] = first_h1
    return info


def _list_documents(include_drafts):
    ensure_tutorials_dir()
    metadata = get_documents_metadata()
    if not isinstance(metadata, dict):
        metadata = {}
    docs = []
    for f in sorted(os.listdir(tutorials_dir)):
        if f.endswith('.md'):
            d = document_info(f, metadata)
            if d and (include_drafts or not d['draft']):
                docs.append(d)
    # Important (pinned) first, then newest first
    docs.sort(key=lambda d: d['sort_key'], reverse=True)
    docs.sort(key=lambda d: not d['is_pinned'])
    return docs


def _login_or_denied():
    if 'user' not in session:
        flash('Please log in to access documents.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page('documents'):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    return None


@private_area_bp.route('/documents')
def documents_list():
    denied = _login_or_denied()
    if denied:
        return denied
    is_admin = is_admin_user()
    every = _list_documents(include_drafts=is_admin)
    category = request.args.get('category', 'all')
    if category not in DOC_CATEGORIES:
        category = 'all'
    published = [d for d in every if not d['draft']]
    drafts = [d for d in every if d['draft']]
    show_drafts = is_admin and request.args.get('drafts') == '1'
    docs = drafts if show_drafts else published
    if category != 'all':
        docs = [d for d in docs if d['category'] == category]
    counts = {k: sum(1 for d in published if d['category'] == k) for k in DOC_CATEGORIES}
    return render_template(
        'documents.html',
        current_path='/documents',
        documents=docs,
        categories=DOC_CATEGORIES,
        category=category,
        counts=counts,
        total=len(published),
        draft_count=len(drafts),
        show_drafts=show_drafts,
        is_admin=is_admin,
        documents_editable=documents_editable(),
    )


@private_area_bp.route('/documents/<filename>')
def document_view(filename):
    denied = _login_or_denied()
    if denied:
        return denied
    is_admin = is_admin_user()
    safe_filename = sanitize_document_filename(filename)
    if not safe_filename:
        abort(404)
    doc = document_info(safe_filename)
    if not doc or (doc['draft'] and not is_admin):
        abort(404)
    feed = [d for d in _list_documents(include_drafts=False) if d['category'] == doc['category']]
    idx = next((i for i, d in enumerate(feed) if d['filename'] == safe_filename), None)
    prev_doc = feed[idx - 1] if idx not in (None, 0) else None
    next_doc = feed[idx + 1] if idx is not None and idx + 1 < len(feed) else None
    return render_template(
        'document_view.html',
        current_path='/documents',
        doc=doc,
        filename=safe_filename,
        title=doc['title'],
        prev_doc=prev_doc,
        next_doc=next_doc,
        is_admin=is_admin,
        documents_editable=documents_editable(),
    )


def _editor_or_denied():
    denied = _login_or_denied()
    if denied:
        return denied
    if not is_admin_user():
        abort(403)
    if not documents_editable():
        flash('Editing documents is switched off.', 'warning')
        return redirect(url_for('private_area.documents_list'))
    return None


@private_area_bp.route('/documents/new')
def document_new():
    denied = _editor_or_denied()
    if denied:
        return denied
    cat = request.args.get('category')
    return render_template('document_edit.html', current_path='/documents', doc=None,
                           categories=DOC_CATEGORIES, default_category=cat if cat in DOC_CATEGORIES else 'guide')


@private_area_bp.route('/documents/<filename>/edit')
def document_edit(filename):
    denied = _editor_or_denied()
    if denied:
        return denied
    safe_filename = sanitize_document_filename(filename)
    doc = document_info(safe_filename, with_body=True) if safe_filename else None
    if not doc:
        abort(404)
    return render_template('document_edit.html', current_path='/documents', doc=doc,
                           categories=DOC_CATEGORIES, default_category=doc['category'])


def _new_filename(title):
    base = re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_').lower()[:60]
    if not base:
        base = 'doc_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    name, n = f'{base}.md', 2
    while os.path.exists(os.path.join(tutorials_dir, name)):
        name, n = f'{base}_{n}.md', n + 1
    return name


def _clean_cover(url):
    url = str(url or '').strip()
    return url if re.fullmatch(r'/tutorials/images/[A-Za-z0-9_.-]+', url) else ''


@private_area_bp.route('/api/documents/save', methods=['POST'])
def api_documents_save():
    """Create or update one document: {filename?, title, summary, category, cover, content, draft, pinned}."""
    if not can_view_documents() or not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    if not documents_editable():
        return jsonify({'error': 'Editing is disabled'}), 403
    data = request.get_json(silent=True) or {}
    title = str(data.get('title', '')).strip()[:200]
    if not title:
        return jsonify({'error': 'Give the document a title'}), 400
    content = str(data.get('content', ''))
    if len(content) > 2_000_000:
        return jsonify({'error': 'Document too long'}), 413
    category = data.get('category') if data.get('category') in DOC_CATEGORIES else 'guide'
    ensure_tutorials_dir()
    filename = sanitize_document_filename(data.get('filename', '')) if data.get('filename') else None
    if filename and not os.path.exists(os.path.join(tutorials_dir, filename)):
        return jsonify({'error': 'Document not found'}), 404
    if not filename:
        filename = _new_filename(title)
    with open(os.path.join(tutorials_dir, filename), 'w', encoding='utf-8') as fh:
        fh.write(content)

    metadata = get_documents_metadata()
    if not isinstance(metadata, dict):
        metadata = {}
    docs = _doc_meta(metadata)
    now = datetime.now()
    entry = docs.get(filename) or {}
    user = session.get('user') or {}
    if not entry:
        entry['created'] = now.strftime('%Y-%m-%d')
        entry['author'] = user.get('name') or user.get('username') or 'GREAT Lab'
        entry['author_picture'] = user.get('picture') or ''
    entry.update({'title': title, 'summary': str(data.get('summary', '')).strip()[:600], 'category': category,
                  'cover': _clean_cover(data.get('cover')), 'draft': bool(data.get('draft')),
                  'updated': now.strftime('%Y-%m-%d'), 'updated_at': now.isoformat(timespec='seconds')})
    docs[filename] = entry
    metadata['docs'] = docs
    pinned = [x for x in (metadata.get('pinned') or []) if x != filename]
    if data.get('pinned'):
        pinned.insert(0, filename)
    metadata['pinned'] = pinned
    save_documents_metadata(metadata)
    return jsonify({'success': True, 'filename': filename,
                    'url': url_for('private_area.document_view', filename=filename)})


@private_area_bp.route('/api/documents/<filename>/delete', methods=['POST'])
def api_documents_delete(filename):
    """Move a document to tutorials/.trash (kept, not erased)."""
    if not can_view_documents() or not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    if not documents_editable():
        return jsonify({'error': 'Editing is disabled'}), 403
    safe_filename = sanitize_document_filename(filename)
    path = os.path.join(tutorials_dir, safe_filename or '')
    if not safe_filename or not os.path.exists(path):
        return jsonify({'error': 'Document not found'}), 404
    trash = os.path.join(tutorials_dir, '.trash')
    os.makedirs(trash, exist_ok=True)
    os.replace(path, os.path.join(trash, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_filename}"))
    metadata = get_documents_metadata()
    if isinstance(metadata, dict):
        metadata['pinned'] = [x for x in (metadata.get('pinned') or []) if x != safe_filename]
        _doc_meta(metadata).pop(safe_filename, None)
        save_documents_metadata(metadata)
    return jsonify({'success': True})


@private_area_bp.route('/api/documents/metadata', methods=['POST'])
def api_documents_metadata():
    # Pin/reorder: document viewers only; non-admins only while editing is enabled
    # (matches the drag/pin controls shown in documents.html).
    if not can_view_documents():
        return jsonify({'error': 'Forbidden'}), 403
    if not is_admin_user() and not documents_editable():
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'Invalid request'}), 400

    for key in ('pinned', 'order'):
        if key in data:
            val = data[key]
            if (not isinstance(val, list) or len(val) > 5000
                    or not all(isinstance(x, str) and len(x) <= 255 for x in val)):
                return jsonify({'error': f'{key} must be a list of filenames'}), 400

    metadata = get_documents_metadata()
    if not isinstance(metadata, dict):
        metadata = {'pinned': [], 'order': []}

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
        
        # Replace {{hide=KEY}} with actual values from env — only for GREAT_Lab members /
        # admins; everyone else who can open the page sees a placeholder.
        if '{{hide=' in raw_content:
            import re
            reveal = is_great_lab_member()
            env_config = read_documents_env() if reveal else {}
            def replace_secret(match):
                if not reveal:
                    return '[hidden]'
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
    if request.content_length and request.content_length > _MAX_DOC_IMAGE_BYTES:
        return jsonify({'error': 'Image too large (max 10 MB)'}), 413
    raw_name = secure_filename(image.filename or '')
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in allowed_image_ext:
        return jsonify({'error': 'Unsupported image type'}), 400

    images_dir = os.path.join(tutorials_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)
    image_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    image_path = os.path.join(images_dir, image_name)
    data = image.stream.read(_MAX_DOC_IMAGE_BYTES + 1)
    if len(data) > _MAX_DOC_IMAGE_BYTES:
        return jsonify({'error': 'Image too large (max 10 MB)'}), 413
    with open(image_path, 'wb') as out:
        out.write(data)
    if not reencode_uploaded_image(image_path, ext):
        return jsonify({'error': 'File is not a valid image'}), 400

    static_path = f"/tutorials/images/{image_name}"
    return jsonify({
        'success': True,
        'image_url': static_path,
        'markdown': f"![]({static_path})"
    })

@private_area_bp.route('/tutorials/images/<path:filename>')
def serve_tutorial_image(filename):
    """Serve images stored in private_area/tutorials/images/."""
    if not can_view_documents():
        abort(403)
    if '..' in filename or filename.startswith('/'):
        abort(400)
    if os.path.splitext(filename)[1].lower() not in allowed_image_ext:
        abort(404)
    from flask import send_from_directory
    images_dir = os.path.join(tutorials_dir, 'images')
    return send_from_directory(images_dir, filename,
                               download_name=secure_filename(os.path.basename(filename)) or 'image',
                               as_attachment=False)


@private_area_bp.route('/api/documents/<filename>/pin', methods=['POST'])
def api_documents_pin(filename):
    """Mark a document important (pinned to the top of the feed) or not: {"pinned": bool}."""
    if not can_view_documents() or not is_admin_user():
        return jsonify({'error': 'Admin only'}), 403
    safe_filename = sanitize_document_filename(filename)
    if not safe_filename or not os.path.exists(os.path.join(tutorials_dir, safe_filename)):
        return jsonify({'error': 'Document not found'}), 404
    metadata = get_documents_metadata()
    if not isinstance(metadata, dict):
        metadata = {}
    pinned = [x for x in (metadata.get('pinned') or []) if x != safe_filename]
    if (request.get_json(silent=True) or {}).get('pinned'):
        pinned.insert(0, safe_filename)
    metadata['pinned'] = pinned
    save_documents_metadata(metadata)
    return jsonify({'success': True, 'pinned': safe_filename in pinned})
