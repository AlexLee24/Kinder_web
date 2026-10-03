"""Security hardening checks that do not need the database.

Headers, the CSP report endpoint, the session policy (legacy cookie, idle and
absolute timeouts), fail-closed admin checks, log redaction and password/username
rules. With no reachable DB, ``refresh_user_session`` marks the session unverified
(it never clears it for that reason), which these tests rely on.
"""
import logging
import time

import pytest

from tests.conftest import BASE_URL, PERSONAS, session_user


def _client_with(app, user):
    c = app.test_client()
    with c.session_transaction() as s:
        s['user'] = user
    return c


def _session_user_of(client):
    with client.session_transaction() as s:
        return s.get('user')


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url', ['/', '/login'])
def test_security_headers_present(client, url):
    r = client.get(url, base_url=BASE_URL)
    assert r.status_code == 200
    h = r.headers
    assert h['X-Content-Type-Options'] == 'nosniff'
    assert h['X-Frame-Options'] == 'SAMEORIGIN'
    assert h['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert 'camera=()' in h['Permissions-Policy']
    assert h['Cross-Origin-Opener-Policy'] == 'same-origin'
    assert h['Cross-Origin-Resource-Policy'] == 'same-origin'
    csp = h['Content-Security-Policy']
    for part in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'self'",
                 "base-uri 'self'", 'report-uri /csp-report'):
        assert part in csp
    # Plain http in tests -> no HSTS.
    assert 'Strict-Transport-Security' not in h


def test_anonymous_page_is_cacheable_but_logged_in_is_not(app, client):
    assert 'no-store' not in (client.get('/', base_url=BASE_URL).headers.get('Cache-Control') or '')
    member = _client_with(app, session_user('member'))
    r = member.get('/', base_url=BASE_URL)
    assert r.headers.get('Cache-Control') == 'no-store'
    assert r.headers.get('Pragma') == 'no-cache'


def test_view_set_headers_are_kept(app):
    """A view's own CORP / CSP / Cache-Control survive the after_request hook."""
    from flask import Response
    with app.test_request_context('/api/some/image', base_url=BASE_URL):
        resp = Response('x')
        resp.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
        resp.headers['Content-Security-Policy'] = "default-src 'none'"
        resp.headers['Cache-Control'] = 'public, max-age=60'
        resp = app.process_response(resp)
    assert resp.headers['Cross-Origin-Resource-Policy'] == 'cross-origin'
    assert resp.headers['Content-Security-Policy'] == "default-src 'none'"
    assert resp.headers['Cache-Control'] == 'public, max-age=60'
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'


def test_hsts_on_https(client, monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, 'DEBUG', False)
    r = client.get('/', base_url=BASE_URL, headers={'X-Forwarded-Proto': 'https'})
    assert r.headers.get('Strict-Transport-Security') == 'max-age=31536000; includeSubDomains'


def test_csp_report_endpoint(client):
    body = {'csp-report': {'document-uri': 'http://localhost:8000/', 'violated-directive': 'script-src',
                           'blocked-uri': 'https://evil.example/x.js'}}
    r = client.post('/csp-report', json=body, base_url=BASE_URL,
                    headers={'Origin': 'https://elsewhere.example',
                             'Content-Type': 'application/csp-report'})
    assert r.status_code == 204
    big = client.post('/csp-report', data='x' * (20 * 1024), base_url=BASE_URL,
                      content_type='application/csp-report')
    assert big.status_code == 204


# ---------------------------------------------------------------------------
# Session policy
# ---------------------------------------------------------------------------

def test_legacy_cookie_without_iat_is_cleared(app):
    legacy = dict(PERSONAS['member'])   # no iat / last_seen
    c = _client_with(app, legacy)
    r = c.get('/', base_url=BASE_URL)
    assert r.status_code == 200
    assert _session_user_of(c) is None


def test_idle_session_expires(app):
    user = session_user('member')
    user['last_seen'] = int(time.time()) - 9 * 3600      # > 8 h idle
    c = _client_with(app, user)
    r = c.get('/', base_url=BASE_URL)
    assert r.status_code == 302 and '/login' in r.headers['Location']
    assert _session_user_of(c) is None


def test_admin_idle_limit_is_shorter(app):
    user = session_user('admin')
    user['last_seen'] = int(time.time()) - 2 * 3600      # > 1 h idle for admins
    c = _client_with(app, user)
    r = c.get('/api/anything-json', base_url=BASE_URL)
    assert r.status_code == 401
    assert _session_user_of(c) is None


def test_absolute_session_lifetime(app):
    user = session_user('member')
    user['iat'] = int(time.time()) - 31 * 24 * 3600
    c = _client_with(app, user)
    r = c.get('/', base_url=BASE_URL)
    assert r.status_code == 302
    assert _session_user_of(c) is None


def test_fresh_session_is_kept(app):
    c = _client_with(app, session_user('member'))
    r = c.get('/', base_url=BASE_URL)
    assert r.status_code == 200
    assert (_session_user_of(c) or {}).get('email') == PERSONAS['member']['email']


def test_admin_checks_fail_closed_when_session_unverified(app):
    from flask import g, session
    from app.core import auth

    calls = []

    @auth.admin_required
    def view():
        calls.append(1)
        return 'ok'

    with app.test_request_context('/api/x', base_url=BASE_URL):
        session['user'] = session_user('admin')
        g.session_unverified = True
        resp = view()
        assert resp[1] == 503 and not calls
        assert auth.is_admin() is False
        g.session_unverified = False
        assert view() == 'ok' and auth.is_admin() is True


def test_start_user_session_contents(app):
    from flask import session
    from app.core.auth import start_user_session
    with app.test_request_context('/', base_url=BASE_URL):
        session['stale'] = 1
        start_user_session({'email': 'a@b.test', 'name': 'A', 'roles': 1, 'role': 'user',
                            'groups': ['GREAT_Lab'], 'session_version': 3,
                            'has_api_key': True}, 'password')
        u = session['user']
        assert 'stale' not in session
        assert 'api_key' not in u
        assert u['iat'] == u['last_seen'] and abs(u['iat'] - time.time()) < 5
        assert u['session_version'] == 3 and u['is_great_lab_member'] is True
        assert session.permanent is True


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_log_redaction():
    from app.core.log_setup import RedactSecretsFilter, redact_secrets
    assert redact_secrets('GET /api/x?api_key=SECRET123&a=1') == 'GET /api/x?api_key=[REDACTED]&a=1'
    assert 'SECRET' not in redact_secrets("{'X-API-Key': 'SECRET'}")
    rec = logging.LogRecord('t', logging.INFO, __file__, 1, 'url=%s', ('/p?api_key=SECRET',), None)
    RedactSecretsFilter().filter(rec)
    assert 'SECRET' not in rec.getMessage()


def test_password_rules_reject_username():
    from app.core.passwords import password_problem
    assert password_problem('xx-alice99-long-pass', 'x@users.invalid', 'alice99') is not None
    assert password_problem('Correct-Horse-Battery', 'bob@example.com', 'bob') is None


def test_username_helpers():
    from app.db.auth import is_placeholder_email, placeholder_email_for, valid_username
    assert placeholder_email_for('Alice.W') == 'alice.w@users.invalid'
    assert is_placeholder_email('alice.w@USERS.invalid')
    assert not is_placeholder_email('alice@example.com')
    # Any language, 1-32 characters; no whitespace, '@' or HTML/path characters.
    assert valid_username('a.b_c-1') and valid_username('ab') and valid_username('王小明')
    for bad in ('', 'a b', 'a@b', '<b>', 'a/b', 'x' * 33):
        assert not valid_username(bad)
    # Non-ASCII usernames get an ASCII placeholder address.
    assert placeholder_email_for('王小明').startswith('u-')
    assert placeholder_email_for('王小明').endswith('@users.invalid')


def test_admin_password_has_no_format_rules():
    from app.core.passwords import admin_password_problem, password_problem
    for ok in ('1', '密碼', 'aaaa'):
        assert admin_password_problem(ok) is None
    assert admin_password_problem('') is not None
    assert admin_password_problem('x' * 1025) is not None
    # A user choosing their own password still gets the normal policy.
    assert password_problem('1') is not None


def test_avatar_helpers():
    import base64, io
    from PIL import Image
    from app.core.avatars import DEFAULT_AVATAR, avatar_url, shrink_data_uri
    buf = io.BytesIO()
    Image.new('RGB', (2000, 1500), (200, 30, 30)).save(buf, 'JPEG')
    big = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    small = shrink_data_uri(big)
    assert small and small.startswith('data:image/jpeg;base64,') and len(small) < len(big)
    with Image.open(io.BytesIO(base64.b64decode(small.split(',', 1)[1]))) as im:
        assert max(im.size) <= 256
    assert shrink_data_uri('data:image/png;base64,bm90IGFuIGltYWdl') is None
    assert avatar_url(7, big).startswith('/avatar/7?v=')
    assert avatar_url(7, 'https://lh3.googleusercontent.com/a/x') == 'https://lh3.googleusercontent.com/a/x'
    assert avatar_url(7, '') == DEFAULT_AVATAR


def test_avatar_route_requires_login(client):
    assert client.get('/avatar/1', base_url=BASE_URL).status_code == 404


def test_safe_next():
    from app.blueprints.auth.routes import _safe_next
    assert _safe_next('/marshal?x=1') == '/marshal?x=1'
    for bad in ('//evil.example', 'https://evil.example', '/\\\\evil', '/a\r\nb', None, 5):
        assert _safe_next(bad) is None


def test_gallery_does_not_serve_metadata(client):
    assert client.get('/gallery/image/x.png.json', base_url=BASE_URL).status_code == 404
    assert client.get('/slideshow/image/slideshow_config.json', base_url=BASE_URL).status_code == 404


def test_unhandled_exception_is_generic(app):
    from app.core import hooks  # noqa: F401  (handler registered in create_app)
    with app.test_request_context('/api/boom', base_url=BASE_URL):
        handler = app.error_handler_spec[None][None][Exception]
        body, status = handler(RuntimeError('secret detail'))
        assert status == 500 and b'secret detail' not in body.get_data()
