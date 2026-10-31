// The bell in the top bar (after EAU_Web's notify.js): unread count (asked on load, every 60 s while the tab is
// visible, and at once when /sw.js receives a push), the latest notifications in a drop-down, mark all read,
// delete one, clear read ones, and a hint when this device has push off. API: app/blueprints/basic/notifications.py.
(function () {
    'use strict';
    var root = document.getElementById('notif');
    if (!root) return;
    var btn = document.getElementById('notif-btn'), panel = document.getElementById('notif-panel');
    var list = document.getElementById('notif-list'), badge = document.getElementById('notif-badge');
    var unread = 0;
    var S = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    var ICONS = {
        megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
        bolt: '<path d="M13 3v7h6l-8 11v-7H5z"/>',
        send: '<path d="M10 14 21 3"/><path d="m21 3-6.5 18a.55.55 0 0 1-1 0L10 14l-7-3.5a.55.55 0 0 1 0-1z"/>',
        bell: '<path d="M10 5a2 2 0 1 1 4 0 7 7 0 0 1 4 6v3a4 4 0 0 0 2 3H4a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6"/><path d="M9 17v1a3 3 0 0 0 6 0v-1"/>',
    };
    var X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

    function ago(iso) {
        var t = Date.parse(iso);
        if (isNaN(t)) return '';
        var s = Math.max(0, (Date.now() - t) / 1000);
        if (s < 60) return 'just now';
        if (s < 3600) return Math.floor(s / 60) + ' min ago';
        if (s < 86400) return Math.floor(s / 3600) + ' h ago';
        if (s < 86400 * 7) return Math.floor(s / 86400) + ' d ago';
        return new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    function post(url, body) {
        return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
            .then(function (r) { return r.json(); });
    }
    function setBadge(n) {
        unread = n || 0;
        badge.hidden = !unread;
        badge.textContent = unread > 99 ? '99+' : String(unread);
        btn.classList.toggle('has-unread', !!unread);
        btn.setAttribute('aria-label', 'Notifications' + (unread ? ' (' + unread + ' unread)' : ''));
        try { if (navigator.setAppBadge) { if (unread) navigator.setAppBadge(unread); else navigator.clearAppBadge(); } } catch (e) { /* unsupported */ }
    }
    function empty(text) {
        list.innerHTML = '';
        var e = document.createElement('div');
        e.className = 'sh-notif-empty';
        e.textContent = text;
        list.appendChild(e);
    }
    function render(items) {
        if (!items.length) { empty('No notifications yet'); return; }
        list.innerHTML = '';
        items.forEach(function (it) {
            var row = document.createElement('div');
            row.className = 'sh-notif-row';
            var a = document.createElement('a');
            a.className = 'sh-notif-item' + (it.is_read ? '' : ' is-unread');
            a.href = '/notifications/' + it.id;
            a.innerHTML = '<span class="sh-notif-ic is-' + it.icon + '"><svg ' + S + '>' + (ICONS[it.icon] || ICONS.bell) + '</svg></span><span class="sh-notif-body"></span>';
            var body = a.querySelector('.sh-notif-body');
            [['sh-notif-title', it.title], ['sh-notif-sub', it.body], ['sh-notif-time', ago(it.created_at)]].forEach(function (p) {
                if (!p[1]) return;
                var s = document.createElement('span');
                s.className = p[0];
                s.textContent = p[1];
                body.appendChild(s);
            });
            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'sh-notif-del';
            del.innerHTML = X;
            del.title = 'Delete';
            del.setAttribute('aria-label', 'Delete this notification');
            del.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                row.classList.add('is-leaving');
                post('/api/notifications/delete', { ids: [it.id] }).then(function (d) {
                    setTimeout(function () { row.remove(); if (!list.querySelector('.sh-notif-row')) empty('No notifications'); }, 150);
                    if (d && d.ok) setBadge(d.unread);
                }).catch(function () { row.classList.remove('is-leaving'); });
            });
            row.appendChild(a);
            row.appendChild(del);
            list.appendChild(row);
        });
    }
    function load() {
        fetch('/api/notifications?limit=30', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) { if (d && d.ok) { render(d.items); setBadge(d.unread); } })
            .catch(function () { empty('Could not load notifications'); });
    }
    function open() { root.classList.add('is-open'); btn.setAttribute('aria-expanded', 'true'); load(); }
    function close() { root.classList.remove('is-open'); btn.setAttribute('aria-expanded', 'false'); }
    btn.addEventListener('click', function (e) { e.stopPropagation(); if (root.classList.contains('is-open')) close(); else open(); });
    document.addEventListener('click', function (e) { if (!root.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

    document.getElementById('notif-readall').addEventListener('click', function () {
        post('/api/notifications/read', { all: true }).then(function (d) {
            if (!d || !d.ok) return;
            setBadge(d.unread);
            list.querySelectorAll('.is-unread').forEach(function (el) { el.classList.remove('is-unread'); });
        }).catch(function () {});
    });
    document.getElementById('notif-delread').addEventListener('click', function () {
        post('/api/notifications/delete', { read: true }).then(function (d) { if (d && d.ok) { setBadge(d.unread); load(); } }).catch(function () {});
    });

    // unread count: on load, every 60 s while visible, when the tab comes back
    function poll() {
        if (document.visibilityState !== 'visible') return;
        fetch('/api/notifications/count', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok) return;
                var more = d.unread > unread;
                setBadge(d.unread);
                if (more && root.classList.contains('is-open')) load();
            }).catch(function () {});
    }
    // hint at the bottom when this device could take push but has not turned it on
    var hint = document.getElementById('notif-push-hint');
    if (hint && window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window && Notification.permission !== 'denied') {
        navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); })
            .then(function (s) { hint.hidden = !!s; }).catch(function () {});
    }
    // /sw.js tells open tabs when a push arrives
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', function (e) {
            if (!e.data || e.data.type !== 'kinder-push') return;
            if (typeof e.data.unread === 'number') setBadge(e.data.unread); else poll();
            if (root.classList.contains('is-open')) load();
        });
    }
    setInterval(poll, 60000);
    document.addEventListener('visibilitychange', poll);
    poll();
    window.kinderNotif = { refresh: poll };
})();
