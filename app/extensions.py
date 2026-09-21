"""Flask extension objects shared across blueprints.

Created here without an app; ``create_app()`` calls ``oauth.init_app(app)``.
"""
from authlib.integrations.flask_client import OAuth

from app.config import config

oauth = OAuth()

# Google OpenID Connect client (used by app.blueprints.auth.routes).
google = oauth.register(
    name='google',
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'code_challenge_method': 'S256',
    },
)
