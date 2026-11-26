// KinderHips — the one sky-survey module every Aladin view in Kinder goes through (object page + its NED view,
// ePESSTO++ NED view, Telescope Simulator; Admin › Site shows the same checks).
//
// Three HiPS servers carry Kinder's surveys: CDS (alasky, Strasbourg), ESA (ESASky, Madrid) and NASA IRSA
// (Caltech). The admin picks the preferred one in Admin › Site (GET /api/aladin/config, app/services/aladin_source.py);
// each survey is loaded from the first server, in [preferred, then the others], that answers AND has that survey —
// checked by fetching the survey's own `properties` file, so a server whose index answers while its tiles are gone
// (seen on alasky, 2026-11) counts as down. Results are shared through sessionStorage (also by the srcdoc iframes,
// which load this file too) and remembered for a few minutes.
//
// API (window.KinderHips):
//   resolve(id)            Promise<string>  the URL to give Aladin for a survey id (old API, still used)
//   pick(id)               Promise<{id, server, url, substitute, preferred}>  server null = nobody has it (url = the id)
//   availability(id)       Promise<{cds: bool|null, esa: …, irsa: …}>  every server checked (null = not hosted there)
//   serverUp(key)          Promise<bool>
//   config()               Promise<{preferred, order}>
//   showStatus(container)  pill: CDS · ESA · IRSA with green/red dots, the one in use marked; click = this survey per server
//   markSelect(select)     suffix each <option> with the backup server's name, or 'offline' (then disabled)
//   markButtons(nodes, attr)  the same as a coloured dot inside each button (attr holds the survey id)
//   SERVERS, SURVEYS, src (this file's versioned URL — the srcdoc iframes load the same one)
(function () {
    if (window.KinderHips) return;
    var SRC = (document.currentScript && document.currentScript.src) || '/static/js/hips_fallback.js';
    var ORIGIN = (function () { try { return new URL(SRC, location.href).origin; } catch (e) { return ''; } })();

    var SERVERS = {
        cds: { label: 'CDS', name: 'CDS alasky — Strasbourg', hosts: ['https://alasky.cds.unistra.fr/', 'https://alaskybis.cds.unistra.fr/'] },
        esa: { label: 'ESA', name: 'ESASky — ESA, Madrid', hosts: ['https://cdn.skies.esac.esa.int/', 'https://skies.esac.esa.int/'] },
        irsa: { label: 'IRSA', name: 'NASA IRSA — Caltech', hosts: ['https://irsa.ipac.caltech.edu/data/hips/'] }
    };
    var KEYS = ['cds', 'esa', 'irsa'];

    // Survey id → its address on each server (relative to the server's host, or a full URL). A leading '~' marks a
    // close substitute rather than the same survey (ESA has no HST colour / Spitzer MIPS1 / XMM-PN colour copy).
    // Addresses from the CDS MocServer records (hips_service_url*) and the IRSA / ESASky HiPS lists, 2026-11.
    var SURVEYS = {
        'CDS/P/DSS2/color': { label: 'DSS2', cds: 'DSS/DSSColor', esa: 'DSSColor', irsa: 'CDS/DSS2/color' },
        'CDS/P/SDSS9/color': { label: 'SDSS9', cds: 'SDSS/DR9/color', esa: 'SDSS9Color', irsa: 'CDS/SDSS/DR9/color' },
        'CDS/P/2MASS/color': { label: '2MASS', cds: '2MASS/Color', esa: '2MASSColor', irsa: 'CDS/2MASS/Color' },
        'CDS/P/allWISE/color': { label: 'AllWISE', cds: 'AllWISE/RGB-W4-W2-W1', esa: 'AllWISEColor', irsa: 'CDS/AllWISE/RGB-W4-W2-W1' },
        'CDS/P/GALEXGR6/AIS/color': { label: 'GALEX-AIS', cds: 'GALEX/GR6-03-2014/AIS-Color', irsa: 'CDS/GALEX/GR6-03-2014/AIS-Color' },
        'CDS/P/DESI-Legacy-Surveys/DR10/color': { label: 'DESI-LS-DR10', cds: 'DESI-legacy-surveys/DR10/CDS_P_DESI-Legacy-Surveys_DR10_color' },
        'CDS/P/PanSTARRS/DR1/color-z-zg-g': { label: 'PanSTARRS-DR1', cds: 'Pan-STARRS/DR1/color-z-zg-g' },
        'CDS/P/DECaLS/DR5/color': { label: 'DECaLS-DR5', cds: 'DECaLS/DR5/color' },
        'CDS/P/Rubin/FirstLook': { label: 'Rubin-LSST', cds: 'Rubin/CDS_P_Rubin_FirstLook' },
        'CDS/P/HSC/DR2/deep/color-i-r-g': { label: 'HSC-DR2-Deep', cds: 'HSC/DR2/CDS_P_HSC_DR2_deep_color-i-r-g' },
        'CDS/P/HSC/DR2/wide/color-i-r-g': { label: 'HSC-DR2-Wide', cds: 'HSC/DR2/CDS_P_HSC_DR2_wide_color-i-r-g' },
        'CDS/P/Mellinger/color': { label: 'Mellinger', cds: 'MellingerRGB' },
        'CDS/P/NVSS': { label: 'NVSS 1.4 GHz', cds: 'NVSS/intensity' },
        'CDS/P/HST/color': { label: 'HST', cds: 'HST-hips/color', esa: '~HST/ACS' },
        'CDS/P/Euclid/ERO/color': { label: 'Euclid-ERO', cds: 'Euclid/ERO/CDS_P_Euclid_ERO_color' },
        'ESAVO/P/JWST/NIRCam_Imaging': { label: 'JWST-NIRCam', cds: 'ESAC/ESAVO_P_JWST_NIRCam_Imaging', esa: 'JWST/NIRCam_Imaging' },
        'ESAVO/P/JWST/P/MIRI_Imaging': { label: 'JWST-MIRI', esa: 'JWST/MIRI_Imaging' },
        'CDS/P/SPITZER/MIPS1': { label: 'Spitzer', cds: 'Spitzer/MIPS1', esa: '~Spitzer/IRAC134_RGB_bright' },
        'AXA/P/SWIFT/BAT/Image': { label: 'Swift-BAT', esa: 'swift_bat_flux' },
        'xcatdb/P/XMM/PN/color': { label: 'XMM-PN', cds: 'SSC/xcatdb_P_XMM_PN_color', esa: '~https://esdchips.esac.esa.int/XMM-Newton/EPIC-RGB' },
        'simg.de/P/NSNS/DR0_2/hbr8': { label: 'NSNS-hbr', cds: 'simg.de/simg.de_P_NSNS_DR0_2_hbr8' },
        'simg.de/P/NSNS/DR0_2/rgb8': { label: 'NSNS-rgb', cds: 'simg.de/simg.de_P_NSNS_DR0_2_rgb8' },
        'simg.de/P/NSNS/DR0_2/ohs8': { label: 'NSNS-ohs', cds: 'simg.de/simg.de_P_NSNS_DR0_2_ohs8' }
    };

    var TTL = 5 * 60 * 1000, CONFIG_TTL = 60 * 1000, TIMEOUT = 4000, NS = 'kinder-hips3-';
    var pending = {};

    function canon(id) {
        if (SURVEYS[id]) return id;
        if (SURVEYS['CDS/' + id]) return 'CDS/' + id;
        return id;
    }
    function stored(key, ttl) {
        try {
            var v = JSON.parse(sessionStorage.getItem(NS + key) || 'null');
            if (v && Date.now() - v.at < ttl) return v;
        } catch (e) { /* storage blocked */ }
        return null;
    }
    function store(key, v) { v.at = Date.now(); try { sessionStorage.setItem(NS + key, JSON.stringify(v)); } catch (e) { /* storage blocked */ } return v; }
    // One check in flight per key in this window; later callers share it (finished ones are read from storage)
    function once(key, make) {
        if (!pending[key]) {
            pending[key] = make().then(function (v) { delete pending[key]; return v; },
                                       function () { delete pending[key]; return null; });
        }
        return pending[key];
    }

    function probe(url) {
        return new Promise(function (resolve) {
            var ctl = window.AbortController ? new AbortController() : null;
            var timer = setTimeout(function () { if (ctl) ctl.abort(); resolve(false); }, TIMEOUT);
            fetch(url, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
                .then(function (r) { clearTimeout(timer); resolve(r.ok); })
                .catch(function () { clearTimeout(timer); resolve(false); });
        });
    }
    function firstOk(urls) {   // index of the first URL (in list order) that answers, or -1
        return Promise.all(urls.map(probe)).then(function (oks) { return oks.indexOf(true); });
    }

    // ── Admin preference ──
    function config() {
        var hit = stored('config', CONFIG_TTL);
        if (hit) return Promise.resolve(hit);
        return once('config', function () {
            return fetch(ORIGIN + '/api/aladin/config', { cache: 'no-store', credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; })
                .then(function (c) {
                    var pref = c && SERVERS[c.preferred] ? c.preferred : 'cds';
                    return store('config', { preferred: pref, order: [pref].concat(KEYS.filter(function (k) { return k !== pref; })) });
                });
        });
    }
    function forgetConfig() { try { sessionStorage.removeItem(NS + 'config'); } catch (e) { /* */ } delete pending.config; }
    function forgetChecks() {
        try {
            for (var i = sessionStorage.length - 1; i >= 0; i--) {
                var k = sessionStorage.key(i);
                if (k && k.indexOf(NS) === 0) sessionStorage.removeItem(k);
            }
        } catch (e) { /* */ }
        pending = {};
    }

    // ── Servers: up = DSS2's properties file answers on one of the server's hosts (all three carry DSS2) ──
    function serverState(key) {
        var hit = stored('srv-' + key, TTL);
        if (hit) return Promise.resolve(hit);
        return once('srv-' + key, function () {
            var s = SERVERS[key], path = SURVEYS['CDS/P/DSS2/color'][key];
            return firstOk(s.hosts.map(function (h) { return h + path + '/properties'; })).then(function (i) {
                return store('srv-' + key, { ok: i >= 0, host: s.hosts[Math.max(i, 0)] });
            });
        });
    }
    function serverUp(key) { return serverState(key).then(function (s) { return !!(s && s.ok); }); }

    function address(id, key) {
        var e = SURVEYS[canon(id)], p = e && e[key];
        if (!p) return null;
        var sub = p.charAt(0) === '~';
        if (sub) p = p.slice(1);
        return { path: p, absolute: /^https?:\/\//.test(p), substitute: sub };
    }
    // Promise<string|null>: the survey's URL on that server if it answers there, else null
    function urlOn(id, key) {
        var a = address(id, key);
        if (!a) return Promise.resolve(null);
        var ck = 'sv-' + key + '|' + canon(id);
        var hit = stored(ck, TTL);
        if (hit) return Promise.resolve(hit.url);
        return once(ck, function () {
            return serverState(key).then(function (st) {
                if (!st || !st.ok) return null;   // server down: don't wait on every survey
                var url = (a.absolute ? a.path : st.host + a.path).replace(/\/+$/, '');
                return probe(url + '/properties').then(function (ok) { return ok ? url : null; });
            }).then(function (url) { return store(ck, { url: url }).url; });
        });
    }
    // Promise<{cds,esa,irsa}>: true / false per server, null where the server doesn't carry the survey
    function availability(id) {
        return Promise.all(KEYS.map(function (k) {
            return address(id, k) ? urlOn(id, k).then(function (u) { return !!u; }) : Promise.resolve(null);
        })).then(function (r) { var o = {}; KEYS.forEach(function (k, i) { o[k] = r[i]; }); return o; });
    }

    // ── Choosing the server for a survey ──
    var current = null;   // the last survey picked in this window: {id, server, url, substitute, preferred}
    function pick(id) {
        var cid = canon(id);
        if (!SURVEYS[cid]) return config().then(function (cfg) { return { id: id, server: null, url: id, unknown: true, preferred: cfg.preferred }; });
        KEYS.forEach(serverState);   // check all three servers at once
        return config().then(function (cfg) {
            var order = cfg.order.filter(function (k) { return address(cid, k); });
            function next(i) {
                if (i >= order.length) return { id: cid, server: null, url: id, preferred: cfg.preferred };
                return urlOn(cid, order[i]).then(function (u) {
                    return u ? { id: cid, server: order[i], url: u, substitute: address(cid, order[i]).substitute, preferred: cfg.preferred } : next(i + 1);
                });
            }
            return next(0);
        });
    }
    function resolve(id) {
        return pick(id).then(function (p) {
            current = p;
            if (window.console && p.server && p.server !== p.preferred) console.info('[Aladin]', p.id, '→ backup', SERVERS[p.server].label, p.url);
            try { window.dispatchEvent(new CustomEvent('kinderhips:pick', { detail: p })); } catch (e) { /* old browser */ }
            return p.url;
        });
    }

    // ── Status pill (inside the sky view) ──
    var DOT = { up: '#30D158', backup: '#FFD60A', down: '#FF453A', wait: 'rgba(245,245,247,.4)', none: 'rgba(245,245,247,.18)' };
    function dot(state, size) { return '<i style="width:' + (size || 7) + 'px;height:' + (size || 7) + 'px;border-radius:50%;background:' + DOT[state] + ';display:inline-block;flex:none"></i>'; }
    function st(v) { return v === undefined || v === null ? 'wait' : v ? 'up' : 'down'; }

    function showStatus(container) {
        if (!container || container.querySelector('.kinder-hips-status')) return;
        if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
        var wrap = document.createElement('div');
        wrap.className = 'kinder-hips-status';
        wrap.setAttribute('role', 'status');
        wrap.style.cssText = 'position:absolute;left:50%;transform:translateX(-50%);bottom:36px;z-index:30;display:flex;flex-direction:column;align-items:center;gap:6px;font:500 11px/1.6 system-ui,sans-serif;color:#f5f5f7';
        var GLASS = 'background:rgba(14,14,18,.8);border:1px solid rgba(255,255,255,.18);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);';
        var panel = document.createElement('div');
        panel.hidden = true;
        panel.style.cssText = GLASS + 'border-radius:10px;padding:8px 10px;min-width:200px;white-space:nowrap';
        var pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('aria-expanded', 'false');
        pill.style.cssText = GLASS + 'display:flex;align-items:center;gap:8px;padding:3px 10px;border-radius:999px;color:inherit;font:inherit;cursor:pointer;white-space:nowrap';
        wrap.appendChild(panel);
        wrap.appendChild(pill);
        container.appendChild(wrap);

        var up = {}, cfg = null, avail = null, availFor = null;
        function paint() {
            var using = current && current.server;
            pill.innerHTML = KEYS.map(function (k) {
                var on = using === k;
                return '<span style="display:inline-flex;align-items:center;gap:5px;color:' + (on ? '#f5f5f7' : 'rgba(245,245,247,.55)') + '">' + dot(st(up[k])) + SERVERS[k].label +
                    (on ? ' <b style="font-weight:600;color:rgba(245,245,247,.75)">· in use</b>' : '') + '</span>';
            }).join('<span style="opacity:.35">|</span>');
            pill.title = 'Sky survey servers — ' + KEYS.map(function (k) { return SERVERS[k].name + ': ' + (up[k] === undefined ? 'checking' : up[k] ? 'online' : 'unreachable'); }).join('; ') +
                (cfg ? '. Preferred (Admin › Site): ' + SERVERS[cfg.preferred].label : '') + '. Click for this survey on each server.';
            if (!panel.hidden) paintPanel();
        }
        function paintPanel() {
            var id = current && current.id, e = id && SURVEYS[id];
            var h = '<div style="font-weight:600;margin-bottom:4px">' + (e ? e.label : 'This survey') + ' <span style="font-weight:400;color:rgba(245,245,247,.55)">on each server</span></div>';
            KEYS.forEach(function (k) {
                var a = id ? address(id, k) : null, v = avail && availFor === id ? avail[k] : undefined;
                var state = !a ? 'none' : st(v);
                var note = !a ? 'not hosted there' : v === undefined ? 'checking…' : v ? (a.substitute ? 'similar survey' : 'available') : 'not answering';
                var tags = (cfg && cfg.preferred === k ? ' <span style="color:#F39F5A">preferred</span>' : '') + (current && current.server === k ? ' <b>· in use</b>' : '');
                h += '<div style="display:flex;align-items:center;gap:7px">' + dot(state, 8) + '<span style="min-width:34px">' + SERVERS[k].label + '</span><span style="color:rgba(245,245,247,.6)">' + note + '</span>' + tags + '</div>';
            });
            if (current && !current.server && !current.unknown) h += '<div style="color:#FF453A;margin-top:4px">No server has this survey right now.</div>';
            panel.innerHTML = h;
        }
        function refreshAvail() {
            var id = current && current.id;
            if (!id || !SURVEYS[id]) return;
            availFor = id; avail = null;
            availability(id).then(function (a) { if (availFor === id) { avail = a; paint(); } });
        }
        pill.addEventListener('click', function (ev) {
            ev.stopPropagation();
            panel.hidden = !panel.hidden;
            pill.setAttribute('aria-expanded', String(!panel.hidden));
            if (!panel.hidden) { refreshAvail(); paintPanel(); }
        });
        window.addEventListener('kinderhips:pick', function () { if (!panel.hidden) refreshAvail(); paint(); });
        paint();
        config().then(function (c) { cfg = c; paint(); });
        KEYS.forEach(function (k) { serverUp(k).then(function (ok) { up[k] = ok; paint(); }); });
    }

    // ── Survey choosers outside the sky view ──
    function verdict(p) {   // 'up' = from the preferred server, 'backup' = from another one, 'down' = nowhere
        if (p.unknown) return null;
        if (!p.server) return 'down';
        return p.server === p.preferred ? 'up' : 'backup';
    }
    function describe(p) {
        if (!p.server) return 'Not available on CDS, ESA or IRSA right now';
        return 'From ' + SERVERS[p.server].name + (p.server !== p.preferred ? ' (backup: ' + SERVERS[p.preferred].label + ' does not have it or is not answering)' : '') +
            (p.substitute ? '; a similar survey, not the same one' : '');
    }
    // <option> text cannot carry an icon: the suffix names a backup server or says offline
    var MARK = { up: '', backup: '', down: '' };
    function markSelect(sel) {
        if (!sel) return;
        Array.prototype.forEach.call(sel.options, function (o) {
            if (!o.dataset.khLabel) o.dataset.khLabel = o.textContent.trim();
            o.textContent = o.dataset.khLabel + ' …';
            pick(o.value).then(function (p) {
                var v = verdict(p);
                if (!v) { o.textContent = o.dataset.khLabel; return; }
                o.textContent = MARK[v] + o.dataset.khLabel + (v === 'backup' ? ' · ' + SERVERS[p.server].label : v === 'down' ? ' · offline' : '');
                o.title = describe(p);
                o.disabled = v === 'down' && !o.selected;
            });
        });
    }
    function markButtons(nodes, attr) {
        Array.prototype.forEach.call(nodes || [], function (b) {
            var id = b.getAttribute(attr || 'data-survey');
            if (!id) return;
            var d = b.querySelector('.kh-dot');
            if (!d) {
                d = document.createElement('i');
                d.className = 'kh-dot';
                d.setAttribute('aria-hidden', 'true');
                d.style.cssText = 'display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:1px;background:' + DOT.wait;
                b.insertBefore(d, b.firstChild);
            }
            pick(id).then(function (p) {
                var v = verdict(p);
                if (!v) { d.remove(); return; }
                d.style.background = DOT[v];
                b.title = describe(p);
                b.classList.toggle('kh-offline', v === 'down');
            });
        });
    }

    window.KinderHips = {
        src: SRC, SERVERS: SERVERS, SURVEYS: SURVEYS, KEYS: KEYS,
        resolve: resolve, pick: pick, availability: availability, serverUp: serverUp, config: config,
        forgetConfig: forgetConfig, forgetChecks: forgetChecks, urlOn: urlOn, address: address, canon: canon,
        showStatus: showStatus, markSelect: markSelect, markButtons: markButtons,
        current: function () { return current; },
        cdsUp: function () { return serverUp('cds'); }, up: serverUp   // old names
    };
})();
