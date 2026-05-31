# ===============================================================================
# IMPORTS AND CONFIGURATION
# ===============================================================================
from flask import Flask, send_from_directory, abort, request, g, session
from dotenv import load_dotenv
import os
import sys
import time
import logging
from werkzeug.routing import BaseConverter
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '..', 'kinder.env'))

# Setup path
sys.path.append(os.path.join(current_dir, "modules"))
sys.path.append(os.path.join(current_dir, "modules", "DETECT_pipe", "modules"))

# Setup daily log file BEFORE other imports so all output is captured
from modules.log_setup import setup_logging
setup_logging(os.path.join(current_dir, 'log'))

# Import modules
from modules.config import config
from modules.database import init_connection_pool, check_db_connection

# Create Flask app
app = Flask(__name__, template_folder='html', static_folder=None)
app.secret_key = config.SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Check database connection on startup
try:
    _db_connection_ok = check_db_connection()
except Exception as exc:
    _db_connection_ok = False
    print(f"WARNING: Database connection check raised an exception: {exc}")

if not _db_connection_ok:
    print("WARNING: Database connection failed. Application may not function correctly.")

# Custom URL converter for TNS object names (supports both upper and lowercase letters)
class AlphaConverter(BaseConverter):
    def __init__(self, url_map): #, minlength=1, maxlength=None
        super(AlphaConverter, self).__init__(url_map)
        self.regex = r'[a-zA-Z]+'

app.url_map.converters['alpha'] = AlphaConverter

# Initialize Kinder DB connection pool
try:
    init_connection_pool()
except Exception as exc:
    print(f"WARNING: Database connection pool could not be initialized: {exc}")

_BLUEPRINT_STATIC_DIRS = [
    os.path.join(current_dir, 'routes', 'basic', 'static'),
    os.path.join(current_dir, 'routes', 'auth', 'static'),
    os.path.join(current_dir, 'routes', 'astronomy_tools', 'static'),
    os.path.join(current_dir, 'routes', 'marshal', 'static'),
    os.path.join(current_dir, 'routes', 'detect', 'static'),
    os.path.join(current_dir, 'routes', 'games', 'static'),
    os.path.join(current_dir, 'routes', 'private_area', 'static'),
    os.path.join(current_dir, 'routes', 'planners', 'static'),
    os.path.join(current_dir, 'routes', 'web_api', 'static'),
]
_PHOTO_DIR = os.path.abspath(os.path.join(current_dir, '..', 'photo'))

@app.route('/static/<path:filename>', endpoint='static')
def serve_static_files(filename):
    for directory in _BLUEPRINT_STATIC_DIRS:
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            return send_from_directory(directory, filename)
    # Root-level photo/ directory
    if filename.startswith('photo/'):
        photo_name = filename[len('photo/'):]
        photo_path = os.path.join(_PHOTO_DIR, photo_name)
        if os.path.isfile(photo_path):
            return send_from_directory(_PHOTO_DIR, photo_name)
    # Icon files from basic/icon/
    if filename.startswith('icon/'):
        icon_name = filename[len('icon/'):]
        icon_dir = os.path.join(current_dir, 'routes', 'basic', 'icon')
        icon_path = os.path.join(icon_dir, icon_name)
        if os.path.isfile(icon_path):
            return send_from_directory(icon_dir, icon_name)
    abort(404)

import re
@app.template_filter('regex_search')
def regex_search(s, pattern):
    if not s:
        return None
    match = re.search(pattern, s)
    if match:
        return match.groups()
    return None

# ===============================================================================
# OAUTH CONFIGURATION
# ===============================================================================
from routes.auth.auth_routes import oauth, refresh_user_session
oauth.init_app(app)

# Register session refresh globally so g.current_user (including DB picture) is
# available on every request regardless of which blueprint handles it.
app.before_request(refresh_user_session)

_access_logger = logging.getLogger('web.request')
_ACCESS_SKIP_PREFIXES = ('/static/', '/api/log/content', '/api/log/daemon/content')
_ACCESS_LOG_ENABLED = os.getenv('ACCESS_LOG_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


@app.before_request
def _mark_request_start():
    g._req_start_monotonic = time.monotonic()


@app.after_request
def _log_request_access(response):
    if not _ACCESS_LOG_ENABLED:
        return response
    path = request.path or ''
    if path.startswith(_ACCESS_SKIP_PREFIXES):
        return response
    start = getattr(g, '_req_start_monotonic', None)
    duration_ms = int((time.monotonic() - start) * 1000) if start is not None else -1
    user_email = (session.get('user') or {}).get('email', 'anon')
    user_agent = (request.user_agent.string or '-')[:120]
    _access_logger.info(
        'event=http_access method=%s path=%s status=%s duration_ms=%s bytes=%s ip=%s user=%s ua="%s"',
        request.method,
        path,
        response.status_code,
        duration_ms,
        response.calculate_content_length() or 0,
        request.headers.get('X-Forwarded-For', request.remote_addr or '-'),
        user_email,
        user_agent,
    )
    return response

# ===============================================================================
# REGISTER ALL ROUTES
# ===============================================================================
from routes import register_routes
register_routes(app)

# ===============================================================================
# DAILY BACKUP SCHEDULER
# ===============================================================================
import fcntl
from apscheduler.schedulers.background import BackgroundScheduler
from modules.backup import run_daily_backup
from modules.phot_scheduler import fetch_inbox_photometry, update_target_mags, retire_stale_followups
# from modules.GCN_alert import start_gcn_listener  # reserved for future use
from modules.auto_tns_download import start_auto_tns_downloader
from modules.tns_gap_filler import start_gap_filler
from modules.db_monitor import check_and_alert as _db_check_and_alert
from modules.database import recycle_idle_connections as _db_recycle
from modules.database.transient import sync_host_redshifts

# Use a file lock to prevent duplicate background jobs when multiple processes
# import this module (e.g. gunicorn multi-worker, process manager restart race).
_bg_lock_path = os.path.join(current_dir, 'log', '.background_jobs.lock')
_bg_lock_fd = open(_bg_lock_path, 'w')
try:
    fcntl.flock(_bg_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    _acquired_bg_lock = True
except OSError:
    _acquired_bg_lock = False

if _acquired_bg_lock:
    _scheduler = BackgroundScheduler(daemon=True)
    if not config.DEBUG:
        _scheduler.add_job(run_daily_backup,         'cron', hour=3, minute=0,  id='daily_backup')
        _scheduler.add_job(fetch_inbox_photometry,   'cron', hour=3, minute=30, id='daily_phot_fetch')
        # _scheduler.add_job(fetch_missing_photometry, 'cron', minute=0,          id='hourly_missing_phot')
        _scheduler.add_job(update_target_mags,       'cron', hour=5, minute=0,  id='daily_target_mag_update')
        _scheduler.add_job(retire_stale_followups,   'cron', hour=5, minute=30, id='daily_retire_stale_followups')
        _scheduler.add_job(sync_host_redshifts,  'cron',     hour=6,   minute=0, id='daily_host_redshift_sync')
        _scheduler.add_job(_db_check_and_alert,  'interval', minutes=10,  id='db_monitor')
        _scheduler.add_job(_db_recycle,          'interval', minutes=30,  id='db_recycle')
    _scheduler.start()
    if not config.DEBUG:
        run_daily_backup()  # run once immediately on startup
        # start_gcn_listener(log_dir=os.path.join(current_dir, 'log'))
        start_auto_tns_downloader(log_dir=os.path.join(current_dir, 'log'))
        start_gap_filler(log_dir=os.path.join(current_dir, 'log'))
    else:
        print("DEBUG mode: all background scheduled jobs are disabled.")
else:
    print(f"[PID {os.getpid()}] Background jobs already running in another process, skipping.")

# ===============================================================================
# APPLICATION STARTUP
# ===============================================================================

if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
