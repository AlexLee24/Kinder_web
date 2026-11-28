// New SLT (/new_slt, new_slt.py / new_slt.html): FOV simulator, compare + budget table and the equipment sheet.
//
// One shared document (window.NEW_SLT.sheet): {tables: [{id, label, kind, columns: [{id, name, width}],
// rows: [{id, cells: {colId: text}}]}], configs: [...], fx: {USD: 1, EUR: …}}. Every edit is a small op (set_cell,
// add_row, …) applied here at once and sent to the server, which applies it to its own copy; the reply is the
// server's whole document, onto which the ops still in flight are applied again. Every 15 s the page asks whether
// someone else changed it.
(function () {
    'use strict';
    const CFG = window.NEW_SLT;
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const uid = (p) => p + Math.random().toString(36).slice(2, 10);
    const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
    const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } };
    const COLORS = ['#F39F5A', '#4CD964', '#74B9FF', '#FF6B61', '#C792EA', '#FFD166', '#5AF3E0', '#FF9FF3', '#FFFFFF'];

    // ═══ shared document + sync ════════════════════════════════════════════════════════════════════════════════
    const S = { doc: null, rev: 0, pending: [], inflight: null, updated: null, by: null, error: null, timer: null,
                drafts: {} };   // configs / fx typed but not sent yet (debounced): kept over a server reply
    const listeners = [];
    const onChange = (fn) => listeners.push(fn);
    const emit = () => listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });

    function findById(list, id) { const i = list.findIndex((x) => x.id === id); return i < 0 ? [-1, null] : [i, list[i]]; }
    function insertAfter(list, item, after) {
        if (after == null) { list.unshift(item); return; }
        const i = list.findIndex((x) => x.id === after);
        if (i < 0) list.push(item); else list.splice(i + 1, 0, item);
    }

    // Mirror of new_slt.apply_op (server). Returns false when the op no longer applies.
    function applyOp(doc, op) {
        const tables = doc.tables;
        if (op.op === 'add_table') { if (findById(tables, op.table.id)[1]) return false; tables.push(JSON.parse(JSON.stringify(op.table))); return true; }
        if (op.op === 'set_configs') { doc.configs = JSON.parse(JSON.stringify(op.configs)); return true; }
        if (op.op === 'set_fx') { doc.fx = Object.assign({}, op.fx, { USD: 1 }); return true; }
        const [ti, t] = findById(tables, op.table);
        if (!t) return false;
        const cols = t.columns, rows = t.rows;
        switch (op.op) {
            case 'set_cell': {
                const r = findById(rows, op.row)[1];
                if (!r || !findById(cols, op.col)[1]) return false;
                if (op.value) r.cells[op.col] = op.value; else delete r.cells[op.col];
                return true;
            }
            case 'add_row': if (findById(rows, op.row.id)[1]) return false; insertAfter(rows, { id: op.row.id, cells: Object.assign({}, op.row.cells) }, op.after); return true;
            case 'delete_row': { const i = findById(rows, op.row)[0]; if (i < 0) return false; rows.splice(i, 1); return true; }
            case 'move_row': { const [i, r] = findById(rows, op.row); if (i < 0) return false; rows.splice(i, 1); insertAfter(rows, r, op.after); return true; }
            case 'order_rows': { const pos = new Map(op.order.map((id, i) => [id, i])); rows.sort((a, b) => (pos.has(a.id) ? pos.get(a.id) : 1e9) - (pos.has(b.id) ? pos.get(b.id) : 1e9)); return true; }
            case 'add_col': if (findById(cols, op.col.id)[1]) return false; insertAfter(cols, { id: op.col.id, name: op.col.name || '', width: op.col.width || 140 }, op.after); return true;
            case 'delete_col': { const i = findById(cols, op.col)[0]; if (i < 0) return false; cols.splice(i, 1); rows.forEach((r) => delete r.cells[op.col]); return true; }
            case 'rename_col': { const c = findById(cols, op.col)[1]; if (!c) return false; c.name = op.name; return true; }
            case 'resize_col': { const c = findById(cols, op.col)[1]; if (!c) return false; c.width = Math.round(Math.min(Math.max(op.width, 48), 900)); return true; }
            case 'move_col': { const [i, c] = findById(cols, op.col); if (i < 0) return false; cols.splice(i, 1); insertAfter(cols, c, op.after); return true; }
            case 'rename_table': if (op.label) t.label = op.label; if (op.kind) t.kind = op.kind; return true;
            case 'delete_table': tables.splice(ti, 1); return true;
            case 'move_table': tables.splice(ti, 1); insertAfter(tables, t, op.after); return true;
        }
        return false;
    }

    function send(ops) {
        ops.forEach((op) => applyOp(S.doc, op));
        S.pending.push(...ops);
        emit();
        clearTimeout(S.timer);
        S.timer = setTimeout(flush, 250);
    }

    function adopt(state) {
        // the server's document + whatever we have not sent yet
        S.doc = state.doc; S.rev = state.rev; S.updated = state.updated; S.by = state.updated_by;
        S.pending.forEach((op) => applyOp(S.doc, op));
        if (S.drafts.configs) S.doc.configs = S.drafts.configs;
        if (S.drafts.fx) S.doc.fx = S.drafts.fx;
    }

    function flush() {
        if (S.inflight || !S.pending.length) return;
        const ops = S.pending.splice(0, 400);
        S.inflight = ops;
        setSync('saving');
        fetch(CFG.ops, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ ops }) })
            .then((r) => r.json().then((j) => ({ ok: r.ok, status: r.status, j })))
            .then(({ ok, status, j }) => {
                S.inflight = null;
                if (status === 403) { location.reload(); return; }
                if (!ok) throw new Error(j.error || ('HTTP ' + status));
                S.error = null;
                adopt(j);
                if (j.skipped && j.skipped.length) toast(j.skipped.length + ' edit(s) no longer applied (someone changed that part).');
                emit();
                if (S.pending.length) flush(); else setSync('saved');
            })
            .catch((e) => {
                S.inflight = null;
                S.pending.unshift(...ops);        // try again
                S.error = e.message;
                setSync('error');
                setTimeout(flush, 4000);
            });
    }

    function poll() {
        if (document.hidden || S.inflight || S.pending.length || Sheet.isEditing() || Object.keys(S.drafts).length) return;
        fetch(CFG.sheet + '?since=' + S.rev, { credentials: 'same-origin' })
            .then((r) => { if (r.status === 403) location.reload(); return r.json(); })
            .then((j) => {
                if (j.same || S.inflight || S.pending.length || Sheet.isEditing()) return;
                adopt(j); emit(); setSync('saved');
            }).catch(() => {});
    }

    function setSync(state) {
        const el = $('nsSync');
        if (!el) return;
        el.dataset.state = state;
        if (state === 'saving') el.textContent = 'Saving…';
        else if (state === 'error') el.textContent = 'Not saved — retrying (' + (S.error || 'offline') + ')';
        else {
            let when = '';
            if (S.updated) { const d = new Date(S.updated.replace(/([+-]\d\d)(\d\d)$/, '$1:$2')); if (!isNaN(d)) when = d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
            el.textContent = S.updated ? ('Saved · ' + when + (S.by ? ' · ' + S.by : '')) : 'Saved';
        }
    }
    window.addEventListener('beforeunload', (e) => { if (S.pending.length || S.inflight) { e.preventDefault(); e.returnValue = ''; } });

    let toastTimer = null;
    function toast(msg) {
        const el = $('nsToast'); el.textContent = msg; el.hidden = false;
        clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
    }

    // ═══ reading numbers out of free text ══════════════════════════════════════════════════════════════════════
    function firstNum(s) {
        const m = String(s || '').replace(/(\d),(?=\d{3}\b)/g, '$1').match(/-?\d+(?:\.\d+)?/);
        return m ? parseFloat(m[0]) : null;
    }
    function parsePixels(s) {
        const m = String(s || '').replace(/,/g, '').match(/(\d{3,6})\s*[×xX*]\s*(\d{3,6})/);
        return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null;
    }
    // a price is read one way only: the amount, then EUR, USD, TWD or JPY ("73000 USD", "~180,000 USD (TBC)", ">19,000 EUR").
    // No code → nocur: shown with a reminder and left out of the totals (never assumed USD).
    const CODE = /(?:^|[^A-Za-z])(EUR|USD|TWD|JPY)(?![A-Za-z])/i;
    function parsePrice(s) {
        s = String(s || '');
        const m = s.replace(/(\d),(?=\d{3}\b)/g, '$1').match(/\d+(?:\.\d+)?/);
        if (!m) return null;
        const code = s.match(CODE);
        return { amount: parseFloat(m[0]), currency: code ? code[1].toUpperCase() : null, nocur: !code,
                 approx: /[~≈>＞<]|–|—|-\s*\d|待|約|起/.test(s), text: s };
    }

    function tablesOf(kind) { return S.doc.tables.filter((t) => t.kind === kind); }
    function colMatch(t, re) { return t.columns.find((c) => re.test(c.name || '')); }
    function rowLookup(kind, id) {
        for (const t of tablesOf(kind)) { const r = t.rows.find((x) => x.id === id); if (r) return { t, r }; }
        return null;
    }
    function rowName(t, r) { const c = t.columns[0]; return (c && r.cells[c.id]) || '(unnamed)'; }
    function cell(t, r, re) { const c = colMatch(t, re); return c ? (r.cells[c.id] || '') : ''; }
    function rowPrice(t, r) {
        const quote = parsePrice(cell(t, r, /廠商報價|quote|報價/i));
        if (quote) return Object.assign(quote, { source: 'quote' });
        const list = parsePrice(cell(t, r, /^(價格|price|cost|定價|list)/i));
        return list ? Object.assign(list, { source: 'list' }) : null;
    }
    const toUSD = (p) => (p && p.currency ? p.amount * (S.doc.fx[p.currency] || 0) : 0);
    const usdToTWD = (v) => (S.doc.fx.TWD ? v / S.doc.fx.TWD : 0);

    function cameraSpecs(t, r) {
        let px = null;
        const prefer = colMatch(t, /大小|size|resolution|解析|format/i);
        if (prefer) px = parsePixels(r.cells[prefer.id]);
        if (!px) for (const c of t.columns) { px = parsePixels(r.cells[c.id]); if (px) break; }
        const um = firstNum(cell(t, r, /pixel\s*size|像素|像元|pixel/i));
        return { px, um };
    }
    function telescopeSpecs(t, r) {
        return { focal: firstNum(cell(t, r, /focal|焦長|焦距/i)), aperture: firstNum(cell(t, r, /aperture|口徑|diam/i)),
                 circle: firstNum(cell(t, r, /image\s*circle|像場|circle/i)) };
    }

    function compute(cfg) {
        const tel = cfg.telescope && rowLookup('telescope', cfg.telescope);
        const cam = cfg.camera && rowLookup('camera', cfg.camera);
        const mnt = cfg.mount && rowLookup('mount', cfg.mount);
        const ts = tel ? telescopeSpecs(tel.t, tel.r) : {};
        const cs = cam ? cameraSpecs(cam.t, cam.r) : {};
        const focal = firstNum(cfg.focal_mm) || ts.focal;
        const px = parsePixels(cfg.pixels) || cs.px;
        const um = firstNum(cfg.pixel_um) || cs.um;
        const out = { cfg, tel, cam, mnt, aperture: ts.aperture, circle: ts.circle, focal, px, um, ok: false };
        out.telName = tel ? rowName(tel.t, tel.r) : '—';
        out.camName = cam ? rowName(cam.t, cam.r) : '—';
        out.mntName = mnt ? rowName(mnt.t, mnt.r) : '—';
        out.prices = { tel: tel && rowPrice(tel.t, tel.r), cam: cam && rowPrice(cam.t, cam.r), mnt: mnt && rowPrice(mnt.t, mnt.r) };
        const extrasUSD = (cfg.extras || []).reduce((s, e) => s + (e.amount || 0) * (e.qty == null ? 1 : e.qty) * (S.doc.fx[e.currency] || 0), 0);
        out.extrasUSD = extrasUSD;
        const qty = cfg.qty || 1;
        out.totalUSD = qty * (toUSD(out.prices.tel) + toUSD(out.prices.cam) + toUSD(out.prices.mnt) + extrasUSD);
        const picked = ['tel', 'cam', 'mnt'].filter((k) => (k === 'mnt' ? cfg.mount : (k === 'tel' ? cfg.telescope : cfg.camera)));
        out.missing = picked.filter((k) => !out.prices[k]);
        out.nocur = picked.filter((k) => out.prices[k] && out.prices[k].nocur);
        out.approx = ['tel', 'cam', 'mnt'].some((k) => out.prices[k] && out.prices[k].approx);
        if (focal && px && um) {
            const f = focal * (cfg.reducer || 1);
            out.fEff = f;
            out.fRatio = out.aperture ? f / out.aperture : null;
            out.scale = 206.265 * um / f;                         // arcsec / pixel
            out.w = px[0] * out.scale / 3600; out.h = px[1] * out.scale / 3600;   // degrees
            out.area = out.w * out.h;
            out.sensorW = px[0] * um / 1000; out.sensorH = px[1] * um / 1000;
            out.diag = Math.hypot(out.sensorW, out.sensorH);
            out.circleDeg = out.circle ? (out.circle / f) * 180 / Math.PI : null;   // diameter on the sky
            out.etendue = out.aperture ? Math.PI * Math.pow(out.aperture / 2000, 2) * out.area : null;  // m² deg²
            out.ok = true;
        }
        return out;
    }

    const fmtAngle = (deg) => (deg >= 1 ? deg.toFixed(2) + '°' : (deg * 60 >= 1 ? (deg * 60).toFixed(1) + '′' : (deg * 3600).toFixed(0) + '″'));
    const fmtPair = (w, h) => {
        const m = Math.max(w, h);
        if (m >= 1) return w.toFixed(2) + '° × ' + h.toFixed(2) + '°';
        if (m * 60 >= 1) return (w * 60).toFixed(1) + '′ × ' + (h * 60).toFixed(1) + '′';
        return (w * 3600).toFixed(0) + '″ × ' + (h * 3600).toFixed(0) + '″';
    };
    const fmtMoney = (v, cur) => {
        if (!v) return '—';
        const sym = { USD: '$', EUR: '€', TWD: 'NT$', JPY: '¥' }[cur] || '';
        return sym + Math.round(v).toLocaleString('en-US');
    };

    // ═══ setups (configs) ══════════════════════════════════════════════════════════════════════════════════════
    let visible = new Set(lsGet('ns-visible', null) || []);
    let visibleInit = !!lsGet('ns-visible', null);
    let editingCfg = null;
    function saveVisible() { lsSet('ns-visible', Array.from(visible)); }
    function configs() { return S.doc.configs || []; }
    let cfgTimer = null;
    function setConfigs(list, now) {
        S.doc.configs = list;
        clearTimeout(cfgTimer);
        const go = () => { delete S.drafts.configs; send([{ op: 'set_configs', configs: S.doc.configs }]); };
        if (now) go();
        else { S.drafts.configs = list; emit(); cfgTimer = setTimeout(go, 500); }
    }

    function renderCfgList() {
        const ul = $('nsCfgs');
        if (!visibleInit) { configs().forEach((c) => visible.add(c.id)); visibleInit = true; saveVisible(); }
        ul.innerHTML = configs().map((c) => {
            const x = compute(c);
            const sub = x.ok ? (fmtPair(x.w, x.h) + ' · ' + x.scale.toFixed(2) + '″/px') : 'needs focal length, pixels and pixel size';
            return '<li class="' + (editingCfg === c.id ? 'is-open' : '') + '" data-id="' + esc(c.id) + '">' +
                '<input type="checkbox" class="ns-cfg-vis" aria-label="Show ' + esc(c.name) + '"' + (visible.has(c.id) ? ' checked' : '') + '>' +
                '<span class="ns-swatch" style="--c:' + esc(c.color) + '"></span>' +
                '<button type="button" class="ns-cfg-name"><b>' + esc(c.name || '(unnamed)') + '</b><small>' + esc(sub) + '</small></button>' +
                '<button type="button" class="ns-cfg-solo" title="Show only this one">only</button></li>';
        }).join('') || '<li class="ns-empty">No setups yet.</li>';
    }

    function optionList(kind, sel, allowNone) {
        let html = allowNone ? '<option value="">— none —</option>' : '';
        tablesOf(kind).forEach((t) => {
            html += '<optgroup label="' + esc(t.label) + '">' + t.rows.map((r) => '<option value="' + esc(r.id) + '"' + (r.id === sel ? ' selected' : '') + '>' + esc(rowName(t, r)) + '</option>').join('') + '</optgroup>';
        });
        return html;
    }

    function renderCfgEditor() {
        const box = $('nsCfgEditor');
        const c = configs().find((x) => x.id === editingCfg);
        if (!c) { box.hidden = true; box.innerHTML = ''; return; }
        if (box.contains(document.activeElement) && box.dataset.id === c.id) return;   // do not rebuild under the cursor
        const x = compute(c);
        box.dataset.id = c.id;
        box.hidden = false;
        box.innerHTML =
            '<div class="ns-ed-grid">' +
            '<label class="ns-wide">Name<input class="ns-input" data-k="name" value="' + esc(c.name) + '"></label>' +
            '<label class="ns-wide">Telescope<select class="ns-input" data-k="telescope">' + optionList('telescope', c.telescope, true) + '</select></label>' +
            '<label class="ns-wide">Camera<select class="ns-input" data-k="camera">' + optionList('camera', c.camera, true) + '</select></label>' +
            '<label class="ns-wide">Mount<select class="ns-input" data-k="mount">' + optionList('mount', c.mount, true) + '</select></label>' +
            '<label>Reducer / extender ×<input class="ns-input" type="number" step="0.01" min="0.1" max="5" data-k="reducer" value="' + esc(c.reducer || 1) + '"></label>' +
            '<label>Rotation (°)<input class="ns-input" type="number" step="1" data-k="rotation" value="' + esc(c.rotation || 0) + '"></label>' +
            '<label>Units<input class="ns-input" type="number" step="1" min="1" max="100" data-k="qty" value="' + esc(c.qty || 1) + '"></label>' +
            '<label>Colour<span class="ns-colors">' + COLORS.map((k) => '<button type="button" class="ns-color' + (k === c.color ? ' is-on' : '') + '" data-color="' + k + '" style="--c:' + k + '" aria-label="' + k + '"></button>').join('') + '</span></label>' +
            '</div>' +
            '<details class="ns-override"' + (c.focal_mm || c.pixels || c.pixel_um ? ' open' : '') + '><summary>Override sheet numbers</summary><div class="ns-ed-grid">' +
            '<label>Focal length (mm)<input class="ns-input" data-k="focal_mm" placeholder="' + esc(x.tel ? (telescopeSpecs(x.tel.t, x.tel.r).focal || '') : '') + '" value="' + esc(c.focal_mm || '') + '"></label>' +
            '<label>Pixel size (µm)<input class="ns-input" data-k="pixel_um" placeholder="' + esc(x.cam ? (cameraSpecs(x.cam.t, x.cam.r).um || '') : '') + '" value="' + esc(c.pixel_um || '') + '"></label>' +
            '<label class="ns-wide">Pixels (W×H)<input class="ns-input" data-k="pixels" placeholder="' + esc(x.cam && cameraSpecs(x.cam.t, x.cam.r).px ? cameraSpecs(x.cam.t, x.cam.r).px.join('×') : '') + '" value="' + esc(c.pixels || '') + '"></label>' +
            '</div></details>' +
            '<div class="ns-extras"><div class="ns-extras-head"><span>Other costs (filters, focuser, dome, shipping…)</span><button type="button" class="kw-btn kw-btn-sm kw-btn-ghost" data-act="add-extra">+ Line</button></div>' +
            (c.extras || []).map((e, i) => '<div class="ns-extra" data-i="' + i + '">' +
                '<input class="ns-input" data-e="label" placeholder="Item" value="' + esc(e.label) + '">' +
                '<input class="ns-input ns-num" type="number" min="0" step="1" data-e="qty" title="Quantity" value="' + esc(e.qty == null ? 1 : e.qty) + '">' +
                '<input class="ns-input ns-num" type="number" min="0" step="any" data-e="amount" placeholder="Amount" value="' + esc(e.amount || '') + '">' +
                '<select class="ns-input" data-e="currency">' + Object.keys(S.doc.fx).map((k) => '<option' + (k === e.currency ? ' selected' : '') + '>' + k + '</option>').join('') + '</select>' +
                '<button type="button" class="ns-x" data-act="del-extra" aria-label="Remove">×</button></div>').join('') +
            '</div>' +
            '<div class="ns-ed-actions"><button type="button" class="kw-btn kw-btn-sm kw-btn-ghost" data-act="dup">Duplicate</button>' +
            '<button type="button" class="kw-btn kw-btn-sm kw-btn-danger" data-act="del">Delete</button>' +
            '<button type="button" class="kw-btn kw-btn-sm kw-btn-primary" data-act="done">Done</button></div>';
    }

    function updateCfg(id, fn, now) {
        const list = JSON.parse(JSON.stringify(configs()));
        const c = list.find((x) => x.id === id);
        if (!c) return;
        fn(c, list);
        setConfigs(list, now);
    }

    function bindSetups() {
        $('nsCfgs').addEventListener('click', (e) => {
            const li = e.target.closest('li[data-id]');
            if (!li) return;
            const id = li.dataset.id;
            if (e.target.classList.contains('ns-cfg-vis')) {
                if (e.target.checked) visible.add(id); else visible.delete(id);
                saveVisible(); Sky.draw(); renderCompare();
            } else if (e.target.closest('.ns-cfg-solo')) {
                visible = new Set([id]); saveVisible(); renderCfgList(); Sky.draw(); Sky.fit(); renderCompare();
            } else if (e.target.closest('.ns-cfg-name')) {
                editingCfg = editingCfg === id ? null : id; renderCfgList(); renderCfgEditor();
            }
        });
        $('nsShowAll').onclick = () => { visible = new Set(configs().map((c) => c.id)); saveVisible(); renderCfgList(); Sky.draw(); Sky.fit(); renderCompare(); };
        $('nsShowNone').onclick = () => { visible = new Set(); saveVisible(); renderCfgList(); Sky.draw(); renderCompare(); };
        $('nsAddCfg').onclick = () => {
            const tel = tablesOf('telescope')[0], cam = tablesOf('camera')[0];
            const used = new Set(configs().map((c) => c.color));
            const c = { id: uid('cfg'), name: 'New setup', telescope: tel && tel.rows[0] ? tel.rows[0].id : null,
                        camera: cam && cam.rows[0] ? cam.rows[0].id : null, mount: null, reducer: 1, rotation: 0, qty: 1,
                        color: COLORS.find((k) => !used.has(k)) || COLORS[0], extras: [] };
            visible.add(c.id); saveVisible(); editingCfg = c.id;
            setConfigs(configs().concat([c]), true);
        };
        const box = $('nsCfgEditor');
        const onField = (e, now) => {
            const id = box.dataset.id, t = e.target;
            if (t.dataset.k) {
                const k = t.dataset.k;
                updateCfg(id, (c) => {
                    if (['reducer', 'rotation', 'qty'].includes(k)) c[k] = parseFloat(t.value) || (k === 'rotation' ? 0 : 1);
                    else if (['telescope', 'camera', 'mount'].includes(k)) c[k] = t.value || null;
                    else c[k] = t.value;
                    if ((k === 'telescope' || k === 'camera') && /^(New setup|.* \+ .*)$/.test(c.name || '')) {
                        const x = compute(c);
                        c.name = (x.telName !== '—' ? x.telName.replace(/^DeltaRho\s*/i, 'DR') : '?') + ' + ' + (x.camName !== '—' ? x.camName : '?');
                        const nameEl = box.querySelector('[data-k="name"]'); if (nameEl) nameEl.value = c.name;
                    }
                }, now);
            } else if (t.dataset.e) {
                const i = +t.closest('.ns-extra').dataset.i, k = t.dataset.e;
                updateCfg(id, (c) => { c.extras[i][k] = (k === 'amount' || k === 'qty') ? (parseFloat(t.value) || 0) : t.value; }, now);
            }
        };
        box.addEventListener('input', (e) => onField(e, false));
        box.addEventListener('change', (e) => { if (e.target.tagName === 'SELECT') onField(e, true); });
        box.addEventListener('click', (e) => {
            const id = box.dataset.id;
            const col = e.target.closest('.ns-color');
            if (col) { updateCfg(id, (c) => { c.color = col.dataset.color; }, true); box.dataset.id = ''; renderCfgEditor(); return; }
            const act = e.target.closest('[data-act]');
            if (!act) return;
            const a = act.dataset.act;
            if (a === 'done') { editingCfg = null; renderCfgList(); renderCfgEditor(); }
            else if (a === 'del') {
                const c = configs().find((x) => x.id === id);
                if (!confirm('Delete the setup "' + (c ? c.name : '') + '"?')) return;
                editingCfg = null; setConfigs(configs().filter((x) => x.id !== id), true);
            } else if (a === 'dup') {
                const c = JSON.parse(JSON.stringify(configs().find((x) => x.id === id)));
                c.id = uid('cfg'); c.name += ' (copy)';
                const used = new Set(configs().map((k) => k.color)); c.color = COLORS.find((k) => !used.has(k)) || c.color;
                visible.add(c.id); saveVisible(); editingCfg = c.id;
                setConfigs(configs().concat([c]), true);
            } else if (a === 'add-extra') {
                updateCfg(id, (c) => { (c.extras = c.extras || []).push({ label: '', qty: 1, amount: 0, currency: 'USD' }); }, true);
                box.dataset.id = ''; renderCfgEditor();
            } else if (a === 'del-extra') {
                const i = +act.closest('.ns-extra').dataset.i;
                updateCfg(id, (c) => { c.extras.splice(i, 1); }, true);
                box.dataset.id = ''; renderCfgEditor();
            }
        });
    }

    // ═══ compare / budget table ════════════════════════════════════════════════════════════════════════════════
    function priceCell(p) {
        if (!p) return '<td class="ns-num ns-dim">—</td>';
        const usd = toUSD(p);
        const title = p.text + (p.source === 'quote' ? ' (廠商報價)' : '');
        if (p.nocur) return '<td class="ns-num is-warn" title="' + esc(title + ' — no currency: write EUR, USD, TWD or JPY after the amount') + '">—<small class="ns-warn-t">no currency</small></td>';
        return '<td class="ns-num" title="' + esc(title) + '">' + (p.approx ? '<span class="ns-approx">≈</span>' : '') + fmtMoney(usd, 'USD') +
            (p.currency !== 'USD' && p.currency !== 'TWD' ? '<small>' + fmtMoney(p.amount, p.currency) + '</small>' : '') +
            (S.doc.fx.TWD ? '<small class="ns-twd">' + fmtMoney(p.currency === 'TWD' ? p.amount : usdToTWD(usd), 'TWD') + '</small>' : '') +
            (p.source === 'quote' ? '<small class="ns-quote">quote</small>' : '') + '</td>';
    }

    function renderCompare() {
        const tbl = $('nsCompare');
        const rows = configs().map(compute);
        const twd = S.doc.fx.TWD ? 1 / S.doc.fx.TWD : null;
        const best = (k, hi) => { const v = rows.filter((x) => x.ok && x[k] != null).map((x) => x[k]); return v.length ? (hi ? Math.max(...v) : Math.min(...v)) : null; };
        const maxArea = best('area', true), maxEt = best('etendue', true);
        tbl.innerHTML = '<thead><tr><th></th><th>Setup</th><th class="ns-num">Focal · f/</th><th class="ns-num">Pixel scale</th><th class="ns-num">Field of view</th>' +
            '<th class="ns-num">Area</th><th class="ns-num" title="Sensor diagonal against the telescope\'s corrected image circle">Sensor ⌀ / circle</th>' +
            '<th class="ns-num" title="Collecting area × field area: survey speed at equal QE">Étendue</th>' +
            '<th class="ns-num">Telescope</th><th class="ns-num">Camera</th><th class="ns-num">Mount</th><th class="ns-num">Other</th><th class="ns-num">Total (USD)</th>' + (twd ? '<th class="ns-num">Total (TWD)</th>' : '') + '</tr></thead><tbody>' +
            rows.map((x) => {
                const c = x.cfg, vis = visible.has(c.id);
                const vign = x.ok && x.circle && x.diag > x.circle;
                return '<tr class="' + (vis ? '' : 'is-hidden') + '" data-id="' + esc(c.id) + '">' +
                    '<td><span class="ns-swatch" style="--c:' + esc(c.color) + '"></span></td>' +
                    '<td class="ns-setup"><b>' + esc(c.name) + (c.qty > 1 ? ' <span class="ns-qty">×' + c.qty + '</span>' : '') + '</b><small>' + esc(x.telName) + ' · ' + esc(x.camName) + (c.mount ? ' · ' + esc(x.mntName) : '') + (c.reducer && c.reducer !== 1 ? ' · ×' + c.reducer : '') + '</small></td>' +
                    (x.ok ? (
                        '<td class="ns-num">' + Math.round(x.fEff) + ' mm' + (x.fRatio ? '<small>f/' + x.fRatio.toFixed(2) + '</small>' : '') + '</td>' +
                        '<td class="ns-num">' + x.scale.toFixed(2) + '″<small>' + x.um + ' µm · ' + x.px[0] + '×' + x.px[1] + '</small></td>' +
                        '<td class="ns-num"><b>' + fmtPair(x.w, x.h) + '</b><small>' + (x.w * 60).toFixed(1) + '′ × ' + (x.h * 60).toFixed(1) + '′</small></td>' +
                        '<td class="ns-num' + (x.area === maxArea ? ' is-best' : '') + '">' + x.area.toFixed(x.area < 0.1 ? 3 : 2) + ' deg²</td>' +
                        '<td class="ns-num' + (vign ? ' is-warn' : '') + '" title="' + (vign ? 'Sensor diagonal is larger than the image circle: corners fall outside the corrected field' : '') + '">' + x.diag.toFixed(1) + ' mm' + (x.circle ? '<small>' + (vign ? '<svg class="kw-ic-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg> ' : '') + 'circle ' + x.circle + ' mm</small>' : '') + '</td>' +
                        '<td class="ns-num' + (x.etendue && x.etendue === maxEt ? ' is-best' : '') + '">' + (x.etendue ? x.etendue.toFixed(3) + '<small>m²·deg²</small>' : '—') + '</td>'
                    ) : '<td colspan="6" class="ns-dim">Missing ' + [!x.focal && 'focal length', !x.px && 'pixel count', !x.um && 'pixel size'].filter(Boolean).join(', ') + ' — add it to the sheet or override it in the setup.</td>') +
                    priceCell(x.prices.tel) + priceCell(x.prices.cam) + priceCell(x.prices.mnt) +
                    '<td class="ns-num">' + (x.extrasUSD ? fmtMoney(x.extrasUSD, 'USD') + (S.doc.fx.TWD ? '<small class="ns-twd">' + fmtMoney(usdToTWD(x.extrasUSD), 'TWD') + '</small>' : '') : '—') + '</td>' +
                    '<td class="ns-num ns-total">' + (x.approx ? '<span class="ns-approx">≈</span>' : '') + fmtMoney(x.totalUSD, 'USD') + [['no price', x.missing], ['no currency', x.nocur]].map(([lab, ks]) => (ks.length ? '<small class="ns-warn-t">' + lab + ': ' + ks.map((k) => ({ tel: 'telescope', cam: 'camera', mnt: 'mount' }[k])).join(', ') + '</small>' : '')).join('') + '</td>' +
                    (twd ? '<td class="ns-num ns-total">' + (x.approx ? '<span class="ns-approx">≈</span>' : '') + fmtMoney(x.totalUSD * twd, 'TWD') + '</td>' : '') +
                    '</tr>';
            }).join('') + '</tbody>';

        const fx = $('nsFx');
        if (!fx.contains(document.activeElement)) {
            fx.innerHTML = '<span>Exchange rates (edit; shared)</span>' + Object.keys(S.doc.fx).filter((k) => k !== 'USD').map((k) =>
                k === 'TWD' || k === 'JPY'
                    ? '<label>1 USD = <input class="ns-input ns-num" type="number" step="any" min="0" data-fx="' + k + '" data-inv="1" value="' + (1 / S.doc.fx[k]).toFixed(k === 'JPY' ? 1 : 2) + '"> ' + k + '</label>'
                    : '<label>1 ' + k + ' = <input class="ns-input ns-num" type="number" step="any" min="0" data-fx="' + k + '" value="' + S.doc.fx[k] + '"> USD</label>'
            ).join('') + '<span class="ns-dim">≈ = price is a lower bound, a range, or unconfirmed</span>';
        }
    }

    function bindFx() {
        let t = null;
        $('nsFx').addEventListener('input', (e) => {
            const el = e.target; if (!el.dataset.fx) return;
            const v = parseFloat(el.value); if (!(v > 0)) return;
            const fx = Object.assign({}, S.doc.fx); fx[el.dataset.fx] = el.dataset.inv ? 1 / v : v;
            S.doc.fx = fx; S.drafts.fx = fx; renderCompare(); renderCfgList();
            clearTimeout(t); t = setTimeout(() => { delete S.drafts.fx; send([{ op: 'set_fx', fx: S.doc.fx }]); }, 600);
        });
        $('nsCompare').addEventListener('click', (e) => {
            const tr = e.target.closest('tr[data-id]'); if (!tr) return;
            editingCfg = tr.dataset.id; renderCfgList(); renderCfgEditor();
            $('nsCfgEditor').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    }

    // ═══ sky (Aladin) ══════════════════════════════════════════════════════════════════════════════════════════
    const Sky = (function () {
        let aladin = null, overlay = null, raf = 0, survey = lsGet('ns-survey', 'CDS/P/DSS2/color');
        const D = Math.PI / 180;

        // gnomonic projection: offsets (x east, y north, degrees) around (ra0, dec0) → [ra, dec]
        function deproject(ra0, dec0, x, y) {
            x *= D; y *= D;
            const rho = Math.hypot(x, y);
            if (rho === 0) return [ra0, dec0];
            const c = Math.atan(rho), d0 = dec0 * D;
            const dec = Math.asin(Math.cos(c) * Math.sin(d0) + y * Math.sin(c) * Math.cos(d0) / rho);
            const ra = ra0 * D + Math.atan2(x * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - y * Math.sin(d0) * Math.sin(c));
            return [((ra / D) % 360 + 360) % 360, dec / D];
        }
        function rect(ra0, dec0, w, h, rotDeg) {
            const th = (rotDeg || 0) * D, pts = [], n = 12;
            const corners = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];
            for (let k = 0; k < 4; k++) {
                const a = corners[k], b = corners[(k + 1) % 4];
                for (let i = 0; i < n; i++) {
                    const u = a[0] + (b[0] - a[0]) * i / n, v = a[1] + (b[1] - a[1]) * i / n;
                    // rotation = position angle of the sensor's "up", east of north; x grows to the east (left on the sky)
                    const x = -(u * Math.cos(th) - v * Math.sin(th)), y = u * Math.sin(th) + v * Math.cos(th);
                    pts.push(deproject(ra0, dec0, x, y));
                }
            }
            return pts;
        }

        function init() {
            const target = lsGet('ns-target', '06 41 00 +09 53 00');   // NGC 2264 / Cone: a field that fills a few degrees
            const sel = $('nsSurvey'); sel.value = survey;
            if (window.KinderHips) KinderHips.markSelect(sel);
            Promise.all([A.init, window.KinderHips ? KinderHips.resolve(survey) : survey]).then(([, s]) => {
                if (window.KinderHips) KinderHips.showStatus($('nsMapWrap'));
                aladin = A.aladin('#ns-aladin', {
                    survey: s, fov: 4, target: target, cooFrame: 'ICRS', showReticle: true, reticleColor: '#BBBBBB', reticleSize: 14,
                    showZoomControl: true, showFullscreenControl: true, showLayersControl: false, showGotoControl: false,
                    showShareControl: false, showCatalog: false, showFrame: false, showCooGrid: false, showProjectionControl: false,
                    showSimbadPointerControl: false, showCooGridControl: false, showSettings: false, showLogo: true,
                    showContextMenu: false, allowFullZoomout: true, realFullscreen: true, showStatusBar: false
                });
                overlay = A.graphicOverlay({ lineWidth: 2 });
                aladin.addOverlay(overlay);
                aladin.on('positionChanged', schedule);
                $('nsMapLoading').hidden = true;
                setTimeout(() => { draw(); fit(); }, 300);
            }).catch((e) => { console.error(e); $('nsMapLoading').textContent = 'The sky view did not load.'; });

            sel.addEventListener('change', () => {
                survey = sel.value; lsSet('ns-survey', survey);
                if (aladin) (window.KinderHips ? KinderHips.resolve(survey) : Promise.resolve(survey)).then((s) => aladin.setImageSurvey(s));
            });
            const go = () => {
                const q = $('nsTarget').value.trim(); if (!q || !aladin) return;
                const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*([+-]?\d+(?:\.\d+)?)\s*$/);
                if (m) { aladin.gotoRaDec(parseFloat(m[1]), parseFloat(m[2])); lsSet('ns-target', m[1] + ' ' + m[2]); schedule(); return; }
                aladin.gotoObject(q, { success: () => { lsSet('ns-target', q); schedule(); }, error: () => toast('Could not find "' + q + '".') });
            };
            $('nsGo').onclick = go;
            $('nsTarget').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
            $('nsCircle').checked = lsGet('ns-circle', true);
            $('nsLabels').checked = lsGet('ns-labels', true);
            $('nsCircle').onchange = () => { lsSet('ns-circle', $('nsCircle').checked); draw(); };
            $('nsLabels').onchange = () => { lsSet('ns-labels', $('nsLabels').checked); draw(); };
            $('nsFit').onclick = fit;
        }

        function schedule() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); }

        function draw() {
            const legend = $('nsLegend');
            const items = configs().filter((c) => visible.has(c.id)).map(compute);
            legend.hidden = !$('nsLabels').checked || !items.length;
            legend.innerHTML = items.map((x) => '<div><span class="ns-swatch" style="--c:' + esc(x.cfg.color) + '"></span><b>' + esc(x.cfg.name) + '</b> ' +
                (x.ok ? fmtPair(x.w, x.h) + ' · ' + x.scale.toFixed(2) + '″/px' : '<i>no FOV</i>') + '</div>').join('');
            if (!aladin || !overlay) return;
            let ra, dec;
            try { [ra, dec] = aladin.getRaDec(); } catch (e) { return; }
            overlay.removeAll();
            const circles = new Set();
            items.forEach((x) => {
                if (!x.ok) return;
                overlay.add(A.polygon(rect(ra, dec, x.w, x.h, x.cfg.rotation), { color: x.cfg.color, lineWidth: 2 }));
                if ($('nsCircle').checked && x.circleDeg && !circles.has(x.circleDeg.toFixed(4))) {
                    circles.add(x.circleDeg.toFixed(4));
                    overlay.add(A.circle(ra, dec, x.circleDeg / 2, { color: '#BBBBBB', lineWidth: 1 }));
                }
            });
        }

        function fit() {
            if (!aladin) return;
            const items = configs().filter((c) => visible.has(c.id)).map(compute).filter((x) => x.ok);
            if (!items.length) return;
            const big = Math.max(...items.map((x) => Math.max(Math.hypot(x.w, x.h), $('nsCircle').checked && x.circleDeg ? x.circleDeg : 0)));
            try { aladin.setFov(Math.min(Math.max(big * 1.35, 0.05), 180)); } catch (e) { /* locked view */ }
            schedule();
        }
        return { init, draw, fit };
    })();

    // ═══ sheet ═════════════════════════════════════════════════════════════════════════════════════════════════
    const Sheet = (function () {
        let tableId = lsGet('ns-tab', null);
        let sel = null;          // {r0, c0, r1, c1} row / column indexes in the shown rows and columns
        let editing = false, editOrig = '';
        let undo = [], redo = [];
        let filter = '';
        let dragSel = false;
        const grid = () => $('nsGrid');
        const wrap = () => $('nsGridWrap');
        let ed = null;           // the one textarea: keyboard sink while a cell is selected, editor while editing

        function table() {
            let t = S.doc.tables.find((x) => x.id === tableId);
            if (!t) { t = S.doc.tables[0]; tableId = t ? t.id : null; }
            return t;
        }
        function shownRows(t) {
            if (!filter) return t.rows;
            const q = filter.toLowerCase();
            return t.rows.filter((r) => Object.values(r.cells).some((v) => String(v).toLowerCase().includes(q)));
        }

        function commit(ops, inverse) {
            if (!ops.length) return;
            undo.push({ ops, inverse }); if (undo.length > 200) undo.shift();
            redo = [];
            send(ops);
        }
        function doUndo() { const h = undo.pop(); if (!h) return; redo.push(h); send(h.inverse.slice()); }
        function doRedo() { const h = redo.pop(); if (!h) return; undo.push(h); send(h.ops.slice()); }

        // ── rendering ──
        function renderTabs() {
            const t = table();
            $('nsTabs').innerHTML = S.doc.tables.map((x) => '<button type="button" role="tab" class="ns-tab' + (t && x.id === t.id ? ' is-on' : '') + '" data-id="' + esc(x.id) + '" aria-selected="' + (t && x.id === t.id) + '">' +
                '<span class="ns-tab-label">' + esc(x.label) + '</span><span class="ns-tab-n">' + x.rows.length + '</span><span class="ns-tab-menu" data-menu="1" title="Sheet options">▾</span></button>').join('') +
                '<button type="button" class="ns-tab ns-tab-add" id="nsAddTab" title="New sheet">+</button>';
        }

        // price columns (價格 / 廠商報價 / price / quote): the cell text plus its value in TWD, read the same way as Compare
        const PRICE_COL = /廠商報價|quote|報價|^(價格|price|cost|定價|list)/i;
        function priceHint(c, text) {
            const p = text && PRICE_COL.test(c.name || '') ? parsePrice(text) : null;
            if (p && p.nocur) return ' title="' + esc(text + ' — no currency: write EUR, USD, TWD or JPY after the amount, e.g. 73000 USD') + '"><span class="ns-pc"><span class="ns-pv">' +
                esc(text) + '</span><span class="ns-twd ns-warn-t">+ EUR / USD / TWD / JPY</span></span>';
            const twd = p && S.doc.fx.TWD && S.doc.fx[p.currency] ? (p.currency === 'TWD' ? p.amount : usdToTWD(toUSD(p))) : 0;
            if (!twd) return '>' + esc(text || '');
            const tip = text + ' ≈ ' + fmtMoney(twd, 'TWD');
            const short = twd >= 1e6 ? (twd / 1e6).toFixed(twd >= 1e8 ? 0 : 2) + 'M' : (twd >= 1e3 ? Math.round(twd / 1e3) + 'k' : Math.round(twd));
            return ' title="' + esc(tip) + '"><span class="ns-pc"><span class="ns-pv">' + esc(text) + '</span><span class="ns-twd">' + (p.approx ? '≈' : '') + 'NT$' + short + '</span></span>';
        }

        // a price column still at the default width is drawn 200 px wide so its TWD value fits; a resized one keeps its width
        const colW = (c) => (PRICE_COL.test(c.name || '') && (!c.width || c.width === 140) ? 200 : (c.width || 140));

        function render() {
            if (editing) return;               // the editor would vanish under the cursor; rendered after commit
            renderTabs();
            const t = table();
            const g = grid();
            if (!t) { g.innerHTML = '<tbody><tr><td class="ns-dim">No sheets. Add one with +.</td></tr></tbody>'; return; }
            const rows = shownRows(t);
            const total = 44 + t.columns.reduce((s, c) => s + colW(c), 0) + 44;
            g.style.width = total + 'px';
            g.innerHTML = '<colgroup><col style="width:44px">' + t.columns.map((c) => '<col style="width:' + colW(c) + 'px">').join('') + '<col style="width:44px"></colgroup>' +
                '<thead><tr><th class="ns-corner"></th>' + t.columns.map((c, ci) => '<th data-c="' + ci + '"' + (PRICE_COL.test(c.name || '') ? ' title="Write the amount, then EUR, USD, TWD or JPY (e.g. 73000 USD)"' : '') + '><span class="ns-hname">' + esc(c.name || ' ') + (PRICE_COL.test(c.name || '') ? '<small class="ns-hcur">EUR · USD · TWD · JPY</small>' : '') + '</span><button type="button" class="ns-hmenu" data-c="' + ci + '" aria-label="Column options">▾</button><span class="ns-resize" data-c="' + ci + '"></span></th>').join('') +
                '<th class="ns-addcol"><button type="button" id="nsAddCol" title="Add a column">+</button></th></tr></thead><tbody>' +
                rows.map((r, ri) => '<tr><th class="ns-rn" data-r="' + ri + '">' + (t.rows.indexOf(r) + 1) + '</th>' +
                    t.columns.map((c, ci) => '<td data-r="' + ri + '" data-c="' + ci + '"' + priceHint(c, r.cells[c.id]) + '</td>').join('') + '<td class="ns-pad"></td></tr>').join('') +
                (rows.length ? '' : '<tr><td></td><td colspan="' + t.columns.length + '" class="ns-dim">' + (filter ? 'No row matches the filter.' : 'Empty sheet — add a row.') + '</td></tr>') +
                '</tbody>';
            if (sel) clampSel(t, rows);
            paintSel(false);
            $('nsUndo').disabled = !undo.length; $('nsRedo').disabled = !redo.length;
        }

        function clampSel(t, rows) {
            const R = rows.length - 1, C = t.columns.length - 1;
            if (R < 0 || C < 0) { sel = null; return; }
            sel.r0 = Math.min(sel.r0, R); sel.r1 = Math.min(sel.r1, R); sel.c0 = Math.min(sel.c0, C); sel.c1 = Math.min(sel.c1, C);
        }
        const rng = () => ({ r0: Math.min(sel.r0, sel.r1), r1: Math.max(sel.r0, sel.r1), c0: Math.min(sel.c0, sel.c1), c1: Math.max(sel.c0, sel.c1) });
        const tdAt = (r, c) => grid().querySelector('td[data-r="' + r + '"][data-c="' + c + '"]');

        function paintSel(focus) {
            grid().querySelectorAll('.is-sel, .is-cur').forEach((el) => el.classList.remove('is-sel', 'is-cur'));
            if (!sel) { if (ed) ed.style.display = 'none'; return; }
            const q = rng();
            for (let r = q.r0; r <= q.r1; r++) for (let c = q.c0; c <= q.c1; c++) { const td = tdAt(r, c); if (td) td.classList.add('is-sel'); }
            const cur = tdAt(sel.r1, sel.c1);
            if (cur) cur.classList.add('is-cur');
            placeEditor(focus);
        }

        function placeEditor(focus) {
            if (!ed) return;
            const cur = tdAt(sel.r1, sel.c1);
            if (!cur) { ed.style.display = 'none'; return; }
            ed.style.display = 'block';
            ed.style.left = cur.offsetLeft + 'px'; ed.style.top = cur.offsetTop + 'px';
            ed.style.width = Math.max(cur.offsetWidth, 180) + 'px'; ed.style.minHeight = cur.offsetHeight + 'px';
            if (!editing) {
                ed.value = selectionText();
                ed.classList.remove('is-editing');
                if (focus) { ed.focus({ preventScroll: true }); ed.select(); }
            }
            if (focus) cur.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }

        function selectionText() {
            const t = table(), rows = shownRows(t), q = rng(), out = [];
            for (let r = q.r0; r <= q.r1; r++) {
                const line = [];
                for (let c = q.c0; c <= q.c1; c++) line.push(tsvCell((rows[r] && rows[r].cells[t.columns[c].id]) || ''));
                out.push(line.join('\t'));
            }
            return out.join('\n');
        }
        const tsvCell = (v) => (/[\t\n"]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v);

        function parseTSV(text) {
            const rows = []; let row = [], cur = '', q = false;
            text = text.replace(/\r\n?/g, '\n');
            for (let i = 0; i < text.length; i++) {
                const ch = text[i];
                if (q) { if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch; }
                else if (ch === '"' && cur === '') q = true;
                else if (ch === '\t') { row.push(cur); cur = ''; }
                else if (ch === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
                else cur += ch;
            }
            if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
            return rows;
        }

        // ── editing ──
        function select(r, c, extend, focus) {
            const t = table(); if (!t) return;
            const R = shownRows(t).length - 1, C = t.columns.length - 1;
            if (R < 0 || C < 0) return;
            r = Math.max(0, Math.min(R, r)); c = Math.max(0, Math.min(C, c));
            if (extend && sel) { sel.r1 = r; sel.c1 = c; } else sel = { r0: r, c0: c, r1: r, c1: c };
            paintSel(focus !== false);
        }

        function beginEdit(keepText) {
            if (!sel || editing) return;
            const t = table(), row = shownRows(t)[sel.r1], col = t.columns[sel.c1];
            if (!row || !col) return;
            editing = true;              // before paintSel, which would otherwise reset the textarea
            sel.r0 = sel.r1; sel.c0 = sel.c1; paintSel(false);
            editOrig = row.cells[col.id] || '';
            if (!keepText) ed.value = editOrig;
            ed.classList.add('is-editing');
            ed.focus({ preventScroll: true });
            if (!keepText) ed.setSelectionRange(ed.value.length, ed.value.length);
            autosize();
        }
        function autosize() { ed.style.height = 'auto'; ed.style.height = Math.max(ed.scrollHeight, tdAt(sel.r1, sel.c1) ? tdAt(sel.r1, sel.c1).offsetHeight : 30) + 'px'; }

        function endEdit(save) {
            if (!editing) return;
            editing = false;
            ed.classList.remove('is-editing');
            const t = table(), row = shownRows(t)[sel.r1], col = t.columns[sel.c1];
            const v = ed.value;
            if (save && row && col && v !== editOrig) {
                commit([{ op: 'set_cell', table: t.id, row: row.id, col: col.id, value: v }],
                       [{ op: 'set_cell', table: t.id, row: row.id, col: col.id, value: editOrig }]);
            } else render();
        }

        function setRange(values) {     // values: [[text]] starting at the selection's top-left; grows rows / columns
            const t = table(), rows = shownRows(t).slice(), q = rng();
            const ops = [], inv = [];
            const needCols = q.c0 + Math.max(...values.map((v) => v.length)) - t.columns.length;
            const cols = t.columns.slice();
            for (let i = 0; i < needCols; i++) {
                const col = { id: uid('c'), name: '', width: 140 };
                ops.push({ op: 'add_col', table: t.id, col, after: cols[cols.length - 1] ? cols[cols.length - 1].id : null });
                inv.unshift({ op: 'delete_col', table: t.id, col: col.id });
                cols.push(col);
            }
            values.forEach((line, i) => {
                let row = rows[q.r0 + i];
                if (!row) {
                    const last = t.rows[t.rows.length - 1];
                    row = { id: uid('r'), cells: {} };
                    ops.push({ op: 'add_row', table: t.id, row, after: rows.length ? rows[rows.length - 1].id : (last ? last.id : null) });
                    inv.unshift({ op: 'delete_row', table: t.id, row: row.id });
                    rows.push(row);
                }
                line.forEach((v, j) => {
                    const col = cols[q.c0 + j]; if (!col) return;
                    const old = row.cells[col.id] || '';
                    if (old === v) return;
                    ops.push({ op: 'set_cell', table: t.id, row: row.id, col: col.id, value: v });
                    if (t.rows.includes(row)) inv.unshift({ op: 'set_cell', table: t.id, row: row.id, col: col.id, value: old });
                });
            });
            commit(ops, inv);
            if (values.length > 1 || values[0].length > 1) { sel = { r0: q.r0, c0: q.c0, r1: q.r0 + values.length - 1, c1: q.c0 + Math.max(...values.map((v) => v.length)) - 1 }; paintSel(true); }
        }

        function clearRange() {
            const q = rng(), t = table(), rows = shownRows(t);
            const vals = [];
            for (let r = q.r0; r <= q.r1; r++) { const line = []; for (let c = q.c0; c <= q.c1; c++) line.push(''); vals.push(line); }
            if (rows.length) setRange(vals);
        }

        // ── rows / columns ──
        function addRow(afterIdx, before) {
            const t = table(), rows = shownRows(t);
            let after = null;
            if (afterIdx == null) after = t.rows.length ? t.rows[t.rows.length - 1].id : null;
            else {
                const ref = rows[afterIdx];
                if (before) { const i = t.rows.indexOf(ref); after = i > 0 ? t.rows[i - 1].id : null; } else after = ref ? ref.id : null;
            }
            const row = { id: uid('r'), cells: {} };
            commit([{ op: 'add_row', table: t.id, row, after }], [{ op: 'delete_row', table: t.id, row: row.id }]);
            const ri = shownRows(table()).findIndex((r) => r.id === row.id);
            if (ri >= 0) select(ri, 0);
        }
        function deleteRows(idxs) {
            const t = table(), rows = shownRows(t);
            const targets = idxs.map((i) => rows[i]).filter(Boolean);
            const ops = [], inv = [];
            targets.forEach((r) => {
                const i = t.rows.indexOf(r);
                ops.push({ op: 'delete_row', table: t.id, row: r.id });
                inv.unshift({ op: 'add_row', table: t.id, row: JSON.parse(JSON.stringify(r)), after: i > 0 ? t.rows[i - 1].id : null });
            });
            commit(ops, inv);
        }
        function duplicateRow(idx) {
            const t = table(), r = shownRows(t)[idx]; if (!r) return;
            const copy = { id: uid('r'), cells: Object.assign({}, r.cells) };
            commit([{ op: 'add_row', table: t.id, row: copy, after: r.id }], [{ op: 'delete_row', table: t.id, row: copy.id }]);
        }
        function moveRow(idx, delta) {
            const t = table(), r = shownRows(t)[idx]; if (!r) return;
            const i = t.rows.indexOf(r), j = i + delta;
            if (j < 0 || j >= t.rows.length) return;
            const oldAfter = i > 0 ? t.rows[i - 1].id : null;
            const order = t.rows.map((x) => x.id); order.splice(i, 1); order.splice(j, 0, r.id);
            const newAfter = j > 0 ? order[j - 1] : null;
            commit([{ op: 'move_row', table: t.id, row: r.id, after: newAfter }], [{ op: 'move_row', table: t.id, row: r.id, after: oldAfter }]);
            select(idx + delta, sel ? sel.c1 : 0);
        }
        function addCol(ci, before) {
            const t = table();
            const after = ci == null ? (t.columns.length ? t.columns[t.columns.length - 1].id : null) : (before ? (ci > 0 ? t.columns[ci - 1].id : null) : t.columns[ci].id);
            const col = { id: uid('c'), name: 'New column', width: 140 };
            commit([{ op: 'add_col', table: t.id, col, after }], [{ op: 'delete_col', table: t.id, col: col.id }]);
            const idx = table().columns.findIndex((c) => c.id === col.id);
            setTimeout(() => renameCol(idx), 0);
        }
        function deleteCol(ci) {
            const t = table(), col = t.columns[ci]; if (!col) return;
            const filled = t.rows.filter((r) => r.cells[col.id]).length;
            if (filled && !confirm('Delete the column "' + col.name + '" and its ' + filled + ' filled cell(s)? (Undo brings it back.)')) return;
            const inv = [{ op: 'add_col', table: t.id, col: { id: col.id, name: col.name, width: col.width }, after: ci > 0 ? t.columns[ci - 1].id : null }];
            t.rows.forEach((r) => { if (r.cells[col.id]) inv.push({ op: 'set_cell', table: t.id, row: r.id, col: col.id, value: r.cells[col.id] }); });
            commit([{ op: 'delete_col', table: t.id, col: col.id }], inv);
        }
        function moveCol(ci, delta) {
            const t = table(), col = t.columns[ci], j = ci + delta;
            if (!col || j < 0 || j >= t.columns.length) return;
            const order = t.columns.map((c) => c.id); order.splice(ci, 1); order.splice(j, 0, col.id);
            commit([{ op: 'move_col', table: t.id, col: col.id, after: j > 0 ? order[j - 1] : null }],
                   [{ op: 'move_col', table: t.id, col: col.id, after: ci > 0 ? t.columns[ci - 1].id : null }]);
        }
        function sortBy(ci, dir) {
            const t = table(), col = t.columns[ci]; if (!col) return;
            const old = t.rows.map((r) => r.id);
            const key = (r) => r.cells[col.id] || '';
            const numeric = t.rows.filter((r) => key(r)).every((r) => firstNum(key(r)) != null && /^[\s~>＞<≈$€¥]*[\d,.]/.test(key(r)));
            const sorted = t.rows.slice().sort((a, b) => {
                const A1 = key(a), B1 = key(b);
                if (!A1 && !B1) return 0; if (!A1) return 1; if (!B1) return -1;     // blanks last
                const d = numeric ? firstNum(A1) - firstNum(B1) : A1.localeCompare(B1, undefined, { numeric: true, sensitivity: 'base' });
                return dir * d;
            });
            commit([{ op: 'order_rows', table: t.id, order: sorted.map((r) => r.id) }], [{ op: 'order_rows', table: t.id, order: old }]);
        }
        function inlineRename(el, value, done) {
            el.contentEditable = 'true'; el.textContent = value; el.classList.add('is-renaming'); el.focus();
            const range = document.createRange(); range.selectNodeContents(el); const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            let finished = false;
            const finish = (save) => {
                if (finished) return; finished = true;
                el.contentEditable = 'false'; el.classList.remove('is-renaming');
                const v = el.textContent.trim();
                if (save && v !== value) done(v); else render();
            };
            el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } else if (e.key === 'Escape') { e.preventDefault(); finish(false); } e.stopPropagation(); });
            el.addEventListener('blur', () => finish(true), { once: true });
        }
        function renameCol(ci) {
            const t = table(), col = t.columns[ci]; if (!col) return;
            const el = grid().querySelector('th[data-c="' + ci + '"] .ns-hname'); if (!el) return;
            inlineRename(el, col.name, (v) => commit([{ op: 'rename_col', table: t.id, col: col.id, name: v }], [{ op: 'rename_col', table: t.id, col: col.id, name: col.name }]));
        }
        function renameTable(id) {
            const t = S.doc.tables.find((x) => x.id === id), el = document.querySelector('.ns-tab[data-id="' + id + '"] .ns-tab-label');
            if (!t || !el) return;
            inlineRename(el, t.label, (v) => v && commit([{ op: 'rename_table', table: t.id, label: v }], [{ op: 'rename_table', table: t.id, label: t.label }]));
        }

        // ── menus ──
        function openMenu(anchor, items) {
            const m = $('nsMenu');
            m.innerHTML = items.map((it, i) => it === '-' ? '<hr>' : (it.head ? '<div class="ns-menu-head">' + esc(it.head) + '</div>' :
                '<button type="button" data-i="' + i + '"' + (it.danger ? ' class="is-danger"' : '') + (it.on ? ' aria-checked="true"' : '') + '>' + (it.on ? '✓ ' : '') + esc(it.label) + '</button>')).join('');
            m.hidden = false;
            const r = anchor.getBoundingClientRect();
            m.style.left = Math.min(r.left, window.innerWidth - m.offsetWidth - 12) + 'px';
            m.style.top = (r.bottom + 4 + m.offsetHeight > window.innerHeight ? Math.max(8, r.top - m.offsetHeight - 4) : r.bottom + 4) + 'px';
            m.onclick = (e) => { const b = e.target.closest('button[data-i]'); if (!b) return; m.hidden = true; items[+b.dataset.i].action(); };
        }
        document.addEventListener('mousedown', (e) => { const m = $('nsMenu'); if (m && !m.hidden && !m.contains(e.target) && !e.target.closest('[data-menu],.ns-hmenu,.ns-rn')) m.hidden = true; });
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('nsMenu')) $('nsMenu').hidden = true; });

        function colMenu(btn, ci) {
            const t = table(), col = t.columns[ci];
            openMenu(btn, [
                { head: col.name || 'Column' },
                { label: 'Sort A → Z', action: () => sortBy(ci, 1) }, { label: 'Sort Z → A', action: () => sortBy(ci, -1) }, '-',
                { label: 'Insert column left', action: () => addCol(ci, true) }, { label: 'Insert column right', action: () => addCol(ci, false) },
                { label: 'Move left', action: () => moveCol(ci, -1) }, { label: 'Move right', action: () => moveCol(ci, 1) },
                { label: 'Rename', action: () => renameCol(ci) }, '-',
                { label: 'Delete column', danger: true, action: () => deleteCol(ci) }
            ]);
        }
        function rowMenu(th, ri) {
            const q = sel ? rng() : { r0: ri, r1: ri };
            const many = sel && ri >= q.r0 && ri <= q.r1 && q.r1 > q.r0;
            openMenu(th, [
                { label: 'Insert row above', action: () => addRow(ri, true) }, { label: 'Insert row below', action: () => addRow(ri, false) },
                { label: 'Duplicate row', action: () => duplicateRow(ri) },
                { label: 'Move up', action: () => moveRow(ri, -1) }, { label: 'Move down', action: () => moveRow(ri, 1) }, '-',
                { label: many ? 'Delete ' + (q.r1 - q.r0 + 1) + ' rows' : 'Delete row', danger: true,
                  action: () => deleteRows(many ? Array.from({ length: q.r1 - q.r0 + 1 }, (_, k) => q.r0 + k) : [ri]) }
            ]);
        }
        function tabMenu(btn, id) {
            const t = S.doc.tables.find((x) => x.id === id), i = S.doc.tables.indexOf(t);
            const kinds = [['camera', 'Cameras'], ['telescope', 'Telescopes'], ['mount', 'Mounts'], ['other', 'Other']];
            openMenu(btn, [
                { label: 'Rename', action: () => renameTable(id) },
                { label: 'Move left', action: () => i > 0 && send([{ op: 'move_table', table: id, after: i > 1 ? S.doc.tables[i - 2].id : null }]) },
                { label: 'Move right', action: () => i < S.doc.tables.length - 1 && send([{ op: 'move_table', table: id, after: S.doc.tables[i + 1].id }]) },
                '-', { head: 'Rows are used as' },
                ...kinds.map(([k, l]) => ({ label: l, on: t.kind === k, action: () => send([{ op: 'rename_table', table: id, kind: k }]) })),
                '-', { label: 'Delete sheet', danger: true, action: () => {
                    if (!confirm('Delete the sheet "' + t.label + '" with its ' + t.rows.length + ' row(s)? This cannot be undone.')) return;
                    send([{ op: 'delete_table', table: id }]);
                } }
            ]);
        }

        function csv() {
            const t = table(); if (!t) return;
            const q = (v) => (/[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v);
            const lines = [t.columns.map((c) => q(c.name || '')).join(',')].concat(t.rows.map((r) => t.columns.map((c) => q(r.cells[c.id] || '')).join(',')));
            const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'new_slt_' + t.label.replace(/\W+/g, '_') + '.csv';
            document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        }

        // ── events ──
        function bind() {
            ed = document.createElement('textarea');
            ed.className = 'ns-editor'; ed.spellcheck = false; ed.setAttribute('aria-label', 'Cell');
            ed.style.display = 'none';
            wrap().appendChild(ed);

            $('nsTabs').addEventListener('click', (e) => {
                if (e.target.closest('#nsAddTab')) {
                    const id = uid('t');
                    const cols = ['Name', '品牌', '價格', '廠商報價', 'Note'].map((n) => ({ id: uid('c'), name: n, width: n === 'Note' ? 300 : 150 }));
                    send([{ op: 'add_table', table: { id, label: 'Sheet ' + (S.doc.tables.length + 1), kind: 'other', columns: cols, rows: [] } }]);
                    tableId = id; lsSet('ns-tab', id); sel = null; render(); setTimeout(() => renameTable(id), 0);
                    return;
                }
                const b = e.target.closest('.ns-tab[data-id]'); if (!b) return;
                if (e.target.closest('[data-menu]')) { tabMenu(e.target.closest('[data-menu]'), b.dataset.id); return; }
                if (b.dataset.id !== tableId) { endEdit(true); tableId = b.dataset.id; lsSet('ns-tab', tableId); sel = null; undo = []; redo = []; render(); }
            });
            $('nsTabs').addEventListener('dblclick', (e) => { const b = e.target.closest('.ns-tab[data-id]'); if (b) renameTable(b.dataset.id); });

            const g = grid();
            g.addEventListener('mousedown', (e) => {
                const td = e.target.closest('td[data-c]');
                if (td) {
                    if (editing) endEdit(true);
                    e.preventDefault();
                    select(+td.dataset.r, +td.dataset.c, e.shiftKey);
                    dragSel = true;
                    return;
                }
                const rn = e.target.closest('.ns-rn');
                if (rn) {
                    e.preventDefault(); if (editing) endEdit(true);
                    const ri = +rn.dataset.r, C = table().columns.length - 1;
                    if (e.shiftKey && sel) { sel.r1 = ri; sel.c0 = 0; sel.c1 = C; paintSel(true); }
                    else { sel = { r0: ri, c0: 0, r1: ri, c1: C }; paintSel(true); }
                    rowMenu(rn, ri);
                    return;
                }
                const rs = e.target.closest('.ns-resize');
                if (rs) {
                    e.preventDefault();
                    const ci = +rs.dataset.c, t = table(), col = t.columns[ci], x0 = e.clientX, w0 = colW(col);
                    const colEl = g.querySelectorAll('col')[ci + 1], g0 = parseFloat(g.style.width);
                    const move = (ev) => { const w = Math.max(48, Math.min(900, w0 + ev.clientX - x0)); colEl.style.width = w + 'px'; g.style.width = (g0 + w - w0) + 'px'; };
                    const up = (ev) => {
                        document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
                        const w = Math.max(48, Math.min(900, w0 + ev.clientX - x0));
                        if (w !== w0) commit([{ op: 'resize_col', table: t.id, col: col.id, width: w }], [{ op: 'resize_col', table: t.id, col: col.id, width: w0 }]);
                    };
                    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
                }
            });
            g.addEventListener('mouseover', (e) => {
                if (!dragSel || editing) return;
                const td = e.target.closest('td[data-c]'); if (!td || !sel) return;
                if (sel.r1 !== +td.dataset.r || sel.c1 !== +td.dataset.c) { sel.r1 = +td.dataset.r; sel.c1 = +td.dataset.c; paintSel(true); }
            });
            document.addEventListener('mouseup', () => { dragSel = false; });
            g.addEventListener('dblclick', (e) => {
                const td = e.target.closest('td[data-c]'); if (td) { select(+td.dataset.r, +td.dataset.c); beginEdit(false); return; }
                const h = e.target.closest('th[data-c]'); if (h && !e.target.closest('.ns-hmenu,.ns-resize')) renameCol(+h.dataset.c);
            });
            g.addEventListener('click', (e) => {
                const hm = e.target.closest('.ns-hmenu'); if (hm) { colMenu(hm, +hm.dataset.c); return; }
                if (e.target.closest('#nsAddCol')) addCol(null);
            });

            ed.addEventListener('compositionstart', () => { if (!editing) { ed.value = ''; beginEdit(true); } });
            ed.addEventListener('input', () => { if (!editing) beginEdit(true); autosize(); });
            ed.addEventListener('blur', () => { if (editing) endEdit(true); });
            ed.addEventListener('keydown', (e) => {
                if (e.isComposing || e.keyCode === 229) return;
                const mod = e.metaKey || e.ctrlKey;
                if (editing) {
                    if (e.key === 'Escape') { e.preventDefault(); ed.value = editOrig; endEdit(false); paintSel(true); }
                    else if (e.key === 'Enter' && !e.shiftKey && !e.altKey) { e.preventDefault(); endEdit(true); select(sel.r1 + 1, sel.c1); }
                    else if (e.key === 'Tab') { e.preventDefault(); endEdit(true); select(sel.r1, sel.c1 + (e.shiftKey ? -1 : 1)); }
                    return;
                }
                if (!sel) return;
                const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
                if (moves[e.key]) {
                    e.preventDefault();
                    const [dr, dc] = moves[e.key];
                    if (mod) { const t = table(); select(dr ? (dr > 0 ? shownRows(t).length - 1 : 0) : sel.r1, dc ? (dc > 0 ? t.columns.length - 1 : 0) : sel.c1, e.shiftKey); }
                    else select(sel.r1 + dr, sel.c1 + dc, e.shiftKey);
                } else if (e.key === 'Tab') { e.preventDefault(); select(sel.r1, sel.c1 + (e.shiftKey ? -1 : 1)); }
                else if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); beginEdit(false); }
                else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); clearRange(); }
                else if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); }
                else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); doRedo(); }
                else if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); const t = table(); sel = { r0: 0, c0: 0, r1: shownRows(t).length - 1, c1: t.columns.length - 1 }; paintSel(true); }
                else if (e.key === 'Escape') { sel = null; paintSel(false); ed.blur(); }
            });
            ed.addEventListener('copy', (e) => { if (editing) return; e.preventDefault(); e.clipboardData.setData('text/plain', selectionText()); });
            ed.addEventListener('cut', (e) => { if (editing) return; e.preventDefault(); e.clipboardData.setData('text/plain', selectionText()); clearRange(); });
            ed.addEventListener('paste', (e) => {
                if (editing || !sel) return;
                e.preventDefault();
                const text = e.clipboardData.getData('text/plain'); if (!text) return;
                const vals = parseTSV(text.replace(/\n$/, ''));
                const q = rng();
                if (vals.length === 1 && vals[0].length === 1 && (q.r1 > q.r0 || q.c1 > q.c0)) {   // one value into a range: fill it
                    const fill = []; for (let r = q.r0; r <= q.r1; r++) { const l = []; for (let c = q.c0; c <= q.c1; c++) l.push(vals[0][0]); fill.push(l); }
                    setRange(fill);
                } else setRange(vals);
            });

            $('nsAddRow').onclick = () => addRow(null);
            $('nsUndo').onclick = doUndo; $('nsRedo').onclick = doRedo;
            $('nsCsv').onclick = csv;
            $('nsFilter').addEventListener('input', (e) => { filter = e.target.value.trim(); sel = null; render(); });
            window.addEventListener('resize', () => sel && placeEditor(false));
        }

        return { bind, render, isEditing: () => editing };
    })();

    // ═══ start ═════════════════════════════════════════════════════════════════════════════════════════════════
    function renderAll() {
        renderCfgList();
        renderCfgEditor();
        renderCompare();
        Sky.draw();
        Sheet.render();
    }

    fetch(CFG.sheet, { credentials: 'same-origin' }).then((r) => r.json()).then((j) => {
        adopt(j);
        setSync('saved');
        bindSetups(); bindFx(); Sheet.bind();
        onChange(renderAll);
        renderAll();
        Sky.init();
        setInterval(poll, 15000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    }).catch((e) => { console.error(e); setSync('error'); });
})();
