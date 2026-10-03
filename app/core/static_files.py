"""One ``/static/<path>`` route that serves files from every blueprint's ``static/`` folder.

Templates use ``url_for('static', filename='css/x.css')`` everywhere, so all blueprints
share a single URL namespace. The first directory that contains the file wins, in the
fixed order below — keep that order, because it decides which file is served when two
blueprints ship the same relative path (today only ``photo/background.jpg``: the
``basic`` copy is served, the ``astronomy_tools`` copy is shadowed).

Each blueprint also declares ``static_folder='static'``, which registers a ``<bp>.static``
endpoint on the same URL rule. Those endpoints only matter for ``url_for``; this
app-level rule is registered first and therefore handles every request.

Versioned URLs (2026-10): ``url_for('static', ...)`` appends ``?v=<file mtime>``. A URL with
``v`` is served with a one-year cache lifetime (and the service worker caches it), because
editing the file changes its URL. Hard-coded ``/static/...`` paths without ``v`` keep the
default revalidating behaviour.

``/sw.js`` serves the service worker of the installable app (PWA) from the site root, so its
scope covers the whole site.
"""
import os

from flask import abort, request, send_from_directory

from app.paths import BLUEPRINTS_DIR

# Lookup order. Must stay in this order (see module docstring).
STATIC_LOOKUP_ORDER = (
    'basic', 'auth', 'astronomy_tools', 'marshal', 'detect',
    'games', 'private_area', 'planners',
)
VERSIONED_MAX_AGE = 365 * 24 * 3600


def register_static_route(app) -> None:
    static_dirs = [str(BLUEPRINTS_DIR / name / 'static') for name in STATIC_LOOKUP_ORDER]
    icon_dir = str(BLUEPRINTS_DIR / 'basic' / 'icon')
    basic_static = str(BLUEPRINTS_DIR / 'basic' / 'static')

    def locate(filename):
        """Directory that serves ``filename`` (same rules as the route below), or None."""
        for directory in static_dirs:
            if os.path.isfile(os.path.join(directory, filename)):
                return directory, filename
        if filename.startswith('icon/'):
            icon_name = filename[len('icon/'):]
            if os.path.isfile(os.path.join(icon_dir, icon_name)):
                return icon_dir, icon_name
        return None

    @app.route('/static/<path:filename>', endpoint='static')
    def serve_static_files(filename):
        found = locate(filename)
        if not found:
            abort(404)
        directory, name = found
        if request.args.get('v'):
            return send_from_directory(directory, name, max_age=VERSIONED_MAX_AGE)
        return send_from_directory(directory, name)

    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint != 'static' and not endpoint.endswith('.static'):
            return
        filename = values.get('filename')
        if not filename or 'v' in values:
            return
        found = locate(filename)
        if found:
            values['v'] = int(os.path.getmtime(os.path.join(*found)))

    @app.route('/sw.js', endpoint='service_worker')
    def service_worker():
        resp = send_from_directory(basic_static, 'sw.js', mimetype='application/javascript')
        resp.headers['Cache-Control'] = 'no-cache'          # browsers must see a new worker right away
        resp.headers['Service-Worker-Allowed'] = '/'
        return resp
