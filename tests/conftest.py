"""Shared pytest fixtures.

The tests build the app with ``create_app(start_jobs=False)`` and talk to the real
Kinder database (there is no test database), exactly like the old root-level
``test_detect_pages.py`` did. They are read-only: only GET requests, no decision
endpoints. Run them with::

    .venv/bin/python -m pytest -q
"""
import os
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DETECT_IN_WEB", "1")
# create_app() refuses to start without a real SECRET_KEY outside of tests.
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("SECRET_KEY", "pytest-only-secret-key-not-for-production")
# The Host check only admits APP_BASE_URL (or local hosts in DEBUG); without a kinder.env
# point it at the test BASE_URL below.
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000")
# Rate-limit hits go to a throw-away file (not the dev server's app/data/rate_limit.sqlite3),
# emptied before every test: all personas share one IP and would hit each other's limits.
os.environ.setdefault("RATE_LIMIT_DB", os.path.join(tempfile.mkdtemp(prefix="kinder-tests-"), "rate_limit.sqlite3"))

# kinder.env (or KINDER_ENV_FILE) is loaded with override=True and usually sets its own
# APP_BASE_URL, so the request host must come from the loaded config, not the default above.
from app.config import config  # noqa: E402

BASE_URL = config.APP_BASE_URL.rstrip("/")  # always one of the allowed hosts

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
    from flask.testing import FlaskClient

    from app import create_app

    class _HostClient(FlaskClient):
        """Requests and session_transaction default to BASE_URL: the cookie jar is keyed
        by that host, so the session a test sets is the one its requests send."""
        def open(self, *args, **kwargs):
            if not args or isinstance(args[0], str):
                kwargs.setdefault("base_url", BASE_URL)
            return super().open(*args, **kwargs)

        def session_transaction(self, *args, **kwargs):
            kwargs.setdefault("base_url", BASE_URL)
            return super().session_transaction(*args, **kwargs)

    a = create_app(start_jobs=False)
    a.config["TESTING"] = True
    a.test_client_class = _HostClient
    return a


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app.core import rate_limit
    rate_limit._db_call(lambda conn: conn.execute("DELETE FROM hits"))
    with rate_limit._mem_lock:
        rate_limit._mem_hits.clear()


def session_user(persona):
    """Session dict for *persona* as a real login would build it (with the
    iat/last_seen stamps the session policy requires), or None for 'anon'."""
    user = PERSONAS[persona]
    if not user:
        return None
    now = int(time.time())
    return dict(user, iat=now, last_seen=now, session_version=0, auth_method="google")


def _client_as(app, persona):
    c = app.test_client()
    user = session_user(persona)
    if user:
        with c.session_transaction() as s:
            s["user"] = user
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
