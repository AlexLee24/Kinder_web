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
    from . import private_routes
    from . import basic
    from . import marshal
    from . import detect_results
    from . import log_routes
    
    # Register blueprints
    auth.register_auth_routes(app)
    admin.register_admin_routes(app)
    astronomy_tools.register_astronomy_routes(app)
    objects.register_object_routes(app)
    api.register_api_routes(app)
    private_routes.register_private_routes(app)
    basic.register_basic_routes(app)
    marshal.register_marshal_routes(app)
    detect_results.register_detect_results_routes(app)
    log_routes.register_log_routes(app)
