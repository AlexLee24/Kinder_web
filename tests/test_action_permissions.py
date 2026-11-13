"""Admin › Permissions: who may do an action (app/core/permissions.py) and the routes it guards.
No database: the stored rules are monkeypatched."""
import pytest

from app.core import permissions as perms


def _rules(**over):
    rules = {a: perms.default_rule(a) for a in perms.ACTIONS}
    for action, rule in over.items():
        rules[action] = dict(perms.default_rule(action), **rule)
    return rules


ADMIN = {'email': 'a@x', 'role': 'admin', 'is_admin': True, 'groups': []}
USER = {'email': 'u@x', 'role': 'user', 'is_admin': False, 'groups': []}
MEMBER = {'email': 'm@x', 'role': 'user', 'is_admin': False, 'groups': ['GREAT_Lab'], 'is_great_lab_member': True}
GUEST = {'email': 'g@x', 'role': 'guest', 'is_admin': False, 'groups': ['Partners']}


def test_defaults_let_users_upload_spectra_only():
    r = _rules()
    assert perms.explain(USER, 'upload_spectrum', r)[0]
    assert not perms.explain(GUEST, 'upload_spectrum', r)[0]
    assert not perms.explain(USER, 'upload_photometry', r)[0]
    assert not perms.explain(MEMBER, 'delete_spectrum', r)[0]
    assert not perms.explain(None, 'upload_spectrum', r)[0]


def test_admins_can_always():
    r = _rules(upload_spectrum={'level': 'admin'})
    assert perms.explain(ADMIN, 'upload_spectrum', r) == (True, 'admin')


@pytest.mark.parametrize('level, user, ok', [
    ('login', GUEST, True), ('user', GUEST, False), ('great_lab', USER, False),
    ('great_lab', MEMBER, True), ('admin', MEMBER, False),
])
def test_levels(level, user, ok):
    assert perms.explain(user, 'upload_photometry', _rules(upload_photometry={'level': level}))[0] is ok


def test_extra_groups_and_people():
    r = _rules(upload_photometry={'level': 'admin', 'groups': ['Partners'], 'users': ['u@x']})
    assert perms.explain(GUEST, 'upload_photometry', r) == (True, 'group Partners')
    assert perms.explain(dict(USER, email='U@X'), 'upload_photometry', r) == (True, 'added by name')
    assert not perms.explain(MEMBER, 'upload_photometry', r)[0]


def test_stored_rules_are_cleaned():
    rule = perms._clean_rule('upload_spectrum', {'level': 'root', 'groups': [' A ', 'A', ''], 'users': ['X@Y']})
    assert rule == {'level': 'user', 'groups': ['A'], 'users': ['x@y']}


@pytest.fixture
def stub_rules(monkeypatch):
    def use(**over):
        rules = _rules(**over)
        monkeypatch.setattr(perms, 'get_rules', lambda fresh=False: rules)
    return use


def test_upload_route_follows_the_setting(client_factory, stub_rules):
    client = client_factory('member')
    stub_rules(upload_spectrum={'level': 'admin'})
    r = client.post('/api/object/2025wny/spectroscopy', json={})
    assert r.status_code == 403 and 'Admin › Permissions' in r.get_json()['error']
    stub_rules()  # default: users may upload -> gets past the guard to the payload checks
    r = client.post('/api/object/2025wny/spectroscopy', json={})
    assert r.status_code == 400


def test_upload_needs_sign_in(app):
    r = app.test_client().post('/api/object/2025wny/spectroscopy', json={})
    assert r.status_code == 401


def test_permission_admin_routes_are_admin_only(client_factory):
    client = client_factory('member')
    assert client.post('/admin/permissions/action', json={'action': 'upload_spectrum', 'level': 'login'}).status_code == 403
    assert client.get('/admin/permissions/check?email=x').status_code == 403
    assert client.get('/admin/permissions').status_code == 302
