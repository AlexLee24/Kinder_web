"""Private area (GREAT_Lab only): Daily Trigger, ePessto++ support, Documents, Lab info,
observation targets/logs and the page-permission admin API."""
from flask import Blueprint

private_area_bp = Blueprint('private_area', __name__, template_folder='templates', static_folder='static')

# Topic modules register their routes on import (order = original registration order).
from . import helpers, page_perms, daily_trigger, lab_info, epessto, documents, targets, debug, observation_logs  # noqa: E402,F401
