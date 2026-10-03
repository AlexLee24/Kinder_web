"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — lc_plotter (split from astronomy_tools_routes.py)."""
import os
import json
import uuid
import time
from werkzeug.security import generate_password_hash, check_password_hash
from flask import render_template, request, jsonify, session, abort, redirect, url_for, make_response
from app.core import rate_limit
from . import astronomy_tools_bp
from .helpers import _SHARE_DIR, _SHARE_ID_RE, _SHARE_TTL_SECS, _client_ip, _rate_ok_burst

_SHARE_MAX_BYTES = 8 * 1024 * 1024
_SHARE_MAX_PASSWORD_LEN = 200
_SHARE_PURGE_INTERVAL_SECS = 3600
_last_share_purge = 0.0

# Shared plots render third-party-supplied Plotly JSON: only plain 2D (non-WebGL) trace
# types are accepted, and layout images (arbitrary URLs) are dropped.
_SHARE_ALLOWED_TRACE_TYPES = frozenset({
    'scatter', 'bar', 'histogram', 'box', 'violin', 'heatmap', 'contour',
})

# Per-response CSP for the shared-plot page (overrides the global one).
_SHARED_PLOT_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.plot.ly; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'self'"          # the password gate POSTs back to this page
)


def _strip_layout_images(layout):
    if not isinstance(layout, dict):
        return {}
    layout = dict(layout)
    layout.pop('images', None)
    tmpl = layout.get('template')
    if isinstance(tmpl, dict):
        tmpl = dict(tmpl)
        tl = tmpl.get('layout')
        if isinstance(tl, dict):
            tl = dict(tl)
            tl.pop('images', None)
            tmpl['layout'] = tl
        tmpl.pop('data', None)   # template trace defaults could smuggle other trace types
        layout['template'] = tmpl
    return layout


def _sanitize_share_plot(traces, layout):
    """Return (traces, layout) restricted to safe content, or (None, None) if a trace
    uses a disallowed type."""
    clean = []
    for t in traces:
        if not isinstance(t, dict):
            return None, None
        ttype = t.get('type', 'scatter')
        if ttype not in _SHARE_ALLOWED_TRACE_TYPES:
            return None, None
        clean.append(t)
    return clean, _strip_layout_images(layout)


def _shared_plot_response(**ctx):
    resp = make_response(render_template('shared_plot.html', **ctx))
    resp.headers['Content-Security-Policy'] = _SHARED_PLOT_CSP
    return resp


def _purge_expired_shares():
    """Opportunistically delete share files older than the TTL (at most once per interval)."""
    global _last_share_purge
    now = time.time()
    if now - _last_share_purge < _SHARE_PURGE_INTERVAL_SECS:
        return
    _last_share_purge = now
    try:
        names = os.listdir(_SHARE_DIR)
    except OSError:
        return
    for name in names:
        if not name.endswith('.json'):
            continue
        fp = os.path.join(_SHARE_DIR, name)
        try:
            if now - os.path.getmtime(fp) > _SHARE_TTL_SECS:
                os.remove(fp)
        except OSError:
            pass


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
    if not isinstance(data, dict):
        return jsonify({'error': 'invalid request'}), 400
    ra  = data.get('ra')
    dec = data.get('dec')
    filters = data.get('filters', [])
    if not isinstance(filters, list):
        return jsonify({'error': 'filters must be a list'}), 400
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
    if 'user' not in session:
        return jsonify({'error': 'Please log in to create share links.'}), 401
    if not _rate_ok_burst(_client_ip(), 'lc_share', 5, 60.0):
        return jsonify({'error': 'Too many share requests; please wait a minute.'}), 429
    if request.content_length is None:
        return jsonify({'error': 'Content-Length required'}), 411
    if request.content_length > _SHARE_MAX_BYTES:
        return jsonify({'error': 'Payload too large'}), 413
    raw = request.get_data(cache=False)
    if len(raw) > _SHARE_MAX_BYTES:
        return jsonify({'error': 'Payload too large'}), 413
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return jsonify({'error': 'Invalid payload'}), 400
    if (not isinstance(payload, dict) or not isinstance(payload.get('traces'), list)
            or not isinstance(payload.get('layout'), dict)):
        return jsonify({'error': 'Invalid payload'}), 400
    traces, layout = _sanitize_share_plot(payload['traces'], payload['layout'])
    if traces is None:
        return jsonify({'error': 'Unsupported trace type in plot'}), 400
    raw_pw = payload.get('password') or ''
    if not isinstance(raw_pw, str) or len(raw_pw) > _SHARE_MAX_PASSWORD_LEN:
        return jsonify({'error': 'Invalid password'}), 400
    os.makedirs(_SHARE_DIR, exist_ok=True)
    _purge_expired_shares()
    share_id = uuid.uuid4().hex[:24]
    path = os.path.join(_SHARE_DIR, f'{share_id}.json')
    raw_pw = raw_pw.strip()
    pw_hash = generate_password_hash(raw_pw) if raw_pw else None
    with open(path, 'w') as f:
        json.dump({
            'traces': traces,
            'layout': layout,
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
    if not isinstance(data, dict):
        abort(404)
    try:
        created_at = float(data.get('created_at', 0) or 0)
    except (TypeError, ValueError):
        created_at = 0
    if time.time() - created_at > _SHARE_TTL_SECS:
        try:
            os.remove(path)
        except OSError:
            pass
        abort(410)
    has_password = bool(data.get('password_hash'))
    session_key = f'lcp_unlock_{share_id}'
    if request.method == 'POST':
        if not has_password:
            abort(400)
        if not rate_limit.allow(f'lc_share_pw:{share_id}:{_client_ip()}', 10, 600):
            abort(429)
        entered = request.form.get('password', '')
        if check_password_hash(data['password_hash'], entered):
            session[session_key] = True
            return redirect(url_for('astronomy_tools.lc_plotter_shared', share_id=share_id))
        return _shared_plot_response(
            traces=None, layout=None,
            is_static=data.get('isStatic', False),
            share_id=share_id,
            has_password=True, password_error=True, unlocked=False)
    # GET
    if has_password and not session.get(session_key):
        return _shared_plot_response(
            traces=None, layout=None,
            is_static=data.get('isStatic', False),
            share_id=share_id,
            has_password=True, password_error=False, unlocked=False)
    # Re-sanitize on the way out too: shares created before the whitelist existed.
    traces, layout = _sanitize_share_plot(data.get('traces') or [], data.get('layout') or {})
    if traces is None:
        abort(404)
    return _shared_plot_response(
        traces=traces,
        layout=layout,
        is_static=data.get('isStatic', False),
        share_id=share_id,
        has_password=has_password, password_error=False, unlocked=True)
