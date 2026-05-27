"""
Log viewer routes — accessible to GREATLab members and admins.
"""
import os
import re
from flask import render_template, session, jsonify, request, redirect, url_for

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_SRC_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[([^\]]+)\]')
_DEFAULT_MAX_READ_BYTES = 128 * 1024
_MAX_ALLOWED_READ_BYTES = 2 * 1024 * 1024
_DEFAULT_TAIL_LINES = 300
_MAX_TAIL_LINES = 2000
_TAIL_BLOCK_BYTES = 64 * 1024
_TAIL_MAX_SCAN_BYTES = 4 * 1024 * 1024


def _line_source(line: str) -> str:
    m = _SRC_RE.match(line)
    return m.group(1) if m else ''


def _filter_line(line: str, source_filters: set[str], has_explicit_filter: bool) -> bool:
    if not has_explicit_filter:
        return True
    return _line_source(line) in source_filters


def _tail_read_lines(log_file: str, max_lines: int, source_filters: set[str], has_explicit_filter: bool) -> tuple[str, int, bool]:
    """Read last lines by scanning from file end in blocks.

    Returns (content, rendered_lines, truncated).
    """
    file_size = os.path.getsize(log_file)
    if file_size <= 0:
        return '', 0, False

    chunks: list[bytes] = []
    scanned = 0
    pos = file_size
    hit_start = False
    newline_count = 0
    estimated_needed = max_lines if not has_explicit_filter else max_lines * 8
    estimated_needed = max(estimated_needed, _DEFAULT_TAIL_LINES)

    with open(log_file, 'rb') as f:
        while pos > 0 and scanned < _TAIL_MAX_SCAN_BYTES:
            read_size = min(_TAIL_BLOCK_BYTES, pos)
            pos -= read_size
            f.seek(pos)
            block = f.read(read_size)
            chunks.append(block)
            scanned += read_size
            newline_count += block.count(b'\n')

            # Stop early when we have enough newline-separated candidates in the buffer.
            if newline_count >= estimated_needed:
                break

        if pos == 0:
            hit_start = True

    raw = b''.join(reversed(chunks))
    text = raw.decode('utf-8', errors='replace')
    lines = text.splitlines()
    if has_explicit_filter:
        lines = [ln for ln in lines if _line_source(ln) in source_filters]

    if len(lines) > max_lines:
        lines = lines[-max_lines:]

    if not lines:
        return '', 0, not hit_start
    return '\n'.join(lines) + '\n', len(lines), (not hit_start)


def _parse_source_filters() -> tuple[set[str], bool]:
    """Return (selected_sources, has_explicit_filter).
    
    An empty/absent 'sources' param means *no filter* (show all lines).
    A non-empty 'sources' param is a comma-separated whitelist.
    """
    raw_multi = request.args.get('sources', None)
    if raw_multi is not None:
        selected = {s.strip() for s in raw_multi.split(',') if s.strip()}
        # Empty string → treat as "no filter"
        if not selected:
            return set(), False
        return selected, True

    raw_single = (request.args.get('source', '') or '').strip()
    if raw_single.lower() in {'', 'all'}:
        return set(), False
    return {raw_single}, True


from flask import Blueprint
web_log_bp = Blueprint('web_log', __name__, template_folder='templates', static_folder='static')

def _can_view():
    if 'user' not in session:
        return False
    u = session['user']
    return bool(u.get('is_great_lab_member')) or bool(u.get('is_admin'))

@web_log_bp.route('/greatlab/log')
def log_viewer():
    if not _can_view():
        return redirect(url_for('basic.home'))
    return render_template('log_viewer.html', current_path='/greatlab/log')

@web_log_bp.route('/api/log/files')
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

@web_log_bp.route('/api/log/content')
def api_log_content():
    if not _can_view():
        return jsonify({'error': 'Access denied'}), 403

    date_str = request.args.get('date', '')
    if not _DATE_RE.match(date_str):
        return jsonify({'error': 'Invalid date format'}), 400

    offset = request.args.get('offset', 0, type=int)
    if offset < 0:
        offset = 0

    source_filters, has_explicit_filter = _parse_source_filters()
    tail_lines = request.args.get('tail_lines', 0, type=int)
    max_bytes = request.args.get('max_bytes', _DEFAULT_MAX_READ_BYTES, type=int)
    if max_bytes <= 0:
        max_bytes = _DEFAULT_MAX_READ_BYTES
    max_bytes = min(max_bytes, _MAX_ALLOWED_READ_BYTES)

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

    file_size = os.path.getsize(log_file)

    if tail_lines and offset == 0:
        tail_lines = max(1, min(tail_lines, _MAX_TAIL_LINES))
        try:
            content, rendered_lines, tail_truncated = _tail_read_lines(log_file, tail_lines, source_filters, has_explicit_filter)
            return jsonify({
                'content': content,
                'offset': file_size,
                'returned_lines': rendered_lines,
                'truncated': (rendered_lines >= tail_lines) or tail_truncated,
                'file_size': file_size,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if offset >= file_size:
        return jsonify({
            'content': '',
            'offset': file_size,
            'returned_lines': 0,
            'truncated': False,
            'file_size': file_size,
        })

    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(offset)
            content = f.read(max_bytes)
            new_offset = f.tell()
        if has_explicit_filter and content:
            filtered_lines = [ln for ln in content.splitlines() if _line_source(ln) in source_filters]
            content = '\n'.join(filtered_lines)
            if filtered_lines:
                content += '\n'
        rendered_lines = len(content.splitlines()) if content else 0
        return jsonify({
            'content': content,
            'offset': new_offset,
            'returned_lines': rendered_lines,
            'truncated': (new_offset < file_size and (new_offset - offset) >= max_bytes),
            'file_size': file_size,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@web_log_bp.route('/api/log/sources')
def api_log_sources():
    if not _can_view():
        return jsonify({'error': 'Access denied'}), 403

    date_str = request.args.get('date', '')
    if not _DATE_RE.match(date_str):
        return jsonify({'error': 'Invalid date format'}), 400

    from modules.log_setup import get_log_dir
    log_dir = get_log_dir()
    if not log_dir:
        return jsonify({'sources': []})

    log_file = os.path.realpath(os.path.join(log_dir, f'{date_str}.log'))
    log_dir_real = os.path.realpath(log_dir)
    if not log_file.startswith(log_dir_real + os.sep):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.isfile(log_file):
        return jsonify({'sources': []})

    sources = set()
    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                src = _line_source(line)
                if src:
                    sources.add(src)
                if i >= 120000:
                    break
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'sources': sorted(sources)})


_DAEMON_LOG_FILES = {
    'gcn_alert': 'gcn_alert.log',
    'detect':    'detect.log',
    'tns_fetch': 'tns_fetch.log',
}

@web_log_bp.route('/api/log/daemon/content')
def api_daemon_log_content():
    if not _can_view():
        return jsonify({'error': 'Access denied'}), 403

    source = request.args.get('source', '')
    if source not in _DAEMON_LOG_FILES:
        return jsonify({'error': 'Invalid source'}), 400

    offset = request.args.get('offset', 0, type=int)
    if offset < 0:
        offset = 0
    max_bytes = request.args.get('max_bytes', _DEFAULT_MAX_READ_BYTES, type=int)
    if max_bytes <= 0:
        max_bytes = _DEFAULT_MAX_READ_BYTES
    max_bytes = min(max_bytes, _MAX_ALLOWED_READ_BYTES)

    from modules.log_setup import get_log_dir
    log_dir = get_log_dir()
    if not log_dir:
        return jsonify({'content': '', 'offset': 0})

    log_file = os.path.realpath(os.path.join(log_dir, _DAEMON_LOG_FILES[source]))
    log_dir_real = os.path.realpath(log_dir)

    if not log_file.startswith(log_dir_real + os.sep):
        return jsonify({'error': 'Access denied'}), 403

    if not os.path.isfile(log_file):
        return jsonify({'content': '', 'offset': 0})

    file_size = os.path.getsize(log_file)
    if offset >= file_size:
        return jsonify({'content': '', 'offset': file_size})

    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(offset)
            content = f.read(max_bytes)
            new_offset = f.tell()
        return jsonify({'content': content, 'offset': new_offset})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
