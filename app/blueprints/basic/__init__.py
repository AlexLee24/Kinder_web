"""Home page, login page, profile page, settings page, home gallery API and the shared shell partials."""
from .routes import basic_bp  # noqa: F401
from . import settings  # noqa: F401  -- /settings + /api/settings/ui on basic_bp
