"""Admin panel actions — panel (split from admin_routes.py)."""
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, render_template, session, url_for

from app.db.auth import (
    get_api_key_requests,
    get_group_requests,
    get_groups,
    get_invitations,
    get_setting,
    get_users,
)

from . import admin_bp


def _as_utc(value):
    """ISO string / datetime -> aware UTC datetime (None if missing or unparsable)."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _overview_stats(users, groups, group_requests, api_key_requests):
    """Numbers for the Overview tiles and the Users header (all computed from data already loaded)."""
    now = datetime.now(timezone.utc)
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    rows = list(users.values())
    last_login = [_as_utc(u.get('last_login')) for u in rows]
    joined = [_as_utc(u.get('join_date')) for u in rows]
    return {
        'users': len(rows),
        'admins': sum(1 for u in rows if u.get('is_admin')),
        'members': sum(1 for u in rows if not u.get('is_admin') and u.get('role') == 'user'),
        'guests': sum(1 for u in rows if not u.get('is_admin') and u.get('role', 'guest') == 'guest'),
        'api_keys': sum(1 for u in rows if u.get('has_api_key')),
        'active_7d': sum(1 for t in last_login if t and t >= week),
        'new_30d': sum(1 for t in joined if t and t >= month),
        'groups': len(groups),
        'memberships': sum(len(g.get('members') or []) for g in groups.values()),
        'pending': len(group_requests) + len(api_key_requests),
    }


def _recent_users(users, limit=6):
    """Most recent sign-ins first (users that never logged in are left out)."""
    seen = [(t, email, u) for email, u in users.items() if (t := _as_utc(u.get('last_login')))]
    seen.sort(key=lambda r: r[0], reverse=True)
    return [dict(u, email=email, last_login_iso=t.isoformat()) for t, email, u in seen[:limit]]


# ===============================================================================
# ADMIN PANEL
# ===============================================================================
@admin_bp.route('/admin')
def admin_panel():
    if 'user' not in session or not session['user'].get('is_admin'):
        flash('Access denied. Administrator privileges required.', 'error')
        return redirect(url_for('basic.home'))

    users = get_users()
    groups = get_groups()
    invitations = get_invitations()
    group_requests = get_group_requests()
    api_key_requests = get_api_key_requests()

    current_user_email = session['user']['email']

    open_registration = get_setting('open_registration', 'true') == 'true'

    return render_template('admin.html',
                         current_path='/admin',
                         users=users,
                         groups=groups,
                         invitations=invitations,
                         group_requests=group_requests,
                         api_key_requests=api_key_requests,
                         current_user_email=current_user_email,
                         open_registration=open_registration,
                         stats=_overview_stats(users, groups, group_requests, api_key_requests),
                         recent_users=_recent_users(users))
