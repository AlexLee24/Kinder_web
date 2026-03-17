"""
Log viewer routes — accessible to GREATLab members and admins.
"""
import os
import re
from flask import render_template, session, jsonify, request, redirect, url_for

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def register_log_routes(app):

    def _can_view():
        if 'user' not in session:
            return False
        u = session['user']
        return bool(u.get('is_great_lab_member')) or bool(u.get('is_admin'))

    @app.route('/greatlab/log')
    def log_viewer():
        if not _can_view():
            return redirect(url_for('home'))
        return render_template('log_viewer.html', current_path='/greatlab/log')

    @app.route('/api/log/files')
    def api_log_files():
        if not _can_view():
            return jsonify({'error': 'Access denied'}), 403
        from modules.log_setup import get_log_dir
        log_dir = get_log_dir()
        if not log_dir or not os.path.isdir(log_dir):
            return jsonify({'dates': []})
        dates = sorted(
            (f[:-4] for f in os.listdir(log_dir)
             if f.endswith('.log') and len(f) == 14 and _DATE_RE.match(f[:-4])),
            reverse=True,
        )
        return jsonify({'dates': dates})

    @app.route('/api/log/content')
    def api_log_content():
        if not _can_view():
            return jsonify({'error': 'Access denied'}), 403

        date_str = request.args.get('date', '')
        if not _DATE_RE.match(date_str):
            return jsonify({'error': 'Invalid date format'}), 400

        offset = request.args.get('offset', 0, type=int)
        if offset < 0:
            offset = 0

        from modules.log_setup import get_log_dir
        log_dir = get_log_dir()
        if not log_dir:
            return jsonify({'content': '', 'offset': 0})

        log_file = os.path.realpath(os.path.join(log_dir, f'{date_str}.log'))
        log_dir_real = os.path.realpath(log_dir)

        # Path traversal guard (defense in depth — date_str is already regex-validated)
        if not log_file.startswith(log_dir_real + os.sep):
            return jsonify({'error': 'Access denied'}), 403

        if not os.path.isfile(log_file):
            return jsonify({'content': '', 'offset': 0})

        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(offset)
                content = f.read()
                new_offset = f.tell()
            return jsonify({'content': content, 'offset': new_offset})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
