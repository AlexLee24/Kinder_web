"""
Calendar routes for the Kinder web application.
"""
import os
import urllib.parse
import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify, Response, abort
from werkzeug.utils import secure_filename

from modules.web_postgres_database import get_users, user_exists, check_object_access, get_groups



def register_private_routes(app):
    """Register calendar routes with the Flask app"""

    tutorials_dir = os.path.join(app.static_folder, 'tutorials')
    tutorials_env_path = os.path.join(tutorials_dir, '.env')
    allowed_image_ext = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

    def ensure_tutorials_dir():
        os.makedirs(tutorials_dir, exist_ok=True)

    def can_view_documents():
        if 'user' not in session:
            return False
        return session['user'].get('is_great_lab_member', False) or session['user'].get('is_admin', False)

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
    
    # ===============================================================================
    # PRIVATE AREA
    # ===============================================================================
    @app.route('/daily_trigger')
    def daily_trigger():
        if 'user' not in session:
            flash('Please log in to access daily trigger.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if not (is_great_lab or is_admin):
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        all_groups = []
        if is_admin:
            groups_dict = get_groups()
            all_groups = list(groups_dict.keys())
        
        return render_template('daily_trigger.html', current_path='/daily_trigger', all_groups=all_groups)

    @app.route('/documents')
    def documents_list():
        if 'user' not in session:
            flash('Please log in to access documents.', 'warning')
            return redirect(url_for('login'))
        
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if not (is_great_lab or is_admin):
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
            
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

    @app.route('/documents/<filename>')
    def document_view(filename):
        if 'user' not in session:
            flash('Please log in to access documents.', 'warning')
            return redirect(url_for('login'))
            
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if not (is_great_lab or is_admin):
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
            
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

    @app.route('/api/documents/metadata', methods=['POST'])
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

    @app.route('/api/documents/settings', methods=['GET', 'POST'])
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

    @app.route('/api/documents/create', methods=['POST'])
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

    @app.route('/api/documents/<filename>/content', methods=['GET', 'PUT'])
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

    @app.route('/api/documents/upload-image', methods=['POST'])
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

        static_path = f"/static/tutorials/images/{image_name}"
        return jsonify({
            'success': True,
            'image_url': static_path,
            'markdown': f"![]({static_path})"
        })

    
    from modules.web_postgres_database import save_observation_target, get_observation_targets, delete_observation_target, update_observation_target

    @app.route('/api/members', methods=['GET'])
    def api_members():
        if 'user' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        
        from modules.web_postgres_database import get_users
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

    @app.route('/api/targets', methods=['GET', 'POST'])
    def api_observation_targets():
        if 'user' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
            
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if request.method == 'GET':
            targets = get_observation_targets()
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

    @app.route('/api/targets/<int:target_id>', methods=['DELETE'])
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

    @app.route('/api/targets/<int:target_id>/toggle', methods=['PUT'])
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
            
        from modules.web_postgres_database import update_observation_target_status
        if update_observation_target_status(target_id, bool(is_active)):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Database error'}), 500

    @app.route('/api/targets/<int:target_id>', methods=['PUT'])
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

    @app.route('/api/search_target')
    def api_search_target():
        """Search TNS objects by name for autocomplete"""
        if 'user' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        
        q = request.args.get('q', '').strip()
        if len(q) < 2:
            return jsonify({'results': []})
        
        try:
            from modules.postgres_database import get_db_connection
            with get_db_connection() as conn:
                cursor = conn.cursor()
                search_pattern = f'%{q}%'
                cursor.execute('''
                    SELECT name, name_prefix, ra, declination, redshift, discoverymag, type
                    FROM tns_objects
                    WHERE name ILIKE %s OR name_prefix || name ILIKE %s OR internal_names ILIKE %s
                    ORDER BY discoverydate DESC
                    LIMIT 15
                ''', (search_pattern, search_pattern, search_pattern))
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    results.append({
                        'name': r[0],
                        'prefix': r[1] or '',
                        'ra': r[2],
                        'dec': r[3],
                        'redshift': r[4],
                        'mag': r[5],
                        'type': r[6] or ''
                    })
                cursor.close()
            return jsonify({'results': results})
        except Exception as e:
            print(f"Search error: {e}")
            return jsonify({'results': []})

    @app.route('/api/auto_exposure')
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
            print(f"Auto exposure error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/private/calendar')
    def private_calendar():
        if 'user' not in session:
            flash('Please log in to access calendar.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        is_great_lab = session['user'].get('is_great_lab_member', False)
        is_admin = session['user'].get('is_admin', False)
        
        if not (is_great_lab or is_admin):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
            
        return render_template('private_calendar.html', current_path='/private/calendar')

    @app.route('/private/telescope')
    def private_telescope():
        if 'user' not in session:
            flash('Please log in to access telescope management.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_telescope.html', current_path='/private/telescope')

    @app.route('/private/projects')
    def private_projects():
        if 'user' not in session:
            flash('Please log in to access projects.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_projects.html', current_path='/private/projects')

    @app.route('/private/resources')
    def private_resources():
        if 'user' not in session:
            flash('Please log in to access resources.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_resources.html', current_path='/private/resources')

    # ===============================================================================
    # DEBUG ROUTES
    # ===============================================================================
    @app.route('/debug/database')
    def debug_database():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            from modules.postgres_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM tns_objects")
            total_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT name_prefix, name, objid FROM tns_objects LIMIT 10")
            sample_objects = cursor.fetchall()
            
            cursor.execute("PRAGMA table_info(tns_objects)")
            columns = cursor.fetchall()
            
            conn.close()
            
            return jsonify({
                'total_objects': total_count,
                'sample_objects': sample_objects,
                'columns': [col[1] for col in columns]
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # @app.route('/debug/object/<object_name>')
    # Debug object tag route - disabled (old tns_database function)
    # @app.route('/api/debug-object-tag/<object_name>')
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

    @app.route('/api/observation_log_months', methods=['GET'])
    def api_get_observation_log_months():
        if 'user' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        try:
            from modules.web_postgres_database import get_observation_log_months
            months = get_observation_log_months()
            return jsonify({'success': True, 'months': months})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/observation_logs', methods=['GET', 'POST'])
    def api_get_observation_logs():
        if 'user' not in session:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
        try:
            if request.method == 'GET':
                year = request.args.get('year', type=int)
                month = request.args.get('month', type=int)
                if not year or not month:
                    return jsonify({'success': False, 'error': 'Year and month are required'}), 400
                    
                from modules.web_postgres_database import get_observation_logs
                logs = get_observation_logs(year, month)
                
                # Format dates to string
                for log in logs:
                    if log['obs_date']:
                        log['obs_date'] = log['obs_date'].strftime('%Y-%m-%d')
                        
                return jsonify({'success': True, 'logs': logs})
            elif request.method == 'POST':
                data = request.json
                target_name = (data.get('target_name') or '').strip()
                obs_date = data.get('obs_date')
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

                # Backward compatibility: older clients may still send target_id
                if not target_name and data.get('target_id'):
                    from modules.web_postgres_database import get_observation_targets
                    tid = int(data.get('target_id'))
                    t = next((x for x in get_observation_targets() if x.get('id') == tid), None)
                    if t:
                        target_name = (t.get('name') or '').strip()
                
                if not target_name or not obs_date:
                    return jsonify({'success': False, 'error': 'Target Name and Date required'}), 400
                    
                from modules.web_postgres_database import upsert_observation_log
                success = upsert_observation_log(
                    target_name, obs_date, user_name, is_triggered, is_observed,
                    trigger_filter,
                    int(data['trigger_exp']) if data.get('trigger_exp') else None,
                    int(data['trigger_count']) if data.get('trigger_count') else None,
                    observed_filter,
                    int(data['observed_exp']) if data.get('observed_exp') else None,
                    int(data['observed_count']) if data.get('observed_count') else None,
                    priority=priority
                )
                
                if success:
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': 'Failed to save log'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    return app
