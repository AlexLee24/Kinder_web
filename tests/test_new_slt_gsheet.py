"""New SLT ⇄ Google Sheets: the real Apps Script (new_slt_gsheet.gs) runs in node against a stand-in SpreadsheetApp
(tests/new_slt_gsheet_mock.js), and the page's routes talk to it the way they talk to Google."""
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests
from werkzeug.security import generate_password_hash

from app.blueprints.astronomy_tools import new_slt as ns
from app.blueprints.astronomy_tools import new_slt_gsheet as gs

URL = '/new_slt'
MOCK = Path(__file__).with_name('new_slt_gsheet_mock.js')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='needs node for the Apps Script stand-in')

CAMERA = [
    ['Sensor', '品牌', '大小', 'Pixel Size', '價格', 'QE', '廠商報價 USD', '廠商報價 TWD', 'Note'],
    ['GSense6060 BI', '', '6144×6144｜61.4×61.4 mm', '10 μm', '~180,000 USD（待確認）', 'BSI', '', '', '片幅最大'],
    ['IMX461', '', '11656×8742｜43.8×32.9 mm', '3.76 μm', '>19,000 EUR', '', '', '', '大帥那台'],
    ['', '', '', '', '', '', '', '', ''],
    ['三色相機', 'sasago co,', '1024×1024 | 13.3×13.3 mm', '13 μm', {'v': 3, 'f': '=COUNTA(A2:A5)'}, '', 115000, {'v': 3795241.5, 'f': '=G5*GOOGLEFINANCE("CURRENCY:USDTWD")'}, 'SBIG Aluma CCD47-10'],
]
RATE = 32          # the mock's USD → TWD rate


@pytest.fixture
def mock():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    p = subprocess.Popen(['node', str(MOCK), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            requests.get(base + '/__dump', timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.05)
    m = type('Mock', (), {})()
    m.base = base
    m.load = lambda sheets: requests.post(base + '/__load', json={'sheets': sheets}, timeout=5).raise_for_status()
    m.dump = lambda: {s['id']: s for s in requests.get(base + '/__dump', timeout=5).json()['sheets']}
    m.edit = lambda sheet, row, col, value: requests.post(base + '/__edit', json={'sheet': sheet, 'row': row, 'col': col, 'value': value}, timeout=5).raise_for_status()
    m.load([{'id': 0, 'name': 'Camera', 'rows': CAMERA}])
    yield m
    p.kill()
    p.wait()


@pytest.fixture
def store(tmp_path, monkeypatch, mock):
    monkeypatch.setattr(ns, 'STORE_DIR', tmp_path)
    monkeypatch.setattr(ns, 'ACCESS_FILE', tmp_path / 'access.json')
    monkeypatch.setattr(ns, 'SHEET_FILE', tmp_path / 'sheet.json')
    monkeypatch.setattr(gs, 'PULL_EVERY_S', 0)
    (tmp_path / 'access.json').write_text(json.dumps({'password_hash': generate_password_hash('survey')}))
    (tmp_path / 'gsheet.json').write_text(json.dumps({'url': mock.base + '/exec', 'secret': 'test-secret',
                                                      'sheet_url': 'https://docs.google.com/spreadsheets/d/x/edit'}))
    return tmp_path


@pytest.fixture
def app_client(client, store):
    assert client.post(URL, data={'password': 'survey'}).status_code == 303
    return client


def _sheet(c):
    r = c.get(URL + '/sheet')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _ops(c, *ops):
    r = c.post(URL + '/sheet/ops', json={'ops': list(ops)})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _cam(j):
    return j['doc']['tables'][0]


def _col(t, name):
    return next(c['id'] for c in t['columns'] if c['name'] == name)


def _row(t, key):
    k = _col(t, t['columns'][0]['name'])
    return next(r for r in t['rows'] if r['cells'].get(k) == key)


def _grid(mock, sid=0):
    return [[(x['v'] if isinstance(x, dict) else x) for x in r] for r in mock.dump()[sid]['rows']]


def test_pull_builds_tables_with_stable_ids(app_client, mock):
    j = _sheet(app_client)
    t = _cam(j)
    assert t['label'] == 'Camera' and t['kind'] == 'camera' and t['gs_sheet'] == 0
    assert [c['name'] for c in t['columns']][-3:] == ['廠商報價 USD', '廠商報價 TWD', 'Note']
    assert [r['cells'][t['columns'][0]['id']] for r in t['rows']] == ['GSense6060 BI', 'IMX461', '三色相機']   # blank row skipped
    tri = _row(t, '三色相機')
    assert tri['cells'][_col(t, '廠商報價 USD')] == '115000'
    assert tri['ro'] == [_col(t, '價格')] and tri['calc'] == [_col(t, '廠商報價 TWD')]   # own TWD formula: editable
    assert j['gsheet']['url'].startswith('https://docs.google.com/') and j['gsheet']['error'] is None
    again = _cam(_sheet(app_client))
    assert [r['id'] for r in again['rows']] == [r['id'] for r in t['rows']]
    assert [c['id'] for c in again['columns']] == [c['id'] for c in t['columns']]


def test_edit_on_page_goes_to_google(app_client, mock):
    t = _cam(_sheet(app_client))
    tri = _row(t, '三色相機')
    j = _ops(app_client, {'op': 'set_cell', 'table': t['id'], 'row': tri['id'], 'col': _col(t, '廠商報價 USD'), 'value': '120000'},
             {'op': 'set_cell', 'table': t['id'], 'row': tri['id'], 'col': _col(t, 'QE'), 'value': '1/2 估計'})
    assert j['skipped'] == []
    g = mock.dump()[0]['rows'][4]
    assert g[6] == 120000 and g[5] == '1/2 估計'                       # number stays a number, text stays text
    assert 'GOOGLEFINANCE' in g[7]['f'] and g[7]['v'] == 120000 * RATE  # the conversion is still a formula
    assert _row(_cam(j), '三色相機')['id'] == tri['id']


def test_formula_cell_is_not_overwritten(app_client, mock):
    t = _cam(_sheet(app_client))
    tri = _row(t, '三色相機')
    j = _ops(app_client, {'op': 'set_cell', 'table': t['id'], 'row': tri['id'], 'col': _col(t, '價格'), 'value': '1'})
    assert j['skipped'] and 'formula' in j['skipped'][0]['reason']
    assert mock.dump()[0]['rows'][4][4]['f'] == '=COUNTA(A2:A5)'


def test_twd_quote_typed_over_the_conversion(app_client, mock):
    t = _cam(_sheet(app_client))
    tri, twd = _row(t, '三色相機'), _col(t, '廠商報價 TWD')
    j = _ops(app_client, {'op': 'set_cell', 'table': t['id'], 'row': tri['id'], 'col': twd, 'value': '3500000'})
    assert j['skipped'] == []
    assert mock.dump()[0]['rows'][4][7:9] == [3500000, 'SBIG Aluma CCD47-10']    # a typed TWD amount, not converted back
    row = _row(_cam(j), '三色相機')
    assert row['cells'][twd] == '3500000' and 'calc' not in row and row['cells'][_col(t, '廠商報價 USD')] == '115000'
    j = _ops(app_client, {'op': 'set_cell', 'table': t['id'], 'row': tri['id'], 'col': twd, 'value': ''})
    g = mock.dump()[0]['rows'][4][7]
    assert 'GOOGLEFINANCE' in g['f'] and g['v'] == 115000 * RATE                  # cleared: converted again
    assert _row(_cam(j), '三色相機')['calc'] == [twd]


def test_new_rows_and_usd_get_the_conversion(app_client, mock):
    t = _cam(_sheet(app_client))
    usd, twd, k = _col(t, '廠商報價 USD'), _col(t, '廠商報價 TWD'), t['columns'][0]['id']
    j = _ops(app_client, {'op': 'add_row', 'table': t['id'], 'row': {'id': 'rq', 'cells': {k: 'QHY600', usd: '7000'}}, 'after': _row(t, '三色相機')['id']},
             {'op': 'set_cell', 'table': t['id'], 'row': _row(t, 'IMX461')['id'], 'col': usd, 'value': '9000'})
    assert j['skipped'] == []
    t2 = _cam(j)
    assert _row(t2, 'QHY600')['cells'][twd] == str(7000 * RATE) and _row(t2, 'IMX461')['cells'][twd] == str(9000 * RATE)
    assert _row(t2, 'GSense6060 BI')['cells'].get(twd) is None                  # no USD: empty, not 0


def test_split_quote_column_fills_existing_rows(app_client, mock):
    mock.load([{'id': 0, 'name': 'Camera', 'rows': CAMERA},
               {'id': 7, 'name': 'Mount', 'rows': [['Mount', '價格', '廠商報價', 'Note'], ['L-600', '40000 USD', 38000, ''], ['T-600', '81000 USD', '', 'x']]}])
    m = next(x for x in _sheet(app_client)['doc']['tables'] if x['label'] == 'Mount')
    assert m['kind'] == 'mount'
    q = _col(m, '廠商報價')
    j = _ops(app_client, {'op': 'rename_col', 'table': m['id'], 'col': q, 'name': '廠商報價 USD'},
             {'op': 'add_col', 'table': m['id'], 'col': {'id': 'mtwd', 'name': '廠商報價 TWD'}, 'after': q})
    assert j['skipped'] == []
    g = mock.dump()[7]['rows']
    assert g[0] == ['Mount', '價格', '廠商報價 USD', '廠商報價 TWD', 'Note']
    assert g[1][3]['v'] == 38000 * RATE and g[2][3]['v'] == '' and 'GOOGLEFINANCE' in g[2][3]['f']
    m2 = next(x for x in j['doc']['tables'] if x['label'] == 'Mount')
    assert _row(m2, 'L-600')['calc'] == ['mtwd'] and _row(m2, 'L-600')['cells']['mtwd'] == str(38000 * RATE)


def test_edit_in_google_shows_on_page_with_same_ids(app_client, mock):
    t = _cam(_sheet(app_client))
    ids = {r['cells'][t['columns'][0]['id']]: r['id'] for r in t['rows']}
    mock.edit(0, 3, 1, 'IMX461 Pro')                                  # rename: matched by row number
    mock.edit(0, 2, 6, 'BSI 90%')
    t2 = _cam(_sheet(app_client))
    assert _row(t2, 'IMX461 Pro')['id'] == ids['IMX461']
    assert _row(t2, 'GSense6060 BI')['cells'][_col(t2, 'QE')] == 'BSI 90%'


def test_sort_in_google_keeps_ids_by_name(app_client, mock):
    t = _cam(_sheet(app_client))
    ids = {r['cells'][t['columns'][0]['id']]: r['id'] for r in t['rows']}
    rows = [CAMERA[0], CAMERA[4], CAMERA[2], CAMERA[1]]
    rows[1] = rows[1][:7] + [{'v': 1, 'f': '=G2*1'}] + rows[1][8:]
    mock.load([{'id': 0, 'name': 'Camera', 'rows': rows}])
    t2 = _cam(_sheet(app_client))
    assert {r['cells'][t2['columns'][0]['id']]: r['id'] for r in t2['rows']} == ids


def test_add_row_then_type_in_it(app_client, mock):
    t = _cam(_sheet(app_client))
    after = _row(t, 'IMX461')
    k = t['columns'][0]['id']
    j = _ops(app_client, {'op': 'add_row', 'table': t['id'], 'row': {'id': 'rnew1', 'cells': {}}, 'after': after['id']},
             {'op': 'set_cell', 'table': t['id'], 'row': 'rnew1', 'col': _col(t, 'Note'), 'value': 'blank name'},
             {'op': 'add_row', 'table': t['id'], 'row': {'id': 'rnew2', 'cells': {k: 'IMX455'}}, 'after': 'rnew1'})
    assert j['skipped'] == []
    names = [r[0] for r in _grid(mock)]
    assert names[:5] == ['Sensor', 'GSense6060 BI', 'IMX461', '', 'IMX455']
    assert _grid(mock)[3][8] == 'blank name'
    t2 = _cam(j)
    assert [r['id'] for r in t2['rows']][2:4] == ['rnew1', 'rnew2']
    t3 = _cam(_sheet(app_client))
    assert [r['id'] for r in t3['rows']] == [r['id'] for r in t2['rows']]


def test_delete_row_checks_the_name(app_client, mock):
    t = _cam(_sheet(app_client))
    gone = _row(t, 'GSense6060 BI')
    mock.load([{'id': 0, 'name': 'Camera', 'rows': [CAMERA[0], CAMERA[2], CAMERA[1], CAMERA[4]]}])   # moved in Google
    j = _ops(app_client, {'op': 'delete_row', 'table': t['id'], 'row': gone['id']})
    assert j['skipped'] == []
    assert [r[0] for r in _grid(mock)] == ['Sensor', 'IMX461', '三色相機']
    j = _ops(app_client, {'op': 'set_cell', 'table': t['id'], 'row': gone['id'], 'col': _col(t, 'QE'), 'value': 'x'})
    assert j['skipped']                                               # already gone: nothing written anywhere
    assert [r[0] for r in _grid(mock)] == ['Sensor', 'IMX461', '三色相機']


def test_columns_and_order(app_client, mock):
    t = _cam(_sheet(app_client))
    note = _col(t, 'Note')
    j = _ops(app_client, {'op': 'add_col', 'table': t['id'], 'col': {'id': 'cnew', 'name': 'Weight'}, 'after': note},
             {'op': 'set_cell', 'table': t['id'], 'row': _row(t, 'IMX461')['id'], 'col': 'cnew', 'value': '1 kg'},
             {'op': 'rename_col', 'table': t['id'], 'col': _col(t, 'QE'), 'name': 'QE (peak)'},
             {'op': 'move_col', 'table': t['id'], 'col': 'cnew', 'after': t['columns'][0]['id']})
    assert j['skipped'] == []
    g = _grid(mock)
    assert g[0][:2] == ['Sensor', 'Weight'] and g[2][1] == '1 kg' and 'QE (peak)' in g[0]
    t2 = _cam(j)
    assert [c['id'] for c in t2['columns']][1] == 'cnew'
    order = [r['id'] for r in t2['rows']][::-1]
    j = _ops(app_client, {'op': 'order_rows', 'table': t['id'], 'order': order})
    assert j['skipped'] == [] and [r['id'] for r in _cam(j)['rows']] == order
    assert [r[0] for r in _grid(mock) if r[0]] == ['Sensor', '三色相機', 'IMX461', 'GSense6060 BI']
    j = _ops(app_client, {'op': 'delete_col', 'table': t['id'], 'col': 'cnew'})
    assert 'Weight' not in _grid(mock)[0]


def test_new_table_and_local_only_parts(app_client, mock):
    cols = [{'id': 'a0', 'name': 'Item'}, {'id': 'a1', 'name': '廠商報價 USD'}, {'id': 'a2', 'name': '廠商報價 TWD'}]
    j = _ops(app_client, {'op': 'add_table', 'table': {'id': 'tacc', 'label': 'Accessories', 'kind': 'accessory', 'columns': cols, 'rows': []}},
             {'op': 'add_row', 'table': 'tacc', 'row': {'id': 'ar0', 'cells': {'a0': 'Filter wheel', 'a1': '3000'}}, 'after': None},
             {'op': 'set_fx', 'fx': {'USD': 1, 'TWD': 0.03}},
             {'op': 'set_configs', 'configs': [{'id': 'cfg1', 'name': 'x', 'telescope': None, 'camera': None, 'mount': None,
                                                'accessories': [{'row': 'ar0', 'qty': 2}, {'row': 'bad id!', 'qty': 1}]}]})
    assert j['skipped'] == []
    tabs = {s['name']: s for s in mock.dump().values()}
    head, row = tabs['Accessories']['rows'][:2]
    assert head == ['Item', '廠商報價 USD', '廠商報價 TWD'] and row[:2] == ['Filter wheel', 3000] and row[2]['v'] == 3000 * RATE
    t = next(x for x in _sheet(app_client)['doc']['tables'] if x['label'] == 'Accessories')
    assert t['id'] == 'tacc' and t['kind'] == 'accessory' and t['rows'][0]['id'] == 'ar0'
    doc = _sheet(app_client)['doc']
    assert doc['fx']['TWD'] == 0.03 and doc['configs'][0]['accessories'] == [{'row': 'ar0', 'qty': 2}]
    j = _ops(app_client, {'op': 'delete_table', 'table': 'tacc'})
    assert 'Google Sheets' in j['skipped'][0]['reason'] and 'Accessories' in {s['name'] for s in mock.dump().values()}


def test_google_down_keeps_the_cached_copy(app_client, mock, store):
    first = _sheet(app_client)
    (store / 'gsheet.json').write_text(json.dumps({'url': 'http://127.0.0.1:9/exec', 'secret': 'x'}))
    j = _sheet(app_client)
    assert j['doc']['tables'] == first['doc']['tables'] and j['gsheet']['error']
    t = _cam(j)
    r = app_client.post(URL + '/sheet/ops', json={'ops': [{'op': 'set_cell', 'table': t['id'], 'row': t['rows'][0]['id'],
                                                          'col': t['columns'][0]['id'], 'value': 'x'}]})
    assert r.status_code == 502                                       # the page keeps the edit and retries


def test_wrong_secret_is_refused(app_client, mock, store):
    (store / 'gsheet.json').write_text(json.dumps({'url': mock.base + '/exec', 'secret': 'nope'}))
    assert 'bad secret' in _sheet(app_client)['gsheet']['error']
