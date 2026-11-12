/* Tools › Spectrum (spectrum.html): load a DESI coadd by TARGETID from /api/spectrum/desi/<id> and plot it.
   Smoothing (inverse-variance weighted boxcar), 1σ band, rest frame, line markers, CSV / PNG export run here. */
(function () {
    'use strict';

    const page = document.querySelector('.sp-page');
    if (!page) return;
    const API = page.dataset.api;
    const $ = (id) => document.getElementById(id);
    const form = $('spForm'), plotEl = $('spPlot'), statusEl = $('spStatus'), infoEl = $('spInfo');
    const ARM_COLORS = { b: '#4FA3FF', r: '#FF6B61', z: '#C77DFF' };
    const RECENT_KEY = 'kinder-spectrum-recent';

    // Vacuum rest wavelengths (Å), as DESI / SDSS use them
    const LINES = [
        { n: 'Lyα', w: 1215.67, k: 'em' }, { n: 'C IV', w: 1549.06, k: 'em' }, { n: 'C III]', w: 1908.73, k: 'em' },
        { n: 'Mg II', w: 2798.75, k: 'em' }, { n: '[O II]', w: 3728.48, k: 'em' }, { n: '[Ne III]', w: 3870.16, k: 'em' },
        { n: 'Hδ', w: 4102.89, k: 'em' }, { n: 'Hγ', w: 4341.69, k: 'em' }, { n: 'He II', w: 4687.02, k: 'em' },
        { n: 'Hβ', w: 4862.68, k: 'em' }, { n: '[O III]', w: 4960.30, k: 'em' }, { n: '[O III]', w: 5008.24, k: 'em' },
        { n: 'He I', w: 5877.25, k: 'em' }, { n: '[O I]', w: 6302.05, k: 'em' }, { n: '[N II]', w: 6549.86, k: 'em' },
        { n: 'Hα', w: 6564.61, k: 'em' }, { n: '[N II]', w: 6585.27, k: 'em' }, { n: '[S II]', w: 6718.29, k: 'em' },
        { n: '[S II]', w: 6732.67, k: 'em' },
        { n: 'Ca K', w: 3934.78, k: 'abs' }, { n: 'Ca H', w: 3969.59, k: 'abs' }, { n: 'G band', w: 4305.61, k: 'abs' },
        { n: 'Mg b', w: 5176.70, k: 'abs' }, { n: 'Na D', w: 5895.60, k: 'abs' }, { n: 'Ca II', w: 8544.44, k: 'abs' },
    ];

    let spec = null;       // last API payload
    let zLines = null;     // redshift used for lines / rest frame
    let loading = 0;       // request counter: a late answer to an older request is ignored

    // ── helpers ──────────────────────────────────────────────────────────
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmt = (v, d) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
    const cssVar = (name, fb) => (getComputedStyle(document.documentElement).getPropertyValue(name) || '').trim() || fb;

    function setStatus(msg, kind) {
        statusEl.hidden = !msg;
        statusEl.textContent = msg || '';
        statusEl.className = 'sp-status' + (kind ? ' is-' + kind : '');
    }

    function smooth(flux, ivar, n) {
        const len = flux.length, h = (n - 1) >> 1, f = new Array(len), e = new Array(len);
        for (let i = 0; i < len; i++) {
            let sw = 0, sf = 0;
            for (let j = Math.max(0, i - h); j <= Math.min(len - 1, i + h); j++) {
                const w = ivar[j];
                if (w > 0) { sw += w; sf += w * flux[j]; }
            }
            if (sw > 0 && ivar[i] > 0) { f[i] = sf / sw; e[i] = 1 / Math.sqrt(sw); }
            else { f[i] = null; e[i] = null; }
        }
        return { f, e };
    }

    function percentile(arr, p) {
        const a = arr.filter((v) => v !== null && Number.isFinite(v)).sort((x, y) => x - y);
        if (!a.length) return null;
        return a[Math.min(a.length - 1, Math.max(0, Math.round((p / 100) * (a.length - 1))))];
    }

    // ── recent TARGETIDs (this browser only) ─────────────────────────────
    function recentGet() {
        try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]').filter((x) => /^\d+$/.test(x)).slice(0, 8); }
        catch (e) { return []; }
    }
    function recentAdd(id) {
        const list = [id, ...recentGet().filter((x) => x !== id)].slice(0, 8);
        try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* private mode */ }
        recentRender();
    }
    function recentRender() {
        const box = $('spRecent'), list = recentGet();
        box.hidden = !list.length;
        box.innerHTML = list.map((id) => `<button type="button" data-id="${esc(id)}" title="Load ${esc(id)}">${esc(id)}</button>`).join('');
    }
    $('spRecent').addEventListener('click', (ev) => {
        const b = ev.target.closest('button[data-id]');
        if (!b) return;
        $('spTargetid').value = b.dataset.id;
        load();
    });

    // ── load ─────────────────────────────────────────────────────────────
    async function load(refresh) {
        const id = $('spTargetid').value.trim();
        if (!/^\d+$/.test(id)) { setStatus('TARGETID is a positive integer, e.g. 39627857210645888.', 'error'); return; }
        const q = new URLSearchParams();
        for (const [k, el] of [['release', 'spRelease'], ['survey', 'spSurvey'], ['program', 'spProgram'], ['ra', 'spRa'], ['dec', 'spDec']]) {
            const v = $(el).value.trim();
            if (v) q.set(k, v);
        }
        if (refresh) q.set('refresh', '1');

        const page_q = new URLSearchParams({ targetid: id });
        for (const k of ['release', 'survey', 'program']) if (q.get(k)) page_q.set(k, q.get(k));
        history.replaceState(null, '', location.pathname + '?' + page_q.toString());

        const my = ++loading;
        $('spLoad').disabled = true;
        setStatus(`Reading TARGETID ${id} from the DESI data server… (a first look-up takes about 5–15 s)`, 'loading');
        try {
            const r = await fetch(API + id + (q.toString() ? '?' + q : ''), { headers: { Accept: 'application/json' } });
            const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
            if (my !== loading) return;
            if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
            spec = data;
            zLines = data.z;
            $('spZ').value = data.z !== null && data.z !== undefined ? Number(data.z).toFixed(5) : '';
            recentAdd(String(data.targetid));
            renderInfo();
            draw();
            setStatus('');
            $('spCsv').disabled = $('spPng').disabled = false;
        } catch (e) {
            if (my !== loading) return;
            setStatus(e.message || String(e), 'error');
        } finally {
            if (my === loading) $('spLoad').disabled = false;
        }
    }

    form.addEventListener('submit', (ev) => { ev.preventDefault(); load(); });

    // ── info panel ───────────────────────────────────────────────────────
    function renderInfo() {
        const d = spec;
        const zwarn = d.zwarn ? `<span class="sp-warn">${esc(d.zwarn)}</span>` : (d.zwarn === 0 ? '0' : '—');
        const ra = d.ra, dec = d.dec;
        const lsUrl = (ra !== null && dec !== null)
            ? `https://www.legacysurvey.org/viewer?ra=${ra}&dec=${dec}&zoom=16&mark=${ra},${dec}&layer=ls-dr10-grz&desi-spec-dr1`
            : null;
        const mags = ['g', 'r', 'z'].filter((b) => d.mag && d.mag[b] !== null && d.mag[b] !== undefined)
            .map((b) => `${b} ${fmt(d.mag[b], 2)}`).join(' · ');
        const alts = (d.alternatives || []).map((a) => {
            const cur = a.release === d.release && a.survey === d.survey && a.program === d.program;
            return `<button type="button" class="sp-alt${cur ? ' is-current' : ''}" data-alt="${esc(a.release)}|${esc(a.survey)}|${esc(a.program)}"
                title="z = ${fmt(a.z, 4)}${a.zwarn ? ' · ZWARN ' + esc(a.zwarn) : ''}${a.primary ? ' · ZCAT primary' : ''}">${esc(a.release.toUpperCase())} ${esc(a.survey)}/${esc(a.program)}${a.primary ? ' ★' : ''}</button>`;
        });
        infoEl.innerHTML = `
            <div class="sp-info-head">
                <span class="sp-info-id">${esc(d.targetid)}</span>
                <button type="button" class="sp-copy" data-copy="${esc(d.targetid)}">Copy ID</button>
                <span class="kw-chip">${esc(d.release_label)}</span>
                <span class="kw-chip">${esc(d.survey)}/${esc(d.program)}</span>
                ${d.spectype ? `<span class="kw-chip kw-chip-gold">${esc(d.spectype)}${d.subtype ? ' · ' + esc(d.subtype) : ''}</span>` : ''}
            </div>
            <dl class="sp-facts">
                <div><dt>Redshift</dt><dd>${fmt(d.z, 5)}${d.zerr !== null ? `<small>± ${fmt(d.zerr, 5)} · ${esc(d.z_source)}</small>` : ''}</dd></div>
                <div><dt>ZWARN</dt><dd>${zwarn}</dd></div>
                <div><dt>Δχ²</dt><dd>${fmt(d.deltachi2, 1)}</dd></div>
                <div><dt>RA, Dec</dt><dd>${fmt(ra, 6)}<small>${fmt(dec, 6)}</small></dd></div>
                <div><dt>HEALPix (64, nest)</dt><dd>${esc(d.healpix)}</dd></div>
                <div><dt>Exposure</dt><dd>${d.coadd_exptime !== null ? fmt(d.coadd_exptime, 0) + ' s' : '—'}<small>${d.coadd_numexp ?? '—'} exposure(s)</small></dd></div>
                ${mags ? `<div><dt>LS mag</dt><dd>${esc(mags)}${d.morphtype ? `<small>${esc(d.morphtype)}</small>` : ''}</dd></div>` : ''}
                <div><dt>Spectrum</dt><dd>${d.primary ? 'ZCAT primary' : 'secondary coadd'}<small>${d.in_catalogue ? 'in cat.desi' : 'not in cat.desi'} · ${d.cached ? 'Kinder cache' : 'read in ' + fmt(d.fetch_seconds, 1) + ' s'}</small></dd></div>
            </dl>
            ${alts.length > 1 ? `<div class="sp-alts"><span class="sp-alts-label">All coadds of this target</span>${alts.join('')}</div>` : ''}
            <div class="sp-links">
                ${lsUrl ? `<a href="${esc(lsUrl)}" target="_blank" rel="noopener noreferrer">Legacy Survey viewer</a>` : ''}
                <a href="${esc(d.coadd_url)}" target="_blank" rel="noopener noreferrer" title="Whole HEALPix coadd file (100–200 MB)">Coadd FITS</a>
                <a href="#" data-refresh="1" title="Read it again from the DESI server">Reload from DESI</a>
            </div>`;
        infoEl.hidden = false;
    }

    infoEl.addEventListener('click', (ev) => {
        const c = ev.target.closest('[data-copy]');
        if (c) {
            navigator.clipboard?.writeText(c.dataset.copy).then(() => {
                c.textContent = 'Copied'; setTimeout(() => { c.textContent = 'Copy ID'; }, 1200);
            });
            return;
        }
        if (ev.target.closest('[data-refresh]')) { ev.preventDefault(); load(true); return; }
        const alt = ev.target.closest('[data-alt]');
        if (alt && !alt.classList.contains('is-current')) {
            const [rel, sv, pg] = alt.dataset.alt.split('|');
            $('spRelease').value = rel; $('spSurvey').value = sv; $('spProgram').value = pg;
            load();
        }
    });

    // ── plot ─────────────────────────────────────────────────────────────
    function draw() {
        if (!spec || !window.Plotly) {
            if (spec && !window.Plotly) setTimeout(draw, 200);
            return;
        }
        plotEl.hidden = false;
        const n = parseInt($('spSmooth').value, 10) || 1;
        $('spSmoothVal').textContent = n === 1 ? 'off' : n + ' px';
        const rest = $('spRest').checked && zLines !== null && zLines !== undefined && zLines > -0.01;
        const scale = rest ? 1 / (1 + zLines) : 1;
        const showErr = $('spErr').checked, showRaw = $('spRaw').checked;

        const traces = [], allF = [];
        let xmin = Infinity, xmax = -Infinity;
        for (const arm of ['b', 'r', 'z']) {
            const a = spec.arms[arm];
            if (!a) continue;
            const x = a.wave.map((w) => w * scale);
            xmin = Math.min(xmin, x[0]); xmax = Math.max(xmax, x[x.length - 1]);
            const s = smooth(a.flux, a.ivar, n);
            allF.push(...s.f);
            if (showRaw && n > 1) {
                traces.push({ x, y: a.flux.map((v, i) => (a.ivar[i] > 0 ? v : null)), type: 'scatter', mode: 'lines',
                    line: { color: ARM_COLORS[arm], width: 0.6 }, opacity: 0.3, hoverinfo: 'skip', showlegend: false });
            }
            if (showErr) {
                traces.push({ x, y: s.f.map((v, i) => (v === null ? null : v + s.e[i])), type: 'scatter', mode: 'lines',
                    line: { width: 0 }, hoverinfo: 'skip', showlegend: false });
                traces.push({ x, y: s.f.map((v, i) => (v === null ? null : v - s.e[i])), type: 'scatter', mode: 'lines',
                    line: { width: 0 }, fill: 'tonexty', fillcolor: ARM_COLORS[arm] + '33', hoverinfo: 'skip', showlegend: false });
            }
            traces.push({ x, y: s.f, type: 'scatter', mode: 'lines', name: arm + ' arm',
                line: { color: ARM_COLORS[arm], width: 1.3 },
                hovertemplate: `%{x:.1f} Å<br>%{y:.3g}<extra>${arm}</extra>` });
        }

        const lo = percentile(allF, 0.5), hi = percentile(allF, 99.5);
        const pad = (hi - lo) * 0.15 || 1;
        const yr = (lo !== null && hi !== null) ? [lo - pad, hi + pad * 1.6] : undefined;

        const text = cssVar('--kw-text-secondary', 'rgba(245,245,247,0.72)');
        const grid = 'rgba(255,255,255,0.08)';
        const shapes = [], annotations = [];
        if (zLines !== null && zLines !== undefined && Number.isFinite(zLines)) {
            const kinds = new Set();
            if ($('spEmLines').checked) kinds.add('em');
            if ($('spAbsLines').checked) kinds.add('abs');
            // Labels on three rows; a label that would touch another on every row is left off (the line stays).
            const plotPx = Math.max(200, (plotEl.clientWidth || 800) - 80);   // ~ plot area width
            const minGap = (xmax - xmin) * 44 / plotPx, rows = [-Infinity, -Infinity, -Infinity];
            const shown = LINES.filter((L) => kinds.has(L.k))
                .map((L) => Object.assign({ xo: L.w * (1 + zLines) * scale }, L))
                .filter((L) => L.xo >= xmin && L.xo <= xmax)
                .sort((a, b) => a.xo - b.xo);
            for (const L of shown) {
                const col = L.k === 'em' ? 'rgba(255,214,10,' : 'rgba(100,210,255,';
                shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: L.xo, x1: L.xo, y0: 0, y1: 1,
                    line: { color: col + '0.5)', width: 1, dash: 'dot' } });
                const row = rows.findIndex((last) => L.xo - last >= minGap);
                if (row < 0) continue;
                rows[row] = L.xo;
                annotations.push({ x: L.xo, y: 1 - row * 0.05, xref: 'x', yref: 'paper', yanchor: 'bottom',
                    text: L.n, showarrow: false, font: { size: 10, color: col + '0.95)' },
                    hovertext: `${L.n} ${L.w.toFixed(2)} Å (rest)`, bgcolor: 'rgba(7,6,26,0.55)' });
            }
        }

        const layout = {
            margin: { l: 64, r: 16, t: 44, b: 52 },
            paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
            font: { color: text, size: 12 },
            xaxis: { title: { text: rest ? `Rest-frame wavelength (Å), z = ${Number(zLines).toFixed(4)}` : 'Observed wavelength (Å)' },
                gridcolor: grid, zeroline: false, range: [xmin, xmax], tickformat: 'd' },
            yaxis: { title: { text: 'F<sub>λ</sub> (10<sup>-17</sup> erg s<sup>-1</sup> cm<sup>-2</sup> Å<sup>-1</sup>)' },
                gridcolor: grid, zerolinecolor: 'rgba(255,255,255,0.18)', range: yr },
            legend: { orientation: 'h', x: 1, xanchor: 'right', y: -0.16, font: { size: 11 } },
            hovermode: 'x unified',
            shapes, annotations,
        };
        Plotly.react(plotEl, traces, layout, { responsive: true, displaylogo: false,
            modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
            toImageButtonOptions: { filename: `desi-${spec.targetid}`, scale: 2 } });
    }

    for (const id of ['spSmooth', 'spRest', 'spErr', 'spRaw', 'spEmLines', 'spAbsLines']) {
        $(id).addEventListener('input', draw);
    }
    $('spZ').addEventListener('change', () => {
        const v = parseFloat($('spZ').value);
        zLines = Number.isFinite(v) ? v : (spec ? spec.z : null);
        draw();
    });
    $('spZReset').addEventListener('click', () => {
        if (!spec) return;
        zLines = spec.z;
        $('spZ').value = spec.z !== null ? Number(spec.z).toFixed(5) : '';
        draw();
    });

    // ── export ───────────────────────────────────────────────────────────
    $('spCsv').addEventListener('click', () => {
        if (!spec) return;
        const rows = ['# DESI ' + spec.release_label + ' coadd, TARGETID ' + spec.targetid + ', ' + spec.survey + '/' + spec.program +
            ', HEALPix ' + spec.healpix + ', z = ' + (spec.z ?? ''), 'arm,wavelength_A,flux_1e-17,ivar'];
        for (const arm of ['b', 'r', 'z']) {
            const a = spec.arms[arm];
            if (!a) continue;
            for (let i = 0; i < a.wave.length; i++) rows.push(`${arm},${a.wave[i]},${a.flux[i]},${a.ivar[i]}`);
        }
        const url = URL.createObjectURL(new Blob([rows.join('\n') + '\n'], { type: 'text/csv' }));
        const link = Object.assign(document.createElement('a'), { href: url, download: `desi-${spec.targetid}.csv` });
        document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $('spPng').addEventListener('click', () => {
        if (spec && window.Plotly) Plotly.downloadImage(plotEl, { format: 'png', filename: `desi-${spec.targetid}`, width: 1400, height: 600, scale: 2 });
    });

    // ── start ────────────────────────────────────────────────────────────
    recentRender();
    if (page.dataset.targetid) load();
})();
