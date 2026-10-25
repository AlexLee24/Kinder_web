/* Pipeline (AutoPhOT): folder scan and New workspace wizard, images and templates, settings (saved as you go),
   run / stop / answer, all settings, export, telescopes. */
(function () {
    'use strict';

    const API = '/api/pipeline/autophot';
    const $ = id => document.getElementById(id);
    const BANDS = ['u', 'g', 'r', 'i', 'z', 'y', 'U', 'B', 'V', 'R', 'I', 'J', 'H', 'K'];

    function el(tag, attrs, ...kids) {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v == null || v === false) continue;
            if (k === 'text') n.textContent = v;
            else if (k === 'class') n.className = v;
            else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
            else n.setAttribute(k, v === true ? '' : v);
        }
        for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid);
        return n;
    }

    async function api(path, body) {
        const opts = { credentials: 'same-origin' };
        if (body !== undefined) {
            opts.method = 'POST';
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify(body);
        }
        let res, data;
        try {
            res = await fetch(path, opts);
            data = await res.json();
        } catch (e) {
            throw new Error(res ? 'Unexpected answer from the server (' + res.status + ').' : 'Network error.');
        }
        if (!res.ok || !data.success) throw new Error(data.error || 'Request failed.');
        return data;
    }

    function stamp(root) {
        (root || document).querySelectorAll('[data-ts]').forEach(n => {
            const v = parseFloat(n.dataset.ts);
            if (v) {
                const d = new Date(v * 1000);
                n.textContent = d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                n.title = d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
            }
        });
    }
    stamp();

    function say(node, text, kind) {
        if (!node) return;
        node.textContent = text || '';
        node.classList.toggle('is-error', kind === 'error');
        node.classList.toggle('is-ok', kind === 'ok');
    }

    // Two-step button: first click arms it for 5 s, the second does the work.
    function armable(btn, armedText, action) {
        const idle = btn.textContent;
        let timer = null;
        btn.addEventListener('click', async () => {
            if (!btn.classList.contains('is-armed')) {
                btn.classList.add('is-armed');
                btn.textContent = armedText;
                timer = setTimeout(() => { btn.classList.remove('is-armed'); btn.textContent = idle; }, 5000);
                return;
            }
            clearTimeout(timer);
            btn.classList.remove('is-armed');
            btn.textContent = idle;
            btn.disabled = true;
            try { await action(); } finally { btn.disabled = false; }
        });
    }

    const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));
    const sizeOf = x => (x.file ? x.file.size : x.size) || 0;
    const sizeText = n => n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' kB';
    const daysLeft = t => {
        const d = (t * 1000 - Date.now()) / 86400e3;
        return d <= 0 ? 'soon' : d < 1 ? 'in ' + Math.max(1, Math.round(d * 24)) + ' h' : 'in ' + Math.round(d) + ' d';
    };
    const bandSelect = (value, attrs) => el('select', Object.assign({ class: 'kw-select kw-select-sm' }, attrs || {}),
        el('option', { value: '', text: 'Filter…', selected: !value }), BANDS.map(b => el('option', { value: b, text: b, selected: b === value })));

    const page = $('plWorkspace');
    const tid = page ? page.dataset.tid : '';
    const base = tid ? API + '/' + encodeURIComponent(tid) : '';
    let overrides = null;            // All settings: {key: one line of YAML}, only values that differ from the default

    // ── FITS headers, read in the browser before anything is uploaded ─────────
    const FITS_RE = /\.(fits|fit|fts)(\.fz|\.gz)?$/i;
    const KEEP = /^(OBJECT|TELESCOP|INSTRUME|FILT|BAND|PASSBAND|DATE-OBS|MJD-OBS|EXPTIME|EXPOSURE|IMAGETYP|OBSTYPE|RA|DEC|OBJCTRA|OBJCTDEC|CRVAL[12]|NAXIS[12]?|ZNAXIS[12]?|ZIMAGE|BITPIX|PCOUNT|GCOUNT)/;

    function parseCard(card) {
        const key = card.slice(0, 8).trim();
        if (card.slice(8, 10) !== '= ') return [key, undefined];
        const raw = card.slice(10);
        if (raw.trimStart().startsWith("'")) {
            const m = raw.match(/'((?:[^']|'')*)'/);
            return [key, m ? m[1].replace(/''/g, "'").trimEnd() : ''];
        }
        const v = raw.split('/')[0].trim();
        if (v === 'T' || v === 'F') return [key, v === 'T'];
        const num = Number(v.replace(/D/i, 'E'));
        return [key, v !== '' && isFinite(num) ? num : v];
    }

    // Primary header, plus the first image extension when the primary has no data (.fz, MEF).
    async function readHeader(file) {
        let stream = file.stream();
        if (/\.gz$/i.test(file.name)) {
            if (typeof DecompressionStream === 'undefined') return null;
            stream = stream.pipeThrough(new DecompressionStream('gzip'));
        }
        const reader = stream.getReader();
        let buf = new Uint8Array(0), ended = false;
        const need = async n => {
            while (buf.length < n && !ended) {
                const r = await reader.read();
                if (r.done) { ended = true; break; }
                const nb = new Uint8Array(buf.length + r.value.length);
                nb.set(buf); nb.set(r.value, buf.length); buf = nb;
            }
            return buf.length >= n;
        };
        const dec = new TextDecoder('latin1');
        const out = {};
        let pos = 0;
        try {
            for (let hdu = 0; hdu < 3; hdu++) {
                const cards = {};
                let end = false;
                while (!end) {
                    if (pos > 4 * 1048576 || !(await need(pos + 2880))) return hdu ? out : null;
                    const block = dec.decode(buf.subarray(pos, pos + 2880));
                    pos += 2880;
                    for (let i = 0; i < 36; i++) {
                        const card = block.slice(i * 80, i * 80 + 80);
                        const [k, v] = parseCard(card);
                        if (k === 'END') { end = true; break; }
                        if (v !== undefined && !(k in cards)) cards[k] = v;
                    }
                }
                if (hdu === 0 && cards.SIMPLE !== true) return null;
                for (const [k, v] of Object.entries(cards)) if (KEEP.test(k) && !(k in out)) out[k] = v;
                const naxis = +cards.NAXIS || 0;
                if (cards.ZIMAGE === true || (naxis >= 2 && +cards.NAXIS1 > 1 && +cards.NAXIS2 > 1)) return out;
                let n = 0;
                if (naxis) { n = 1; for (let i = 1; i <= naxis; i++) n *= +cards['NAXIS' + i] || 0; }
                pos += Math.ceil(((n + (+cards.PCOUNT || 0)) * (+cards.GCOUNT || 1) * Math.abs(+cards.BITPIX || 8) / 8) / 2880) * 2880;
            }
            return out;
        } catch (e) {
            return null;
        } finally {
            reader.cancel().catch(() => {});
        }
    }

    async function pool(items, n, fn) {
        let i = 0;
        await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
            while (i < items.length) { const k = i++; await fn(items[k], k); }
        }));
    }

    // Files from a drop: folders are walked (DataTransferItem entries); each file gets its path in the folder.
    async function droppedFiles(dt) {
        const entries = [...(dt.items || [])].map(it => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
        if (!entries.length) return [...dt.files].map(f => ({ file: f, rel: f.name }));
        const out = [];
        const walk = async (entry, prefix) => {
            if (entry.isFile) {
                const file = await new Promise((ok, bad) => entry.file(ok, bad));
                out.push({ file, rel: prefix + file.name });
            } else if (entry.isDirectory) {
                const reader = entry.createReader();
                let batch;
                do {
                    batch = await new Promise((ok, bad) => reader.readEntries(ok, bad));
                    for (const e of batch) await walk(e, prefix + entry.name + '/');
                } while (batch.length);
            }
        };
        for (const e of entries) await walk(e, '');
        return out;
    }

    // Drop zone with "Choose folder" / "Choose files"; onFiles gets [{file, rel}].
    function dropZone(root, onFiles) {
        const zone = root.querySelector('.pl-drop-zone');
        root.querySelectorAll('.pl-drop-input').forEach(input => input.addEventListener('change', () => {
            const list = [...input.files].map(f => ({ file: f, rel: f.webkitRelativePath || f.name }));
            input.value = '';
            if (list.length) onFiles(list);
        }));
        ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add('is-over'); }));
        ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, () => zone.classList.remove('is-over')));
        zone.addEventListener('drop', async e => {
            e.preventDefault();
            const list = await droppedFiles(e.dataTransfer);
            if (list.length) onFiles(list);
        });
    }

    const CAL_RE = /^(bias|zero|dark|flat|sky ?flat|dome ?flat|twilight)/i;

    // Sort dropped files: science frames, templates (any folder whose name has "templ"), skipped ones; read headers;
    // ask the server which standard filter each is (it knows telescope.yml).
    async function scanFiles(list, onProgress) {
        let folder = '';
        const parts0 = list.map(x => x.rel.split('/'));
        if (parts0.length && parts0.every(p => p.length > 1 && p[0] === parts0[0][0])) folder = parts0[0][0];
        const items = [], other = [];
        for (const x of list) {
            const parts = (folder ? x.rel.split('/').slice(1) : x.rel.split('/'));
            const name = parts[parts.length - 1], dirs = parts.slice(0, -1);
            if (name.startsWith('.') || dirs.some(d => d.startsWith('.'))) continue;
            if (!FITS_RE.test(name)) { other.push(x.rel); continue; }
            const it = { file: x.file, rel: parts.join('/'), name, kind: 'science', why: '', hdr: null, band: '', raw: '' };
            if (dirs.some(d => /_REDUCED$/i.test(d))) { it.kind = 'skip'; it.why = 'AutoPhOT output folder'; }
            else if (dirs.some(d => /templ/i.test(d))) it.kind = 'template';
            items.push(it);
        }
        let done = 0;
        await pool(items.filter(it => it.kind !== 'skip'), 6, async it => {
            it.hdr = await readHeader(it.file);
            if (onProgress) onProgress(++done, items.length);
        });
        for (const it of items) {
            const typ = it.hdr && String(it.hdr.IMAGETYP || it.hdr.OBSTYPE || '');
            if (it.kind === 'science' && typ && CAL_RE.test(typ.trim())) { it.kind = 'skip'; it.why = 'Calibration frame (' + typ.trim() + ')'; }
        }
        const ask = items.filter(it => it.kind !== 'skip');
        if (ask.length) {
            try {
                const r = await api(API + '/classify', { headers: ask.map(it => ({ name: it.rel, header: filterCards(it.hdr) })) });
                r.files.forEach((f, k) => { ask[k].band = f.band; ask[k].raw = f.raw; ask[k].how = f.how; });
            } catch (e) { /* filters stay unknown; AutoPhOT still reads the headers itself */ }
        }
        // Upload names: the file name, or folder__name when two subfolders hold the same name
        const seen = {};
        for (const it of items) {
            if (it.kind === 'skip') continue;
            let up = it.name;
            if (seen[up]) up = it.rel.replace(/\//g, '__');
            seen[up] = true;
            it.up = up;
        }
        return { folder, items, other };
    }

    function filterCards(h) {
        const out = {};
        for (const [k, v] of Object.entries(h || {})) if (/^(TELESCOP|INSTRUME|FILT|BAND|PASSBAND)/.test(k)) out[k] = String(v);
        return out;
    }

    function hdrCoords(h) {
        if (!h) return null;
        const pick = (...keys) => keys.map(k => h[k]).find(v => v !== undefined && v !== '');
        const ra = pick('RA', 'OBJCTRA', 'CRVAL1'), dec = pick('DEC', 'OBJCTDEC', 'CRVAL2');
        return ra !== undefined && dec !== undefined ? { ra: String(ra).trim(), dec: String(dec).trim() } : null;
    }

    const mostCommon = vals => {
        const c = {};
        vals.filter(Boolean).forEach(v => { c[v] = (c[v] || 0) + 1; });
        return Object.keys(c).sort((a, b) => c[b] - c[a])[0] || '';
    };
    const nightOf = h => {
        const d = h && String(h['DATE-OBS'] || '');
        if (!d) return '';
        const t = Date.parse(d.length <= 10 ? d + 'T00:00:00Z' : d.replace(' ', 'T') + (/[zZ+]/.test(d.slice(10)) ? '' : 'Z'));
        return isNaN(t) ? d.slice(0, 10) : new Date(t - 12 * 3600e3).toISOString().slice(0, 10);
    };

    // Summary of a scan: counts, filters, nights, telescopes, warnings, and every file in a table.
    function scanSummary(scan) {
        const sci = scan.items.filter(i => i.kind === 'science'), tpl = scan.items.filter(i => i.kind === 'template');
        const skip = scan.items.filter(i => i.kind === 'skip');
        const byBand = {};
        sci.forEach(i => { byBand[i.band || '?'] = (byBand[i.band || '?'] || 0) + 1; });
        const tels = [...new Set(sci.map(i => i.hdr ? [i.hdr.TELESCOP, i.hdr.INSTRUME].filter(Boolean).join(' / ') : '').filter(Boolean))];
        const nights = new Set(sci.map(i => nightOf(i.hdr)).filter(Boolean));
        const missing = sci.filter(i => i.hdr && !(i.hdr.TELESCOP && i.hdr.INSTRUME && (i.hdr.FILTER || i.hdr.FILTER1 || i.hdr.FILTNAME)));
        const unread = sci.filter(i => !i.hdr);
        const bytes = sci.concat(tpl).reduce((a, i) => a + sizeOf(i), 0);
        const kids = [
            el('div', { class: 'pl-scan-head' },
                el('b', { text: (scan.folder ? scan.folder + '/ · ' : '') + plural(sci.length, 'frame') }),
                el('span', { text: sizeText(bytes) }),
                nights.size ? el('span', { text: plural(nights.size, 'night') }) : null,
                tels.length ? el('span', { text: tels.join(', ') }) : null),
            el('div', { class: 'pl-chips' }, Object.keys(byBand).sort().map(b => el('span', { class: 'kw-chip' + (b === '?' ? ' kw-chip-red' : ' kw-chip-gold'), text: (b === '?' ? 'unknown filter' : b) + ' × ' + byBand[b] })),
                tpl.length ? el('span', { class: 'kw-chip kw-chip-blue', text: plural(tpl.length, 'template') }) : null),
        ];
        if (missing.length) kids.push(el('p', { class: 'pl-warn', text: plural(missing.length, 'frame') + ' without TELESCOP, INSTRUME or FILTER in the header; AutoPhOT skips them.' }));
        if (unread.length) kids.push(el('p', { class: 'pl-hint', text: plural(unread.length, 'header') + ' could not be read here (the server checks them after upload).' }));
        if (skip.length) kids.push(el('p', { class: 'pl-hint', text: 'Left out: ' + skip.map(i => i.rel + ' (' + i.why + ')').slice(0, 4).join(', ') + (skip.length > 4 ? ' and ' + (skip.length - 4) + ' more' : '') + '.' }));
        if (scan.other.length) kids.push(el('p', { class: 'pl-hint', text: plural(scan.other.length, 'file') + ' that are not FITS left out.' }));
        const rows = scan.items.map(i => el('tr', { class: i.kind === 'skip' ? 'is-skip' : null },
            el('td', { class: 'pl-mono', title: i.rel }, i.rel, i.kind === 'template' ? el('span', { class: 'kw-chip kw-chip-blue', text: 'template' }) : null),
            el('td', {}, i.band ? el('b', { text: i.band }) : el('span', { class: 'pl-faint', text: '?' }), i.raw && i.raw !== i.band ? el('small', { text: ' ' + i.raw }) : null),
            el('td', { text: i.hdr ? (i.hdr.TELESCOP || '—') : '—' }), el('td', { text: i.hdr ? (i.hdr.INSTRUME || '—') : '—' }),
            el('td', { text: i.hdr ? String(i.hdr['DATE-OBS'] || '—').replace('T', ' ').slice(0, 19) : '—' }),
            el('td', { text: i.hdr && i.hdr.EXPTIME != null ? String(i.hdr.EXPTIME) : '—' }),
            el('td', { text: i.hdr ? (i.hdr.OBJECT || '—') : '—' }),
            el('td', { class: 'pl-faint', text: i.kind === 'skip' ? i.why : '' })));
        kids.push(el('details', { class: 'pl-scan-files' }, el('summary', { text: 'Show every file' }),
            el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table pl-hdr' },
                el('thead', {}, el('tr', {}, ['File', 'Filter', 'TELESCOP', 'INSTRUME', 'DATE-OBS', 'EXPTIME', 'OBJECT', ''].map(h => el('th', { text: h })))),
                el('tbody', {}, rows)))));
        return kids;
    }

    // ── Uploads: each FITS goes up in pieces under the server's request limit ──
    const CHUNK = parseInt((document.querySelector('[data-chunk]') || {}).dataset?.chunk, 10) || 8 * 1024 * 1024;

    async function uploadFile(wsBase, file, name, onProgress, template) {
        let offset = 0;
        do {
            const piece = file.slice(offset, offset + CHUNK);
            const q = new URLSearchParams({ name: name || file.name, offset: String(offset), total: String(file.size) });
            if (template) q.set('template', template);
            let res, data;
            try {
                res = await fetch(wsBase + '/upload?' + q, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/octet-stream' }, body: piece,
                });
                data = await res.json();
            } catch (e) {
                throw new Error(res ? 'Upload refused by the server (' + res.status + ').' : 'Network error during upload.');
            }
            if (!res.ok || !data.success) throw new Error(data.error || 'Upload failed.');
            offset += piece.size;
            if (onProgress) onProgress(offset);
            if (data.done) return data;
        } while (offset < file.size);
        throw new Error('Upload did not finish.');
    }

    // Upload a list [{file, up, template}] one after the other with one progress bar; returns {ok, failed: [{item, error}]}.
    async function uploadAll(wsBase, list, bar) {
        const total = list.reduce((a, x) => a + sizeOf(x), 0) || 1;
        let sent = 0, ok = 0;
        const failed = [];
        bar.hidden = false;
        const show = (k, extra) => {
            bar.querySelector('.pl-bar > span').style.width = Math.min(100, Math.round(sent / total * 100)) + '%';
            bar.querySelector('small').textContent = 'Uploading ' + Math.min(k + 1, list.length) + ' of ' + list.length + ' · ' + sizeText(sent) + ' of ' + sizeText(total) + (extra ? ' · ' + extra : '');
        };
        for (let k = 0; k < list.length; k++) {
            const x = list[k], start = sent;
            show(k, x.up);
            try {
                if (x.server) {                     // a calibrated frame already on the server: copied there
                    x.result = await api(wsBase + '/add_calibrated', { path: x.server });
                    sent = start + sizeOf(x);
                    if (x.result.skipped && x.result.skipped.length) throw new Error(x.result.skipped[0] + ' is already in this workspace.');
                } else {
                    x.result = await uploadFile(wsBase, x.file, x.up, n => { sent = start + n; show(k, x.up); }, x.template);
                }
                ok++;
            } catch (err) { failed.push({ item: x, error: err.message }); sent = start + sizeOf(x); }
        }
        bar.querySelector('small').textContent = failed.length ? ok + ' uploaded, ' + failed.length + ' failed' : plural(ok, 'file') + ' uploaded';
        return { ok, failed };
    }

    // ── Workspace form (both the wizard and the workspace page) ───────────────
    function formBody(form) {
        const f = form.elements;
        const mode = (form.querySelector('input[name=ts_mode]:checked') || {}).value || 'none';
        const b = {
            name: f.name.value.trim(), ra: f.ra.value.trim(), dec: f.dec.value.trim(),
            catalog: f.catalog.value, ncpu: parseInt(f.ncpu.value, 10) || 1,
            stack: f.stack.checked, stack_with_singles: f.stack_with_singles.checked,
            stack_align: f.stack_align.value, stack_combine: f.stack_combine.value, stack_sigma: parseFloat(f.stack_sigma.value) || 3,
            subtraction: mode !== 'none', sub_method: f.sub_method.value, ts_download: mode === 'survey' ? f.ts_download.value : '',
            ts_size: parseFloat(f.ts_size.value) || 10, ts_align: f.ts_align.value, ts_forceconv: f.ts_forceconv.value,
        };
        if (overrides) b.overrides = overrides;
        return b;
    }

    function tsMode(form) { return (form.querySelector('input[name=ts_mode]:checked') || {}).value || 'none'; }

    function wireForm(form) {
        const msg = form.querySelector('.pl-msg');
        const sync = () => {
            const mode = tsMode(form);
            form.querySelectorAll('[data-show-ts]').forEach(n => { n.hidden = !n.dataset.showTs.split(' ').includes(mode); });
            form.querySelectorAll('.pl-seg-item').forEach(n => n.classList.toggle('is-on', n.querySelector('input').checked));
            const st = form.elements.stack;
            form.querySelectorAll('[data-show-if="stack"]').forEach(n => { n.hidden = !st.checked; });
        };
        form.addEventListener('change', sync);
        sync();

        // Name → Kinder objects (autocomplete), or CDS Sesame with Look up
        const name = form.elements.name;
        const box = form.querySelector('.pl-suggest');
        let timer = null, items = [];
        const hide = () => { box.hidden = true; box.replaceChildren(); items = []; };
        const pick = s => {
            name.value = s.name; form.elements.ra.value = s.ra; form.elements.dec.value = s.dec; hide();
            form.dispatchEvent(new Event('change', { bubbles: true }));
        };
        name.addEventListener('input', () => {
            clearTimeout(timer);
            const q = name.value.trim();
            if (q.length < 3) { hide(); return; }
            timer = setTimeout(async () => {
                items = await kinderObjects(q);
                box.replaceChildren(...items.slice(0, 8).map(s => el('li', {
                    role: 'option', onmousedown: ev => { ev.preventDefault(); pick(s); },
                }, el('span', { text: s.name }), el('small', { text: s.ra + '  ' + s.dec }))));
                box.hidden = !items.length;
            }, 220);
        });
        name.addEventListener('blur', () => setTimeout(hide, 150));
        name.addEventListener('keydown', e => {
            if (e.key === 'Escape') hide();
            if (e.key === 'Enter' && !box.hidden && items.length) { e.preventDefault(); pick(items[0]); }
        });
        form.querySelector('[data-lookup]').addEventListener('click', async ev => {
            const btn = ev.currentTarget;
            const q = name.value.trim();
            if (!q) { say(msg, 'Type a name first.', 'error'); return; }
            btn.disabled = true;
            say(msg, 'Looking up ' + q + '…');
            try {
                const r = await api(API + '/resolve?name=' + encodeURIComponent(q));
                form.elements.ra.value = r.ra;
                form.elements.dec.value = r.dec;
                say(msg, 'Found in ' + r.source + '.', 'ok');
                form.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (err) { say(msg, err.message, 'error'); }
            btn.disabled = false;
        });
        return { msg, sync };
    }

    async function kinderObjects(q) {
        try {
            const r = await fetch('/api/target_autocomplete?q=' + encodeURIComponent(q), { credentials: 'same-origin' });
            const items = r.ok ? await r.json() : [];
            return Array.isArray(items) ? items : [];
        } catch (err) { return []; }
    }

    // ── Calibrated frames on the server: search folders, tick frames ──────────
    const CAL_API = '/api/pipeline/calibrated';
    function picker(root, onPick) {
        const label = root.dataset.pickLabel || 'Use these frames';
        let qTimer = null;
        async function showFolders(q) {
            const search = el('input', { type: 'search', class: 'pl-ws-filter', placeholder: 'Search folders (target, night, telescope…)', value: q || '', 'aria-label': 'Search folders' });
            const list = el('div', { class: 'pl-pick-list' }, el('p', { class: 'pl-hint', text: 'Loading…' }));
            root.replaceChildren(search, list);
            const load = async () => {
                try {
                    const d = await api(CAL_API + '/folders?q=' + encodeURIComponent(search.value.trim()));
                    list.replaceChildren(...[(d.folders.length ? d.folders.map(f => el('button', { type: 'button', class: 'pl-pick-dir', onclick: () => showFolder(f.path, search.value) },
                        el('b', { class: 'pl-mono', text: f.path + '/' }), el('span', { text: plural(f.n, 'FITS', 'FITS') }), el('span', { 'data-ts': String(f.mtime) })))
                        : [el('p', { class: 'pl-faint', text: search.value.trim() ? 'No folder matches.' : 'No folders with FITS.' })]),
                        d.more ? el('p', { class: 'pl-hint', text: d.more + ' more; narrow the search.' }) : null].flat().filter(Boolean));
                    stamp(list);
                } catch (err) { list.replaceChildren(el('p', { class: 'pl-msg is-error', text: err.message })); }
            };
            search.addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(load, 250); });
            search.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
            load();
        }
        async function showFolder(path, q) {
            root.replaceChildren(el('p', { class: 'pl-hint', text: 'Reading ' + path + '…' }));
            let d;
            try { d = await api(CAL_API + '/folder?path=' + encodeURIComponent(path)); }
            catch (err) { root.replaceChildren(el('p', { class: 'pl-msg is-error', text: err.message })); return; }
            const boxes = [];
            const foot = el('span', { class: 'pl-faint' });
            const go = el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-primary', text: label });
            const sync = () => {
                const on = boxes.filter(b => b.box.checked);
                foot.textContent = on.length + ' of ' + boxes.length + ' selected · ' + sizeText(on.reduce((a, b) => a + b.f.size, 0));
                go.disabled = !on.length;
                all.checked = on.length === boxes.length; all.indeterminate = on.length > 0 && on.length < boxes.length;
            };
            const all = el('input', { type: 'checkbox', 'aria-label': 'Select all', onchange: () => { boxes.forEach(b => { if (!b.f.error) b.box.checked = all.checked; }); sync(); } });
            const rows = d.files.map(f => {
                const cal = f.imagetyp && CAL_RE.test(f.imagetyp);
                const box = el('input', { type: 'checkbox', checked: !f.error && !cal, disabled: !!f.error, onchange: sync, 'aria-label': f.name });
                boxes.push({ box, f });
                const h = f.header || {};
                return el('tr', { class: cal || f.error ? 'is-skip' : null },
                    el('td', {}, box), el('td', { class: 'pl-mono' }, f.name, cal ? el('span', { class: 'kw-chip', text: f.imagetyp }) : null),
                    el('td', {}, f.band ? el('b', { text: f.band }) : el('span', { class: 'pl-faint', text: '?' }), f.raw && f.raw !== f.band ? el('small', { text: ' ' + f.raw }) : null),
                    f.error ? el('td', { colspan: '4', class: 'is-miss', text: f.error }) : [
                        el('td', { text: [h.TELESCOP, h.INSTRUME].filter(Boolean).join(' / ') || '—' }),
                        el('td', { text: (h['DATE-OBS'] || '—').replace('T', ' ').slice(0, 19) }),
                        el('td', { text: h.EXPTIME || '—' }), el('td', { text: h.OBJECT || '—' })]);
            });
            go.addEventListener('click', async () => {
                const chosen = boxes.filter(b => b.box.checked).map(b => b.f);
                go.disabled = true;
                try { await onPick(chosen, d.path); } finally { go.disabled = false; }
            });
            root.replaceChildren(...[
                el('div', { class: 'pl-pick-head' },
                    el('button', { type: 'button', class: 'pl-link', text: '← All folders', onclick: () => showFolders(q) }),
                    el('b', { class: 'pl-mono', text: d.path + '/' })),
                el('div', { class: 'kw-table-wrap pl-pick-files' }, el('table', { class: 'kw-table pl-table pl-hdr' },
                    el('thead', {}, el('tr', {}, el('th', {}, all), ['File', 'Filter', 'Telescope / instrument', 'Date (UTC)', 'Exp (s)', 'OBJECT'].map(t => el('th', { text: t })))),
                    el('tbody', {}, rows))),
                d.more ? el('p', { class: 'pl-hint', text: d.more + ' more FITS not listed (first 500).' }) : null,
                el('div', { class: 'pl-pick-foot' }, foot, el('span', { class: 'pl-spacer' }), go)].filter(Boolean));
            sync();
        }
        showFolders('');
    }

    // ── New workspace wizard ──────────────────────────────────────────────────
    const wizard = document.querySelector('[data-pl-form][data-new]');
    if (wizard) {
        const { msg, sync } = wireForm(wizard);
        const scanBox = wizard.querySelector('[data-scan]');
        const cov = wizard.querySelector('[data-coverage]');
        const planBox = wizard.querySelector('[data-plan]');
        const bar = wizard.querySelector('[data-progress]');
        const btn = wizard.querySelector('button[type=submit]');
        const hint = wizard.querySelector('[data-target-hint]');
        let scan = null, extraTpl = [], created = null;

        const templates = () => (scan ? scan.items.filter(i => i.kind === 'template') : []).concat(extraTpl);
        const science = () => (scan ? scan.items.filter(i => i.kind === 'science') : []);

        // Per filter: frames, and which template (if any) will be used
        function renderCoverage() {
            const sci = science(), tpl = templates();
            const bands = [...new Set(sci.map(i => i.band || '?').concat(tpl.filter(t => t.band).map(t => t.band)))].sort();
            if (!bands.length) { cov.replaceChildren(el('p', { class: 'pl-hint', text: 'Drop the images first; each filter then gets a row here.' })); renderPlan(); return; }
            const rows = bands.map(b => {
                const n = sci.filter(i => (i.band || '?') === b).length;
                const cands = tpl.filter(t => t.band === b);
                if (cands.length && !cands.some(c => c.use)) cands.slice().sort((x, y) => y.file.size - x.file.size)[0].use = true;
                let cell;
                if (b === '?') cell = el('span', { class: 'pl-faint', text: 'Filter unknown; AutoPhOT decides when it runs' });
                else if (cands.length) {
                    cell = el('select', { class: 'kw-select kw-select-sm', 'aria-label': 'Template for ' + b, onchange: e => {
                        cands.forEach(c => { c.use = c.up === e.target.value; }); renderPlan(); } },
                        cands.map(c => el('option', { value: c.up, text: c.rel + ' · ' + sizeText(c.file.size), selected: c.use })));
                } else cell = el('span', { class: 'kw-chip kw-chip-red', text: 'No template' });
                return el('tr', {}, el('td', {}, el('b', { text: b === '?' ? '—' : b })), el('td', { text: n ? String(n) : '—' }), el('td', {}, cell));
            });
            const unknown = tpl.filter(t => !t.band);
            const kids = [el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table pl-cov' },
                el('thead', {}, el('tr', {}, el('th', { text: 'Filter' }), el('th', { text: 'Frames' }), el('th', { text: 'Template' }))),
                el('tbody', {}, rows)))];
            if (unknown.length) {
                kids.push(el('div', { class: 'pl-warn' }, el('b', { text: 'Which filter are these templates? ' }),
                    unknown.map(t => el('span', { class: 'pl-unknown' }, el('span', { class: 'pl-mono', text: t.rel + (t.raw ? ' (FILTER ' + t.raw + ')' : '') }),
                        bandSelect('', { onchange: e => { t.band = e.target.value; renderCoverage(); } })))));
            }
            cov.replaceChildren(...kids);
            renderPlan();
        }

        function renderPlan() {
            const sci = science(), mode = tsMode(wizard);
            const used = mode === 'own' ? templates().filter(t => t.band && t.use) : [];
            const ws = (wizard.elements.name.value.trim() || 'workspace').replace(/\s+/g, '_').replace(/[^A-Za-z0-9_+\-.]/g, '_');
            planBox.hidden = !sci.length;
            planBox.replaceChildren(el('span', { class: 'kw-label', text: 'Will be created on the server' }),
                el('ul', { class: 'pl-tree' },
                    el('li', { class: 'is-dir' }, el('b', { text: ws + '/' })),
                    el('li', { class: 'is-dir pl-d1' }, el('b', { text: 'images/' }), el('small', { text: plural(sci.length, 'frame') })),
                    used.length ? el('li', { class: 'is-dir pl-d2' }, el('b', { text: 'templates/' })) : null,
                    used.map(t => el('li', { class: 'pl-d3' }, el('b', { text: t.band + '_template/' }), el('small', { text: t.rel }))),
                    el('li', { class: 'is-dir pl-d1 is-later' }, el('b', { text: 'images_REDUCED/' }), el('small', { text: 'AutoPhOT output, after the run' }))));
        }

        async function prefillTarget() {
            const sci = science();
            const obj = mostCommon(sci.map(i => i.hdr && String(i.hdr.OBJECT || '').trim()));
            const f = wizard.elements;
            if (obj && !f.name.value.trim()) f.name.value = obj;
            const q = f.name.value.trim();
            if (q && !f.ra.value.trim()) {
                const hits = await kinderObjects(q);
                const norm = s => String(s).toLowerCase().replace(/[\s_]/g, '').replace(/^(sn|at)/, '');
                const hit = hits.find(h => norm(h.name) === norm(q));
                if (hit) {
                    f.name.value = hit.name; f.ra.value = hit.ra; f.dec.value = hit.dec;
                    say(hint, 'Position from the Kinder object ' + hit.name + '.', 'ok');
                    return;
                }
            }
            const c = hdrCoords((sci.find(i => i.hdr) || {}).hdr);
            hint.replaceChildren(document.createTextNode('AutoPhOT measures at this position; the name is only a label. '));
            if (c && !f.ra.value.trim()) {
                hint.append(el('button', { type: 'button', class: 'pl-link', text: 'Use the telescope pointing from the header (' + c.ra + ', ' + c.dec + ')',
                    onclick: () => { f.ra.value = c.ra; f.dec.value = c.dec; say(hint, 'Pointing from the header: check it is the target, not the field centre.', null); } }));
            }
        }

        dropZone(wizard.querySelector('[data-pl-drop]'), async list => {
            if (created) return;
            scanBox.hidden = false;
            scanBox.replaceChildren(el('p', { class: 'pl-hint', text: 'Reading ' + plural(list.length, 'file') + '…' }));
            scan = await scanFiles(list, (d, n) => { scanBox.firstChild.textContent = 'Reading headers ' + d + ' / ' + n + '…'; });
            if (!science().length) {
                scanBox.replaceChildren(el('p', { class: 'pl-msg is-error', text: 'No FITS frames found in what you dropped.' }));
                return;
            }
            scanBox.replaceChildren(...scanSummary(scan),
                el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: 'Start over', onclick: () => { scan = null; extraTpl = []; scanBox.hidden = true; renderCoverage(); } }));
            if (templates().length) {
                const own = wizard.querySelector('input[name=ts_mode][value=own]');
                if (own) { own.checked = true; sync(); }
            }
            renderCoverage();
            await prefillTarget();
            renderPlan();
        });

        // Source: this computer (drop) or calibrated frames on the server (picker); both end in the same scan
        const srcSync = () => {
            const src = (wizard.querySelector('input[name=src]:checked') || {}).value || 'upload';
            wizard.querySelectorAll('[data-src]').forEach(n => { n.hidden = n.dataset.src !== src; });
        };
        wizard.addEventListener('change', e => { if (e.target.name === 'src') srcSync(); });
        srcSync();
        const pick = wizard.querySelector('[data-picker]');
        if (pick) {
            picker(pick, async (files, folder) => {
                if (created) return;
                const seen = {};
                const items = files.map(f => {
                    const up = seen[f.name] ? f.path.replace(/\//g, '__') : f.name;
                    seen[f.name] = true;
                    return { server: f.path, rel: f.name, name: f.name, up, size: f.size, kind: 'science', why: '',
                        hdr: f.header || {}, band: f.band, raw: f.raw };
                });
                scan = { folder, items, other: [] };
                scanBox.hidden = false;
                scanBox.replaceChildren(...scanSummary(scan),
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: 'Start over', onclick: () => { scan = null; scanBox.hidden = true; renderCoverage(); } }));
                renderCoverage();
                await prefillTarget();
                renderPlan();
                scanBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });
        }

        const tplDrop = cov.parentElement.querySelector('[data-pl-drop]');
        dropZone(tplDrop, async list => {
            const s = await scanFiles(list);
            const add = s.items.filter(i => i.kind !== 'skip').map(i => Object.assign(i, { kind: 'template', use: false }));
            add.forEach(t => { t.up = 'tpl__' + t.up; });
            extraTpl = extraTpl.concat(add);
            add.filter(t => t.band).forEach(t => templates().filter(o => o.band === t.band).forEach(o => { o.use = o === t; }));
            renderCoverage();
        });
        wizard.addEventListener('change', e => { if (e.target.name === 'ts_mode' || e.target.name === 'name') renderPlan(); });
        wizard.elements.name.addEventListener('input', renderPlan);
        renderCoverage();

        wizard.addEventListener('submit', async e => {
            e.preventDefault();
            const sci = science();
            if (!created && !sci.length) { say(msg, 'Drop a folder or FITS files first.', 'error'); return; }
            const f = wizard.elements;
            if (!f.name.value.trim() || !f.ra.value.trim() || !f.dec.value.trim()) { say(msg, 'Enter the target and its RA and Dec.', 'error'); f.name.focus(); return; }
            const mode = tsMode(wizard);
            const tpl = mode === 'own' ? templates().filter(t => t.band && t.use) : [];
            btn.disabled = true;
            try {
                if (!created) {
                    say(msg, 'Creating the workspace…');
                    created = await api(API + '/new', formBody(wizard));
                    wizard.querySelectorAll('input, select').forEach(n => { n.disabled = true; });
                }
                const queue = sci.map(i => ({ file: i.file, up: i.up, server: i.server, size: i.size })).concat(tpl.map(t => ({ file: t.file, up: t.up.replace(/^tpl__/, ''), template: t.band })))
                    .filter(x => !x.done);
                say(msg, '');
                const r = await uploadAll(API + '/' + encodeURIComponent(created.id), queue, bar);
                queue.forEach(x => { if (x.result) x.done = true; });
                if (!r.failed.length) { location.href = created.url; return; }
                say(msg, r.failed.map(x => x.item.up + ': ' + x.error).slice(0, 3).join(' · ') + (r.failed.length > 3 ? ' …' : ''), 'error');
                btn.textContent = 'Open the workspace';
                btn.onclick = ev => { ev.preventDefault(); location.href = created.url; };
            } catch (err) { say(msg, err.message, 'error'); }
            btn.disabled = false;
        });
    }

    // ── Workspace page: images, templates, layout ─────────────────────────────

    const imgBody = $('plImgBody');
    const wsForm = document.querySelector('[data-pl-form][data-tid]');
    let reloadImages = () => {};
    if (imgBody) {
        const cov = wsForm ? wsForm.querySelector('[data-coverage]') : null;
        let last = null;

        const fail = err => imgBody.prepend(el('p', { class: 'pl-msg is-error', text: err.message }));
        function removeButton(name, label) {
            const b = el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: label || 'Remove', title: 'Move out of this workspace (can be put back)' });
            armable(b, 'Confirm', async () => {
                try { await api(base + '/images/remove', { name }); load(); } catch (err) { fail(err); }
            });
            return b;
        }
        function addTemplateButton(band) {
            const input = el('input', { type: 'file', class: 'pl-drop-input', accept: '.fits,.fit,.fts,.fz,.gz' });
            const btn = el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Add template', onclick: () => input.click() });
            input.addEventListener('change', async () => {
                const file = input.files[0];
                if (!file) return;
                btn.disabled = true;
                try {
                    await uploadFile(base, file, file.name, n => { btn.textContent = Math.round(n / file.size * 100) + '%'; }, band);
                    load();
                } catch (err) { btn.textContent = 'Add template'; btn.disabled = false; fail(err); }
            });
            return el('span', {}, input, btn);
        }

        function renderImages(d) {
            $('plImgCount').textContent = plural(d.n, 'frame');
            d.files.forEach(f => { f.stack = d.stacks.indexOf(f.name) >= 0; });
            const parts = [];
            if (d.missing) parts.push(el('p', { class: 'pl-warn', text: plural(d.missing, 'frame') + ' missing TELESCOP / INSTRUME / FILTER; AutoPhOT skips them.' }));
            if (!d.files.length) parts.push(el('div', { class: 'pl-empty' }, el('b', { text: 'No frames yet' }), 'Drop a folder or FITS files above.'));
            else {
                parts.push(el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table pl-hdr' },
                    el('thead', {}, el('tr', {}, ['File', 'Filter', 'Telescope / instrument', 'Date (UTC)', 'Exp (s)', 'Deleted'].map(h => el('th', { text: h })), el('th'))),
                    el('tbody', {}, d.files.map(f => el('tr', {},
                        el('td', { class: 'pl-mono' }, f.name, f.stack ? el('span', { class: 'kw-chip kw-chip-gold', text: 'stack' }) : null),
                        f.error ? el('td', { class: 'is-miss', colspan: '4', text: f.error }) : [
                            el('td', { class: !f.FILTER ? 'is-miss' : null }, f.band ? el('b', { text: f.band }) : null,
                                el('small', { text: (f.band ? ' ' : '') + (f.FILTER || 'missing') })),
                            el('td', { class: !(f.TELESCOP && f.INSTRUME) ? 'is-miss' : null, text: (f.TELESCOP || 'TELESCOP missing') + ' / ' + (f.INSTRUME || 'INSTRUME missing') }),
                            el('td', { text: (f['DATE-OBS'] || '—').replace('T', ' ').slice(0, 19) }),
                            el('td', { text: f.EXPTIME || '—' })],
                        el('td', { class: 'pl-faint', title: new Date(f.expires * 1000).toLocaleString(), text: daysLeft(f.expires) }),
                        el('td', { class: 'pl-acts' }, f.stack ? null : removeButton(f.name))))))));
            }
            if (d.expired.length) {
                const restore = d.restorable ? el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Copy ' + d.restorable + ' again from the server',
                    onclick: async ev => {
                        ev.currentTarget.disabled = true;
                        try { const r = await api(base + '/restore', {}); if (r.missing.length) fail(new Error(r.missing.length + ' no longer on the server.')); load(); }
                        catch (err) { fail(err); ev.currentTarget.disabled = false; }
                    } }) : null;
                parts.push(el('details', { class: 'pl-removed pl-expired' },
                    el('summary', { text: plural(d.expired.length, 'FITS', 'FITS') + ' deleted after ' + d.keep_days + ' days (results kept)' }),
                    restore ? el('div', {}, el('span', { class: 'pl-faint', text: 'Frames that came from the calibrated folder can be copied again.' }), restore) : null,
                    d.expired.slice(-200).reverse().map(e => el('div', {}, el('span', { class: 'pl-mono', text: e.name }), el('span', { class: 'pl-faint', 'data-ts': String(e.at) })))));
            }
            if (d.removed.length) {
                parts.push(el('details', { class: 'pl-removed' },
                    el('summary', { text: d.removed.length + ' removed' }),
                    d.removed.map(r => el('div', {}, el('span', { class: 'pl-mono', text: r }),
                        el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: 'Put back',
                            onclick: async ev => {
                                ev.currentTarget.disabled = true;
                                try { await api(base + '/images/restore', { name: r }); load(); } catch (err) { fail(err); }
                            } })))));
            }
            imgBody.replaceChildren(...parts);
            stamp(imgBody);
        }

        function renderCoverage(d) {
            if (!cov) return;
            const active = {};
            d.templates.filter(t => t.active).forEach(t => { active[t.band] = t; });
            const bands = [...new Set(d.coverage.map(c => c.band).concat(Object.keys(active)))].sort((a, b) => (!a) - (!b) || a.localeCompare(b));
            const rows = bands.map(b => {
                const c = d.coverage.find(x => x.band === b) || { n: 0 };
                const t = active[b];
                const cell = !b ? el('span', { class: 'pl-faint', text: 'Filter unknown' })
                    : t ? el('span', { class: 'pl-tpl-cell' }, el('span', { class: 'pl-mono', text: t.name.split('/').pop() }), removeButton(t.name))
                        : el('span', { class: 'pl-tpl-cell' }, el('span', { class: 'kw-chip kw-chip-red', text: 'No template' }), addTemplateButton(b));
                return el('tr', {}, el('td', {}, el('b', { text: b || '—' })), el('td', { text: c.n ? String(c.n) : '—' }), el('td', {}, cell),
                    el('td', { class: 'pl-faint', text: t ? daysLeft(t.expires) : '' }));
            });
            const kids = [el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table pl-cov' },
                el('thead', {}, el('tr', {}, el('th', { text: 'Filter' }), el('th', { text: 'Frames' }), el('th', { text: 'Template used' }), el('th', { text: 'Deleted' }))),
                el('tbody', {}, rows.length ? rows : el('tr', {}, el('td', { colspan: '3', class: 'pl-faint', text: 'Add frames first.' })))))];
            const aside = d.templates.filter(t => !t.active);
            if (aside.length) {
                kids.push(el('details', { class: 'pl-removed' }, el('summary', { text: plural(aside.length, 'template') + ' set aside (another one of the filter is used)' }),
                    aside.map(t => el('div', {}, el('span', { class: 'pl-mono', text: t.name }), removeButton(t.name)))));
            }
            cov.replaceChildren(...kids);
        }

        function renderTree(d) {
            const tree = $('plTree');
            if (!tree) return;
            const byBand = {};
            d.templates.filter(t => t.active).forEach(t => { byBand[t.band] = t.name.split('/').pop(); });
            const nLegacy = parseInt(page.dataset.legacy, 10) || 0;
            tree.replaceChildren(...[
                el('li', { class: 'is-dir' }, el('b', { text: tid + '/' })),
                el('li', { class: 'is-dir pl-d1' }, el('b', { text: 'images/' }), el('small', { text: plural(d.n, 'frame') })),
                Object.keys(byBand).length ? el('li', { class: 'is-dir pl-d2' }, el('b', { text: 'templates/' })) : null,
                Object.keys(byBand).sort().map(b => el('li', { class: 'pl-d3' }, el('b', { text: b + '_template/' }), el('small', { text: byBand[b] }))),
                el('li', { class: 'is-dir pl-d1' + (page.dataset.results ? '' : ' is-later') }, el('b', { text: 'images_REDUCED/' }), el('small', { text: page.dataset.results ? 'AutoPhOT output' : 'after the first run' })),
                nLegacy ? el('li', { class: 'is-dir pl-d1' }, el('b', { text: 'legacy/' }), el('small', { text: plural(nLegacy, 'earlier run') })) : null,
            ].flat().filter(Boolean));
        }

        async function load() {
            try {
                last = await api(base + '/images');
                renderImages(last);
                renderCoverage(last);
                renderTree(last);
            } catch (err) {
                imgBody.replaceChildren(el('p', { class: 'pl-msg is-error', text: err.message }));
            }
        }
        reloadImages = load;

        const serverPick = document.querySelector('#plFromServer [data-picker]');
        if (serverPick) {
            picker(serverPick, async files => {
                const queue = files.map(f => ({ server: f.path, up: f.name, size: f.size }));
                const r = await uploadAll(base, queue, $('plAddState'));
                if (r.failed.length) fail(new Error(r.failed.map(x => x.item.up + ': ' + x.error).slice(0, 3).join(' · ')));
                load();
            });
        }

        // Frames (and a templates/ subfolder) dropped on Images: upload at once
        const addState = $('plAddState');
        let busy = false;
        dropZone($('plAddFiles'), async list => {
            if (busy) return;
            busy = true;
            addState.hidden = false;
            addState.querySelector('small').textContent = 'Reading ' + plural(list.length, 'file') + '…';
            const s = await scanFiles(list);
            const queue = s.items.filter(i => i.kind !== 'skip').map(i => ({ file: i.file, up: i.up, template: i.kind === 'template' ? (i.band || 'auto') : '' }));
            if (!queue.length) { addState.querySelector('small').textContent = 'No FITS in what you dropped.'; busy = false; return; }
            const r = await uploadAll(base, queue, addState);
            if (r.failed.length) fail(new Error(r.failed.map(x => x.item.up + ': ' + x.error).slice(0, 3).join(' · ')));
            busy = false;
            load();
        });

        // Templates dropped on Template subtraction: the server reads each filter
        const tplRoot = wsForm ? wsForm.querySelector('.pl-ts-own [data-pl-drop]') : null;
        if (tplRoot) {
            dropZone(tplRoot, async list => {
                const files = list.filter(x => FITS_RE.test(x.file.name));
                for (const x of files) {
                    try { await uploadFile(base, x.file, x.file.name, null, 'auto'); }
                    catch (err) {
                        // Filter not recognised: ask for it next to the message, upload again with that filter
                        const sel = bandSelect('');
                        const row = el('p', { class: 'pl-warn' }, err.message + ' ', sel,
                            el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Upload as this filter', onclick: async ev => {
                                if (!sel.value) return;
                                ev.currentTarget.disabled = true;
                                try { await uploadFile(base, x.file, x.file.name, null, sel.value); row.remove(); load(); }
                                catch (e2) { row.firstChild.textContent = e2.message + ' '; ev.currentTarget.disabled = false; }
                            } }));
                        tplRoot.after(row);
                    }
                }
                load();
            });
        }
        load();
    }

    // ── Workspace settings: saved as they change ──────────────────────────────
    const saveState = $('plSaveState');
    let saveTimer = null, saving = Promise.resolve();
    async function saveNow() {
        if (!wsForm) return;
        clearTimeout(saveTimer);
        say(saveState, 'Saving…');
        saving = saving.then(() => api(base + '/save', formBody(wsForm)))
            .then(() => say(saveState, 'Saved', 'ok'), err => { say(saveState, err.message, 'error'); throw err; });
        return saving.catch(() => { saving = Promise.resolve(); throw new Error(saveState.textContent); });
    }
    if (wsForm) {
        wireForm(wsForm);
        wsForm.addEventListener('submit', e => { e.preventDefault(); saveNow().catch(() => {}); });
        wsForm.addEventListener('change', e => {
            if (!e.target.name || e.target.closest('[data-coverage], [data-pl-drop]')) return;
            clearTimeout(saveTimer);
            saveTimer = setTimeout(() => saveNow().catch(() => {}), 500);
        });
    }

    // ── Run, progress, log, answers, stop ─────────────────────────────────────
    const jobBox = $('plJob');
    if (jobBox) {
        const logEl = $('plLog'), stateEl = $('plJobState'), runBtn = $('plRun'), ans = $('plAnswer'), prog = $('plProgress');
        let running = false, timer = null, stopArmed = false, armTimer = null;

        const elapsed = start => {
            const s = Math.max(0, Math.round(Date.now() / 1000 - start));
            const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
            return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(sec).padStart(2, '0');
        };
        function setRunning(on) {
            running = on;
            runBtn.disabled = false;
            stopArmed = false;
            runBtn.classList.toggle('kw-btn-primary', !on);
            runBtn.classList.toggle('kw-btn-danger', on);
            runBtn.classList.remove('is-armed');
            runBtn.textContent = on ? 'Stop' : 'Run';
            const head = $('plHeadState');
            if (head && on) head.replaceChildren(el('span', { class: 'kw-chip kw-chip-blue' }, el('span', { class: 'pl-pulse', 'aria-hidden': 'true' }), 'Running'));
        }
        function show(j) {
            const stick = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
            if (j.log) { logEl.hidden = false; $('plLogFoot').hidden = false; $('plRunHint').hidden = true; logEl.textContent = j.log; }
            if (stick) logEl.scrollTop = logEl.scrollHeight;
            const isRunning = j.status === 'running';
            if (isRunning !== running) setRunning(isRunning);
            const wasHidden = ans.hidden;
            ans.hidden = !j.waiting;
            if (j.waiting && wasHidden) ans.elements.text.focus();
            const p = j.progress;
            prog.hidden = !p;
            if (p) {
                prog.querySelector('.pl-bar > span').style.width = Math.round(p.done / Math.max(1, p.total) * 100) + '%';
                prog.querySelector('small').textContent = p.done + ' of ' + plural(p.total, 'image') + ' measured' + (p.failed ? ' · ' + p.failed + ' failed' : '');
            }
            say(stateEl, isRunning ? (j.waiting ? 'Waiting for an answer · ' : 'Running · ') + elapsed(j.start)
                : j.status === 'failed' ? 'Failed, see the log' : j.status === 'stopped' ? 'Stopped' : j.status === 'done' ? 'Finished' : '',
                j.status === 'failed' ? 'error' : null);
            return isRunning;
        }
        async function poll() {
            try {
                const j = (await api(base + '/job')).job;
                if (show(j)) return;
                clearInterval(timer); timer = null;
                if (j.status === 'done') location.href = location.pathname + '?tab=results';
            } catch (err) { clearInterval(timer); timer = null; say(stateEl, err.message, 'error'); }
        }
        const startPolling = () => { if (!timer) timer = setInterval(poll, 1500); poll(); };

        runBtn.addEventListener('click', async () => {
            if (running) {
                if (!stopArmed) {
                    stopArmed = true;
                    runBtn.classList.add('is-armed');
                    runBtn.textContent = 'Stop now?';
                    armTimer = setTimeout(() => { stopArmed = false; runBtn.classList.remove('is-armed'); runBtn.textContent = 'Stop'; }, 5000);
                    return;
                }
                clearTimeout(armTimer);
                runBtn.disabled = true;
                try { await api(base + '/stop', {}); poll(); }
                catch (err) { say(stateEl, err.message, 'error'); runBtn.disabled = false; }
                return;
            }
            runBtn.disabled = true;
            say(stateEl, 'Starting…');
            try {
                if (wsForm) await saveNow();
                await api(base + '/run', {});
                logEl.textContent = '';
                setRunning(true);
                startPolling();
            } catch (err) { say(stateEl, err.message, 'error'); runBtn.disabled = false; }
        });
        async function send(text) {
            try { await api(base + '/answer', { text }); ans.elements.text.value = ''; ans.hidden = true; poll(); }
            catch (err) { say(stateEl, err.message, 'error'); }
        }
        ans.addEventListener('submit', e => { e.preventDefault(); send(ans.elements.text.value); });
        ans.querySelector('[data-default]').addEventListener('click', () => send(''));

        api(base + '/job').then(d => { if (show(d.job)) startPolling(); }).catch(() => {});
    }

    // ── All AutoPhOT settings (loaded when opened) ────────────────────────────
    const all = $('plAll');
    if (all) {
        const body = $('plAllBody'), q = $('plAllQ'), only = $('plAllOnly'), count = $('plAllCount');
        const TITLES = { common: 'Common', general: 'General', preprocessing: 'Preprocessing', photometry: 'Photometry',
            wcs: 'WCS (astrometry)', catalog: 'Catalog', zeropoint: 'Zeropoint', cosmic_rays: 'Cosmic rays',
            source_detection: 'Source detection', limiting_magnitude: 'Limiting magnitude', alignment: 'Alignment',
            template_subtraction: 'Template subtraction', background: 'Background', postprocessing: 'Post-processing',
            lightcurve: 'Light curve' };
        let S = null;
        const byKey = {};
        const current = it => (it.key in overrides ? overrides[it.key] : it.default);

        function row(it) {
            const v = current(it), changed = it.key in overrides;
            let ctl;
            if (it.kind === 'bool') {
                ctl = el('select', { class: 'kw-select kw-select-sm', 'data-key': it.key, 'aria-label': it.key },
                    ['true', 'false'].map(o => el('option', { value: o, selected: String(v).toLowerCase() === o, text: o === 'true' ? 'True' : 'False' })));
            } else {
                ctl = el('input', { type: it.secret ? 'password' : 'text', class: 'pl-mono', 'data-key': it.key, value: v,
                    spellcheck: 'false', autocomplete: 'off', 'aria-label': it.key });
            }
            return el('div', { class: 'pl-set' + (changed ? ' is-changed' : ''), 'data-row': it.key },
                el('div', { class: 'pl-set-main' },
                    el('div', { class: 'pl-set-name' },
                        el('code', {}, it.sub ? el('span', { class: 'pl-faint', text: it.sub + '.' }) : null, it.name),
                        it.type ? el('span', { class: 'pl-set-type', text: it.type }) : null),
                    it.note ? el('p', { class: 'pl-set-note', text: it.note }) : null,
                    it.help ? el('p', { class: 'pl-set-help', text: it.help }) : null),
                el('div', { class: 'pl-set-ctl' }, ctl,
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', 'data-reset': it.key, text: 'Reset' }),
                    el('small', { class: 'pl-set-def' }, 'Default ', el('code', { text: it.secret && it.default !== 'null' ? '••••' : it.default }))));
        }
        function itemsOf(id) {
            return id === 'common' ? S.common.map(k => byKey[k]) : S.items.filter(it => it.section === id);
        }
        function section(id, open) {
            const items = itemsOf(id);
            const n = items.filter(it => it.key in overrides).length;
            return el('details', { class: 'pl-sec', 'data-sec': id, open },
                el('summary', {}, el('b', { text: TITLES[id] || id.charAt(0).toUpperCase() + id.slice(1).replace(/_/g, ' ') }), el('span', { class: 'pl-faint', text: String(items.length) }),
                    n ? el('span', { class: 'kw-chip kw-chip-gold', text: n + ' changed' }) : null),
                el('div', { class: 'pl-sec-body' }, open ? items.map(row) : null));
        }
        function render() {
            const text = q.value.trim().toLowerCase();
            if (text || only.checked) {
                const list = S.items.filter(it => (!only.checked || it.key in overrides)
                    && (!text || (it.key + ' ' + it.help + ' ' + it.note).toLowerCase().includes(text)));
                body.replaceChildren(list.length
                    ? el('p', { class: 'pl-faint', text: list.length + ' setting' + (list.length === 1 ? '' : 's') + (list.length > 300 ? ', first 300 shown' : '') })
                    : el('p', { class: 'pl-faint', text: 'No matching setting.' }), ...list.slice(0, 300).map(row));
            } else {
                body.replaceChildren(section('common', true), ...S.sections.map(s => section(s.id, false)));
            }
            updateCount();
        }
        function updateCount() {
            const n = Object.keys(overrides).length;
            count.hidden = !n;
            count.textContent = n + ' changed';
        }
        body.addEventListener('toggle', e => {
            const d = e.target;
            if (!d.matches || !d.matches('details.pl-sec') || !d.open) return;
            const b = d.querySelector('.pl-sec-body');
            if (!b.childElementCount) b.replaceChildren(...itemsOf(d.dataset.sec).map(row));
        }, true);
        function setValue(key, text) {
            const it = byKey[key];
            const same = String(text).trim() === it.default || (it.kind === 'bool' && String(text).toLowerCase() === it.default)
                || (it.kind === 'number' && String(text).trim() !== '' && Number(text) === Number(it.default));
            if (same) delete overrides[key]; else overrides[key] = text;
            body.querySelectorAll('[data-row="' + CSS.escape(key) + '"]').forEach(r => r.classList.toggle('is-changed', key in overrides));
            updateCount();
        }
        body.addEventListener('change', e => { if (e.target.dataset.key) setValue(e.target.dataset.key, e.target.value); });
        body.addEventListener('input', e => { if (e.target.dataset.key && e.target.tagName === 'INPUT') setValue(e.target.dataset.key, e.target.value); });
        body.addEventListener('click', e => {
            const b = e.target.closest('[data-reset]');
            if (!b) return;
            const it = byKey[b.dataset.reset];
            setValue(it.key, it.default);
            body.querySelectorAll('[data-key="' + CSS.escape(it.key) + '"]').forEach(n => { n.value = it.default; });
        });
        let qt = null;
        q.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => S && render(), 150); });
        only.addEventListener('change', () => S && render());
        $('plAllSave').addEventListener('click', () => saveNow().catch(() => {}));
        let loaded = false;
        all.addEventListener('toggle', async () => {
            if (!all.open || loaded) return;
            loaded = true;
            try {
                S = await api(base + '/settings');
                S.items.forEach(it => { byKey[it.key] = it; });
                overrides = Object.assign({}, S.overrides);
                render();
            } catch (err) {
                loaded = false;
                body.replaceChildren(el('p', { class: 'pl-msg is-error', text: err.message }));
            }
        });
    }

    // ── Delete workspace / earlier run ────────────────────────────────────────
    const del = $('plDelete');
    if (del) {
        armable(del, 'Delete for sure?', async () => {
            try { await api(base + '/delete', {}); location.href = '/pipeline'; }
            catch (err) { del.after(el('p', { class: 'pl-msg is-error', text: err.message })); }
        });
    }
    document.querySelectorAll('[data-legacy-del]').forEach(b => {
        armable(b, 'Confirm', async () => {
            try { await api(base + '/legacy/delete', { run: b.dataset.legacyDel }); location.reload(); }
            catch (err) { b.after(el('p', { class: 'pl-msg is-error', text: err.message })); }
        });
    });

    // ── Import into a Kinder object: object → check the points → type the name ─
    const imp = $('plImport');
    if (imp) {
        const openBtn = $('plImportOpen');
        const steps = [...imp.querySelectorAll('[data-istep]')];
        const msg = imp.querySelector('[data-msg]'), next = imp.querySelector('[data-next]'), back = imp.querySelector('[data-back]');
        const obj = $('plImpObj'), confirm = $('plImpConfirm');
        let step = 1, pv = null;
        const body = () => ({ object: obj.value.trim(), method: $('plImpMethod').value, limit: $('plImpLimit').value,
            with_limits: $('plImpLimits').checked, run: openBtn.dataset.run || '' });
        function show(n) {
            step = n;
            steps.forEach(s => { s.hidden = +s.dataset.istep !== n; });
            imp.querySelector('[data-step-label]').textContent = 'Step ' + n + ' of 3';
            back.hidden = n === 1;
            next.textContent = n === 1 ? 'Next' : n === 2 ? 'These points are right' : 'Import';
            next.classList.toggle('kw-btn-danger', n === 3);
            next.disabled = n === 3 && confirm.value.trim() !== (pv && pv.object);
            say(msg, '');
            (n === 1 ? obj : n === 3 ? confirm : next).focus();
        }
        const close = () => { imp.classList.remove('is-open'); document.body.style.overflow = ''; };
        openBtn.addEventListener('click', () => {
            obj.value = obj.value || openBtn.dataset.object;
            confirm.value = '';
            imp.classList.add('is-open');
            document.body.style.overflow = 'hidden';
            show(1);
        });
        imp.querySelector('[data-cancel]').addEventListener('click', close);
        imp.addEventListener('click', e => { if (e.target === imp) close(); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape' && imp.classList.contains('is-open')) close(); });
        back.addEventListener('click', () => show(step - 1));
        confirm.addEventListener('input', () => { next.disabled = confirm.value.trim() !== (pv && pv.object); });
        confirm.addEventListener('keydown', e => { if (e.key === 'Enter' && !next.disabled) next.click(); });
        obj.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); next.click(); } });
        next.addEventListener('click', async () => {
            next.disabled = true;
            try {
                if (step === 1) {
                    say(msg, 'Checking…');
                    pv = await api(base + '/import/preview', body());
                    const nl = pv.points.filter(p => p.upper).length;
                    imp.querySelector('[data-sum]').textContent = plural(pv.points.length, 'point') + ' (' + (pv.points.length - nl) + ' detections, ' + plural(nl, 'limit') + ') → '
                        + pv.object + ', which has ' + plural(pv.n_existing, 'point') + (pv.n_duplicates ? '; about ' + pv.n_duplicates + ' of these are already there and will be skipped.' : '.');
                    const al = imp.querySelector('[data-already]');
                    al.hidden = !pv.already;
                    if (pv.already) al.textContent = 'This light curve was already imported into ' + pv.object + ' on ' + new Date(pv.already.time * 1000).toLocaleString() + ' (' + pv.already.n_inserted + ' points). Importing again only adds points that are not there yet.';
                    imp.querySelector('[data-rows]').replaceChildren(...pv.points.map(p => el('tr', { class: p.upper ? 'is-skip' : null },
                        el('td', { text: p.mjd.toFixed(5) }), el('td', { text: (p.upper ? '>' : '') + p.magnitude.toFixed(3) }),
                        el('td', { text: p.magnitude_error == null ? '—' : p.magnitude_error.toFixed(3) }), el('td', { text: p.filter }), el('td', { text: p.telescope }))));
                    show(2);
                } else if (step === 2) {
                    imp.querySelector('[data-final]').textContent = 'Add ' + plural(pv.points.length, 'point') + ' to ' + pv.object + '?';
                    confirm.value = '';
                    show(3);
                } else {
                    say(msg, 'Importing…');
                    const r = await api(base + '/import', Object.assign(body(), { object: pv.object, confirm: confirm.value.trim() }));
                    say(msg, r.n_inserted + ' of ' + r.n_points + ' points added to ' + r.object + '.', 'ok');
                    next.hidden = true; back.hidden = true;
                    imp.querySelector('[data-cancel]').textContent = 'Close';
                    imp.querySelector('[data-cancel]').addEventListener('click', () => location.reload(), { once: true });
                    return;
                }
            } catch (err) { say(msg, err.message, 'error'); }
            next.disabled = step === 3 && confirm.value.trim() !== (pv && pv.object);
        });
        // Kinder objects as you type
        const box = imp.querySelector('.pl-suggest');
        let t = null;
        obj.addEventListener('input', () => {
            clearTimeout(t);
            const q = obj.value.trim();
            if (q.length < 3) { box.hidden = true; return; }
            t = setTimeout(async () => {
                const items = await kinderObjects(q);
                box.replaceChildren(...items.slice(0, 8).map(o => el('li', { role: 'option', onmousedown: ev => { ev.preventDefault(); obj.value = o.name; box.hidden = true; } },
                    el('span', { text: o.name }), el('small', { text: o.ra + '  ' + o.dec }))));
                box.hidden = !items.length;
            }, 220);
        });
        obj.addEventListener('blur', () => setTimeout(() => { box.hidden = true; }, 150));
    }
    document.querySelectorAll('[data-import-undo]').forEach(b => {
        armable(b, 'Remove them?', async () => {
            try { await api(base + '/import/undo', { id: b.dataset.importUndo }); location.reload(); }
            catch (err) { b.after(el('p', { class: 'pl-msg is-error', text: err.message })); }
        });
    });

    // ── Workspace list filter (Pipeline page) ─────────────────────────────────
    const wsFilter = $('plWsFilter');
    if (wsFilter) {
        wsFilter.addEventListener('input', () => {
            const q = wsFilter.value.trim().toLowerCase();
            document.querySelectorAll('#plWsList .pl-ws').forEach(li => { li.hidden = q && !li.dataset.name.includes(q); });
        });
    }

    // ── Telescopes: the shared telescope.yml ──────────────────────────────────
    const telText = $('plTelText');
    if (telText) {
        const msg = $('plTelMsg');
        let saved = telText.value;
        const dirty = () => telText.value !== saved;
        const sync = () => telText.classList.toggle('is-dirty', dirty());
        telText.addEventListener('input', sync);
        telText.addEventListener('keydown', e => {          // Tab indents instead of leaving the editor
            if (e.key !== 'Tab' || e.shiftKey) return;
            e.preventDefault();
            telText.setRangeText('  ', telText.selectionStart, telText.selectionEnd, 'end');
            sync();
        });
        window.addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
        const val = v => (v == null || v === 'not_given_by_user')
            ? el('span', { class: 'kw-chip kw-chip-red', text: 'not set' }) : el('span', { class: 'pl-mono', text: String(v) });
        function table(rows) {
            $('plTelCount').textContent = String(rows.length);
            $('plTelTable').replaceChildren(el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table' },
                el('thead', {}, el('tr', {}, ['Telescope', 'Instrument', 'Pixel scale (″)', 'Gain', 'Read noise', 'Saturation', 'Filters'].map(h => el('th', { text: h })))),
                el('tbody', {}, rows.map(r => el('tr', {},
                    el('td', {}, el('b', { text: r.telescope })),
                    el('td', {}, r.instrument, r.local_only ? el('span', { class: 'kw-chip kw-chip-gold', title: 'Not in the template in git', text: 'This server' }) : null),
                    el('td', {}, val(r.pixel_scale)), el('td', {}, val(r.gain)), el('td', {}, val(r.readnoise)), el('td', {}, val(r.saturate)),
                    el('td', { text: r.filters.join(', ') || '—' })))))));
        }
        $('plTelSave').addEventListener('click', async ev => {
            const btn = ev.currentTarget;
            btn.disabled = true;
            say(msg, 'Saving…');
            try {
                const r = await api('/api/pipeline/telescopes', { text: telText.value });
                saved = telText.value;
                sync();
                if (r.rows) table(r.rows);
                say(msg, r.changed ? 'Saved on this server.' : 'No changes.', 'ok');
            } catch (err) { say(msg, err.message, 'error'); }
            btn.disabled = false;
        });
        $('plTelReset').addEventListener('click', () => { telText.value = saved; sync(); say(msg, ''); });
    }

    // ── Light curve for import: preview, download ─────────────────────────────
    const exp = $('plExport');
    if (exp) {
        const url = dl => {
            const f = exp.elements;
            const p = new URLSearchParams({ method: f.method.value, limit: f.limit.value, header: f.header.checked ? '1' : '0' });
            if (exp.dataset.run) p.set('run', exp.dataset.run);
            if (dl) p.set('download', '1');
            return '/pipeline/autophot/' + encodeURIComponent(tid) + '/export.txt?' + p;
        };
        const pre = exp.querySelector('.pl-export-pre');
        const preview = async () => {
            try {
                const r = await fetch(url(false), { credentials: 'same-origin' });
                pre.textContent = r.ok ? await r.text() : 'No light curve to export.';
                pre.hidden = false;
            } catch (err) { pre.textContent = 'Network error.'; pre.hidden = false; }
        };
        exp.querySelector('[data-preview]').addEventListener('click', () => {
            if (pre.hidden) preview(); else pre.hidden = true;
        });
        exp.addEventListener('change', () => { if (!pre.hidden) preview(); });
        exp.addEventListener('submit', e => { e.preventDefault(); location.href = url(true); });
    }
})();
