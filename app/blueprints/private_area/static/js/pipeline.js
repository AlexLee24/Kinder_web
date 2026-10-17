/* Pipeline (AutoPhOT): workspace form, header check, run / stop / answer, images, all settings, export. */
(function () {
    'use strict';

    const API = '/api/pipeline/autophot';
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
        for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid);
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

    const page = $('plWorkspace');
    const tid = page ? page.dataset.tid : '';
    const base = tid ? API + '/' + encodeURIComponent(tid) : '';
    let overrides = null;            // All settings: {key: one line of YAML}, only values that differ from the default

    // ── Uploads: each FITS goes up in pieces under the server's request limit ──
    const CHUNK = parseInt((document.querySelector('[data-chunk]') || {}).dataset?.chunk, 10) || 8 * 1024 * 1024;
    const FITS_RE = /\.(fits|fit|fts)(\.fz|\.gz)?$/i;

    function sizeText(n) {
        return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' kB';
    }

    async function uploadFile(wsBase, file, onProgress, template) {
        let offset = 0;
        do {
            const piece = file.slice(offset, offset + CHUNK);
            const q = new URLSearchParams({ name: file.name, offset: String(offset), total: String(file.size) });
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
            if (onProgress) onProgress(offset / file.size);
            if (data.done) return data.name;
        } while (offset < file.size);
        throw new Error('Upload did not finish.');
    }

    // Drop zone: keeps a list of chosen files with a row (name, size, progress, remove) for each.
    function dropZone(root, onAdd) {
        const input = root.querySelector('.pl-drop-input');
        const zone = root.querySelector('.pl-drop-zone');
        const list = root.querySelector('.pl-files');
        const items = [];
        function add(files) {
            for (const file of files) {
                if (items.some(it => it.file.name === file.name && it.state !== 'done')) continue;
                const bar = el('span', { class: 'pl-bar' }, el('span'));
                const note = el('small', { text: FITS_RE.test(file.name) ? sizeText(file.size) : 'Not a FITS file' });
                const item = { file, state: FITS_RE.test(file.name) ? 'queued' : 'bad' };
                const rm = el('button', { type: 'button', class: 'kw-icon-btn', 'aria-label': 'Remove ' + file.name, text: '×',
                    onclick: () => { if (item.state === 'sending') return; items.splice(items.indexOf(item), 1); item.row.remove(); list.hidden = !items.length; } });
                item.row = el('li', { class: item.state === 'bad' ? 'is-bad' : null }, el('span', { class: 'pl-mono', text: file.name }), note, bar, rm);
                item.set = (state, text, frac) => {
                    item.state = state;
                    item.row.className = 'is-' + state;
                    if (text != null) note.textContent = text;
                    if (frac != null) bar.firstChild.style.width = Math.round(frac * 100) + '%';
                    rm.hidden = state === 'sending' || state === 'done';
                };
                items.push(item);
                list.append(item.row);
            }
            list.hidden = !items.length;
            if (onAdd) onAdd(items);
        }
        input.addEventListener('change', () => { add(input.files); input.value = ''; });
        ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add('is-over'); }));
        ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, () => zone.classList.remove('is-over')));
        zone.addEventListener('drop', e => { e.preventDefault(); add(e.dataTransfer.files); });
        return {
            items,
            async send(wsBase) {
                let ok = 0, failed = 0;
                for (const it of items) {
                    if (it.state !== 'queued' && it.state !== 'error') continue;
                    it.set('sending', '0%', 0);
                    try {
                        await uploadFile(wsBase, it.file, f => it.set('sending', Math.round(f * 100) + '%', f));
                        it.set('done', 'Uploaded', 1);
                        ok++;
                    } catch (err) { it.set('error', err.message); failed++; }
                }
                return { ok, failed };
            },
        };
    }

    // ── Workspace form ────────────────────────────────────────────────────────
    function formBody(form) {
        const f = form.elements;
        const b = {
            name: f.name.value.trim(), ra: f.ra.value.trim(), dec: f.dec.value.trim(),
            catalog: f.catalog.value, ncpu: parseInt(f.ncpu.value, 10) || 1,
            stack: f.stack.checked, stack_with_singles: f.stack_with_singles.checked,
            stack_align: f.stack_align.value, stack_combine: f.stack_combine.value, stack_sigma: parseFloat(f.stack_sigma.value) || 3,
            subtraction: f.subtraction.checked, sub_method: f.sub_method.value, ts_download: f.ts_download.value,
            ts_size: parseFloat(f.ts_size.value) || 10, ts_align: f.ts_align.value, ts_forceconv: f.ts_forceconv.value,
        };
        if (overrides) b.overrides = overrides;
        return b;
    }

    document.querySelectorAll('[data-pl-form]').forEach(form => {
        const editing = !!form.dataset.tid;
        const msg = form.querySelector('.pl-msg');

        ['stack', 'subtraction'].forEach(k => {
            const box = form.elements[k];
            const sync = () => form.querySelectorAll('[data-show-if="' + k + '"]').forEach(n => { n.hidden = !box.checked; });
            box.addEventListener('change', sync);
            sync();
        });

        const dropRoot = form.querySelector('[data-pl-drop]');
        const drop = dropRoot ? dropZone(dropRoot) : null;
        let created = null;              // {id, url} once the workspace exists; a retry only uploads
        form.addEventListener('submit', async e => {
            e.preventDefault();
            const btn = form.querySelector('button[type=submit]');
            if (!editing && !created && !drop.items.some(it => it.state === 'queued')) {
                say(msg, 'Add at least one FITS image.', 'error');
                return;
            }
            btn.disabled = true;
            try {
                if (editing) {
                    say(msg, 'Saving…');
                    await api(base + '/save', formBody(form));
                    say(msg, 'Saved.', 'ok');
                    if (window.plReloadImages) window.plReloadImages();
                } else {
                    if (!created) {
                        say(msg, 'Creating the workspace…');
                        created = await api(API + '/new', formBody(form));
                        form.querySelectorAll('input[name], select[name]').forEach(n => { n.disabled = true; });
                    }
                    say(msg, 'Uploading…');
                    const r = await drop.send(API + '/' + encodeURIComponent(created.id));
                    if (!r.failed) { location.href = created.url; return; }
                    say(msg, r.failed + ' file' + (r.failed === 1 ? '' : 's') + ' failed. Fix or remove them and press the button again, or open the workspace.', 'error');
                    btn.textContent = 'Retry upload';
                    if (!form.querySelector('.pl-open-ws')) {
                        btn.after(el('a', { class: 'kw-btn kw-btn-ghost pl-open-ws', href: created.url, text: 'Open workspace' }));
                    }
                }
            } catch (err) { say(msg, err.message, 'error'); }
            btn.disabled = false;
        });

        // Name → Kinder objects (autocomplete), or CDS Sesame with Look up
        const name = form.elements.name;
        const box = form.querySelector('.pl-suggest');
        let timer = null, items = [];
        const hide = () => { box.hidden = true; box.replaceChildren(); items = []; };
        const pick = s => { name.value = s.name; form.elements.ra.value = s.ra; form.elements.dec.value = s.dec; hide(); };
        name.addEventListener('input', () => {
            clearTimeout(timer);
            const q = name.value.trim();
            if (q.length < 3) { hide(); return; }
            timer = setTimeout(async () => {
                try {
                    const r = await fetch('/api/target_autocomplete?q=' + encodeURIComponent(q), { credentials: 'same-origin' });
                    items = r.ok ? await r.json() : [];
                } catch (err) { items = []; }
                if (!Array.isArray(items)) items = [];
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
            } catch (err) { say(msg, err.message, 'error'); }
            btn.disabled = false;
        });

    });

    const HEADER_KEYS = ['TELESCOP', 'INSTRUME', 'FILTER', 'DATE-OBS', 'EXPTIME'];

    function headerTable(files, rowExtra) {
        if (!files.length) return el('p', { class: 'pl-faint', text: 'No FITS here.' });
        return el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table pl-table pl-hdr' },
            el('thead', {}, el('tr', {}, el('th', { text: 'File' }), HEADER_KEYS.map(k => el('th', { text: k })), rowExtra ? el('th') : null)),
            el('tbody', {}, files.map(f => el('tr', {},
                el('td', { class: 'pl-mono' }, f.name, f.stack ? el('span', { class: 'kw-chip kw-chip-gold', text: 'stack' }) : null),
                f.error ? el('td', { class: 'is-miss', colspan: '5', text: f.error })
                    : HEADER_KEYS.map(k => {
                        const required = k !== 'DATE-OBS' && k !== 'EXPTIME';
                        return el('td', { class: !f[k] && required ? 'is-miss' : null, text: f[k] || (required ? 'missing' : '—') });
                    }),
                rowExtra ? el('td', { class: 'pl-acts' }, rowExtra(f)) : null)))));
    }

    // ── Images in the workspace ───────────────────────────────────────────────
    const imgBody = $('plImgBody');
    if (imgBody) {
        const load = async () => {
            try {
                const d = await api(base + '/images');
                $('plImgCount').textContent = d.n + ' FITS';
                d.files.forEach(f => { f.stack = d.stacks.indexOf(f.name) >= 0; });
                const parts = [];
                if (d.missing) parts.push(el('p', { class: 'pl-warn', text: d.missing + ' frame' + (d.missing === 1 ? '' : 's') + ' missing TELESCOP / INSTRUME / FILTER; AutoPhOT skips them.' }));
                if (d.n_sub) parts.push(el('p', { class: 'pl-hint', text: d.n_sub + ' in subfolders, skipped.' }));
                parts.push(headerTable(d.files, f => f.stack ? null : removeButton(f.name)));
                if (d.templates.length) {
                    parts.push(el('h3', { class: 'pl-sub', text: 'Templates' }), el('ul', { class: 'pl-tpl-list' },
                        d.templates.map(t => el('li', {}, el('span', { class: 'pl-mono', text: t }), removeButton(t)))));
                }
                if (d.removed.length) {
                    parts.push(el('details', { class: 'pl-removed' },
                        el('summary', { text: d.removed.length + ' removed' }),
                        d.removed.map(r => el('div', {}, el('span', { class: 'pl-mono', text: r }),
                            el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: 'Put back',
                                onclick: async ev => {
                                    ev.currentTarget.disabled = true;
                                    try { await api(base + '/images/restore', { name: r }); load(); }
                                    catch (err) { imgBody.prepend(el('p', { class: 'pl-msg is-error', text: err.message })); }
                                } })))));
                }
                imgBody.replaceChildren(...parts);
            } catch (err) {
                imgBody.replaceChildren(el('p', { class: 'pl-msg is-error', text: err.message }));
            }
        };
        function removeButton(name) {
            const b = el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-ghost', text: 'Remove', title: 'Move out of this workspace (can be put back)' });
            armable(b, 'Confirm', async () => {
                try { await api(base + '/images/remove', { name }); load(); }
                catch (err) { imgBody.prepend(el('p', { class: 'pl-msg is-error', text: err.message })); }
            });
            return b;
        }
        // New images: upload as soon as they are dropped or chosen
        const addRoot = $('plAddFiles');
        if (addRoot) {
            let sending = false;
            const zone = dropZone(addRoot, async () => {
                if (sending) return;
                sending = true;
                while (zone.items.some(it => it.state === 'queued')) await zone.send(base);
                sending = false;
                load();
            });
        }
        const tplBtn = $('plTplSend');
        if (tplBtn) {
            tplBtn.addEventListener('click', async () => {
                const f = $('plTplFile').files[0], filt = $('plTplFilter').value.trim(), m = $('plTplMsg');
                if (!filt || !f) { say(m, 'Enter the filter and choose a FITS file.', 'error'); return; }
                tplBtn.disabled = true;
                try {
                    await uploadFile(base, f, frac => say(m, 'Uploading ' + Math.round(frac * 100) + '%'), filt);
                    say(m, 'Template added.', 'ok');
                    $('plTplFile').value = '';
                    load();
                } catch (err) { say(m, err.message, 'error'); }
                tplBtn.disabled = false;
            });
        }
        window.plReloadImages = load;
        load();
    }

    // ── Run, log, answers, stop ───────────────────────────────────────────────
    const jobBox = $('plJob');
    if (jobBox) {
        const logEl = $('plLog'), stateEl = $('plJobState'), runBtn = $('plRun'), ans = $('plAnswer');
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
            if (head) head.replaceChildren(on ? el('span', { class: 'kw-chip kw-chip-blue' }, el('span', { class: 'pl-pulse', 'aria-hidden': 'true' }), 'Running') : '');
        }
        function show(j) {
            const stick = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
            if (j.log) { logEl.hidden = false; $('plLogFoot').hidden = false; logEl.textContent = j.log; }
            if (stick) logEl.scrollTop = logEl.scrollHeight;
            const isRunning = j.status === 'running';
            if (isRunning !== running) setRunning(isRunning);
            const wasHidden = ans.hidden;
            ans.hidden = !j.waiting;
            if (j.waiting && wasHidden) ans.elements.text.focus();
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
            const form = document.querySelector('[data-pl-form]');
            try {
                if (form) await api(base + '/save', formBody(form));
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
        $('plAllSave').addEventListener('click', () => {
            const form = document.querySelector('[data-pl-form]');
            if (form) form.requestSubmit();
        });
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
