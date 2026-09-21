"""
Planners blueprint — exposes templates and static assets.
Page routes and API endpoints are handled by astronomy_tools_routes.py.
Registering this blueprint makes planners/templates/ discoverable by Flask.
"""
import os
from flask import Blueprint, send_from_directory, abort

planners_bp = Blueprint('planners', __name__, template_folder='templates', static_folder='static')

_OV_PLOT_DIR = os.path.join(os.path.dirname(__file__), 'ov_plot')

@planners_bp.route('/ov_plot/<path:filename>')
def serve_ov_plot(filename):
    """Serve generated OV plot images from planners/ov_plot/."""
    # Reject any path traversal attempts
    if '..' in filename or filename.startswith('/'):
        abort(400)
    return send_from_directory(_OV_PLOT_DIR, filename)
