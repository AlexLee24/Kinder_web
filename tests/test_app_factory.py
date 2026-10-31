"""Structural checks that do not need the database to be reachable."""
import importlib
import pkgutil

import pytest


def test_all_blueprints_registered(app):
    expected = {
        'auth', 'admin', 'astronomy_tools', 'marshal_bp', 'api', 'web_api', 'private_area',
        'basic', 'marshal', 'detect', 'web_log', 'database_status', 'system_status', 'games', 'planners',
    }
    assert set(app.blueprints) == expected


def test_route_count_is_stable(app):
    # 250 rules before the 2026-09 refactor (docs/FEATURES.md appendix A); 245 after the
    # clean-up (4 template-less /private/* pages, the dead web_api.static rule and the
    # group-request URL change); 243 after dropping the shadowed basic.* duplicates of
    # /api/profile/join_group and /leave_group. Update deliberately when routes change.
    # 247 with password login (/login/password, /account/password,
    # /admin/set-password, /admin/clear-password). 251 with the security hardening
    # (/csp-report, /account/logout-all, /admin/force-logout,
    # /api/profile/regenerate_api_key).
    # 252 with /avatar/<usr_id> (profile pictures served instead of inlined).
    # 254 with the installable app (2026-10: /sw.js, /offline).
    # 261 with Direct Trigger (page + 6 API routes); 286 with Pipeline (8 pages + 15 API + 2 admin, Telescopes included);
    # 287 with the Pipeline folder scan (classify API); 294 with Calibrated_Science (2), copy / restore (2)
    # and import into Kinder objects (preview, import, undo); 297 with /admin/system (page, status, recount);
    # 299 with /settings and /api/settings/ui; 305 with Admin › Bots (page, status, log, run, stop, overview);
    # 317 by 2026-10-29; 328 with Pipeline › Reduction batches (3 pages + 8 API);
    # 331 with Lab › Bots (/bots, /api/bots/status, /api/bots/<id>/results); 333 with the Lulin robot feed
    # (/api/v1/robot/alerts) and cancelling a robot alert; 336 with DETECT › LSST
    # (/detect/lsst, /api/detect/lsst/lightcurve/<oid>, /api/detect/lsst/run); 338 with the ETC
    # Simple mode API and /detect/lsst/<oid> (Daily Trigger link of an LSST-<oid> target); 341 with
    # DETECT › Cross-match, the LSST run status and the LSST-oid cross-match API; 351 with
    # DETECT › LSST Review (page, image, light curve, fetch, set / unset / no host, status, flag, tracker);
    # 352 with the LSST-DETECT archives; 360 with Lab › Calendar (page, events list / add / change, Lulin sync,
    # subscription link, the token feed and one event's .ics); 371 with Web Push (/api/push/key, status, subscribe,
    # unsubscribe, test and Admin › Push: page, preview, send, device test, person test, device delete); 372 with
    # Trigger duty volunteering (/api/lab_calendar/volunteer).
    assert sum(1 for _ in app.url_map.iter_rules()) == 372


def test_duplicate_rules_keep_precedence(app):
    """Same URL registered by two blueprints: the first registered one must win."""
    wins = {}
    for rule in app.url_map.iter_rules():
        methods = frozenset(m for m in rule.methods if m not in ('HEAD', 'OPTIONS'))
        key = (rule.rule, methods)
        wins.setdefault(key, rule.endpoint)
    assert wins[('/api/profile/join_group', frozenset({'POST'}))] == 'auth.profile_join_group'
    assert wins[('/api/profile/leave_group', frozenset({'POST'}))] == 'auth.profile_leave_group'
    assert wins[('/api/generate_key', frozenset({'POST'}))] == 'api.generate_key'
    assert wins[('/static/<path:filename>', frozenset({'GET'}))] == 'static'


def test_every_app_module_imports():
    """Every module under app/ (except the vendored packages) imports cleanly."""
    import app as app_pkg
    failures = []
    for mod in pkgutil.walk_packages(app_pkg.__path__, prefix='app.'):
        if mod.name.startswith('app.vendor'):
            continue
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # pragma: no cover - reported below
            failures.append((mod.name, repr(exc)))
    assert not failures, failures


def test_paths_exist():
    from app import paths
    assert paths.APP_DIR.is_dir() and (paths.APP_DIR / '__init__.py').exists()
    assert paths.BLUEPRINTS_DIR.is_dir() and paths.RESOURCES_DIR.is_dir()
    assert (paths.RESOURCES_DIR / 'kn_lc_mag.txt').exists()
    assert (paths.RESOURCES_DIR / 'filter_colors.json').exists()
    assert paths.DETECT_DIR.is_dir()
    assert paths.CASTOR_SRC.is_dir(), "CASTOR must be cloned into app/vendor/CASTOR"


@pytest.mark.parametrize('url', ['/', '/login', '/marshal', '/astronomy_tools', '/games'])
def test_public_pages_render(client, url):
    from tests.conftest import BASE_URL
    r = client.get(url, base_url=BASE_URL)
    assert r.status_code == 200
