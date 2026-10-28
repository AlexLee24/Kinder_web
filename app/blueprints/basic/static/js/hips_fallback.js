// Aladin sky surveys with an ESA fallback. Aladin Lite resolves survey IDs ("CDS/P/DSS2/color") through
// the CDS MocServer and loads tiles from CDS (alasky). When CDS can't be reached the sky stays grey, so
// every Aladin view in Kinder (object page, its NED view, ePESSTO++ NED view, Telescope Simulator) asks
// KinderHips.resolve(id) first: the CDS id while CDS answers, otherwise the same survey on ESA's HiPS
// mirror (ESASky, skies.esac.esa.int), or ESA's DSS2 colour when ESA has no copy of that survey.
// Loaded inside the srcdoc iframes too (same origin), so the checks are shared via sessionStorage.
// Every view also shows a small CDS / ESA status pill (KinderHips.showStatus).
(function () {
    var ESA = 'https://cdn.skies.esac.esa.int/';
    var ESDC = 'https://esdchips.esac.esa.int/';
    // CDS survey id → the same survey on ESA's mirror (from sky.esa.int/esasky-tap/hips-sources)
    var MIRROR = {
        'CDS/P/DSS2/color': ESA + 'DSSColor/',
        'P/DSS2/color': ESA + 'DSSColor/',
        'CDS/P/SDSS9/color': ESA + 'SDSS9Color/',
        'P/SDSS9/color': ESA + 'SDSS9Color/',
        'CDS/P/2MASS/color': ESA + '2MASSColor/',
        'P/2MASS/color': ESA + '2MASSColor/',
        'CDS/P/allWISE/color': ESA + 'AllWISEColor/',
        'ESAVO/P/JWST/NIRCam_Imaging': ESA + 'JWST/NIRCam_Imaging/',
        'ESAVO/P/JWST/P/MIRI_Imaging': ESA + 'JWST/MIRI_Imaging/',
        'CDS/P/HST/color': ESA + 'HST/ACS/',
        'CDS/P/SPITZER/MIPS1': ESA + 'Spitzer/IRAC134_RGB_bright/',
        'AXA/P/SWIFT/BAT/Image': ESA + 'swift_bat_flux/',
        'xcatdb/P/XMM/PN/color': ESDC + 'XMM-Newton/EPIC-RGB/',
        'ESDC/P/XMM/EPIC-RGB': ESDC + 'XMM-Newton/EPIC-RGB/'
    };
    var DEFAULT = MIRROR['CDS/P/DSS2/color'];
    // Where each service is checked: the MocServer Aladin asks first (+ its mirror), and ESA's DSS2 survey
    var CHECKS = {
        cds: ['https://alasky.cds.unistra.fr/MocServer/query?ID=CDS%2FP%2FDSS2%2Fcolor&get=record&fmt=json',
              'https://alaskybis.cds.unistra.fr/MocServer/query?ID=CDS%2FP%2FDSS2%2Fcolor&get=record&fmt=json'],
        esa: [ESA + 'DSSColor/properties']
    };
    var TTL = 10 * 60 * 1000, TIMEOUT = 4000;
    var pending = {};

    function remembered(name) {
        try {
            var v = JSON.parse(sessionStorage.getItem('kinder-hips-' + name) || 'null');
            if (v && Date.now() - v.at < TTL) return v.ok;
        } catch (e) { /* storage blocked */ }
        return null;
    }
    function remember(name, ok) { try { sessionStorage.setItem('kinder-hips-' + name, JSON.stringify({ ok: ok, at: Date.now() })); } catch (e) { /* storage blocked */ } }

    function probe(url) {
        return new Promise(function (resolve, reject) {
            var ctl = window.AbortController ? new AbortController() : null;
            var timer = setTimeout(function () { if (ctl) ctl.abort(); reject(new Error('timeout')); }, TIMEOUT);
            fetch(url, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
                .then(function (r) { clearTimeout(timer); r.ok ? resolve(true) : reject(new Error(r.status)); })
                .catch(function (e) { clearTimeout(timer); reject(e); });
        });
    }

    // Promise<boolean>: does this service ('cds' | 'esa') answer? One check per tab, remembered 10 minutes.
    function up(name) {
        var known = remembered(name);
        if (known !== null) return Promise.resolve(known);
        if (!pending[name]) {
            pending[name] = new Promise(function (resolve) {
                var urls = CHECKS[name], left = urls.length;
                urls.forEach(function (u) {
                    probe(u).then(function () { resolve(true); }, function () { if (--left === 0) resolve(false); });
                });
            }).then(function (ok) { remember(name, ok); return ok; });
        }
        return pending[name];
    }
    function cdsUp() { return up('cds'); }

    // Promise<string>: the survey to give Aladin for this CDS id
    function resolve(id) {
        return cdsUp().then(function (ok) {
            if (ok) return id;
            var alt = MIRROR[id] || DEFAULT;
            if (window.console) console.info('[Aladin] CDS unreachable — using ESA mirror for', id, '→', alt);
            return alt;
        });
    }

    // Status pill near the bottom of the sky view (above Aladin's field-of-view readout): CDS and ESA each with a green / red dot, the one in use
    // highlighted. Shows "checking" until both answers are in.
    var DOT = { up: '#30D158', down: '#FF453A', wait: 'rgba(245,245,247,.4)' };
    function item(label, state, inUse) {
        return '<span style="display:inline-flex;align-items:center;gap:5px;' + (inUse ? 'color:#f5f5f7' : 'color:rgba(245,245,247,.55)') + '">' +
            '<i style="width:7px;height:7px;border-radius:50%;background:' + DOT[state] + ';display:inline-block"></i>' + label +
            (inUse ? ' <b style="font-weight:600;color:rgba(245,245,247,.7)">· in use</b>' : '') + '</span>';
    }
    function paint(el, cds, esa) {
        var c = cds === null ? 'wait' : cds ? 'up' : 'down', e = esa === null ? 'wait' : esa ? 'up' : 'down';
        var using = cds === null ? '' : cds ? 'cds' : 'esa';
        el.innerHTML = item('CDS', c, using === 'cds') + '<span style="opacity:.35">|</span>' + item('ESA', e, using === 'esa');
        el.title = 'Sky survey servers — CDS (alasky, Strasbourg): ' + (cds === null ? 'checking' : cds ? 'online' : 'unreachable') +
            '; ESA (ESASky mirror): ' + (esa === null ? 'checking' : esa ? 'online' : 'unreachable') +
            (using === 'esa' ? '. Tiles come from ESA while CDS is down.' : '');
    }
    function showStatus(container) {
        if (!container || container.querySelector('.kinder-hips-status')) return;
        var el = document.createElement('div');
        el.className = 'kinder-hips-status';
        el.setAttribute('role', 'status');
        el.style.cssText = 'position:absolute;left:50%;transform:translateX(-50%);bottom:36px;z-index:30;white-space:nowrap;' +
            'display:flex;align-items:center;gap:8px;padding:3px 10px;border-radius:999px;' +
            'font:500 11px/1.6 system-ui,sans-serif;background:rgba(14,14,18,.72);border:1px solid rgba(255,255,255,.18);';
        if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
        container.appendChild(el);
        var st = { cds: null, esa: null };
        paint(el, null, null);
        up('cds').then(function (ok) { st.cds = ok; paint(el, st.cds, st.esa); });
        up('esa').then(function (ok) { st.esa = ok; paint(el, st.cds, st.esa); });
    }

    window.KinderHips = { resolve: resolve, cdsUp: cdsUp, up: up, showStatus: showStatus, mirrors: MIRROR };
})();
