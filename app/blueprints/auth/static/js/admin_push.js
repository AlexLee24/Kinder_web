// Admin › Push (/admin/push): the people list (push on / off, devices, test, remove), picking people, the compose
// form with its estimate and phone preview, and Reuse in the history. Data: <script id="apPeople"> (admin/push.py).
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const page = $('apPage');
    if (!page) return;
    let PEOPLE = [];
    try { PEOPLE = JSON.parse($('apPeople').textContent) || []; } catch (e) { /* empty */ }
    let CATS = {};
    try { (JSON.parse($('apCategories').textContent) || []).forEach((c) => { CATS[c[0]] = c[1]; }); } catch (e) { /* none */ }
    const byId = new Map(PEOPLE.map((p) => [p.usr_id, p]));
    const picked = new Set();
    const open = new Set();
    const form = $('apForm');

    function toast(msg, type) {
        const n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => { n.style.animation = 'notificationSlideOut 0.25s forwards'; setTimeout(() => n.remove(), 260); }, 3400);
    }
    function post(url, body) {
        return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify(body || {}) }).then((r) => r.json().catch(() => ({})).then((d) => { d.status = r.status; return d; }));
    }
    function ago(iso) {
        if (!iso) return '';
        const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
        if (isNaN(s)) return '';
        if (s < 60) return 'just now';
        if (s < 3600) return Math.round(s / 60) + ' min ago';
        if (s < 86400) return Math.round(s / 3600) + ' h ago';
        return Math.round(s / 86400) + ' d ago';
    }
    const day = (iso) => (iso ? new Date(iso).toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' }) : '—');
    document.querySelectorAll('time[data-local]').forEach((t) => {
        const d = new Date(t.getAttribute('datetime'));
        if (!isNaN(d)) t.textContent = d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    });

    // ── people list ──
    let filter = 'all';
    const PLAT_IC = { iPhone: '📱', iPad: '📱', Android: '🤖', Mac: '💻', Windows: '🖥️', Linux: '🐧' };
    function deviceHTML(d) {
        const health = d.fail_count ? '<span class="ap-bad">failed ' + d.fail_count + '× (' + esc(d.last_error) + '); removed after 5</span>'
            : d.last_ok_at ? 'last delivered ' + esc(ago(d.last_ok_at)) : '<span class="ap-warn-t">not delivered yet</span>';
        return '<div class="ap-dev" data-sid="' + d.id + '"><span class="ap-dev-ic" aria-hidden="true">' + (PLAT_IC[d.platform] || '🔔') + '</span>' +
            '<div class="ap-dev-main"><b>' + esc(d.platform) + ' · ' + esc(d.browser) + '</b>' +
            '<span class="ap-dev-cats">' + Object.keys(CATS).map((k) => '<span class="ap-cat' + (d.categories.includes(k) ? ' is-on' : '') +
                '" title="' + (d.categories.includes(k) ? 'Takes: ' : 'Unticked: ') + esc(CATS[k]) + '">' + esc(CATS[k].replace(/ \(.*\)$/, '')) + '</span>').join('') + '</span>' +
            '<small>on since ' + esc(day(d.created_at)) + ' · ' + health + ' · <span title="' + esc(d.user_agent) + '">' + esc(d.host) + '</span></small></div>' +
            '<div class="ap-dev-acts"><button type="button" class="kw-btn kw-btn-sm" data-act="dev-test">Test</button>' +
            '<button type="button" class="kw-btn kw-btn-sm kw-btn-danger" data-act="dev-del">Remove</button></div></div>';
    }
    function rowHTML(p) {
        const n = p.devices.length;
        const tags = (p.is_admin ? '<span class="kw-chip kw-chip-gold">Admin</span>' : '') +
            p.groups.map((g) => '<span class="kw-chip' + (g === 'GREAT_Lab' ? ' kw-chip-blue' : '') + '">' + esc(g === 'GREAT_Lab' ? 'GREAT Lab' : g) + '</span>').join('');
        const av = p.picture ? '<img class="kw-avatar kw-avatar-sm" src="' + esc(p.picture) + '" alt="" loading="lazy">'
            : '<span class="kw-avatar kw-avatar-sm">' + esc((p.name || '?').slice(0, 1).toUpperCase()) + '</span>';
        const state = n ? '<span class="ap-state is-on"><i></i>On · ' + n + ' device' + (n === 1 ? '' : 's') + '</span>'
            : '<span class="ap-state"><i></i>Off</span>';
        const isOpen = open.has(p.usr_id);
        return '<div class="ap-row' + (n ? ' has-push' : '') + (isOpen ? ' is-open' : '') + '" role="listitem" data-uid="' + p.usr_id + '">' +
            '<div class="ap-row-main">' +
            '<label class="ap-pick" title="' + (n ? 'Pick for a message' : 'Push is off: nothing to send to') + '"><input type="checkbox" data-act="pick"' +
            (picked.has(p.usr_id) ? ' checked' : '') + (n ? '' : ' disabled') + ' aria-label="Pick ' + esc(p.name) + '"></label>' +
            av + '<div class="ap-who"><b>' + esc(p.name) + '</b><small>' + (p.placeholder_email ? 'local account' : esc(p.email)) + '</small></div>' +
            '<div class="ap-tags">' + tags + '</div>' + state +
            '<div class="ap-acts">' + (n ? '<button type="button" class="kw-btn kw-btn-sm" data-act="user-test">Test</button>' +
                '<button type="button" class="kw-btn kw-btn-sm" data-act="message">Message</button>' +
                '<button type="button" class="kw-icon-btn ap-toggle" data-act="toggle" aria-expanded="' + isOpen + '" aria-label="Devices of ' + esc(p.name) + '">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></button>'
                : '<span class="ap-hint">Not turned on</span>') + '</div></div>' +
            (n && isOpen ? '<div class="ap-devs">' + p.devices.map(deviceHTML).join('') + '</div>' : '') + '</div>';
    }
    function render() {
        const q = $('apQ').value.trim().toLowerCase();
        const membersOnly = $('apMembersOnly').checked;
        const list = PEOPLE.filter((p) => (!membersOnly || p.is_member) &&
            (filter === 'all' || (filter === 'on') === (p.devices.length > 0)) &&
            (!q || (p.name + ' ' + p.email + ' ' + p.groups.join(' ')).toLowerCase().includes(q)));
        $('apList').innerHTML = list.length ? list.map(rowHTML).join('') : '<p class="kw-empty">Nobody matches.</p>';
        // a picture that no longer loads: show the initial instead
        $('apList').querySelectorAll('img.kw-avatar').forEach((img) => img.addEventListener('error', () => {
            const s = document.createElement('span');
            s.className = 'kw-avatar kw-avatar-sm';
            s.textContent = (byId.get(Number(img.closest('.ap-row').dataset.uid)) || {}).name?.slice(0, 1).toUpperCase() || '?';
            img.replaceWith(s);
        }, { once: true }));
        const scope = PEOPLE.filter((p) => !membersOnly || p.is_member);
        const on = scope.filter((p) => p.devices.length).length;
        $('apCount').textContent = on + ' of ' + scope.length + (membersOnly ? ' members' : ' people') + ' have push on';
    }
    document.querySelectorAll('[data-state]').forEach((b) => b.addEventListener('click', () => {
        filter = b.dataset.state;
        document.querySelectorAll('[data-state]').forEach((x) => x.classList.toggle('is-on', x === b));
        render();
    }));
    $('apQ').addEventListener('input', render);
    $('apMembersOnly').addEventListener('change', render);

    $('apList').addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-act]');
        if (!b) return;
        const row = b.closest('.ap-row'), p = byId.get(Number(row.dataset.uid));
        const act = b.dataset.act;
        if (act === 'pick') {
            if (b.checked) picked.add(p.usr_id); else picked.delete(p.usr_id);
            if (picked.size) setTarget('users');
            renderPicked();
            return;
        }
        if (act === 'toggle') {
            if (open.has(p.usr_id)) open.delete(p.usr_id); else open.add(p.usr_id);
            render();
            return;
        }
        if (act === 'message') {
            picked.clear();
            picked.add(p.usr_id);
            setTarget('users');
            renderPicked();
            render();
            form.scrollIntoView({ behavior: 'smooth', block: 'start' });
            $('apTitle').focus({ preventScroll: true });
            return;
        }
        b.disabled = true;
        if (act === 'user-test') {
            post('/admin/push/user/' + p.usr_id + '/test').then((d) => {
                b.disabled = false;
                if (d.ok) toast('Test sent to ' + p.name + ': ' + d.delivered + ' device(s) took it' + (d.failed ? ', ' + d.failed + ' failed' : ''), 'success');
                else toast(d.error || ('No device took it (' + d.failed + ' failed). Open the row to see why.'), 'error');
            });
        } else if (act === 'dev-test') {
            const sid = Number(b.closest('.ap-dev').dataset.sid);
            post('/admin/push/device/' + sid + '/test').then((d) => {
                b.disabled = false;
                toast((d.ok ? 'Sent: ' : 'Not sent: ') + (d.message || d.error || ''), d.ok ? 'success' : 'error');
                if (!d.ok && /removed/.test(d.message || '')) { p.devices = p.devices.filter((x) => x.id !== sid); render(); }
            });
        } else if (act === 'dev-del') {
            const sid = Number(b.closest('.ap-dev').dataset.sid);
            if (!confirm('Remove this device from ' + p.name + '\'s push? They can turn it on again in Settings.')) { b.disabled = false; return; }
            post('/admin/push/device/' + sid + '/delete').then((d) => {
                if (d.ok) { p.devices = p.devices.filter((x) => x.id !== sid); picked.delete(p.usr_id); render(); renderPicked(); toast('Removed', 'success'); }
                else { b.disabled = false; toast('Could not remove it', 'error'); }
            });
        }
    });

    // ── compose ──
    const target = () => (form.querySelector('input[name=target]:checked') || {}).value || 'me';
    function setTarget(t) { const r = form.querySelector('input[name=target][value="' + t + '"]'); if (r) { r.checked = true; syncTarget(); } }
    function syncTarget() {
        $('apGroupWrap').hidden = target() !== 'group';
        $('apPickedWrap').hidden = target() !== 'users';
        estimate();
    }
    function renderPicked() {
        $('apChips').innerHTML = picked.size ? Array.from(picked).map((id) => {
            const p = byId.get(id);
            return '<span class="ap-chip">' + esc(p ? p.name : id) + '<button type="button" data-unpick="' + id + '" aria-label="Remove">×</button></span>';
        }).join('') : '<span class="kw-muted">Nobody yet</span>';
        estimate();
    }
    $('apChips').addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-unpick]');
        if (!b) return;
        picked.delete(Number(b.dataset.unpick));
        renderPicked();
        render();
    });
    let estTimer = null, est = { recipients: 0, with_push: 0, devices: 0 };
    function estimate() {
        clearTimeout(estTimer);
        estTimer = setTimeout(() => {
            post('/admin/push/preview', { target: target(), group: $('apGroup') ? $('apGroup').value : '', usr_ids: Array.from(picked) }).then((d) => {
                est = d;
                $('apEst').textContent = d.recipients + ' ' + (d.recipients === 1 ? 'person' : 'people') + ' (bell) · ' + d.with_push + ' with push · ' + d.devices + ' device' + (d.devices === 1 ? '' : 's');
            });
        }, 120);
    }
    form.addEventListener('change', (ev) => { if (ev.target.name === 'target' || ev.target.id === 'apGroup') syncTarget(); });
    function preview() {
        $('apPTitle').textContent = $('apTitle').value || 'Title';
        $('apPBody').textContent = $('apBody').value;
        $('apTitleN').textContent = $('apTitle').value.length + '/120';
        $('apBodyN').textContent = $('apBody').value.length + '/500';
    }
    $('apTitle').addEventListener('input', preview);
    $('apBody').addEventListener('input', preview);
    const now = new Date();
    $('apClock').textContent = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');

    form.addEventListener('submit', (ev) => {
        ev.preventDefault();
        if (!$('apTitle').value.trim()) { toast('Write a title', 'error'); $('apTitle').focus(); return; }
        if (target() === 'users' && !picked.size) { toast('Pick at least one person in the list below', 'error'); return; }
        if (!est.recipients) { toast('Nobody is in that list', 'error'); return; }
        if (target() !== 'me' && !confirm('Send this to ' + est.recipients + ' ' + (est.recipients === 1 ? 'person' : 'people') + ' (under their bell; pushed to ' + est.devices + ' device' + (est.devices === 1 ? '' : 's') + ')? It cannot be taken back.')) return;
        const btn = $('apSend');
        btn.disabled = true;
        post('/admin/push/send', { title: $('apTitle').value, body: $('apBody').value, url: $('apUrl').value, target: target(),
            group: $('apGroup') ? $('apGroup').value : '', usr_ids: Array.from(picked) }).then((d) => {
            if (!d.ok) { btn.disabled = false; toast(d.error || 'Could not send', 'error'); return; }
            toast('Sent to ' + d.recipients + ' bell(s), pushing to ' + d.devices + ' device(s)…', 'success');
            setTimeout(() => location.reload(), 2500);      // the history row then shows how many took it
        }).catch(() => { btn.disabled = false; toast('Could not send', 'error'); });
    });

    document.querySelectorAll('[data-reuse]').forEach((b) => b.addEventListener('click', () => {
        const x = JSON.parse(b.getAttribute('data-reuse'));
        $('apTitle').value = x.title || '';
        $('apBody').value = x.body || '';
        $('apUrl').value = x.url || '';
        preview();
        form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        $('apTitle').focus({ preventScroll: true });
    }));

    render();
    renderPicked();
    syncTarget();
    preview();
})();
