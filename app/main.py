"""Backward-compatible entry point.

Older deployments start the site from inside ``app/`` with ``gunicorn main:app`` or
``python app/main.py``. Both still work through this shim, but new setups should use the
project-root entry points ``wsgi.py`` (gunicorn) and ``run.py`` (development server).
The application itself is built by ``app.create_app()`` (see ``app/__init__.py``).
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app import create_app  # noqa: E402
from app.config import config  # noqa: E402

app = create_app()

if __name__ == '__main__':
    print(f" * Local:   http://{config.HOST}:{config.PORT}")
    print(f" * Public:  {config.APP_BASE_URL}")
    try:
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)
    except KeyboardInterrupt:
        print(' * Shutting down')
    finally:
        os._exit(0)  # don't wait for background threads (NIST cache build, TNS sync)
