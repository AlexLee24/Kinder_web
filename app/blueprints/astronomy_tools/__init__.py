"""
Astronomy tools routes for the Kinder web application.
"""
from flask import Blueprint

astronomy_tools_bp = Blueprint('astronomy_tools', __name__, template_folder='templates', static_folder='static')

# Topic modules register their routes on import (order = original registration order).
from . import (  # noqa: E402,F401
    euclid_compare,
    exposure_time_calculator,
    finding_chart,
    finding_chart_render,
    helpers,
    lc_plotter,
    planner,
    public_api,
    query_api,
    robot_api,
    spectrum,
    tools,
)
