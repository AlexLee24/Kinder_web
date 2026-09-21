"""One ``/static/<path>`` route that serves files from every blueprint's ``static/`` folder.

Templates use ``url_for('static', filename='css/x.css')`` everywhere, so all blueprints
share a single URL namespace. The first directory that contains the file wins, in the
fixed order below — keep that order, because it decides which file is served when two
blueprints ship the same relative path (today only ``photo/background.jpg``: the
``basic`` copy is served, the ``astronomy_tools`` copy is shadowed).

Each blueprint also declares ``static_folder='static'``, which registers a ``<bp>.static``
endpoint on the same URL rule. Those endpoints only matter for ``url_for``; this
app-level rule is registered first and therefore handles every request.
"""
import os

from flask import abort, send_from_directory

from app.paths import BLUEPRINTS_DIR

# Lookup order. Must stay in this order (see module docstring).
STATIC_LOOKUP_ORDER = (
    'basic', 'auth', 'astronomy_tools', 'marshal', 'detect',
    'games', 'private_area', 'planners',
)


def register_static_route(app) -> None:
    static_dirs = [str(BLUEPRINTS_DIR / name / 'static') for name in STATIC_LOOKUP_ORDER]
    icon_dir = str(BLUEPRINTS_DIR / 'basic' / 'icon')

    @app.route('/static/<path:filename>', endpoint='static')
    def serve_static_files(filename):
        for directory in static_dirs:
            if os.path.isfile(os.path.join(directory, filename)):
                return send_from_directory(directory, filename)
        # Logo / favicon files live in blueprints/basic/icon/ and are addressed as icon/<name>
        if filename.startswith('icon/'):
            icon_name = filename[len('icon/'):]
            if os.path.isfile(os.path.join(icon_dir, icon_name)):
                return send_from_directory(icon_dir, icon_name)
        abort(404)
