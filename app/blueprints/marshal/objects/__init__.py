"""
Object routes for the Kinder web application.
"""
from flask import Blueprint

objects_bp = Blueprint('marshal_bp', __name__)

# Topic modules register their routes on import (order = original registration order).
from . import helpers, page, api, photometry, spectroscopy, comments, permissions, ned  # noqa: E402,F401
