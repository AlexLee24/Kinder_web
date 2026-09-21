"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — documents (split from private_area_routes.py)."""
import os
import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify, abort
from werkzeug.utils import secure_filename
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
    sanitize_document_filename,
    save_documents_metadata,
    tutorials_dir,
    write_documents_env,
)


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
