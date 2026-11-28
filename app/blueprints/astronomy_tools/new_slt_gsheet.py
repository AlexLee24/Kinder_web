"""New SLT ⇄ Google Sheets: when app/data/new_slt/gsheet.json exists, the Google Sheet is the master copy of the
equipment tables and sheet.json only caches it (plus what lives only in Kinder: setups, FX rates, column widths).

    gsheet.json  {"url": "https://script.google.com/macros/s/…/exec", "secret": "…", "sheet_url": "https://docs.google.com/…"}

The Apps Script in new_slt_gsheet.gs (installed in the Google Sheet, see its header) answers POSTs from here:

  * read   — every tab (not starting with "_") as display values + formulas. The page's GET pulls at most every
             PULL_EVERY_S seconds and rebuilds the tables from it, keeping Kinder's row / column / table ids stable
             (rows matched by their first-column text, then by row number; tables by tab id).
  * apply  — an edit made on the page (set a cell, add a row, …) is translated into the same edit in Google Sheets,
             sent at once, and the tables are rebuilt from Google's answer. An edit Google refuses (the row was deleted
             there, the cell is a formula) is reported back as skipped, so nothing is half-applied.

Deleting a whole tab is only done in Google Sheets.
"""
import copy
import json
import logging
import re
import secrets
import time

import requests

from .new_slt import OpError, MAX_DOC_BYTES, apply_op
from . import new_slt as ns

logger = logging.getLogger(__name__)

PULL_EVERY_S = 10          # the page polls every 15 s: each poll may read Google once
TIMEOUT_S = 45
LOCAL_OPS = ('set_configs', 'set_fx', 'resize_col')
AUTO_TWD = re.compile(r'GOOGLEFINANCE\("CURRENCY:USDTWD"\)', re.I)   # the script's own USD → TWD formula: editable


class SyncError(Exception):
    pass


def config_file():
    return ns.STORE_DIR / 'gsheet.json'


def load_config():
    try:
        c = json.loads(config_file().read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.error('new_slt gsheet: cannot read %s: %s', config_file(), e)
        return None
    return c if isinstance(c, dict) and c.get('url') and c.get('secret') else None


def call(cfg, action, ops=None):
    """POST to the Apps Script; Google answers with a redirect to the result, which requests follows as a GET."""
    try:
        r = requests.post(cfg['url'], json={'secret': cfg['secret'], 'action': action, 'ops': ops or []},
                          timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise SyncError(f'Google Sheets did not answer ({e.__class__.__name__})')
    try:
        j = r.json()
    except ValueError:
        raise SyncError(f'Google Sheets answered HTTP {r.status_code}, not data (is the script deployed for Anyone?)')
    if not isinstance(j, dict) or not j.get('ok'):
        raise SyncError('Google Sheets: ' + str((j or {}).get('error') or 'error'))
    return j


# ── Google tabs → Kinder tables ──────────────────────────────────────────────────────────────────────────────────────

def _s(v):
    return str('' if v is None else v).strip()


def _new_id(prefix, taken):
    while True:
        i = f'{prefix}{secrets.token_hex(4)}'
        if i not in taken:
            taken.add(i)
            return i


def _match(new, old, prefix, taken):
    """new: [(key, pos)]; old: [(key, pos, id)]. Same key (unique on both sides) first, then same position, else a
    new id. Returns one id per new item."""
    out = [None] * len(new)
    free = {o[2] for o in old}
    nk = {}
    for k, _ in new:
        nk[k] = nk.get(k, 0) + 1
    ok = {}
    for o in old:
        ok[o[0]] = ok.get(o[0], 0) + 1
    by_key = {o[0]: o[2] for o in old if o[0] and ok[o[0]] == 1}
    for x, (k, _) in enumerate(new):
        if k and nk[k] == 1 and k in by_key and by_key[k] in free:
            out[x] = by_key[k]
            free.discard(by_key[k])
    by_pos = {}
    for o in old:
        if o[2] in free and o[1] is not None:
            by_pos.setdefault(o[1], o[2])
    for x, (_, p) in enumerate(new):
        if out[x] is None and p in by_pos and by_pos[p] in free:
            out[x] = by_pos[p]
            free.discard(by_pos[p])
    for x in range(len(new)):
        if out[x] is None:
            out[x] = _new_id(prefix, taken)
    return out


def _guess_kind(name):
    n = name.lower()
    for kind, words in (('camera', ('camera', 'sensor', '相機')), ('telescope', ('telescope', 'ota', '望遠鏡')),
                        ('mount', ('mount', '赤道儀', '腳架')), ('accessory', ('accessor', '配件'))):
        if any(w in n for w in words):
            return kind
    return 'other'


def key_col(t):
    """The Kinder column that is column A in Google Sheets (rows are found by its text), or None."""
    return next((c for c in t['columns'] if c.get('i') == 1), None)


def row_key(t, r):
    c = key_col(t)
    return _s(r['cells'].get(c['id'])) if c else ''


def _table_from_tab(tab, prev, tid, taken):
    values = tab.get('values') or []
    formulas = tab.get('formulas') or []
    header = values[0] if values else []
    ncols = max((len(r) for r in values), default=0)
    keep = [j for j in range(ncols)
            if (j < len(header) and _s(header[j])) or any(j < len(r) and _s(r[j]) for r in values[1:])]
    prev_cols = (prev or {}).get('columns', [])
    cids = _match([(_s(header[j]) if j < len(header) else '', j + 1) for j in keep],
                  [(_s(c.get('name')), c.get('i'), c['id']) for c in prev_cols], tid + 'c', taken)
    width = {c['id']: c.get('width', 140) for c in prev_cols}
    columns = [{'id': cid, 'name': _s(header[j]) if j < len(header) else '', 'width': width.get(cid, 140), 'i': j + 1}
               for cid, j in zip(cids, keep)]

    raw = [(n, r) for n, r in enumerate(values[1:], start=2) if any(_s(v) for v in r)]
    prev_rows = (prev or {}).get('rows', [])
    pt = prev or {'columns': []}
    rids = _match([(_s(r[0]) if r else '', n) for n, r in raw],
                  [(row_key(pt, r), r.get('n'), r['id']) for r in prev_rows], tid + 'r', taken)
    rows = []
    for rid, (n, r) in zip(rids, raw):
        f = formulas[n - 1] if n - 1 < len(formulas) else []
        cells, ro, calc = {}, [], []
        for c, j in zip(columns, keep):
            v = _s(r[j]) if j < len(r) else ''
            if v:
                cells[c['id']] = v
            if j < len(f) and _s(f[j]):
                (calc if AUTO_TWD.search(_s(f[j])) else ro).append(c['id'])
        row = {'id': rid, 'cells': cells, 'n': n}
        if ro:
            row['ro'] = ro
        if calc:
            row['calc'] = calc
        rows.append(row)
    kind = prev['kind'] if prev else _guess_kind(tab['name'])
    return {'id': tid, 'label': tab['name'], 'kind': kind, 'columns': columns, 'rows': rows, 'gs_sheet': tab['sheetId']}


def tables_from_tabs(tabs, prev_doc):
    prev_tables = prev_doc.get('tables', [])
    by_sheet = {t['gs_sheet']: t for t in prev_tables if t.get('gs_sheet') is not None}
    by_label = {}
    for t in prev_tables:
        by_label.setdefault(t.get('label'), t)
    taken = {t['id'] for t in prev_tables}
    for t in prev_tables:
        taken.update(c['id'] for c in t['columns'])
        taken.update(r['id'] for r in t['rows'])
    used, out = set(), []
    for tab in tabs:
        prev = by_sheet.get(tab['sheetId'])
        if prev is None or prev['id'] in used:
            cand = by_label.get(tab['name'])
            prev = cand if cand is not None and cand['id'] not in used and cand.get('gs_sheet') in (None, tab['sheetId']) else None
        tid = prev['id'] if prev else _new_id('t', taken)
        used.add(tid)
        out.append(_table_from_tab(tab, prev, tid, taken))
    return out


# ── Kinder ops → Google ops ──────────────────────────────────────────────────────────────────────────────────────────

def _find(items, iid, what):
    for i, x in enumerate(items):
        if x['id'] == iid:
            return i, x
    raise OpError(f'{what} not found')


class _Batch:
    def __init__(self, doc):
        self.doc = doc
        self.new_rows, self.new_cols = set(), set()

    def table(self, op):
        _, t = _find(self.doc['tables'], op.get('table'), 'table')
        if t.get('gs_sheet') is None:
            raise OpError('that sheet is not in Google Sheets yet')
        return t

    def rloc(self, t, rid):
        _, r = _find(t['rows'], rid, 'row')
        if rid in self.new_rows:
            return {'id': rid}
        return {'n': r.get('n'), 'key': row_key(t, r)}

    def cloc(self, t, cid):
        _, c = _find(t['columns'], cid, 'column')
        if cid in self.new_cols:
            return {'id': cid}
        return {'i': c.get('i'), 'name': _s(c.get('name'))}

    def translate(self, op):
        """Google ops for one Kinder op, computed on the document before the op is applied."""
        kind = op.get('op') if isinstance(op, dict) else None
        if kind in LOCAL_OPS:
            return []
        if kind == 'add_table':
            t = op.get('table') or {}
            return [{'op': 'add_tab', 'tid': t.get('id'), 'name': _s(t.get('label')) or 'Sheet',
                     'headers': [_s(c.get('name')) for c in (t.get('columns') or []) if isinstance(c, dict)]}]
        if kind == 'delete_table':
            raise OpError('delete the tab in Google Sheets')
        t = self.table(op)
        sid = t['gs_sheet']
        if kind == 'set_cell':
            _, r = _find(t['rows'], op.get('row'), 'row')
            if op.get('col') in r.get('ro', []):
                raise OpError('that cell is a formula in Google Sheets')
            return [{'op': 'set', 'sheet': sid, 'row': self.rloc(t, r['id']), 'col': self.cloc(t, op.get('col')),
                     'value': op.get('value') or ''}]
        if kind == 'add_row':
            row = op.get('row') or {}
            after = op.get('after')
            if after is not None and not any(r['id'] == after for r in t['rows']):
                after = t['rows'][-1]['id'] if t['rows'] else None
            cols = {c['id'] for c in t['columns']}
            out = [{'op': 'insert_row', 'sheet': sid, 'id': row.get('id'),
                    'after': self.rloc(t, after) if after is not None else None,
                    'cells': [{'col': self.cloc(t, k), 'value': v} for k, v in (row.get('cells') or {}).items()
                              if k in cols and v not in ('', None)]}]
            self.new_rows.add(row.get('id'))
            return out
        if kind == 'delete_row':
            return [{'op': 'delete_row', 'sheet': sid, 'row': self.rloc(t, op.get('row'))}]
        if kind == 'move_row':
            after = op.get('after')
            return [{'op': 'move_row', 'sheet': sid, 'row': self.rloc(t, op.get('row')),
                     'after': self.rloc(t, after) if after is not None else None}]
        if kind == 'order_rows':
            tmp = copy.deepcopy(t)
            apply_op({'tables': [tmp]}, dict(op, table=tmp['id']))
            order = [r['id'] for r in tmp['rows']]
            return [{'op': 'move_row', 'sheet': sid, 'row': self.rloc(t, rid),
                     'after': self.rloc(t, order[k - 1]) if k else None} for k, rid in enumerate(order)]
        if kind == 'add_col':
            col = op.get('col') or {}
            after = op.get('after')
            out = [{'op': 'insert_col', 'sheet': sid, 'id': col.get('id'), 'name': _s(col.get('name')),
                    'after': self.cloc(t, after) if after is not None else None}]
            self.new_cols.add(col.get('id'))
            return out
        if kind == 'delete_col':
            return [{'op': 'delete_col', 'sheet': sid, 'col': self.cloc(t, op.get('col'))}]
        if kind == 'rename_col':
            return [{'op': 'rename_col', 'sheet': sid, 'col': self.cloc(t, op.get('col')), 'name': _s(op.get('name'))}]
        if kind == 'move_col':
            after = op.get('after')
            return [{'op': 'move_col', 'sheet': sid, 'col': self.cloc(t, op.get('col')),
                     'after': self.cloc(t, after) if after is not None else None}]
        if kind == 'rename_table':
            label = _s(op.get('label'))
            return [{'op': 'rename_tab', 'sheet': sid, 'name': label}] if label and label != t['label'] else []
        if kind == 'move_table':
            tmp = {'tables': [dict(x) for x in self.doc['tables']]}
            apply_op(tmp, op)
            index = next(k for k, x in enumerate(tmp['tables'], start=1) if x['id'] == t['id'])
            return [{'op': 'move_tab', 'sheet': sid, 'index': index}]
        raise OpError('unknown op')

    def settle(self, answer, sent):
        """After a Google call: new tabs get their sheet id, every row / column its position now."""
        for (_, gop), res in zip(sent, answer.get('results') or []):
            if gop['op'] == 'add_tab' and res.get('ok'):
                t = next((x for x in self.doc['tables'] if x['id'] == gop['tid'] and x.get('gs_sheet') is None), None)
                if t:
                    t['gs_sheet'] = res['sheetId']
                    for k, c in enumerate(t['columns'], start=1):
                        c['i'] = k
        for sid, fin in (answer.get('final') or {}).items():
            t = next((x for x in self.doc['tables'] if str(x.get('gs_sheet')) == str(sid)), None)
            if not t:
                continue
            rpos = {tok: k for k, tok in enumerate(fin.get('rows') or [], start=1)}
            cpos = {tok: k for k, tok in enumerate(fin.get('cols') or [], start=1)}
            for r in t['rows']:
                tok = 'n:' + r['id'] if r['id'] in self.new_rows else f"r{r.get('n')}"
                r['n'] = rpos.get(tok)
            for c in t['columns']:
                tok = 'n:' + c['id'] if c['id'] in self.new_cols else f"c{c.get('i')}"
                c['i'] = cpos.get(tok)
        self.new_rows.clear()
        self.new_cols.clear()


def apply_ops(ops, cfg, who):
    """The synced version of the /new_slt/sheet/ops route: returns (state, skipped)."""
    skipped = []
    with ns._locked():
        state = ns._read_sheet()
        doc = copy.deepcopy(state['doc'])
        if 'gs_pulled' not in state:                    # never read from Google yet: start from its tables
            doc['tables'] = tables_from_tabs(call(cfg, 'read')['tabs'], doc)
        b = _Batch(doc)
        sent, tabs, local_changed = [], None, False

        def flush():
            nonlocal tabs
            if not sent:
                return
            answer = call(cfg, 'apply', [g for _, g in sent])
            failed = {}
            for (i, _), res in zip(sent, answer.get('results') or []):
                if not res.get('ok'):
                    failed.setdefault(i, res.get('error') or 'refused by Google Sheets')
            skipped.extend({'index': i, 'reason': why} for i, why in failed.items())
            b.settle(answer, sent)
            tabs = answer.get('tabs')
            sent.clear()

        for i, op in enumerate(ops):
            try:
                gops = b.translate(op)
                apply_op(doc, op)
            except (OpError, StopIteration, KeyError, TypeError) as e:
                skipped.append({'index': i, 'reason': str(e) if isinstance(e, OpError) else 'bad op'})
                continue
            if not gops:
                local_changed = True
            sent.extend((i, g) for g in gops)
            if op.get('op') == 'add_table':
                flush()
        flush()
        if tabs is not None:
            doc['tables'] = tables_from_tabs(tabs, doc)
        if len(json.dumps(doc, ensure_ascii=False).encode()) > MAX_DOC_BYTES:
            raise SyncError('The sheet is too large.')
        if tabs is not None or local_changed:
            state = dict(state, rev=state['rev'] + 1, updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), updated_by=who,
                         doc=doc, gs_seq=state.get('gs_seq', 0) + 1, gs_error=None,
                         **({'gs_pulled': time.time()} if tabs is not None else {}))
            ns._write_sheet(state)
    return state, skipped


def pull(cfg, force=False):
    """Refresh the cached tables from Google Sheets when the copy is older than PULL_EVERY_S. Never raises: on a
    failure the cached copy is kept and the error is stored in the state for the page to show."""
    state = ns._read_sheet()
    if not force and time.time() - state.get('gs_pulled', 0) < PULL_EVERY_S:
        return state
    seq = state.get('gs_seq', 0)
    try:
        tabs, err = call(cfg, 'read')['tabs'], None
    except SyncError as e:
        tabs, err = None, str(e)
        logger.warning('new_slt gsheet pull: %s', e)
    with ns._locked():
        state = ns._read_sheet()
        if state.get('gs_seq', 0) != seq:          # an edit went to Google meanwhile: its answer is newer than ours
            return state
        state['gs_pulled'], state['gs_error'] = time.time(), err
        if tabs is not None:
            tables = tables_from_tabs(tabs, state['doc'])
            if tables != state['doc'].get('tables'):
                state = dict(state, rev=state['rev'] + 1, updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                             updated_by='Google Sheets', doc=dict(state['doc'], tables=tables))
        ns._write_sheet(state)
    return state


def public_info(cfg, state):
    """What the page shows: the Google Sheet link, when it was last read, and the last error."""
    pulled = state.get('gs_pulled')
    return {'url': cfg.get('sheet_url') or '', 'error': state.get('gs_error'),
            'pulled': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(pulled)) if pulled else None}
