"""Admin panel actions — panel (split from admin_routes.py)."""
from flask import render_template, redirect, url_for, session, flash
from app.db.auth import (
    get_users,
    get_groups,
    get_invitations,
    get_setting,
    get_group_requests,
    get_api_key_requests,
)
from . import admin_bp


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
                         open_registration=open_registration)
