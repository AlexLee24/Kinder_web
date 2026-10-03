"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — helpers (split from object_routes.py)."""
import math


# ===============================================================================
# OBJECT DATA API
# ===============================================================================
def sanitize_for_json(data):
    """Convert NaN and Inf values to None for JSON serialization"""
    if isinstance(data, list):
        return [sanitize_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {key: sanitize_for_json(value) for key, value in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    return data


# ===============================================================================
# OBJECT-LEVEL PERMISSIONS
# ===============================================================================
def resolve_object_name(object_name):
    """Return the canonical ``transient.objects.name`` for a URL name
    (``2024abc``, ``AT2024abc``, ``SN 2024abc`` …), or None when unknown."""
    from app.db import get_db_connection
    name = (object_name or '').strip()
    if not name:
        return None
    # Escape LIKE wildcards: ILIKE is only used for case-insensitivity here.
    pat = name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM transient.objects "
            "WHERE name = %s OR name ILIKE %s "
            "   OR (COALESCE(name_prefix, '') || COALESCE(name, '')) ILIKE %s "
            "ORDER BY (name = %s) DESC LIMIT 1",
            (name, pat, pat.replace(' ', ''), name)
        )
        row = cur.fetchone()
    return row[0] if row else None


def can_access_object(object_name, user_email=None):
    """``check_object_access`` on the canonical object name (anonymous included)."""
    from app.db.auth import check_object_access
    try:
        canonical = resolve_object_name(object_name)
    except Exception:
        return False
    if canonical is None:
        return False
    return check_object_access(canonical, user_email)


def session_can_access_object(object_name):
    """``can_access_object`` for the current session user (None when anonymous)."""
    from flask import session
    user = session.get('user') or {}
    return can_access_object(object_name, user.get('email'))


def non_guest_required(view=None, *, error='Access denied', status=403):
    """JSON API guard: logged-in, non-guest users (admins included) only."""
    from functools import wraps
    from flask import jsonify
    from app.core.auth import is_non_guest

    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_non_guest():
                return jsonify({'error': error}), status
            return fn(*args, **kwargs)
        return wrapper
    return decorate(view) if view is not None else decorate
