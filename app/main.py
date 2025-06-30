# ===============================================================================
# IMPORTS AND CONFIGURATION
# ===============================================================================
from flask import Flask
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
import atexit
from werkzeug.routing import BaseConverter

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Import modules
from modules.config import config
from modules.database import init_database
from modules.tns_database import init_tns_database
from modules.tns_scheduler import tns_scheduler
from modules.auto_snooze_scheduler import auto_snooze_scheduler
from modules.calendar_database import init_calendar_database

# Create Flask app
app = Flask(__name__, template_folder='html', static_folder='static')
app.secret_key = config.SECRET_KEY

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

# Start schedulers
tns_scheduler.start_scheduler()
auto_snooze_scheduler.start_scheduler()

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
# APPLICATION STARTUP
# ===============================================================================
# Register cleanup functions
atexit.register(lambda: tns_scheduler.stop_scheduler())
atexit.register(lambda: auto_snooze_scheduler.stop_scheduler())

if __name__ == '__main__':
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
