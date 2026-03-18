# ===============================================================================
# IMPORTS AND CONFIGURATION
# ===============================================================================
from flask import Flask
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
import sys
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
from modules.web_postgres_database import init_database
from modules.postgres_database import init_tns_database, check_db_connection

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
# DAILY BACKUP SCHEDULER
# ===============================================================================
from apscheduler.schedulers.background import BackgroundScheduler
from modules.backup import run_daily_backup
from modules.phot_scheduler import fetch_inbox_photometry

_scheduler = BackgroundScheduler(daemon=True)
_scheduler.add_job(run_daily_backup, 'cron', hour=3, minute=0, id='daily_backup')
_scheduler.add_job(fetch_inbox_photometry, 'cron', hour=3, minute=30, id='daily_phot_fetch')
_scheduler.start()
run_daily_backup()  # run once immediately on startup

# ===============================================================================
# APPLICATION STARTUP
# ===============================================================================

if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
