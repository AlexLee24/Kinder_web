"""
Basic routes (home, login page, profile)
"""
import os, json, time
from flask import render_template, redirect, url_for, session, flash, send_from_directory, jsonify, request, abort
from flask import Blueprint
from werkzeug.utils import secure_filename
from PIL import Image

basic_bp = Blueprint('basic', __name__, template_folder='templates', static_folder='static')

SLIDESHOW_DIR = os.path.join(os.path.dirname(__file__), 'slideshow')
SLIDESHOW_CONFIG = os.path.join(SLIDESHOW_DIR, 'slideshow_config.json')

# Gallery configuration
GALLERY_DIR = os.path.join(os.path.dirname(__file__), 'gallery_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
THUMBNAIL_SIZE = (300, 300)

# Create gallery directory if it doesn't exist
os.makedirs(GALLERY_DIR, exist_ok=True)

def allowed_file(filename):
    """Check if file is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_thumbnail(image_path):
    """Create thumbnail from image."""
    try:
        img = Image.open(image_path)
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        thumbnail_path = image_path.replace('.', '_thumb.')
        img.save(thumbnail_path, quality=85, optimize=True)
        return thumbnail_path
    except Exception as e:
        print(f'Thumbnail creation error: {e}')
        return image_path

@basic_bp.route('/slideshow/image/<filename>')
def slideshow_image(filename):
    """Serve images from the slideshow folder."""
    filename = os.path.basename(filename)  # prevent path traversal
    return send_from_directory(SLIDESHOW_DIR, filename)


@basic_bp.route('/api/slideshow')
def get_slideshow():
    """Return slideshow config as JSON, filtering enabled + existing slides."""
    if not os.path.exists(SLIDESHOW_CONFIG):
        return jsonify({'slides': [], 'interval': 6500, 'transition': 500})
    with open(SLIDESHOW_CONFIG, 'r', encoding='utf-8') as f:
        config = json.load(f)
    slides = []
    for slide in config.get('slides', []):
        if not slide.get('enabled', True):
            continue
        filepath = os.path.join(SLIDESHOW_DIR, slide['filename'])
        if os.path.exists(filepath):
            slides.append({
                'url': url_for('basic.slideshow_image', filename=slide['filename']),
                'title': slide.get('title', ''),
                'caption': slide.get('caption', ''),
                'author': slide.get('author', ''),
                'fit': bool(slide.get('fit', True)),
            })
    return jsonify({
        'slides': slides,
        'interval': config.get('interval', 6500),
        'transition': config.get('transition', 500),
    })


@basic_bp.route('/')
def home():
    return render_template('home.html', current_path='/')

@basic_bp.route('/login')
def login():
    return render_template('login.html', current_path='/login')

@basic_bp.route('/profile')
def profile():
    if 'user' not in session:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('basic.login'))
    
    user_email = session['user']['email']
    user_groups = []
    user_data = None
    
    from modules.database.auth import user_exists, get_user, get_groups, get_user_group_requests
    all_groups = []
    user_requests = {}
    if user_exists(user_email):
        user_data = get_user(user_email)  # already includes groups
        user_groups = user_data.get('groups', []) if user_data else []
        user_requests = get_user_group_requests(user_email)
        # Convert list → dict keyed by group_name for easy lookup
        user_requests = {r['group_name']: r.get('status') for r in user_requests}
        
        session['user']['name'] = user_data.get('name', session['user']['name'])
        # Never store base64 images in the session cookie (4 KB limit).
        # Only update the picture if it looks like a URL, not a data URI.
        new_pic = user_data.get('picture') or ''
        if new_pic and not new_pic.startswith('data:image'):
            session['user']['picture'] = new_pic
        if (session['user'].get('picture') or '').startswith('data:image'):
            session['user']['picture'] = ''
        session['user']['is_admin'] = user_data.get('is_admin', False)
        session['user']['is_great_lab_member'] = 'GREAT_Lab' in user_groups or session['user'].get('is_admin', False)
        
        # Fetch all available groups to display
        groups_dict = get_groups()
        for g_name, g_data in groups_dict.items():
            all_groups.append({
                'name': g_name,
                'description': g_data.get('description', ''),
                'member_count': len(g_data.get('members', [])),
                'is_member': g_name in user_groups,
                'request_status': user_requests.get(g_name)
            })
    
    return render_template('profile.html', 
                         current_path='/profile',
                         user_groups=user_groups,
                         user_data=user_data,
                         all_groups=all_groups)

from flask import request, jsonify
from modules.database.auth import create_group_request, remove_user_from_group, group_exists

@basic_bp.route('/api/profile/join_group', methods=['POST'])
def api_join_group():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    data = request.json
    group_name = data.get('group_name')
    
    if not group_name or not group_exists(group_name):
        return jsonify({'success': False, 'error': 'Invalid group name'}), 400
        
    user_email = session['user']['email']
    if create_group_request(user_email, group_name):
        return jsonify({'success': True, 'message': f'Request to join {group_name} sent.'})
    else:
        return jsonify({'success': False, 'error': 'Request already exists or failed to create.'})

@basic_bp.route('/api/profile/leave_group', methods=['POST'])
def api_leave_group():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    data = request.json
    group_name = data.get('group_name')
    
    if not group_name:
        return jsonify({'success': False, 'error': 'Group name required'}), 400
        
    user_email = session['user']['email']
    if remove_user_from_group(user_email, group_name):
        return jsonify({'success': True, 'message': f'Left {group_name}.'})
    else:
        return jsonify({'success': False, 'error': 'Failed to leave group.'})


@basic_bp.route('/api/gallery')
def api_gallery_list():
    """Get all gallery images."""
    try:
        items = []
        if os.path.exists(GALLERY_DIR):
            for filename in sorted(os.listdir(GALLERY_DIR)):
                if filename.endswith('_thumb.jpg') or filename.endswith('_thumb.png'):
                    continue
                if allowed_file(filename):
                    filepath = os.path.join(GALLERY_DIR, filename)
                    # Try to get metadata
                    metadata_file = filepath + '.json'
                    metadata = {}
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, 'r', encoding='utf-8') as f:
                                metadata = json.load(f)
                        except:
                            pass

                    items.append({
                        'id': filename,
                        'title': metadata.get('title', filename),
                        'description': metadata.get('description', ''),
                        'photographer': metadata.get('photographer', 'Anonymous'),
                        'span': metadata.get('span', 'col-span-1 row-span-1'),
                        'image_url': url_for('basic.gallery_image', filename=filename),
                        'thumbnail_url': url_for('basic.gallery_image', filename=filename.replace('.', '_thumb.'))
                            if filename + '_thumb' in os.listdir(GALLERY_DIR) else url_for('basic.gallery_image', filename=filename)
                    })
        return jsonify({'items': items, 'success': True})
    except Exception as e:
        print(f'Gallery list error: {e}')
        return jsonify({'items': [], 'success': False, 'error': str(e)}), 500


@basic_bp.route('/api/gallery/upload', methods=['POST'])
def api_gallery_upload():
    """Upload a gallery image (admin only)."""
    if 'user' not in session or not session.get('user', {}).get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image provided'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'File type not allowed'}), 400

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE:
            return jsonify({'success': False, 'error': 'File too large'}), 400

        # Save file
        filename = secure_filename(file.filename)
        # Add timestamp to avoid conflicts
        timestamp = int(time.time())
        name, ext = os.path.splitext(filename)
        filename = f'{name}_{timestamp}{ext}'

        filepath = os.path.join(GALLERY_DIR, filename)
        file.save(filepath)

        # Create thumbnail
        create_thumbnail(filepath)

        # Save metadata
        metadata = {
            'title': request.form.get('title', filename),
            'description': request.form.get('description', ''),
            'photographer': request.form.get('photographer', ''),
            'span': request.form.get('span', 'col-span-1 row-span-1'),
            'uploaded_by': session.get('user', {}).get('email'),
            'uploaded_at': time.time()
        }

        metadata_file = filepath + '.json'
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f)

        return jsonify({
            'success': True,
            'message': 'Image uploaded successfully',
            'filename': filename
        })

    except Exception as e:
        print(f'Upload error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@basic_bp.route('/api/gallery/<item_id>', methods=['DELETE'])
def api_gallery_delete(item_id):
    """Delete a gallery image (admin only)."""
    if 'user' not in session or not session.get('user', {}).get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        filepath = os.path.join(GALLERY_DIR, secure_filename(item_id))

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'File not found'}), 404

        # Delete image and thumbnail
        os.remove(filepath)

        # Delete thumbnail
        thumb_path = filepath.replace('.', '_thumb.')
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

        # Delete metadata
        metadata_file = filepath + '.json'
        if os.path.exists(metadata_file):
            os.remove(metadata_file)

        return jsonify({'success': True, 'message': 'Image deleted'})

    except Exception as e:
        print(f'Delete error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@basic_bp.route('/api/gallery/<item_id>', methods=['PUT'])
def api_gallery_update(item_id):
    """Update gallery image metadata (admin only)."""
    if 'user' not in session or not session.get('user', {}).get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        filepath = os.path.join(GALLERY_DIR, secure_filename(item_id))

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'File not found'}), 404

        # Get data from request
        data = request.json

        # Load existing metadata
        metadata_file = filepath + '.json'
        metadata = {}
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except:
                pass

        # Update metadata
        if 'title' in data:
            metadata['title'] = data['title']
        if 'description' in data:
            metadata['description'] = data['description']
        if 'photographer' in data:
            metadata['photographer'] = data['photographer']
        if 'span' in data:
            metadata['span'] = data['span']

        # Save updated metadata
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'message': 'Image updated successfully',
            'data': metadata
        })

    except Exception as e:
        print(f'Update error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@basic_bp.route('/gallery/image/<filename>')
def gallery_image(filename):
    """Serve gallery images."""
    filename = secure_filename(filename)
    if not os.path.exists(os.path.join(GALLERY_DIR, filename)):
        abort(404)
    return send_from_directory(GALLERY_DIR, filename)
