"""Settings page (/settings, after EAU's): background, background mask, accent colour, glass colour and opacity.

Changes apply at once in the browser (js/ui_prefs.js) and are saved 0.4 s later: signed-in users on the server
(one JSON row per account in auth.system_settings, key ``ui_prefs:<email>``), everyone also in localStorage.
Registered on basic_bp (imported by the package __init__).
"""
import json
import re

from flask import jsonify, render_template, request, session

from app.db.auth import get_setting, set_setting

from .routes import basic_bp

DEFAULTS = {'bg': 'photo', 'bg_color': '#06060C', 'accent': '#F39F5A', 'glass': 70, 'glass_color': '#0E0E12', 'mask': 60}
BACKGROUNDS = ('photo', 'plain', 'color')
_HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')


def _key(email: str) -> str:
    return 'ui_prefs:' + email.lower()


def _clean(raw: dict) -> dict:
    """Keep known keys with valid values; anything else falls back to the default."""
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    if raw.get('bg') in BACKGROUNDS:
        out['bg'] = raw['bg']
    for k in ('bg_color', 'accent', 'glass_color'):
        v = raw.get(k)
        if isinstance(v, str) and _HEX.match(v):
            out[k] = v.upper()
    for k, lo, hi in (('glass', 40, 95), ('mask', 0, 85)):
        try:
            out[k] = max(lo, min(hi, int(raw.get(k, out[k]))))
        except (TypeError, ValueError):
            pass
    return out


def _email():
    return (session.get('user') or {}).get('email')


@basic_bp.app_template_global('ui_prefs')
def ui_prefs():
    """Templates: the signed-in user's saved settings, or None (the browser then reads localStorage)."""
    email = _email()
    if not email:
        return None
    cached = session.get('ui_prefs')          # read the DB once per session, not on every page
    if isinstance(cached, dict) and cached.get('_for') == email:
        return cached.get('prefs')
    prefs = None
    raw = get_setting(_key(email))
    if raw:
        try:
            prefs = _clean(json.loads(raw))
        except ValueError:
            prefs = None
    session['ui_prefs'] = {'_for': email, 'prefs': prefs}
    return prefs


@basic_bp.route('/settings')
def settings():
    return render_template('settings.html', defaults=DEFAULTS)


@basic_bp.route('/api/settings/ui', methods=['POST'])
def api_settings_save():
    email = _email()
    if not email:
        return jsonify(ok=False, error='login'), 401
    prefs = _clean(request.get_json(silent=True) or {})
    if not set_setting(_key(email), json.dumps(prefs)):
        return jsonify(ok=False, error='db'), 503
    session['ui_prefs'] = {'_for': email, 'prefs': prefs}
    return jsonify(ok=True, prefs=prefs)
