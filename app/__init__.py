"""Kinder Web — Flask application package.

``create_app()`` is the application factory used by ``wsgi.py`` (gunicorn), ``run.py``
(development server) and the tests. Everything that used to happen at import time in the
old ``app/main.py`` now happens inside ``create_app()``, in the same order.

Package map::

    app/config.py        settings read from kinder.env
    app/paths.py         every on-disk location (+ vendored packages on sys.path)
    app/extensions.py    OAuth client
    app/core/            hooks, auth helpers, static files, logging, converters, validation
    app/db/              PostgreSQL access layer (auth / transient / obs / cat schemas)
    app/services/        domain logic (TNS sync, photometry, DETECT, planning, jobs, ...)
    app/blueprints/      one folder per site area: routes + templates + static
    app/vendor/          CASTOR (git clone) and DETECT (rsync copy)
"""
from . import paths  # noqa: F401  -- must be first: vendored packages on sys.path, DETECT_DATA_DIR default

import matplotlib
matplotlib.use('Agg')  # headless server; must run before any pyplot import

# CASTOR's moon.py builds astropy Time/AltAz frames for every calculation, which by
# default triggers astropy to try downloading fresh Earth-orientation (IERS) data from
# datacenter.iers.org on first use. On a server with no/unreliable outbound internet
# this makes every single ETC calculation eat a network timeout before it even starts,
# and repeats on every request once the on-disk IERS cache is stale — set once here,
# at process start, rather than left to astropy's per-call default. The bundled IERS
# table this falls back to is off by at most ~1 arcsec, negligible for airmass/moon
# geometry at the precision this tool needs.
from astropy.utils import iers
iers.conf.auto_download = False

from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app(start_jobs: bool = True) -> Flask:
    """Build the Flask app.

    ``start_jobs=False`` skips the background scheduler / daemon threads (tests, one-off
    scripts). Everything else is identical to production.
    """
    # Daily log file BEFORE anything else so all output (including print) is captured.
    from app.core.log_setup import setup_logging
    setup_logging(str(paths.LOG_DIR))

    from app.config import config
    from app.db import init_connection_pool, check_db_connection
    from app.core.converters import register_converters
    from app.core.template_filters import register_template_filters
    from app.core.static_files import register_static_route
    from app.core.hooks import register_hooks
    from app.extensions import oauth
    from app.blueprints import register_blueprints

    app = Flask(__name__, static_folder=None)  # templates come from each blueprint; /static is a custom route
    app.secret_key = config.SECRET_KEY
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # Secure requires HTTPS; local DEBUG runs over plain http://127.0.0.1, so only
    # enforce it outside of DEBUG (production sits behind an HTTPS-terminating proxy).
    app.config['SESSION_COOKIE_SECURE'] = not config.DEBUG
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

    # Check database connection on startup
    try:
        _db_connection_ok = check_db_connection()
    except Exception as exc:
        _db_connection_ok = False
        print(f"WARNING: Database connection check raised an exception: {exc}")
    if not _db_connection_ok:
        print("WARNING: Database connection failed. Application may not function correctly.")

    register_converters(app)

    # Initialize Kinder DB connection pool
    try:
        init_connection_pool()
    except Exception as exc:
        print(f"WARNING: Database connection pool could not be initialized: {exc}")

    register_static_route(app)
    register_template_filters(app)

    oauth.init_app(app)
    register_hooks(app)          # before/after request hooks + error handlers (order matters)
    register_blueprints(app)

    if start_jobs:
        from app.services.jobs.scheduler import start_background_jobs
        start_background_jobs(app)

    return app
