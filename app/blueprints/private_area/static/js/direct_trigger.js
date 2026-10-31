// Direct Trigger — tonight's change of plan (see app/blueprints/private_area/direct_trigger.py).
// All server data is rendered with textContent; nothing is built from HTML strings.
(function () {
    'use strict';

    const page = document.getElementById('dtPage');
    if (!page) return;
    const FILTERS = (page.dataset.filters || 'up,gp,rp,ip,zp').split(',');
    const TEL_KEY = 'kinder.directTrigger.telescope';
    const CONFIRM_MS = 5000;
    // tonight's Lulin schedule closes LOT to triggers (lab_calendar.lot_closed); the server refuses LOT sends too
    const LOT_CLOSED = page.dataset.lotClosed || '';
    const LOT_CLOSED_MSG = `No LOT trigger tonight (Lulin schedule: ${LOT_CLOSED}). Send SLT only.`;
    const lotShut = () => state.tel === 'LOT' && !!LOT_CLOSED;

    const $ = id => document.getElementById(id);
    const state = { tel: 'SLT', mode: 'auto', lists: { SLT: [], LOT: [] }, scriptFor: null, loaded: false };
    try { if (localStorage.getItem(TEL_KEY) === 'LOT') state.tel = 'LOT'; } catch (e) { /* storage blocked */ }

    // ── helpers ─────────────────────────────────────────────────────────────
    async function api(url, options) {
        const resp = await fetch(url, Object.assign({ credentials: 'same-origin' }, options || {}));
        let data = {};
        try { data = await resp.json(); } catch (e) { /* non-JSON error page */ }
        if (!resp.ok || data.success === false) {
            throw new Error(data.error || `Request failed (${resp.status}).`);
        }
        return data;
    }
    const postJson = (url, body) => api(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });

    function el(tag, props, ...children) {
        const node = document.createElement(tag);
        Object.entries(props || {}).forEach(([k, v]) => {
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
            else node.setAttribute(k, v);
        });
        children.flat().forEach(c => node.append(c instanceof Node ? c : document.createTextNode(String(c))));
        return node;
    }

    function setMsg(node, text, kind) {
        node.textContent = text || '';
        node.classList.toggle('is-error', kind === 'error');
        node.classList.toggle('is-ok', kind === 'ok');
    }

    function fmtTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Two-step buttons: first press arms, second press within CONFIRM_MS acts.
    function armable(button, armedLabel, action) {
        let timer = null;
        const original = () => button.dataset.label;
        button.addEventListener('click', async () => {
            if (!button.classList.contains('is-armed')) {
                button.dataset.label = button.innerHTML;
                button.classList.add('is-armed');
                button.textContent = armedLabel();
                timer = setTimeout(() => { button.classList.remove('is-armed'); button.innerHTML = original(); }, CONFIRM_MS);
                return;
            }
            clearTimeout(timer);
            button.classList.remove('is-armed');
            button.innerHTML = original();
            await action();
        });
    }

    // ── telescope scope ─────────────────────────────────────────────────────
    function applyScope() {
        document.querySelectorAll('.dt-scope [data-tel]').forEach(b => {
            const on = b.dataset.tel === state.tel;
            b.classList.toggle('is-on', on);
            b.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        document.querySelectorAll('[data-tel-label]').forEach(n => { n.textContent = state.tel; });
        $('dtProgramField').hidden = state.tel !== 'LOT';
        try { localStorage.setItem(TEL_KEY, state.tel); } catch (e) { /* ignore */ }
        resetScript();
        renderList();
    }
    document.querySelectorAll('.dt-scope [data-tel]').forEach(b => b.addEventListener('click', () => {
        state.tel = b.dataset.tel;
        applyScope();
    }));

    // ── exposure mode + filter rows ─────────────────────────────────────────
    function setMode(mode) {
        state.mode = mode;
        document.querySelectorAll('.dt-exp-mode [data-mode]').forEach(b => {
            const on = b.dataset.mode === mode;
            b.classList.toggle('is-on', on);
            b.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        $('dtFilters').hidden = mode !== 'manual';
        $('dtAutoHint').hidden = mode !== 'auto';
        if (mode === 'manual' && !$('dtFilterRows').children.length) addFilterRow('rp');
    }
    document.querySelectorAll('.dt-exp-mode [data-mode]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));

    function addFilterRow(filter) {
        const rows = $('dtFilterRows');
        if (!rows.children.length) {
            rows.append(el('div', { class: 'dt-filter-head', 'aria-hidden': 'true' },
                el('span', { text: 'Filter' }), el('span', { text: 'Exp (s)' }), el('span', { text: 'Count' }), el('span')));
        }
        const select = el('select', { class: 'kw-select kw-select-sm', 'aria-label': 'Filter' },
            FILTERS.map(f => el('option', { value: f, text: f })));
        select.value = filter || 'rp';
        const row = el('div', { class: 'dt-filter-row' },
            select,
            el('input', { type: 'number', min: '1', max: '3600', value: '300', 'aria-label': 'Exposure in seconds' }),
            el('input', { type: 'number', min: '1', max: '50', value: '1', 'aria-label': 'Count' }),
            el('button', { type: 'button', class: 'kw-icon-btn is-danger', 'aria-label': 'Remove filter', text: '×',
                onclick: () => { row.remove(); if (rows.children.length === 1) rows.replaceChildren(); } }));
        rows.append(row);
    }
    $('dtAddFilter').addEventListener('click', () => addFilterRow('gp'));

    // ── name autocomplete (database objects) ────────────────────────────────
    let suggestTimer = null;
    let suggestions = [];
    const suggestBox = $('dtSuggest');
    function hideSuggest() { suggestBox.hidden = true; suggestBox.replaceChildren(); suggestions = []; }
    function pickSuggestion(s) {
        $('dtName').value = s.name;
        $('dtRa').value = s.ra;
        $('dtDec').value = s.dec;
        if (s.mag && !$('dtMag').value) $('dtMag').value = s.mag;
        hideSuggest();
        $('dtMag').focus();
    }
    $('dtName').addEventListener('input', e => {
        clearTimeout(suggestTimer);
        const q = e.target.value.trim();
        if (q.length < 3) { hideSuggest(); return; }
        suggestTimer = setTimeout(async () => {
            try {
                const resp = await fetch('/api/target_autocomplete?q=' + encodeURIComponent(q), { credentials: 'same-origin' });
                suggestions = resp.ok ? await resp.json() : [];
            } catch (err) { suggestions = []; }
            suggestBox.replaceChildren(...suggestions.slice(0, 8).map((s, i) => el('li',
                { role: 'option', 'data-i': String(i), onmousedown: ev => { ev.preventDefault(); pickSuggestion(s); } },
                el('span', { text: s.name }), el('small', { text: `${s.ra}  ${s.dec}` }))));
            suggestBox.hidden = !suggestions.length;
        }, 220);
    });
    $('dtName').addEventListener('blur', () => setTimeout(hideSuggest, 150));
    $('dtName').addEventListener('keydown', e => {
        if (e.key === 'Escape') hideSuggest();
        if (e.key === 'Enter' && !suggestBox.hidden && suggestions.length) { e.preventDefault(); pickSuggestion(suggestions[0]); }
    });

    // ── add target ──────────────────────────────────────────────────────────
    $('dtForm').addEventListener('submit', async e => {
        e.preventDefault();
        const msg = $('dtFormMsg');
        const body = {
            telescope: state.tel,
            name: $('dtName').value.trim(),
            mag: $('dtMag').value.trim(),
            ra: $('dtRa').value.trim(),
            dec: $('dtDec').value.trim(),
            priority: $('dtPriority').value,
            repeat_count: $('dtRepeat').value,
            program: state.tel === 'LOT' ? $('dtProgram').value.trim() : '',
            note: $('dtNote').value.trim(),
            auto_exp: state.mode === 'auto',
            filters: state.mode === 'manual'
                ? Array.from(document.querySelectorAll('.dt-filter-row')).map(r => {
                    const [sel, exp, count] = r.querySelectorAll('select, input');
                    return { filter: sel.value, exp: exp.value, count: count.value };
                })
                : [],
        };
        if (!body.name || !body.ra || !body.dec) { setMsg(msg, 'Target, RA and Dec are required.', 'error'); return; }
        const submit = $('dtSubmit');
        submit.disabled = true;
        setMsg(msg, 'Adding…');
        try {
            const data = await postJson('/api/direct_trigger/targets', body);
            state.lists[state.tel].push(data.target);
            setMsg(msg, `${data.target.name} added to ${state.tel}.`, 'ok');
            ['dtName', 'dtMag', 'dtRa', 'dtDec', 'dtNote'].forEach(id => { $(id).value = ''; });
            $('dtRepeat').value = '0';
            $('dtPriority').value = 'Normal';
            resetScript();
            renderList();
            $('dtName').focus();
        } catch (err) {
            setMsg(msg, err.message, 'error');
        } finally {
            submit.disabled = false;
        }
    });

    // ── list ────────────────────────────────────────────────────────────────
    function exposureText(t) {
        if (t.auto_exp) return `Auto (mag ${t.mag || '?'})`;
        return (t.filters || []).map(f => `${f.filter} ${f.exp}s×${f.count}`).join(', ');
    }

    function renderList() {
        const list = state.lists[state.tel] || [];
        ['SLT', 'LOT'].forEach(tel => {
            const n = document.querySelector(`[data-count="${tel}"]`);
            if (n) n.textContent = String((state.lists[tel] || []).length);
        });
        const body = $('dtListBody');
        const lastSent = list.map(t => t.last_sent_at).filter(Boolean).sort().pop();
        $('dtListMeta').textContent = list.length
            ? `${list.length} target${list.length === 1 ? '' : 's'}${lastSent ? ` · last sent ${fmtTime(lastSent)}` : ''}`
            : '';
        $('dtClear').hidden = !list.length;
        $('dtPreview').disabled = !list.length;

        if (!state.loaded) return;   // keep the skeleton until the first load finishes
        if (!list.length) {
            body.replaceChildren(el('div', { class: 'dt-empty' },
                el('b', { text: `No ${state.tel} targets for tonight yet` }),
                'Add one with the form. The Daily Trigger list is not affected.'));
            return;
        }
        const rows = list.map(t => el('tr', {},
            el('td', {}, el('span', { class: 'dt-name', text: t.name }),
                el('span', { class: 'dt-sub', text: [t.program, t.note].filter(Boolean).join(' · ') })),
            el('td', {}, el('span', { text: t.ra }), el('span', { class: 'dt-sub', text: t.dec })),
            el('td', { text: exposureText(t) + (t.repeat_count ? ` · repeat ${t.repeat_count}` : '') }),
            el('td', {}, el('span', { class: `kw-chip dt-prio-${t.priority}`, text: t.priority })),
            el('td', {}, el('button', {
                type: 'button', class: 'kw-icon-btn is-danger', 'aria-label': `Remove ${t.name}`, text: '×',
                onclick: () => removeTarget(t),
            }))));
        body.replaceChildren(el('div', { class: 'kw-table-wrap' },
            el('table', { class: 'kw-table dt-table' },
                el('thead', {}, el('tr', {}, ['Target', 'RA / Dec', 'Exposure', 'Priority', ''].map(h => el('th', { scope: 'col', text: h })))),
                el('tbody', {}, rows))));
    }

    async function removeTarget(t) {
        try {
            await api(`/api/direct_trigger/targets/${encodeURIComponent(t.id)}`, { method: 'DELETE' });
            state.lists[t.telescope] = state.lists[t.telescope].filter(x => x.id !== t.id);
            resetScript();
            renderList();
        } catch (err) {
            setMsg($('dtSendMsg'), err.message, 'error');
        }
    }

    armable($('dtClear'), () => `Clear all ${state.tel}?`, async () => {
        try {
            await postJson('/api/direct_trigger/clear', { telescope: state.tel });
            state.lists[state.tel] = [];
            resetScript();
            renderList();
        } catch (err) {
            setMsg($('dtSendMsg'), err.message, 'error');
        }
    });

    async function loadLists() {
        try {
            const data = await api('/api/direct_trigger/targets');
            state.lists = { SLT: [], LOT: [] };
            (data.targets || []).forEach(t => { (state.lists[t.telescope] = state.lists[t.telescope] || []).push(t); });
            state.loaded = true;
        } catch (err) {
            $('dtListBody').replaceChildren(el('div', { class: 'dt-empty' }, el('b', { text: 'Could not load the list' }), err.message));
            return;
        }
        renderList();
    }

    // ── script & send ───────────────────────────────────────────────────────
    function resetScript() {
        state.scriptFor = null;
        $('dtScript').value = '';
        $('dtSend').disabled = true;
        $('dtCopy').disabled = true;
        setMsg($('dtSendMsg'), lotShut() ? LOT_CLOSED_MSG : '', lotShut() ? 'error' : undefined);
    }

    $('dtPreview').addEventListener('click', async () => {
        const btn = $('dtPreview');
        btn.disabled = true;
        setMsg($('dtSendMsg'), 'Building…');
        try {
            const data = await postJson('/api/direct_trigger/preview', { telescope: state.tel });
            $('dtScript').value = data.greeting + data.script;
            state.scriptFor = state.tel;
            $('dtCopy').disabled = false;
            if (lotShut()) {
                setMsg($('dtSendMsg'), LOT_CLOSED_MSG, 'error');
            } else {
                $('dtSend').disabled = false;
                setMsg($('dtSendMsg'), `${data.count} target${data.count === 1 ? '' : 's'} ready. Press Send twice to confirm.`);
            }
        } catch (err) {
            setMsg($('dtSendMsg'), err.message, 'error');
        } finally {
            btn.disabled = !(state.lists[state.tel] || []).length;
        }
    });

    $('dtCopy').addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText($('dtScript').value);
            setMsg($('dtSendMsg'), 'Script copied.', 'ok');
        } catch (err) {
            $('dtScript').select();
            setMsg($('dtSendMsg'), 'Select the text and copy it manually.', 'error');
        }
    });

    armable($('dtSend'), () => `Confirm: send ${(state.lists[state.tel] || []).length} to ${state.tel}`, async () => {
        if (state.scriptFor !== state.tel) { setMsg($('dtSendMsg'), 'Build the script first.', 'error'); return; }
        const btn = $('dtSend');
        btn.disabled = true;
        setMsg($('dtSendMsg'), `Sending to ${state.tel}…`);
        try {
            const data = await postJson('/api/direct_trigger/send', { telescope: state.tel });
            const warn = (data.log_warnings || []).length ? ` Observation Log: ${data.log_warnings.join('; ')}` : '';
            setMsg($('dtSendMsg'), `Sent ${data.sent} target${data.sent === 1 ? '' : 's'} to ${state.tel}.${warn}`, warn ? 'error' : 'ok');
            await loadLists();
        } catch (err) {
            setMsg($('dtSendMsg'), err.message, 'error');
        } finally {
            btn.disabled = state.scriptFor !== state.tel || lotShut();
        }
    });

    setMode('auto');
    applyScope();
    loadLists();
})();
