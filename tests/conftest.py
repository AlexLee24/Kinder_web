"""Shared pytest fixtures.

The tests build the app with ``create_app(start_jobs=False)`` and talk to the real
Kinder database (there is no test database), exactly like the old root-level
``test_detect_pages.py`` did. They are read-only: only GET requests, no decision
endpoints. Run them with::

    .venv/bin/python -m pytest -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DETECT_IN_WEB", "1")

BASE_URL = "http://localhost:8000"  # must be one of the allowed hosts (DEBUG) or APP_BASE_URL

PERSONAS = {
    "anon": None,
    "guest": {"email": "smoke-guest@kinder.test", "name": "Smoke Guest", "role": "guest",
              "is_admin": False, "is_great_lab_member": False, "groups": [], "picture": ""},
    "member": {"email": "smoke-member@kinder.test", "name": "Smoke Member", "role": "user",
               "is_admin": False, "is_great_lab_member": True, "groups": ["GREAT_Lab"], "picture": ""},
    "admin": {"email": "smoke-admin@kinder.test", "name": "Smoke Admin", "role": "admin",
              "is_admin": True, "is_great_lab_member": True, "groups": ["GREAT_Lab"], "picture": ""},
}


@pytest.fixture(scope="session")
def app():
    from app import create_app
    a = create_app(start_jobs=False)
    a.config["TESTING"] = True
    return a


def _client_as(app, persona):
    c = app.test_client()
    user = PERSONAS[persona]
    if user:
        with c.session_transaction() as s:
            s["user"] = dict(user)
    return c


@pytest.fixture
def client(app):
    """Anonymous client."""
    return _client_as(app, "anon")


@pytest.fixture
def admin_client(app):
    """Client with a fake admin session (no login round-trip)."""
    return _client_as(app, "admin")


@pytest.fixture
def client_factory(app):
    """``client_factory('member')`` -> test client logged in as that persona."""
    return lambda persona: _client_as(app, persona)
