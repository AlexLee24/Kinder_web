// Runs app/blueprints/astronomy_tools/new_slt_gsheet.gs (the real Apps Script) against an in-memory stand-in for
// SpreadsheetApp, behind a small HTTP server that answers like an Apps Script web app (POST → 302 → GET result).
//   node tests/new_slt_gsheet_mock.js <port> [seed.json]
// Test hooks: POST /__load {sheets: [{id, name, rows: [[value | {v, f}]]}]} replaces the spreadsheet,
//             GET /__dump returns it, POST /__edit {sheet, row, col, value} edits a cell as a person in Google would.
'use strict';
const fs = require('fs');
const http = require('http');
const path = require('path');
const vm = require('vm');

let book = { sheets: [] };
let nextId = 1000;

function load(seed) {
    book = { sheets: (seed.sheets || []).map((s) => ({ id: s.id, name: s.name, grid: (s.rows || []).map((r) => r.map(cell)) })) };
}
const cell = (x) => (x && typeof x === 'object' ? { v: x.v, f: x.f || '' } : { v: x == null ? '' : x, f: '' });
const shown = (c) => (c ? String(c.v === null || c.v === undefined ? '' : c.v) : '');
const colNum = (L) => L.split('').reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
const colName = (n) => { let s = ''; while (n) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - m - 1) / 26; } return s; };
const RATE = 32;   // stand-in for GOOGLEFINANCE("CURRENCY:USDTWD")

function Sheet(s) {
    const g = () => s.grid;
    const at = (r, c) => { while (g().length < r) g().push([]); const row = g()[r - 1]; while (row.length < c) row.push({ v: '', f: '' }); return row; };
    const lastRow = () => { for (let r = g().length; r >= 1; r--) if (g()[r - 1].some((c) => shown(c) !== '' || c.f)) return r; return 0; };
    const lastCol = () => { let m = 0; g().forEach((row) => row.forEach((c, j) => { if (shown(c) !== '' || c.f) m = Math.max(m, j + 1); })); return m; };
    // formulas are evaluated only for the USD → TWD shape, reading the USD cell in the same row (as Sheets does after moves)
    const evalRow = (row) => row.forEach((c) => {
        const m = c.f && c.f.match(/^=IF\(ISNUMBER\(([A-Z]+)\d+\),[A-Z]+\d+\*GOOGLEFINANCE/);
        if (m) { const u = row[colNum(m[1]) - 1]; c.v = u && typeof u.v === 'number' ? u.v * RATE : ''; }
    });
    const self = {
        getName: () => s.name, setName: (n) => { s.name = n; return self; }, getSheetId: () => s.id,
        getLastRow: lastRow, getLastColumn: lastCol, setFrozenRows: () => self,
        getDataRange: () => Range(1, 1, Math.max(lastRow(), 1), Math.max(lastCol(), 1)),
        getRange: (a, b, c, d) => {
            if (typeof a === 'string') { const m = a.match(/^(\d+):(\d+)$/); if (!m) throw new Error('mock: A1 ' + a); return Range(+m[1], 1, +m[2] - +m[1] + 1, Math.max(lastCol(), 1)); }
            return Range(a, b, c || 1, d || 1);
        },
        insertRowAfter: (n) => { at(n, 1); g().splice(n, 0, []); return self; },
        insertColumnBefore: (c) => { g().forEach((row) => { while (row.length < c - 1) row.push({ v: '', f: '' }); row.splice(c - 1, 0, { v: '', f: '' }); }); return self; },
        insertColumnAfter: (c) => { g().forEach((row) => { while (row.length < c) row.push({ v: '', f: '' }); row.splice(c, 0, { v: '', f: '' }); }); return self; },
        deleteRow: (n) => { g().splice(n - 1, 1); return self; },
        deleteColumn: (c) => { g().forEach((row) => row.splice(c - 1, 1)); return self; },
        moveRows: (range, dest) => {      // dest: index before the move
            const n = range._r; at(Math.max(n, dest - 1), 1);
            const row = g()[n - 1]; g().splice(n - 1, 1); g().splice(dest > n ? dest - 2 : dest - 1, 0, row);
        },
        moveColumns: (range, dest) => {
            const c = range._c;
            g().forEach((row) => { while (row.length < Math.max(c, dest)) row.push({ v: '', f: '' }); const x = row.splice(c - 1, 1)[0]; row.splice(dest > c ? dest - 2 : dest - 1, 0, x); });
        },
    };
    function Range(r, c, nr, nc) {
        const get = (fn) => { g().forEach(evalRow); const out = []; for (let i = 0; i < nr; i++) { const line = []; for (let j = 0; j < nc; j++) { const row = g()[r - 1 + i] || []; line.push(fn(row[c - 1 + j])); } out.push(line); } return out; };
        const put = (i, j, v) => {
            const row = at(r + i, c + j);
            if (typeof v === 'string' && v.charAt(0) === "'") row[c - 1 + j] = { v: v.slice(1), f: '' };
            else if (typeof v === 'string' && v.charAt(0) === '=') throw new Error('mock: formulas are not evaluated');
            else row[c - 1 + j] = { v: v, f: '' };
        };
        const rg = {
            _r: r, _c: c,
            getDisplayValue: () => get(shown)[0][0], getDisplayValues: () => get(shown),
            getFormula: () => get((x) => (x ? x.f : ''))[0][0], getFormulas: () => get((x) => (x ? x.f : '')),
            setValue: (v) => { put(0, 0, v); return rg; },
            setValues: (vals) => { vals.forEach((line, i) => line.forEach((v, j) => put(i, j, v))); return rg; },
            clearContent: () => { for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) put(i, j, ''); return rg; },
            setFontWeight: () => rg, setNumberFormat: () => rg,
            setFormula: (f) => { const row = at(r, c); row[c - 1] = { v: '', f }; return rg; },
            getA1Notation: () => colName(c) + r, getRow: () => r, getSheet: () => self,
        };
        return rg;
    }
    return self;
}

let active = null;
const ss = {
    getSheets: () => book.sheets.map(Sheet),
    getSheetByName: (n) => { const s = book.sheets.find((x) => x.name === n); return s ? Sheet(s) : null; },
    insertSheet: (name, index) => { const s = { id: nextId++, name, grid: [] }; book.sheets.splice(index == null ? book.sheets.length : index, 0, s); return Sheet(s); },
    setActiveSheet: (sh) => { active = sh.getSheetId(); },
    moveActiveSheet: (pos) => { const i = book.sheets.findIndex((x) => x.id === active); const s = book.sheets.splice(i, 1)[0]; book.sheets.splice(pos - 1, 0, s); },
};
const ctx = vm.createContext({
    SpreadsheetApp: { getActiveSpreadsheet: () => ss, flush: () => {} },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    ContentService: { createTextOutput: (s) => ({ s, setMimeType() { return this; } }), MimeType: { JSON: 'json' } },
    JSON, String, Number, Math, Object, Array, Error,
});
const src = fs.readFileSync(path.join(__dirname, '..', 'app', 'blueprints', 'astronomy_tools', 'new_slt_gsheet.gs'), 'utf8')
    .replace("const SECRET = 'PASTE-THE-SECRET-HERE';", "const SECRET = 'test-secret';");
const doPost = vm.runInContext(src + '\n;doPost', ctx);

const results = {};
let seq = 0;
const port = +process.argv[2] || 8799;
if (process.argv[3]) load(JSON.parse(fs.readFileSync(process.argv[3], 'utf8')));
http.createServer((req, res) => {
    let body = '';
    req.on('data', (d) => { body += d; });
    req.on('end', () => {
        const json = (o, code) => { res.writeHead(code || 200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
        try {
            if (req.method === 'POST' && req.url === '/__load') { load(JSON.parse(body)); return json({ ok: true }); }
            if (req.url === '/__dump') return json({ sheets: book.sheets.map((s) => ({ id: s.id, name: s.name, rows: s.grid.map((r) => r.map((c) => (c.f ? { v: c.v, f: c.f } : c.v))) })) });
            if (req.method === 'POST' && req.url === '/__edit') { const e = JSON.parse(body); Sheet(book.sheets.find((x) => x.id === e.sheet)).getRange(e.row, e.col).setValue(e.value); return json({ ok: true }); }
            if (req.method === 'POST' && req.url === '/exec') {
                const id = String(++seq);
                results[id] = doPost({ postData: { contents: body } }).s;
                res.writeHead(302, { Location: '/result/' + id }); return res.end();
            }
            const m = req.url.match(/^\/result\/(\d+)$/);
            if (req.method === 'GET' && m && results[m[1]]) { res.writeHead(200, { 'Content-Type': 'application/json' }); const s = results[m[1]]; delete results[m[1]]; return res.end(s); }
            json({ error: 'not found' }, 404);
        } catch (e) { json({ error: String(e && e.stack || e) }, 500); }
    });
}).listen(port, '127.0.0.1', () => console.log('gsheet mock on ' + port));
