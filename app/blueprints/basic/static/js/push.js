// Push notifications panel of /settings (#push), after EAU_Web's push.js: turn push on / off for this device and send
// a test. States: loading | on | off | denied (blocked in the browser) | ios (needs the Home Screen app) | na.
// The subscription goes to /api/push/subscribe (app/blueprints/basic/push.py); /sw.js shows what arrives.
(function () {
    'use strict';
    var box = document.getElementById('push');
    if (!box) return;
    var stateEl = box.querySelector('.st-push-state'), actions = box.querySelector('.st-push-actions');
    var KEY = null, sub = null;
    var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

    function post(url, body) {
        return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body || {}) })
            .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.status = r.status; return d; }); });
    }
    function toast(msg, type) {
        var n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(function () { n.style.animation = 'notificationSlideOut 0.25s forwards'; setTimeout(function () { n.remove(); }, 260); }, 3200);
    }
    function keyBytes(b64) {
        var pad = '='.repeat((4 - b64.length % 4) % 4);
        var raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
    }

    var ua = navigator.userAgent;
    var isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    var mobile = isIOS || /Android|Mobi/i.test(ua);
    var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    var supported = window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    // put this platform's tips first in "Not arriving?"
    var mine = box.querySelector('.st-push-help [data-platform="' + (isIOS ? 'ios' : /Android/i.test(ua) ? 'android' : 'desktop') + '"]');
    if (mine) { mine.classList.add('is-mine'); mine.parentNode.insertBefore(mine, mine.parentNode.firstChild); }

    function show(state, title, text, buttons) {
        box.setAttribute('data-state', state);
        stateEl.innerHTML = '<b>' + esc(title) + '</b>' + (text ? '<small>' + esc(text) + '</small>' : '');
        actions.innerHTML = '';
        (buttons || []).forEach(function (b) {
            var el = document.createElement('button');
            el.type = 'button';
            el.className = 'kw-btn kw-btn-sm' + (b.primary ? ' kw-btn-primary' : '');
            el.textContent = b.label;
            el.addEventListener('click', function () { el.disabled = true; Promise.resolve(b.run()).finally(function () { el.disabled = false; }); });
            actions.appendChild(el);
        });
    }

    function test() {
        return post('/api/push/test').then(function (d) {
            if (d.ok) toast('Test sent: it should pop up within a few seconds', 'success');
            else toast(d.error || 'The push service did not take it. Try turning push off and on again.', 'error');
        });
    }
    function onState(devices) {
        show('on', 'Push is on for this ' + (mobile ? 'device' : 'computer'),
            'Messages from the Kinder admins pop up here, even when Kinder is closed.' +
            (devices > 1 ? ' You have push on ' + devices + ' devices.' : ''),
            [{ label: 'Send a test', primary: true, run: test }, { label: 'Turn off', run: off }]);
    }
    function offState() {
        show('off', 'Push is off on this ' + (mobile ? 'device' : 'computer'),
            'Turn it on to get messages from the Kinder admins as notifications, even when Kinder is closed.',
            [{ label: 'Turn on', primary: true, run: on }]);
    }
    function deniedState() {
        show('denied', 'Notifications are blocked for Kinder',
            isIOS ? 'Allow them in Settings → Notifications → Kinder, then come back here.'
                  : 'Click the icon left of the address bar → Site settings → Notifications → Allow, then reload this page.', []);
    }

    function on() {
        return Notification.requestPermission().then(function (perm) {
            if (perm !== 'granted') { deniedState(); return; }
            return navigator.serviceWorker.ready.then(function (reg) {
                var fresh = function () { return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(KEY) }); };
                return reg.pushManager.getSubscription().then(function (old) {
                    if (!old) return fresh();
                    // made with another server key (keys were replaced): drop it, or subscribe() fails
                    var k = old.options && old.options.applicationServerKey;
                    var same = k && btoa(String.fromCharCode.apply(null, new Uint8Array(k))) === btoa(String.fromCharCode.apply(null, keyBytes(KEY)));
                    return same ? old : old.unsubscribe().then(fresh);
                });
            }).then(function (s) {
                sub = s;
                return post('/api/push/subscribe', { subscription: s.toJSON() });
            }).then(function (d) {
                if (!d.ok) throw new Error(d.error || 'save');
                return post('/api/push/status', { endpoint: sub.endpoint });
            }).then(function (st) {
                onState(st.devices || 1);
                toast('Push is on', 'success');
                return test();
            });
        }).catch(function (e) { toast('Could not turn push on' + (e && e.message && e.message !== 'save' ? ': ' + e.message : ''), 'error'); });
    }
    function off() {
        if (!sub) { offState(); return; }
        var endpoint = sub.endpoint;
        return sub.unsubscribe().catch(function () {}).then(function () {
            return post('/api/push/unsubscribe', { endpoint: endpoint });
        }).then(function () { sub = null; offState(); toast('Push is off on this device', 'info'); });
    }

    if (!supported) {
        if (isIOS && !standalone) show('ios', 'On iPhone / iPad, add Kinder to the Home Screen first',
            'In Safari tap Share → Add to Home Screen, open Kinder from that icon, then turn push on here (iOS 16.4 or later).', []);
        else show('na', 'This browser cannot receive push', 'Use Chrome, Edge, Firefox or Safari over https.', []);
        return;
    }
    fetch('/api/push/key', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (k) {
        if (!k.ok || !k.key) { show('na', 'Push is not set up on this server yet', 'An admin has to add the VAPID keys to kinder.env.', []); return; }
        KEY = k.key;
        if (Notification.permission === 'denied') { deniedState(); return; }
        return navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (s) {
            sub = s;
            if (!s) { offState(); return; }
            return post('/api/push/status', { endpoint: s.endpoint }).then(function (st) {
                if (st.subscribed) onState(st.devices);
                else offState();      // the browser is subscribed, but for another account (logged in as someone else)
            });
        });
    }).catch(function () { offState(); });
})();
