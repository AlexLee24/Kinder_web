/* Daily Trigger: "Last night" (automatic photometry of the night's frames, /api/daily_trigger/auto_phot) and the
   Observation Targets workspace view (target list + the selected target). Loaded after daily_trigger.js and built on
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

    let data = null, night = null, refreshTimer = null, latest = {}, view = 'ws', selected = null, wsTimer = null;
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
    const mjdNow = () => Date.now() / 864e5 + 40587;
    const nightMjd = iso => Date.parse(iso + 'T12:00:00Z') / 864e5 + 40587;
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
                el('button', { type: 'button', class: 'dta-name', text: r.target, title: 'Show in the target workspace', onclick: () => focusTarget(r.target, r.telescope) }),
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

    // ── Workspace view ───────────────────────────────────────────────────────
    function currentTel() { return document.getElementById('tab-LOT')?.classList.contains('active') ? 'LOT' : 'SLT'; }
    function latestFor(t) { return (latest[t.name] || []).find(r => r.telescope === t.telescope) || (latest[t.name] || [])[0] || null; }
    function scheduleWs() { clearTimeout(wsTimer); wsTimer = setTimeout(renderWs, 30); }

    function setView(v) {
        view = v;
        try { localStorage.setItem('dt-target-view', v); } catch (e) { /* private mode */ }
        const sec = document.querySelector('.pa-obs-section');
        sec.classList.toggle('is-ws', v === 'ws');
        $('dtWs').hidden = v !== 'ws';
        document.querySelectorAll('[data-dtview]').forEach(b => {
            const on = b.dataset.dtview === v;
            b.setAttribute('aria-pressed', String(on));
            b.classList.toggle('is-on', on);
        });
        if (v === 'ws') renderWs();
    }

    function renderWs() {
        if (view !== 'ws') return;
        const tel = currentTel();
        const all = (tgts()).filter(t => t.telescope === tel);
        const rank = t => PRI.indexOf(t.priority) < 0 ? 9 : PRI.indexOf(t.priority);
        const on = all.filter(t => t.is_active !== false).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
        const off = all.filter(t => t.is_active === false).sort((a, b) => a.name.localeCompare(b.name));
        if (!all.some(t => t.id === selected)) selected = (on[0] || off[0] || {}).id ?? null;
        const list = $('dtWsList');
        const item = t => {
            const r = latestFor(t), b = r ? bestPerFilter(r).find(p => p.det && p.mag != null) : null;
            const f = r && r.frames && r.frames.length ? (r.frames.includes('r') ? 'r' : r.frames[0]) : null;
            return el('button', { type: 'button', class: 'dtw-item' + (t.is_active === false ? ' is-off' : ''),
                                  'aria-current': t.id === selected ? 'true' : 'false', 'data-id': t.id,
                                  onclick: () => { selected = t.id; renderWs(); } },
                f ? thumb(r, f) : el('span', { class: 'dta-thumb is-empty', 'aria-hidden': 'true' }),
                el('span', { class: 'dtw-item-main' }, el('span', { class: 'dtw-item-name', text: t.name }),
                    el('span', { class: 'dtw-item-sub' }, el('span', { class: 'dta-pri is-' + String(t.priority || '').toLowerCase(), text: t.priority || '—' }),
                        r && r.night !== (data && data.last_night) ? el('span', { class: 'mono', text: ' · ' + r.night.slice(5) }) : null)),
                el('span', { class: 'dtw-item-r' }, b ? el('span', { class: 'mono', text: `${band(b.filter)} ${b.mag.toFixed(2)}` }) : null,
                    r ? stateEl(r, true) : el('span', { class: 'dta-muted dtw-small', text: t.last_observed ? 'Not measured' : 'Never observed' })));
        };
        list.replaceChildren(
            el('div', { class: 'dtw-group', text: `Tonight · ${on.length}` }), ...on.map(item),
            off.length ? el('div', { class: 'dtw-group', text: `Off · ${off.length}` }) : null, ...off.map(item));
        if (!all.length) list.append(el('p', { class: 'dta-empty', text: `No ${tel} targets yet` }));
        renderDetail(all.find(t => t.id === selected));
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
            el('dt', { text: 'Note' }), el('dd', { text: t.plan || '—' }),
            el('dt', { text: 'Note for GREATLab' }), el('dd', { text: t.note_gl || '—' }));
    }

    function renderDetail(t) {
        const box = $('dtWsDetail');
        if (!t) { box.replaceChildren(el('p', { class: 'dta-empty', text: 'Pick a target' })); return; }
        const other = t.telescope === 'SLT' ? 'LOT' : 'SLT';
        const r = latestFor(t);
        const coord = typeof formatTargetCoordValue === 'function' ? formatTargetCoordValue(t.ra, t.dec) : { ra: t.ra, dec: t.dec };
        const a = astro[t.id];
        const sw = el('label', { class: 'pa-action-switch', title: t.is_active !== false ? 'On tonight: in the target list Lulin gets' : 'Off: not sent tonight' },
            el('input', { type: 'checkbox', checked: t.is_active !== false ? true : null, 'aria-label': 'On tonight',
                          onchange: e => toggleTargetActive(t.id, e.currentTarget.checked) }), el('span', { class: 'pa-action-slider' }));
        box.replaceChildren(
            el('div', { class: 'dtw-head' },
                el('div', {},
                    el('h3', { class: 'dtw-title' }, el('a', { href: objUrl(t.name), text: t.name }), t.program ? el('span', { class: 'pa-program-badge', text: t.program }) : null),
                    el('div', { class: 'dtw-coords mono' }, `${coord.ra}  ${coord.dec}`, el('span', { class: 'dta-muted', text: `  ·  ${t.telescope}  ·  ` }),
                        el('span', { class: 'dta-pri is-' + String(t.priority || '').toLowerCase(), text: t.priority || '' })),
                    a ? el('div', { class: 'dtw-astro' }, el('span', { text: `Moon ${a.moon_separation != null ? a.moon_separation + '°' : '—'}` }),
                        el('span', { text: `Transit ${a.transit_time_local ? a.transit_time_local.slice(11, 16) : '—'}` }),
                        el('span', { text: `Peak ${a.altitudes && a.altitudes.length ? Math.round(Math.max(...a.altitudes)) + '°' : '—'}` })) : null),
                el('div', { class: 'dtw-actions' },
                    el('span', { class: 'dtw-switch' }, sw, el('span', { text: t.is_active !== false ? 'On tonight' : 'Off' })),
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Edit', onclick: () => editTarget(t.id) }),
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Copy to ' + other, onclick: e => copyTargetToTelescope(e, t.id, other) }),
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm', text: 'Delete', onclick: () => deleteTarget(t.id) }),
                    el('button', { type: 'button', class: 'kw-btn kw-btn-sm kw-btn-primary', text: 'Trigger', onclick: () => openSingleTriggerModal(t.id) }))),
            el('div', { class: 'dtw-lc', id: 'dtWsLc' }, el('div', { class: 'dta-muted dtw-small', text: 'Loading the light curve…' })),
            el('div', { class: 'dtw-two' },
                el('section', { 'aria-label': 'Latest automatic photometry' },
                    el('div', { class: 'dtw-sh' }, el('h4', { text: r ? (r.night === (data && data.last_night) ? 'Last night' : 'Night of ' + r.night) : 'Automatic photometry' }), r ? stateBtn(r) : null),
                    r ? lastNightTable(r) : el('p', { class: 'dta-muted dtw-small', text: 'No frames of this target have been measured yet' })),
                el('section', { 'aria-label': 'Frames' },
                    el('div', { class: 'dtw-sh' }, el('h4', { text: 'Frames' }), r ? el('span', { class: 'dta-muted dtw-small', text: '60″ around the target' }) : null),
                    r && r.frames && r.frames.length ? el('div', { class: 'dtw-frames' }, r.frames.map(f => el('figure', {}, thumb(r, f, 'is-lg'), el('figcaption', { class: 'mono', text: f })))) : el('p', { class: 'dta-muted dtw-small', text: '—' }))),
            el('div', { class: 'dtw-two' },
                el('section', { 'aria-label': 'Plan' }, el('div', { class: 'dtw-sh' }, el('h4', { text: 'Plan' })), plan(t)),
                el('section', { 'aria-label': 'Visibility tonight' }, el('div', { class: 'dtw-sh' }, el('h4', { text: 'Tonight from Lulin' })),
                    el('div', { class: 'dtw-vis', html: a && a.altitudes && typeof drawMiniVisibilitySVG === 'function' ? drawMiniVisibilitySVG(a.altitudes, a._times) : '<span class="dta-muted dtw-small">—</span>' }))));
        drawLc(t, r);
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

    async function drawLc(t, r) {
        const box = () => $('dtWsLc');
        let pts = lcCache[t.name];
        if (!pts) {
            try {
                const res = await fetch('/api/daily_trigger/target_lc?name=' + encodeURIComponent(t.name), { credentials: 'same-origin' });
                const d = await res.json();
                pts = lcCache[t.name] = d.success ? d.points : [];
            } catch (e) { pts = []; }
        }
        if (!box() || selected !== t.id) return;
        const now = mjdNow(), x0 = now - 60, recent = pts.filter(p => p.mjd >= x0 && p.mag != null);
        if (!recent.length) { box().replaceChildren(el('p', { class: 'dta-muted dtw-small', text: pts.length ? 'No photometry in the last 60 days' : 'No photometry on the Transient page yet' })); return; }
        const W = 760, H = 220, pl = 40, pb = 24, pr = 10, pt = 10;
        const mags = recent.map(p => p.mag), lo = Math.min(...mags) - 0.3, hi = Math.max(...mags) + 0.3;
        const X = m => pl + (m - x0) / (now - x0) * (W - pl - pr), Y = m => pt + (m - lo) / (hi - lo) * (H - pt - pb);
        const ns = 'http://www.w3.org/2000/svg', s = document.createElementNS(ns, 'svg');
        s.setAttribute('viewBox', `0 0 ${W} ${H}`); s.setAttribute('class', 'dtw-svg'); s.setAttribute('role', 'img');
        s.setAttribute('aria-label', `${t.name} light curve, last 60 days; automatic points ringed, limits as open triangles`);
        const add = (tag, a, txt) => { const n = document.createElementNS(ns, tag); for (const k in a) n.setAttribute(k, a[k]); if (txt != null) n.textContent = txt; s.append(n); return n; };
        const step = hi - lo > 3 ? 1 : 0.5;
        for (let m = Math.ceil(lo / step) * step; m <= hi; m += step) {
            add('line', { x1: pl, x2: W - pr, y1: Y(m), y2: Y(m), class: 'g' });
            add('text', { x: pl - 6, y: Y(m) + 3, 'text-anchor': 'end', class: 'l' }, m.toFixed(1));
        }
        for (const d of [-60, -45, -30, -15, 0]) add('text', { x: X(now + d), y: H - 6, 'text-anchor': 'middle', class: 'l' }, d ? d + ' d' : 'today');
        if (r) add('line', { x1: X(nightMjd(r.night)), x2: X(nightMjd(r.night)), y1: pt, y2: H - pb, class: 'n' });
        const byF = {};
        recent.forEach(p => (byF[band(p.filter)] = byF[band(p.filter)] || []).push(p));
        const legend = [];
        for (const f of Object.keys(byF).sort((a, b) => 'ugrizyocw'.indexOf(a) - 'ugrizyocw'.indexOf(b))) {
            const c = col(f), detp = byF[f].filter(p => p.err != null).sort((a, b) => a.mjd - b.mjd);
            if (detp.length > 1) add('polyline', { points: detp.map(p => `${X(p.mjd)},${Y(p.mag)}`).join(' '), fill: 'none', stroke: c, 'stroke-opacity': 0.35, 'stroke-width': 1 });
            for (const p of byF[f]) {
                const x = X(p.mjd), y = Y(p.mag), auto = /\(AUTO/.test(p.telescope);
                if (p.err == null) add('path', { d: `M${x - 4},${y - 3} L${x + 4},${y - 3} L${x},${y + 4} Z`, fill: 'none', stroke: c, 'stroke-width': 1.3 });
                else {
                    if (p.err > 0) add('line', { x1: x, x2: x, y1: Y(p.mag - p.err), y2: Y(p.mag + p.err), stroke: c, 'stroke-opacity': 0.6 });
                    if (auto) add('circle', { cx: x, cy: y, r: 6, fill: 'none', stroke: '#fff', 'stroke-width': 1.2 });
                    add('circle', { cx: x, cy: y, r: auto ? 3.4 : 2.6, fill: c });
                }
                add('title', {}, `${p.filter} ${p.err == null ? '>' : ''}${p.mag.toFixed(2)}${p.err != null ? ' ±' + p.err.toFixed(2) : ''} · ${p.telescope} · MJD ${p.mjd.toFixed(2)}`);
            }
            legend.push(el('span', {}, el('i', { class: 'dta-dot', style: `background:${c}` }), f));
        }
        legend.push(el('span', {}, el('i', { class: 'dta-dot is-ring' }), 'AUTO'), el('span', {}, el('i', { class: 'dta-tri' }), 'limit'));
        box().replaceChildren(el('div', { class: 'dtw-legend' }, legend), s);
    }

    function focusTarget(name, tel) {
        const t = (tgts()).find(x => x.name === name && x.telescope === tel) || (tgts()).find(x => x.name === name);
        if (!t) { window.location.href = objUrl(name); return; }
        if (currentTel() !== t.telescope && typeof switchTab === 'function') switchTab(t.telescope);
        selected = t.id;
        setView('ws');
        document.querySelector('.pa-obs-section').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
        const btn = document.querySelector(`.dtw-item[data-id="${t.id}"]`);
        if (btn) btn.focus({ preventScroll: true });
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

    // keyboard: up / down moves through the target list
    document.addEventListener('keydown', e => {
        if (!e.target.classList || !e.target.classList.contains('dtw-item') || !['ArrowDown', 'ArrowUp'].includes(e.key)) return;
        const items = [...document.querySelectorAll('.dtw-item')], i = items.indexOf(e.target);
        const next = items[i + (e.key === 'ArrowDown' ? 1 : -1)];
        if (next) { e.preventDefault(); next.focus(); next.click(); document.querySelector(`.dtw-item[data-id="${next.dataset.id}"]`)?.focus(); }
    });

    function init() {
        const dlg = $('dtAutoDlg');
        if (dlg) {
            dlg.addEventListener('close', () => clearTimeout(dlgTimer));
            if (!('closedBy' in HTMLDialogElement.prototype)) {          // light dismiss where closedby is missing
                const outside = e => { const b = dlg.getBoundingClientRect(); return e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom; };
                let down = false;
                dlg.addEventListener('pointerdown', e => { down = outside(e); });
                dlg.addEventListener('pointerup', e => { if (down && outside(e)) dlg.close(); });
            }
        }
        let v = 'ws';
        try { v = localStorage.getItem('dt-target-view') || 'ws'; } catch (e) { /* private mode */ }
        document.querySelectorAll('[data-dtview]').forEach(b => b.addEventListener('click', () => setView(b.dataset.dtview)));
        setView(v === 'table' ? 'table' : 'ws');
        setTimeout(() => { if (!data) load(night); }, 1500);    // normally loadTargets (above) asks first
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
