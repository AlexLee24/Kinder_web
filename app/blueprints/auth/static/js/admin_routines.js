// Admin › Routines (/admin/routines): a 24 h strip and agenda of today's fixed times, one row per routine (state, schedule,
// next run, last run, Run now), and for the open routine its steps, recent runs and log. Polls /admin/routines/status
// every 15 s; an open log follows /admin/routines/<id>/log every 3 s. Every time reads "12:00 UTC+8 (04:00 UTC+0)".
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    let data = { routines: [], groups: [] };
    try { data = JSON.parse($('rtInitial').textContent) || data; } catch (e) { /* the first poll fills it */ }
    let open = null, logOffset = null, logTimer = null, statusTimer = null;
    const busy = {};
    const MAX_LOG_CHARS = 400000;
    const H8 = 8 * 3600 * 1000;

    // ── time: always UTC+8 first, UTC+0 in brackets ─────────────────────────
    const pad = (n) => String(n).padStart(2, '0');
    const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    function hm(d) { return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); }
    function both(iso, withDay) {
        if (!iso) return '—';
        const u = new Date(iso);
        if (isNaN(u)) return '—';
        const t8 = new Date(u.getTime() + H8);
        const today8 = new Date(Date.now() + H8);
        const sameDay = t8.getUTCDate() === today8.getUTCDate() && t8.getUTCMonth() === today8.getUTCMonth();
        const day = (withDay || !sameDay) ? MON[t8.getUTCMonth()] + ' ' + t8.getUTCDate() + ' ' : '';
        return day + hm(t8) + ' UTC+8 (' + hm(u) + ' UTC+0)';
    }
    function rel(iso) {
        if (!iso) return '';
        const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
        if (isNaN(s)) return '';
        const a = Math.abs(s);
        const txt = a < 60 ? a + ' s' : a < 3600 ? Math.round(a / 60) + ' min' : a < 86400 ? Math.round(a / 3600) + ' h' : Math.round(a / 86400) + ' d';
        return s > 0 ? 'in ' + txt : txt + ' ago';
    }
    function dur(secs) {
        if (secs == null) return '';
        secs = Math.round(secs);
        if (secs < 60) return secs + ' s';
        if (secs < 3600) return Math.floor(secs / 60) + ' min ' + (secs % 60) + ' s';
        return Math.floor(secs / 3600) + ' h ' + Math.round((secs % 3600) / 60) + ' min';
    }
    function secsBetween(a, b) {
        if (!a || !b) return null;
        return (new Date(b) - new Date(a)) / 1000;
    }

    // ── network ─────────────────────────────────────────────────────────────
    function getJSON(url) {
        return fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' }).then((r) => r.json().then((d) => {
            if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
            return d;
        }));
    }
    function post(url, body) {
        return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
            .then((r) => r.json().then((d) => ({ ok: r.ok && !d.error && d.success !== false, d })));
    }

    // ── 24 h strip + agenda ─────────────────────────────────────────────────
    function marks() {
        const out = [];
        data.routines.forEach((r) => (r.marks || []).forEach((m) => {
            const min8 = ((m[0] + 8) % 24) * 60 + m[1];
            out.push({ r, min8, utc: pad(m[0]) + ':' + pad(m[1]), t8: pad(Math.floor(min8 / 60)) + ':' + pad(min8 % 60) });
        }));
        return out.sort((a, b) => a.min8 - b.min8);
    }
    function renderDay() {
        const n8 = new Date(Date.now() + H8);
        const nowMin = n8.getUTCHours() * 60 + n8.getUTCMinutes();
        $('rtNow').textContent = 'Now ' + both(new Date().toISOString());
        const ms = marks();
        let ticks = '';
        for (let h = 0; h <= 24; h += 3) {
            ticks += '<span class="rt-tick" style="left:' + (h / 24 * 100) + '%"><b>' + pad(h % 24 === 0 && h ? 24 : h) + '</b><i>' + pad((h + 16) % 24) + '</i></span>';
        }
        const dots = ms.map((m) => '<span class="rt-mark' + (m.r.enabled ? '' : ' is-off') + (m.min8 < nowMin ? ' is-past' : '') +
            '" style="left:' + (m.min8 / 1440 * 100) + '%" title="' + esc(m.t8 + ' UTC+8 (' + m.utc + ' UTC+0) · ' + m.r.name) + '"></span>').join('');
        $('rtStrip').innerHTML = '<div class="rt-axis"><span class="rt-axis-l">UTC+8</span><span class="rt-axis-l is-u">UTC+0</span>' +
            '<div class="rt-bar">' + dots + '<span class="rt-nowline" style="left:' + (nowMin / 1440 * 100) + '%"></span></div>' + ticks + '</div>';
        const nextIdx = ms.findIndex((m) => m.min8 >= nowMin && m.r.enabled);
        $('rtAgenda').innerHTML = ms.map((m, i) => '<li class="' + (m.min8 < nowMin ? 'is-past' : '') + (i === nextIdx ? ' is-next' : '') + (m.r.enabled ? '' : ' is-off') + '">' +
            '<time>' + m.t8 + ' <small>UTC+8</small> <span>(' + m.utc + ' UTC+0)</span></time>' +
            '<a href="#' + m.r.id + '" data-open="' + m.r.id + '">' + esc(m.r.name) + '</a>' +
            (i === nextIdx ? '<em>next</em>' : '') + (m.r.enabled ? '' : '<em class="is-off">off</em>') + '</li>').join('');
    }

    // ── rows ────────────────────────────────────────────────────────────────
    function lastRun(r) { return (r.runs || [])[0] || null; }
    function stateOf(r) {
        if (r.running) return ['busy', 'Running'];
        if (!r.enabled) return ['off', data.debug ? 'Off (DEBUG)' : 'Off'];
        const l = lastRun(r);
        if (!l) return ['idle', 'Not run yet'];
        if (l.ok === false) return ['bad', 'Last run failed'];
        if (l.ok == null && !l.finished_at) return ['busy', 'Running'];
        return ['ok', 'OK'];
    }
    function lastText(r) {
        const l = lastRun(r);
        if (!l) return '<span class="bot-muted">—</span>';
        const at = l.finished_at || l.started_at;
        const secs = l.secs != null ? l.secs : secsBetween(l.started_at, l.finished_at);
        const mark = l.ok === false ? '<b class="bot-bad" aria-label="Failed"><svg class="kw-ic-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></b> ' : l.ok ? '<b class="bot-good" aria-label="OK"><svg class="kw-ic-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg></b> ' : '';
        return mark + esc(both(at)) + '<small>' + esc(rel(at)) + (secs != null && l.finished_at ? ' · ' + esc(dur(secs)) : '') +
            (l.manual ? ' · Run now' : '') + '</small>';
    }
    function row(r) {
        const [code, label] = stateOf(r);
        const isOpen = open === r.id;
        const acts = [];
        if (r.can_run) acts.push('<button type="button" class="kw-btn kw-btn-sm kw-btn-tinted" data-run="' + r.id + '"' + (r.running || busy[r.id] ? ' disabled' : '') + '>' + (r.running ? 'Running…' : 'Run now') + '</button>');
        acts.push('<button type="button" class="kw-btn kw-btn-sm" data-open="' + r.id + '" aria-expanded="' + isOpen + '">' + (isOpen ? 'Close' : 'Log') + '</button>');
        return '<div class="rt-row' + (isOpen ? ' is-open' : '') + '" id="rt-' + r.id + '">' +
            '<div class="rt-line">' +
            '<span class="bot-dot is-' + code + '" title="' + esc(label) + '"></span>' +
            '<div class="rt-name"><b>' + esc(r.name) + (r.bot ? ' <span class="kw-chip">Bot</span>' : '') + '</b><small>' + esc(r.when) + '</small></div>' +
            '<div class="rt-cell"><span class="rt-k">Next</span>' + (r.next_run ? esc(both(r.next_run)) + '<small>' + esc(rel(r.next_run)) + '</small>' : '<span class="bot-muted">' + (r.enabled ? (data.debug ? 'Not in DEBUG' : 'By hand') : 'Off') + '</span>') + '</div>' +
            '<div class="rt-cell"><span class="rt-k">Last</span>' + lastText(r) + '</div>' +
            '<div class="rt-acts">' + acts.join('') + '</div>' +
            '</div>' + (isOpen ? '<div class="rt-detail" id="rtDetail"></div>' : '') + '</div>';
    }
    function renderGroups() {
        const keepLog = open && $('rtLog') ? $('rtLog').innerHTML : null;
        const keepScroll = open && $('rtLog') ? $('rtLog').scrollTop : 0;
        $('rtGroups').innerHTML = data.groups.map((g) => {
            const rs = data.routines.filter((r) => r.group === g);
            return '<section class="kw-panel rt-group"><div class="kw-panel-head"><h2>' + esc(g) + '</h2><span class="kw-panel-meta">' + rs.length + '</span></div>' +
                '<div class="rt-list">' + rs.map(row).join('') + '</div></section>';
        }).join('');
        if (open) renderDetail(keepLog, keepScroll);
    }
    function renderTop() {
        const rs = data.routines;
        const bad = rs.filter((r) => r.enabled && stateOf(r)[0] === 'bad').length;
        const run = rs.filter((r) => r.running).length;
        const pill = $('rtState');
        pill.className = 'sys-pill ' + (bad ? 'is-bad' : 'is-ok');
        pill.querySelector('b').textContent = (bad ? bad + ' failed' : 'All fine') + (run ? ' · ' + run + ' running' : '');
    }

    // ── detail ──────────────────────────────────────────────────────────────
    function stepsHtml(r) {
        const l = lastRun(r);
        if (r.bot) {
            return '<p class="bot-muted">A lab bot: its steps, events and settings are on <a href="/admin/bots#' + esc(r.bot) + '">Admin › Bots</a>.</p>';
        }
        const done = {};
        ((l && l.steps) || []).forEach((s) => { done[s.name] = s; });
        return '<ol class="rt-steps">' + r.steps.map((name) => {
            const s = done[name];
            const st = !s ? '' : s.ok === false ? '<b class="bot-bad" aria-label="Failed"><svg class="kw-ic-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></b>' : s.ok ? '<b class="bot-good" aria-label="OK"><svg class="kw-ic-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg></b>' : '<span class="bot-muted">–</span>';
            return '<li>' + st + '<span>' + esc(name) + '</span>' + (s ? '<small>' + esc((s.secs != null ? dur(s.secs) + ' · ' : '') + (s.message || '')) + '</small>' : '') + '</li>';
        }).join('') + '</ol>';
    }
    function historyHtml(r) {
        const runs = r.runs || [];
        if (!runs.length) return '<p class="bot-muted">No runs recorded yet.</p>';
        return '<table class="bot-src-runs rt-runs"><thead><tr><th>Started</th><th>Took</th><th>Result</th></tr></thead><tbody>' + runs.map((l) => {
            const secs = l.secs != null ? l.secs : secsBetween(l.started_at, l.finished_at);
            const res = !l.finished_at ? '<span class="bot-busy">Running</span>' : l.ok === false ? '<span class="bot-bad">Failed</span> ' + esc(l.message || '') : '<span class="bot-good">OK</span> ' + esc(l.message || '');
            return '<tr><td>' + esc(both(l.started_at, true)) + (l.manual ? ' <span class="kw-chip">Run now</span>' : '') + '</td><td>' + (l.finished_at ? esc(dur(secs)) : '') + '</td><td class="bot-wrap">' + res + '</td></tr>';
        }).join('') + '</tbody></table>';
    }
    function renderDetail(keepLog, keepScroll) {
        const r = data.routines.find((x) => x.id === open);
        const box = $('rtDetail');
        if (!r || !box) return;
        box.innerHTML = '<p class="bot-about">' + esc(r.about) + '</p>' +
            '<div class="rt-detail-grid"><div><h3>' + (r.bot ? 'Steps' : 'Steps (last run)') + '</h3>' + stepsHtml(r) + '</div>' +
            '<div><h3>Recent runs</h3>' + historyHtml(r) + '</div></div>' +
            '<div class="bot-log-bar"><h3>Log</h3><label class="bot-check"><input type="checkbox" id="rtFollow" checked> Follow</label>' +
            '<label class="bot-check"><input type="checkbox" id="rtProblems"> Only problems</label><span class="kw-panel-meta" id="rtLogMeta"></span></div>' +
            '<pre class="bot-log rt-log" id="rtLog" tabindex="0" aria-label="' + esc(r.name) + ' log"></pre>';
        $('rtProblems').addEventListener('change', () => $('rtLog').classList.toggle('only-problems', $('rtProblems').checked));
        $('rtFollow').addEventListener('change', () => { if ($('rtFollow').checked) { scrollLog(); pollLog(); } });
        if (keepLog != null) { $('rtLog').innerHTML = keepLog; $('rtLog').scrollTop = keepScroll; }
    }
    function toggle(id) {
        stopLog();
        open = open === id ? null : id;
        logOffset = null;
        history.replaceState(null, '', open ? '#' + open : location.pathname);
        renderGroups();
        if (open) {
            pollLog();
            const el = $('rt-' + open);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    // ── log ─────────────────────────────────────────────────────────────────
    function lineClass(l) {
        if (/ (ERROR|CRITICAL) /.test(l) || /Traceback|Error:| ✗ /.test(l)) return 'lv-err';
        if (/ WARNING /.test(l)) return 'lv-warn';
        if (/ [▶■] /.test(l) || / INFO ── /.test(l)) return 'lv-head';
        return '';
    }
    function appendLog(text, reset) {
        const pre = $('rtLog');
        if (!pre) return;
        if (reset) pre.innerHTML = '';
        if (!text) return;
        pre.insertAdjacentHTML('beforeend', text.split('\n').filter((l) => l !== '').map((l) => '<span class="' + lineClass(l) + '">' + esc(l) + '\n</span>').join(''));
        while (pre.textContent.length > MAX_LOG_CHARS && pre.firstChild) pre.removeChild(pre.firstChild);
    }
    function scrollLog() { const p = $('rtLog'); if (p) p.scrollTop = p.scrollHeight; }
    function stopLog() { clearTimeout(logTimer); logTimer = null; }
    function pollLog() {
        stopLog();
        const id = open;
        if (!id) return;
        getJSON('/admin/routines/' + id + '/log' + (logOffset != null ? '?offset=' + logOffset : '')).then((d) => {
            if (id !== open) return;
            const first = logOffset == null;
            appendLog(d.text, first || d.reset);
            logOffset = d.offset;
            const pre = $('rtLog');
            if (first && pre && !pre.textContent) pre.innerHTML = '<span class="bot-muted">Nothing logged yet.\n</span>';
            $('rtLogMeta').textContent = 'Updated ' + both(new Date().toISOString());
            if ($('rtFollow') && $('rtFollow').checked) scrollLog();
        }).catch((e) => { const m = $('rtLogMeta'); if (m) m.textContent = 'Could not read the log: ' + e.message; })
            .finally(() => {
                if (id === open && $('rtFollow') && $('rtFollow').checked) logTimer = setTimeout(pollLog, document.hidden ? 15000 : 3000);
            });
    }

    // ── status ──────────────────────────────────────────────────────────────
    function render() { renderTop(); renderDay(); renderGroups(); }
    function refresh() {
        clearTimeout(statusTimer);
        return getJSON('/admin/routines/status').then((d) => { data = d; render(); })
            .catch((e) => {
                const pill = $('rtState');
                pill.className = 'sys-pill is-bad';
                pill.querySelector('b').textContent = 'Could not load: ' + e.message;
            }).finally(() => { statusTimer = setTimeout(refresh, document.hidden ? 60000 : 15000); });
    }
    function runNow(id, btn) {
        const r = data.routines.find((x) => x.id === id);
        if (!r) return;
        busy[id] = true;
        btn.disabled = true;
        btn.textContent = 'Starting…';
        post('/admin/routines/' + id + '/run').then(({ ok, d }) => {
            if (!ok) alert(r.name + ': ' + (d.error || d.message || 'could not start'));
        }).catch((e) => alert(r.name + ': ' + e.message)).finally(() => {
            delete busy[id];
            if (open !== id) toggle(id); else { logOffset = null; pollLog(); }
            setTimeout(refresh, 800);
        });
    }

    document.addEventListener('click', (e) => {
        const run = e.target.closest('[data-run]');
        if (run) { runNow(run.dataset.run, run); return; }
        const op = e.target.closest('[data-open]');
        if (op) { e.preventDefault(); toggle(op.dataset.open); return; }
        const tool = e.target.closest('[data-tool]');
        if (tool) runTool(tool.dataset.tool, tool);
    });
    $('rtRefresh').addEventListener('click', refresh);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

    // ── manual tools ────────────────────────────────────────────────────────
    function toolOut(html, cls) {
        const o = $('rtToolOut');
        o.hidden = false;
        o.className = 'rt-tool-out bot-alert ' + (cls || 'is-info');
        o.innerHTML = html;
    }
    function pollUntil(url, done, label) {
        const t = setInterval(() => getJSON(url).then((s) => {
            if (!s.running) { clearInterval(t); done(s); } else toolOut(esc(label) + ': running…' + (s.total ? ' ' + (s.current || 0) + ' / ' + s.total : ''));
        }).catch(() => clearInterval(t)), 3000);
    }
    function runTool(kind, btn) {
        const T = {
            'tns-daily': ['/admin/tns-download-daily', () => ({ date: $('rtTnsDate').value || undefined }), 'TNS daily import', '/admin/tns-task-status'],
            'tns-snooze': ['/admin/tns-auto-snooze', null, 'Auto-snooze', '/admin/tns-task-status'],
            'phot-fetch': ['/admin/run-photometry-fetch', null, 'Inbox photometry', '/admin/photometry-fetch-status'],
            'missing-phot': ['/admin/run-missing-phot-fetch', null, 'Missing photometry'],
            'target-mags': ['/admin/run-update-target-mags', null, 'Target magnitudes'],
            'clean-images': ['/admin/documents/clean-images', null, 'Document images'],
        };
        if (kind === 'clean-images' && !confirm('Delete every uploaded image that no Markdown document references? This cannot be undone.')) return;
        const [url, body, label, statusUrl] = T[kind];
        btn.disabled = true;
        toolOut(esc(label) + ': starting…');
        post(url, body ? body() : {}).then(({ ok, d }) => {
            if (!ok) { toolOut(esc(label) + ': ' + esc(d.message || d.error || 'failed'), 'is-bad'); return; }
            toolOut(esc(label) + ': ' + esc(d.message || 'started'));
            if (statusUrl) {
                pollUntil(statusUrl, (s) => {
                    const msg = s.message || (s.total != null ? 'done — ' + s.total + ' objects: ' + (s.success || 0) + ' fetched, ' + (s.failed || 0) + ' failed' : 'done');
                    toolOut(esc(label) + ': ' + esc(msg), 'is-ok');
                }, label);
            }
        }).catch((e) => toolOut(esc(label) + ': ' + esc(e.message), 'is-bad')).finally(() => { btn.disabled = false; });
    }
    // ── Pipeline · AutoPhOT paths (read only) ───────────────────────────────
    (function pipeline() {
        const rows = $('pipelineRows');
        if (!rows) return;
        const status = $('pipelineStatus');
        function node(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
        function load(probe) {
            status.textContent = probe ? 'Checking…' : '';
            getJSON('/admin/pipeline/settings' + (probe ? '?probe=1' : '')).then((d) => {
                if (!d.success) throw new Error(d.error || 'Could not load');
                const byKey = {};
                (d.checks || []).forEach((c) => { byKey[c.key] = c; });
                rows.replaceChildren(...d.settings.map((s) => {
                    const c = byKey[s.key];
                    const field = node('div', 'kw-field');
                    const label = node('div', 'pipe-label');
                    label.append(node('span', 'pipe-dot' + (c ? (c.ok ? ' is-ok' : ' is-bad') : '')), node('span', '', s.label));
                    field.append(label, node('code', 'pipe-path', s.used), node('div', 'pipe-note' + (c && !c.ok ? ' is-bad' : ''), s.source + (c ? ' · ' + c.detail : '')));
                    return field;
                }));
                const bad = (d.checks || []).filter((c) => !c.ok).length;
                status.textContent = probe ? (bad ? bad + ' problem' + (bad > 1 ? 's' : '') + ' found' : 'Ready') : '';
            }).catch(() => { rows.replaceChildren(node('p', 'pipe-note is-bad', 'Could not load the pipeline paths.')); status.textContent = ''; });
        }
        $('pipelineCheck').addEventListener('click', () => load(true));
        load(false);
    })();

    // first paint from the server's data, then poll; #<routine id> opens that routine
    render();
    const h = (location.hash || '').slice(1);
    if (data.routines.some((r) => r.id === h)) toggle(h);
    setInterval(renderDay, 60000);
    refresh();
})();
