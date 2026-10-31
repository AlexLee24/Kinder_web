// Triggers › Alerts (/bots): a card per bot (state) and the results of the selected one. Polls /api/bots/status
// every 15 s and the open bot's /api/bots/<id>/results every 60 s while the page is visible. Read only: no run / stop /
// log here.
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    let bots = [];
    try { bots = JSON.parse($('lbInitial').textContent) || []; } catch (e) { /* first poll fills it */ }
    let sel = null, tab = null, results = {}, loading = null;
    const isAdmin = !!$('lbPage').dataset.admin;

    // ── time ───────────────────────────────────────────────────────────────
    function ago(iso) {
        if (!iso) return '—';
        const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
        if (isNaN(s)) return '—';
        if (s < 0) return until(iso);
        if (s < 60) return s + ' s ago';
        if (s < 3600) return Math.round(s / 60) + ' min ago';
        if (s < 86400) return Math.round(s / 3600) + ' h ago';
        return Math.round(s / 86400) + ' d ago';
    }
    function until(iso) {
        const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
        if (isNaN(s)) return '—';
        if (s <= 0) return 'now';
        if (s < 3600) return 'in ' + Math.max(1, Math.round(s / 60)) + ' min';
        if (s < 86400) return 'in ' + Math.round(s / 3600) + ' h';
        return 'in ' + Math.round(s / 86400) + ' d';
    }
    function stamp(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return isNaN(d) ? '' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    const timeTag = (iso, cls) => '<time class="' + cls + '" datetime="' + esc(iso || '') + '" title="' + esc(stamp(iso)) + '">' + esc(ago(iso)) + '</time>';

    function getJSON(url) {
        return fetch(url, { headers: { Accept: 'application/json' } }).then((r) => r.json().then((d) => {
            if (!r.ok || d.success === false) throw new Error(d.error || ('HTTP ' + r.status));
            return d;
        }));
    }

    // ── cards ──────────────────────────────────────────────────────────────
    const fact = (label, html) => '<div><dt>' + esc(label) + '</dt><dd>' + html + '</dd></div>';
    function card(b) {
        const facts = [];
        const run = b.last_run || {};
        if (b.kind === 'listener') {
            facts.push(fact('Last sign of life', b.heartbeat_at ? esc(ago(b.heartbeat_at)) : '—'));
        } else {
            let last = '—';
            if (run.started_at && !run.finished_at) last = '<span class="lb-h-busy">running</span>';
            else if (run.finished_at) last = '<span class="' + (run.ok ? 'lb-h-ok' : 'lb-h-bad') + '">' + (run.ok ? 'OK' : 'Failed') + '</span> · ' + esc(ago(run.finished_at));
            facts.push(fact('Last run', last));
        }
        facts.push(fact(b.next_run ? 'Next run' : 'Today', b.next_run ? esc(until(b.next_run)) : (b.today || 0) + ' events'));
        const ev = b.last_event;
        const err = b.last_error && (!ev || b.last_error.at >= ev.at) && b.health === 'bad' ? b.last_error : null;
        return '<article class="kw-panel lb-card' + (b.id === sel ? ' is-sel' : '') + '" data-bot="' + esc(b.id) + '">' +
            '<button type="button" class="lb-card-head" aria-pressed="' + (b.id === sel) + '"><span class="lb-dot is-' + esc(b.health) + '" aria-hidden="true"></span><b>' + esc(b.name) + '</b></button>' +
            '<p class="lb-sub"><b class="lb-h-' + esc(b.health) + '">' + esc(b.health_label) + '</b> · ' + esc(b.schedule) + '</p>' +
            (b.setup ? '<p class="lb-alert is-warn">' + esc(b.setup) + '</p>' : '') +
            (err ? '<p class="lb-alert is-bad"><b>' + esc(ago(err.at)) + ':</b> ' + esc(err.text) + '</p>' : '') +
            '<dl class="lb-facts">' + facts.join('') + '</dl>' +
            '<div class="lb-last">' + (ev ? timeTag(ev.at, 'lb-last-time') + '<span class="lb-last-text lvl-' + esc(ev.level) + '" title="' + esc(ev.text) + '">' + esc(ev.text) + '</span>'
                : '<span class="lb-last-text">Nothing yet</span>') + '</div></article>';
    }
    function renderCards() { $('lbCards').innerHTML = bots.map(card).join(''); }

    // ── results ────────────────────────────────────────────────────────────
    const TABS = {
        gcn: [['ep', 'Einstein Probe'], ['circulars', 'GCN circulars'], ['robot', 'Robot API'], ['activity', 'Activity']],
        astronote: [['notes', 'AstroNotes'], ['activity', 'Activity']],
        obs_log: [['nights', 'Nights'], ['activity', 'Activity']],
    };
    const current = () => bots.find((b) => b.id === sel);

    function select(id, newTab) {
        if (!bots.some((b) => b.id === id)) id = bots[0] && bots[0].id;
        if (!id) return;
        const changed = id !== sel;
        sel = id;
        const names = TABS[sel].map((t) => t[0]);
        tab = newTab && names.includes(newTab) ? newTab : (!changed && names.includes(tab) ? tab : names[0]);
        try { history.replaceState(null, '', '#' + sel + (tab !== names[0] ? '/' + tab : '')); } catch (e) { /* file:// */ }
        document.querySelectorAll('.lb-card').forEach((c) => {
            const on = c.dataset.bot === sel;
            c.classList.toggle('is-sel', on);
            const h = c.querySelector('.lb-card-head');
            if (h) h.setAttribute('aria-pressed', on);
        });
        $('lbDetailT').textContent = current().name;
        $('lbTabs').innerHTML = TABS[sel].map((t) => '<button type="button" class="kw-tab' + (t[0] === tab ? ' is-on' : '') + '" role="tab" aria-selected="' + (t[0] === tab) + '" data-tab="' + t[0] + '">' + t[1] + '</button>').join('');
        if (changed || !results[sel]) load(sel); else renderView();
    }

    function load(id) {
        if (loading === id) return;
        loading = id;
        if (!results[id]) $('lbView').innerHTML = '<p class="kw-empty">Loading…</p>';
        getJSON('/api/bots/' + encodeURIComponent(id) + '/results').then((d) => {
            results[id] = d;
            results[id].at = new Date();
        }).catch((e) => {
            results[id] = { error: e.message, at: new Date() };
        }).finally(() => {
            loading = null;
            if (id === sel) renderView();
        });
    }

    function renderView() {
        const b = current(), r = results[sel];
        if (!b || !r) return;
        $('lbMeta').textContent = r.at ? 'Updated ' + r.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const v = $('lbView');
        if (tab === 'activity') { v.innerHTML = activity(b); return; }
        if (r.error && !r.nights && !r.ep) { v.innerHTML = '<p class="lb-alert is-bad">' + esc(r.error) + '</p>'; return; }
        if (tab === 'ep') v.innerHTML = (r.error ? '<p class="lb-alert is-bad">' + esc(r.error) + '</p>' : '') + epAlerts(r.ep || []);
        else if (tab === 'robot') v.innerHTML = robotApi(r.robot_clients || []);
        else if (tab === 'circulars') v.innerHTML = circulars(r.circulars || []);
        else if (tab === 'notes') v.innerHTML = notes(r.notes || []);
        else if (tab === 'nights') v.innerHTML = nights(r);
    }

    function activity(b) {
        const evs = b.events || [];
        if (!evs.length) return '<p class="kw-empty">No activity yet. This lists what the bot did: alerts posted, nights logged, runs that failed.</p>';
        return '<div class="lb-activity">' + evs.map((e) =>
            '<div class="kw-row"><span class="lb-dot is-' + (e.level === 'error' ? 'bad' : e.level === 'warn' ? 'warn' : 'ok') + '" aria-hidden="true"></span>' +
            '<div class="kw-row-main"><b>' + esc(e.text) + '</b></div>' + timeTag(e.at, 'kw-row-time') + '</div>').join('') + '</div>';
    }

    const ROBOT_STATUS = { active: ['kw-chip-green', 'Active'], cancelled: ['kw-chip-red', 'Cancelled'], expired: ['', 'Expired'] };
    function epAlerts(list) {
        if (!list.length) return '<p class="kw-empty">No Einstein Probe alert yet. Each WXT alert gets a name (EPt…), an SLT script, a Lulin visibility plot and a robot alert number.</p>';
        return '<p class="kw-panel-desc">The newest ' + list.length + ' Einstein Probe WXT alerts, newest first. The number is the robot alert id; the robot API shows only the newest Active one.</p><div class="lb-items">' + list.map((e) => {
            const st = ROBOT_STATUS[e.status];
            const vis = e.observable_tonight == null ? '' : e.observable_tonight
                ? 'Up to ' + esc(e.max_alt_deg) + '° tonight, Moon ' + esc(e.moon_sep_deg) + '°' : 'Not observable tonight' + (e.max_alt_deg != null ? ' (max ' + esc(e.max_alt_deg) + '°)' : '');
            const sub = ['RA ' + esc(e.ra) + ' · Dec ' + esc(e.dec), vis].filter(Boolean).join(' · ');
            const acts = ['<button type="button" class="kw-btn kw-btn-sm" data-copy="' + esc(e.script) + '">Copy script</button>'];
            if (isAdmin && e.id && e.status === 'active') acts.push('<button type="button" class="kw-btn kw-btn-sm kw-btn-danger" data-robot="' + e.id + '" data-to="cancelled">Cancel for robot</button>');
            if (isAdmin && e.id && e.status === 'cancelled') acts.push('<button type="button" class="kw-btn kw-btn-sm" data-robot="' + e.id + '" data-to="active">Restore</button>');
            return '<details class="lb-item"><summary><div class="lb-item-main"><b>' + (e.id ? '#' + esc(e.id) + ' ' : '') + esc(e.name) + '</b><small>' + sub + '</small></div>' +
                (st ? '<span class="kw-chip ' + st[0] + '">' + st[1] + '</span>' : '') + timeTag(e.created_at, 'lb-item-time') + '</summary>' +
                '<div class="lb-item-body">' +
                (e.trigger_time ? '<p>Trigger ' + esc(e.trigger_time) + (e.expires_at ? ' · robot window until ' + esc(stamp(e.expires_at)) : '') + '</p>' : '') +
                (e.status === 'cancelled' && e.status_by ? '<p>Cancelled by ' + esc(e.status_by) + ' ' + esc(ago(e.status_at)) + '</p>' : '') +
                '<pre class="lb-pre">' + esc(e.script) + '</pre><div class="lb-actions">' + acts.join('') + '</div></div></details>';
        }).join('') + '</div>';
    }

    function robotApi(list) {
        const url = location.origin + '/api/v1/robot/alert';
        return '<p class="kw-panel-desc">The Lulin robot polls one keyless endpoint. It shows at most one alert, the newest Active one, with its script; the robot runs it only when its id is larger than the one it ran last.</p>' +
            '<pre class="lb-pre">curl -s ' + esc(url) + '</pre>' +
            '<div class="lb-actions"><a class="kw-btn kw-btn-sm" href="/api/v1/robot/alert" target="_blank" rel="noopener">Open the feed</a><a class="kw-btn kw-btn-sm" href="/api" target="_blank" rel="noopener">API docs</a></div>' +
            '<h3>Who polls</h3>' +
            (list.length ? '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>Client</th><th>Last poll</th><th>Got</th><th>Polls</th></tr></thead><tbody>' +
                list.map((c) => '<tr><td>' + esc(c.ip) + (c.agent ? '<br><small class="kw-muted">' + esc(c.agent) + '</small>' : '') + '</td><td>' + timeTag(c.at, '') +
                    '</td><td class="lb-num">' + (c.alert_id ? '#' + esc(c.alert_id) : 'nothing') + '</td><td class="lb-num">' + esc(c.polls) + '</td></tr>').join('') +
                '</tbody></table></div>' : '<p class="kw-empty">Nobody has polled the robot API yet.</p>');
    }

    function circulars(list) {
        if (!list.length) return '<p class="kw-empty">No GCN circular received yet.</p>';
        return '<p class="kw-panel-desc">The newest ' + list.length + ' circulars posted to Slack, newest first.</p><div class="lb-items">' + list.map((c) =>
            '<details class="lb-item"><summary><div class="lb-item-main"><b>' + esc(c.subject || '(no subject)') + '</b>' +
            '<small>' + (c.id ? 'GCN ' + esc(c.id) : 'Circular') + '</small></div>' + timeTag(c.received_at, 'lb-item-time') + '</summary>' +
            '<div class="lb-item-body"><pre class="lb-pre">' + esc(c.text.replace(/\*/g, '')) + '</pre>' +
            (c.id ? '<div class="lb-actions"><a class="kw-btn kw-btn-sm" href="https://gcn.nasa.gov/circulars/' + encodeURIComponent(c.id) + '" target="_blank" rel="noopener noreferrer">Open on GCN</a></div>' : '') +
            '</div></details>').join('') + '</div>';
    }

    function notes(list) {
        if (!list.length) return '<p class="kw-empty">No AstroNote posted since this list started. New notes show up here once the bot posts them to Slack.</p>';
        return '<p class="kw-panel-desc">The newest ' + list.length + ' AstroNotes posted to Slack, newest first.</p><div class="lb-items">' + list.map((n) => {
            const meta = [n.id, n.type, n.source_group].filter(Boolean).map(esc).join(' · ');
            const objs = (n.objects || []).map((o) => '<a class="kw-chip kw-chip-blue" href="/object/' + encodeURIComponent(o.iauname || o.name) + '">' + esc(o.name) +
                (o.type ? ' · ' + esc(o.type) : '') + (o.z ? ' · z=' + esc(o.z) : '') + '</a>').join('');
            return '<details class="lb-item"><summary><div class="lb-item-main"><b>' + esc(n.title) + '</b><small>' + meta + '</small></div>' +
                timeTag(n.posted_at, 'lb-item-time') + '</summary><div class="lb-item-body">' +
                (n.authors ? '<p><em>' + esc(n.authors) + '</em></p>' : '') +
                (objs ? '<div class="lb-chips">' + objs + '</div>' : '') +
                (n.abstract ? '<p>' + esc(n.abstract) + '</p>' : '') +
                '<div class="lb-actions"><a class="kw-btn kw-btn-sm" href="' + esc(n.url) + '" target="_blank" rel="noopener noreferrer">View on TNS</a></div></div></details>';
        }).join('') + '</div>';
    }

    const count = (x) => (x.frames || []).reduce((n, f) => n + (Number(f.count) || 0), 0);
    const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
    function nights(r) {
        const list = r.nights || [];
        const head = '<p class="kw-panel-desc">What the bot added to the observation log in the last ' + esc(r.days) + ' nights. ' +
            '<a href="/daily_trigger">Open the observation log</a></p>' + (r.error ? '<p class="lb-alert is-bad">' + esc(r.error) + '</p>' : '');
        if (!list.length) return head + '<p class="kw-empty">Nothing added in this window.</p>';
        return head + '<div class="lb-items">' + list.map((n) => {
            const t = n.targets || [];
            const sci = t.filter((x) => !x.calibration), cal = t.filter((x) => x.calibration);
            const total = t.reduce((m, x) => m + count(x), 0);
            const sub = [(n.telescopes || []).join(', '), plural(sci.length, 'target'), plural(total, 'frame')].filter(Boolean).join(' · ');
            return '<div class="lb-night"><div class="lb-night-head"><b>' + esc(n.night) + '</b><small>' + esc(sub) + '</small></div>' +
                (sci.length ? '<ul class="lb-added">' + sci.map((x) => '<li><b>' + esc(x.name) + '</b><span>' + esc(x.telescope) + ' · ' + plural(count(x), 'frame') + '</span></li>').join('') + '</ul>' : '') +
                (cal.length ? '<p class="lb-cal">Calibration: ' + cal.map((x) => (new Set(cal.map((c) => c.telescope)).size > 1 ? esc(x.telescope) + ' ' : '') + esc(x.name) + ' ' + count(x)).join(' · ') + '</p>' : '') +
                (!t.length ? '<p class="lb-cal">Frames found, but nothing in the observation log.</p>' : '') + '</div>';
        }).join('') + '</div>';
    }

    // ── events ─────────────────────────────────────────────────────────────
    $('lbCards').addEventListener('click', (e) => {
        const c = e.target.closest('.lb-card');
        if (c && !e.target.closest('a')) select(c.dataset.bot);
    });
    $('lbTabs').addEventListener('click', (e) => {
        const t = e.target.closest('[data-tab]');
        if (t) select(sel, t.dataset.tab);
    });
    $('lbView').addEventListener('click', (e) => {
        const rb = e.target.closest('[data-robot]');
        if (rb) {
            if (rb.dataset.to === 'cancelled' && !confirm('Cancel robot alert #' + rb.dataset.robot + '? The Lulin robot will no longer run it.')) return;
            rb.disabled = true;
            fetch('/api/bots/robot_alerts/' + rb.dataset.robot + '/status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: rb.dataset.to }) })
                .then((r) => r.json().then((d) => { if (!r.ok || !d.success) throw new Error(d.error || ('HTTP ' + r.status)); }))
                .then(() => { load('gcn'); poll(); })
                .catch((err) => { rb.disabled = false; alert(err.message); });
            return;
        }
        const btn = e.target.closest('[data-copy]');
        if (!btn) return;
        navigator.clipboard.writeText(btn.dataset.copy).then(() => {
            btn.textContent = 'Copied';
            setTimeout(() => { btn.textContent = 'Copy script'; }, 1500);
        }).catch(() => { btn.textContent = 'Copy failed'; });
    });
    function poll() {
        return getJSON('/api/bots/status').then((d) => {
            bots = d.bots || [];
            renderCards();
            const cur = current();
            if (cur && tab === 'activity') renderView();
        }).catch(() => { /* keep the last state */ });
    }
    $('lbRefresh').addEventListener('click', () => { poll(); if (sel) load(sel); });

    renderCards();
    const hash = location.hash.slice(1).split('/');
    select(hash[0], hash[1]);
    setInterval(() => { if (!document.hidden) poll(); }, 15000);
    setInterval(() => { if (!document.hidden && sel) load(sel); }, 60000);
})();
