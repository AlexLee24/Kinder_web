"""Authentication and administration.

    routes.py           Google OAuth login/callback, local admin login, logout, profile actions
    admin/              Admin Panel page and its management actions (blueprint 'admin')
    web_log.py          /admin/log server log viewer (blueprint 'web_log')
    database_status.py  /admin/database connection monitor (blueprint 'database_status')
"""
from .routes import auth_bp  # noqa: F401
from .admin import admin_bp  # noqa: F401
from .web_log import web_log_bp  # noqa: F401
from .database_status import database_status_bp  # noqa: F401
