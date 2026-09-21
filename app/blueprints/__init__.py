"""Site areas, one package per blueprint. Each package holds its routes, templates and
static files together::

    basic/            home page, login page, profile, gallery, navbar partial (_navbar.html)
    auth/             Google OAuth / local admin login, profile actions; admin/ panel, web_log, database_status
    marshal/          object list page; objects/ = object detail page + per-object APIs
    detect/           DETECT host-screening review pages
    astronomy_tools/  tools, planners, LC plotter, CASTOR ETC, finding chart, public REST API
    planners/         templates/static for the planner pages + /ov_plot file serving
    private_area/     GREAT_Lab-only: Daily Trigger, ePessto++, Documents, Lab info, targets/logs API
    web_api/          JSON API for the pages and API-key clients (+ legacy_api.py)
    games/            1A2B game

Registration order matters: when two blueprints register the same URL rule the one
registered first handles the request (today: ``/api/profile/join_group`` and
``/api/profile/leave_group`` -> ``auth``; ``/api/generate_key`` -> ``api``).
"""


def register_blueprints(app):
    """Register all blueprints with the Flask app (same order as before the refactor)."""
    from .auth import auth_bp, admin_bp, web_log_bp, database_status_bp
    from .astronomy_tools import astronomy_tools_bp
    from .marshal import marshal_bp, objects_bp
    from .web_api import web_api_bp
    from .web_api.legacy_api import api_blueprint
    from .private_area import private_area_bp
    from .basic import basic_bp
    from .detect import detect_bp
    from .games import games_bp
    from .planners import planners_bp

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
    app.register_blueprint(database_status_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(planners_bp)
