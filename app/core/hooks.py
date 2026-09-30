"""Request/response hooks that apply to every route, in the order they must run.

``register_hooks(app)`` installs, in this order:

``before_request``
    1. ``enforce_allowed_host`` – reject requests whose Host header is not the configured
       public domain (or the local dev hosts when DEBUG).
    2. ``check_same_origin`` – CSRF guard: state-changing requests carrying an
       ``Origin`` (or, failing that, ``Referer``) header from another host get 403.
    3. ``refresh_user_session`` – sync ``session['user']`` / ``g.current_user`` from the DB.
    4. ``mark_request_start`` – timing for the access log.
    5. ``block_pipe_in_api_params`` – ``/api/`` requests may not contain ``|`` anywhere.

``after_request``
    - security headers (``add_security_headers``): COOP/CORP, nosniff, frame and
      referrer policy, Permissions-Policy, HSTS (HTTPS, non-DEBUG), enforced CSP
      and ``Cache-Control: no-store`` for logged-in / admin / API responses. A view
      that sets CORP, CSP or Cache-Control itself keeps its own value.
    - optional access log (``ACCESS_LOG_ENABLED=1``)

``errorhandler``
    - ``ParamOutOfRangeError`` -> ``{"error": ...}`` 400
    - 413 (upload over ``MAX_CONTENT_LENGTH``) -> JSON for ``/api/`` paths
    - any other unhandled exception -> logged, generic 500 (never ``str(exc)``)

Route: ``POST /csp-report`` collects browser CSP violation reports (no auth,
rate-limited, body capped, logged at WARNING, 204).
"""
import logging
import os
import time
from urllib.parse import urlparse

from flask import abort, g, jsonify, make_response, request, session
from werkzeug.exceptions import HTTPException

from app.config import config
from app.core import rate_limit
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


_STATE_CHANGING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
CSP_REPORT_PATH = '/csp-report'
_CSP_REPORT_MAX_BYTES = 16 * 1024
_CSP_REPORT_LIMIT = 30          # reports per IP ...
_CSP_REPORT_WINDOW_S = 60       # ... per minute

_PERMISSIONS_POLICY = (
    'camera=(), microphone=(), geolocation=(), payment=(), usb=(), '
    'fullscreen=(self), clipboard-write=(self)'
)


def build_csp(debug: bool) -> str:
    """The site-wide Content-Security-Policy (enforced)."""
    directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.plot.ly "
        "https://code.jquery.com https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https:",
        # data: — Aladin Lite fetches its embedded WebAssembly from a data: URL.
        "connect-src 'self' https: data:",
        "frame-src 'self' https://calendar.google.com https://www.meteoblue.com",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https://accounts.google.com",
        "frame-ancestors 'self'",
    ]
    if not debug:
        directives.append('upgrade-insecure-requests')
    directives.append(f'report-uri {CSP_REPORT_PATH}')
    return '; '.join(directives)


def _is_logged_in_request() -> bool:
    return 'user' in session


def _is_cross_origin_request() -> bool:
    """True if a state-changing request names an origin other than this host.

    Browsers send ``Origin`` on cross-site POSTs (and ``Referer`` in most other
    cases), so a mismatch means a forged cross-site request. Requests with
    neither header (API-key clients, curl, scripts) are allowed through.
    """
    source = request.headers.get('Origin') or request.headers.get('Referer')
    if not source:
        return False
    try:
        netloc = urlparse(source).netloc
    except ValueError:
        return True
    # 'Origin: null' (sandboxed iframes, data: URLs) has no netloc -> reject.
    return netloc.lower() != (request.host or '').lower()


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

    @app.before_request
    def check_same_origin():
        if request.path == CSP_REPORT_PATH:
            return None   # browsers post violation reports without a same-origin guarantee
        if request.method in _STATE_CHANGING_METHODS and _is_cross_origin_request():
            logging.getLogger('app').warning(
                "Rejected cross-origin %s %s (Origin=%r Referer=%r Host=%r)",
                request.method, request.path, request.headers.get('Origin'),
                request.headers.get('Referer'), request.host,
            )
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Cross-origin request rejected'}), 403
            abort(403)
        return None

    # Registered globally so g.current_user (including DB picture) is available on
    # every request regardless of which blueprint handles it.
    app.before_request(refresh_user_session)

    @app.before_request
    def mark_request_start():
        g._req_start_monotonic = time.monotonic()

    @app.before_request
    def reject_nul_bytes():
        # PostgreSQL cannot store NUL characters: such input only ever ends in a
        # driver error (500), so refuse it up front for every route.
        if ('\x00' in request.path
                or any('\x00' in v for v in request.args.values())
                or (request.form and any('\x00' in v for v in request.form.values()))):
            return jsonify({'error': 'Invalid characters in request'}), 400
        return None

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

    @app.errorhandler(413)
    def handle_request_too_large(exc):
        if request.path.startswith('/api/'):
            limit = app.config.get('MAX_CONTENT_LENGTH')
            msg = 'Request body too large'
            if limit:
                msg += f' (limit {limit // (1024 * 1024)} MB)'
            return jsonify({'error': msg}), 413
        return exc

    @app.errorhandler(Exception)
    def handle_unexpected_exception(exc):
        # HTTP errors (404, 403, 405, ...) keep Flask's normal handling.
        if isinstance(exc, HTTPException):
            return exc
        logging.getLogger('app').exception(
            'Unhandled exception on %s %s', request.method, request.path)
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Internal server error'}), 500
        resp = make_response('Internal server error. Please try again later.', 500)
        resp.mimetype = 'text/plain'
        return resp

    def csp_report():
        """Receive browser CSP violation reports (report-uri). Always 204."""
        ip = request.remote_addr or 'unknown'
        if not rate_limit.allow(f'csp_report:{ip}', _CSP_REPORT_LIMIT, _CSP_REPORT_WINDOW_S):
            return '', 204
        length = request.content_length
        if length is not None and length > _CSP_REPORT_MAX_BYTES:
            return '', 204
        raw = request.stream.read(_CSP_REPORT_MAX_BYTES + 1)
        if len(raw) > _CSP_REPORT_MAX_BYTES:
            return '', 204
        summary = raw.decode('utf-8', errors='replace')
        try:
            import json
            body = json.loads(summary)
            rep = body.get('csp-report', body) if isinstance(body, dict) else {}
            if isinstance(body, list) and body and isinstance(body[0], dict):   # Reporting API
                rep = body[0].get('body') or {}
            if isinstance(rep, dict):
                summary = 'doc=%s violated=%s blocked=%s source=%s:%s' % (
                    str(rep.get('document-uri') or rep.get('documentURL') or '')[:200],
                    str(rep.get('violated-directive') or rep.get('effectiveDirective') or '')[:100],
                    str(rep.get('blocked-uri') or rep.get('blockedURL') or '')[:200],
                    str(rep.get('source-file') or rep.get('sourceFile') or '')[:200],
                    rep.get('line-number') or rep.get('lineNumber') or '',
                )
        except Exception:
            pass
        logging.getLogger('app.csp').warning('CSP violation ip=%s %s',
                                             ip, summary[:600].replace('\n', ' '))
        return '', 204

    app.add_url_rule(CSP_REPORT_PATH, 'csp_report', csp_report, methods=['POST'])

    _csp_value = build_csp(config.DEBUG)

    @app.after_request
    def add_security_headers(response):
        h = response.headers
        h.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        # Views that must be embeddable cross-origin (e.g. image endpoints) set
        # their own Cross-Origin-Resource-Policy; keep it.
        h.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        h.setdefault('X-Content-Type-Options', 'nosniff')
        h.setdefault('X-Frame-Options', 'SAMEORIGIN')
        h.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        h.setdefault('Permissions-Policy', _PERMISSIONS_POLICY)
        if not config.DEBUG and request.is_secure:
            h.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        if 'Content-Security-Policy' not in h:
            h['Content-Security-Policy'] = _csp_value

        path = request.path or ''
        if not path.startswith('/static/') and 'Cache-Control' not in h:
            if (_is_logged_in_request() or path.startswith('/admin')
                    or path.startswith('/api/')):
                h['Cache-Control'] = 'no-store'
                h['Pragma'] = 'no-cache'
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
            request.remote_addr or '-',   # real client IP (ProxyFix, one trusted hop)
            user_email,
            user_agent,
        )
        return response
