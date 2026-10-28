// Settings page (/settings): every change is applied at once with KinderUi.apply and saved 0.4 s after the last one.
// Signed in: POST /api/settings/ui (the account); everyone: also localStorage 'kinder-ui'.
(function () {
    var cfg = window.ST_CFG || {};
    var UI = window.KinderUi;
    if (!UI) return;
    var HEX = /^#[0-9a-f]{6}$/i;
    var p = Object.assign({}, UI.DEFAULTS, UI.read());
    var $ = function (id) { return document.getElementById(id); };
    var status = $('st-status');
    function say(text, bad) {
        status.textContent = text;
        status.classList.toggle('is-bad', !!bad);
    }

    var timer = null;
    function commit() {
        UI.apply(p);
        render();
        clearTimeout(timer);
        timer = setTimeout(save, 400);
    }
    function save() {
        try { localStorage.setItem('kinder-ui', JSON.stringify(p)); } catch (e) { /* private mode */ }
        if (!cfg.loggedIn) { say('Saved in this browser.'); return; }
        fetch('/api/settings/ui', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.error);
                window.KW_UI_SERVER = d.prefs;
                say('Saved to your account.');
            })
            .catch(function () { say('Could not save. Try again later.', true); });
    }

    function mark(sel, attr, value) {
        document.querySelectorAll(sel).forEach(function (b) {
            var on = b.getAttribute(attr).toUpperCase() === String(value).toUpperCase();
            b.classList.toggle('is-on', on); b.setAttribute('aria-checked', on);
        });
    }
    function syncHex(pick, hex, value) {
        $(pick).value = value.toLowerCase();
        if (document.activeElement !== $(hex)) $(hex).value = value.toUpperCase();
    }
    function render() {
        mark('[data-bg]', 'data-bg', p.bg);
        var bgc = String(p.bg_color || UI.DEFAULTS.bg_color);
        $('st-bg-color-tile').style.setProperty('--st-bgc', bgc);
        $('st-bgcolor-row').hidden = p.bg !== 'color';
        $('st-mask-row').hidden = p.bg === 'color';          // solid colour has no mask
        mark('[data-bgcolor]', 'data-bgcolor', bgc);
        syncHex('st-bgcolor-pick', 'st-bgcolor-hex', bgc);
        mark('[data-accent]', 'data-accent', p.accent);
        syncHex('st-accent-pick', 'st-accent-hex', p.accent);
        var gcol = String(p.glass_color || UI.DEFAULTS.glass_color);
        mark('[data-glasscolor]', 'data-glasscolor', gcol);
        syncHex('st-glasscolor-pick', 'st-glasscolor-hex', gcol);
        $('st-mask').value = p.mask; $('st-mask-v').textContent = p.mask + '%';
        $('st-glass').value = p.glass; $('st-glass-v').textContent = p.glass + '%';
    }

    // swatches, colour pickers and hex fields share one pattern
    function colour(key, attr, pick, hex, extra) {
        document.querySelectorAll('[' + attr + ']').forEach(function (b) {
            b.addEventListener('click', function () { p[key] = b.getAttribute(attr).toUpperCase(); if (extra) extra(); commit(); });
        });
        $(pick).addEventListener('input', function (e) { p[key] = e.target.value.toUpperCase(); if (extra) extra(); commit(); });
        $(hex).addEventListener('input', function (e) {
            var v = e.target.value.trim();
            if (v && v[0] !== '#') v = '#' + v;
            var ok = HEX.test(v);
            e.target.classList.toggle('is-bad', !ok && v.length >= 7);
            if (ok) { p[key] = v.toUpperCase(); if (extra) extra(); commit(); }
        });
    }
    colour('bg_color', 'data-bgcolor', 'st-bgcolor-pick', 'st-bgcolor-hex', function () { p.bg = 'color'; });
    colour('accent', 'data-accent', 'st-accent-pick', 'st-accent-hex');
    colour('glass_color', 'data-glasscolor', 'st-glasscolor-pick', 'st-glasscolor-hex');
    document.querySelectorAll('[data-bg]').forEach(function (b) {
        b.addEventListener('click', function () { p.bg = b.getAttribute('data-bg'); commit(); });
    });
    $('st-mask').addEventListener('input', function (e) { p.mask = +e.target.value; commit(); });
    $('st-glass').addEventListener('input', function (e) { p.glass = +e.target.value; commit(); });
    $('st-reset').addEventListener('click', function () { p = Object.assign({}, UI.DEFAULTS); commit(); });

    render();
})();
