/* Admin System page: polls /api/admin/system/status every 10 s; KPI trend lines live only in this tab. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const EVERY = 10000;
    const H = {};                                   // KPI history since the page opened (max 90 points = 15 min)

    function el(tag, attrs, ...kids) {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (v == null || v === false) continue;
            if (k === 'text') n.textContent = v;
            else if (k === 'class') n.className = v;
            else if (k === 'style') n.setAttribute('style', v);
            else n.setAttribute(k, v === true ? '' : v);
        }
        for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid);
        return n;
    }
    const put = (node, ...kids) => node.replaceChildren(...kids.flat(Infinity).filter(k => k != null && k !== false));
    const bytes = n => n == null ? '—' : n >= 1099511627776 ? (n / 1099511627776).toFixed(2) + ' TB' : n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB'
        : n >= 1048576 ? (n / 1048576).toFixed(0) + ' MB' : Math.max(0, Math.round(n / 1024)) + ' kB';
    const dur = s => {
        if (s == null) return '—';
        s = Math.round(s);
        const d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60;
        return d ? d + ' d ' + h + ' h' : h ? h + ' h ' + m + ' min' : m + ' min';
    };
    const ago = t => t ? dur(Date.now() / 1000 - t) + ' ago' : '—';
    const when = t => t ? new Date(t * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
    const lvl = (v, warn, bad) => v >= bad ? 'is-bad' : v >= warn ? 'is-warn' : 'is-ok';
    const svgNS = 'http://www.w3.org/2000/svg';

    function spark(key, v) {
        const a = H[key] = H[key] || [];
        a.push(v);
        if (a.length > 90) a.shift();
        if (a.length < 2) return null;
        const W = 120, Hh = 28, max = Math.max(...a), min = Math.min(...a), rng = (max - min) || 1;
        const pts = a.map((x, i) => (i / (a.length - 1) * W).toFixed(1) + ',' + (Hh - 2 - (x - min) / rng * (Hh - 4)).toFixed(1)).join(' ');
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', '0 0 ' + W + ' ' + Hh);
        svg.setAttribute('preserveAspectRatio', 'none');
        svg.setAttribute('aria-hidden', 'true');
        for (const [cls, p] of [['f', '0,' + Hh + ' ' + pts + ' ' + W + ',' + Hh], ['l', pts]]) {
            const pl = document.createElementNS(svgNS, 'polyline');
            pl.setAttribute('points', p);
            pl.setAttribute('class', cls);
            svg.append(pl);
        }
        return svg;
    }
    function kpi(key, label, value, unit, cls, v, sub) {
        return el('div', { class: 'kw-kpi sys-kpi ' + (cls || '') }, el('span', { class: 'kw-kpi-label', text: label }),
            el('b', {}, value, unit ? el('i', { text: unit }) : null), sub ? el('small', { text: sub }) : null, spark(key, v));
    }
    function gauge(label, pct, sub) {
        pct = Math.max(0, Math.min(100, pct || 0));
        return el('div', { class: 'sys-gauge ' + lvl(pct, 75, 90) },
            el('div', { class: 'sys-gauge-top' }, el('span', { text: label }), el('b', { text: pct.toFixed(0) + '%' })),
            el('div', { class: 'sys-bar' }, el('i', { style: 'width:' + pct + '%' })), sub ? el('small', { text: sub }) : null);
    }
    const facts = rows => rows.filter(Boolean).map(([k, v]) => [el('dt', { text: k }), el('dd', {}, v == null ? '—' : v)]);

    let lastIo = null;
    function render(d) {
        const h = d.host || {}, p = d.process || {}, pipe = d.pipeline || {}, pool = d.db_pool || {};
        const loadCore = h.loadavg && h.cpus ? h.loadavg[0] / h.cpus * 100 : null;
        const fullest = (d.disks || []).slice().sort((a, b) => b.used_pct - a.used_pct)[0];
        let ioRate = null;
        if (h.disk_io && lastIo) {
            const dt = Math.max(1, d.time - lastIo.time);
            ioRate = { r: (h.disk_io.read - lastIo.read) / dt, w: (h.disk_io.write - lastIo.write) / dt };
        }
        if (h.disk_io) lastIo = { time: d.time, read: h.disk_io.read, write: h.disk_io.write };

        put($('sysKpis'), 
            kpi('cpu', 'CPU', (h.cpu_pct || 0).toFixed(0), '%', lvl(h.cpu_pct || 0, 70, 90), h.cpu_pct || 0, h.cpus ? h.cpus + ' cores' : ''),
            loadCore != null ? kpi('load', 'Load / core', loadCore.toFixed(0), '%', lvl(loadCore, 80, 120), loadCore, h.loadavg.map(x => x.toFixed(2)).join(' · ')) : null,
            h.mem_used_pct != null ? kpi('mem', 'Memory', h.mem_used_pct.toFixed(0), '%', lvl(h.mem_used_pct, 80, 92), h.mem_used_pct, bytes(h.mem_avail) + ' free of ' + bytes(h.mem_total)) : null,
            h.swap_total ? kpi('swap', 'Swap', (h.swap_pct || 0).toFixed(0), '%', lvl(h.swap_pct || 0, 50, 85), h.swap_pct || 0, bytes(h.swap_used) + ' of ' + bytes(h.swap_total)) : null,
            p.rss_total != null ? kpi('kinder', 'Kinder memory', (p.rss_total / 1048576).toFixed(0), ' MB', lvl(p.rss_total / 1048576, 1500, 3000), p.rss_total / 1048576,
                (p.workers || 1) + (p.server ? ' gunicorn worker' + (p.workers === 1 ? '' : 's') : ' process')) : null,
            fullest ? kpi('disk', 'Fullest disk', fullest.used_pct.toFixed(0), '%', lvl(fullest.used_pct, 80, 92), fullest.used_pct, bytes(fullest.free) + ' free · ' + fullest.mount) : null,
            ioRate ? kpi('io', 'Disk I/O', bytes(ioRate.r + ioRate.w), '/s', '', ioRate.r + ioRate.w, 'read ' + bytes(ioRate.r) + '/s · write ' + bytes(ioRate.w) + '/s') : null,
            kpi('runs', 'AutoPhOT runs', String(pipe.running || 0), pipe.max_running ? ' / ' + pipe.max_running : '', (pipe.running || 0) >= (pipe.max_running || 99) ? 'is-warn' : '', pipe.running || 0,
                (pipe.workspaces || 0) + ' workspaces'),
            pool.pool_max ? kpi('pool', 'DB pool', String(pool.in_use), ' / ' + pool.pool_max, lvl(pool.usage_pct || 0, 70, 90), pool.in_use, pool.idle + ' idle') : null);

        $('sysHostMeta').textContent = (h.platform || '') + (h.uptime ? ' · up ' + dur(h.uptime) : '');
        put($('sysGauges'), 
            h.cpu_pct != null ? gauge('CPU', h.cpu_pct, (h.cpus || '?') + ' cores') : null,
            loadCore != null ? gauge('Load per core (1 min)', loadCore, h.loadavg.map(x => x.toFixed(2)).join(' · ') + ' (1 · 5 · 15 min)') : null,
            h.mem_used_pct != null ? gauge('Memory', h.mem_used_pct, bytes(h.mem_avail) + ' free of ' + bytes(h.mem_total)) : null,
            h.swap_total ? gauge('Swap', h.swap_pct, bytes(h.swap_used) + ' of ' + bytes(h.swap_total)) : null,
            pool.pool_max ? gauge('Kinder DB connection pool', pool.usage_pct, pool.in_use + ' in use · ' + pool.idle + ' idle · max ' + pool.pool_max) : null);
        put($('sysCores'), ...(h.cpu_per_core || []).map((c, i) => el('span', { class: 'sys-core ' + lvl(c, 70, 90), title: 'Core ' + (i + 1) + ': ' + c.toFixed(0) + '%' },
            el('i', { style: 'height:' + Math.max(4, c) + '%' }))));

        put($('sysDisks'), ...(d.disks || []).map(v => el('div', { class: 'sys-disk' },
            gauge(v.mount, v.used_pct, bytes(v.free) + ' free of ' + bytes(v.total)),
            el('div', { class: 'sys-holds' }, v.holds.map(x => el('span', { class: 'kw-chip' + (x.exists ? '' : ' kw-chip-red'), title: x.path + (x.exists ? '' : ' (not on this machine)'), text: x.label }))))));

        const s = p.self || {};
        put($('sysProc'), ...facts([
            ['Server', p.server ? 'gunicorn, ' + p.workers + ' worker' + (p.workers === 1 ? '' : 's') : 'single process (development)'],
            ['Memory, all processes', bytes(p.rss_total)],
            ['CPU, all processes', p.cpu_total != null ? p.cpu_total.toFixed(0) + '%' : null],
            ['This worker', s.pid ? 'pid ' + s.pid + ' · ' + bytes(s.rss) + ' · ' + s.threads + ' threads' + (s.fds != null ? ' · ' + s.fds + ' open files' : '') : null],
            ['Running since', s.started ? when(s.started) + ' (' + dur(Date.now() / 1000 - s.started) + ')' : null],
            (p.autophot || []).length ? ['AutoPhOT processes', p.autophot.map(a => a.name + ' ' + bytes(a.rss) + ' · ' + a.cpu_pct.toFixed(0) + '%').join(', ')] : null,
            ['This page took', d.took_ms + ' ms'],
        ]));
        put($('sysPipe'), ...facts([
            ['Workspaces', String(pipe.workspaces || 0)],
            ['AutoPhOT running', (pipe.running || 0) + (pipe.max_running ? ' of at most ' + pipe.max_running : '')],
            ['FITS kept', pipe.keep_days ? pipe.keep_days + ' days, then deleted (results stay)' : null],
            ['Last FITS cleanup', pipe.last_cleanup ? ago(pipe.last_cleanup) : 'not yet'],
        ]));
        renderSizes(d.sizes || {});

        const top = d.top || {};
        $('sysTopMeta').textContent = top.n ? top.n + ' processes' : '';
        const procTable = (rows, cpuFirst) => [el('thead', {}, el('tr', {}, ['Process', 'User', cpuFirst ? 'CPU' : 'Memory', cpuFirst ? 'Memory' : 'CPU'].map(t => el('th', { text: t })))),
            el('tbody', {}, (rows || []).map(r => el('tr', {}, el('td', { text: r.name + ' (' + r.pid + ')' }), el('td', { class: 'sys-muted', text: r.user }),
                el('td', {}, el('b', { text: cpuFirst ? r.cpu_pct.toFixed(0) + '%' : bytes(r.rss) })), el('td', { class: 'sys-muted', text: cpuFirst ? bytes(r.rss) : r.cpu_pct.toFixed(0) + '%' }))))];
        put($('sysTopMem'), ...procTable(top.by_mem, false));
        put($('sysTopCpu'), ...procTable(top.by_cpu, true));

        const worst = [h.cpu_pct, h.mem_used_pct, fullest && fullest.used_pct].filter(x => x != null);
        const state = $('sysState');
        const bad = worst.some(x => x >= 92), warn = worst.some(x => x >= 80);
        state.className = 'sys-pill ' + (bad ? 'is-bad' : warn ? 'is-warn' : 'is-ok');
        state.querySelector('b').textContent = (bad ? 'Under pressure' : warn ? 'Busy' : 'Healthy') + ' · ' + new Date(d.time * 1000).toLocaleTimeString();
    }

    function renderSizes(sz) {
        const data = sz.data;
        $('sysSizeMeta').textContent = sz.scanning ? 'Counting…' : data ? 'Counted ' + ago(data.finished) + ' in ' + data.took_s + ' s' : '';
        $('sysRecount').disabled = !!sz.scanning;
        if (!data) return;
        put($('sysSizes'), ...data.groups.map(g => {
            const max = Math.max(1, ...g.items.map(i => i.bytes));
            const ws = g.key === 'workspaces';
            return el('details', { class: 'sys-group', open: ['reduction', 'kinder', 'workspaces'].includes(g.key) },
                el('summary', {}, el('b', { text: g.label }), el('span', { class: 'sys-muted sys-path', text: g.path }), el('span', { class: 'sys-total', text: g.missing ? 'not on this machine' : bytes(g.bytes) })),
                g.items.length ? el('div', { class: 'kw-table-wrap' }, el('table', { class: 'kw-table sys-size-table' },
                    el('thead', {}, el('tr', {}, el('th', { text: 'Name' }), el('th', { text: 'Size' }), el('th', { class: 'sys-barcol' }),
                        el('th', { text: ws ? 'FITS (deleted after 7 d)' : 'Files' }), el('th', { text: ws ? '' : 'Newest' }))),
                    el('tbody', {}, g.items.map(i => el('tr', {},
                        el('td', { class: 'sys-mono', text: i.name + (i.dir ? '/' : '') }), el('td', {}, el('b', { text: bytes(i.bytes) })),
                        el('td', { class: 'sys-barcol' }, el('span', { class: 'sys-bar sys-bar-sm' }, el('i', { style: 'width:' + (i.bytes / max * 100).toFixed(1) + '%' }))),
                        el('td', { class: 'sys-muted', text: ws ? bytes(i.fits) : (i.files || 0).toLocaleString() + (i.partial ? '+' : '') }),
                        el('td', { class: 'sys-muted', text: ws ? '' : when(i.newest) })))))) : el('p', { class: 'sys-muted', text: g.missing ? 'This folder is not on this machine.' : 'Empty.' }));
        }));
    }

    let timer = null;
    async function load() {
        try {
            const r = await fetch('/api/admin/system/status', { credentials: 'same-origin' });
            const d = await r.json();
            if (!r.ok || !d.success) throw new Error(d.error || 'HTTP ' + r.status);
            render(d);
        } catch (err) {
            const state = $('sysState');
            state.className = 'sys-pill is-bad';
            state.querySelector('b').textContent = 'Cannot read status: ' + err.message;
        }
    }
    function start() { clearInterval(timer); load(); timer = setInterval(() => { if (!document.hidden) load(); }, EVERY); }
    $('sysRefresh').addEventListener('click', load);
    $('sysRecount').addEventListener('click', async ev => {
        ev.currentTarget.disabled = true;
        $('sysSizeMeta').textContent = 'Counting…';
        try { await fetch('/api/admin/system/sizes', { method: 'POST', credentials: 'same-origin' }); } catch (e) { /* the next poll shows it */ }
        setTimeout(load, 1500);
    });
    start();
})();
