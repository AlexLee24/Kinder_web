"""DETECT host screening pages and review APIs"""
from flask import Blueprint

detect_bp = Blueprint('detect', __name__, template_folder='templates', static_folder='static')

# Topic modules register their routes on import (order = original registration order).
from . import helpers, cache, payload, routes  # noqa: E402,F401
