// Lab › Calendar (/lab_calendar): draws the month view (one month at a time) and the list from <script id="lcData">,
// and runs the event, add / edit and subscribe dialogs and the calls to /api/lab_calendar/*.
// lcData = {series: {db_id: shared fields}, occ: [[id, db_id, date, end_date, time_label, start, end], …], today, …}
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const page = $('lcPage');
    if (!page) return;
    let DATA = { series: {}, occ: [] };
    try { DATA = JSON.parse($('lcData').textContent) || DATA; } catch (e) { /* empty calendar */ }
    const ME = page.dataset.email, IS_ADMIN = !!page.dataset.admin, TODAY = DATA.today;
    // One object per occurrence: the series fields plus this occurrence's dates
    const EVENTS = {}, OCC = [];
    DATA.occ.forEach((o) => {
        const s = DATA.series[o[1]];
        if (!s) return;
        const e = Object.assign({}, s, { id: o[0], db_id: o[1], date: o[2], end_date: o[3], time_label: o[4], start: o[5], end: o[6] });
        e.is_past = e.end_date < TODAY;
        e.is_today = e.date <= TODAY && TODAY <= e.end_date;
        EVENTS[e.id] = e;
        OCC.push(e);
    });
    const store = {
        get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
        set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
    };

    function toast(msg, type) {
        const n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => { n.style.animation = 'notificationSlideOut 0.25s forwards'; setTimeout(() => n.remove(), 260); }, 2800);
    }
    function api(url, method, body) {
        return fetch(url, {
            method: method || 'GET', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        }).then((r) => r.json().catch(() => ({})).then((d) => {
            if (!r.ok || d.success === false) throw new Error(d.error || ('HTTP ' + r.status));
            return d;
        }));
    }

    // ── dates (strings are Taiwan dates, so no time-zone maths in the browser) ──
    const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const parts = (iso) => iso.slice(0, 10).split('-').map(Number);
    const asUTC = (iso) => { const p = parts(iso); return new Date(Date.UTC(p[0], p[1] - 1, p[2])); };
    const fmtDay = (iso) => { const d = asUTC(iso); return WD[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); };
    const addDays = (iso, n) => { const d = asUTC(iso); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
    function whenText(e) {
        const range = e.end_date !== e.date ? fmtDay(e.date) + ' – ' + fmtDay(e.end_date) : fmtDay(e.date);
        if (e.all_day) return range + ' · all day';
        return e.end_date !== e.date ? fmtDay(e.date) + ' ' + e.start.slice(11, 16) + ' – ' + fmtDay(e.end_date) + ' ' + e.end.slice(11, 16)
            : range + ' · ' + e.time_label;
    }
    const lc = (x) => String(x || '').toLowerCase();
    const canEdit = (e) => e.source === 'lab' && (IS_ADMIN || lc(e.created_by) === lc(ME) || (e.assignee_email && lc(e.assignee_email) === lc(ME)));
    // Trigger duty: when the sunset push for one night went out (or why not)
    function dutyNote(e) {
        if (e.category !== 'trigger' || !e.assignee_email) return '';
        const r = (DATA.reminders || {})[TODAY + '|' + e.assignee_email];
        const OUT = { sent: (n) => 'Reminder pushed to ' + n + ' device' + (n === 1 ? '' : 's') + ' at sunset',
            already_sent: () => 'No reminder needed: the SLT trigger was already sent', no_device: () => 'Not reminded: no device with Trigger reminders on',
            pending: () => 'Sending the reminder…' };
        if (e.is_today && r) return OUT[r.outcome] ? OUT[r.outcome](r.devices) : '';
        if (e.is_today) return 'Push reminder at Lulin sunset tonight, ' + DATA.sunset_today;
        if (!e.is_past) return 'Push reminder at Lulin sunset on each night of the duty';
        return '';
    }

    // ── dialogs ──
    let lastFocus = null;
    function openModal(m) { lastFocus = document.activeElement; m.style.display = 'block'; const f = m.querySelector('input:not([type=hidden]), button'); if (f) f.focus({ preventScroll: true }); }
    function closeModal(m) { m.style.display = 'none'; if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); }
    document.querySelectorAll('.kw-modal').forEach((m) => {
        m.addEventListener('click', (ev) => { if (ev.target === m || ev.target.closest('[data-close]')) closeModal(m); });
    });
    document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Escape') return;
        document.querySelectorAll('.kw-modal').forEach((m) => { if (m.style.display === 'block') closeModal(m); });
    });

    // ── event details ──
    const IC = {
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
        repeat: '<path d="M4 12V9a3 3 0 0 1 3-3h13l-3-3M20 12v3a3 3 0 0 1-3 3H4l3 3"/>',
        user: '<circle cx="12" cy="8" r="4"/><path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/>',
        bell: '<path d="M10 5a2 2 0 1 1 4 0 7 7 0 0 1 4 6v3a4 4 0 0 0 2 3H4a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6"/><path d="M9 17v1a3 3 0 0 0 6 0v-1"/>',
        pin: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
        link: '<path d="M10 14a3.5 3.5 0 0 0 5 0l4-4a3.5 3.5 0 0 0-5-5l-.5.5"/><path d="M14 10a3.5 3.5 0 0 0-5 0l-4 4a3.5 3.5 0 0 0 5 5l.5-.5"/>',
    };
    const svg = (k) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + IC[k] + '</svg>';
    function showEvent(id) {
        const e = EVENTS[id];
        if (!e) return;
        $('lcEvTitle').textContent = e.title;
        let h = '<p><span class="lc-chip lc-c-' + esc(e.color) + '">' + esc(e.category_label) + '</span></p><div class="lc-ev-meta">';
        if (e.assignee_name) h += svg('user') + '<span>On duty: <b>' + esc(e.assignee_name) + '</b>' + (lc(e.assignee_email) === lc(ME) ? ' (you)' : '') + '</span>';
        h += svg('clock') + '<span>' + esc(whenText(e)) + '</span>';
        const dn = dutyNote(e);
        if (dn) h += svg('bell') + '<span>' + esc(dn) + '</span>';
        if (e.repeat) h += svg('repeat') + '<span>' + esc(e.repeat_label) + (e.repeat_until ? ' until ' + esc(fmtDay(e.repeat_until)) : '') + '</span>';
        if (e.location) h += svg('pin') + '<span>' + esc(e.location) + '</span>';
        if (e.url) h += svg('link') + '<a href="' + esc(e.url) + '" target="_blank" rel="noopener noreferrer">' + esc(e.url) + '</a>';
        h += '</div>';
        if (e.description) h += '<p class="lc-ev-desc">' + esc(e.description) + '</p>';
        if (e.source === 'lulin') h += '<p class="lc-ev-by">From the Lulin LOT schedule (Lulin TAC calendar). It is read only here.</p>';
        else if (e.created_by_name) h += '<p class="lc-ev-by">Added by ' + esc(e.created_by_name) + '</p>';
        $('lcEvBody').innerHTML = h;
        let a = '<a class="kw-btn" href="/lab_calendar/event/' + e.db_id + '.ics" title="Imports this one event; it will not update">Add to my calendar</a><span class="lc-spacer"></span>';
        if (canEdit(e)) a += '<button type="button" class="kw-btn kw-btn-danger" data-act="delete">Delete</button><button type="button" class="kw-btn kw-btn-primary" data-act="edit">Edit</button>';
        else a += '<button type="button" class="kw-btn" data-close>Close</button>';
        const box = $('lcEvActions');
        box.innerHTML = a;
        box.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => {
            closeModal($('lcEvModal'));
            if (b.dataset.act === 'edit') openForm(e); else removeEvent(e);
        }));
        openModal($('lcEvModal'));
    }
    document.addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-ev]');
        if (b) { ev.preventDefault(); ev.stopPropagation(); showEvent(b.dataset.ev); }
    });

    // ── add / edit ──
    const form = $('lcForm');
    const F = (n) => form.elements[n];
    function syncForm() {
        const duty = F('category').value === 'trigger';
        form.classList.toggle('is-duty', duty);
        form.classList.toggle('is-allday', duty || F('all_day').checked);
        F('title').placeholder = duty ? 'Optional (default: Trigger: <name>)' : 'e.g. Group meeting';
        $('lcFUntilWrap').hidden = !F('repeat').value;
    }
    F('all_day').addEventListener('change', syncForm);
    F('category').addEventListener('change', syncForm);
    F('repeat').addEventListener('change', syncForm);
    F('date').addEventListener('change', () => { if (!F('end_date').value || F('end_date').value < F('date').value) F('end_date').value = F('date').value; });
    F('start_time').addEventListener('change', () => {
        // keep a one-hour slot when the end was not moved yet
        const [h, m] = F('start_time').value.split(':').map(Number);
        if (isNaN(h) || F('end_date').value !== F('date').value) return;
        if (!F('end_time').value || F('end_time').value <= F('start_time').value) F('end_time').value = String(Math.min(23, h + 1)).padStart(2, '0') + ':' + String(m).padStart(2, '0');
    });
    function openForm(e, date, category) {
        form.reset();
        $('lcFormErr').hidden = true;
        F('id').value = e ? e.db_id : '';
        $('lcFormTitle').textContent = e ? 'Edit event' : 'Add event';
        $('lcFormDelete').hidden = !e;
        $('lcFormNote').hidden = !(e && e.repeat);
        if (e) {
            F('title').value = e.title;
            F('category').value = e.category;
            F('all_day').checked = e.all_day;
            F('date').value = e.series_start.slice(0, 10);
            F('end_date').value = e.all_day ? addDays(e.series_end.slice(0, 10), -1) : e.series_end.slice(0, 10);
            if (e.all_day && F('end_date').value < F('date').value) F('end_date').value = F('date').value;
            if (!e.all_day) { F('start_time').value = e.series_start.slice(11, 16); F('end_time').value = e.series_end.slice(11, 16); }
            F('assignee').value = e.assignee_email || '';
            F('repeat').value = e.repeat || '';
            F('repeat_until').value = e.repeat_until || '';
            F('location').value = e.location;
            F('url').value = e.url;
            F('description').value = e.description;
        } else {
            F('date').value = F('end_date').value = date || TODAY;
            if (category) F('category').value = category;
        }
        syncForm();
        openModal($('lcFormModal'));
        (F('category').value === 'trigger' && !F('assignee').value ? F('assignee') : F('title')).focus();
    }
    $('lcAddOpen').addEventListener('click', () => openForm(null));
    if ($('lcDutyAdd')) $('lcDutyAdd').addEventListener('click', () => openForm(null, TODAY, 'trigger'));
    $('lcFormDelete').addEventListener('click', () => {
        const e = Object.values(EVENTS).find((x) => String(x.db_id) === F('id').value);
        if (e) { closeModal($('lcFormModal')); removeEvent(e); }
    });
    form.addEventListener('submit', (ev) => {
        ev.preventDefault();
        const body = {
            title: F('title').value, category: F('category').value, all_day: F('all_day').checked, assignee: F('assignee').value,
            date: F('date').value, end_date: F('end_date').value || F('date').value,
            start_time: F('start_time').value, end_time: F('end_time').value,
            repeat: F('repeat').value, repeat_until: F('repeat').value ? F('repeat_until').value : '',
            location: F('location').value, url: F('url').value, description: F('description').value,
        };
        const id = F('id').value;
        const save = $('lcFormSave');
        save.disabled = true;
        api(id ? '/api/lab_calendar/events/' + id : '/api/lab_calendar/events', 'POST', body)
            .then(() => { store.set('kinder-lc-month', body.date.slice(0, 7)); location.reload(); })
            .catch((err) => { $('lcFormErr').textContent = err.message; $('lcFormErr').hidden = false; save.disabled = false; });
    });
    function removeEvent(e) {
        if (!confirm('Delete "' + e.title + '"' + (e.repeat ? ' and every occurrence of it' : '') + '?')) return;
        api('/api/lab_calendar/events/' + e.db_id, 'DELETE').then(() => location.reload()).catch((err) => toast(err.message, 'error'));
    }

    // ── month view ──
    const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    const monthKey = (y, m) => y + '-' + String(m).padStart(2, '0');
    const nextKey = (key, n) => { const p = key.split('-').map(Number), d = new Date(Date.UTC(p[0], p[1] - 1 + n, 1)); return monthKey(d.getUTCFullYear(), d.getUTCMonth() + 1); };
    const FIRST = DATA.first_month || DATA.this_month, LAST = DATA.last_month || DATA.this_month;
    const byDay = {};       // 'YYYY-MM-DD' → occurrences on that day (an event spanning days sits on each)
    OCC.forEach((e) => {
        for (let d = e.date, n = 0; d <= e.end_date && n < 63; d = addDays(d, 1), n++) (byDay[d] = byDay[d] || []).push(e);
    });
    // in a day cell the group's own events come first, then the Lulin schedule
    Object.values(byDay).forEach((l) => l.sort((a, b) => (a.source === 'lab' ? 0 : 1) - (b.source === 'lab' ? 0 : 1)));
    function evButton(e, day) {
        const start = e.time_label && day === e.date ? '<b>' + esc(e.time_label.split('–')[0].trim()) + '</b> ' : '';
        const tip = e.title + (e.time_label ? ' · ' + e.time_label : '') + (e.location ? ' · ' + e.location : '');
        return '<button type="button" class="lc-cal-ev lc-c-' + esc(e.color) + (e.source === 'lulin' ? ' is-lulin' : '') + '" data-ev="' + esc(e.id) + '" title="' + esc(tip) + '">' +
            start + (e.source === 'lulin' ? '<i>LOT</i> ' : '') + esc(e.title) + '</button>';
    }
    let shown = DATA.this_month;
    function showMonth(key) {
        shown = key < FIRST ? FIRST : key > LAST ? LAST : key;
        const p = shown.split('-').map(Number);
        const first = new Date(Date.UTC(p[0], p[1] - 1, 1));
        let d = addDays(shown + '-01', -((first.getUTCDay() + 6) % 7));     // the Monday on or before the 1st
        let h = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((w, i) => '<div class="lc-cal-wd' + (i > 4 ? ' is-we' : '') + '" role="columnheader">' + w + '</div>').join('');
        do {
            for (let i = 0; i < 7; i++, d = addDays(d, 1)) {
                const inMonth = d.slice(0, 7) === shown;
                const cls = 'lc-cal-cell' + (inMonth ? '' : ' is-out') + (d === TODAY ? ' is-today' : d < TODAY ? ' is-past' : '');
                h += '<div class="' + cls + '" data-date="' + d + '" role="gridcell"><span class="lc-cal-num">' + Number(d.slice(8)) + '</span>' +
                    (inMonth ? (byDay[d] || []).map((e) => evButton(e, d)).join('') : '') + '</div>';
            }
        } while (d.slice(0, 7) === shown);
        $('lcCalGrid').innerHTML = h;
        $('lcPagerTitle').textContent = MONTHS[p[1] - 1] + ' ' + p[0];
        $('lcPrev').disabled = shown <= FIRST;
        $('lcNext').disabled = shown >= LAST;
    }
    $('lcPrev').addEventListener('click', () => showMonth(nextKey(shown, -1)));
    $('lcNext').addEventListener('click', () => showMonth(nextKey(shown, 1)));
    $('lcToday').addEventListener('click', () => showMonth(DATA.this_month));
    const remembered = store.get('kinder-lc-month');   // the month an event was just saved in
    store.set('kinder-lc-month', '');
    showMonth(/^\d{4}-\d{2}$/.test(remembered || '') ? remembered : DATA.this_month);
    $('lcGrid').addEventListener('click', (ev) => {
        const cell = ev.target.closest('.lc-cal-cell');
        if (cell && !cell.classList.contains('is-out') && !ev.target.closest('[data-ev]')) openForm(null, cell.dataset.date);
    });

    // ── list (drawn the first time it is shown) ──
    const PIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + IC.pin + '</svg>';
    const REP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + IC.repeat + '</svg>';
    const daysLeft = (iso) => Math.round((asUTC(iso) - asUTC(TODAY)) / 864e5);
    function card(e) {
        const d = asUTC(e.date), left = daysLeft(e.date);
        const rem = e.is_today ? 'Today' : e.is_past ? (-left) + ' d ago' : left === 1 ? 'Tomorrow' : 'in ' + left + ' d';
        const until = e.end_date !== e.date ? 'until ' + fmtDay(e.end_date).slice(0, -5) : '';
        const loc = e.location ? PIN + esc(e.location) + (until ? ' · ' + until : '') : until;
        return '<article id="ev-' + esc(e.id) + '" class="lc-card' + (e.is_past ? ' is-past' : '') + (e.is_today ? ' is-today' : '') + '">' +
            '<div class="lc-card-date"><span class="lc-card-day">' + d.getUTCDate() + '</span><span class="lc-card-wd">' + WD[d.getUTCDay()] + '</span></div>' +
            '<div class="lc-card-body"><div class="lc-card-top"><span class="lc-chip lc-c-' + esc(e.color) + '">' + esc(e.category_label) + '</span>' +
            (e.time_label ? '<span class="lc-time">' + esc(e.time_label) + '</span>' : '') +
            (e.repeat ? '<span class="lc-time">' + REP + esc(e.repeat_label) + '</span>' : '') +
            '<span class="lc-remaining">' + rem + '</span></div>' +
            '<h3 class="lc-card-title"><button type="button" data-ev="' + esc(e.id) + '">' + esc(e.title) + '</button></h3>' +
            (e.description ? '<p class="lc-card-desc">' + esc(e.description) + '</p>' : '') +
            (loc ? '<p class="lc-card-loc">' + loc + '</p>' : '') + '</div></article>';
    }
    let listDrawn = false;
    function drawList() {
        listDrawn = true;
        const groups = [];
        OCC.forEach((e) => {
            const k = e.date.slice(0, 7);
            if (!groups.length || groups[groups.length - 1].k !== k) groups.push({ k, items: [] });
            groups[groups.length - 1].items.push(e);
        });
        $('lcList').innerHTML = groups.length ? groups.map((g) => {
            const p = g.k.split('-').map(Number), n = g.items.length;
            return '<section class="kw-panel lc-month' + (g.items.every((e) => e.is_past) ? ' is-all-past' : '') + '">' +
                '<header class="lc-month-head"><span class="lc-month-num">' + String(p[1]).padStart(2, '0') + '</span><div>' +
                '<h2 class="lc-month-name">' + MONTHS[p[1] - 1] + ' ' + p[0] + '</h2><div class="lc-month-count">' + n + ' event' + (n === 1 ? '' : 's') + '</div></div></header>' +
                '<div class="lc-list">' + g.items.map(card).join('') + '</div></section>';
        }).join('') : '<section class="kw-panel"><p class="kw-empty">No matching events. <a href="/lab_calendar">Clear filters</a></p></section>';
    }

    // ── list / month, past events ──
    const grid = $('lcGrid'), list = $('lcList'), past = $('lcShowPast');
    function setView(v) {
        if (v === 'list' && !listDrawn) drawList();
        grid.hidden = v !== 'month';
        list.hidden = v === 'month';
        if (past) $('lcPastWrap').hidden = v === 'month';
        document.querySelectorAll('[data-view]').forEach((b) => b.classList.toggle('is-on', b.dataset.view === v));
        store.set('kinder-lc-view', v);
    }
    document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
    if (past) {
        past.checked = store.get('kinder-lc-past') === '1';
        list.classList.toggle('hide-past', !past.checked);
        past.addEventListener('change', () => { list.classList.toggle('hide-past', !past.checked); store.set('kinder-lc-past', past.checked ? '1' : '0'); });
    }
    const q = new URLSearchParams(location.search);
    setView(q.get('q') ? 'list' : (store.get('kinder-lc-view') === 'list' ? 'list' : 'month'));

    // ── Lulin sync ──
    const syncBtn = $('lcSyncNow');
    if (syncBtn) syncBtn.addEventListener('click', () => {
        syncBtn.disabled = true;
        syncBtn.textContent = 'Syncing…';
        api('/api/lab_calendar/sync', 'POST', {})
            .then((d) => { toast('Lulin schedule synced: ' + d.added + ' new, ' + d.updated + ' changed, ' + d.removed + ' removed', 'success'); setTimeout(() => location.reload(), 900); })
            .catch((err) => { toast(err.message, 'error'); syncBtn.disabled = false; syncBtn.textContent = 'Sync now'; });
    });

    // ── subscribe ──
    const sub = $('lcSubModal');
    let feed = null, src = '';
    function applyFeed() {
        if (!feed) return;
        const suffix = src ? '?src=' + src : '';
        const http = feed.http + suffix, webcal = feed.webcal + suffix;
        sub.querySelector('[data-sub="google"]').href = 'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(webcal);
        sub.querySelector('[data-sub="apple"]').href = webcal;
        sub.querySelector('[data-sub="outlook"]').href = 'https://outlook.live.com/calendar/0/addfromweb?url=' + encodeURIComponent(http) + '&name=' + encodeURIComponent('GREAT Lab Calendar');
        $('lcFeedUrl').value = http;
        $('lcSubList').setAttribute('aria-busy', 'false');
    }
    function loadFeed(reset) {
        $('lcSubList').setAttribute('aria-busy', 'true');
        return api('/api/lab_calendar/feed_link', 'POST', { reset: !!reset })
            .then((d) => { feed = d; applyFeed(); })
            .catch((err) => toast(err.message, 'error'));
    }
    $('lcSubscribeOpen').addEventListener('click', () => { openModal(sub); if (!feed) loadFeed(false); });
    sub.querySelectorAll('[data-src]').forEach((b) => b.addEventListener('click', () => {
        src = b.dataset.src;
        sub.querySelectorAll('[data-src]').forEach((x) => x.classList.toggle('is-on', x === b));
        applyFeed();
    }));
    $('lcFeedCopy').addEventListener('click', () => {
        const inp = $('lcFeedUrl');
        if (!inp.value) return;
        (navigator.clipboard ? navigator.clipboard.writeText(inp.value) : Promise.reject())
            .catch(() => { inp.select(); document.execCommand('copy'); })
            .then(() => toast('Link copied', 'success'));
    });
    $('lcFeedReset').addEventListener('click', () => {
        if (!confirm('Make a new link? Calendars subscribed with the old one stop updating.')) return;
        loadFeed(true).then(() => toast('New link made: subscribe again with it', 'success'));
    });
})();
