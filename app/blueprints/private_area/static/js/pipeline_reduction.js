/* Pipeline › Reduction: New batch (drop raw frames → make a batch, upload in pieces, start it, open it) on the hub,
   and the batch page (run / stop / delete, steps, astrometry, results, send to AutoPhOT, log; polled while running). */
(function () {
    'use strict';

    const API = '/api/pipeline/reduction';
    const $ = id => document.getElementById(id);

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

    function say(node, text, kind) {
        if (!node) return;
        node.textContent = text || '';
        node.classList.toggle('is-error', kind === 'error');
        node.classList.toggle('is-ok', kind === 'ok');
    }

    const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));
    const sizeText = n => n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' kB';
    const secs = s => s >= 90 ? Math.round(s / 60) + ' min' : Math.round(s) + ' s';

    function stamp(root) {
        (root || document).querySelectorAll('[data-ts]').forEach(n => {
            const v = parseFloat(n.dataset.ts);
            if (!v) return;
            const d = new Date(v * 1000);
            n.textContent = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            n.title = d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
        });
        (root || document).querySelectorAll('[data-left]').forEach(n => {
            const d = (parseFloat(n.dataset.left) * 1000 - Date.now()) / 86400e3;
            n.textContent = d <= 0 ? 'soon' : d < 1 ? 'in ' + Math.max(1, Math.round(d * 24)) + ' h' : 'in ' + Math.round(d) + ' d';
        });
    }
    stamp();

    // Two-step button: the first click arms it for 5 s, the second does the work.
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

    // ── FITS header, read in the browser to show what was dropped ──
    const FITS_RE = /\.(fits|fit|fts)$/i;
    const TYPE = { light: 'Science', lightframe: 'Science', object: 'Science', bias: 'Bias', biasframe: 'Bias', zero: 'Bias',
        dark: 'Dark', darkframe: 'Dark', flat: 'Flat', flatframe: 'Flat' };

    function parseCard(card) {
        const key = card.slice(0, 8).trim();
        if (card.slice(8, 10) !== '= ') return [key, undefined];
        const raw = card.slice(10);
        if (raw.trimStart().startsWith("'")) {
            const m = raw.match(/'((?:[^']|'')*)'/);
            return [key, m ? m[1].replace(/''/g, "'").trimEnd() : ''];
        }
        const v = raw.split('/')[0].trim();
        const num = Number(v.replace(/D/i, 'E'));
        return [key, v !== '' && isFinite(num) ? num : v];
    }

    async function readHeader(file) {
        const out = {};
        try {
            for (let pos = 0; pos < 20 * 2880; pos += 2880) {
                const block = new TextDecoder('latin1').decode(await file.slice(pos, pos + 2880).arrayBuffer());
                if (block.length < 2880) return out;
                for (let i = 0; i < 36; i++) {
                    const [k, v] = parseCard(block.slice(i * 80, i * 80 + 80));
                    if (k === 'END') return out;
                    if (v !== undefined && !(k in out)) out[k] = v;
                }
            }
        } catch (e) { /* not readable: the server says why */ }
        return out;
    }

    async function droppedFiles(dt) {
        const entries = [...(dt.items || [])].map(it => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
        if (!entries.length) return [...dt.files];
        const out = [];
        const walk = async entry => {
            if (entry.isFile) out.push(await new Promise((ok, bad) => entry.file(ok, bad)));
            else if (entry.isDirectory) {
                const reader = entry.createReader();
                let batch;
                do {
                    batch = await new Promise((ok, bad) => reader.readEntries(ok, bad));
                    for (const e of batch) if (!e.name.startsWith('.')) await walk(e);
                } while (batch.length);
            }
        };
        for (const e of entries) await walk(e);
        return out;
    }

    function dropZone(root, onFiles) {
        const zone = root.querySelector('.pl-drop-zone');
        root.querySelectorAll('.pl-drop-input').forEach(input => input.addEventListener('change', () => {
            const list = [...input.files];
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

    const CHUNK = parseInt((document.querySelector('[data-chunk]') || {}).dataset?.chunk, 10) || 8 * 1024 * 1024;

    async function uploadFile(base, file, onProgress) {
        let offset = 0;
        do {
            const piece = file.slice(offset, offset + CHUNK);
            const q = new URLSearchParams({ name: file.name, offset: String(offset), total: String(file.size) });
            let res, data;
            try {
                res = await fetch(base + '/upload?' + q, { method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/octet-stream' }, body: piece });
                data = await res.json();
            } catch (e) {
                throw new Error(res ? 'Upload refused by the server (' + res.status + ').' : 'Network error during upload.');
            }
            if (!res.ok || !data.success) throw new Error(data.error || 'Upload failed.');
            offset += piece.size;
            onProgress(offset);
            if (data.done) return data;
        } while (offset < file.size);
        throw new Error('Upload did not finish.');
    }

    // ── Hub: New batch ──
    const newBox = $('rdNew');
    if (newBox) {
        const pick = newBox.querySelector('[data-pick]');
        const rows = newBox.querySelector('[data-pick-rows]');
        const go = newBox.querySelector('[data-go]');
        const msg = newBox.querySelector('[data-msg]');
        const bar = newBox.querySelector('[data-progress]');
        let items = [];

        const render = () => {
            pick.hidden = !items.length;
            rows.replaceChildren(...items.map(it => el('tr', { class: it.type ? '' : 'is-skip' },
                el('td', { class: 'pl-mono rd-name', title: it.file.name, text: it.file.name }),
                el('td', {}, it.type ? el('span', { class: 'rd-type is-' + it.type.toLowerCase(), text: it.type }) : el('span', { class: 'pl-faint', text: it.why })),
                el('td', { text: it.h.OBJECT || '—' }), el('td', { text: it.h.FILTER || '—' }),
                el('td', { text: typeof it.h.EXPTIME === 'number' ? it.h.EXPTIME + ' s' : '—' }),
                el('td', { class: 'rd-num', text: sizeText(it.file.size) }))));
            const ok = items.filter(it => it.type);
            const count = t => ok.filter(it => it.type === t).length;
            const parts = [plural(count('Science'), 'science frame')];
            for (const t of ['Bias', 'Dark', 'Flat']) if (count(t)) parts.push(count(t) + ' ' + t.toLowerCase());
            if (items.length > ok.length) parts.push(items.length - ok.length + ' skipped');
            newBox.querySelector('[data-pick-sum]').textContent = parts.join(' · ');
            go.disabled = !count('Science');
            say(msg, items.length && !count('Science') ? 'Add at least one science (Light) frame.' : '');
        };

        dropZone(newBox.querySelector('[data-pl-drop]'), async files => {
            const seen = new Set(items.map(it => it.file.name));
            for (const f of files) {
                if (seen.has(f.name) || f.name.startsWith('.')) continue;
                seen.add(f.name);
                const it = { file: f, h: {}, type: '', why: '' };
                if (!FITS_RE.test(f.name)) it.why = 'Not .fits / .fit / .fts';
                else {
                    it.h = await readHeader(f);
                    const t = String(it.h.IMAGETYP || '').trim().toLowerCase();
                    it.type = TYPE[t] || '';
                    if (!it.type) it.why = t ? 'IMAGETYP ' + it.h.IMAGETYP : 'No IMAGETYP';
                }
                items.push(it);
            }
            render();
        });
        newBox.querySelector('[data-pick-clear]').addEventListener('click', () => { items = []; render(); });

        go.addEventListener('click', async () => {
            const list = items.filter(it => it.type);
            go.disabled = true;
            try {
                const made = await api(API + '/new', {});
                const base = API + '/' + encodeURIComponent(made.id);
                const total = list.reduce((a, it) => a + it.file.size, 0) || 1;
                let sent = 0;
                const failed = [];
                bar.hidden = false;
                for (let k = 0; k < list.length; k++) {
                    const start = sent;
                    const show = () => {
                        bar.querySelector('.pl-bar > span').style.width = Math.min(100, Math.round(sent / total * 100)) + '%';
                        bar.querySelector('small').textContent = 'Uploading ' + (k + 1) + ' of ' + list.length + ' · ' + sizeText(sent) + ' of ' + sizeText(total);
                    };
                    show();
                    try { await uploadFile(base, list[k].file, n => { sent = start + n; show(); }); }
                    catch (err) { failed.push(list[k].file.name + ': ' + err.message); sent = start + list[k].file.size; }
                }
                if (failed.length === list.length) throw new Error(failed[0]);
                say(msg, failed.length ? plural(failed.length, 'frame') + ' not uploaded: ' + failed[0] : 'Starting the reduction…', failed.length ? 'error' : 'ok');
                try { await api(base + '/run', {}); } catch (err) { say(msg, err.message, 'error'); }
                setTimeout(() => { location.href = made.url; }, failed.length ? 2500 : 300);
            } catch (err) {
                say(msg, err.message, 'error');
                go.disabled = false;
            }
        });
    }

    // ── Batch page ──
    const page = $('rdBatch');
    if (!page) return;
    const base = API + '/' + encodeURIComponent(page.dataset.bid);
    const msg = $('rdMsg');
    const logBox = $('rdLog');
    let offset = 0, timer = null, last = null, seeded = false;
    const ticked = new Set();

    const STEP_ICON = { done: '✓', failed: '✕', skipped: '–', running: '', pending: '' };
    const REASON = { no_solution: 'no solution', cpu_limit: 'CPU limit', timeout: 'took too long' };

    function stateChip(status) {
        const label = { running: 'Running', done: 'Done', stopped: 'Stopped', failed: 'Failed' }[status];
        if (!label) return el('span', { class: 'kw-chip', text: 'Not run' });
        return el('span', { class: 'kw-chip' + ({ running: ' kw-chip-blue', done: ' kw-chip-green', failed: ' kw-chip-red' }[status] || '') },
            status === 'running' ? el('span', { class: 'pl-pulse', 'aria-hidden': 'true' }) : null, label);
    }

    function renderSteps(p, status) {
        const steps = p.steps || [];
        $('rdSteps').replaceChildren(...(steps.length ? steps : [{ label: 'Not reduced yet', status: 'pending' }]).map(s => {
            const t = s.started && s.ended ? secs(s.ended - s.started) : s.started && s.status === 'running' ? secs(Date.now() / 1000 - s.started) : '';
            const st = status !== 'running' && s.status === 'running' ? 'failed' : s.status;
            return el('li', { class: 'rd-step is-' + st },
                el('span', { class: 'rd-step-dot', 'aria-hidden': 'true', text: STEP_ICON[st] || '' }),
                el('span', { class: 'rd-step-label', text: s.label }),
                el('span', { class: 'rd-step-note', text: [s.note, t].filter(Boolean).join(' · ') }));
        }));
        const a = p.astrometry || [];
        const solved = a.filter(x => x.status === 'solved').length;
        $('rdStepMeta').textContent = a.length ? solved + ' of ' + a.length + ' solved' : '';
        const probs = p.problems || [];
        const err = p.error && status !== 'stopped' ? el('p', { class: 'pl-warn', text: p.error }) : null;
        $('rdProblems').replaceChildren(err || '', probs.length ? el('div', { class: 'rd-problems' },
            el('b', { text: plural(probs.length, 'problem') }),
            el('ul', {}, probs.map(x => el('li', {}, el('span', { class: 'pl-mono', text: x.name }), el('span', { text: x.why }))))) : '');
    }

    function renderResults(results, p) {
        const box = $('rdResults');
        const frames = results.filter(r => !r.master), masters = results.filter(r => r.master);
        $('rdSend').hidden = !frames.length;
        $('rdResMeta').textContent = frames.length ? plural(frames.length, 'frame') + (masters.length ? ' · ' + plural(masters.length, 'master') : '') : '';
        if (!results.length) return;
        if (!seeded && frames.length) { frames.forEach(r => ticked.add(r.name)); seeded = true; }   // all ticked at first
        const fileUrl = name => location.pathname + '/file/' + name.split('/').map(encodeURIComponent).join('/');
        const all = el('input', { type: 'checkbox', 'aria-label': 'Select all frames' });
        all.checked = frames.length && frames.every(r => ticked.has(r.name));
        all.addEventListener('change', () => { frames.forEach(r => all.checked ? ticked.add(r.name) : ticked.delete(r.name)); renderResults(results, p); });
        const row = r => {
            const a = r.astrometry || {};
            const cb = r.master ? '' : el('input', { type: 'checkbox', 'aria-label': 'Select ' + r.name, checked: ticked.has(r.name) });
            if (cb) cb.addEventListener('change', () => { cb.checked ? ticked.add(r.name) : ticked.delete(r.name); all.checked = frames.every(x => ticked.has(x.name)); });
            const wcs = r.master ? el('span', { class: 'pl-faint', text: 'Master' })
                : r.solved ? el('span', { class: 'rd-wcs is-ok', title: a.how ? 'Solved (' + a.how + ' search)' : 'Solved', text: a.pixscale ? a.pixscale.toFixed(3) + '″/px' : 'WCS' })
                    : el('span', { class: 'rd-wcs is-bad', text: 'No WCS' + (a.reason ? ' · ' + (REASON[a.reason] || a.reason) : '') });
            return el('tr', {}, el('td', { class: 'rd-cb' }, cb), el('td', { class: 'pl-mono rd-name', title: r.name, text: r.name }),
                el('td', {}, wcs), el('td', { class: 'rd-num pl-mono', text: a.ra != null ? a.ra.toFixed(4) + ' ' + a.dec.toFixed(4) : '' }),
                el('td', { class: 'rd-num', text: sizeText(r.size) }),
                el('td', { class: 'rd-num' }, el('a', { class: 'kw-btn kw-btn-sm kw-btn-ghost', href: fileUrl(r.name), download: '', text: 'Download' })));
        };
        box.replaceChildren(el('div', { class: 'rd-table-wrap' }, el('table', { class: 'rd-table rd-results' },
            el('thead', {}, el('tr', {}, el('th', { class: 'rd-cb' }, frames.length ? all : ''), el('th', { text: 'Frame' }), el('th', { text: 'Astrometry' }),
                el('th', { class: 'rd-num', text: 'Centre RA Dec (°)' }), el('th', { class: 'rd-num', text: 'Size' }), el('th', {}))),
            el('tbody', {}, frames.map(row), masters.map(row)))));
    }

    function render(d) {
        const status = d.job.status || '';
        $('rdState').replaceChildren(stateChip(status));
        const running = status === 'running';
        $('rdRun').hidden = running;
        $('rdRun').textContent = status ? 'Reduce again' : 'Reduce';
        $('rdStop').hidden = !running;
        $('rdDelete').hidden = running;
        renderSteps(d.progress || {}, status);
        if (!running || (d.results || []).length !== (last && last.results ? last.results.length : -1)) renderResults(d.results || [], d.progress || {});
        if (d.summary) { $('rdExpires').dataset.left = d.summary.expires; stamp(page); }
        if (d.reset) logBox.textContent = '';
        if (d.log) {
            const atEnd = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 30;
            logBox.textContent += d.log;
            if (logBox.textContent.length > 400000) logBox.textContent = logBox.textContent.slice(-300000);
            if (atEnd) logBox.scrollTop = logBox.scrollHeight;
        }
        offset = d.offset || offset;
        last = d;
        clearTimeout(timer);
        if (running) timer = setTimeout(poll, 3000);
    }

    async function poll() {
        try { render(await api(base + '/job?offset=' + offset)); }
        catch (err) { say(msg, err.message, 'error'); clearTimeout(timer); timer = setTimeout(poll, 10000); }
    }

    const initial = JSON.parse(($('rdInitial') || {}).textContent || 'null');
    if (initial) { offset = 0; initial.offset = initial.offset || 0; render(initial); logBox.scrollTop = logBox.scrollHeight; }

    $('rdRun').addEventListener('click', async () => {
        $('rdRun').disabled = true;
        try {
            await api(base + '/run', {});
            say(msg, '');
            ticked.clear();
            seeded = false;
            last = null;
            logBox.textContent = '';
            offset = 0;
            await poll();
        } catch (err) { say(msg, err.message, 'error'); }
        finally { $('rdRun').disabled = false; }
    });
    armable($('rdStop'), 'Click again to stop', async () => {
        try { await api(base + '/stop', {}); say(msg, 'Stopping…'); setTimeout(poll, 1500); }
        catch (err) { say(msg, err.message, 'error'); }
    });
    armable($('rdDelete'), 'Click again to delete', async () => {
        try { const r = await api(base + '/delete', {}); location.href = r.url; }
        catch (err) { say(msg, err.message, 'error'); }
    });

    const wsSel = $('rdWs'), wsName = $('rdWsName');
    const syncName = () => { wsName.hidden = !!wsSel.value; };
    wsSel.addEventListener('change', syncName);
    syncName();
    $('rdSendGo').addEventListener('click', async () => {
        const names = [...ticked];
        if (!names.length) { say(msg, 'Tick at least one frame to send.', 'error'); return; }
        $('rdSendGo').disabled = true;
        say(msg, 'Copying ' + plural(names.length, 'frame') + ' to AutoPhOT…');
        try {
            const r = await api(base + '/send', { names, workspace: wsSel.value, name: wsName.value.trim() });
            say(msg, plural(r.added.length, 'frame') + ' copied' + (r.skipped.length ? ', ' + r.skipped.length + ' already there' : '') + '. Opening the workspace…', 'ok');
            setTimeout(() => { location.href = r.url; }, 700);
        } catch (err) {
            say(msg, err.message, 'error');
            $('rdSendGo').disabled = false;
        }
    });
})();
