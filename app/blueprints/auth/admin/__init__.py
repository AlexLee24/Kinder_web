"""
Admin routes for the Kinder web application.
"""
from flask import Blueprint

# Templates/static live one level up, shared with the auth blueprint (blueprints/auth/).
admin_bp = Blueprint('admin', __name__, template_folder='../templates', static_folder='../static')

# Topic modules register their routes on import (order = original registration order).
from . import helpers, users, panel, api_keys, settings, groups, maintenance, tns, detect, scheduled_jobs  # noqa: E402,F401
