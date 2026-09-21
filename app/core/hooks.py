"""Request/response hooks that apply to every route, in the order they must run.

``register_hooks(app)`` installs, in this order:

``before_request``
    1. ``enforce_allowed_host`` – reject requests whose Host header is not the configured
       public domain (or the local dev hosts when DEBUG).
    2. ``refresh_user_session`` – sync ``session['user']`` / ``g.current_user`` from the DB.
    3. ``mark_request_start`` – timing for the access log.
    4. ``block_pipe_in_api_params`` – ``/api/`` requests may not contain ``|`` anywhere.

``after_request``
    - cross-origin isolation headers
    - optional access log (``ACCESS_LOG_ENABLED=1``)

``errorhandler``
    - ``ParamOutOfRangeError`` -> ``{"error": ...}`` 400
"""
import logging
import os
import time
from urllib.parse import urlparse

from flask import abort, g, jsonify, request, session

from app.config import config
from app.core.auth import refresh_user_session
from app.core.request_validation import ParamOutOfRangeError

_access_logger = logging.getLogger('web.request')
_ACCESS_SKIP_PREFIXES = ('/static/', '/api/log/content', '/api/log/daemon/content')
_ACCESS_LOG_ENABLED = os.getenv('ACCESS_LOG_ENABLED', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def allowed_hosts() -> set:
    hosts = {urlparse(config.APP_BASE_URL).netloc}
    if config.DEBUG:
        # In local dev the site is usually reached via 127.0.0.1/localhost rather
        # than the public APP_BASE_URL domain — allow those too so the Host check
        # doesn't block local testing.
        hosts.update({
            f'{config.HOST}:{config.PORT}',
            f'localhost:{config.PORT}',
            f'127.0.0.1:{config.PORT}',
        })
    return hosts


def _contains_pipe(value):
    if isinstance(value, str):
        return '|' in value
    if isinstance(value, dict):
        return any(_contains_pipe(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_pipe(v) for v in value)
    return False


def register_hooks(app) -> None:
    _allowed = allowed_hosts()

    @app.before_request
    def enforce_allowed_host():
        # Reject requests whose Host header doesn't match the configured public
        # domain (e.g. direct-IP access) — the Host header is attacker-controlled
        # and must not be trusted for routing/redirect decisions.
        if request.host not in _allowed:
            logging.getLogger('app').warning(
                "Rejected request: Host header %r not in allowed hosts %r "
                "(set APP_BASE_URL in kinder.env to match how the site is accessed)",
                request.host, _allowed,
            )
            abort(404)

    # Registered globally so g.current_user (including DB picture) is available on
    # every request regardless of which blueprint handles it.
    app.before_request(refresh_user_session)

    @app.before_request
    def mark_request_start():
        g._req_start_monotonic = time.monotonic()

    @app.before_request
    def block_pipe_in_api_params():
        if not request.path.startswith('/api/'):
            return None

        if any('|' in v for v in request.args.values()):
            return jsonify({'error': "Invalid character '|' is not allowed"}), 400

        if any('|' in v for v in request.form.values()):
            return jsonify({'error': "Invalid character '|' is not allowed"}), 400

        if request.is_json:
            try:
                body = request.get_json(silent=True)
            except Exception:
                body = None
            if _contains_pipe(body):
                return jsonify({'error': "Invalid character '|' is not allowed"}), 400

        return None

    @app.errorhandler(ParamOutOfRangeError)
    def handle_param_out_of_range(exc):
        return jsonify({'error': str(exc)}), 400

    @app.after_request
    def add_isolation_headers(response):
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        return response

    @app.after_request
    def log_request_access(response):
        if not _ACCESS_LOG_ENABLED:
            return response
        path = request.path or ''
        if path.startswith(_ACCESS_SKIP_PREFIXES):
            return response
        start = getattr(g, '_req_start_monotonic', None)
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else -1
        user_email = (session.get('user') or {}).get('email', 'anon')
        user_agent = (request.user_agent.string or '-')[:120]
        _access_logger.info(
            'event=http_access method=%s path=%s status=%s duration_ms=%s bytes=%s ip=%s user=%s ua="%s"',
            request.method,
            path,
            response.status_code,
            duration_ms,
            response.calculate_content_length() or 0,
            request.headers.get('X-Forwarded-For', request.remote_addr or '-'),
            user_email,
            user_agent,
        )
        return response
