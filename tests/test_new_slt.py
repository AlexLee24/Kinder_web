"""New SLT (/new_slt): unlisted, password only; the sheet lives outside git and is edited with small ops."""
import json

import pytest
from werkzeug.security import generate_password_hash

from app.blueprints.astronomy_tools import new_slt as ns

URL = '/new_slt'


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, 'STORE_DIR', tmp_path)
    monkeypatch.setattr(ns, 'ACCESS_FILE', tmp_path / 'access.json')
    monkeypatch.setattr(ns, 'SHEET_FILE', tmp_path / 'sheet.json')
    (tmp_path / 'access.json').write_text(json.dumps({'password_hash': generate_password_hash('survey')}))
    return tmp_path


def _open(client):
    assert client.post(URL, data={'password': 'survey'}).status_code == 303


def _ops(client, *ops):
    r = client.post(URL + '/sheet/ops', json={'ops': list(ops)})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_no_access_file_is_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ns, 'ACCESS_FILE', tmp_path / 'missing.json')
    assert client.get(URL).status_code == 404
    assert client.get(URL + '/sheet').status_code == 404


def test_locked_page_and_api(client, store):
    r = client.get(URL)
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'type="password"' in page and 'nsGrid' not in page
    assert r.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert client.get(URL + '/sheet').status_code == 403
    assert client.post(URL + '/sheet/ops', json={'ops': [{'op': 'set_fx', 'fx': {}}]}).status_code == 403


def test_wrong_password_stays_locked(client, store):
    r = client.post(URL, data={'password': 'nope'})
    assert r.status_code == 401 and 'Wrong password.' in r.get_data(as_text=True)
    assert client.get(URL + '/sheet').status_code == 403


def test_right_password_opens_page_and_seed(client, store):
    _open(client)
    assert 'nsGrid' in client.get(URL).get_data(as_text=True)
    j = client.get(URL + '/sheet').get_json()
    assert j['rev'] == 0
    labels = [t['label'] for t in j['doc']['tables']]
    assert labels == ['Camera', 'Telescope', 'Mount']
    names = [r['cells']['camc0'] for r in j['doc']['tables'][0]['rows']]
    assert names[:6] == ['GSense6060 BI', 'GSense4040 BI', 'IMX411', 'IMX461', 'IMX455', 'GSense400 BI']
    tel = j['doc']['tables'][1]['rows'][0]['cells']
    assert tel['telc0'] == 'DeltaRho 500' and tel['telc3'] == '1537'
    mounts = [r['cells']['mntc0'] for r in j['doc']['tables'][2]['rows']]
    assert mounts == ['L-600', 'T-600']
    assert client.get(URL + '/sheet?since=0').get_json() == {'rev': 0, 'same': True}


def test_lock_signs_out(client, store):
    _open(client)
    client.post(URL + '/lock')
    assert client.get(URL + '/sheet').status_code == 403


def test_ops_edit_and_persist(client, store):
    _open(client)
    j = _ops(client,
             {'op': 'set_cell', 'table': 'cam', 'row': 'camr0', 'col': 'camc1', 'value': 'Gpixel'},
             {'op': 'add_col', 'table': 'cam', 'col': {'id': 'cX', 'name': 'Read noise'}, 'after': 'camc3'},
             {'op': 'add_row', 'table': 'tel', 'row': {'id': 'rN', 'cells': {'telc0': 'CDK24', 'nope': 'x'}}, 'after': None},
             {'op': 'delete_row', 'table': 'mnt', 'row': 'mntr1'})
    assert j['rev'] == 1 and j['skipped'] == []
    saved = json.loads((store / 'sheet.json').read_text())['doc']
    cam, tel, mnt = saved['tables']
    assert cam['rows'][0]['cells']['camc1'] == 'Gpixel'
    assert [c['name'] for c in cam['columns']][4] == 'Read noise'
    assert tel['rows'][0] == {'id': 'rN', 'cells': {'telc0': 'CDK24'}}
    assert [r['id'] for r in mnt['rows']] == ['mntr0']


def test_two_editors_do_not_overwrite_each_other(client, store):
    _open(client)
    _ops(client, {'op': 'set_cell', 'table': 'cam', 'row': 'camr0', 'col': 'camc6', 'value': 'A'})
    _ops(client, {'op': 'set_cell', 'table': 'cam', 'row': 'camr1', 'col': 'camc6', 'value': 'B'})
    rows = client.get(URL + '/sheet').get_json()['doc']['tables'][0]['rows']
    assert rows[0]['cells']['camc6'] == 'A' and rows[1]['cells']['camc6'] == 'B'


def test_stale_and_bad_ops_are_skipped(client, store):
    _open(client)
    j = _ops(client,
             {'op': 'set_cell', 'table': 'cam', 'row': 'gone', 'col': 'camc0', 'value': 'x'},
             {'op': 'explode', 'table': 'cam'},
             {'op': 'set_cell', 'table': 'cam', 'row': 'camr0', 'col': 'camc0', 'value': 'ok'})
    assert [s['index'] for s in j['skipped']] == [0, 1]
    assert j['rev'] == 1
    r = client.post(URL + '/sheet/ops', json={'ops': [{'op': 'delete_table', 'table': 'nope'}]})
    assert r.get_json()['rev'] == 1                      # nothing applied: no new revision


def test_configs_and_fx_are_cleaned(client, store):
    _open(client)
    j = _ops(client,
             {'op': 'set_configs', 'configs': [{'id': 'c1', 'name': 'A', 'telescope': 'telr0', 'camera': 'camr4',
                                                'mount': '../x', 'reducer': 99, 'color': 'red', 'extras': [
                                                    {'label': 'Filters', 'amount': '5000', 'currency': 'EUR'}]}]},
             {'op': 'set_fx', 'fx': {'EUR': 1.2, 'USD': 7, 'bad': 3, 'TWD': -1}})
    c = j['doc']['configs'][0]
    assert c['mount'] is None and c['reducer'] == 5 and c['color'] == '#F39F5A'
    assert c['extras'] == [{'label': 'Filters', 'amount': 5000.0, 'currency': 'EUR', 'qty': 1}]
    assert j['doc']['fx'] == {'EUR': 1.2, 'USD': 1.0}
