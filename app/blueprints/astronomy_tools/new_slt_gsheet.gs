// Kinder New SLT ⇄ this Google Sheet (new_slt_gsheet.py on the Kinder side).
//
// Install once, in the Google Sheet: Extensions › Apps Script › replace Code.gs with this file › set SECRET to the
// value in Kinder's app/data/new_slt/gsheet.json › Deploy › New deployment › type Web app, Execute as: Me,
// Who has access: Anyone › Deploy, allow access, and copy the Web app URL (…/exec) into gsheet.json as "url".
//
// Kinder POSTs JSON {secret, action: "read" | "apply", ops: [...]} and gets back {ok, results, tabs, final}.
// Every tab whose name does not start with "_" is one table; row 1 is the header. Rows are found by the text in
// their first column (checked against the row number Kinder last saw), columns by their header, so sorting or
// inserting rows here does not confuse Kinder. Cells holding a formula are never overwritten.

const SECRET = 'PASTE-THE-SECRET-HERE';

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'bad request' }); }
  if (!body || SECRET.indexOf('PASTE-') === 0 || body.secret !== SECRET) return out_({ ok: false, error: 'bad secret' });
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(25000)) return out_({ ok: false, error: 'busy' });
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const st = {};
    let results = [];
    if (body.action === 'apply') results = (body.ops || []).map((op) => {
      try { return Object.assign({ ok: true }, applyOne_(ss, st, op) || {}); }
      catch (err) { return { ok: false, error: String((err && err.message) || err) }; }
    });
    else if (body.action !== 'read') return out_({ ok: false, error: 'unknown action' });
    SpreadsheetApp.flush();
    const final = {};
    Object.keys(st).forEach((k) => { final[k] = { rows: st[k].rows, cols: st[k].cols }; });
    return out_({ ok: true, results: results, final: final, tabs: readTabs_(ss) });
  } catch (err) {
    return out_({ ok: false, error: String((err && err.message) || err) });
  } finally {
    lock.releaseLock();
  }
}

function doGet() { return out_({ ok: false, error: 'POST only' }); }

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function readTabs_(ss) {
  return ss.getSheets().filter((sh) => sh.getName().charAt(0) !== '_').map((sh) => {
    const r = sh.getDataRange();
    return { name: sh.getName(), sheetId: sh.getSheetId(), values: r.getDisplayValues(), formulas: r.getFormulas() };
  });
}

// Per tab, the rows / columns as they are now, each named by where it was when this request started ("r5", "c3")
// or by the Kinder id it was created with in this request ("n:<id>").
function tab_(ss, st, sheetId) {
  if (!st[sheetId]) {
    const sh = ss.getSheets().filter((s) => s.getSheetId() === sheetId)[0];
    if (!sh) throw new Error('tab not found (deleted or renamed in Google Sheets?)');
    const nr = Math.max(sh.getLastRow(), 1), nc = Math.max(sh.getLastColumn(), 1);
    const rows = [], cols = [];
    for (let i = 1; i <= nr; i++) rows.push('r' + i);
    for (let i = 1; i <= nc; i++) cols.push('c' + i);
    st[sheetId] = { sh: sh, rows: rows, cols: cols };
  }
  return st[sheetId];
}

const norm_ = (v) => String(v == null ? '' : v).trim();

function rowAt_(t, loc) {
  if (loc.id) { const i = t.rows.indexOf('n:' + loc.id); if (i >= 0) return i + 1; }
  const key = norm_(loc.key);
  const i = t.rows.indexOf('r' + loc.n);
  if (i > 0 && norm_(t.sh.getRange(i + 1, 1).getDisplayValue()) === key) return i + 1;
  if (key) {
    const last = Math.max(t.sh.getLastRow(), 1);
    const vals = t.sh.getRange(1, 1, last, 1).getDisplayValues();
    const hits = [];
    for (let j = 1; j < vals.length; j++) if (norm_(vals[j][0]) === key) hits.push(j + 1);
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) throw new Error('more than one row named "' + key + '"');
  }
  throw new Error('row "' + (key || '(no name)') + '" moved or was deleted in Google Sheets');
}

function colAt_(t, loc) {
  if (loc.id) { const i = t.cols.indexOf('n:' + loc.id); if (i >= 0) return i + 1; }
  const name = norm_(loc.name);
  const i = t.cols.indexOf('c' + loc.i);
  if (i >= 0 && norm_(t.sh.getRange(1, i + 1).getDisplayValue()) === name) return i + 1;
  if (name) {
    const vals = t.sh.getRange(1, 1, 1, Math.max(t.sh.getLastColumn(), 1)).getDisplayValues()[0];
    const hits = [];
    vals.forEach((v, j) => { if (norm_(v) === name) hits.push(j + 1); });
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) throw new Error('more than one column named "' + name + '"');
  }
  throw new Error('column "' + (name || '(no name)') + '" moved or was deleted in Google Sheets');
}

// A plain number is stored as a number (so formulas such as =G9*GOOGLEFINANCE(...) keep working); anything else as
// text, exactly as typed (the leading ' stops Sheets turning "1/2" into a date or "=..." into a formula).
function put_(range, value) {
  if (range.getFormula()) throw new Error('that cell is a formula in Google Sheets');
  const v = String(value == null ? '' : value);
  if (v === '') range.clearContent();
  else if (/^-?\d+(\.\d+)?$/.test(v)) range.setValue(Number(v));
  else range.setValue("'" + v);
}

function putCells_(t, row, cells) {
  (cells || []).forEach((c) => put_(t.sh.getRange(row, colAt_(t, c.col)), c.value));
}

function applyOne_(ss, st, op) {
  if (op.op === 'add_tab') {
    if (ss.getSheetByName(op.name)) throw new Error('a tab named "' + op.name + '" already exists');
    const sh = ss.insertSheet(op.name, ss.getSheets().length);
    const head = op.headers || [];
    const body = op.rows || [];
    if (head.length) {
      sh.getRange(1, 1, 1, head.length).setValues([head.map((h) => "'" + h)]).setFontWeight('bold');
      sh.setFrozenRows(1);
      body.forEach((r, k) => r.forEach((v, j) => { if (v !== '' && v != null) put_(sh.getRange(k + 2, j + 1), v); }));
    }
    return { sheetId: sh.getSheetId() };
  }
  const t = tab_(ss, st, op.sheet);
  const sh = t.sh;
  switch (op.op) {
    case 'set':
      put_(sh.getRange(rowAt_(t, op.row), colAt_(t, op.col)), op.value);
      return {};
    case 'insert_row': {
      const after = op.after ? rowAt_(t, op.after) : 1;      // no row before it: first under the header
      sh.insertRowAfter(after);
      t.rows.splice(after, 0, 'n:' + op.id);
      putCells_(t, after + 1, op.cells);
      return { n: after + 1 };
    }
    case 'delete_row': {
      const n = rowAt_(t, op.row);
      if (n === 1) throw new Error('that is the header row');
      sh.deleteRow(n);
      t.rows.splice(n - 1, 1);
      return {};
    }
    case 'move_row': {
      const n = rowAt_(t, op.row);
      const dest = op.after ? rowAt_(t, op.after) + 1 : 2;
      if (dest === n || dest === n + 1) return {};
      sh.moveRows(sh.getRange(n + ':' + n), dest);
      const tok = t.rows.splice(n - 1, 1)[0];
      t.rows.splice(dest > n ? dest - 2 : dest - 1, 0, tok);
      return {};
    }
    case 'insert_col': {
      const after = op.after ? colAt_(t, op.after) : 0;
      if (after === 0) sh.insertColumnBefore(1); else sh.insertColumnAfter(after);
      t.cols.splice(after, 0, 'n:' + op.id);
      sh.getRange(1, after + 1).setValue("'" + (op.name || '')).setFontWeight('bold');
      return { i: after + 1 };
    }
    case 'rename_col': {
      const c = colAt_(t, op.col);
      sh.getRange(1, c).setValue("'" + (op.name || ''));
      return {};
    }
    case 'delete_col': {
      const c = colAt_(t, op.col);
      sh.deleteColumn(c);
      t.cols.splice(c - 1, 1);
      return {};
    }
    case 'move_col': {
      const c = colAt_(t, op.col);
      const dest = op.after ? colAt_(t, op.after) + 1 : 1;
      if (dest === c || dest === c + 1) return {};
      sh.moveColumns(sh.getRange(1, c, 1, 1), dest);   // whole column
      const tok = t.cols.splice(c - 1, 1)[0];
      t.cols.splice(dest > c ? dest - 2 : dest - 1, 0, tok);
      return {};
    }
    case 'rename_tab':
      sh.setName(op.name);
      return {};
    case 'move_tab':
      ss.setActiveSheet(sh);
      ss.moveActiveSheet(Math.max(1, Math.min(op.index, ss.getSheets().length)));
      return {};
  }
  throw new Error('unknown op ' + op.op);
}
