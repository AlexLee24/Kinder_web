"""Per-object Data Source Permissions: only an object's own settings are stored (a source on Default drops its row
and follows Admin › Permissions again), and spectra obey them on the object page like photometry does."""
import contextlib

import pytest

from app.blueprints.marshal.objects import permissions as perm_routes
from app.blueprints.marshal.objects import spectroscopy as spec_routes
from app.core import auth as core_auth
from app.db import auth


@pytest.fixture(autouse=True)
def _no_account_rows(monkeypatch):
    """The personas have no DB row; without a database the session check would refuse the writes (503)."""
    monkeypatch.setattr(core_auth, '_get_user_cached', lambda email: None)


class _Cur:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, args=None):
        self.log.append((' '.join(sql.split()), args))


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self, cursor_factory=None):
        return _Cur(self.log)

    def commit(self):
        self.log.append(('COMMIT', None))


def test_default_drops_the_row_and_a_level_upserts_it(monkeypatch):
    log = []
    monkeypatch.setattr(auth, 'get_db_connection', lambda: contextlib.nullcontext(_Conn(log)))
    assert auth.set_source_permissions_batch('2026gzf', 'phot', [
        {'source_name': 'LOT', 'inherit': True},
        {'source_name': 'PS', 'is_public': False, 'allowed_groups': [1]},
    ])
    (delete, d_args), (upsert, u_args), commit = log
    assert delete.startswith('DELETE FROM transient.object_source_permissions') and d_args == ('2026gzf', 'phot', 'LOT')
    assert upsert.startswith('INSERT INTO transient.object_source_permissions') and u_args == ('2026gzf', 'phot', 'PS', False, [1])
    assert commit == ('COMMIT', None)


def test_batch_api_passes_inherit_and_maps_group_names(admin_client, monkeypatch):
    saved = {}
    monkeypatch.setattr(perm_routes, 'get_all_groups', lambda: {'GREAT_Lab': {'group_id': 1}, 'NCU': {'group_id': 2}})
    monkeypatch.setattr(perm_routes, 'set_source_permissions_batch',
                        lambda obj, dt, perms: saved.setdefault((obj, dt), perms) is not None)
    r = admin_client.post('/api/object/2026gzf/source-permissions/batch', json={'permissions': [
        {'data_type': 'phot', 'source_name': 'LOT', 'inherit': True, 'is_public': True},
        {'data_type': 'phot', 'source_name': 'PS', 'is_public': 0, 'allowed_groups': ['NCU', 'gone']},
        {'data_type': 'spec', 'source_name': 'LOT', 'is_public': False, 'allowed_groups': None},
    ]})
    assert r.status_code == 200, r.get_json()
    assert saved[('2026gzf', 'phot')] == [{'source_name': 'LOT', 'inherit': True},
                                          {'source_name': 'PS', 'is_public': False, 'allowed_groups': [2]}]
    assert saved[('2026gzf', 'spec')] == [{'source_name': 'LOT', 'is_public': False, 'allowed_groups': None}]


def test_batch_api_refuses_a_bad_entry_and_reports_a_failed_save(admin_client, monkeypatch):
    monkeypatch.setattr(perm_routes, 'get_all_groups', lambda: {})
    monkeypatch.setattr(perm_routes, 'set_source_permissions_batch', lambda *a: False)
    url = '/api/object/2026gzf/source-permissions/batch'
    assert admin_client.post(url, json={'permissions': [{'data_type': 'x', 'source_name': 'LOT'}]}).status_code == 400
    assert admin_client.post(url, json={'permissions': [{'data_type': 'phot'}]}).status_code == 400
    assert admin_client.post(url, json={'permissions': [{'data_type': 'phot', 'source_name': 'LOT'}]}).status_code == 500


def test_batch_api_is_admin_only(client_factory):
    r = client_factory('member').post('/api/object/2026gzf/source-permissions/batch', json={'permissions': []})
    assert r.status_code in (401, 403)


def _spectra_setup(monkeypatch, allowed):
    spectra = [{'telescope': 'LOT', 'spectrum_id': 'LOT@@61000.0'}, {'telescope': 'NOT', 'spectrum_id': 'NOT@@61001.0'}]
    seen = []

    def fake_filter(obj, dt, records, **kw):
        seen.append((obj, dt, kw.get('user_email')))
        names = [r['telescope'] if isinstance(r, dict) else r for r in records]
        return [r for r, n in zip(records, names) if n in allowed]

    monkeypatch.setattr(spec_routes, 'filter_by_source_permissions', fake_filter)
    monkeypatch.setattr(spec_routes, 'session_can_access_object', lambda name: True)
    monkeypatch.setattr(spec_routes, 'resolve_object_name', lambda name: name)
    monkeypatch.setattr(spec_routes.TNSObjectDB, 'get_spectrum_list', staticmethod(lambda name: list(spectra)))
    return seen


def test_spectrum_list_hides_sources_the_user_may_not_see(client_factory, monkeypatch):
    seen = _spectra_setup(monkeypatch, {'NOT'})
    r = client_factory('member').get('/api/object/2026gzf/spectroscopy')
    body = r.get_json()
    assert r.status_code == 200 and [s['telescope'] for s in body['spectra']] == ['NOT'] and body['count'] == 1
    assert seen == [('2026gzf', 'spec', 'smoke-member@kinder.test')]


def test_one_hidden_spectrum_is_refused(client_factory, monkeypatch):
    _spectra_setup(monkeypatch, {'NOT'})
    c = client_factory('member')
    assert c.get('/api/object/2026gzf/spectrum/LOT@@61000.0').status_code == 403
    assert c.get('/api/spectrum/LOT@@61000.0/download?object=2026gzf').status_code == 403
