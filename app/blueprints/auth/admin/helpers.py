"""Admin panel actions — helpers (split from admin_routes.py)."""
from flask import session
from app.db.auth import get_users


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
