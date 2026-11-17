/* Daily Trigger: "Last night" (automatic photometry of the night's frames, /api/daily_trigger/auto_phot) and, on the
   Observation Targets table, a survey cutout per row and a popout with the whole target (opened from its row). Loaded after daily_trigger.js and built on
   its state and actions: allTargetsCache, renderTable / switchTab / fillAstroInfo (wrapped here), editTarget,
   toggleTargetActive, deleteTarget, copyTargetToTelescope, openSingleTriggerModal, drawMiniVisibilitySVG. */
(function () {
    'use strict';

    const API = '/api/daily_trigger/auto_phot';
    const FCOL = { u: '#c05cff', g: '#2fc46e', r: '#ff3b3b', i: '#ff70a6', z: '#e8a0a0', y: '#e8853a', o: '#ffa500', c: '#22e5ff',
                   w: '#eeb861', b: '#5b8cff', v: '#b6e34a' };
    const STATE = { done: 'Detected', lim: 'Not detected · limits', failed: 'Failed', running: 'Measuring', queued: 'Queued',
                    waiting: 'Not measured yet', skipped: 'EP · not measured' };
    const SHORT = { done: 'Detected', lim: 'Limits only', failed: 'Failed', running: 'Measuring', queued: 'Queued',
                    waiting: 'Not measured', skipped: 'EP' };
    const PRI = ['Urgent', 'High', 'Normal', 'Filler'];
    const $ = id => document.getElementById(id);
    // daily_trigger.js keeps the targets in a top-level `let`: shared between classic scripts, but not on window
    // eslint-disable-next-line no-undef
    const tgts = () => (typeof allTargetsCache !== 'undefined' && Array.isArray(allTargetsCache) ? allTargetsCache : []);

    let data = null, night = null, refreshTimer = null, latest = {}, selected = null, wsTimer = null;
    const lcCache = {}, astro = {};

    function el(tag, attrs, ...kids) {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v == null || v === false) continue;
            if (k === 'text') n.textContent = v;
            else if (k === 'class') n.className = v;
            else if (k === 'html') n.innerHTML = v;
            else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
            else n.setAttribute(k, v === true ? '' : v);
        }
        for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c);
        return n;
    }
    const band = f => { const s = String(f || '').trim(); return (s.length > 1 && /p$/i.test(s) ? s.slice(0, -1) : s).toLowerCase(); };
    const col = f => FCOL[band(f)] || '#9a9aa5';
    const fchip = f => el('span', { class: 'dta-f', style: `--fc:${col(f)}`, text: f });
    const objUrl = name => '/object/' + encodeURIComponent(String(name).replace(/^(AT|SN|TDE|FRB)\s?/i, ''));
    const dets = r => (r.phot || []).filter(p => p.det && p.mag != null);
    const rowState = r => r.status === 'done' ? (dets(r).length ? 'done' : 'lim') : r.status;
    const priOf = name => { const t = (tgts()).find(x => x.name === name); return t ? t.priority : ''; };

    function stateEl(r, short) {
        const s = rowState(r);
        const txt = s === 'running' && r.n_frames && !short ? `Measuring · ${r.n_done || 0} of ${r.n_frames} frames` : (short ? SHORT : STATE)[s] || s;
        return el('span', { class: 'dta-state is-' + s }, s === 'running' ? el('span', { class: 'dta-spin', 'aria-hidden': 'true' }) : null, txt);
    }
    // Failed or running: the state opens the details (why it failed, how the run is going, the log)
    function stateBtn(r, short) {
        const s = rowState(r);
        if (!r.id || (s !== 'failed' && s !== 'running')) return stateEl(r, short);
        return el('button', { type: 'button', class: 'dta-why', title: s === 'failed' ? 'Why it failed' : 'Log of the run',
                              'aria-haspopup': 'dialog', onclick: () => openDetails(r) },
            stateEl(r, short), el('span', { class: 'dta-why-more', text: s === 'failed' ? 'Why?' : 'Log' }));
    }
    let dlgTimer = null;
    async function openDetails(r) {
        const dlg = $('dtAutoDlg');
        clearTimeout(dlgTimer);
        const fill = async first => {
            let d;
            try {
                const res = await fetch(`${API}/${r.id}/details`, { credentials: 'same-origin' });
                d = await res.json();
                if (!d.success) throw new Error(d.error || 'Could not load');
            } catch (e) { d = { error: e.message }; }
            if (!first && !dlg.open) return;
            const st = d.status === 'done' && !(r.phot || []).some(p => p.det) ? 'lim' : (d.status || r.status);
            const pre = el('pre', { class: 'dta-log', tabindex: '0', 'aria-label': 'Last lines of the AutoPhOT log', text: d.log || 'No log yet.' });
            dlg.replaceChildren(...[
                el('div', { class: 'dta-dlg-head' },
                    el('div', {}, el('h2', { id: 'dtAutoDlgTitle', text: `${r.target} · ${r.telescope}` }),
                        el('div', { class: 'dta-sub' }, r.night, ' · ', stateEl({ ...r, status: d.status || r.status, n_done: d.n_done ?? r.n_done, n_frames: d.n_frames ?? r.n_frames, phot: st === 'lim' ? [] : r.phot }))),
                    el('form', { method: 'dialog' }, el('button', { class: 'dta-iconbtn', value: 'close', 'aria-label': 'Close', html: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>' }))),
                d.error ? el('p', { class: 'dta-warn', text: d.error }) : null,
                d.reason ? el('div', { class: 'dta-reason' }, el('b', { text: d.status === 'failed' ? 'Reason' : 'Note' }), el('p', { text: d.reason })) : null,
                d.n_in != null ? el('p', { class: 'dta-muted dtw-small', text: `${d.n_ok ?? 0} of ${d.n_in} images measured` + (d.progress ? ` · ${d.progress.done} of ${d.progress.total} done in this run` : '') }) : null,
                d.images && d.images.length ? el('section', {}, el('h3', { text: 'Images not measured' }),
                    el('ul', { class: 'dta-list' }, d.images.map(f => el('li', {}, el('span', { class: 'mono', text: f.name }),
                        f.filter ? el('span', { class: 'dta-muted', text: ' · ' + f.filter }) : null,
                        el('div', { class: 'dta-muted dtw-small', text: f.hint || (f.errors || []).slice(-1)[0] || ({ FAIL: 'AutoPhOT failed on this image (see the log)', SKIPPED: 'Skipped before photometry' }[f.status] || f.status) })))) ) : null,
                d.problems && d.problems.length ? el('section', {}, el('h3', { text: 'Errors AutoPhOT reported' }),
                    el('ul', { class: 'dta-list' }, d.problems.map(p => el('li', { class: 'dtw-small' }, p.text, p.n > 1 ? el('span', { class: 'dta-muted', text: ` (×${p.n})` }) : null)))) : null,
                el('section', {}, el('h3', { text: 'Log' }), pre),
                el('div', { class: 'dta-dlg-foot' },
                    d.pipeline ? el('a', { class: 'kw-btn kw-btn-sm', href: d.pipeline, text: 'Open the Pipeline run' }) : null,
                    d.status === 'failed' ? el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-primary', text: 'Retry', onclick: e => { retry(r, e.currentTarget); dlg.close(); } }) : null,
                    el('form', { method: 'dialog' }, el('button', { class: 'kw-btn kw-btn-sm', value: 'close', autofocus: true, text: 'Close' })))].filter(Boolean));
            pre.scrollTop = pre.scrollHeight;
            if (d.status === 'running' || d.status === 'queued') dlgTimer = setTimeout(() => fill(false), 10000);
        };
        dlg.replaceChildren(el('p', { class: 'dta-muted', text: 'Loading…' }));
        if (!dlg.open) dlg.showModal();
        await fill(true);
    }

    function magEl(p) {
        return p.det && p.mag != null
            ? el('span', { class: 'dta-mag' }, el('span', { class: 'mono', text: p.mag.toFixed(2) }), el('span', { class: 'mono dta-err', text: ' ±' + (p.err != null ? p.err.toFixed(2) : '—') }))
            : el('span', { class: 'mono dta-lim', text: p.lim != null ? '>' + p.lim.toFixed(1) : 'no limit' });
    }
    function bestPerFilter(r) {
        const by = {};
        for (const p of r.phot || []) {
            const k = band(p.filter), cur = by[k];
            if (!cur || (p.det && !cur.det) || (p.det === cur.det && (p.snr || 0) > (cur.snr || 0))) by[k] = p;
        }
        return Object.values(by).sort((a, b) => 'ugrizyocw'.indexOf(band(a.filter)) - 'ugrizyocw'.indexOf(band(b.filter)));
    }
    function deltaEl(r) {
        const ds = bestPerFilter(r).filter(p => p.det && p.mag != null);
        const p = ['r', 'g', 'i', 'z', 'o', 'c'].map(f => ds.find(x => band(x.filter) === f && (r.prev || {})[x.filter])).find(Boolean)
            || ds.find(x => (r.prev || {})[x.filter]);
        if (!p) return el('span', { class: 'dta-muted', text: '—' });
        const prev = r.prev[p.filter], d = p.mag - prev.mag, days = Math.max(0, Math.round(p.mjd - prev.mjd));
        return el('span', { class: 'mono dta-delta ' + (d > 0.05 ? 'is-fade' : d < -0.05 ? 'is-rise' : ''),
                            title: `Previous ${p.filter}: ${prev.mag.toFixed(2)} (${prev.telescope || '?'}), ${days} d earlier` },
            `${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(2)} ${band(p.filter)}`, el('span', { class: 'dta-muted', text: ` in ${days} d` }));
    }
    function thumb(r, f, cls) {
        return el('img', { class: 'dta-thumb ' + (cls || ''), loading: 'lazy', width: cls === 'is-lg' ? 128 : 44, height: cls === 'is-lg' ? 128 : 44,
                           src: `${API}/${r.id}/frame/${encodeURIComponent(f)}.png`,
                           alt: `${r.target} ${f}-band frame, ${r.night}, 60 arcsec around the target` });
    }
    function links(r) {
        const out = [];
        if (r.obj_name) out.push(el('a', { href: objUrl(r.obj_name), text: 'Transient page' }));
        if (r.pipeline) out.push(el('a', { href: r.pipeline, text: 'Pipeline run' }));
        return out.flatMap((a, i) => i ? [el('span', { class: 'dta-muted', text: ' · ' }), a] : [a]);
    }
    // frames of the night per filter (what will be / is being measured)
    function framesEl(r) {
        const fc = r.frame_counts || {};
        const ks = Object.keys(fc).sort((a, b) => 'ugrizyocw'.indexOf(a) - 'ugrizyocw'.indexOf(b));
        if (!ks.length) return el('span', { class: 'dta-muted', text: r.n_frames ? `${r.n_frames} frames` : '—' });
        return el('div', { class: 'dta-mags' }, ks.map(f => el('span', {}, el('i', { class: 'dta-dot', style: `background:${col(f)}` }),
            el('span', { class: 'dta-muted', text: f + ' ' }), el('span', { class: 'mono dta-muted', text: `${fc[f]} frame${fc[f] > 1 ? 's' : ''}` }))));
    }
    async function measure(r, btn) {
        btn.disabled = true;
        btn.textContent = 'Queued';
        try {
            const res = await fetch(API + '/measure', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                                                        body: JSON.stringify({ night: r.night, target: r.target, telescope: r.telescope }) });
            const d = await res.json();
            if (!d.success) throw new Error(d.error || 'Failed');
            load(night);
        } catch (e) { btn.disabled = false; btn.textContent = 'Measure now'; alert(e.message); }
    }
    async function retry(r, btn) {
        btn.disabled = true;
        btn.textContent = 'Queued';
        try {
            const res = await fetch(`${API}/${r.id}/retry`, { method: 'POST', credentials: 'same-origin' });
            const d = await res.json();
            if (!d.success) throw new Error(d.error || 'Failed');
            load(night);
        } catch (e) { btn.disabled = false; btn.textContent = 'Retry'; alert(e.message); }
    }

    // ── Last night ───────────────────────────────────────────────────────────
    async function load(n) {
        clearTimeout(refreshTimer);
        const names = [...new Set((tgts()).map(t => t.name))].join(',');
        try {
            const q = new URLSearchParams();
            if (n) q.set('night', n);
            if (names) q.set('latest', names);
            const res = await fetch(API + '?' + q, { credentials: 'same-origin' });
            const d = await res.json();
            if (!d.success) throw new Error(d.error || 'Could not load');
            data = d; night = d.night; latest = d.latest || {};
            renderNight();
            scheduleWs();
            if (d.rows.some(r => r.status === 'queued' || r.status === 'running')) refreshTimer = setTimeout(() => load(night), 15000);
            else if (d.rows.some(r => r.status === 'waiting')) refreshTimer = setTimeout(() => load(night), 60000);
        } catch (e) {
            const tb = $('dtAutoTable').tBodies[0];
            tb.replaceChildren(el('tr', {}, el('td', { colspan: 6, class: 'dta-empty', text: 'Could not load last night: ' + e.message })));
        }
    }

    function renderNight() {
        const d = data, rows = d.rows;
        const dt = new Date(night + 'T00:00:00Z');
        $('dtAutoNight').textContent = dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
        $('dtAutoTitle').textContent = night === d.last_night ? 'Last night' : 'Night of';
        const known = [...new Set([d.last_night, ...d.nights.map(x => x.night)])].sort();
        const i = known.indexOf(night);
        $('dtAutoPrev').disabled = i <= 0;
        $('dtAutoNext').disabled = night >= d.last_night;
        $('dtAutoPrev').onclick = () => load(i > 0 ? known[i - 1] : night);
        $('dtAutoNext').onclick = () => load(known[i + 1] || d.last_night);

        const measured = rows.filter(r => r.status !== 'skipped');
        const n = s => measured.filter(r => rowState(r) === s).length;
        const frames = measured.reduce((a, r) => a + (r.n_frames || 0), 0);
        const sum = [[frames, 'frames'], [measured.length, 'targets'], [n('done'), 'detected'], [n('lim'), 'limits only'],
                     [n('failed'), 'failed'], [n('running') + n('queued'), 'measuring'], [n('waiting'), 'not measured yet']];
        $('dtAutoSum').replaceChildren(...(rows.length ? sum.filter(([v], k) => k < 3 || v).map(([v, l]) => el('div', {}, el('b', { class: 'mono', text: String(v) }), el('span', { text: l }))) : []));

        const order = { running: 0, done: 1, lim: 2, queued: 3, waiting: 4, failed: 5 };
        const tb = $('dtAutoTable').tBodies[0];
        if (!measured.length) {
            tb.replaceChildren(el('tr', {}, el('td', { colspan: 6, class: 'dta-empty',
                text: rows.length ? 'Only EP targets were observed; they are left to the EP pipeline' : 'No calibrated frames from this night' })));
        } else {
            tb.replaceChildren(...measured.sort((a, b) => (order[rowState(a)] - order[rowState(b)]) ||
                (PRI.indexOf(priOf(a.target)) - PRI.indexOf(priOf(b.target))) || a.target.localeCompare(b.target)).map(rowEl));
        }
        const skipped = rows.filter(r => r.status === 'skipped').map(r => r.target);
        const notObj = measured.filter(r => r.status === 'done' && !r.obj_name).map(r => r.target);
        $('dtAutoFoot').replaceChildren(...[
            skipped.length ? el('span', { text: `Left to the EP pipeline: ${skipped.join(', ')}` }) : null,
            notObj.length ? el('span', { text: `Not Kinder objects (measured, not on a Transient page): ${notObj.join(', ')}` }) : null,
        ].filter(Boolean));
    }

    function rowEl(r) {
        const s = rowState(r), best = bestPerFilter(r);
        const veto = (r.phot || []).find(p => !p.det && p.veto);
        const pri = priOf(r.target);
        return el('tr', { 'aria-busy': s === 'running' ? 'true' : null, class: s === 'running' ? 'is-running' : null },
            el('th', { scope: 'row' },
                el('button', { type: 'button', class: 'dta-name', text: r.target, title: 'Open the target', 'aria-haspopup': 'dialog', onclick: () => focusTarget(r.target, r.telescope) }),
                el('div', { class: 'dta-sub' }, r.telescope, pri ? el('span', { class: 'dta-pri is-' + pri.toLowerCase(), text: ' · ' + pri }) : null)),
            el('td', { 'data-l': 'Frame' }, r.frames && r.frames.length ? thumb(r, r.frames.includes('r') ? 'r' : r.frames[0]) : el('span', { class: 'dta-muted', text: '—' })),
            el('td', { 'data-l': 'Magnitudes' }, best.length
                ? el('div', { class: 'dta-mags' }, best.map(p => el('span', {}, el('i', { class: 'dta-dot', style: `background:${col(p.filter)}` }), el('span', { class: 'dta-muted', text: band(p.filter) + ' ' }), magEl(p))))
                : s === 'failed' ? el('span', { class: 'dta-muted', text: r.reason || 'No measurement' }) : framesEl(r)),
            el('td', { 'data-l': 'Since last epoch', class: 'dta-nowrap' }, deltaEl(r)),
            el('td', { 'data-l': 'Status' }, stateBtn(r),
                veto ? el('div', { class: 'dta-note', text: veto.veto }) : null,
                s === 'done' && !r.obj_name ? el('div', { class: 'dta-note', text: 'Not a Kinder object' }) : null),
            el('td', { class: 'dta-right dta-nowrap' },
                s === 'failed' ? el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Retry', onclick: e => retry(r, e.currentTarget) }) : null,
                s === 'waiting' ? el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Measure now', onclick: e => measure(r, e.currentTarget) }) : null,
                s !== 'failed' && s !== 'waiting' ? links(r) : null));
    }

    // ── Observation Targets: a survey cutout and a popout button per row; the row opens the target ──
    function currentTel() { return document.getElementById('tab-LOT')?.classList.contains('active') ? 'LOT' : 'SLT'; }
    function latestFor(t) { return (latest[t.name] || []).find(r => r.telescope === t.telescope) || (latest[t.name] || [])[0] || null; }
    function scheduleWs() { clearTimeout(wsTimer); wsTimer = setTimeout(renderWs, 30); }
    const rowId = tr => { const b = tr && tr.querySelector('.pa-sel-box[data-tid]'); return b ? Number(b.dataset.tid) : null; };
    const rowOf = id => document.querySelector(`.pa-sel-box[data-tid="${id}"]`)?.closest('tr') || null;
    const tableRows = tel => [...document.querySelectorAll(`#${tel.toLowerCase()}-list > tr`)].filter(tr => rowId(tr) != null);
    const OPEN_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>';

    function renderWs() {
        for (const tel of ['SLT', 'LOT']) {
            const all = (tgts()).filter(t => t.telescope === tel);
            tableRows(tel).forEach(tr => decorateRow(tr, all.find(x => x.id === rowId(tr))));
        }
        const dlg = $('dtTargetDlg');
        if (dlg && dlg.open) {
            const t = (tgts()).find(x => x.id === selected);
            if (t) { renderDetail(t); navState(); } else dlg.close();
        }
    }

    function decorateRow(tr, t) {
        if (!t) return;
        tr.classList.add('dtp-row');
        tr.classList.toggle('is-open', t.id === selected && !!$('dtTargetDlg')?.open);
        // the popout button, beside the name
        const home = tr.querySelector('.pa-name-line');
        if (home && !home.querySelector('.dtp-open')) {
            home.append(el('button', { type: 'button', class: 'dtp-open', html: OPEN_SVG, title: 'Open the target',
                                       'aria-label': `Open ${t.name}`, 'aria-haspopup': 'dialog', onclick: () => openTarget(t.id) }));
        }
        const cell = tr.querySelector('.pa-td-sky');
        if (cell && !tr.classList.contains('pa-row-off') && !cell.querySelector('.dtp-sky')) {
            const sky = skyThumb(t);
            if (sky) cell.append(sky);
        }
        // the latest automatic photometry under the name
        tr.querySelector('.dtw-auto')?.remove();
        const r = latestFor(t), box = tr.querySelector('.pa-td-name-content');
        if (!r || !box || tr.classList.contains('pa-row-off')) return;
        const b = bestPerFilter(r).find(p => p.det && p.mag != null);
        box.append(el('div', { class: 'dtw-auto' }, stateEl(r, true),
            b ? el('span', { class: 'mono', text: `${band(b.filter)} ${b.mag.toFixed(2)}` }) : null,
            el('span', { class: 'mono dta-muted', text: r.night === (data && data.last_night) ? 'last night' : r.night.slice(5) })));
    }

    // a 60″ survey cutout for a table row: the first survey that has the position (the same chain as the popout)
    function skyThumb(t) {
        const ra = typeof parseRAToDeg === 'function' ? parseRAToDeg(t.ra) : parseFloat(t.ra);
        const dec = typeof parseDecToDeg === 'function' ? parseDecToDeg(t.dec) : parseFloat(t.dec);
        if (!Number.isFinite(ra) || !Number.isFinite(dec)) return null;
        const key = `${ra.toFixed(5)},${dec.toFixed(5)}`;
        let i = skyFound[key] ?? 0;
        const btn = el('button', { type: 'button', class: 'dtp-sky', title: 'Open the target' });
        const lab = el('span', { class: 'dtp-sky-lab' });
        const img = el('img', { loading: 'lazy', decoding: 'async', width: 88, height: 88, alt: '' });
        btn.addEventListener('click', e => { e.stopPropagation(); openTarget(t.id); });
        const none = () => { btn.className = 'dtp-sky is-empty'; btn.title = 'No survey image here'; btn.replaceChildren(); btn.disabled = true; };
        const tryNext = () => {
            if (i >= SKY.length) { skyFound[key] = SKY.length; none(); return; }
            img.dataset.label = SKY[i][1];
            img.src = `/api/cutouts/image?ra=${ra.toFixed(6)}&dec=${dec.toFixed(6)}&fov=60&src=${SKY[i][0]}`;
        };
        img.addEventListener('load', () => {
            skyFound[key] = i;
            btn.classList.add('has-img');
            lab.textContent = SHORT_SKY[SKY[i][0]] || img.dataset.label;
            btn.setAttribute('aria-label', `Open ${t.name} · ${img.dataset.label} image, 60 arcsec`);
        });
        img.addEventListener('error', () => { i += 1; skyFound[key] = Math.max(skyFound[key] ?? 0, i); tryNext(); });
        btn.setAttribute('aria-label', `Open ${t.name}`);
        btn.append(img, lab);
        if (i >= SKY.length) none(); else tryNext();
        return btn;
    }

    // the popout
    function openTarget(id) {
        const t = (tgts()).find(x => x.id === id);
        const dlg = $('dtTargetDlg');
        if (!t || !dlg) return;
        selected = id;
        renderDetail(t);
        navState();
        if (!dlg.open) dlg.showModal();
        dlg.scrollTop = 0;
        document.querySelectorAll('tr.dtp-row.is-open').forEach(x => x.classList.remove('is-open'));
        rowOf(id)?.classList.add('is-open');
    }
    function siblings() {
        const t = (tgts()).find(x => x.id === selected);
        const ids = t ? tableRows(t.telescope).map(rowId) : [];
        return { ids, i: ids.indexOf(selected) };
    }
    function navState() {
        const { ids, i } = siblings();
        const t = (tgts()).find(x => x.id === selected);
        $('dtTargetPrev').disabled = i <= 0;
        $('dtTargetNext').disabled = i < 0 || i >= ids.length - 1;
        $('dtTargetPos').textContent = i >= 0 ? `${i + 1} of ${ids.length} · ${t.telescope}` : '';
    }
    function step(d) {
        const { ids, i } = siblings();
        if (i >= 0 && ids[i + d] != null) openTarget(ids[i + d]);
    }

    function plan(t) {
        const fs = (t.filters || []).filter(f => f && f.filter);
        const total = fs.reduce((a, f) => a + (parseInt(f.exp) || 0) * (parseInt(f.count) || 0), 0);
        return el('dl', { class: 'dtw-dl' },
            el('dt', { text: 'Filters' }), el('dd', {}, fs.length ? el('span', { class: 'dtw-filters' }, fs.map(f => el('span', { class: 'dtw-fx' }, fchip(f.filter), el('span', { class: 'mono dta-muted', text: `${f.exp}s × ${f.count}` })))) : '—'),
            el('dt', { text: 'Total exposure' }), el('dd', { class: 'mono', text: total ? total + ' s' : '—' }),
            el('dt', { text: 'Last observed' }), el('dd', { class: 'mono', text: t.last_observed ? String(t.last_observed).slice(0, 10) : 'Never' }),
            t.mag ? el('dt', { text: 'Mag' }) : null, t.mag ? el('dd', { class: 'mono', text: t.mag }) : null,
            t.repeat_count > 0 ? el('dt', { text: 'Repeat' }) : null, t.repeat_count > 0 ? el('dd', { text: String(t.repeat_count) }) : null,
        );
    }

    function renderDetail(t) {
        const box = $('dtWsDetail');
        if (!t) { box.dataset.lc = ''; box.replaceChildren(); return; }
        const r = latestFor(t);
        const coord = typeof formatTargetCoordValue === 'function' ? formatTargetCoordValue(t.ra, t.dec) : { ra: t.ra, dec: t.dec };
        const a = astro[t.id];
        // keep the drawn light curve while the same target (and the same automatic row) stays picked
        const lcKey = `${t.id}|${r ? r.id + ':' + r.updated_at : ''}`;
        const keep = box.dataset.lc === lcKey ? $('dtWsLc') : null;
        box.dataset.lc = lcKey;
        box.replaceChildren(
            el('div', { class: 'dtw-head' },
                el('div', {},
                    el('h2', { class: 'dtw-title', id: 'dtTargetDlgTitle' }, el('a', { href: objUrl(t.name), text: t.name }), t.program ? el('span', { class: 'pa-program-badge', text: t.program }) : null),
                    el('div', { class: 'dtw-coords mono' }, `${coord.ra}  ${coord.dec}`, el('span', { class: 'dta-muted', text: `  ·  ${t.telescope}  ·  ` }),
                        el('span', { class: 'dta-pri is-' + String(t.priority || '').toLowerCase(), text: t.priority || '' })),
                    a ? el('div', { class: 'dtw-astro' }, el('span', { text: `Moon ${a.moon_separation != null ? a.moon_separation + '°' : '—'}` }),
                        el('span', { text: `Transit ${a.transit_time_local ? a.transit_time_local.slice(11, 16) : '—'}` }),
                        el('span', { text: `Peak ${a.altitudes && a.altitudes.length ? Math.round(Math.max(...a.altitudes)) + '°' : '—'}` })) : null),
                // the notes next to the name, where they are read first
                (t.plan || t.note_gl) ? el('dl', { class: 'dtw-notes' },
                    t.plan ? el('div', {}, el('dt', { text: 'Note for Lulin' }), el('dd', { text: t.plan })) : null,
                    t.note_gl ? el('div', {}, el('dt', { text: 'Note for Lab' }), el('dd', { text: t.note_gl })) : null) : null),
            keep || el('div', { class: 'dtw-lc', id: 'dtWsLc' },
                el('div', { id: 'telescopeToggles', style: 'display:none; flex-wrap:wrap; gap:6px; padding:0 0 10px;' }),
                el('div', { id: 'dtWsLcPlot', class: 'dtw-lc-plot' }, el('div', { class: 'dta-muted dtw-small', text: 'Loading the light curve…' })),
                el('div', { id: 'photLegend', style: 'display:none; flex-wrap:wrap; gap:4px 6px; padding:8px 0 6px; max-height:108px; overflow-y:auto; border-top:1px solid rgba(255,255,255,0.06); margin-top:8px;' })),
            el('section', { 'aria-label': 'Latest automatic photometry' },
                el('div', { class: 'dtw-sh' }, el('h4', { text: r ? (r.night === (data && data.last_night) ? 'Last night' : 'Night of ' + r.night) : 'Automatic photometry' }), r ? stateBtn(r) : null),
                r ? lastNightTable(r) : el('p', { class: 'dta-muted dtw-small', text: 'No frames of this target have been measured yet' })),
            fieldSection(t, r),
            el('div', { class: 'dtw-two' },
                el('section', { 'aria-label': 'Plan' }, el('div', { class: 'dtw-sh' }, el('h4', { text: 'Plan' })), plan(t)),
                el('section', { 'aria-label': 'Visibility tonight' }, el('div', { class: 'dtw-sh' }, el('h4', { text: 'Tonight from Lulin' })),
                    el('div', { class: 'dtw-vis', html: a && a.altitudes && typeof drawMiniVisibilitySVG === 'function' ? drawMiniVisibilitySVG(a.altitudes, a._times) : '<span class="dta-muted dtw-small">—</span>' }))));
        if (!keep) drawLc(t);
    }

    // The frames' whole field (the telescope's field of view, north up) per filter, then a survey image of the same sky
    const fieldCache = {};                       // row id → {field} once the server has drawn it
    const arcmin = v => (v / 60).toFixed(v < 600 ? 1 : 0) + '′';
    function fieldSection(t, r) {
        const head = el('div', { class: 'dtw-sh' }, el('h4', { text: 'Field' }));
        const body = el('div', { class: 'dtw-field', id: 'dtWsField' });
        const sec = el('section', { 'aria-label': 'Field of view and a survey image' }, head, body);
        const fill = f => {
            if (!f) {                                // nothing measured (yet): the survey around the target
                head.append(el('span', { class: 'dta-muted dtw-small', text: 'Survey, 60″ around the target' }));
                body.classList.add('is-small');
                body.replaceChildren(skyFig(t) || el('p', { class: 'dta-muted dtw-small', text: '—' }));
                return;
            }
            head.append(el('span', { class: 'dta-muted dtw-small', text: `${r.telescope} field · ${arcmin(f.w)} × ${arcmin(f.h)} · north up` }));
            const ratio = `${f.w} / ${f.h}`;
            const fig = (src, cap, alt, capCls) => el('figure', {},
                el('a', { href: src, target: '_blank', rel: 'noopener', title: 'Open full size' },
                    el('img', { src, alt, loading: 'lazy', style: `aspect-ratio:${ratio}` })),
                el('figcaption', { class: capCls || 'mono', text: cap }));
            const base = `${API}/${r.id}`;
            const figs = f.filters.map(b => fig(`${base}/field/${encodeURIComponent(b)}.png`, b, `${t.name} ${b}-band frame, ${r.night}, the whole ${r.telescope} field`));
            const sv = f.survey || {};
            figs.push(sv.key ? fig(`${base}/survey.jpg`, sv.label, `${sv.label} image of the same field`, 'dtw-sky-cap')
                             : el('figure', {}, el('span', { class: 'dtw-field-empty', style: `aspect-ratio:${ratio}` }),
                                  el('figcaption', { class: 'dta-muted', text: 'No survey image' })));
            body.replaceChildren(...figs);
        };
        if (!r || r.status !== 'done') { fill(null); return sec; }
        if (fieldCache[r.id]) { fill(fieldCache[r.id].field); return sec; }
        body.replaceChildren(el('p', { class: 'dta-muted dtw-small', text: 'Drawing the field…' }));
        fetch(`${API}/${r.id}/field`, { credentials: 'same-origin' }).then(res => res.json()).then(d => {
            if (!d.success) throw new Error(d.error || 'failed');
            fieldCache[r.id] = { field: d.field };
            if (body.isConnected) fill(d.field);
        }).catch(() => { if (body.isConnected) fill(null); });
        return sec;
    }

    // A survey image of the same 60″, from the first survey that has the position: Euclid, DESI Legacy, Pan-STARRS1, others
    const SKY = [['vis', 'Euclid VIS'], ['dr11', 'Legacy DR11'], ['dr10', 'Legacy DR10'], ['ps1', 'Pan-STARRS1'],
                 ['hsc', 'HSC PDR3'], ['sdss', 'SDSS']];
    const SHORT_SKY = { vis: 'Euclid', dr11: 'DR11', dr10: 'DR10', ps1: 'PS1', hsc: 'HSC', sdss: 'SDSS' };
    const skyFound = {};                         // position → first SKY index still worth asking (SKY.length: none has it)
    function skyFig(t) {
        const ra = typeof parseRAToDeg === 'function' ? parseRAToDeg(t.ra) : parseFloat(t.ra);
        const dec = typeof parseDecToDeg === 'function' ? parseDecToDeg(t.dec) : parseFloat(t.dec);
        if (!Number.isFinite(ra) || !Number.isFinite(dec)) return null;
        const key = `${ra.toFixed(5)},${dec.toFixed(5)}`;
        let i = skyFound[key] ?? 0;
        const cap = el('figcaption', { class: 'dta-muted', text: 'Survey…' });
        const img = el('img', { class: 'dta-thumb is-lg dtw-sky-img', width: 128, height: 128, alt: '' });
        const fig = el('figure', { class: 'dtw-sky' },
            el('a', { href: '/sky_cutouts?q=' + encodeURIComponent(`${ra.toFixed(6)} ${dec.toFixed(6)}`) + '&fov=60', title: 'Open in Sky Cutouts' }, img), cap);
        const none = () => fig.replaceChildren(el('span', { class: 'dta-thumb is-lg is-empty', 'aria-hidden': 'true' }),
                                               el('figcaption', { class: 'dta-muted', text: 'No survey image' }));
        const tryNext = () => {
            if (i >= SKY.length) { skyFound[key] = SKY.length; none(); return; }
            const [src, label] = SKY[i];
            img.alt = `${label} image, 60 arcsec around ${t.name}`;
            img.dataset.label = label;
            img.src = `/api/cutouts/image?ra=${ra.toFixed(6)}&dec=${dec.toFixed(6)}&fov=60&src=${src}`;
        };
        img.addEventListener('load', () => { skyFound[key] = i; cap.textContent = img.dataset.label; cap.className = 'dtw-sky-cap'; });
        img.addEventListener('error', () => { i += 1; skyFound[key] = Math.max(skyFound[key] ?? 0, i); tryNext(); });   // a re-render starts past it
        if (i >= SKY.length) none(); else tryNext();
        return fig;
    }

    function lastNightTable(r) {
        const best = r.phot || [];
        if (!best.length) return el('p', { class: 'dtw-small ' + (r.status === 'failed' ? 'dta-warn' : 'dta-muted'), text: r.reason || (r.status === 'skipped' ? 'EP targets are left to the EP pipeline' : `${r.n_frames} frames, measuring`) });
        return el('div', {},
            el('table', { class: 'dta-mini' },
                el('thead', {}, el('tr', {}, ['Filter', 'Magnitude', 'S/N', 'MJD'].map(h => el('th', { scope: 'col', text: h })))),
                el('tbody', {}, best.map(p => el('tr', {}, el('th', { scope: 'row' }, fchip(p.filter)), el('td', {}, magEl(p), p.veto && !p.det ? el('div', { class: 'dta-note', text: p.veto }) : null),
                    el('td', { class: 'mono', text: p.snr != null ? p.snr.toFixed(1) : '—' }), el('td', { class: 'mono dta-muted', text: p.mjd != null ? p.mjd.toFixed(3) : '' }))))),
            el('p', { class: 'dtw-small dta-muted' }, r.obj_name ? ['On the Transient page as ', el('span', { class: 'mono', text: r.label }), ' · ', deltaEl(r)] : 'Not a Kinder object: not added to a Transient page',
                r.pipeline ? [' · ', el('a', { href: r.pipeline, text: 'Pipeline run' })] : null));
    }

    // The Transient page's light curve (lc_plot.js: the same Plotly figure, telescope toggles, filter legend, phase axis)
    const LC_TTL = 120e3;
    const whenPlotly = () => new Promise((res, rej) => {
        if (window.Plotly) return res();
        const t0 = Date.now(), t = setInterval(() => {
            if (window.Plotly) { clearInterval(t); res(); } else if (Date.now() - t0 > 20e3) { clearInterval(t); rej(new Error('Plotly did not load')); }
        }, 100);
    });
    async function lcData(t) {
        const c = lcCache[t.name];
        if (c && Date.now() - c.at < LC_TTL) return c;
        const j = async u => { const res = await fetch(u, { credentials: 'same-origin' }); return res.json(); };
        const o = await j('/api/daily_trigger/target_lc?name=' + encodeURIComponent(t.name));
        const d = { at: Date.now(), object: o.success ? o.object : null, disc: o.discoverydate || null, plot: null };
        if (d.object) d.plot = await j(`/api/object/${encodeURIComponent(d.object)}/photometry/plot?extinction=false&k_corr=false`);
        return (lcCache[t.name] = d);
    }
    async function drawLc(t) {
        const say = text => { const b = $('dtWsLcPlot'); if (b && selected === t.id) b.replaceChildren(el('p', { class: 'dta-muted dtw-small', text })); };
        let d;
        try { d = await lcData(t); } catch (e) { say('Could not load the light curve'); return; }
        if (!d.object) { say('Not a Kinder object: no light curve'); return; }
        if (!d.plot || !d.plot.success || !d.plot.plot_json) { say((d.plot && (d.plot.message || d.plot.error)) || 'No photometry on the Transient page yet'); return; }
        try { await whenPlotly(); } catch (e) { say('Could not load the plotting library'); return; }
        const box = $('dtWsLcPlot');
        if (!box || selected !== t.id) return;
        const disc = _mjdFromDateString(d.disc);
        lcPhaseRefDefault = disc != null ? { mjd: disc, custom: false } : null;
        try { lcDraw(box, d.plot, fig => lcAddPhaseAxis(fig, lcPhaseRefDefault, 'Phase (days since discovery)'), 420); }
        catch (e) { console.error('dt_auto: light curve', e); say('Could not draw the light curve'); }
    }

    function focusTarget(name, tel) {
        const t = (tgts()).find(x => x.name === name && x.telescope === tel) || (tgts()).find(x => x.name === name);
        if (!t) { window.location.href = objUrl(name); return; }
        if (currentTel() !== t.telescope && typeof switchTab === 'function') switchTab(t.telescope);
        openTarget(t.id);
    }

    // ── hooks into daily_trigger.js ──────────────────────────────────────────
    const origRender = window.renderTable;
    if (typeof origRender === 'function') window.renderTable = function () { const out = origRender.apply(this, arguments); scheduleWs(); return out; };
    const origSwitch = window.switchTab;
    if (typeof origSwitch === 'function') window.switchTab = function () { const out = origSwitch.apply(this, arguments); scheduleWs(); return out; };
    const origFill = window.fillAstroInfo;
    if (typeof origFill === 'function') window.fillAstroInfo = function (id, td, times) {
        astro[id] = { ...td, _times: times };
        if (id === selected) scheduleWs();
        return origFill.apply(this, arguments);
    };
    let loadTimer = null;
    const origLoad = window.loadTargets;
    if (typeof origLoad === 'function') window.loadTargets = async function () {
        const out = await origLoad.apply(this, arguments);
        clearTimeout(loadTimer);
        loadTimer = setTimeout(() => load(night), 50);          // the targets changed: their latest rows too
        return out;
    };

    // a click anywhere on a row (not on its own controls) opens the target
    const ROW_CONTROLS = 'input, button, a, label, select, textarea, .pa-td-coord, .pa-row-off .pa-td-note, .pa-copy-menu, .pa-mini-plot, .pa-td-actions';
    function wireRows() {
        document.querySelector('.pa-obs-section')?.addEventListener('click', e => {
            if (e.target.closest(ROW_CONTROLS) || String(window.getSelection() || '')) return;   // selecting text is not a click
            const tr = e.target.closest('tbody > tr.dtp-row');
            if (tr && rowId(tr) != null) openTarget(rowId(tr));
        });
        const dlg = $('dtTargetDlg');
        if (!dlg) return;
        $('dtTargetPrev').addEventListener('click', () => step(-1));
        $('dtTargetNext').addEventListener('click', () => step(1));
        dlg.addEventListener('keydown', e => {
            if (e.target.closest('input, textarea, select, .js-plotly-plot')) return;
            if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
            if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
        });
        dlg.addEventListener('close', () => {
            const tr = rowOf(selected);
            document.querySelectorAll('tr.dtp-row.is-open').forEach(x => x.classList.remove('is-open'));
            selected = null;
            (tr?.querySelector('.dtp-open'))?.focus({ preventScroll: true });
        });
    }

    function lightDismiss(dlg) {                                   // where closedby="any" is missing
        if (!dlg || 'closedBy' in HTMLDialogElement.prototype) return;
        const outside = e => { const b = dlg.getBoundingClientRect(); return e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom; };
        let down = false;
        dlg.addEventListener('pointerdown', e => { down = outside(e); });
        dlg.addEventListener('pointerup', e => { if (down && outside(e)) dlg.close(); });
    }

    function init() {
        const dlg = $('dtAutoDlg');
        if (dlg) dlg.addEventListener('close', () => clearTimeout(dlgTimer));
        lightDismiss(dlg);
        lightDismiss($('dtTargetDlg'));
        try { localStorage.removeItem('dt-target-view'); } catch (e) { /* private mode */ }
        wireRows();
        renderWs();
        setTimeout(() => { if (!data) load(night); }, 1500);    // normally loadTargets (above) asks first
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
