"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — lc_plotter (split from astronomy_tools_routes.py)."""
import os
import json
import uuid
import time
from werkzeug.security import generate_password_hash, check_password_hash
from flask import render_template, request, jsonify, session, abort, redirect, url_for
from . import astronomy_tools_bp
from .helpers import _SHARE_DIR, _SHARE_ID_RE, _SHARE_TTL_SECS


@astronomy_tools_bp.route('/lc_plotter')
def lc_plotter():
    from app.services.astro.filter_colors import all_colors
    from flask import session as flask_session
    user_email = flask_session.get('user', {}).get('email', '')
    return render_template('lc_plotter.html', current_path='/lc_plotter',
                           filter_colors=all_colors(), user_email=user_email)

@astronomy_tools_bp.route('/lc_plotter/mw_extinction', methods=['POST'])
def lc_plotter_mw_extinction():
    """Return per-filter Milky Way extinction A using SFD E(B-V) + SF11 ratios."""
    data = request.get_json(silent=True) or {}
    ra  = data.get('ra')
    dec = data.get('dec')
    filters = data.get('filters', [])
    if ra is None or dec is None:
        return jsonify({'error': 'ra and dec required'}), 400
    try:
        ra = float(ra); dec = float(dec)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid ra/dec'}), 400
    if not (0 <= ra <= 360) or not (-90 <= dec <= 90):
        return jsonify({'error': 'ra/dec out of range'}), 400
    from app.services.astro.ext_M_calculator import get_extinction
    result = {}
    for f in filters[:60]:
        if not isinstance(f, str) or len(f) > 20:
            continue
        try:
            result[f] = round(float(get_extinction(ra, dec, f)), 4)
        except Exception:
            result[f] = None
    return jsonify(result)

@astronomy_tools_bp.route('/lc_plotter/share', methods=['POST'])
def lc_plotter_share():
    if request.content_length and request.content_length > 8 * 1024 * 1024:
        return jsonify({'error': 'Payload too large'}), 413
    payload = request.get_json(silent=True)
    if not payload or 'traces' not in payload or 'layout' not in payload:
        return jsonify({'error': 'Invalid payload'}), 400
    os.makedirs(_SHARE_DIR, exist_ok=True)
    share_id = uuid.uuid4().hex[:24]
    path = os.path.join(_SHARE_DIR, f'{share_id}.json')
    raw_pw = (payload.get('password') or '').strip()
    pw_hash = generate_password_hash(raw_pw) if raw_pw else None
    with open(path, 'w') as f:
        json.dump({
            'traces': payload['traces'],
            'layout': payload['layout'],
            'isStatic': bool(payload.get('isStatic', False)),
            'created_at': time.time(),
            'password_hash': pw_hash,
        }, f)
    return jsonify({'id': share_id})

@astronomy_tools_bp.route('/lc_plotter/shared/<share_id>', methods=['GET', 'POST'])
def lc_plotter_shared(share_id):
    if not _SHARE_ID_RE.match(share_id):
        abort(404)
    path = os.path.join(_SHARE_DIR, f'{share_id}.json')
    if not os.path.isfile(path):
        abort(404)
    with open(path) as f:
        data = json.load(f)
    # Check 60-day expiry
    if time.time() - data.get('created_at', 0) > _SHARE_TTL_SECS:
        abort(410)
    has_password = bool(data.get('password_hash'))
    session_key = f'lcp_unlock_{share_id}'
    if request.method == 'POST':
        if not has_password:
            abort(400)
        entered = request.form.get('password', '')
        if check_password_hash(data['password_hash'], entered):
            session[session_key] = True
            return redirect(url_for('astronomy_tools.lc_plotter_shared', share_id=share_id))
        return render_template('shared_plot.html',
                               traces=None, layout=None,
                               is_static=data.get('isStatic', False),
                               share_id=share_id,
                               has_password=True, password_error=True, unlocked=False)
    # GET
    if has_password and not session.get(session_key):
        return render_template('shared_plot.html',
                               traces=None, layout=None,
                               is_static=data.get('isStatic', False),
                               share_id=share_id,
                               has_password=True, password_error=False, unlocked=False)
    return render_template('shared_plot.html',
                           traces=data['traces'],
                           layout=data['layout'],
                           is_static=data.get('isStatic', False),
                           share_id=share_id,
                           has_password=has_password, password_error=False, unlocked=True)
