"""Private area (GREAT_Lab only): Daily Trigger, ePessto++ support, Documents, Lab info, Lab calendar,
observation targets/logs, Lab Bots and the page-permission admin API."""
from flask import Blueprint

private_area_bp = Blueprint('private_area', __name__, template_folder='templates', static_folder='static')

# Topic modules register their routes on import (order = original registration order).
from . import (  # noqa: E402,F401
    bots,
    daily_trigger,
    debug,
    direct_trigger,
    documents,
    epessto,
    helpers,
    lab_calendar,
    lab_info,
    observation_logs,
    page_perms,
    pipeline,
    targets,
)
