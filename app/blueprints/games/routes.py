"""
Games routes
"""
import contextlib
import fcntl
import os
import json
import threading
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session

games_bp = Blueprint('games', __name__, template_folder='templates', static_folder='static')

from app.core import rate_limit
from app.paths import DATA_DIR
# NOTE: before the 2026-09 refactor this resolved to <repo>/data/ (a directory that did not
# exist), so the leaderboard was never persisted; it now lives with the other runtime data.
LEADERBOARD_FILE = os.path.join(DATA_DIR, '1a2b_leaderboard.json')


@games_bp.route('/games')
def games():
    return render_template('games.html', current_path='/games')


_leaderboard_thread_lock = threading.Lock()
_MAX_LEADERBOARD_RECORDS = 1000
_MAX_ATTEMPTS = 100
_MAX_NAME_LEN = 100
_SUBMIT_INTERVAL_SECS = 5.0


class _LeaderboardUnreadable(Exception):
    pass


@contextlib.contextmanager
def _leaderboard_lock():
    """Serialise read-modify-write of the leaderboard file across threads and processes."""
    os.makedirs(os.path.dirname(LEADERBOARD_FILE), exist_ok=True)
    with _leaderboard_thread_lock, open(LEADERBOARD_FILE + '.lock', 'a') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_leaderboard(strict=False):
    """Return the list of valid records. With strict=True, raise on a corrupt file
    instead of returning [] (so a writer never overwrites existing data)."""
    if not os.path.exists(LEADERBOARD_FILE):
        return []
    try:
        with open(LEADERBOARD_FILE, 'r') as f:
            data = json.load(f)
    except (OSError, ValueError):
        if strict:
            raise _LeaderboardUnreadable()
        return []
    if not isinstance(data, list):
        if strict:
            raise _LeaderboardUnreadable()
        return []
    return [r for r in data
            if isinstance(r, dict) and isinstance(r.get('attempts'), int)
            and not isinstance(r.get('attempts'), bool)]


def _write_leaderboard(records):
    tmp_path = f"{LEADERBOARD_FILE}.tmp.{os.getpid()}"
    with open(tmp_path, 'w') as f:
        json.dump(records, f)
    os.replace(tmp_path, LEADERBOARD_FILE)


def _submit_rate_ok(ip):
    return rate_limit.allow(f'games_submit:{ip}', 1, _SUBMIT_INTERVAL_SECS)


@games_bp.route('/api/games/leaderboard', methods=['GET'])
def get_leaderboard():
    data = _read_leaderboard()
    data.sort(key=lambda x: x['attempts'])
    return jsonify(data[:10])


@games_bp.route('/api/games/leaderboard', methods=['POST'])
def submit_score():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
    attempts = data.get('attempts')

    if type(attempts) is not int or not (1 <= attempts <= _MAX_ATTEMPTS):
        return jsonify({'success': False, 'error': 'Invalid attempts'}), 400

    if not _submit_rate_ok(request.remote_addr or ''):
        return jsonify({'success': False, 'error': 'Too many submissions; please wait a few seconds.'}), 429

    name = session.get('user', {}).get('name', 'User') if 'user' in session else 'User'
    name = (str(name or 'User').strip() or 'User')[:_MAX_NAME_LEN]

    record = {
        'name': name,
        'attempts': attempts,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    try:
        with _leaderboard_lock():
            records = _read_leaderboard(strict=True)
            records.append(record)
            # Keep only the best records (fewest attempts; earlier date wins ties).
            records.sort(key=lambda r: (r['attempts'], str(r.get('date', ''))))
            _write_leaderboard(records[:_MAX_LEADERBOARD_RECORDS])
    except _LeaderboardUnreadable:
        return jsonify({'success': False, 'error': 'Leaderboard temporarily unavailable'}), 503

    return jsonify({'success': True})
