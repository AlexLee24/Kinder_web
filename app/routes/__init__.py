"""
Routes package for the Kinder web application.
"""

def register_routes(app):
    """Register all routes with the Flask app"""
    from . import auth
    from . import admin
    from . import astronomy_tools
    from . import objects
    from . import api
    from . import calendar_routes
    from . import basic
    from . import marshal
    from . import custom_targets
    
    # Register blueprints
    auth.register_auth_routes(app)
    admin.register_admin_routes(app)
    astronomy_tools.register_astronomy_routes(app)
    objects.register_object_routes(app)
    api.register_api_routes(app)
    calendar_routes.register_calendar_routes(app)
    basic.register_basic_routes(app)
    marshal.register_marshal_routes(app)
    custom_targets.register_custom_targets_routes(app)
