// Site shell (markup in _shell_top.html / _shell.html, styles in css/shell.css). _base.html loads it right after </main>.
// 1) Phones: tapping a section in the bottom tab bar opens its groups as a sheet instead of leaving the page;
//    the About section (links out only) opens its menu on every screen size.
// 2) A tapped navigation link turns "selected" at once instead of when the next page has loaded.
// 3) Page-change feedback: thin progress bar at the top, plus a spinner on phones when it takes a moment.
// 4) Account menu (click to open — phones have no hover), flash messages, home first-screen scroll effect,
//    tab bar out of the way while the on-screen keyboard is up.
// 5) Aladin sky views in iframes are emptied before leaving the page (otherwise the next page never loads).
(function () {
    var body = document.body;
    var root = document.documentElement;
    var mq = window.matchMedia('(max-width: 860px)');

    // ── 1) Section sheet / menu ──
    var scrim = document.createElement('div');
    scrim.className = 'sh-scrim';
    body.appendChild(scrim);

    function closeSheets() {
        document.querySelectorAll('.sh-rail-item.is-open').forEach(function (it) { it.classList.remove('is-open'); });
        body.classList.remove('sh-sheet-open');
    }
    function openSheet(item) {
        var was = item.classList.contains('is-open');
        closeSheets();
        if (was) return;
        item.classList.add('is-open');
        if (mq.matches) body.classList.add('sh-sheet-open');
        var first = item.querySelector('.sh-fly a.is-on') || item.querySelector('.sh-fly a');
        if (first) first.focus({ preventScroll: true });
    }
    document.querySelectorAll('.sh-rail-item').forEach(function (item) {
        var btn = item.querySelector('.sh-rail-btn');
        if (!btn || !item.querySelector('.sh-fly')) return;
        btn.addEventListener('click', function (e) {
            if (!mq.matches && !btn.hasAttribute('data-sh-menu-only')) return;
            e.preventDefault();
            openSheet(item);
        });
    });
    scrim.addEventListener('click', closeSheets);
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.sh-rail-item')) document.querySelectorAll('.sh-rail-item.is-open').forEach(function (it) { if (!mq.matches) it.classList.remove('is-open'); });
    });

    // ── 2) Instant "selected" state on navigation links ──
    var NAV_SETS = [
        ['.sh-rail-btn', '.sh-rail'],
        ['.sh-fly a', '.sh-fly'],
        ['.sh-tabs a', '.sh-tabs'],
        ['.sh-views a', '.sh-views']
    ];
    function select(a, sel, scopeSel) {
        var scope = a.closest(scopeSel) || a.parentElement;
        scope.querySelectorAll(sel).forEach(function (x) { if (x !== a) { x.classList.remove('is-on'); x.removeAttribute('aria-current'); } });
        a.classList.add('is-on');
        a.setAttribute('aria-current', 'page');
    }
    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a || a.target === '_blank' || a.hasAttribute('download') || a.origin !== location.origin) return;
        if (a.getAttribute('href') === '#') return;
        var hit = false;
        NAV_SETS.forEach(function (n) { if (!hit && a.matches(n[0])) { select(a, n[0], n[1]); hit = true; } });
        if (!hit) return;
        var href = a.getAttribute('href');
        document.querySelectorAll('.sh-tabs a').forEach(function (x) { if (x !== a && x.getAttribute('href') === href) select(x, '.sh-tabs a', '.sh-tabs'); });
        var item = a.closest('.sh-rail-item');
        if (item) {
            var btn = item.querySelector('.sh-rail-btn');
            if (btn && btn !== a) select(btn, '.sh-rail-btn', '.sh-rail');
            closeSheets();
        }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeSheets(); closeUser(); } });
    mq.addEventListener('change', closeSheets);

    // ── 3) Page-change feedback ──
    var bar = document.createElement('div');
    bar.className = 'sh-progress'; bar.setAttribute('aria-hidden', 'true');
    body.appendChild(bar);
    var spin = document.createElement('div');
    spin.className = 'sh-spin'; spin.setAttribute('role', 'status');
    spin.innerHTML = '<i></i><span>Loading</span>';
    body.appendChild(spin);
    var timer = null, giveUp = null, spinWait = null;
    function stop() {
        clearInterval(timer); clearTimeout(spinWait); clearTimeout(giveUp);
        bar.classList.remove('is-on'); bar.style.width = '0'; spin.classList.remove('is-on');
    }
    function start() {
        clearTimeout(spinWait);
        spinWait = setTimeout(function () { spin.classList.add('is-on'); }, 250);   // fast loads never show it
        bar.classList.add('is-on'); bar.style.width = '12%';
        var w = 12;
        clearInterval(timer);
        timer = setInterval(function () { w = Math.min(88, w + (88 - w) * 0.12); bar.style.width = w + '%'; }, 160);
        clearTimeout(giveUp);
        giveUp = setTimeout(stop, 8000);
    }
    document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if (a.target === '_blank' || a.hasAttribute('download') || a.hasAttribute('data-noprogress')) return;
        var href = a.getAttribute('href');
        if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
        if (a.origin !== location.origin) return;
        if (a.pathname === location.pathname && a.search === location.search) return;   // same page / hash only
        // decide after the other click handlers ran: a prevented click (a sheet opened instead) does not leave the page
        setTimeout(function () { if (!e.defaultPrevented) start(); }, 0);
    }, true);
    window.addEventListener('pageshow', function () { stop(); closeSheets(); closeUser(); });

    // ── 4) Account menu ──
    var user = document.querySelector('.sh-user');
    function closeUser() {
        if (!user) return;
        user.classList.remove('is-open');
        user.querySelector('.sh-user-btn').setAttribute('aria-expanded', 'false');
    }
    if (user) {
        var ubtn = user.querySelector('.sh-user-btn');
        ubtn.addEventListener('click', function (e) {
            e.stopPropagation();
            var on = !user.classList.contains('is-open');
            user.classList.toggle('is-open', on);
            ubtn.setAttribute('aria-expanded', on ? 'true' : 'false');
        });
        document.addEventListener('click', function (e) {
            if (!user.contains(e.target) || e.target.closest('.sh-user-menu a')) closeUser();
        });
    }

    // Flash messages fade out like before
    setTimeout(function () {
        var flash = document.getElementById('flash-message');
        if (flash) { flash.style.opacity = '0'; setTimeout(function () { flash.style.display = 'none'; }, 300); }
    }, 3500);

    // On-screen keyboard up: move the bottom tab bar out of the way
    function typing(el) { return el && el.matches && el.matches('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button]):not([type=submit]), textarea, select, [contenteditable="true"]'); }
    document.addEventListener('focusin', function (e) { if (typing(e.target)) root.classList.add('kw-typing'); });
    document.addEventListener('focusout', function () {
        setTimeout(function () { if (!typing(document.activeElement)) root.classList.remove('kw-typing'); }, 50);
    });

    // Home first screen: the big wordmark shrinks back to a heading as you scroll (--hp 0 → 1)
    var hero = document.getElementById('sh-hello');
    if (hero && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        var ticking = false;
        var upd = function () {
            ticking = false;
            var h = hero.offsetHeight || 1;
            hero.style.setProperty('--hp', Math.min(1, Math.max(0, window.scrollY / (h * 0.6))).toFixed(3));
        };
        window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(upd); } }, { passive: true });
        upd();
    }

    // Home tiles rise in as they scroll into view
    var tiles = document.querySelectorAll('.sh-home .reveal');
    if (tiles.length && 'IntersectionObserver' in window) {
        root.classList.add('js-reveal');
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); } });
        }, { rootMargin: '0px 0px -8% 0px' });
        tiles.forEach(function (t) { io.observe(t); });
    }

    // A tab strip wider than its room scrolls sideways (page-bar tabs on phones, the Lab group pills in the top
    // bar on narrower desktops / tablets). Re-checked whenever the strip or its tabs change size: while it overflows,
    // CSS fades the edge that still has more (.sh-can-l / .sh-can-r) and two round arrow buttons step it; the
    // vertical mouse wheel scrolls it sideways. The first time it overflows it starts at the selected tab.
    var ARROW = '<svg class="sh-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="%P"/></svg>';
    function makeArrow(dir) {
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'sh-scroll-btn'; b.hidden = true; b.tabIndex = -1;   // keyboard users tab through the links themselves
        b.setAttribute('aria-label', dir < 0 ? 'Scroll left' : 'Scroll right');
        b.innerHTML = ARROW.replace('%P', dir < 0 ? 'm15 6-6 6 6 6' : 'm9 6 6 6-6 6');
        return b;
    }
    function scrollableStrip(strip) {
        var left = makeArrow(-1), right = makeArrow(1), seen = false;
        strip.parentNode.insertBefore(left, strip);
        strip.parentNode.insertBefore(right, strip.nextSibling);
        function place(btn, atRight) {
            var host = strip.parentNode, sr = strip.getBoundingClientRect(), hr = host.getBoundingClientRect(), size = 28, inset = 4;
            btn.style.top = (sr.top - hr.top - host.clientTop + host.scrollTop + (sr.height - size) / 2) + 'px';
            btn.style.left = (sr.left - hr.left - host.clientLeft + host.scrollLeft + (atRight ? sr.width - size - inset : inset)) + 'px';
        }
        function update() {
            var max = strip.scrollWidth - strip.clientWidth, over = strip.clientWidth > 0 && max > 1;
            strip.classList.toggle('sh-overflow', over);
            strip.classList.toggle('sh-can-l', over && strip.scrollLeft > 1);
            strip.classList.toggle('sh-can-r', over && strip.scrollLeft < max - 1);
            left.hidden = !(over && strip.scrollLeft > 1);
            right.hidden = !(over && strip.scrollLeft < max - 1);
            if (!over) return;
            if (getComputedStyle(strip.parentNode).position === 'static') strip.parentNode.style.position = 'relative';
            place(left, false); place(right, true);
            if (!seen) {
                seen = true;
                var on = strip.querySelector('.is-on, [aria-current="page"], [aria-selected="true"]');
                if (on) { strip.scrollLeft += on.getBoundingClientRect().left - strip.getBoundingClientRect().left - (strip.clientWidth - on.offsetWidth) / 2; update(); }
            }
        }
        function step(dir) { strip.scrollBy({ left: dir * Math.max(120, strip.clientWidth * 0.6), behavior: 'smooth' }); }
        left.addEventListener('click', function () { step(-1); });
        right.addEventListener('click', function () { step(1); });
        strip.addEventListener('scroll', update, { passive: true });
        strip.addEventListener('wheel', function (e) {
            if (!strip.classList.contains('sh-overflow') || Math.abs(e.deltaX) >= Math.abs(e.deltaY) || e.ctrlKey) return;
            var max = strip.scrollWidth - strip.clientWidth;
            if ((e.deltaY < 0 && strip.scrollLeft <= 0) || (e.deltaY > 0 && strip.scrollLeft >= max - 1)) return;   // at the end: let the page scroll
            e.preventDefault();
            strip.scrollLeft += e.deltaY;
        }, { passive: false });
        if ('ResizeObserver' in window) {
            var ro = new ResizeObserver(update);
            ro.observe(strip); ro.observe(strip.parentNode);
            Array.prototype.forEach.call(strip.children, function (c) { ro.observe(c); });
            // tabs added later (admin bot tabs are filled by script)
            new MutationObserver(function () {
                Array.prototype.forEach.call(strip.children, function (c) { ro.observe(c); });
                update();
            }).observe(strip, { childList: true });
        } else {
            window.addEventListener('resize', update);
        }
        update();
    }
    document.querySelectorAll('.sh-pagebar :is(.kw-tabbar, .kw-seg, .sh-views), .sh-top .sh-tabs').forEach(scrollableStrip);

    // ── 5) Leaving a page with an Aladin sky view in an iframe (object page, ePESSTO++): Aladin Lite 3.8.2
    //    inside an iframe keeps the tab from receiving the next page — it stays on "loading" forever. Sending
    //    those iframes to about:blank first lets the navigation finish. If the page is still here a moment
    //    later (the link was a download, or leaving was cancelled), the sky views are reloaded.
    window.addEventListener('beforeunload', function () {
        var frames = Array.prototype.slice.call(document.querySelectorAll('iframe[id$="aladin-iframe"]'));
        if (!frames.length) return;
        frames.forEach(function (f) {
            try { f.contentWindow.location.replace('about:blank'); } catch (e) { /* already gone */ }
        });
        setTimeout(function () {
            frames.forEach(function (f) { if (f.isConnected && f.hasAttribute('srcdoc')) f.srcdoc = f.srcdoc; });
        }, 1500);
    });
})();
