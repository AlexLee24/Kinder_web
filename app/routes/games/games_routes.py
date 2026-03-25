"""
Games routes
"""
import os
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session

games_bp = Blueprint('games', __name__, template_folder='templates', static_folder='static')

LEADERBOARD_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', '1a2b_leaderboard.json')


@games_bp.route('/games')
def games():
    return render_template('games.html', current_path='/games')


@games_bp.route('/api/games/leaderboard', methods=['GET'])
def get_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, 'r') as f:
            try:
                data = json.load(f)
            except Exception:
                data = []
    else:
        data = []
    data.sort(key=lambda x: x['attempts'])
    return jsonify(data[:10])


@games_bp.route('/api/games/leaderboard', methods=['POST'])
def submit_score():
    data = request.json
    attempts = data.get('attempts')

    if not attempts or not isinstance(attempts, int):
        return jsonify({'success': False, 'error': 'Invalid attempts'}), 400

    name = session.get('user', {}).get('name', 'User') if 'user' in session else 'User'

    record = {
        'name': name,
        'attempts': attempts,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    records = []
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, 'r') as f:
            try:
                records = json.load(f)
            except Exception:
                pass

    records.append(record)
    os.makedirs(os.path.dirname(LEADERBOARD_FILE), exist_ok=True)

    with open(LEADERBOARD_FILE, 'w') as f:
        json.dump(records, f)

    return jsonify({'success': True})
