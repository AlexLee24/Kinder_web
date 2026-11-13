"""Private-page permissions for Special Run: each tab is its own page; a page's level ('member' = GREAT Lab members,
'admin' = admins only) plus its added groups decide who opens it. Lens Simulator starts as admins only;
Euclid-SLSN keeps the old 'special_run' groups until it is set on its own."""
import json

import pytest

from app.blueprints.private_area import helpers
from app.db import auth

MEMBER = {'groups': ['GREAT_Lab'], 'is_great_lab_member': True}
VISITOR = {'groups': ['Visitors']}


@pytest.fixture
def store(monkeypatch):
    settings = {}
    monkeypatch.setattr(auth, 'get_setting', lambda key, default=None: settings.get(key, default))
    return settings


def test_unset_euclid_tab_inherits_old_special_run_groups(store):
    store['page_perm:special_run'] = json.dumps(['Visitors'])
    assert helpers._get_page_extra_groups('special_run_euclid_slsn') == ['Visitors']
    assert helpers.user_can_access_page(VISITOR, 'special_run_euclid_slsn')
    assert not helpers.user_can_access_page(VISITOR, 'special_run_lens_sim')   # new tab: no inherited groups


def test_tab_groups_override_old_key(store):
    store['page_perm:special_run'] = json.dumps(['Visitors'])
    store['page_perm:special_run_euclid_slsn'] = '[]'
    assert helpers._get_page_extra_groups('special_run_euclid_slsn') == []


def test_lens_sim_defaults_to_admins_only(store):
    assert helpers.page_level('special_run_lens_sim') == 'admin'
    assert helpers.page_level('special_run_euclid_slsn') == 'member'
    assert helpers.user_can_access_page({'is_admin': True}, 'special_run_lens_sim')
    assert not helpers.user_can_access_page(MEMBER, 'special_run_lens_sim')
    assert helpers.user_can_access_page(MEMBER, 'special_run_euclid_slsn')


def test_level_can_be_changed(store):
    store['page_level:special_run_lens_sim'] = 'member'
    assert helpers.user_can_access_page(MEMBER, 'special_run_lens_sim')
    store['page_level:daily_trigger'] = 'admin'
    assert not helpers.user_can_access_page(MEMBER, 'daily_trigger')


def test_admins_only_page_still_opens_for_added_groups(store):
    store['page_perm:special_run_lens_sim'] = json.dumps(['Visitors'])
    assert helpers.user_can_access_page(VISITOR, 'special_run_lens_sim')
    assert not helpers.user_can_access_page(MEMBER, 'special_run_lens_sim')


def test_both_tabs_are_private_pages():
    assert {'special_run_euclid_slsn', 'special_run_lens_sim'} <= set(helpers._PRIVATE_PAGES)
    assert 'special_run' not in helpers._PRIVATE_PAGES


@pytest.mark.parametrize('persona, status', [('admin', 200), ('member', 302), ('guest', 302), ('anon', 302)])
def test_lens_sim_page_default(client_factory, store, persona, status):
    assert client_factory(persona).get('/special_run/lens_sim').status_code == status


def test_lens_sim_tab_only_in_nav_of_those_who_may_open_it(client_factory, store):
    assert b'/special_run/lens_sim' in client_factory('admin').get('/special_run/euclid_slsn').data
    assert b'/special_run/lens_sim' not in client_factory('member').get('/special_run/euclid_slsn').data
    store['page_level:special_run_lens_sim'] = 'member'
    assert b'/special_run/lens_sim' in client_factory('member').get('/special_run/euclid_slsn').data


def test_level_api(client_factory, monkeypatch, store):
    saved = {}
    monkeypatch.setattr(auth, 'set_setting', lambda k, v: saved.__setitem__(k, v) or True)
    r = client_factory('admin').post('/api/admin/private_area/page_level', json={'page': 'special_run_lens_sim', 'level': 'member'})
    assert r.status_code == 200 and saved == {'page_level:special_run_lens_sim': 'member'}
    assert client_factory('admin').post('/api/admin/private_area/page_level', json={'page': 'x', 'level': 'member'}).status_code == 400
    assert client_factory('member').post('/api/admin/private_area/page_level', json={'page': 'special_run_lens_sim', 'level': 'member'}).status_code == 403
