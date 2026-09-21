"""WSGI entry point for gunicorn, run from the project root::

    gunicorn --workers 4 --worker-class gthread --threads 4 --bind 127.0.0.1:8000 wsgi:app
"""
from app import create_app

app = create_app()
