"""New SLT (/new_slt): planning the next SLT — equipment sheet (cameras, telescopes, mounts), FOV simulator, budget.

Not linked from any page and not indexed: reached only by its address, and only with the password. Everything lives
outside git under app/data/new_slt/ (the repository is public):

    access.json   {"password_hash": "<werkzeug generate_password_hash(...)>"}      no file: the page is 404
    sheet.json    {"rev": 12, "updated": "...", "updated_by": "...", "doc": {...}}  created from SEED on first open

Set or change the password (signs everyone out):

    python -m app.blueprints.astronomy_tools.new_slt set-password

With app/data/new_slt/gsheet.json the tables live in a Google Sheet instead (new_slt_gsheet.py).

The page edits the sheet with small operations (set a cell, add a row, …, see apply_op) that the server applies to its
current copy, so two people editing different cells at once do not overwrite each other.
"""
import copy
import fcntl
import hashlib
import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager

from flask import abort, jsonify, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.core import rate_limit
from app.paths import DATA_DIR

from . import astronomy_tools_bp
from .helpers import _client_ip

logger = logging.getLogger(__name__)

STORE_DIR = DATA_DIR / 'new_slt'
ACCESS_FILE = STORE_DIR / 'access.json'
SHEET_FILE = STORE_DIR / 'sheet.json'
SESSION_KEY = 'new_slt_access'
LOGIN_BURST, LOGIN_WINDOW_S = 8, 600          # password tries per IP
OPS_BURST, OPS_WINDOW_S = 240, 60             # edit requests per IP

MAX_TABLES, MAX_COLS, MAX_ROWS = 30, 60, 2000
MAX_CELL, MAX_NAME, MAX_OPS, MAX_CONFIGS = 4000, 120, 500, 80
MAX_DOC_BYTES = 3 * 1024 * 1024
KINDS = ('camera', 'telescope', 'mount', 'other')
_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


# ── seed ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _table(tid, label, kind, columns, rows, widths=None):
    cols = [{'id': f'{tid}c{i}', 'name': n, 'width': (widths or {}).get(n, 140)} for i, n in enumerate(columns)]
    return {'id': tid, 'label': label, 'kind': kind, 'columns': cols,
            'rows': [{'id': f'{tid}r{j}', 'cells': {c['id']: v for c, v in zip(cols, r) if v != ''}}
                     for j, r in enumerate(rows)]}


def seed_doc():
    camera = _table('cam', 'Camera', 'camera',
                    ['Sensor', '品牌', '大小', 'Pixel Size', '價格', 'QE', '廠商報價', 'Note'], [
        ['GSense6060 BI', '', '6144×6144 | 61.4×61.4 mm | 對角 86.9 mm', '10 µm', '~180,000 USD（待確認）',
         'BSI（筆記未附 QE）', '', '片幅最大；Full well 95k e⁻'],
        ['GSense4040 BI', '', '4096×4096 | 36.9×36.9 mm | 對角 52.1 mm', '9 µm', '>30,000 USD',
         '官方 QE 曲線（見圖）', '', '尺寸跟 IMX455 差不多；Full well 39k e⁻'],
        ['IMX411', '', '14192×10640 | 53.4×40 mm | 對角 66.7 mm（中片幅）', '3.76 µm', '>10,000 EUR',
         '無官方；他人實測約 50%', '', '尺寸最大（中片幅）；超過 50 mm 可能要換濾鏡；Full well 50k e⁻'],
        ['IMX461', '', '11656×8742 | 43.8×32.9 mm | 對角 54.8 mm', '3.76 µm', '>19,000 EUR',
         '無官方；他人實測與 IMX455', '', '尺寸略小於 IMX411；大帥那台；Full well 50k e⁻'],
        ['IMX455', '', '9568×6380 | 36×24 mm | 對角 43.2 mm（全片幅）', '3.76 µm', '>6,100 EUR',
         '官方 QE 曲線（見圖）', '', '7DT 用這台；Full well 50k e⁻'],
        ['GSense400 BI', '', '2048×2048 | 22.5×22.5 mm | 對角 31.9 mm', '11 µm', '（筆記未列）',
         'BSI（筆記未附 QE）', '', '片幅最小；Full well 90k e⁻'],
        ['iKon-L 936 (DZ936)', 'Andor', '2048×2048 | 27.6×27.6 mm | 對角 39.1 mm', '13.5 µm', '', '', '',
         '現役 SLT 相機，比較用'],
    ], {'Sensor': 170, '大小': 330, 'QE': 200, 'Note': 380, '價格': 170})
    telescope = _table('tel', 'Telescope', 'telescope',
                       ['Telescope', '品牌', 'Aperture (mm)', 'Focal length (mm)', 'f-ratio', 'Image circle (mm)',
                        '價格', '廠商報價', 'Note'], [
        ['DeltaRho 500', 'PlaneWave', '508', '1537', 'f/3.03', '70', '', '',
         '20″；像場 70 mm（>2.6°）；中央遮蔽 59%（直徑）；後焦 232.8 mm'],
        ['SLT 40 cm (現役)', 'Lulin', '400', '3320', 'f/8.3', '', '', '', '現役 SLT，比較用'],
    ], {'Telescope': 170, 'Note': 380})
    mount = _table('mnt', 'Mount', 'mount',
                   ['Mount', '品牌', '型式', 'Payload', '重量', '價格', '廠商報價', 'Note'], [
        ['L-600', 'PlaneWave', 'Direct-drive alt-az（可加楔台當赤道儀）', '136 kg (300 lb)', '153 kg',
         '~40,000 USD（官網）', '', '原設計給 CDK24'],
        ['T-600', 'PlaneWave', 'Direct-drive gimbal（高度軸兩側都能掛）', '272 kg (600 lb)', '274 kg',
         '65,000–81,000 USD（官網兩頁不同，待確認）', '', '可並掛兩支 CDK24'],
    ], {'型式': 280, 'Note': 260, '價格': 280})
    configs = [{'id': f'cfg{i}', 'name': f'DR500 + {row["cells"]["camc0"]}', 'telescope': 'telr0', 'camera': row['id'],
                'mount': 'mntr0', 'reducer': 1, 'rotation': 0, 'color': color, 'extras': []}
               for i, (row, color) in enumerate(zip(camera['rows'][:6], ['#F39F5A', '#4CD964', '#74B9FF', '#FF6B61',
                                                                          '#C792EA', '#FFD166']))]
    configs.append({'id': 'cfg_now', 'name': 'Current SLT', 'telescope': 'telr1', 'camera': 'camr6', 'mount': None,
                    'reducer': 1, 'rotation': 0, 'color': '#FFFFFF', 'extras': []})
    return {'tables': [camera, telescope, mount], 'configs': configs,
            'fx': {'USD': 1.0, 'EUR': 1.096, 'TWD': 0.030349, 'JPY': 0.006270}}   # 2026-11-27: 1 USD = 32.95 TWD, 159.5 JPY


# ── storage ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_access():
    try:
        return json.loads(ACCESS_FILE.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.error('new_slt: cannot read %s: %s', ACCESS_FILE, e)
        return None


@contextmanager
def _locked():
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_DIR / '.lock', 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_sheet():
    try:
        return json.loads(SHEET_FILE.read_text())
    except FileNotFoundError:
        return {'rev': 0, 'updated': None, 'updated_by': None, 'doc': seed_doc()}


def _write_sheet(state):
    tmp = SHEET_FILE.with_suffix(f'.tmp{os.getpid()}')
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':')))
    os.replace(tmp, SHEET_FILE)


def load_sheet():
    with _locked():
        return _read_sheet()


def _fingerprint(access):
    return hashlib.sha256((access.get('password_hash') or '').encode()).hexdigest()[:16]


def _unlocked(access):
    return bool(access) and session.get(SESSION_KEY) == _fingerprint(access)


def _no_index(resp):
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _who():
    u = session.get('user') or {}
    return (u.get('name') or u.get('email') or 'guest')[:80]


# ── operations ───────────────────────────────────────────────────────────────────────────────────────────────────────

class OpError(ValueError):
    pass


def _id(v):
    if not isinstance(v, str) or not _ID.match(v):
        raise OpError('bad id')
    return v


def _text(v, limit):
    if v is None:
        return ''
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        raise OpError('bad text')
    return v[:limit]


def _find(items, iid, what):
    for i, x in enumerate(items):
        if x.get('id') == iid:
            return i, x
    raise OpError(f'{what} not found')


def _insert_after(items, item, after):
    """Insert after the item with id `after`; None → at the start; unknown id → at the end."""
    if after is None:
        items.insert(0, item)
        return
    for i, x in enumerate(items):
        if x.get('id') == after:
            items.insert(i + 1, item)
            return
    items.append(item)


def _clean_config(c):
    if not isinstance(c, dict):
        raise OpError('bad config')

    def num(v, lo, hi, default):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return default
        return min(max(x, lo), hi) if x == x else default

    extras = []
    for e in (c.get('extras') or [])[:30]:
        if isinstance(e, dict):
            extras.append({'label': _text(e.get('label'), MAX_NAME), 'amount': num(e.get('amount'), 0, 1e10, 0),
                           'currency': _text(e.get('currency'), 8) or 'USD',
                           'qty': num(e.get('qty'), 0, 1000, 1)})
    color = c.get('color') if isinstance(c.get('color'), str) and _COLOR.match(c.get('color')) else '#F39F5A'
    ref = lambda k: c.get(k) if isinstance(c.get(k), str) and _ID.match(c.get(k)) else None  # noqa: E731
    return {'id': _id(c.get('id')), 'name': _text(c.get('name'), MAX_NAME), 'telescope': ref('telescope'),
            'camera': ref('camera'), 'mount': ref('mount'), 'reducer': num(c.get('reducer'), 0.1, 5, 1),
            'rotation': num(c.get('rotation'), -360, 360, 0), 'color': color, 'extras': extras,
            'qty': num(c.get('qty'), 1, 100, 1),
            'pixels': _text(c.get('pixels'), 40), 'pixel_um': _text(c.get('pixel_um'), 20),
            'focal_mm': _text(c.get('focal_mm'), 20)}


def apply_op(doc, op):
    """Apply one edit to doc in place. Ops name tables, rows and columns by id, so they still apply after someone
    else's edit; an op on something already deleted raises OpError and is skipped."""
    if not isinstance(op, dict):
        raise OpError('bad op')
    kind = op.get('op')
    tables = doc.setdefault('tables', [])

    if kind == 'add_table':
        if len(tables) >= MAX_TABLES:
            raise OpError('too many tables')
        t = op.get('table') or {}
        tid = _id(t.get('id'))
        if any(x['id'] == tid for x in tables):
            raise OpError('table exists')
        cols = [{'id': _id(c.get('id')), 'name': _text(c.get('name'), MAX_NAME), 'width': 140}
                for c in (t.get('columns') or [])[:MAX_COLS] if isinstance(c, dict)]
        tables.append({'id': tid, 'label': _text(t.get('label'), MAX_NAME) or 'Sheet',
                       'kind': t.get('kind') if t.get('kind') in KINDS else 'other', 'columns': cols, 'rows': []})
        return
    if kind == 'set_configs':
        configs = op.get('configs')
        if not isinstance(configs, list) or len(configs) > MAX_CONFIGS:
            raise OpError('bad configs')
        doc['configs'] = [_clean_config(c) for c in configs]
        return
    if kind == 'set_fx':
        fx = op.get('fx')
        if not isinstance(fx, dict) or len(fx) > 20:
            raise OpError('bad fx')
        out = {}
        for k, v in fx.items():
            if isinstance(k, str) and re.match(r'^[A-Z]{3}$', k):
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    continue
                if 0 < x < 1e6:
                    out[k] = x
        out['USD'] = 1.0
        doc['fx'] = out
        return

    ti, t = _find(tables, _id(op.get('table')), 'table')
    cols, rows = t['columns'], t['rows']

    if kind == 'set_cell':
        _, row = _find(rows, _id(op.get('row')), 'row')
        cid = _id(op.get('col'))
        _find(cols, cid, 'column')
        value = _text(op.get('value'), MAX_CELL)
        if value:
            row['cells'][cid] = value
        else:
            row['cells'].pop(cid, None)
    elif kind == 'add_row':
        if len(rows) >= MAX_ROWS:
            raise OpError('too many rows')
        r = op.get('row') or {}
        rid = _id(r.get('id'))
        if any(x['id'] == rid for x in rows):
            raise OpError('row exists')
        col_ids = {c['id'] for c in cols}
        cells = {k: _text(v, MAX_CELL) for k, v in (r.get('cells') or {}).items() if k in col_ids and v not in ('', None)}
        _insert_after(rows, {'id': rid, 'cells': cells}, op.get('after'))
    elif kind == 'delete_row':
        ri, _ = _find(rows, _id(op.get('row')), 'row')
        rows.pop(ri)
    elif kind == 'move_row':
        ri, row = _find(rows, _id(op.get('row')), 'row')
        rows.pop(ri)
        _insert_after(rows, row, op.get('after'))
    elif kind == 'order_rows':
        order = op.get('order')
        if not isinstance(order, list):
            raise OpError('bad order')
        pos = {rid: i for i, rid in enumerate(order) if isinstance(rid, str)}
        rows.sort(key=lambda r: pos.get(r['id'], len(pos)))
    elif kind == 'add_col':
        if len(cols) >= MAX_COLS:
            raise OpError('too many columns')
        c = op.get('col') or {}
        cid = _id(c.get('id'))
        if any(x['id'] == cid for x in cols):
            raise OpError('column exists')
        _insert_after(cols, {'id': cid, 'name': _text(c.get('name'), MAX_NAME), 'width': 140}, op.get('after'))
    elif kind == 'delete_col':
        ci, col = _find(cols, _id(op.get('col')), 'column')
        cols.pop(ci)
        for r in rows:
            r['cells'].pop(col['id'], None)
    elif kind == 'rename_col':
        _, col = _find(cols, _id(op.get('col')), 'column')
        col['name'] = _text(op.get('name'), MAX_NAME)
    elif kind == 'resize_col':
        _, col = _find(cols, _id(op.get('col')), 'column')
        try:
            col['width'] = int(min(max(float(op.get('width')), 48), 900))
        except (TypeError, ValueError):
            raise OpError('bad width')
    elif kind == 'move_col':
        ci, col = _find(cols, _id(op.get('col')), 'column')
        cols.pop(ci)
        _insert_after(cols, col, op.get('after'))
    elif kind == 'rename_table':
        t['label'] = _text(op.get('label'), MAX_NAME) or t['label']
        if op.get('kind') in KINDS:
            t['kind'] = op.get('kind')
    elif kind == 'delete_table':
        tables.pop(ti)
    elif kind == 'move_table':
        tables.pop(ti)
        _insert_after(tables, t, op.get('after'))
    else:
        raise OpError('unknown op')


# ── routes ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@astronomy_tools_bp.route('/new_slt', methods=['GET', 'POST'])
def new_slt():
    access = load_access()
    if not access or not access.get('password_hash'):
        abort(404)
    error = None
    if request.method == 'POST':
        if not rate_limit.allow(f'new_slt_login:{_client_ip()}', LOGIN_BURST, LOGIN_WINDOW_S):
            error = 'Too many tries. Wait a few minutes.'
        elif check_password_hash(access['password_hash'], (request.form.get('password') or '')[:256]):
            session[SESSION_KEY] = _fingerprint(access)
            return _no_index(redirect(url_for('astronomy_tools.new_slt'), 303))
        else:
            error = 'Wrong password.'
    if not _unlocked(access):
        return _no_index(make_response(render_template('new_slt.html', locked=True, error=error,
                                                       current_path='/new_slt'), 401 if error else 200))
    return _no_index(make_response(render_template('new_slt.html', locked=False, current_path='/new_slt')))


@astronomy_tools_bp.route('/new_slt/lock', methods=['POST'])
def new_slt_lock():
    session.pop(SESSION_KEY, None)
    return _no_index(redirect(url_for('astronomy_tools.new_slt'), 303))


def _guard():
    access = load_access()
    if not access or not access.get('password_hash'):
        abort(404)
    if not _unlocked(access):
        abort(403)


def _state_json(state, **extra):
    from . import new_slt_gsheet as gs
    cfg = gs.load_config()
    if cfg:
        extra['gsheet'] = gs.public_info(cfg, state)
    return _no_index(jsonify({'rev': state['rev'], 'updated': state.get('updated'),
                              'updated_by': state.get('updated_by'), 'doc': state['doc'], **extra}))


@astronomy_tools_bp.route('/new_slt/sheet', methods=['GET'])
def new_slt_sheet():
    """The whole sheet; ?since=<rev> answers {"rev": n, "same": true} when nothing changed."""
    _guard()
    from . import new_slt_gsheet as gs
    cfg = gs.load_config()
    state = gs.pull(cfg) if cfg else load_sheet()       # Google Sheets is the master copy when it is set up
    since = request.args.get('since', type=int)
    if since is not None and since == state['rev']:
        return _no_index(jsonify({'rev': state['rev'], 'same': True,
                                  **({'gsheet': gs.public_info(cfg, state)} if cfg else {})}))
    return _state_json(state)


@astronomy_tools_bp.route('/new_slt/sheet/ops', methods=['POST'])
def new_slt_ops():
    _guard()
    if not rate_limit.allow(f'new_slt_ops:{_client_ip()}', OPS_BURST, OPS_WINDOW_S):
        return _no_index(jsonify({'error': 'Too many edits at once. Wait a moment.'})), 429
    body = request.get_json(silent=True) or {}
    ops = body.get('ops')
    if not isinstance(ops, list) or not ops or len(ops) > MAX_OPS:
        return _no_index(jsonify({'error': 'No edits.'})), 400
    from . import new_slt_gsheet as gs
    cfg = gs.load_config()
    if cfg:
        try:
            state, skipped = gs.apply_ops(ops, cfg, _who())
        except gs.SyncError as e:
            return _no_index(jsonify({'error': str(e)})), 502
        return _state_json(state, skipped=skipped)
    skipped = []
    with _locked():
        state = _read_sheet()
        doc = copy.deepcopy(state['doc'])
        for i, op in enumerate(ops):
            try:
                apply_op(doc, op)
            except OpError as e:
                skipped.append({'index': i, 'reason': str(e)})
        if len(json.dumps(doc, ensure_ascii=False).encode()) > MAX_DOC_BYTES:
            return _no_index(jsonify({'error': 'The sheet is too large.'})), 413
        if len(skipped) < len(ops):
            state = {'rev': state['rev'] + 1, 'updated': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                     'updated_by': _who(), 'doc': doc}
            _write_sheet(state)
    return _state_json(state, skipped=skipped)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cli(argv):
    if argv[:1] != ['set-password']:
        print('usage: python -m app.blueprints.astronomy_tools.new_slt set-password   (reads the password from stdin)')
        return 2
    import getpass
    pw = getpass.getpass('New password: ') if sys.stdin.isatty() else sys.stdin.readline().rstrip('\n')
    if not pw:
        print('empty password, nothing changed')
        return 1
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    ACCESS_FILE.write_text(json.dumps({'password_hash': generate_password_hash(pw)}))
    os.chmod(ACCESS_FILE, 0o600)
    print(f'wrote {ACCESS_FILE}')
    return 0


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
