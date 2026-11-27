"""Lab access (private_area/lab_pages.py): one Lab rule in front of every Lab page, each page its own rule or
"Same as Lab"; the sidebar and Admin › Permissions list the pages of LAB_NAV."""
import json

import pytest

from app.blueprints.private_area import lab_pages
from app.db import auth

MEMBER = {'groups': ['GREAT_Lab'], 'is_great_lab_member': True, 'role': 'member'}
VISITOR = {'groups': ['Visitors'], 'role': 'user'}
USER = {'groups': [], 'role': 'user'}


@pytest.fixture
def store(monkeypatch):
    settings = {}
    monkeypatch.setattr(auth, 'get_setting', lambda key, default=None: settings.get(key, default))
    return settings


def test_every_nav_page_is_a_private_page():
    from app.blueprints.private_area import helpers
    assert helpers._PRIVATE_PAGES == lab_pages.PAGES
    assert {'detect_tns', 'detect_lsst', 'pipeline', 'documents'} <= set(lab_pages.PAGES)
    assert len(set(lab_pages.PAGES)) == len(lab_pages.PAGES)


def test_defaults_keep_old_behaviour(store):
    assert lab_pages.level('lab') == 'member'
    assert lab_pages.level('daily_trigger') == 'member'
    assert lab_pages.level('detect_tns') == 'lab'
    assert lab_pages.user_can_open(MEMBER, 'detect_tns')
    assert not lab_pages.user_can_open(USER, 'detect_tns')


def test_unset_lab_rule_lets_in_groups_added_to_pages(store):
    store['page_perm:epessto_support'] = json.dumps(['Visitors'])
    assert lab_pages.groups('lab') == ['Visitors']
    assert lab_pages.user_can_open(VISITOR, 'epessto_support')
    assert not lab_pages.user_can_open(VISITOR, 'daily_trigger')     # page rule still applies
    assert lab_pages.user_can_open(VISITOR, 'detect_tns')            # "Same as Lab": what Admin shows on the Lab card
    store['page_perm:lab'] = '[]'
    assert not lab_pages.user_can_open(VISITOR, 'epessto_support')   # out of the Lab → out of every page


def test_closing_the_lab_closes_every_page(store):
    store['page_level:lab'] = 'admin'
    store['page_perm:lab'] = '[]'
    assert not any(lab_pages.user_can_open(MEMBER, p) for p in lab_pages.PAGES)
    assert all(lab_pages.user_can_open({'is_admin': True}, p) for p in lab_pages.PAGES)
    assert lab_pages.visible_nav(MEMBER) == []


def test_page_can_be_narrower_than_lab(store):
    store['page_level:lab'] = 'signed_in'
    assert lab_pages.user_can_open(USER, 'detect_tns')
    assert not lab_pages.user_can_open(USER, 'daily_trigger')
    store['page_level:documents'] = 'lab'
    assert lab_pages.user_can_open(USER, 'documents')


def test_nav_lists_only_openable_pages(store):
    store['page_level:special_run_euclid_slsn'] = 'admin'
    nav = dict((g[0], [h for h, _ in g[4]]) for g in lab_pages.visible_nav(MEMBER))
    assert 'specialrun' not in nav                       # both Special Run pages closed → group gone
    assert nav['detect'][0] == '/detect'


def test_page_for_path():
    assert lab_pages.page_for_path('/detect') == 'detect_tns'
    assert lab_pages.page_for_path('/detect/lsst/review') == 'detect_lsst'
    assert lab_pages.page_for_path('/detect_image/x') is None
    assert lab_pages.page_for_path('/detect/lens/sugohi') is None   # shared helper, not the TNS-DETECT page
    assert lab_pages.page_for_path('/documents/foo.md') == 'documents'


@pytest.mark.parametrize('persona, status', [('admin', 200), ('member', 302)])
def test_gate_closes_pages(client_factory, store, persona, status):
    store['page_level:lab'] = 'admin'
    store['page_perm:lab'] = '[]'
    assert client_factory(persona).get('/detect/archives').status_code == status


def test_lab_level_api(client_factory, monkeypatch, store):
    saved = {}
    monkeypatch.setattr(auth, 'set_setting', lambda k, v: saved.__setitem__(k, v) or True)
    admin = client_factory('admin')
    assert admin.post('/api/admin/private_area/page_level', json={'page': 'lab', 'level': 'signed_in'}).status_code == 200
    assert saved == {'page_level:lab': 'signed_in'}
    assert admin.post('/api/admin/private_area/page_level', json={'page': 'lab', 'level': 'lab'}).status_code == 400
    d = admin.get('/api/admin/private_area/page_perms').get_json()
    assert [g['key'] for g in d['nav']][0] == 'pipeline' and 'lab' in d['levels']
