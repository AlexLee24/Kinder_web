/* Lab › Special Run › Euclid-SLSN: results grid, run/progress polling and an in-browser stretch of the
   Euclid cutouts (raw float32 from /api/special_run/euclid_slsn/pixels/<slug>/<band>).
   Stretches: Auto STF (PixInsight Screen Transfer Function / Siril autostretch — the same maths as
   services/special_run/euclid_slsn.py:_stretch), asinh, log, sqrt, linear. Legacy Survey DR10 / DR11 colour
   cutouts at the same 0.1"/px scale sit next to them for comparison. */
(() => {
    const page = document.getElementById('srPage');
    if (!page) return;
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const fileUrl = (slug, f) => page.dataset.file.replace('SLUG', encodeURIComponent(slug)).replace('FNAME', f);
    const pixUrl = (slug, b) => page.dataset.pixels.replace('SLUG', encodeURIComponent(slug)).replace('BAND', b);
    const LS = 'https://www.legacysurvey.org/viewer';

    /* ------------------------------------------------------------ settings */
    const DEFAULTS = {
        mode: 'stf', shadows: -2.8, target: 0.25, black: 1.0, white: 99.8, soft: 0.05,
        cmap: 'gray', invert: false, nisp: 'rgb', linked: false, marker: true,
        show: {vis: true, nisp: true, dr10: true, dr11: true},
    };
    const KEY = 'kinder-euclid-slsn-view';
    let S = structuredClone(DEFAULTS);
    try { Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); S.show = {...DEFAULTS.show, ...(S.show || {})}; } catch (e) { /* private mode */ }
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* ignore */ } };

    /* ------------------------------------------------------------ colour maps (5-stop approximations) */
    const STOPS = {
        gray: [[0, 0, 0], [255, 255, 255]],
        inferno: [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]],
        viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
        cubehelix: [[0, 0, 0], [22, 66, 59], [161, 121, 74], [194, 168, 236], [255, 255, 255]],
    };
    function lut(name, invert) {
        const st = STOPS[name] || STOPS.gray, out = new Uint8ClampedArray(256 * 3);
        for (let i = 0; i < 256; i++) {
            const v = (invert ? 255 - i : i) / 255 * (st.length - 1), k = Math.min(Math.floor(v), st.length - 2), f = v - k;
            for (let c = 0; c < 3; c++) out[i * 3 + c] = st[k][c] + (st[k + 1][c] - st[k][c]) * f;
        }
        return out;
    }

    /* ------------------------------------------------------------ stretch maths */
    const mtf = (m, x) => ((m - 1) * x) / ((2 * m - 1) * x - m);

    function stats(img) {            // once per band: finite range + sorted sample for medians / percentiles
        if (img.stats) return img.stats;
        const d = img.data, n = d.length, step = Math.max(1, Math.floor(n / 60000));
        let lo = Infinity, hi = -Infinity;
        const sample = [];
        for (let i = 0; i < n; i++) {
            const v = d[i];
            if (!Number.isFinite(v)) continue;
            if (v < lo) lo = v;
            if (v > hi) hi = v;
            if (i % step === 0) sample.push(v);
        }
        const sorted = Float64Array.from(sample).sort();
        const q = (p) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p / 100 * (sorted.length - 1))))];
        const med = q(50);
        const dev = Float64Array.from(sorted, (v) => Math.abs(v - med)).sort();
        const mad = 1.4826 * dev[Math.floor(dev.length / 2)];
        img.stats = {lo, hi, med, mad, q};
        return img.stats;
    }

    /* returns a function value → [0,1] for the current settings */
    function transfer(img) {
        const {lo, hi, med, mad, q} = stats(img);
        const span = Math.max(hi - lo, 1e-30);
        if (S.mode === 'stf') {
            const xm = (med - lo) / span, xs = mad / span;
            const c0 = Math.min(Math.max(xm + S.shadows * xs, 0), 1);
            const m = mtf(S.target, Math.max(xm - c0, 1e-6));
            return (v) => {
                const y = Math.min(Math.max(((v - lo) / span - c0) / (1 - c0), 0), 1);
                return mtf(m, y);
            };
        }
        const b = q(S.black), w = Math.max(q(S.white), b + 1e-30);
        const lin = (v) => Math.min(Math.max((v - b) / (w - b), 0), 1);
        if (S.mode === 'asinh') { const k = Math.asinh(1 / S.soft); return (v) => Math.asinh(lin(v) / S.soft) / k; }
        if (S.mode === 'log') { const k = Math.log1p(1 / S.soft); return (v) => Math.log1p(lin(v) / S.soft) / k; }
        if (S.mode === 'sqrt') return (v) => Math.sqrt(lin(v));
        return lin;
    }

    /* paint one band (cmap) or three (RGB) onto a canvas, FITS row 0 at the bottom */
    function paint(canvas, chans, mark) {
        const w = Math.min(...chans.map((c) => c.w)), h = Math.min(...chans.map((c) => c.h));
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d'), im = ctx.createImageData(w, h), px = im.data;
        if (chans.length === 1) {
            const f = transfer(chans[0]), L = lut(S.cmap, S.invert), d = chans[0].data, cw = chans[0].w;
            for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
                const v = d[y * cw + x], t = Number.isFinite(v) ? Math.round(255 * f(v)) : 0, o = ((h - 1 - y) * w + x) * 4;
                px[o] = L[t * 3]; px[o + 1] = L[t * 3 + 1]; px[o + 2] = L[t * 3 + 2]; px[o + 3] = 255;
            }
        } else {
            let fs;
            if (S.linked) {   // linked: one transfer from the summed channel statistics
                const ref = {w: chans[0].w, h: chans[0].h, data: chans[0].data.map((v, i) => (v + chans[1].data[i] + chans[2].data[i]) / 3)};
                const f = transfer(ref); fs = [f, f, f];
            } else fs = chans.map(transfer);
            for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
                const o = ((h - 1 - y) * w + x) * 4;
                for (let c = 0; c < 3; c++) {
                    const v = chans[c].data[y * chans[c].w + x];
                    const t = Number.isFinite(v) ? fs[c](v) : 0;
                    px[o + c] = 255 * (S.invert ? 1 - t : t);
                }
                px[o + 3] = 255;
            }
        }
        ctx.putImageData(im, 0, 0);
        if (mark && S.marker && mark.x != null) drawMarker(ctx, mark.x, h - 1 - mark.y, h);
    }

    function drawMarker(ctx, x, y, size) {
        const gap = size * 0.035, arm = size * 0.07;
        ctx.lineWidth = Math.max(1.5, size / 160);
        ctx.strokeStyle = S.cmap === 'gray' ? (getComputedStyle(page).getPropertyValue('--color-accent').trim() || '#F39F5A') : '#33e6ff';
        ctx.beginPath();
        ctx.moveTo(x + gap, y); ctx.lineTo(x + gap + arm, y);       // east is left: arms point right and up
        ctx.moveTo(x, y - gap); ctx.lineTo(x, y - gap - arm);
        ctx.stroke();
    }

    /* ------------------------------------------------------------ data */
    const cache = new Map();   // `${slug}/${band}` → Promise<{w,h,data,tx,ty}>
    function band(slug, b) {
        const k = `${slug}/${b}`;
        if (!cache.has(k)) {
            cache.set(k, fetch(pixUrl(slug, b)).then(async (r) => {
                if (!r.ok) throw new Error(r.status);
                const w = +r.headers.get('X-Width'), h = +r.headers.get('X-Height');
                const tx = r.headers.get('X-Target-X'), ty = r.headers.get('X-Target-Y');
                return {w, h, data: new Float32Array(await r.arrayBuffer()), tx: tx === '' ? null : +tx, ty: ty === '' ? null : +ty};
            }).catch((e) => { cache.delete(k); throw e; }));
        }
        return cache.get(k);
    }

    let rows = [];   // covered results

    async function renderPanel(cv) {
        const slug = cv.dataset.slug, kind = cv.dataset.kind;
        try {
            if (kind === 'vis') {
                const v = await band(slug, 'VIS');
                paint(cv, [v], {x: v.tx, y: v.ty});
            } else {
                const names = S.nisp === 'rgb' ? ['NIR_H', 'NIR_J', 'NIR_Y'] : [S.nisp];
                const ch = await Promise.all(names.map((b) => band(slug, b)));
                paint(cv, ch, {x: ch[0].tx, y: ch[0].ty});
            }
            cv.closest('.sr-panel').classList.remove('is-err');
        } catch (e) {
            cv.closest('.sr-panel').classList.add('is-err');
        }
    }

    const seen = new IntersectionObserver((ents) => ents.forEach((e) => {
        if (e.isIntersecting) { seen.unobserve(e.target); e.target.dataset.live = '1'; renderPanel(e.target); }
    }), {rootMargin: '400px'});

    function redrawAll() {
        document.querySelectorAll('canvas.sr-cv[data-live="1"]').forEach(renderPanel);
    }

    const nispLabel = () => (S.nisp === 'rgb' ? 'NISP H / J / Y' : `NISP ${S.nisp.replace('NIR_', '')}`);
    const lsImg = (c, key) => page.dataset.ls.replace('SLUG', encodeURIComponent(c.slug)).replace('KEY', key) + `?v=${encodeURIComponent(lastFinished || '')}`;
    const lsLink = (c, layer) => `${LS}?ra=${c.ra}&dec=${c.dec}&layer=${layer}&zoom=16&mark=${c.ra},${c.dec}`;

    function panels(c, big) {
        const out = [];
        if (S.show.vis) out.push(`<figure class="sr-panel"><canvas class="sr-cv" data-slug="${esc(c.slug)}" data-kind="vis"></canvas><figcaption>Euclid ${esc((c.release || 'q1').toUpperCase())} VIS</figcaption></figure>`);
        if (S.show.nisp) out.push(`<figure class="sr-panel"><canvas class="sr-cv" data-slug="${esc(c.slug)}" data-kind="nisp"></canvas><figcaption>${nispLabel()}</figcaption></figure>`);
        for (const [key, layer, label] of [['dr10', 'ls-dr10', 'LS DR10'], ['dr11', 'ls-dr11', 'LS DR11']]) {
            if (!S.show[key]) continue;
            out.push(`<figure class="sr-panel sr-ls${S.marker ? ' has-mark' : ''}"><img loading="lazy" src="${lsImg(c, key)}" alt=""
                onerror="this.parentNode.classList.add('is-err');this.remove()">
                <figcaption><a href="${lsLink(c, layer)}" target="_blank" rel="noopener">${label} ↗</a></figcaption></figure>`);
        }
        return `<div class="sr-panels${big ? ' is-big' : ''}" style="--n:${Math.max(out.length, 1)}">${out.join('')}</div>`;
    }

    function card(c) {
        const name = c.in_db ? `<a href="/object/${encodeURIComponent(c.obj_name)}">${esc(c.name)}</a>` : esc(c.name);
        const alias = (c.aliases || []).length ? `<span class="sr-muted">${esc(c.aliases.join(', '))}</span>` : '';
        const z = c.redshift != null ? `z = ${(+c.redshift).toPrecision(4)}` : '';
        const fits = (c.bands || []).map((b) => `<a href="${fileUrl(c.slug, b + '.fits')}">${esc(b.replace('NIR_', ''))}</a>`).join('');
        const err = (c.errors || []).length ? `<span class="sr-muted">⚠ ${esc(c.errors.join('; '))}</span>` : '';
        return `<article class="kw-panel sr-card" data-slug="${esc(c.slug)}">
            <div class="sr-card-body"><b>${name}</b>${alias}<span>${esc(c.type || '')}</span><span>${z}</span>
            <span class="sr-muted">${(+c.ra).toFixed(5)} ${(+c.dec).toFixed(5)}</span>
            <span class="sr-fits">FITS ${fits}<button type="button" class="kw-btn kw-btn-ghost kw-btn-sm sr-zoom">Enlarge</button></span>${err}</div>
            ${panels(c, false)}</article>`;
    }

    function buildGrid() {
        $('srGrid').innerHTML = rows.map(card).join('');
        $('srGrid').querySelectorAll('canvas.sr-cv').forEach((cv) => seen.observe(cv));
    }

    /* ------------------------------------------------------------ controls */
    const ctl = {
        mode: $('cMode'), shadows: $('cShadows'), target: $('cTarget'), black: $('cBlack'), white: $('cWhite'),
        soft: $('cSoft'), cmap: $('cCmap'), invert: $('cInvert'), nisp: $('cNisp'), linked: $('cLinked'), marker: $('cMarker'),
    };
    const fmt = {shadows: (v) => `${(+v).toFixed(1)} σ`, target: (v) => (+v).toFixed(2), black: (v) => `${(+v).toFixed(1)} %`,
                 white: (v) => `${(+v).toFixed(2)} %`, soft: (v) => (+v).toFixed(3)};

    function syncControls() {
        for (const [k, el] of Object.entries(ctl)) {
            if (el.type === 'checkbox') el.checked = !!S[k]; else el.value = S[k];
            const out = document.querySelector(`[data-out="${k}"]`);
            if (out) out.textContent = fmt[k] ? fmt[k](S[k]) : '';
        }
        document.querySelectorAll('[data-show]').forEach((el) => { el.checked = !!S.show[el.dataset.show]; });
        page.dataset.mode = S.mode;
        ctl.linked.disabled = S.nisp !== 'rgb';
    }

    let raf = 0;
    const scheduleRedraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { redrawAll(); redrawBox(); }); };

    for (const [k, el] of Object.entries(ctl)) {
        el.addEventListener('input', () => {
            S[k] = el.type === 'checkbox' ? el.checked : (el.type === 'range' ? +el.value : el.value);
            save(); syncControls();
            if (k === 'nisp') { buildGrid(); redrawBox(true); return; }
            if (k === 'marker') { document.querySelectorAll('.sr-ls').forEach((f) => f.classList.toggle('has-mark', S.marker)); }
            scheduleRedraw();
        });
    }
    document.querySelectorAll('[data-show]').forEach((el) => el.addEventListener('change', () => {
        S.show[el.dataset.show] = el.checked; save(); buildGrid(); redrawBox(true);
    }));
    $('cReset').addEventListener('click', () => { S = structuredClone(DEFAULTS); save(); syncControls(); buildGrid(); redrawBox(true); });
    syncControls();

    /* ------------------------------------------------------------ enlarge */
    const box = $('srBox');
    let boxRow = null;
    function redrawBox(rebuild) {
        if (!boxRow || !box.open) return;
        const body = box.querySelector('.sr-box-body');
        if (rebuild || !body.firstChild) {
            body.innerHTML = panels(boxRow, true);
            body.querySelectorAll('canvas.sr-cv').forEach((cv) => { cv.dataset.live = '1'; renderPanel(cv); });
        } else body.querySelectorAll('canvas.sr-cv').forEach(renderPanel);
    }
    $('srGrid').addEventListener('click', (e) => {
        const btn = e.target.closest('.sr-zoom');
        if (!btn) return;
        boxRow = rows.find((r) => r.slug === btn.closest('.sr-card').dataset.slug);
        box.querySelector('.sr-box-title').textContent = `${boxRow.name}  ${boxRow.type || ''}  ${boxRow.redshift != null ? 'z = ' + (+boxRow.redshift).toPrecision(4) : ''}`;
        box.showModal();
        redrawBox(true);
    });
    box.addEventListener('click', (e) => { if (e.target === box || e.target.closest('.sr-box-close')) box.close(); });

    /* ------------------------------------------------------------ run + status */
    let timer = null, lastFinished;

    function renderResults(r) {
        const cov = r.covered || [], miss = r.not_covered || [];
        $('kTargets').textContent = r.n_targets ?? '–';
        $('kCovered').textContent = r.finished ? cov.length : '–';
        $('kTiles').textContent = r.n_tiles ?? '–';
        $('kLast').textContent = r.finished || '–';
        $('srZip').hidden = !cov.length;
        $('srEmpty').hidden = !!cov.length;
        if (r.finished === lastFinished) return;
        lastFinished = r.finished;
        cache.clear();
        rows = cov;
        buildGrid();
        $('srMissBox').hidden = !miss.length;
        $('srMissN').textContent = miss.length;
        $('srMiss').innerHTML = miss.map((m) => `<li${m.reason && !m.reason.startsWith("outside") ? ` title="${esc(m.reason)}"` : ""}>${esc(m.name)}${m.reason && !m.reason.startsWith("outside") ? " *" : ""}</li>`).join('');
    }

    function renderStatus(s) {
        const running = s.state === 'running';
        $('srRun').disabled = running;
        $('srRun').textContent = running ? 'Running…' : 'Run';
        $('kState').textContent = {running: 'running now', done: 'finished', error: 'failed', stale: 'interrupted', idle: 'never'}[s.state] || s.state || 'never';
        $('srProgress').classList.toggle('is-on', running || s.state === 'error' || s.state === 'stale');
        $('srStep').textContent = s.step || '';
        $('srCount').textContent = s.total ? `${s.done || 0} / ${s.total}` : '';
        $('srBar').style.width = s.total ? `${Math.round(100 * (s.done || 0) / s.total)}%` : (running ? '4%' : '0');
        const log = $('srLog');
        log.textContent = (s.log || []).join('\n');
        log.scrollTop = log.scrollHeight;
        return running;
    }

    async function poll() {
        clearTimeout(timer);
        try {
            const res = await fetch(page.dataset.status, {cache: 'no-store'});
            const data = await res.json();
            const running = renderStatus(data.status || {});
            renderResults(data.results || {});
            if (running) timer = setTimeout(poll, 2000);
        } catch (e) {
            timer = setTimeout(poll, 5000);
        }
    }

    $('srRun').addEventListener('click', async () => {
        $('srRun').disabled = true;
        try {
            const res = await fetch(page.dataset.run, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({refresh: $('srRefresh').checked}),
            });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                alert(d.error || `Run failed (${res.status})`);
            }
        } finally {
            poll();
        }
    });

    poll();
})();
