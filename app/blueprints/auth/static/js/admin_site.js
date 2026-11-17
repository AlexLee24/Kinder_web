// Admin › Site (/admin/site): the preferred sky-survey server for every Aladin view (POST /admin/site/aladin), each
// server's state, and every survey Kinder offers on each server — all checked live with js/hips_fallback.js.
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    if (!$('stPage') || !window.KinderHips) return;
    const H = window.KinderHips;
    const form = $('stServerForm');
    const saveBtn = $('stSave');
    let saved = (form.querySelector('input[name="server"]:checked') || {}).value || 'cds';

    function toast(msg, type) {
        const n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => { n.style.animation = 'notificationSlideOut 0.25s forwards'; setTimeout(() => n.remove(), 260); }, 3400);
    }
    const chosen = () => (form.querySelector('input[name="server"]:checked') || {}).value || saved;

    // The survey rows: every id hips_fallback.js knows, in its order
    const ids = Object.keys(H.SURVEYS);
    const tbody = $('stTable').querySelector('tbody');
    tbody.innerHTML = ids.map((id) => '<tr data-id="' + esc(id) + '"><td><b>' + esc(H.SURVEYS[id].label) + '</b><span class="st-id">' + esc(id) + '</span></td>' +
        H.KEYS.map((k) => '<td class="st-c" data-server="' + k + '"><i class="st-dot" data-state="' + (H.address(id, k) ? 'wait' : 'none') + '"></i></td>').join('') +
        '<td class="st-now-cell"><span class="st-now"><i class="st-dot" data-state="wait"></i><span>…</span></span></td></tr>').join('');

    let avail = {};   // id → {cds, esa, irsa}
    let up = {};      // server → bool

    function paintServers() {
        const pref = chosen();
        // Backup numbering follows the order: preferred, then the others in SERVERS order
        let n = 0;
        H.KEYS.forEach((k) => {
            const card = form.querySelector('.st-server[data-server="' + k + '"]');
            if (!card) return;
            if (k !== pref) card.querySelector('.st-tag-backup').textContent = 'Backup ' + (++n);
            const dot = card.querySelector('.st-dot');
            dot.dataset.state = up[k] === undefined ? 'wait' : up[k] ? 'up' : 'down';
            card.querySelector('[data-role="state"]').textContent = up[k] === undefined ? 'Checking…' : up[k] ? 'Online' : 'Not answering';
            let has = 0, total = 0;
            ids.forEach((id) => { if (H.address(id, k)) { total++; if (avail[id] && avail[id][k]) has++; } });
            card.querySelector('[data-role="count"]').textContent = total + ' of ' + ids.length + ' surveys hosted' + (up[k] ? ' · ' + has + ' answering' : '');
        });
        document.querySelectorAll('#stTable th.st-c').forEach((th) => th.classList.toggle('is-pref', th.dataset.server === pref));
    }
    function paintRow(id) {
        const tr = tbody.querySelector('tr[data-id="' + CSS.escape(id) + '"]');
        const a = avail[id];
        if (!tr || !a) return;
        H.KEYS.forEach((k) => {
            const ad = H.address(id, k);
            const d = tr.querySelector('td[data-server="' + k + '"] .st-dot');
            d.dataset.state = !ad ? 'none' : a[k] ? (ad.substitute ? 'sub' : 'up') : 'down';
            d.parentElement.title = H.SERVERS[k].label + ': ' + (!ad ? 'not hosted there' : a[k] ? (ad.substitute ? 'a similar survey (not the same one)' : 'available') : 'not answering');
        });
        // What the site shows with the chosen preference (order: chosen, then the rest)
        const pref = chosen();
        const order = [pref].concat(H.KEYS.filter((k) => k !== pref));
        const from = order.find((k) => H.address(id, k) && a[k]);
        const now = tr.querySelector('.st-now');
        now.querySelector('.st-dot').dataset.state = !from ? 'down' : from === pref ? 'up' : 'backup';
        now.querySelector('span').textContent = !from ? 'Not available' : 'From ' + H.SERVERS[from].label + (H.address(id, from).substitute ? ' (similar)' : '') + (from === pref ? '' : ' (backup)');
    }

    function check() {
        H.forgetChecks();
        avail = {}; up = {};
        tbody.querySelectorAll('td.st-c .st-dot').forEach((d) => { if (d.dataset.state !== 'none') d.dataset.state = 'wait'; });
        tbody.querySelectorAll('.st-now .st-dot').forEach((d) => { d.dataset.state = 'wait'; });
        paintServers();
        H.KEYS.forEach((k) => H.serverUp(k).then((ok) => { up[k] = ok; paintServers(); }));
        ids.forEach((id) => H.availability(id).then((a) => { avail[id] = a; paintRow(id); paintServers(); }));
    }

    form.addEventListener('change', () => {
        saveBtn.disabled = chosen() === saved;
        paintServers();
        ids.forEach(paintRow);
    });
    $('stRecheck').addEventListener('click', check);
    saveBtn.addEventListener('click', () => {
        const server = chosen();
        saveBtn.disabled = true;
        fetch('/admin/site/aladin', {
            method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ server }),
        }).then((r) => r.json().catch(() => ({}))).then((d) => {
            if (!d.ok) { saveBtn.disabled = false; toast(d.error || 'Could not save', 'error'); return; }
            saved = server;
            H.forgetConfig();
            $('stSaved').textContent = 'Saved — ' + H.SERVERS[server].label + ' is preferred. Open pages pick it up within a minute.';
            toast(H.SERVERS[server].label + ' is now the preferred sky server', 'success');
        }).catch(() => { saveBtn.disabled = false; toast('Could not save (network)', 'error'); });
    });

    check();
})();
