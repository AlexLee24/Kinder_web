"""
API routes for the Kinder web application.
"""
from flask import Blueprint

web_api_bp = Blueprint('web_api', __name__)  # JSON only: no templates, no static files

# Topic modules register their routes on import (order = original registration order).
from . import helpers, keys, observation_v1, detect, objects, tns  # noqa: E402,F401
