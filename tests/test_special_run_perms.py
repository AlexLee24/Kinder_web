"""Special Run tabs: each tab has its own private-page key; an unset tab keeps the old 'special_run' groups."""
import json

from app.blueprints.private_area import helpers
from app.db import auth


def _store(monkeypatch, settings):
    monkeypatch.setattr(auth, 'get_setting', lambda key, default=None: settings.get(key, default))


def test_unset_tab_inherits_old_special_run_groups(monkeypatch):
    _store(monkeypatch, {'page_perm:special_run': json.dumps(['Visitors'])})
    assert helpers._get_page_extra_groups('special_run_lens_sim') == ['Visitors']
    assert helpers.user_can_access_page({'groups': ['Visitors']}, 'special_run_euclid_slsn')


def test_tab_setting_overrides_old_key(monkeypatch):
    _store(monkeypatch, {'page_perm:special_run': json.dumps(['Visitors']),
                         'page_perm:special_run_lens_sim': json.dumps(['Students'])})
    assert helpers._get_page_extra_groups('special_run_lens_sim') == ['Students']
    assert not helpers.user_can_access_page({'groups': ['Visitors']}, 'special_run_lens_sim')
    assert helpers.user_can_access_page({'groups': ['Visitors']}, 'special_run_euclid_slsn')


def test_emptied_tab_does_not_fall_back(monkeypatch):
    _store(monkeypatch, {'page_perm:special_run': json.dumps(['Visitors']), 'page_perm:special_run_lens_sim': '[]'})
    assert helpers._get_page_extra_groups('special_run_lens_sim') == []


def test_both_tabs_are_private_pages():
    assert {'special_run_euclid_slsn', 'special_run_lens_sim'} <= set(helpers._PRIVATE_PAGES)
    assert 'special_run' not in helpers._PRIVATE_PAGES
