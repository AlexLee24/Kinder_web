"""Structural checks that do not need the database to be reachable."""
import importlib
import pkgutil

import pytest


def test_all_blueprints_registered(app):
    expected = {
        'auth', 'admin', 'astronomy_tools', 'marshal_bp', 'api', 'web_api', 'private_area',
        'basic', 'marshal', 'detect', 'web_log', 'database_status', 'games', 'planners',
    }
    assert set(app.blueprints) == expected


def test_route_count_is_stable(app):
    # 250 rules before the 2026-09 refactor (docs/FEATURES.md appendix A); 245 after the
    # clean-up (4 template-less /private/* pages, the dead web_api.static rule and the
    # group-request URL change). Update deliberately when routes are added or removed.
    assert sum(1 for _ in app.url_map.iter_rules()) == 245


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
