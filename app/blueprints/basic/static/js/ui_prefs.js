// Personal look (Settings page, /settings — after EAU's ui_prefs.js): background (Kinder photo / black / solid colour),
// background mask, accent colour, glass colour and opacity.
// Loaded synchronously in <head> by _base.html, so the colours are set on <html> before the page paints.
// Signed-in users: the server puts their saved settings in window.KW_UI_SERVER; otherwise localStorage 'kinder-ui'.
(function () {
    var DEFAULTS = { bg: 'photo', bg_color: '#06060C', accent: '#F39F5A', glass: 70, glass_color: '#0E0E12', mask: 60 };

    function hexRgb(hex) {
        var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
        if (!m) return null;
        var n = parseInt(m[1], 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    function mix(rgb, to, t) { return rgb.map(function (c, i) { return Math.round(c + (to[i] - c) * t); }); }
    function css(rgb, a) { return a == null ? 'rgb(' + rgb.join(',') + ')' : 'rgba(' + rgb.join(',') + ',' + a + ')'; }
    // WCAG relative luminance: dark or white text on the accent
    function lum(rgb) {
        var c = rgb.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    }

    function read() {
        if (window.KW_UI_SERVER) return window.KW_UI_SERVER;
        try { return JSON.parse(localStorage.getItem('kinder-ui') || 'null') || {}; } catch (e) { return {}; }
    }

    function apply(p) {
        p = p || {};
        var s = document.documentElement.style;
        var rgb = hexRgb(p.accent) || hexRgb(DEFAULTS.accent);
        s.setProperty('--color-accent', css(rgb));
        s.setProperty('--color-accent-hover', css(mix(rgb, [255, 255, 255], 0.18)));
        s.setProperty('--color-accent-soft', css(rgb, 0.14));
        s.setProperty('--color-accent-text', lum(rgb) > 0.36 ? '#0c0a1a' : '#ffffff');
        // glass: its own colour (near-black by default) + opacity; menus use the same colour a little lighter and denser
        var glass = Math.max(40, Math.min(95, +p.glass || DEFAULTS.glass)) / 100;
        var gc = hexRgb(p.glass_color) || hexRgb(DEFAULTS.glass_color);
        s.setProperty('--color-surface', css(gc, glass));
        s.setProperty('--color-surface-elevated', css(mix(gc, [255, 255, 255], 0.05), Math.min(0.97, glass + 0.22).toFixed(2)));
        var mask = p.bg === 'color' ? 0 : (p.mask == null ? DEFAULTS.mask : Math.max(0, Math.min(85, +p.mask)));
        s.setProperty('--ui-mask', (mask / 100).toFixed(2));
        if (p.bg === 'plain' || p.bg === 'color') s.setProperty('--ui-bg', 'none');
        else s.removeProperty('--ui-bg');                       // shell.css default: the Kinder photo
        var bgc = p.bg === 'color' ? hexRgb(p.bg_color) : null;
        s.setProperty('--ui-bg-color', bgc ? css(bgc) : (p.bg === 'plain' ? '#050508' : '#07061A'));
        document.documentElement.classList.toggle('ui-bg-solid', p.bg === 'color');   // solid colour: no mask layer at all
    }

    window.KinderUi = { DEFAULTS: DEFAULTS, read: read, apply: apply };
    apply(read());
})();
