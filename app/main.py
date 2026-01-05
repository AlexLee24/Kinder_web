# ===============================================================================
# IMPORTS AND CONFIGURATION
# ===============================================================================
from flask import Flask
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
import atexit
from werkzeug.routing import BaseConverter
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
# Use relative path to kinder.env (1 level up from app/)
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', 'kinder.env'))
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, "modules"))
# Add DETECT_pipe modules to path
sys.path.append(os.path.join(current_dir, "modules", "DETECT_pipe", "modules"))

# Import modules
from modules.config import config
from modules.database import init_database
from modules.postgres_database import init_tns_database, check_db_connection
from modules.calendar_database import init_calendar_database

try:
    from modules.DETECT_pipe.modules._daily_run import daily_run
except ImportError as e:
    print(f"Warning: Could not import daily_run: {e}")
    def daily_run(): pass

# Create Flask app
app = Flask(__name__, template_folder='html', static_folder='static')
app.secret_key = config.SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Check database connection on startup
if not check_db_connection():
    print("WARNING: Database connection failed. Application may not function correctly.")

# Custom URL converter for TNS object names (supports both upper and lowercase letters)
class AlphaConverter(BaseConverter):
    def __init__(self, url_map, minlength=1, maxlength=None):
        super(AlphaConverter, self).__init__(url_map)
        self.regex = r'[a-zA-Z]+'

app.url_map.converters['alpha'] = AlphaConverter

# Initialize databases
init_database()
init_tns_database()
init_calendar_database()

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
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# ===============================================================================
# REGISTER ALL ROUTES
# ===============================================================================
from routes import register_routes
register_routes(app)

# ===============================================================================
# SCHEDULER CONFIGURATION
# ===============================================================================
def init_scheduler():
    try:
        scheduler = BackgroundScheduler()
        # Run at 02:00 UTC daily
        scheduler.add_job(func=daily_run, trigger="cron", hour=2, minute=0, timezone='UTC')
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())
        print("Scheduler started: daily_run scheduled for 02:00 UTC")
    except Exception as e:
        print(f"Failed to start scheduler: {e}")

# Initialize scheduler (ensure it only runs once in production/debug)
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    init_scheduler()

# ===============================================================================
# APPLICATION STARTUP
# ===============================================================================

if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
