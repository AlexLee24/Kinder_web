"""Development entry point: ``uv run python run.py`` (or ``python main.py``).

Production uses gunicorn with ``wsgi.py`` instead — see README.md.
"""
import os

from app import create_app
from app.config import config

app = create_app()


def main():
    print(f" * Local:   http://{config.HOST}:{config.PORT}")
    print(f" * Public:  {config.APP_BASE_URL}")
    try:
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)
    except KeyboardInterrupt:
        print(' * Shutting down')
    finally:
        os._exit(0)  # don't wait for background threads (NIST cache build, TNS sync)


if __name__ == '__main__':
    main()
