import os
from dotenv import load_dotenv

from app.paths import ENV_FILE

# The one place kinder.env is loaded (app/db imports this module for the same reason).
# override=True: values in kinder.env win over stale variables inherited from the shell.
load_dotenv(ENV_FILE, override=True)

# Placeholder shipped in old configs; never acceptable as a real signing key.
INSECURE_SECRET_KEYS = frozenset({'', 'your-very-secure-secret-key'})

class Config:
    # Application settings
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = int(os.getenv('PORT', '5000'))

    # Public base URL used to build absolute links (e.g. OAuth redirect_uri).
    # Must NOT be derived from the request's Host header (host header injection).
    APP_BASE_URL = os.getenv('APP_BASE_URL', f'http://{HOST}:{PORT}')

    # Flask settings
    # No default: create_app() refuses to start without a real key (except under tests).
    SECRET_KEY = os.getenv('SECRET_KEY', '')
    
    # Google OAuth
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    
    # Email settings
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SENDER_EMAIL = os.getenv('SENDER_EMAIL')
    SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
    
    # Session cookie: Secure (HTTPS only) by default; DEBUG defaults to False so the
    # local http://127.0.0.1 dev server still works. Override with SESSION_COOKIE_SECURE.
    SESSION_COOKIE_SECURE = os.getenv(
        'SESSION_COOKIE_SECURE', 'false' if DEBUG else 'true'
    ).strip().lower() in {'1', 'true', 'yes', 'on'}

    # Admin settings
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
    ADMIN_LOCAL_EMAIL = os.getenv('ADMIN_LOCAL_EMAIL')
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

config = Config()