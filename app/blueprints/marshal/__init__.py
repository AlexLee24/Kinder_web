"""Marshal object list (routes.py, blueprint 'marshal') and the object detail page with
its per-object APIs (objects/, blueprint 'marshal_bp')."""
from .routes import marshal_bp  # noqa: F401
from .objects import objects_bp  # noqa: F401
