// Installable app (PWA): registers /sw.js and offers "Install app" (2026-10, after EAU_Web's pwa.js).
// Loaded on every page by _navbar.html. Install entries are elements with [data-pwa-install]
// (navbar menus); they stay hidden unless the browser can install the site or it is iOS Safari,
// where installing means Share → Add to Home Screen, so we show those steps instead.
// Signed-in users on a phone also get a one-time banner (snoozed for 14 days by "Not now").
(function () {
    var script = document.currentScript;
    var signedIn = !!(script && script.dataset.user === '1');
    var standalone = document.documentElement.classList.contains('is-standalone');
    var SNOOZE_KEY = 'kinder_pwa_snooze_until';
    var INSTALLED_KEY = 'kinder_pwa_installed';
    var SNOOZE_DAYS = 14;
    var deferred = null;

    function getItem(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
    function setItem(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

    // ── service worker ──
    var secure = location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    if ('serviceWorker' in navigator && secure) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/sw.js').catch(function () { /* unsupported / blocked */ });
        });
    }

    // ── platform ──
    var ua = navigator.userAgent || '';
    function isIOS() { return /iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1); }
    function isInApp() { return /Line\/|FBAN|FBAV|Instagram|Messenger|MicroMessenger/i.test(ua); }
    function isPhone() { return window.matchMedia('(max-width: 768px) and (pointer: coarse)').matches; }

    function installable() {
        if (standalone || getItem(INSTALLED_KEY) === '1') return false;
        return !!deferred || isIOS() || isInApp();
    }
    function refresh() {
        var show = installable();
        document.querySelectorAll('[data-pwa-install]').forEach(function (el) { el.hidden = !show; });
    }

    // ── step-by-step guide (iOS, in-app browsers) ──
    var ICO = {
        share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>',
        plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M12 8v8M8 12h8"/></svg>',
        open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="3"/><path d="M11 18h2"/></svg>',
        dots: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>',
        compass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg>'
    };
    function steps() {
        if (isInApp()) return { title: 'Open in your browser first', steps: [
            [ICO.dots, 'In-app browsers (LINE, Facebook, Instagram) can’t install apps: tap ⋯ → “Open in browser”.'],
            [ICO.plus, 'Then choose “Install app” again.']] };
        if (isIOS() && /CriOS|FxiOS|EdgiOS/.test(ua)) return { title: 'Open in Safari first', steps: [
            [ICO.compass, 'On iPhone and iPad only Safari can add apps to the Home Screen.'],
            [ICO.share, 'Open kinder in Safari, tap Share → “Add to Home Screen”.']] };
        if (isIOS()) return { title: 'Add Kinder to your Home Screen', steps: [
            [ICO.share, 'Tap the Share button in Safari (bottom bar on iPhone, top right on iPad).'],
            [ICO.plus, 'Scroll down and choose “Add to Home Screen”, then tap “Add”.'],
            [ICO.open, 'Open Kinder from its icon — it runs full screen, like an app.']] };
        return { title: 'Install Kinder', steps: [
            [ICO.dots, 'Open the browser menu and choose “Install app” or “Add to Home screen”.']] };
    }
    function guide() {
        var g = steps();
        var old = document.getElementById('kw-pwa-guide');
        if (old) old.remove();
        var d = document.createElement('dialog');
        d.id = 'kw-pwa-guide';
        d.className = 'kw-pwa-guide';
        d.innerHTML = '<div class="kw-pwa-guide-head"><img src="/static/pwa/icon-96.png" alt=""><b></b></div>' +
            '<ol class="kw-pwa-guide-steps"></ol><div class="kw-pwa-guide-acts"><button type="button" class="kw-btn kw-btn-primary">Got it</button></div>';
        d.querySelector('b').textContent = g.title;
        var ol = d.querySelector('ol');
        g.steps.forEach(function (st, i) {
            var li = document.createElement('li');
            li.innerHTML = '<span class="kw-pwa-step-n">' + (i + 1) + '</span><span class="kw-pwa-step-ico">' + st[0] + '</span><span class="kw-pwa-step-t"></span>';
            li.querySelector('.kw-pwa-step-t').textContent = st[1];
            ol.appendChild(li);
        });
        d.querySelector('button').addEventListener('click', function () { d.close(); });
        d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
        d.addEventListener('close', function () { d.remove(); });
        document.body.appendChild(d);
        if (d.showModal) d.showModal(); else d.setAttribute('open', '');
    }

    function install() {
        hideBanner();
        if (deferred) {
            var p = deferred;
            deferred = null;
            p.prompt();
            if (p.userChoice) p.userChoice.then(function (c) { if (c && c.outcome === 'accepted') setItem(INSTALLED_KEY, '1'); refresh(); });
            return;
        }
        guide();
    }

    // ── banner (signed-in users on phones, once per 14 days) ──
    var banner = null;
    function hideBanner() { if (banner) { banner.classList.remove('is-in'); var b = banner; banner = null; setTimeout(function () { b.remove(); }, 250); } }
    function maybeBanner() {
        if (banner || !signedIn || !isPhone() || !installable()) return;
        if (Number(getItem(SNOOZE_KEY) || 0) > Date.now()) return;
        banner = document.createElement('div');
        banner.className = 'kw-pwa-banner';
        banner.setAttribute('role', 'dialog');
        banner.setAttribute('aria-label', 'Install Kinder');
        banner.innerHTML = '<img src="/static/pwa/icon-96.png" alt="">' +
            '<div class="kw-pwa-banner-txt"><b>Install Kinder</b><small>Open Marshal and Daily Trigger full screen, like an app.</small></div>' +
            '<div class="kw-pwa-banner-acts"><button type="button" class="kw-btn kw-btn-sm kw-btn-ghost" data-act="later">Not now</button>' +
            '<button type="button" class="kw-btn kw-btn-sm kw-btn-primary" data-act="install">Install</button></div>';
        banner.addEventListener('click', function (e) {
            var act = e.target.closest('[data-act]');
            if (!act) return;
            if (act.dataset.act === 'later') { setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_DAYS * 864e5)); hideBanner(); }
            else install();
        });
        document.body.appendChild(banner);
        setTimeout(function () { if (banner) banner.classList.add('is-in'); }, 30);   // after first paint → slide in
    }

    window.addEventListener('beforeinstallprompt', function (e) {
        e.preventDefault();             // we show our own entry / banner instead of the mini-infobar
        deferred = e;
        refresh();
        maybeBanner();
    });
    window.addEventListener('appinstalled', function () {
        setItem(INSTALLED_KEY, '1');
        deferred = null;
        refresh();
        hideBanner();
    });
    // capture phase: _navbar.html stops propagation of clicks on dropdown links
    document.addEventListener('click', function (e) {
        var t = e.target.closest('[data-pwa-install] a, [data-pwa-install-btn]');
        if (!t) return;
        e.preventDefault();
        install();
    }, true);

    // ── installed app: same-site links stay inside the app ──
    // Marshal / object pages open objects with target=_blank or window.open(..., '_blank'); in the
    // standalone app that would throw the user out to a browser window. External sites (TNS, NED…)
    // still open outside, and blob:/data: downloads are left alone.
    if (standalone) {
        var sameSite = function (href) {
            try {
                var u = new URL(href, location.href);
                return (u.protocol === 'http:' || u.protocol === 'https:') && u.origin === location.origin ? u : null;
            } catch (e) { return null; }
        };
        var nativeOpen = window.open;
        window.open = function (url, target) {
            var u = url ? sameSite(String(url)) : null;
            if (u && (!target || target === '_blank')) { location.href = u.href; return window; }
            return nativeOpen.apply(window, arguments);
        };
        document.addEventListener('click', function (e) {
            if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            var a = e.target.closest && e.target.closest('a[target="_blank"][href]');
            if (!a || a.hasAttribute('download')) return;
            var u = sameSite(a.getAttribute('href'));
            if (!u) return;
            e.preventDefault();
            location.href = u.href;
        });
    }

    function start() {
        refresh();
        if (isIOS() || isInApp()) setTimeout(maybeBanner, 1500);   // no beforeinstallprompt there
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
