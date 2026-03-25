"""
Routes package for the Kinder web application.
"""

def register_routes(app):
    """Register all routes with the Flask app"""
    from .auth.auth_routes import auth_bp
    from .auth.admin_routes import admin_bp
    from .astronomy_tools.astronomy_tools_routes import astronomy_tools_bp
    from .marshal.object_routes import objects_bp
    from .api_routes import api_blueprint
    from .web_api.web_api_routes import web_api_bp
    from .private_area.private_area_routes import private_area_bp
    from .basic.basic_routes import basic_bp
    from .marshal.marshal_routes import marshal_bp
    from .detect.detect_routes import detect_bp
    from .web_log.web_log_routes import web_log_bp
    from .games.games_routes import games_bp
    from .planners.planners_routes import planners_bp
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(astronomy_tools_bp)
    app.register_blueprint(objects_bp)
    app.register_blueprint(api_blueprint)
    app.register_blueprint(web_api_bp)
    app.register_blueprint(private_area_bp)
    app.register_blueprint(basic_bp)
    app.register_blueprint(marshal_bp)
    app.register_blueprint(detect_bp)
    app.register_blueprint(web_log_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(planners_bp)
