/* Tools › Sky Cutouts (euclid_compare.html): resolve a position, check Euclid DR1 / Q1 coverage, then fill 2–4 panels.
   Euclid panels are raw float32 from /api/euclid/pixels, stretched in the browser by window.FitsStretch
   (static/js/fits_stretch.js); every other survey is a colour JPEG from /api/euclid/survey (404 = no data there).
   State (position, field, panels) is mirrored in the URL (?q=&fov=&p=), display settings in localStorage. */
(() => {
    const page = document.getElementById('ecPage');
    if (!page || !window.FitsStretch) return;
    const FS = window.FitsStretch;
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const SOURCES = {
        vis: {label: 'Euclid VIS', bands: ['VIS']},
        nisp: {label: 'Euclid NISP H / J / Y', bands: ['NIR_H', 'NIR_J', 'NIR_Y']},
        nisp_y: {label: 'Euclid NISP Y', bands: ['NIR_Y']},
        nisp_j: {label: 'Euclid NISP J', bands: ['NIR_J']},
        nisp_h: {label: 'Euclid NISP H', bands: ['NIR_H']},
        dr10: {label: 'Legacy Survey DR10', jpeg: 'dr10', view: 'ls-dr10'},
        dr11: {label: 'Legacy Survey DR11', jpeg: 'dr11', view: 'ls-dr11'},
        dr10_model: {label: 'Legacy Survey DR10 model', jpeg: 'dr10_model', view: 'ls-dr10-model'},
        dr10_resid: {label: 'Legacy Survey DR10 residual', jpeg: 'dr10_resid', view: 'ls-dr10-resid'},
        hsc: {label: 'HSC PDR3', jpeg: 'hsc', view: 'hscmap'},
        ps1: {label: 'Pan-STARRS1', jpeg: 'ps1', view: 'ps1'},
        sdss: {label: 'SDSS', jpeg: 'sdss', view: 'sdss'},
        unwise: {label: 'unWISE', jpeg: 'unwise', view: 'unwise-neo7'},
        galex: {label: 'GALEX', jpeg: 'galex', view: 'galex'},
        vlass: {label: 'VLASS', jpeg: 'vlass', view: 'vlass1.2'},
    };
    /* Link of a panel's caption: the survey's own viewer at the position. */
    const HSC_PARAMS = {type: 'SDSS_TRUE_COLOR', filter: ['HSC-I', 'HSC-R', 'HSC-G'],
                        sdssTrueColor: {beta: 22026.465794806718, a: 1, bias: 0.05, b0: 0}};
    function viewUrl(view) {
        const rad = Math.PI / 180;
        if (view === 'hscmap') {
            const st = {view: {a: pos.ra * rad, d: pos.dec * rad, fovy: fov / 3600 * rad, roll: 0},
                        sspParams: HSC_PARAMS, externalTiles: [], activeReruns: ['pdr3_wide', 'pdr3_dud']};
            return `https://hscmap.mtk.nao.ac.jp/hscMap4/app/#/?_=${encodeURIComponent(JSON.stringify(st))}`;
        }
        if (view === 'ps1') return `https://ps1images.stsci.edu/cgi-bin/ps1cutouts?${qs({pos: `${pos.ra} ${pos.dec}`, filter: 'color', size: Math.round(fov / 0.25)})}`;
        return `https://www.legacysurvey.org/viewer?${qs({ra: pos.ra, dec: pos.dec, layer: view, zoom: 16, mark: `${pos.ra},${pos.dec}`})}`;
    }
    const accent = () => getComputedStyle(page).getPropertyValue('--color-accent').trim() || '#F39F5A';

    /* ------------------------------------------------------------ settings */
    const KEY = 'kinder-euclid-compare';
    let S = {...FS.DEFAULTS};
    try { Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* private mode */ }
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* ignore */ } };

    let panels = page.dataset.panels.split(',');
    const DEFAULT_PANELS = page.dataset.defaultPanels.split(',');
    let pos = null, cov = null, fov = +$('ecFov').value;

    /* ------------------------------------------------------------ data */
    const cache = new Map();
    const qs = (o) => new URLSearchParams(o).toString();
    function band(b) {
        const k = `${pos.ra},${pos.dec},${fov},${b}`;
        if (!cache.has(k)) {
            cache.set(k, fetch(`${page.dataset.apiPixels}?${qs({ra: pos.ra, dec: pos.dec, fov, band: b})}`).then(async (r) => {
                if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
                const h = (n) => r.headers.get(n);
                return {w: +h('X-Width'), h: +h('X-Height'), tx: +h('X-Target-X'), ty: +h('X-Target-Y'),
                        data: new Float32Array(await r.arrayBuffer())};
            }).catch((e) => { cache.delete(k); throw e; }));
        }
        return cache.get(k);
    }

    /* ------------------------------------------------------------ rendering */
    const scaleBar = () => {
        const arc = fov <= 20 ? 2 : fov <= 45 ? 5 : fov <= 90 ? 10 : 20;
        return `<div class="ec-scale" style="width:${(100 * arc / fov).toFixed(2)}%"><span>${arc}″</span></div>`;
    };

    function panelHtml(src, i) {
        const s = SOURCES[src];
        if (s.jpeg) {
            const url = `${page.dataset.apiSurvey}?${qs({ra: pos.ra, dec: pos.dec, fov, key: s.jpeg})}`;
            const view = viewUrl(s.view);
            return `<figure class="ec-panel is-loading${S.marker ? ' has-mark' : ''}" data-i="${i}">
                <img alt="" src="${url}" onload="this.parentNode.classList.remove('is-loading');this.nextElementSibling.remove()"
                     onerror="this.parentNode.classList.remove('is-loading','has-mark');this.nextElementSibling.textContent='No ${esc(s.label)} data here';this.remove()">
                <div class="ec-msg">Loading…</div>
                <figcaption><a href="${view}" target="_blank" rel="noopener">${esc(s.label)} ↗</a></figcaption>${scaleBar()}</figure>`;
        }
        const rel = cov && cov.release ? ` (${cov.release.toUpperCase()})` : '';
        const ok = cov && cov.covered && s.bands.every((b) => (cov.bands || []).includes(b));
        const msg = !cov ? 'Checking Euclid coverage…' : ok ? 'Loading…' : esc(cov.reason || `No ${s.label} here`);
        return `<figure class="ec-panel${ok || !cov ? ' is-loading' : ''}" data-i="${i}" data-src="${src}">
            <canvas></canvas><div class="ec-msg">${msg}</div>
            <figcaption>${esc(s.label)}${rel}</figcaption>${ok ? scaleBar() : ''}</figure>`;
    }

    async function drawEuclid(fig) {
        const s = SOURCES[fig.dataset.src];
        if (!cov || !cov.covered || !s.bands.every((b) => (cov.bands || []).includes(b))) return;
        try {
            const ch = await Promise.all(s.bands.map(band));
            FS.paint(fig.querySelector('canvas'), ch, S, {x: ch[0].tx, y: ch[0].ty}, accent());
            fig.classList.remove('is-loading');
            fig.querySelector('.ec-msg')?.remove();
        } catch (e) {
            fig.classList.remove('is-loading');
            const m = fig.querySelector('.ec-msg');
            if (m) m.textContent = e.message;
        }
    }

    function redrawEuclid() { $('ecGrid').querySelectorAll('.ec-panel[data-src]').forEach(drawEuclid); }

    function buildGrid() {
        if (!pos) return;
        const grid = $('ecGrid');
        grid.hidden = false;
        grid.dataset.n = panels.length;
        grid.innerHTML = panels.map(panelHtml).join('');
        redrawEuclid();
    }

    function info() {
        const box = $('ecInfo');
        box.hidden = false;
        const name = pos.name ? `<b>${esc(pos.name)}</b>` : '';
        const obj = pos.obj_name ? `<a href="/object/${encodeURIComponent(pos.obj_name)}">Kinder page</a>` : '';
        let euclid = '<span class="ec-muted">Checking Euclid coverage…</span>';
        if (cov) {
            euclid = cov.covered
                ? `Euclid ${esc(cov.release.toUpperCase())} tile <b>${esc(cov.tile)}</b> · ${esc((cov.bands || []).map((b) => b.replace('NIR_', '')).join(' / '))}`
                : `<span class="ec-warn">No Euclid data: ${esc(cov.reason)}</span>`;
        }
        box.innerHTML = `${name}<b>${pos.ra.toFixed(6)} ${pos.dec >= 0 ? '+' : ''}${pos.dec.toFixed(6)}</b>
            <span class="ec-muted">${esc(pos.source)}</span>${obj}<span>${euclid}</span>
            <span class="ec-muted">${fov}″ × ${fov}″ · north up, east left</span>`;
    }

    function status(text, cls) {
        const el = $('ecStatus');
        el.hidden = !text;
        el.textContent = text || '';
        el.className = `sp-status${cls ? ' ' + cls : ''}`;
    }

    function syncUrl() {
        const u = new URL(location.href);
        u.searchParams.set('q', $('ecQ').value.trim());
        u.searchParams.set('fov', fov);
        u.searchParams.set('p', panels.join(','));
        history.replaceState(null, '', u);
    }

    async function show() {
        const q = $('ecQ').value.trim();
        if (!q) return;
        fov = +$('ecFov').value;
        status('Resolving…', 'is-loading');
        $('ecInfo').hidden = true;
        $('ecGrid').hidden = true;
        try {
            const r = await fetch(`${page.dataset.apiResolve}?${qs({q})}`);
            const d = await r.json();
            if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
            pos = d;
        } catch (e) {
            status(e.message, 'is-error');
            return;
        }
        syncUrl();
        cov = null;
        status('');
        info();
        buildGrid();
        try {
            const r = await fetch(`${page.dataset.apiCoverage}?${qs({ra: pos.ra, dec: pos.dec})}`);
            const d = await r.json();
            cov = r.ok ? d : {covered: false, reason: d.error || `HTTP ${r.status}`};
        } catch (e) {
            cov = {covered: false, reason: e.message};
        }
        info();
        buildGrid();
    }

    /* ------------------------------------------------------------ panel controls */
    function syncPanelControls() {
        document.querySelectorAll('.ec-count [data-count]').forEach((b) => b.classList.toggle('is-on', +b.dataset.count === panels.length));
        document.querySelectorAll('.ec-src').forEach((l) => { l.hidden = +l.dataset.slot >= panels.length; });
        document.querySelectorAll('.ec-src select').forEach((s) => { s.value = panels[+s.dataset.slot] || DEFAULT_PANELS[+s.dataset.slot]; });
    }
    document.querySelectorAll('.ec-count [data-count]').forEach((b) => b.addEventListener('click', () => {
        const n = +b.dataset.count;
        panels = Array.from({length: n}, (_, i) => panels[i] || DEFAULT_PANELS[i]);
        syncPanelControls(); buildGrid(); if (pos) syncUrl();
    }));
    document.querySelectorAll('.ec-src select').forEach((s) => s.addEventListener('change', () => {
        panels[+s.dataset.slot] = s.value;
        buildGrid(); if (pos) syncUrl();
    }));
    syncPanelControls();

    /* ------------------------------------------------------------ display controls */
    const ctl = {mode: $('cMode'), shadows: $('cShadows'), target: $('cTarget'), black: $('cBlack'), white: $('cWhite'),
                 soft: $('cSoft'), cmap: $('cCmap'), invert: $('cInvert'), linked: $('cLinked'), marker: $('cMarker')};
    const fmt = {shadows: (v) => `${(+v).toFixed(1)} σ`, target: (v) => (+v).toFixed(2), black: (v) => `${(+v).toFixed(1)} %`,
                 white: (v) => `${(+v).toFixed(2)} %`, soft: (v) => (+v).toFixed(3)};
    function syncControls() {
        for (const [k, el] of Object.entries(ctl)) {
            if (el.type === 'checkbox') el.checked = !!S[k]; else el.value = S[k];
            const out = document.querySelector(`[data-out="${k}"]`);
            if (out) out.textContent = fmt[k] ? fmt[k](S[k]) : '';
        }
        page.dataset.mode = S.mode;
    }
    let raf = 0;
    for (const [k, el] of Object.entries(ctl)) {
        el.addEventListener('input', () => {
            S[k] = el.type === 'checkbox' ? el.checked : (el.type === 'range' ? +el.value : el.value);
            save(); syncControls();
            if (k === 'marker') $('ecGrid').querySelectorAll('.ec-panel:not([data-src])').forEach((f) => f.classList.toggle('has-mark', S.marker));
            cancelAnimationFrame(raf); raf = requestAnimationFrame(redrawEuclid);
        });
    }
    $('cReset').addEventListener('click', () => { S = {...FS.DEFAULTS}; save(); syncControls(); redrawEuclid(); });
    syncControls();

    $('ecForm').addEventListener('submit', (e) => { e.preventDefault(); show(); });
    $('ecFov').addEventListener('change', () => { if (pos) show(); });
    if (page.dataset.q) show();
})();
