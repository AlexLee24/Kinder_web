// Admin › Bots (/admin/bots): cards for every lab bot, and a detail panel for one of them (log, events and, per bot,
// steps / folders / nights / NAS moves). Polls /admin/bots/status every 10 s; while the Log tab is open and the page is visible
// it follows the bot's log every 3 s from the last byte offset.
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    let bots = [];
    try { bots = JSON.parse($('botInitial').textContent) || []; } catch (e) { /* first poll fills it */ }
    let sel = null, tab = 'log', logOffset = null, logTimer = null, busy = {};
    const MAX_LOG_CHARS = 400000;

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
        if (!iso) return '—';
        const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
        if (isNaN(s)) return '—';
        if (s <= 0) return 'now';
        if (s < 60) return 'in ' + s + ' s';
        if (s < 3600) return 'in ' + Math.round(s / 60) + ' min';
        if (s < 86400) return 'in ' + Math.round(s / 3600) + ' h';
        return 'in ' + Math.round(s / 86400) + ' d';
    }
    function stamp(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return isNaN(d) ? '' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    function dur(secs) {
        if (secs == null) return '';
        if (secs < 60) return secs + ' s';
        if (secs < 3600) return Math.floor(secs / 60) + ' min ' + (secs % 60) + ' s';
        return Math.floor(secs / 3600) + ' h ' + Math.round((secs % 3600) / 60) + ' min';
    }

    // ── network ────────────────────────────────────────────────────────────
    function getJSON(url) {
        return fetch(url, { headers: { Accept: 'application/json' } }).then((r) => r.json().then((d) => {
            if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
            return d;
        }));
    }
    function post(url) {
        return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
            .then((r) => r.json().then((d) => ({ ok: r.ok && !d.error, d })));
    }

    // ── summary ────────────────────────────────────────────────────────────
    const HEALTHY = ['ok', 'busy'];
    function renderTop() {
        const live = bots.filter((b) => b.health !== 'off');
        const good = live.filter((b) => HEALTHY.includes(b.health)).length;
        const bad = bots.filter((b) => b.health === 'bad' || b.health === 'warn');
        const today = bots.reduce((n, b) => n + (b.today || 0), 0);
        const next = bots.map((b) => b.next_run).filter(Boolean).sort()[0];
        $('botKpis').innerHTML =
            kpi('Healthy', good + '<i> / ' + live.length + '</i>', live.length ? 'running or OK' : 'none running', '') +
            kpi('Need attention', bad.length, bad.length ? bad.map((b) => b.name).join(', ') : 'all clear', bad.length ? 'is-bad' : '') +
            kpi('Events today', today, 'alerts posted, nights logged …', '') +
            kpi('Next run', next ? until(next) : '—', next ? stamp(next) : 'no scheduled run', '');
        const pill = $('botState');
        pill.className = 'sys-pill ' + (bad.length ? 'is-bad' : good ? 'is-ok' : 'is-warn');
        pill.querySelector('b').textContent = bad.length ? bad.length + ' need attention' : good ? 'All bots OK' : 'No bot running';
    }
    function kpi(label, value, small, cls) {
        return '<div class="kw-kpi bot-kpi ' + cls + '"><span class="kw-kpi-label">' + esc(label) + '</span><b>' + value + '</b><small>' + esc(small) + '</small></div>';
    }

    // ── cards ──────────────────────────────────────────────────────────────
    function fact(label, value, title) {
        return '<div><dt>' + esc(label) + '</dt><dd' + (title ? ' title="' + esc(title) + '"' : '') + '>' + value + '</dd></div>';
    }
    // DETECT: one block per half instead of the generic facts (last / next run of every trigger, what ALeRCE returned)
    function hoursAgo(iso) {          // "33 h ago" rather than "1 d ago": how long ALeRCE has had nothing new matters to the hour
        const h = (Date.now() - new Date(iso).getTime()) / 3600000;
        return isNaN(h) ? '—' : h < 1 || h >= 72 ? ago(iso) : Math.round(h) + ' h ago';
    }
    function when(iso, fn) {
        return iso ? esc(fn(iso)) + '<small>' + esc(stamp(iso)) + '</small>' : '—';
    }
    function srcTNS(t) {
        if (t.unavailable) return '<p class="bot-alert is-warn">TNS-DETECT status unavailable: ' + esc(t.unavailable) + '</p>';
        const rows = (t.runs || []).map((r) => {
            let last = '<span class="bot-muted">no run recorded yet</span>';
            if (r.started_at && !r.finished_at) last = '<span class="bot-busy">running since ' + esc(ago(r.started_at).replace(' ago', '')) + '</span>';
            else if (r.finished_at) last = '<span class="' + (r.ok ? 'bot-good' : 'bot-bad') + '">' + (r.ok ? 'OK' : 'Failed') + '</span> · ' + esc(ago(r.finished_at)) +
                '<small>' + esc(stamp(r.finished_at)) + (r.message ? ' · ' + esc(r.message) : '') + '</small>';
            return '<tr><th scope="row">' + esc(r.name) + '</th><td>' + last + '</td><td>' + when(r.next_run, until) + '</td></tr>';
        }).join('');
        return '<table class="bot-src-runs"><thead><tr><th>Trigger</th><th>Last run</th><th>Next run</th></tr></thead><tbody>' + rows + '</tbody></table>' +
            '<p class="bot-src-note">An import runs DETECT right after it, on the objects it added or changed; an import with nothing new skips it.</p>';
    }
    function srcLSST(l) {
        if (l.unavailable) return '<p class="bot-alert is-warn">LSST-DETECT status unavailable: ' + esc(l.unavailable) + '</p>';
        if (!l.enabled) return '<p class="bot-alert is-warn">LSST-DETECT is switched off (LSST_WATCH=0 in kinder.env).</p>';
        const o = l.last_ok || {};
        const dl = [];
        let st = '<span class="bot-muted">not run yet</span>';
        if (l.state === 'running') st = '<span class="bot-busy">Running · ' + esc(l.phase || '') + ' · since ' + esc(ago(l.started_at).replace(' ago', '')) + '</span>';
        else if (l.state === 'error') st = '<span class="bot-bad">Failed</span> · ' + esc(ago(l.finished_at));
        else if (l.state === 'interrupted') st = '<span class="bot-bad">Interrupted</span> (server restarted mid-run) · ' + esc(ago(l.started_at));
        else if (l.state === 'done') st = '<span class="bot-good">OK</span> · ' + esc(ago(l.finished_at));
        if (l.trigger) st += ' · ' + esc(l.trigger) + ' run';
        dl.push(fact('Last run', st + '<small>' + esc(stamp(l.finished_at || l.started_at)) + (l.state === 'done' && o.seconds != null ? ' · took ' + esc(dur(Math.round(o.seconds))) : '') + '</small>'));
        if (o.at) {
            const cls = ['SN', 'AGN', 'VS'].filter((k) => k in (o.by_class || {})).map((k) => k + ' ' + o.by_class[k]).join(' · ');
            const win = o.window && o.window[0] ? 'first detected ' + stamp(o.window[0]) + ' – ' + stamp(o.window[1]) : '';
            dl.push(fact('ALeRCE returned', '<b class="bot-n">' + (o.fetched || 0) + '</b> objects' + (cls ? ' (' + esc(cls) + ')' : '') +
                '<small>' + esc(win) + (l.state === 'error' ? ' · last successful run, ' + esc(ago(o.at)) : '') + '</small>'));
            dl.push(fact('Matched', esc((o.lens || 0) + ' near a lens · ' + (o.desi || 0) + ' near a DESI galaxy') +
                '<small>' + esc((o.stored || 0) + ' stored · ' + (o.linked || 0) + ' in TNS' + (o.relinked ? ' · ' + o.relinked + ' older ones newly in TNS' : '')) + '</small>'));
            const d = o.detect || {};
            dl.push(fact('DETECT', d.error ? '<span class="bot-bad">Failed</span><small>' + esc(d.error) + '</small>'
                : esc((d.screened || 0) + ' screened · ' + (d.images || 0) + ' images') + (d.failed ? ' · <span class="bot-bad">' + d.failed + ' failed</span>' : ' · 0 failed')));
        }
        dl.push(fact('Newest LSST object', l.newest_alert_at ? '<span class="' + (l.stale ? 'bot-bad' : 'bot-good') + '">' + esc(hoursAgo(l.newest_alert_at)) + '</span><small>first detected ' + esc(stamp(l.newest_alert_at)) + '</small>' : '—'));
        dl.push(fact('Next run', 'hourly ' + when(l.next_hourly, until)));
        dl.push(fact('Next daily sweep', when(l.next_sweep, until) + '<small>re-reads the last 1.5 days</small>'));
        let alert = '';
        if (l.state === 'error') {
            alert = '<p class="bot-alert is-bad"><b>Last run failed:</b> ' + esc(l.error || 'see the run log on LSST-DETECT') +
                (/alerce/i.test(l.error || '') ? ' — Kinder could not read ALeRCE (blocked, down or timing out).' : '') + '</p>';
        } else if (l.stale && l.state === 'done') {
            alert = '<p class="bot-alert is-warn"><b>No new LSST object at ALeRCE for ' + esc(hoursAgo(l.newest_alert_at).replace(' ago', '')) + '.</b> ' +
                'Kinder is not blocked: the last run read ALeRCE without errors. Rubin did not observe since, or ALeRCE has not ingested it yet.</p>';
        }
        return alert + '<dl class="bot-facts bot-src-facts">' + dl.join('') + '</dl>';
    }
    function detectSources(src) {
        const t = src.tns || {}, l = src.lsst || {};
        return '<section class="bot-src"><h3>TNS-DETECT <a href="/detect">Open →</a></h3>' + srcTNS(t) + '</section>' +
            '<section class="bot-src"><h3>LSST-DETECT <a href="/detect/lsst">Open →</a></h3>' + srcLSST(l) + '</section>';
    }
    function card(b) {
        const facts = [];
        if (b.kind === 'listener') {
            facts.push(fact('Heartbeat', esc(ago(b.heartbeat_at)), stamp(b.heartbeat_at)));
            facts.push(fact('Up since', esc(b.started_at ? stamp(b.started_at) : '—')));
        } else {
            const r = b.last_run || {};
            let last = '—';
            if (r.started_at && !r.finished_at) last = '<span class="bot-busy">running since ' + esc(ago(r.started_at).replace(' ago', '')) + '</span>';
            else if (r.finished_at) last = '<span class="' + (r.ok ? 'bot-good' : 'bot-bad') + '">' + (r.ok ? 'OK' : 'Failed') + '</span> · ' + esc(ago(r.finished_at));
            facts.push(fact('Last run', last, r.message || ''));
            facts.push(fact('Next run', esc(b.next_run ? until(b.next_run) : '—'), stamp(b.next_run)));
        }
        facts.push(fact('Today', '<b class="bot-n">' + (b.today || 0) + '</b> events'));
        const ev = b.last_event;
        const setup = (b.detail || {}).setup;
        const err = b.last_error && (b.health === 'bad' || b.health === 'warn') && !setup ? b.last_error : null;
        const running = b.state === 'running' && b.health === 'busy';
        const acts = [];
        acts.push('<button type="button" class="kw-btn kw-btn-sm" data-act="open" data-bot="' + b.id + '">Log & details</button>');
        if (b.can_run && !running) {
            // DETECT has two ways to run it by hand: the daily Follow-up re-screen and what TNS touched in the last 2 h
            const kinds = b.id === 'detect' ? [['followups', 'Re-screen Follow-ups'], ['recent', 'Recent (2 h)']] : [['', 'Run now']];
            kinds.forEach((k) => acts.push('<button type="button" class="kw-btn kw-btn-sm kw-btn-tinted" data-act="run" data-bot="' + b.id + '"' + (k[0] ? ' data-kind="' + k[0] + '"' : '') + (busy[b.id] ? ' disabled' : '') + '>' + k[1] + '</button>'));
        }
        if (b.can_stop && running) acts.push('<button type="button" class="kw-btn kw-btn-sm kw-btn-danger" data-act="stop" data-bot="' + b.id + '"' + (busy[b.id] ? ' disabled' : '') + '>Stop</button>');
        if (b.sources) acts.push('<a class="kw-btn kw-btn-sm kw-btn-ghost" href="/detect/lsst">LSST run log →</a>');
        else (b.links || []).forEach((l) => acts.push('<a class="kw-btn kw-btn-sm kw-btn-ghost" href="' + esc(l[1]) + '">' + esc(l[0]) + ' →</a>'));
        return '<article class="kw-panel bot-card' + (b.id === sel ? ' is-sel' : '') + '" data-bot="' + b.id + '">' +
            '<div class="bot-card-head"><span class="bot-dot is-' + b.health + '" aria-hidden="true"></span><h2>' + esc(b.name) + '</h2>' +
            '<span class="kw-chip ' + (b.kind === 'listener' ? 'kw-chip-blue' : 'kw-chip-purple') + '">' + (b.kind === 'listener' ? 'Listener' : 'Scheduled') + '</span></div>' +
            '<p class="bot-sub"><b class="bot-h-' + b.health + '">' + esc(b.health_label) + '</b> · ' + esc(b.schedule) + '</p>' +
            (b.sources ? '' : '<p class="bot-about">' + esc(b.about) + '</p>') +
            (setup ? '<p class="bot-alert is-warn">' + esc(setup) + '</p>' : '') +
            (err ? '<p class="bot-alert is-bad"><b>' + esc(ago(err.at)) + ':</b> ' + esc(err.text) + '</p>' : '') +
            (b.sources ? detectSources(b.sources) :
                '<dl class="bot-facts">' + facts.join('') + '</dl>' +
                '<div class="bot-last">' + (ev ? '<span class="bot-ev-time" title="' + esc(stamp(ev.at)) + '">' + esc(ago(ev.at)) + '</span><span class="bot-ev-text lvl-' + esc(ev.level) + '">' + esc(ev.text) + '</span>' : '<span class="bot-muted">No events yet</span>') + '</div>') +
            '<div class="kw-panel-foot">' + acts.join('') + '</div></article>';
    }
    function renderCards() { $('botCards').innerHTML = bots.map(card).join(''); }

    // ── detail ─────────────────────────────────────────────────────────────
    function tabsFor(b) {
        const t = [['log', 'Log'], ['events', 'Events']];
        if (b.id === 'reduction') t.push(['steps', 'Steps'], ['folders', 'Folders']);
        if (b.id === 'obs_log') t.push(['nights', 'Nights']);
        if (b.id === 'detect') t.push(['overview', 'Overview & manual runs']);
        if (b.id === 'nas_backup') t.unshift(['moves', 'Moves']);
        return t;
    }
    function current() { return bots.find((b) => b.id === sel); }
    function select(id, newTab) {
        if (!bots.some((b) => b.id === id)) return;
        const changed = id !== sel;
        sel = id;
        const b = current();
        const names = tabsFor(b).map((t) => t[0]);
        tab = newTab && names.includes(newTab) ? newTab : (changed ? names[0] : (names.includes(tab) ? tab : names[0]));
        if (changed) logOffset = null;
        try { history.replaceState(null, '', '#' + sel + (tab !== names[0] ? '/' + tab : '')); } catch (e) { /* file:// */ }
        document.querySelectorAll('#botPick .kw-seg-item').forEach((x) => {
            const on = x.dataset.bot === sel;
            x.classList.toggle('is-on', on); x.setAttribute('aria-selected', on);
        });
        document.querySelectorAll('.bot-card').forEach((c) => c.classList.toggle('is-sel', c.dataset.bot === sel));
        $('botDetailT').textContent = b.name;
        $('botTabs').innerHTML = tabsFor(b).map((t) => '<button type="button" class="kw-tab' + (t[0] === tab ? ' is-on' : '') + '" role="tab" aria-selected="' + (t[0] === tab) + '" data-tab="' + t[0] + '">' + t[1] + '</button>').join('');
        renderView(true);
    }

    function renderView(fresh) {
        const b = current();
        if (!b) return;
        stopLog();
        const v = $('botView');
        if (tab === 'log') {
            if (fresh || !$('botLog')) {
                v.innerHTML = '<div class="bot-log-bar"><label class="bot-check"><input type="checkbox" id="botFollow" checked> Follow</label>' +
                    '<label class="bot-check"><input type="checkbox" id="botProblems"> Warnings and errors only</label>' +
                    '<span class="kw-panel-meta" id="botLogMeta"></span></div>' +
                    '<pre class="bot-log" id="botLog" tabindex="0" aria-label="' + esc(b.name) + ' log"></pre>';
                $('botProblems').addEventListener('change', () => $('botLog').classList.toggle('only-problems', $('botProblems').checked));
                $('botFollow').addEventListener('change', () => { if ($('botFollow').checked) { scrollLog(); pollLog(); } });
                logOffset = null;
            }
            pollLog();
        } else if (tab === 'events') {
            v.innerHTML = b.events.length ? '<div class="bot-events">' + b.events.map((e) =>
                '<div class="kw-row"><span class="bot-dot is-' + (e.level === 'error' ? 'bad' : e.level === 'warn' ? 'warn' : 'ok') + '"></span>' +
                '<div class="kw-row-main"><b class="bot-wrap">' + esc(e.text) + '</b></div><span class="kw-row-time" title="' + esc(stamp(e.at)) + '">' + esc(ago(e.at)) + '</span></div>').join('') + '</div>'
                : '<p class="bot-muted">No events yet. Events are what the bot did: alerts posted, nights logged, runs finished or failed.</p>';
        } else if (tab === 'steps') {
            renderSteps(b);
        } else if (tab === 'folders') {
            v.innerHTML = '<p class="bot-muted">Reading the folders…</p>';
            getJSON('/admin/bots/reduction/overview' + (fresh ? '?fresh=1' : '')).then(renderFolders).catch((e) => { v.innerHTML = '<p class="bot-alert is-bad">' + esc(e.message) + '</p>'; });
        } else if (tab === 'moves') {
            if (fresh) v.innerHTML = '<p class="bot-muted">Reading the folders…</p>';
            getJSON('/admin/bots/nas_backup/overview' + (fresh ? '?fresh=1' : '')).then(renderMoves).catch((e) => { v.innerHTML = '<p class="bot-alert is-bad">' + esc(e.message) + '</p>'; });
        } else if (tab === 'overview') {
            v.innerHTML = '<p class="bot-muted">Reading the database…</p>';
            getJSON('/admin/bots/detect/overview').then(renderDetect).catch((e) => { v.innerHTML = '<p class="bot-alert is-bad">' + esc(e.message) + '</p>'; });
        } else if (tab === 'nights') {
            const d = b.detail || {};
            const nights = d.nights || [];
            v.innerHTML = (d.raw_dir ? '<p class="kw-panel-desc">Raw frames from <code>' + esc(d.raw_dir) + '</code>, last run.</p>' : '') +
                (nights.length ? '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>Night</th><th>Telescopes</th><th>Targets</th><th>Frames</th></tr></thead><tbody>' +
                    nights.map((n) => '<tr><td>' + esc(n.night) + '</td><td>' + esc((n.telescopes || []).join(', ')) + '</td><td>' + n.targets + '</td><td>' + n.frames + '</td></tr>').join('') +
                    '</tbody></table></div>' : '<p class="bot-muted">No nights with frames in the last run.</p>');
        }
    }

    const STEP_CHIP = { ok: ['kw-chip-green', 'Done'], failed: ['kw-chip-red', 'Failed'], running: ['kw-chip-gold', 'Running'], stopped: ['kw-chip-red', 'Stopped'], skipped: ['', 'Skipped'], pending: ['', 'Waiting'] };
    function renderSteps(b) {
        const d = b.detail || {};
        const steps = d.steps || [];
        const run = b.last_run || {};
        $('botView').innerHTML =
            (d.setup ? '<p class="bot-alert is-warn">' + esc(d.setup) + '</p>' : '') +
            '<p class="kw-panel-desc">' + (run.started_at ? 'Run started ' + esc(stamp(run.started_at)) + (run.finished_at ? ', finished ' + esc(stamp(run.finished_at)) + (run.message ? ' — ' + esc(run.message) : '') : ' and still running.') : 'Not run yet.') +
            (d.root ? ' Folder <code>' + esc(d.root) + '</code>.' : '') + '</p>' +
            (steps.length ? '<ol class="bot-steps">' + steps.map((s, i) => {
                const c = STEP_CHIP[s.state] || ['', s.state];
                const live = s.state === 'running' && s.started_at ? Math.round((Date.now() - new Date(s.started_at)) / 1000) : s.secs;
                return '<li class="bot-step is-' + esc(s.state) + '"><span class="bot-step-n">' + (i + 1) + '</span><div class="bot-step-main"><b>' + esc(s.label) + '</b><small>' + esc(s.script) +
                    (s.rc != null && s.state !== 'ok' ? ' · exit ' + esc(s.rc) : '') + '</small>' +
                    ((s.tail || []).length ? '<pre class="bot-step-tail">' + esc(s.tail.join('\n')) + '</pre>' : '') + '</div>' +
                    '<span class="bot-step-time">' + esc(dur(live)) + '</span><span class="kw-chip ' + c[0] + '">' + c[1] + '</span></li>';
            }).join('') + '</ol>' : '<p class="bot-muted">The steps appear after the first run.</p>');
    }
    function renderDetect(st) {
        const db = st.db || {};
        const stale = db.last_run && (Date.now() - new Date(db.last_run).getTime()) > 6 * 3600e3;
        const setup = (current().detail || {}).setup;
        $('botView').innerHTML =
            (setup ? '<p class="bot-alert is-warn">' + esc(setup) + '</p>' : '') +
            (db.error ? '<p class="bot-alert is-bad">Database: ' + esc(db.error) + '</p>' : '') +
            '<div class="kw-kpis bot-kpis">' +
            kpi('Latest screening in DB', db.last_run ? ago(db.last_run) : '—', db.last_run ? stamp(db.last_run) + ' · any DETECT instance' : '', stale ? 'is-bad' : '') +
            kpi('Last 24 h', db.screened_24h != null ? db.screened_24h + ' screened' : '—',
                db.screened_24h != null ? db.confirmed_24h + ' confirmed · ' + db.review_24h + ' review · ' + db.none_24h + ' none' + (db.history_rows_24h != null ? ' · ' + db.history_rows_24h + ' history rows' : '') : '', '') +
            kpi('Waiting for a person', db.pending_review != null ? db.pending_review : '—', 'Inbox objects with a host verdict (7 d) · ' + (db.followups != null ? db.followups + ' in Follow-up' : ''), db.pending_review > 0 ? 'is-warn' : '') +
            kpi('Other writers', db.legacy_rows_24h > 0 ? db.legacy_rows_24h + ' legacy rows' : 'none',
                db.legacy_rows_24h > 0 ? 'cross_matches rows without rule v1 data in 24 h: an old DETECT still runs somewhere' : 'no cross_matches without rule v1 data in 24 h', db.legacy_rows_24h > 0 ? 'is-bad' : '') +
            '</div>' +
            '<dl class="bot-paths">' +
            '<div><dt>Code</dt><dd>' + esc(st.code_present ? (st.version && st.version.synced ? 'synced ' + st.version.synced.slice(0, 10) : 'present') : 'missing') + '</dd></div>' +
            '<div><dt>SFD dust maps</dt><dd>' + (st.sfd_maps ? 'present' : 'missing (fetched on first use)') + '</dd></div>' +
            '<div><dt>Data folder</dt><dd class="sys-mono">' + esc(st.data_dir || '—') + '</dd></div>' +
            (st.running ? '<div><dt>Running now</dt><dd>' + esc(st.running.label) + (st.running.objects != null ? ' · ' + st.running.objects + ' objects' : '') + '</dd></div>' : '') +
            '</dl>' +
            '<h3>Run it now</h3>' +
            '<p class="kw-panel-desc">The hourly TNS import and the daily 04:00 UTC job start DETECT on their own. Only one run goes at a time; another request is refused until it finishes.</p>' +
            '<div class="bot-detect-run">' +
            '<button type="button" class="kw-btn kw-btn-sm" data-detect-run="followups" title="Re-screen every Follow-up object now">Re-screen Follow-ups</button>' +
            '<button type="button" class="kw-btn kw-btn-sm" data-detect-run="recent" title="Objects TNS touched in the last 2 hours">Recent (2 h)</button>' +
            '<span class="bot-detect-names"><input type="text" id="detectNames" placeholder="2026abdm, 2026abnn" aria-label="Object names" spellcheck="false">' +
            '<button type="button" class="kw-btn kw-btn-sm kw-btn-tinted" data-detect-run="names">Run on objects</button></span>' +
            '<span id="detectRunMsg" class="bot-muted"></span></div>';
    }
    function size(n) {
        if (n == null) return '—';
        if (n >= 1e12) return (n / 1e12).toFixed(2) + ' TB';
        if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB';
        if (n >= 1e6) return (n / 1e6).toFixed(0) + ' MB';
        return Math.round(n / 1e3) + ' kB';
    }
    function renderMoves(o) {
        if (tab !== 'moves') return;
        const counts = Object.entries(o.pending_counts || {});
        const moves = o.moves || [], pending = o.pending || [];
        const npend = counts.reduce((a, c) => a + c[1], 0);
        const inside = (m) => m.path.indexOf(m.folder + '/') === 0 ? m.path.slice(m.folder.length + 1) : m.path;
        $('botView').innerHTML =
            (o.problem ? '<p class="bot-alert is-warn">' + esc(o.problem) + '</p>' : '') +
            (o.busy ? '<p class="bot-alert is-info"><b>Pipeline busy:</b> ' + esc(o.busy) + ' — a run now is skipped.</p>' : '') +
            (o.dry_run ? '<p class="bot-alert is-info">NAS_ARCHIVE_DRY_RUN is on: runs only log what they would move.</p>' : '') +
            '<div class="kw-kpis bot-kpis">' +
            kpi('Moved, last 30 days', size(o.month.bytes), o.month.items + ' items · ' + o.month.files + ' files', '') +
            kpi('Last move', moves.length ? ago(moves[0].at) : '—', moves.length ? stamp(moves[0].at) + ' · ' + moves[0].path : 'nothing moved yet', '') +
            kpi('Next run would move', npend ? size(o.pending_bytes) + (npend > pending.length ? '+' : '') : 'nothing', counts.map((c) => c[1] + ' ' + c[0]).join(' · ') || 'all within the rules', '') +
            '</div>' +
            '<dl class="bot-paths"><div><dt>From</dt><dd class="sys-mono">' + esc(o.root || '—') + '</dd></div>' +
            '<div><dt>To</dt><dd class="sys-mono">' + esc(o.target || '—') + '</dd></div>' +
            '<div><dt>Schedule</dt><dd>Every ' + o.interval_min + ' min, up to ' + o.budget_min + ' min of copying per run</dd></div></dl>' +
            '<h3>Recently moved</h3>' +
            (moves.length ? '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>When</th><th>Folder</th><th>Moved</th><th>Files</th><th>Size</th></tr></thead><tbody>' +
                moves.map((m) => '<tr><td class="bot-nowrap" title="' + esc(stamp(m.at)) + '">' + esc(ago(m.at)) + '</td><td>' + esc(m.folder) + '</td><td class="sys-mono bot-wrap">' + esc(inside(m)) +
                    (m.finished ? '' : ' <span class="kw-chip kw-chip-gold">partial</span>') + '</td><td>' + m.files + '</td><td class="bot-nowrap">' + size(m.bytes) + '</td></tr>').join('') +
                '</tbody></table></div>' : '<p class="bot-muted">Nothing moved yet.</p>') +
            '<h3>Next to move</h3>' +
            (pending.length ? '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>Folder</th><th>Path</th><th>Size</th></tr></thead><tbody>' +
                pending.map((m) => '<tr><td>' + esc(m.folder) + '</td><td class="sys-mono bot-wrap">' + esc(inside(m)) + '</td><td class="bot-nowrap">' + size(m.bytes) + '</td></tr>').join('') +
                '</tbody></table></div>' + (npend > pending.length ? '<p class="bot-muted">…and ' + (npend - pending.length) + ' more.</p>' : '')
                : '<p class="bot-muted">Nothing is old enough to move.</p>') +
            '<p class="bot-muted">Rules: raw nights not from this month or last month; dated masters older than 30 days (the newest of each setup stays); calibrated targets with no new frame for 60 days. Nothing moves while its raw frames are still here.</p>';
    }
    function renderFolders(o) {
        const rows = (list, empty) => list.length ? '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>Folder</th><th>FITS</th><th>Changed</th></tr></thead><tbody>' +
            list.map((x) => '<tr><td class="sys-mono">' + esc(x.name) + '</td><td>' + x.frames + '</td><td title="' + esc(stamp(x.modified)) + '">' + esc(ago(x.modified)) + '</td></tr>').join('') + '</tbody></table></div>'
            : '<p class="bot-muted">' + empty + '</p>';
        const ext = o.external || [];
        $('botView').innerHTML =
            (o.problem ? '<p class="bot-alert is-warn">' + esc(o.problem) + '</p>' : '') +
            (ext.length ? '<p class="bot-alert is-info"><b>Running outside Kinder:</b> ' + ext.map((x) => esc(x.script) + ' (pid ' + x.pid + (x.user ? ', ' + esc(x.user) : '') + ', since ' + esc(stamp(x.since)) + ')').join(' · ') + '</p>' : '') +
            '<dl class="bot-paths"><div><dt>Folder</dt><dd class="sys-mono">' + esc(o.root || '—') + '</dd></div>' +
            '<div><dt>Python</dt><dd class="sys-mono">' + esc(o.python || 'not found') + '</dd></div>' +
            '<div><dt>Schedule</dt><dd>' + esc(o.schedule) + (o.skip_sync ? ' · download step skipped' : '') + '</dd></div>' +
            '<div><dt>Last activity</dt><dd title="' + esc(stamp(o.activity)) + '">' + esc(o.activity ? ago(o.activity) + ' (' + stamp(o.activity) + ')' : '—') + '</dd></div>' +
            (o.masters ? '<div><dt>Master frames</dt><dd>' + o.masters.files + ' in MasterBDF, newest ' + esc(ago(o.masters.newest)) + '</dd></div>' : '') +
            '</dl>' +
            ((o.problems || []).length ? '<h3>Problem folders</h3><div class="bot-files">' + o.problems.map((x) =>
                '<span class="bot-file' + (x.files ? ' is-warn' : '') + '" title="' + esc(x.path) + ' · changed ' + esc(stamp(x.modified)) + '">' + esc(x.label) + ': <b>' + x.files + '</b></span>').join('') + '</div>' : '') +
            '<div class="bot-two"><div><h3>Newest raw nights</h3>' + rows(o.raw, 'No raw nights found.') + '</div>' +
            '<div><h3>Newest calibrated sets</h3>' + rows(o.calibrated, 'No calibrated folders found.') + '</div></div>' +
            (o.crontab ? '<h3>Schedule on the server (crontab_setup.txt)</h3><pre class="bot-step-tail bot-cron">' + esc(o.crontab) + '</pre>' : '') +
            (o.folders.length ? '<h3>In the reduction folder</h3><div class="bot-files">' + o.folders.map((f) =>
                '<span class="bot-file' + (f.dir ? ' is-dir' : '') + '" title="' + esc(stamp(f.modified)) + '">' + esc(f.name) + (f.dir ? '/' : '') + '</span>').join('') + '</div>' : '');
    }

    // ── log ────────────────────────────────────────────────────────────────
    function lineClass(l) {
        if (/ (ERROR|CRITICAL) /.test(l) || /Traceback|Error:/.test(l)) return 'lv-err';
        if (/ WARNING /.test(l)) return 'lv-warn';
        if (/ INFO ── /.test(l)) return 'lv-head';
        return '';
    }
    function appendLog(text, reset) {
        const pre = $('botLog');
        if (!pre) return;
        if (reset) pre.innerHTML = '';
        if (!text) return;
        const html = text.split('\n').filter((l) => l !== '').map((l) => '<span class="' + lineClass(l) + '">' + esc(l) + '\n</span>').join('');
        pre.insertAdjacentHTML('beforeend', html);
        while (pre.textContent.length > MAX_LOG_CHARS && pre.firstChild) pre.removeChild(pre.firstChild);
    }
    function scrollLog() { const p = $('botLog'); if (p) p.scrollTop = p.scrollHeight; }
    function stopLog() { clearTimeout(logTimer); logTimer = null; }
    function pollLog() {
        stopLog();
        const id = sel;
        if (tab !== 'log' || !id) return;
        getJSON('/admin/bots/' + id + '/log' + (logOffset != null ? '?offset=' + logOffset : '')).then((d) => {
            if (id !== sel || tab !== 'log') return;
            const first = logOffset == null;
            appendLog(d.text, first || d.reset);
            logOffset = d.offset;
            const pre = $('botLog');
            if (first && pre && !pre.textContent) pre.innerHTML = '<span class="bot-muted">Nothing logged yet.\n</span>';
            $('botLogMeta').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            if ($('botFollow') && $('botFollow').checked) scrollLog();
        }).catch((e) => { const m = $('botLogMeta'); if (m) m.textContent = 'Could not read the log: ' + e.message; })
            .finally(() => {
                if (id === sel && tab === 'log' && $('botFollow') && $('botFollow').checked) logTimer = setTimeout(pollLog, document.hidden ? 15000 : 3000);
            });
    }

    // ── status polling ─────────────────────────────────────────────────────
    let statusTimer = null;
    function refresh() {
        clearTimeout(statusTimer);
        return getJSON('/admin/bots/status').then((d) => {
            bots = d.bots || [];
            renderTop(); renderCards();
            if (!sel) {
                const hash = (location.hash || '').slice(1).split('/');
                const first = bots.find((b) => b.health === 'bad' || b.health === 'warn') || bots[0];
                select(bots.some((b) => b.id === hash[0]) ? hash[0] : first && first.id, hash[1]);
            } else if (tab === 'events' || tab === 'steps' || tab === 'nights') {
                renderView(false);
            }
        }).catch((e) => {
            const pill = $('botState');
            pill.className = 'sys-pill is-bad';
            pill.querySelector('b').textContent = 'Could not load: ' + e.message;
        }).finally(() => { statusTimer = setTimeout(refresh, document.hidden ? 30000 : 10000); });
    }

    // ── events ─────────────────────────────────────────────────────────────
    $('botCards').addEventListener('click', (ev) => {
        const btn = ev.target.closest('button[data-act]');
        if (!btn) return;
        const id = btn.dataset.bot;
        if (btn.dataset.act === 'open') {
            select(id);
            $('botDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
        const stop = btn.dataset.act === 'stop';
        if (stop && !confirm('Stop the reduction pipeline? The running step is killed and the rest are skipped.')) return;
        busy[id] = true;
        btn.disabled = true;
        btn.textContent = stop ? 'Stopping…' : 'Starting…';
        post(stop ? '/admin/bots/reduction/stop' : '/admin/bots/' + id + '/run' + (btn.dataset.kind ? '?kind=' + btn.dataset.kind : '')).then((r) => {
            if (!r.ok) alert(r.d.error || 'Failed');
            if (sel !== id) select(id, 'log'); else { logOffset = null; renderView(true); }
        }).catch((e) => alert(e.message)).finally(() => { busy[id] = false; setTimeout(refresh, 800); });
    });
    $('botView').addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-detect-run]');
        if (!b) return;
        const body = { kind: b.dataset.detectRun };
        if (body.kind === 'names') body.names = ($('detectNames').value || '').trim();
        if (body.kind === 'recent') body.hours = 2;
        const msg = $('detectRunMsg');
        b.disabled = true;
        msg.className = 'bot-muted'; msg.textContent = 'Starting…';
        fetch('/admin/detect-run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then((r) => r.json().then((d) => ({ ok: r.ok && d.success, d })))
            .then((r) => { msg.className = r.ok ? 'bot-good' : 'bot-bad'; msg.textContent = r.d.message || (r.ok ? 'Started' : 'Failed'); setTimeout(refresh, 1500); })
            .catch((e) => { msg.className = 'bot-bad'; msg.textContent = e.message; })
            .finally(() => { b.disabled = false; });
    });
    $('botPick').addEventListener('click', (ev) => { const b = ev.target.closest('[data-bot]'); if (b) select(b.dataset.bot); });
    $('botTabs').addEventListener('click', (ev) => { const t = ev.target.closest('[data-tab]'); if (t) select(sel, t.dataset.tab); });
    $('botRefresh').addEventListener('click', () => { refresh(); if (tab !== 'log') renderView(true); });
    window.addEventListener('hashchange', () => {
        const h = (location.hash || '').slice(1).split('/');
        if (h[0] && (h[0] !== sel || (h[1] && h[1] !== tab))) select(h[0], h[1]);
    });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { refresh(); if (tab === 'log') pollLog(); } });

    renderTop(); renderCards();
    refresh();
})();
