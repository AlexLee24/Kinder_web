"""Admin panel actions — helpers (split from admin_routes.py)."""
import logging
import threading

from flask import g, jsonify, request, session
from app.db.auth import get_user, get_users

_audit_logger = logging.getLogger('app.audit')


def audit(action: str, target: str | None = None, detail: str = '') -> None:
    """One audit line per security-relevant admin action (actor, target, change, IP)."""
    actor = (session.get('user') or {}).get('email', 'anon')
    _audit_logger.info('audit action=%s actor=%s target=%s ip=%s %s',
                       action, actor, target or '-', request.remote_addr or '-', detail)


def _caller_is_super_admin() -> bool:
    me = getattr(g, 'current_user', None)
    if not me or me.get('email') != (session.get('user') or {}).get('email'):
        me = get_user((session.get('user') or {}).get('email')) or {}
    return bool(me.get('is_super_admin'))


def privileged_target_denied(target_email: str, what: str = 'manage another admin'):
    """Acting on an admin / super admin account requires a super admin caller.

    Returns a 403 JSON response to send back, or None when allowed. The caller's
    own account is always allowed here (self-specific limits live in the route)."""
    if target_email == (session.get('user') or {}).get('email'):
        return None
    target = get_user(target_email) or {}
    if not target.get('is_admin'):
        return None
    if _caller_is_super_admin():
        return None
    audit('denied', target_email, f'reason=not_super_admin attempted={what}')
    return jsonify({'error': f'Only a super admin can {what}.'}), 403


def update_user_session_groups(user_email):
    """Helper function to update user session with current group information"""
    if 'user' in session and session['user']['email'] == user_email:
        users = get_users()
        if user_email in users:
            session['user']['groups'] = users[user_email].get('groups', [])

# ===============================================================================
# TNS MANUAL OPERATIONS
# ===============================================================================
_tns_task_status = {'running': False, 'message': ''}

# ===============================================================================
# DETECT (embedded pipeline) STATUS + MANUAL RUNS
# ===============================================================================

_detect_manual = {'running': False, 'message': ''}

# Guards the check-and-set of the 'running' flags above so two concurrent
# requests can't both start a background task.
_task_lock = threading.Lock()


def _claim_task(status: dict) -> bool:
    """Atomically mark *status* as running. False if it already was."""
    with _task_lock:
        if status['running']:
            return False
        status['running'] = True
        status['message'] = 'Running...'
        return True


def _start_claimed_task(status: dict, target, **thread_kwargs) -> None:
    """Start *target* in a daemon thread; release the claim if the start fails.
    *target* must reset ``status['running']`` in its own ``finally``."""
    try:
        threading.Thread(target=target, daemon=True, **thread_kwargs).start()
    except Exception:
        status['running'] = False
        raise

# ===============================================================================
# SCHEDULED JOBS STATUS
# ===============================================================================

# (label, schedule_desc, trigger_type, trigger_kwargs)
_SCHEDULED_JOBS = {
    'daily_backup':                 ('Daily Backup',              'Daily 03:00 UTC',  'cron',     {'hour': 3,  'minute': 0}),
    'daily_phot_fetch':             ('Inbox Photometry Fetch',    'Daily 03:30 UTC',  'cron',     {'hour': 3,  'minute': 30}),
    'daily_target_mag_update':      ('Update Target Mags',        'Daily 05:00 UTC',  'cron',     {'hour': 5,  'minute': 0}),
    'daily_retire_stale_followups': ('Retire Stale Follow-ups',   'Daily 05:30 UTC',  'cron',     {'hour': 5,  'minute': 30}),
    'daily_host_redshift_sync':     ('Host Redshift Sync',        'Daily 06:00 UTC',  'cron',     {'hour': 6,  'minute': 0}),
    'db_monitor':                   ('DB Health Monitor',         'Every 10 min',     'interval', {'minutes': 10}),
    'db_recycle':                   ('DB Connection Recycle',     'Every 30 min',     'interval', {'minutes': 30}),
    'detect_page_prewarm':          ('Detect Page Prewarm',       'Every 30 min',     'interval', {'minutes': 30}),
    'daily_detect_followups':       ('DETECT: Follow-up re-screen', 'Daily 04:00 UTC', 'cron',     {'hour': 4,  'minute': 0}),
}
