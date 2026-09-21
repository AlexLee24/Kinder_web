"""
Astronomy tools routes for the Kinder web application.
"""
from flask import Blueprint

astronomy_tools_bp = Blueprint('astronomy_tools', __name__, template_folder='templates', static_folder='static')

# Topic modules register their routes on import (order = original registration order).
from . import helpers, tools, planner, lc_plotter, exposure_time_calculator, finding_chart, finding_chart_render, public_api  # noqa: E402,F401
