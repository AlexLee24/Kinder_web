"""Development entry point (same as run.py): ``uv run python main.py``.

Production: ``gunicorn wsgi:app`` from this directory. Logs go to app/log/<date>.log
AND to the terminal (stderr) in both cases.
"""
from run import app, main  # noqa: F401  -- `app` re-exported for `gunicorn main:app`

if __name__ == '__main__':
    main()
