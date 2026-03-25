"""
Planners blueprint — exposes templates and static assets.
Page routes and API endpoints are handled by astronomy_tools_routes.py.
Registering this blueprint makes planners/templates/ discoverable by Flask.
"""
from flask import Blueprint

planners_bp = Blueprint('planners', __name__, template_folder='templates', static_folder='static')
