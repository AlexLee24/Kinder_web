/* Lab › Special Run › Lens Simulator (special_run_lens_sim.html): strong lensing ray-traced in the browser.
   For every image-plane pixel θ the source is sampled at β = θ − α(θ). Lens: point mass, or SIE (Kormann et al.
   1994 normalisation, tiny core) with external shear. Source: Sérsic, clumpy (Sérsic + knots), a point (quasar / SN)
   or a host galaxy with a supernova in it (Host + SN). Foreground: an isolated elliptical, a group or a cluster
   (BCG + intracluster light + member galaxies that also deflect), chosen from σ or by hand; a lensed background
   field at z_source, foreground stars, seeing and sky noise.
   Distances: flat ΛCDM (H0 = 70, Ωm = 0.3). Angles are in arcsec throughout. */
(() => {
    const page = document.getElementById('lsPage');
    if (!page) return;
    const $ = (id) => document.getElementById(id);

    /* ------------------------------------------------------------ physics */
    const C = 299792.458, H0 = 70, OM = 0.3, DH = C / H0;      // km/s, km/s/Mpc, Mpc
    const ARC = 206264.806;                                     // arcsec per radian
    const G_C2 = 4.7853e-20;                                    // G M☉ / c² in Mpc
    const G_KPC = 4.3009e-6;                                    // G in kpc (km/s)² / M☉
    const R0 = 100;                                             // kpc: SIE mass is the projected mass inside R0

    function chi(z) {   // comoving distance (Mpc), Simpson
        const n = 200, h = z / n;
        const f = (x) => 1 / Math.sqrt(OM * (1 + x) ** 3 + 1 - OM);
        let s = f(0) + f(z);
        for (let i = 1; i < n; i++) s += (i % 2 ? 4 : 2) * f(i * h);
        return DH * s * h / 3;
    }
    function dists(zl, zs) {
        const cl = chi(zl), cs = chi(zs);
        return {Dl: cl / (1 + zl), Ds: cs / (1 + zs), Dls: (cs - cl) / (1 + zs)};
    }
    const sigmaOf = (M) => Math.sqrt(G_KPC * M / (Math.PI * R0));                  // km/s
    const logMOfSigma = (s) => Math.log10(Math.PI * s * s * R0 / G_KPC);
    function thetaE(model, M, d) {                                                   // arcsec
        if (d.Dls <= 0) return 0;
        if (model === 'pm') return Math.sqrt(4 * G_C2 * M * d.Dls / (d.Dl * d.Ds)) * ARC;
        const s = sigmaOf(M) / C;
        return 4 * Math.PI * s * s * d.Dls / d.Ds * ARC;
    }

    /* ------------------------------------------------------------ state */
    const DEF = {model: 'sie', logm: logMOfSigma(260), zl: 0.2, q: 0.8, pa: 30, gamma: 0.03, gpa: 60, light: 0.8,
                 src: 'galaxy', zs: 0.6, re: 1.5, n: 1, sq: 0.7, spa: 20, bx: 0.15, by: 0.1,
                 env: 'auto', g2: 0, g2x: 1.5, g2y: 1.5, mag: 23, snMag: 23, obs: null, showObs: true,
                 tel: 'ideal', band: 'r', D: 1, pixT: 0.35, exp: 3, white: 19, knee: 26, fov: 'auto', seeing: 0, field: true, crit: true, caus: true};
    // Telescopes: aperture D (m), pixel scale (″, per band), median seeing (″), ground or space sky.
    // Zero point (AB mag giving 1 e⁻/s) ≈ 24.3 + 5 log D — a broad-band, ~50 % throughput approximation.
    const BANDS = {g: 0.48, r: 0.62, i: 0.77, z: 0.91, J: 1.25, H: 1.6, K: 2.2};                     // µm
    const SKY = {ground: {g: 22.0, r: 21.0, i: 20.2, z: 19.3, J: 16.5, H: 14.5, K: 13.5},             // mag/arcsec² (dark site)
                 space: {g: 22.8, r: 22.5, i: 22.4, z: 22.3, J: 22.1, H: 21.9, K: 21.5}};             // zodiacal light
    const TELESCOPES = {
        ideal: {label: 'Ideal (no PSF, no noise)'},
        lot: {label: 'Lulin LOT 1 m', D: 1.0, pix: () => 0.35, seeing: 1.3, sky: 'ground'},
        subaru: {label: 'Subaru HSC 8.2 m', D: 8.2, pix: () => 0.168, seeing: 0.7, sky: 'ground'},
        euclid: {label: 'Euclid 1.2 m (VIS / NISP)', D: 1.2, pix: (b) => (BANDS[b] > 1 ? 0.3 : 0.1), seeing: 0, sky: 'space'},
        hst: {label: 'HST 2.4 m (WFC3 UVIS / IR)', D: 2.4, pix: (b) => (BANDS[b] > 1 ? 0.13 : 0.04), seeing: 0, sky: 'space'},
        jwst: {label: 'JWST 6.5 m (NIRCam)', D: 6.5, pix: (b) => (BANDS[b] > 2.4 ? 0.063 : 0.031), seeing: 0, sky: 'space'},
        custom: {label: 'Custom', sky: 'ground'},
    };
    const PRESETS = [
        ['Galaxy–galaxy lens (SLACS-like)', {mag: 21.5}],
        ['Cosmic Horseshoe (SDSS J1148+1930)', {mag: 23.5, logm: logMOfSigma(500), zl: 0.444, zs: 2.379, q: 0.85, pa: 100, gamma: 0.02,
            src: 'clumpy', re: 1.6, sq: 0.8, bx: 0.04, by: 0.06, light: 0.6}],
        ['8 o\'clock arc (SDSS J0022+1431)', {mag: 23.5, logm: logMOfSigma(380), zl: 0.38, zs: 2.73, q: 0.75, pa: 40, gamma: 0.05,
            src: 'clumpy', re: 1.2, sq: 0.6, bx: 0.25, by: 0.12, light: 0.8}],
        ['Abell 370 giant arc (cluster)', {mag: 22.5, logm: logMOfSigma(1500), zl: 0.375, zs: 0.725, q: 0.65, pa: 100, gamma: 0.06, gpa: 10,
            src: 'clumpy', re: 8, sq: 0.5, spa: 10, bx: 0, by: 0.25, light: 1, n: 1}],
        ['MACS J0717 (most massive cluster lens)', {mag: 23.5, logm: logMOfSigma(1750), zl: 0.546, zs: 2.5, q: 0.6, pa: 135, gamma: 0.08,
            src: 'clumpy', re: 6, sq: 0.6, spa: 45, bx: 0, by: 0.22, light: 1}],
        ['Einstein Cross (Q2237+0305)', {mag: 20.5, logm: logMOfSigma(215), zl: 0.0394, zs: 1.695, q: 0.75, pa: 70, gamma: 0.01,
            src: 'point', bx: 0.03, by: 0.02, light: 1}],
        ['Twin Quasar (Q0957+561)', {mag: 17.8, logm: logMOfSigma(450), zl: 0.36, zs: 1.41, q: 0.8, pa: 60, gamma: 0.2, gpa: 70,
            src: 'point', bx: 0.35, by: 0.15, light: 0.8}],
        // Fitted in the image plane to the five SN image positions of arXiv:2608.28413 (G1 SIE + G2 SIS + shear, no
        // unobserved bright images allowed), then moved 0.014″ in the source plane off a small G2 caustic so the
        // configuration is stable: A–E reproduced within 0.04–0.13″, exactly five images (checked on a 700² grid);
        // θ_E,1 = 1.63″, θ_E,2 = 0.64″ (paper: ≈ 1.6″ and 0.7–0.8″); μ_A ≈ 10.5 → the unlensed SN ≈ 22.3 mag.
        // Flux ratios are only roughly matched (the observed ones include microlensing). x = −ΔRA cosδ, y = ΔDec, from G1.
        ['SN 2025wny (lensed SLSN, z = 2.01)', {logm: 12.75846, zl: 0.3755, zs: 2.0151, q: 0.737, pa: 157.6355, gamma: 0.1342,
            gpa: 18.131, g2: 175.85, g2x: 0.967, g2y: 2.126, src: 'hostsn', re: 1.0, n: 1, sq: 0.8, spa: 0, bx: 0.1952, by: 0.34516,
            light: 1, mag: 25.5, snMag: 22.3, env: 'galaxy',
            obs: [[-1.213, 1.318, 'A'], [-1.813, -0.806, 'B'], [0.195, -1.595, 'C'], [2.705, 1.058, 'D'], [0.658, 2.542, 'E']]}],
        ['SN Requiem / SN Encore (MACS J0138.0−2155)', {mag: 22.5, logm: logMOfSigma(850), zl: 0.338, zs: 1.95, q: 0.6, pa: 100, gamma: 0.05,
            snMag: 25, src: 'hostsn', re: 5, n: 2.5, sq: 0.7, spa: 30, bx: 0, by: 0.17, light: 1}],
        ['Lensed supernova (iPTF16geu-like)', {mag: 23.3, logm: logMOfSigma(160), zl: 0.216, zs: 0.409, q: 0.8, pa: 50, gamma: 0.05,
            src: 'point', bx: 0.05, by: 0.04, light: 1}],
        ['Point-mass lens (idealised)', {mag: 24, model: 'pm', logm: 12, zl: 0.5, zs: 2, gamma: 0, src: 'galaxy', re: 0.8,
            bx: 0.2, by: 0, light: 0}],
    ];
    let S = {...DEF};

    /* ------------------------------------------------------------ controls */
    const sliders = {logm: 'lsLogM', zl: 'lsZl', q: 'lsQ', pa: 'lsPa', gamma: 'lsGamma', gpa: 'lsGpa', light: 'lsLight',
                     zs: 'lsZs', re: 'lsRe', n: 'lsN', sq: 'lsSq', spa: 'lsSpa', bx: 'lsBx', by: 'lsBy', seeing: 'lsSeeing',
                     g2: 'lsG2', g2x: 'lsG2x', g2y: 'lsG2y', mag: 'lsMag', snMag: 'lsSnMag', D: 'lsD', pixT: 'lsPixT', exp: 'lsExp',
                     white: 'lsWhite', knee: 'lsKnee'};
    const fmt = {
        logm: (v) => `${(10 ** v).toExponential(1).replace('e+', '×10^')} M☉`.replace(/\^(\d+)/, (_, e) => sup(e)),
        zl: (v) => v.toFixed(3), zs: (v) => v.toFixed(3), q: (v) => v.toFixed(2), pa: (v) => `${v}°`, gpa: (v) => `${v}°`,
        gamma: (v) => v.toFixed(3), light: (v) => v.toFixed(2), re: (v) => `${v.toFixed(2)} kpc`, n: (v) => v.toFixed(1),
        sq: (v) => v.toFixed(2), spa: (v) => `${v}°`, bx: (v) => v.toFixed(3), by: (v) => v.toFixed(3),
        seeing: (v) => (v ? `${v.toFixed(2)}″` : 'off'), g2: (v) => (v ? `${v} km/s` : 'off'),
        g2x: (v) => `${v.toFixed(2)}″`, g2y: (v) => `${v.toFixed(2)}″`, mag: (v) => `${v.toFixed(1)} AB`, snMag: (v) => `${v.toFixed(1)} AB`,
        D: (v) => `${v.toFixed(1)} m`, white: (v) => `${v.toFixed(1)}`, knee: (v) => `${v.toFixed(1)}`, pixT: (v) => `${v.toFixed(3)}″/px`, exp: (v) => fmtTime(10 ** v),
    };
    function fmtTime(t) { return t < 120 ? `${t.toFixed(0)} s` : t < 7200 ? `${(t / 60).toFixed(0)} min` : `${(t / 3600).toFixed(1)} h`; }
    Object.entries(TELESCOPES).forEach(([k, t]) => $('lsTel').insertAdjacentHTML('beforeend', `<option value="${k}">${t.label}</option>`));
    Object.entries(BANDS).forEach(([k, l]) => $('lsBand').insertAdjacentHTML('beforeend', `<option value="${k}">${k} (${l} µm)</option>`));
    function telescope() {   // the telescope actually used, with derived numbers
        const T = TELESCOPES[S.tel];
        if (S.tel === 'ideal') return {ideal: true};
        const D = S.tel === 'custom' ? S.D : T.D, pixT = S.tel === 'custom' ? S.pixT : T.pix(S.band), lam = BANDS[S.band];
        const diff = 1.03 * lam * 1e-6 / D * ARC;
        return {D, pixT, lam, diff, fwhm: Math.sqrt(S.seeing ** 2 + diff ** 2), zp: 24.3 + 5 * Math.log10(D),
                sky: SKY[T.sky][S.band], t: 10 ** S.exp, label: T.label};
    }
    // Every slider also has a number box (typed values are clamped to the slider's range)
    const UNIT = {logm: 'M☉', pa: '°', gpa: '°', re: 'kpc', spa: '°', bx: 'θE', by: 'θE', seeing: '″', g2: 'km/s', g2x: '″',
                  g2y: '″', mag: 'AB', snMag: 'AB', D: 'm', pixT: '″/px', exp: 's',
                  white: 'mag/″²', knee: 'mag/″²'};
    const toUser = (k, v) => (k === 'logm' ? (10 ** v).toPrecision(3) : k === 'exp' ? String(Math.round(10 ** v))
        : String(+(+v).toFixed(Math.max(0, -Math.floor(Math.log10(+$(sliders[k]).step || 1))))));
    const fromUser = (k, t) => { const v = parseFloat(String(t).replace(/[^0-9eE+.\-]/g, '')); return k === 'logm' || k === 'exp' ? Math.log10(v) : v; };
    function sup(e) { return String(e).replace(/\d/g, (d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[d]); }

    for (const k of Object.keys(sliders)) {
        const out = document.querySelector(`[data-out="${k}"]`);
        if (!out) continue;
        out.innerHTML = `<input class="ls-num" data-num="${k}" inputmode="decimal" aria-label="value">${UNIT[k] ? `<span class="ls-unit">${UNIT[k]}</span>` : ''}`;
        const box = out.querySelector('input');
        box.addEventListener('click', (e) => e.preventDefault());           // the box sits inside the slider's <label>
        box.addEventListener('change', () => {
            const sl = $(sliders[k]);
            let v = fromUser(k, box.value);
            if (!isFinite(v)) { syncControls(); return; }
            v = Math.min(+sl.max, Math.max(+sl.min, v));
            sl.value = v; S[k] = v;
            if (k === 'zl' && S.zs <= S.zl + 0.01) S.zs = Math.min(10, S.zl + 0.01);
            if (k === 'zs' && S.zl >= S.zs - 0.01) S.zl = Math.max(0.01, S.zs - 0.01);
            $('lsPreset').value = '';
            syncControls(); schedule();
        });
        box.addEventListener('keydown', (e) => { if (e.key === 'Enter') box.blur(); });
    }
    PRESETS.forEach(([name], i) => $('lsPreset').insertAdjacentHTML('beforeend', `<option value="${i}">${name}</option>`));

    function syncControls() {
        for (const [k, id] of Object.entries(sliders)) {
            $(id).value = S[k];
            const box = document.querySelector(`[data-num="${k}"]`);
            if (box && document.activeElement !== box) { box.value = toUser(k, S[k]); box.title = fmt[k](S[k]); }
        }
        $('lsFov').value = String(S.fov);
        $('lsCrit').checked = S.crit;
        $('lsCaus').checked = S.caus;
        $('lsField').checked = S.field;
        $('lsEnv').value = S.env;
        $('lsTel').value = S.tel;
        $('lsBand').value = S.band;
        $('lsObs').checked = S.showObs;
        $('lsObsRow').hidden = !S.obs;
        page.dataset.g2 = S.g2 > 0 ? '1' : '0';
        page.dataset.tel = S.tel === 'ideal' ? 'ideal' : S.tel === 'custom' ? 'custom' : 'preset';
        page.dataset.model = S.model;
        page.dataset.src = S.src;
        document.querySelectorAll('[data-model]').forEach((b) => b.classList.toggle('is-on', b.dataset.model === S.model));
        document.querySelectorAll('[data-src]').forEach((b) => b.classList.toggle('is-on', b.dataset.src === S.src));
        $('lsMassLabel').textContent = S.model === 'pm' ? 'Total mass' : 'Mass inside 100 kpc';
    }

    let raf = 0;
    const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); };
    for (const [k, id] of Object.entries(sliders)) {
        $(id).addEventListener('input', () => {
            S[k] = +$(id).value;
            if (k === 'zl' && S.zs <= S.zl + 0.01) S.zs = Math.min(10, S.zl + 0.01);
            if (k === 'zs' && S.zl >= S.zs - 0.01) S.zl = Math.max(0.01, S.zs - 0.01);
            $('lsPreset').value = '';
            syncControls(); schedule();
        });
    }
    document.querySelectorAll('[data-model]').forEach((b) => b.addEventListener('click', () => { S.model = b.dataset.model; syncControls(); schedule(); }));
    document.querySelectorAll('[data-src]').forEach((b) => b.addEventListener('click', () => { S.src = b.dataset.src; syncControls(); schedule(); }));
    $('lsFov').addEventListener('change', () => { S.fov = $('lsFov').value === 'auto' ? 'auto' : +$('lsFov').value; schedule(); });
    $('lsCrit').addEventListener('change', () => { S.crit = $('lsCrit').checked; schedule(); });
    $('lsCaus').addEventListener('change', () => { S.caus = $('lsCaus').checked; schedule(); });
    $('lsField').addEventListener('change', () => { S.field = $('lsField').checked; schedule(); });
    $('lsEnv').addEventListener('change', () => { S.env = $('lsEnv').value; $('lsPreset').value = ''; schedule(); });
    $('lsObs').addEventListener('change', () => { S.showObs = $('lsObs').checked; schedule(); });
    $('lsTel').addEventListener('change', () => {
        S.tel = $('lsTel').value;
        const T = TELESCOPES[S.tel];
        if (T.D) { S.D = T.D; S.pixT = T.pix(S.band); S.seeing = T.seeing; }
        if (S.tel === 'jwst' && BANDS[S.band] < 0.7) S.band = 'H';
        syncControls(); schedule();
    });
    $('lsBand').addEventListener('change', () => { S.band = $('lsBand').value; syncControls(); schedule(); });
    $('lsPreset').addEventListener('change', () => {
        const p = PRESETS[+$('lsPreset').value];
        if (!p) return;
        const keep = ['tel', 'band', 'D', 'pixT', 'exp', 'seeing', 'field', 'crit', 'caus', 'showObs', 'white', 'knee'];
        S = {...DEF, ...p[1], fov: 'auto', ...Object.fromEntries(keep.map((k) => [k, S[k]]))};
        syncControls(); schedule();
    });
    $('lsReset').addEventListener('click', () => { S = {...DEF}; $('lsPreset').value = '0'; syncControls(); schedule(); });

    /* ------------------------------------------------------------ lens + source */
    function deflector(tE) {
        const g1 = S.gamma * Math.cos(2 * S.gpa * Math.PI / 180), g2 = S.gamma * Math.sin(2 * S.gpa * Math.PI / 180);
        const ca = Math.cos(S.pa * Math.PI / 180), sa = Math.sin(S.pa * Math.PI / 180);
        const q = S.q, f = Math.sqrt(Math.max(1 - q * q, 0)), core = 1e-4 * tE + 1e-9, sq = Math.sqrt(q);
        const tE2 = tE * tE;
        return (x, y, out) => {
            let ax, ay;
            if (S.model === 'pm') {
                const r2 = x * x + y * y + 1e-12 * tE2 + 1e-18;
                ax = tE2 * x / r2; ay = tE2 * y / r2;
            } else {
                const xr = ca * x + sa * y, yr = -sa * x + ca * y;
                let axr, ayr;
                if (f < 1e-3) {
                    const r = Math.sqrt(xr * xr + yr * yr + core * core);
                    axr = tE * xr / r; ayr = tE * yr / r;
                } else {
                    const psi = Math.sqrt(q * q * (xr * xr + core * core) + yr * yr);
                    axr = tE * sq / f * Math.atan(f * xr / (psi + core));
                    ayr = tE * sq / f * Math.atanh(Math.min(0.999999, f * yr / (psi + q * q * core)));
                }
                ax = ca * axr - sa * ayr; ay = sa * axr + ca * ayr;
            }
            out[0] = ax + g1 * x + g2 * y;
            out[1] = ay + g2 * x - g1 * y;
        };
    }

    function rng(seed) { return () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }; }
    const KNOTS = (() => {   // fixed star-forming knots (in units of r_e), so "Clumpy" looks the same every time
        const r = rng(42), k = [];
        for (let i = 0; i < 7; i++) {
            const rad = 1.1 * Math.sqrt(r()), th = 2 * Math.PI * r();
            k.push([rad * Math.cos(th), rad * Math.sin(th), 0.6 + 0.6 * r(), 0.1 + 0.08 * r()]);
        }
        return k;
    })();

    function sourceFn(cx, cy, reArc, pix) {
        if (S.src === 'point') return () => 0;
        const n = S.src === 'clumpy' ? 1 : S.n, bn = 1.9992 * n - 0.3271, inv = 1 / n;
        const hostSn = S.src === 'hostsn';
        const c = Math.cos(S.spa * Math.PI / 180), s = Math.sin(S.spa * Math.PI / 180), q = S.sq;
        const re = Math.max(reArc, 0.3 * pix);
        const knots = S.src === 'clumpy' ? KNOTS.map(([u, v, w, sg]) => {
            const kx = cx + (c * u * Math.sqrt(q) - s * v / Math.sqrt(q)) * re, ky = cy + (s * u * Math.sqrt(q) + c * v / Math.sqrt(q)) * re;
            const sig = Math.max(sg * re, 0.5 * pix);
            return [kx, ky, w, 1 / (2 * sig * sig)];
        }) : [];
        const base = S.src === 'clumpy' ? 0.45 : 1;
        return (x, y) => {
            const dx = x - cx, dy = y - cy;
            const xr = c * dx + s * dy, yr = -s * dx + c * dy;
            const r = Math.sqrt(q * xr * xr + yr * yr / q) / re;
            let v = base * Math.exp(-bn * Math.pow(r, inv));
            for (const [kx, ky, w, k] of knots) {
                const ex = x - kx, ey = y - ky;
                v += w * Math.exp(-(ex * ex + ey * ey) * k);
            }
            return v;
        };
    }

    /* ------------------------------------------------------------ foreground scene */
    // What sits at the lens redshift depends on the lens class: an isolated elliptical, a group (central galaxy +
    // a few members) or a cluster (BCG + intracluster light + a red sequence whose number grows as σ³). Members
    // follow Σ ∝ 1/r, have Schechter-like luminosities, Faber–Jackson σ (L ∝ σ⁴) and add their own SIS deflection.
    // Positions are in kpc (so the scene shrinks with distance) and seeded, so moving a slider does not reshuffle it.
    const ENV_LABEL = {galaxy: 'Isolated galaxy', group: 'Group', cluster: 'Cluster', none: 'Compact object'};
    const RED = [1.0, 0.78, 0.5], BLUE_MEMBER = [0.72, 0.84, 1.0];

    function envOf(sig) {
        if (S.model === 'pm') return 'none';
        if (S.env !== 'auto') return S.env;
        return sig < 350 ? 'galaxy' : sig < 750 ? 'group' : 'cluster';
    }

    function scene(d, sig, kpcL, fov, pix) {
        const env = envOf(sig), r = rng(9001), objs = [], perturbers = [];
        const lensFac = 4 * Math.PI / (C * C) * d.Dls / d.Ds * ARC;           // θ_E = lensFac · σ²
        const arc = (kpc) => kpc / kpcL;
        const add = (o) => { o.reA = Math.max(arc(o.re), 1.2 * pix); objs.push(o); };
        if (env === 'none') return {env, objs, perturbers, n: 0};
        if (S.g2 > 0) {   // a second lens galaxy (e.g. SN 2025wny's G2): SIS mass + elliptical light, offset in arcsec
            const L2 = Math.min(6, Math.max(0.1, (S.g2 / 220) ** 4));
            perturbers.push([S.g2x, S.g2y, lensFac * S.g2 * S.g2]);
            add({x: S.g2x, y: S.g2y, L: L2, re: Math.min(15, Math.max(1, 4 * L2 ** 0.6)), n: 4, q: 0.8, pa: 60, col: RED});
        }
        // central galaxy
        let Lc, rec;
        if (env === 'galaxy') { Lc = Math.min(6, Math.max(0.2, (sig / 220) ** 4)); rec = Math.min(15, Math.max(1, 4 * Lc ** 0.6)); }
        else if (env === 'group') { Lc = 3 + 3 * (sig - 350) / 400; rec = 8 * (Lc / 3) ** 0.6; }
        else { Lc = 8 + 4 * sig / 1000; rec = 25 + 10 * sig / 1000; }
        add({x: 0, y: 0, L: Lc, re: rec, n: 4, q: S.q, pa: S.pa, col: RED});
        if (env === 'cluster') add({x: 0, y: 0, L: Lc * 2.2, re: 160, n: 1, q: Math.min(1, S.q + 0.1), pa: S.pa, col: [1.0, 0.82, 0.6], icl: true});
        if (env === 'galaxy') return {env, objs, perturbers, n: 0};
        // members
        const nMem = env === 'group' ? Math.round(3 + 5 * Math.min(1, (sig - 350) / 400))
                                    : Math.round(Math.min(80, Math.max(10, 25 * (sig / 1000) ** 3)));
        const Rmax = env === 'group' ? 300 : 1500 * sig / 1000;
        const ca = Math.cos(S.pa * Math.PI / 180), sa = Math.sin(S.pa * Math.PI / 180), qs = Math.sqrt(S.q);
        let shown = 0;
        for (let i = 0; i < nMem; i++) {
            const rr = Math.max(25, Rmax * r()), th = 2 * Math.PI * r();
            const u = rr * Math.cos(th) / qs, v = rr * Math.sin(th) * qs;          // follow the halo's shape
            const xk = ca * u - sa * v, yk = sa * u + ca * v;
            const L = Math.min(3, Math.max(0.08, 0.12 / (r() ** 1.3 + 0.04)));
            const spiral = env === 'group' ? r() < 0.35 : (rr > 0.5 * Rmax && r() < 0.3);
            const q = spiral ? 0.3 + 0.6 * r() : 0.6 + 0.4 * r(), pa = 180 * r();
            const x = arc(xk), y = arc(yk);
            const sigI = 220 * L ** 0.25 * (spiral ? 0.7 : 1);
            if (Math.abs(x) < fov && Math.abs(y) < fov) perturbers.push([x, y, lensFac * sigI * sigI]);
            if (Math.abs(x) < 0.7 * fov && Math.abs(y) < 0.7 * fov) {
                shown++;
                add({x, y, L, re: (spiral ? 5 : 4) * L ** 0.6, n: spiral ? 1 : 4, q, pa, col: spiral ? BLUE_MEMBER : RED});
            }
        }
        return {env, objs, perturbers, n: shown};
    }

    // Background field at the source redshift (lensed, so clusters show weak-lensing arclets) and foreground stars.
    function field(fov, pix) {
        const r = rng(4242 + Math.round(fov * 10)), half = 0.6 * fov, gals = [], stars = [];
        const nG = Math.min(700, Math.round(0.012 * (2 * half) ** 2));
        const cols = [[0.55, 0.75, 1.0], [0.9, 0.92, 1.0], [1.0, 0.82, 0.62]];
        for (let i = 0; i < nG; i++) {
            const re = Math.max(0.6 * pix, 0.12 * Math.exp(1.1 * r()));
            gals.push({x: (2 * r() - 1) * half, y: (2 * r() - 1) * half, re, q: 0.3 + 0.7 * r(), pa: Math.PI * r(),
                       amp: 0.025 + 0.35 * r() ** 2, col: cols[Math.floor(3 * r())]});
        }
        const nS = Math.round(0.00015 * (2 * half) ** 2);
        for (let i = 0; i < nS; i++) {
            const t = r();
            stars.push({x: (2 * r() - 1) * half, y: (2 * r() - 1) * half, mag: 17 + 7 * r(),
                        col: [1.0, 0.9 + 0.1 * t, 0.75 + 0.25 * t]});
        }
        // grid hash in the source plane for fast lookups
        const cell = Math.max(1.5, fov / 24), nc = Math.ceil(2 * half / cell) + 1, grid = new Map();
        for (const g of gals) {
            const ext = 5 * g.re;
            const i0 = Math.floor((g.x - ext + half) / cell), i1 = Math.floor((g.x + ext + half) / cell);
            const j0 = Math.floor((g.y - ext + half) / cell), j1 = Math.floor((g.y + ext + half) / cell);
            for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
                const k = j * nc + i;
                if (!grid.has(k)) grid.set(k, []);
                grid.get(k).push(g);
            }
            g.c = Math.cos(g.pa); g.s = Math.sin(g.pa); g.ir = 1 / g.re;
        }
        const at = (x, y, out) => {   // adds the background light at source-plane (x, y) into out[0..2]
            const k = Math.floor((y + half) / cell) * nc + Math.floor((x + half) / cell);
            const list = grid.get(k);
            if (!list) return;
            for (const g of list) {
                const dx = x - g.x, dy = y - g.y, xr = g.c * dx + g.s * dy, yr = -g.s * dx + g.c * dy;
                const rr = Math.sqrt(g.q * xr * xr + yr * yr / g.q) * g.ir;
                if (rr > 5) continue;
                const v = g.amp * Math.exp(-1.678 * rr);
                out[0] += v * g.col[0]; out[1] += v * g.col[1]; out[2] += v * g.col[2];
            }
        };
        return {at, stars};
    }

    // Gaussian blur by three box passes per axis (cost independent of the seeing in pixels)
    function boxPass(src, dst, N, r, horiz) {
        const w = 2 * r + 1;
        for (let a = 0; a < N; a++) {
            let acc = 0;
            const idx = (b) => (horiz ? a * N + Math.min(N - 1, Math.max(0, b)) : Math.min(N - 1, Math.max(0, b)) * N + a);
            for (let b = -r; b <= r; b++) acc += src[idx(b)];
            for (let b = 0; b < N; b++) {
                dst[horiz ? a * N + b : b * N + a] = acc / w;
                acc += src[idx(b + r + 1)] - src[idx(b - r)];
            }
        }
    }
    // Point sources (quasar, or the supernova of Host + SN, 0.4 r_e from the host centre along its major axis) are
    // far smaller than a pixel, so they are not sampled: the lens equation β = θ − α(θ) is solved for their images
    // (grid minima of |β − β_s|, refined by Newton steps) and each image gets |μ| × the flux, μ = 1 / det A.
    function pointImages(defl, bsx, bsy, AX, AY, fov, pix) {
        const cand = [], d2 = (k, x, y) => (x - AX[k] - bsx) ** 2 + (y - AY[k] - bsy) ** 2;
        for (let j = 1; j < N - 1; j++) {
            const y = fov / 2 - (j + 0.5) * pix;
            for (let i = 1; i < N - 1; i++) {
                const x = (i + 0.5) * pix - fov / 2, k = j * N + i, v = d2(k, x, y);
                if (v > 16 * pix * pix) continue;
                let min = true;
                for (let dj = -1; dj <= 1 && min; dj++) for (let di = -1; di <= 1; di++) {
                    if (!di && !dj) continue;
                    const kk = k + dj * N + di, xx = x + di * pix, yy = y - dj * pix;
                    if (d2(kk, xx, yy) < v) { min = false; break; }
                }
                if (min) cand.push([x, y]);
            }
        }
        const a = [0, 0], b = [0, 0], h = 1e-4 * fov, out = [];
        const beta = (x, y) => { defl(x, y, a); return [x - a[0], y - a[1]]; };
        const jac = (x, y) => {
            const px = beta(x + h, y), mx = beta(x - h, y), py = beta(x, y + h), my = beta(x, y - h);
            return [(px[0] - mx[0]) / (2 * h), (py[0] - my[0]) / (2 * h), (px[1] - mx[1]) / (2 * h), (py[1] - my[1]) / (2 * h)];
        };
        for (let [x, y] of cand) {
            let ok = false;
            for (let it = 0; it < 30; it++) {
                const [ux, uy] = beta(x, y), ex = bsx - ux, ey = bsy - uy;
                if (ex * ex + ey * ey < (1e-6 * fov) ** 2) { ok = true; break; }
                const [a11, a12, a21, a22] = jac(x, y), det = a11 * a22 - a12 * a21;
                if (Math.abs(det) < 1e-9) break;
                let sx = (a22 * ex - a12 * ey) / det, sy = (-a21 * ex + a11 * ey) / det;
                const st = Math.hypot(sx, sy);
                if (st > 2 * pix) { sx *= 2 * pix / st; sy *= 2 * pix / st; }
                x += sx; y += sy;
            }
            if (!ok || Math.abs(x) > fov / 2 || Math.abs(y) > fov / 2) continue;
            if (out.some((o) => Math.hypot(o.x - x, o.y - y) < 0.5 * pix)) continue;
            const [a11, a12, a21, a22] = jac(x, y);
            out.push({x, y, mu: 1 / (a11 * a22 - a12 * a21)});
            void b;
        }
        return out;
    }

    function stamp(chs, cols, x0, y0, flux, fov, pix) {   // a point of total flux (units × arcsec²) as a 0.6-pixel Gaussian
        const sg = 0.6 * pix, k = 1 / (2 * sg * sg), amp = flux / (2 * Math.PI * sg * sg), ext = 4 * sg;
        const i0 = Math.max(0, Math.floor((x0 - ext + fov / 2) / pix)), i1 = Math.min(N - 1, Math.ceil((x0 + ext + fov / 2) / pix));
        const j0 = Math.max(0, Math.floor((fov / 2 - y0 - ext) / pix)), j1 = Math.min(N - 1, Math.ceil((fov / 2 - y0 + ext) / pix));
        for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
            const x = (i + 0.5) * pix - fov / 2 - x0, y = fov / 2 - (j + 0.5) * pix - y0, v = amp * Math.exp(-(x * x + y * y) * k);
            for (let c = 0; c < chs.length; c++) chs[c][j * N + i] += v * cols[c];
        }
    }

    function blur(a, N, sigPix) {
        if (sigPix < 0.3) return a;
        const r = Math.max(1, Math.round((Math.sqrt(12 * sigPix * sigPix / 3 + 1) - 1) / 2));
        let x = Float32Array.from(a), y = new Float32Array(a.length);
        for (const horiz of [true, false]) for (let i = 0; i < 3; i++) { boxPass(x, y, N, r, horiz); [x, y] = [y, x]; }
        return x;
    }

    function gauss(r) {   // standard normal (Box–Muller) from a seeded uniform generator
        return Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
    }

    /* ------------------------------------------------------------ render */
    const N = 340;
    const SRC_RGB = [0.45, 0.72, 1.0];
    const off = document.createElement('canvas');
    off.width = off.height = N;
    const offCtx = off.getContext('2d');
    let view = null;     // what the last render used (for dragging and overlays)

    function css(name, fb) { return getComputedStyle(page).getPropertyValue(name).trim() || fb; }

    function render() {
        const d = dists(S.zl, S.zs);
        const M = 10 ** S.logm;
        const tE = thetaE(S.model, M, d);
        const sig = S.model === 'sie' ? sigmaOf(M) : 0;
        const kpcL = d.Dl * 1000 / ARC, kpcS = d.Ds * 1000 / ARC;      // kpc per arcsec at the lens / source
        const reArc = S.re / kpcS;
        const fov = S.fov === 'auto' ? niceFov(Math.max(5 * tE, S.src === 'point' ? 0 : 6 * reArc, 0.5)) : S.fov;
        const pix = fov / N;
        const cx = S.bx * tE, cy = S.by * tE;
        const alpha = deflector(tE), src = sourceFn(cx, cy, reArc, pix);
        const ptSrc = S.src === 'point' || S.src === 'hostsn';
        const ptX = S.src === 'point' ? cx : cx + 0.4 * Math.max(reArc, 0.3 * pix) * Math.cos(S.spa * Math.PI / 180);
        const ptY = S.src === 'point' ? cy : cy + 0.4 * Math.max(reArc, 0.3 * pix) * Math.sin(S.spa * Math.PI / 180);
        const defl = (x, y, o) => {
            alpha(x, y, o);
            for (const [px, py, tE2] of P) {
                const dx = x - px, dy = y - py, rr = Math.sqrt(dx * dx + dy * dy) + 0.02 * tE2 + 1e-6;
                o[0] += tE2 * dx / rr; o[1] += tE2 * dy / rr;
            }
        };
        const sc = scene(d, sig, kpcL, fov, pix);
        const fld = S.field ? field(fov, pix) : null;
        const P = sc.perturbers;
        // star-forming sources are blue; a bulge-like (n ≥ 2) host is a red, quiescent galaxy (e.g. SN Requiem's MRG-M0138)
        const SC = (S.src === 'galaxy' || S.src === 'hostsn') && S.n >= 2 ? [1.0, 0.7, 0.48] : SRC_RGB;

        // Units: surface brightness in multiples of 22 mag/arcsec² (AB). The source is scaled to its total magnitude.
        const NN = N * N;
        const img = [new Float32Array(NN), new Float32Array(NN), new Float32Array(NN)];
        const pln = [new Float32Array(NN), new Float32Array(NN), new Float32Array(NN)];
        const sImg = new Float32Array(NN), sPln = new Float32Array(NN);          // the main source alone
        const AX = new Float32Array(NN), AY = new Float32Array(NN);
        const a = [0, 0], bg = [0, 0, 0];
        let sumImg = 0, sumSrc = 0;
        for (let j = 0; j < N; j++) {
            const y = fov / 2 - (j + 0.5) * pix;
            for (let i = 0; i < N; i++) {
                const x = (i + 0.5) * pix - fov / 2, k = j * N + i;
                defl(x, y, a);                     // main lens + member / second galaxies (SIS) + shear
                AX[k] = a[0]; AY[k] = a[1];
                const bx = x - a[0], by = y - a[1];
                const v = src(bx, by), v0 = src(x, y);
                sumImg += v; sumSrc += v0; sImg[k] = v; sPln[k] = v0;
                if (fld) {
                    bg[0] = bg[1] = bg[2] = 0; fld.at(bx, by, bg);
                    img[0][k] += bg[0]; img[1][k] += bg[1]; img[2][k] += bg[2];
                    bg[0] = bg[1] = bg[2] = 0; fld.at(x, y, bg);
                    pln[0][k] += bg[0]; pln[1][k] += bg[1]; pln[2][k] += bg[2];
                }
            }
        }
        let mu = sumSrc > 0 ? sumImg / sumSrc : NaN;
        const srcAmp = sumSrc > 0 ? 10 ** (-0.4 * (S.mag - 22)) / (sumSrc * pix * pix) : 0;
        for (let k = 0; k < NN; k++) {
            sImg[k] *= srcAmp; sPln[k] *= srcAmp;
            for (let c = 0; c < 3; c++) { img[c][k] += sImg[k] * SC[c]; pln[c][k] += sPln[k] * SC[c]; }
        }
        let pts = [];
        if (ptSrc) {   // quasar / supernova images from the lens equation
            const F = 10 ** (-0.4 * ((S.src === 'point' ? S.mag : S.snMag) - 22)), PT_RGB = S.src === 'point' ? SRC_RGB : [0.92, 0.95, 1.0];
            pts = pointImages(defl, ptX, ptY, AX, AY, fov, pix);
            for (const im of pts) stamp([...img, sImg], [...PT_RGB, 1], im.x, im.y, Math.abs(im.mu) * F, fov, pix);
            stamp([...pln, sPln], [...PT_RGB, 1], ptX, ptY, F, fov, pix);
            if (S.src === 'point') mu = pts.reduce((t, im) => t + Math.abs(im.mu), 0);
        }

        // foreground light (not lensed): each object drawn in its own box
        if (S.light > 0) {
            const tolman = Math.min(3, ((1 + 0.3) / (1 + S.zl)) ** 4);       // (1+z)⁻⁴ dimming, relative to z = 0.3
            for (const o of sc.objs) {
                const bn = o.n === 4 ? 7.669 : 1.678, inv = 1 / o.n;
                // I(r) = I_e exp(−b_n[(r/r_e)^(1/n) − 1]); an L* elliptical at z = 0.3 has μ_e ≈ 21.5 mag/arcsec² and
                // I_e follows the Kormendy relation (bigger → fainter per arcsec²)
                const Ie = (o.icl ? 0.06 : 1.5 * (o.re / 4) ** -1.2 * (o.n === 1 ? 0.5 : 1)) * S.light * tolman;
                const c = Math.cos(o.pa * Math.PI / 180), s = Math.sin(o.pa * Math.PI / 180);
                const ext = Math.min(fov, (o.icl ? 3 : o.n === 4 ? 40 : 12) * o.reA);   // far enough that no box edge shows
                const i0 = Math.max(0, Math.floor((o.x - ext + fov / 2) / pix)), i1 = Math.min(N - 1, Math.ceil((o.x + ext + fov / 2) / pix));
                const j0 = Math.max(0, Math.floor((fov / 2 - o.y - ext) / pix)), j1 = Math.min(N - 1, Math.ceil((fov / 2 - o.y + ext) / pix));
                for (let j = j0; j <= j1; j++) {
                    const y = fov / 2 - (j + 0.5) * pix - o.y;
                    for (let i = i0; i <= i1; i++) {
                        const x = (i + 0.5) * pix - fov / 2 - o.x;
                        const xr = c * x + s * y, yr = -s * x + c * y;
                        const rr = Math.sqrt(o.q * xr * xr + yr * yr / o.q) / o.reA + 1e-3;
                        const v = Ie * Math.exp(-bn * (Math.pow(rr, inv) - 1));
                        const k = j * N + i;
                        img[0][k] += v * o.col[0]; img[1][k] += v * o.col[1]; img[2][k] += v * o.col[2];
                    }
                }
            }
        }
        if (fld) {   // foreground stars (17–24 mag): unresolved, drawn at the pixel scale before the PSF
            const sg = Math.max(0.6 * pix, 0.01);
            for (const st of fld.stars) {
                const ext = 4 * sg, kk = 1 / (2 * sg * sg), amp = 10 ** (-0.4 * (st.mag - 22)) / (2 * Math.PI * sg * sg);
                const i0 = Math.max(0, Math.floor((st.x - ext + fov / 2) / pix)), i1 = Math.min(N - 1, Math.ceil((st.x + ext + fov / 2) / pix));
                const j0 = Math.max(0, Math.floor((fov / 2 - st.y - ext) / pix)), j1 = Math.min(N - 1, Math.ceil((fov / 2 - st.y + ext) / pix));
                for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
                    const x = (i + 0.5) * pix - fov / 2 - st.x, y = fov / 2 - (j + 0.5) * pix - st.y;
                    const v = amp * Math.exp(-(x * x + y * y) * kk), k = j * N + i;
                    img[0][k] += v * st.col[0]; img[1][k] += v * st.col[1]; img[2][k] += v * st.col[2];
                }
            }
        }

        // the telescope: PSF (seeing ⊕ diffraction 1.03 λ/D), detector pixels, photon + sky + read noise
        const T = telescope();
        const sigPix = T.ideal ? 1 : T.fwhm / 2.3548 / pix;   // ideal: perfect optics, but a point still fills a pixel
        const f = T.ideal ? 1 : T.pixT / pix;
        const observe = (ch) => (f > 1.5 ? pixelate(blur(ch, N, sigPix), N, f) : blur(ch, N, sigPix));
        const out = [img, pln].map((rgb) => rgb.map(observe));
        const maxOf = (arr) => { let m = 0; for (let k = 0; k < arr.length; k++) if (arr[k] > m) m = arr[k]; return m; };
        const peakI = T.ideal ? 0 : maxOf(observe(sImg));                // brightest observed source pixel (for S/N)
        let noise = null;
        if (!T.ideal) {
            const pe = Math.max(T.pixT, pix);                              // effective pixel (″)
            const Eu = 10 ** (-0.4 * (22 - T.zp)) * pe * pe * T.t;          // e⁻ per pixel for 1 unit
            const skyE = 10 ** (-0.4 * (T.sky - T.zp)) * pe * pe * T.t, RN2 = 25;
            const fb = Math.max(1, f);
            const nb = Math.ceil(N / fb);
            for (const [w, rgb] of out.entries()) {   // one draw per detector pixel, shared by R, G, B (grey noise)
                const rn = rng(31337 + w), draws = new Float32Array(nb * nb);
                for (let b = 0; b < draws.length; b++) draws[b] = gauss(rn);
                for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
                    const k = j * N + i, dr = draws[Math.floor(j / fb) * nb + Math.floor(i / fb)];
                    const e = Math.max(0, (rgb[0][k] + rgb[1][k] + rgb[2][k]) / 3) * Eu, sd = Math.sqrt(skyE + e + RN2) / Eu;
                    for (const ch of rgb) ch[k] += dr * sd;
                }
            }
            const skyU = Math.sqrt(skyE + RN2) / Eu;
            noise = {skyU, Eu, skyE, RN2, pe, snr: peakI * Eu / Math.sqrt(skyE + peakI * Eu + RN2),
                     mu1: 22 - 2.5 * Math.log10(skyU * pe)};               // 1σ surface-brightness limit per arcsec²
        }
        // display: one fixed surface-brightness scale for both panels (white point and asinh knee in mag/arcsec²), so a
        // change to one object never brightens or dims the others; lensing conserves surface brightness, so an arc and its
        // unlensed source look equally bright per pixel
        const norm = 1 / 10 ** (-0.4 * (S.white - 22)), soft = Math.min(0.5, 10 ** (-0.4 * (S.knee - 22)) * norm);

        // critical curves (det A changes sign between neighbours) and their caustics
        const crit = [], caus = [];
        const det = new Float32Array(NN);
        for (let j = 1; j < N - 1; j++) for (let i = 1; i < N - 1; i++) {
            const k = j * N + i;
            const dxx = (AX[k + 1] - AX[k - 1]) / (2 * pix), dxy = (AX[k - N] - AX[k + N]) / (2 * pix);
            const dyx = (AY[k + 1] - AY[k - 1]) / (2 * pix), dyy = (AY[k - N] - AY[k + N]) / (2 * pix);
            det[k] = (1 - dxx) * (1 - dyy) - dxy * dyx;
        }
        for (let j = 1; j < N - 2; j++) for (let i = 1; i < N - 2; i++) {
            const k = j * N + i;
            if (det[k] * det[k + 1] < 0 || det[k] * det[k + N] < 0) {
                const x = (i + 0.5) * pix - fov / 2, y = fov / 2 - (j + 0.5) * pix;
                crit.push([x, y]); caus.push([x - AX[k], y - AY[k]]);
            }
        }

        paint($('lsSrc'), out[1], norm, soft, fov, S.caus ? caus : [], '#ff6b8a', [cx, cy]);
        paint($('lsImg'), out[0], norm, soft, fov, S.crit ? crit : [], css('--color-accent', '#F39F5A'), null,
              S.obs && S.showObs ? S.obs : null);
        scaleBar('lsScaleS', fov); scaleBar('lsScaleI', fov);
        view = {fov, tE, pts};
        stats(d, M, tE, kpcL, reArc, mu, fov, sc, T, noise, pts);
        chart(M);
    }

    function niceFov(v) {
        const steps = [0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 60, 80, 120, 160, 240, 300, 480, 600];
        return steps.find((s) => s >= v) || 600;
    }

    function pixelate(ch, N, f) {   // block-average onto detector pixels f sim-pixels wide
        const nb = Math.ceil(N / f), sum = new Float64Array(nb * nb), cnt = new Uint32Array(nb * nb), o = new Float32Array(ch.length);
        for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
            const b = Math.floor(j / f) * nb + Math.floor(i / f); sum[b] += ch[j * N + i]; cnt[b]++;
        }
        for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
            const b = Math.floor(j / f) * nb + Math.floor(i / f); o[j * N + i] = sum[b] / cnt[b];
        }
        return o;
    }

    function paint(cv, rgb, norm, soft, fov, pts, col, mark, obs) {
        const data = offCtx.createImageData(N, N), px = data.data, den = Math.asinh(1 / soft);
        for (let k = 0; k < N * N; k++) {
            for (let c = 0; c < 3; c++) {
                const v = Math.asinh(rgb[c][k] * norm / soft) / den;
                px[4 * k + c] = 255 * Math.min(1, Math.max(0, v));
            }
            px[4 * k + 3] = 255;
        }
        offCtx.putImageData(data, 0, 0);
        const dpr = window.devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr) || 420;
        if (cv.width !== W) { cv.width = W; cv.height = W; }
        const ctx = cv.getContext('2d');
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(off, 0, 0, W, W);
        const toPx = (x, y) => [(x / fov + 0.5) * W, (0.5 - y / fov) * W];
        ctx.fillStyle = col;
        const r = Math.max(1, dpr * 0.9);
        for (const [x, y] of pts) {
            const [u, v] = toPx(x, y);
            if (u >= 0 && u < W && v >= 0 && v < W) ctx.fillRect(u - r / 2, v - r / 2, r, r);
        }
        if (obs) {   // observed image positions (e.g. HST / JWST astrometry)
            ctx.strokeStyle = '#5ef0c4'; ctx.fillStyle = '#5ef0c4'; ctx.lineWidth = 1.5 * dpr;
            ctx.font = `${12 * dpr}px system-ui, sans-serif`;
            for (const [x, y, lab] of obs) {
                const [u, v] = toPx(x, y), h = 6 * dpr;
                ctx.beginPath(); ctx.moveTo(u - h, v - h); ctx.lineTo(u + h, v + h); ctx.moveTo(u + h, v - h); ctx.lineTo(u - h, v + h); ctx.stroke();
                ctx.fillText(lab, u + 8 * dpr, v - 6 * dpr);
            }
        }
        if (mark) {   // source centre handle
            const [u, v] = toPx(mark[0], mark[1]);
            ctx.strokeStyle = 'rgba(255,255,255,.75)'; ctx.lineWidth = dpr;
            ctx.beginPath(); ctx.arc(u, v, 7 * dpr, 0, 2 * Math.PI); ctx.stroke();
        }
    }

    function scaleBar(id, fov) {
        const target = fov / 5, steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120];
        const len = steps.reduce((b, s) => (Math.abs(s - target) < Math.abs(b - target) ? s : b), steps[0]);
        const el = $(id);
        el.style.width = `${(88 * len / fov).toFixed(2)}%`;
        el.firstElementChild.textContent = len >= 60 ? `${len / 60}′` : `${len}″`;
    }

    function num(v, d = 2) {
        if (!isFinite(v)) return '—';
        if (v !== 0 && (Math.abs(v) >= 1e5 || Math.abs(v) < 1e-2)) {
            const e = Math.floor(Math.log10(Math.abs(v)));
            return `${(v / 10 ** e).toFixed(1)}×10${sup(e).replace('-', '⁻')}`;
        }
        return v.toFixed(d);
    }

    function stats(d, M, tE, kpcL, reArc, mu, fov, sc, T, noise, pts) {
        const sigCr = d.Ds / (4 * Math.PI * G_C2 * d.Dl * d.Dls) / 1e12;       // M☉ / pc²
        const RE = tE * kpcL;                                                   // kpc
        const ME = sigCr * 1e6 * Math.PI * RE * RE;                             // M☉ (Σcr in M☉/kpc² × area)
        const rows = [
            ['Lens', sc.env === 'galaxy' || sc.env === 'none' ? ENV_LABEL[sc.env] : `${ENV_LABEL[sc.env]} · ${sc.n} members in view`, true],
            ['Einstein radius θ<sub>E</sub>', `${num(tE)}″`, true],
            ['Physical R<sub>E</sub>', `${num(RE)} kpc`, true],
            ['Magnification μ', `${num(mu, 1)}×`, true],
            pts.length ? [`${S.src === 'point' ? 'Point' : 'SN'} images`, `${pts.length} · |μ| ${pts.slice().sort((p, q) => Math.abs(q.mu) - Math.abs(p.mu)).map((im) => num(Math.abs(im.mu), 1)).join(', ')}`, true] : null,
            ['Mass inside θ<sub>E</sub>', `${num(ME)} M☉`],
            S.model === 'sie' ? ['Velocity dispersion σ', `${num(sigmaOf(M), 0)} km/s`] : null,
            ['Σ<sub>cr</sub>', `${num(sigCr, 0)} M☉/pc²`],
            ['D<sub>l</sub> (angular)', `${num(d.Dl / 1000)} Gpc`],
            ['D<sub>s</sub> (angular)', `${num(d.Ds / 1000)} Gpc`],
            ['D<sub>ls</sub>', `${num(d.Dls / 1000)} Gpc`],
            ['D<sub>ls</sub> / D<sub>s</sub>', num(d.Dls / d.Ds, 3)],
            ['Scale at the lens', `${num(kpcL)} kpc/″`],
            S.src === 'point' ? null : ['Source r<sub>e</sub>', `${num(reArc, 3)}″`],
            ['Field', `${fov}″ × ${fov}″`],
            T.ideal ? null : ['PSF FWHM', `${num(T.fwhm)}″ <small>(diffraction ${num(T.diff, 3)}″)</small>`, true],
            T.ideal ? null : ['Detector pixel', `${num(T.pixT, 3)}″`],
            noise ? ['S/N at the brightest image pixel', num(noise.snr, 1), true] : null,
            noise ? ['1σ depth', `${num(noise.mu1, 1)} mag/arcsec²`] : null,
            noise ? ['Sky', `${num(T.sky, 1)} mag/arcsec² · ${num(10 ** S.exp, 0)} s`] : null,
        ].filter(Boolean);
        $('lsStats').innerHTML = rows.map(([k, v, key]) => `<div class="ls-stat${key ? ' is-key' : ''}"><span>${k}</span><b>${v}</b></div>`).join('');
    }

    function chart(M) {
        const cv = $('lsChart'), dpr = window.devicePixelRatio || 1;
        const W = Math.round((cv.clientWidth || 900) * dpr), H = Math.round(W * 0.28);
        if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
        const ctx = cv.getContext('2d');
        ctx.clearRect(0, 0, W, H);
        const zmax = Math.max(0.02, S.zs - 0.005), n = 160, xs = [], ys = [];
        for (let i = 0; i <= n; i++) {
            const z = 0.005 + (zmax - 0.005) * i / n;
            xs.push(z); ys.push(thetaE(S.model, M, dists(z, S.zs)));
        }
        const ymax = Math.max(...ys.filter(isFinite)) * 1.1 || 1;
        const L = 56 * dpr, R = 14 * dpr, T = 12 * dpr, B = 30 * dpr;
        const X = (z) => L + (z / zmax) * (W - L - R), Y = (v) => H - B - Math.min(v / ymax, 1) * (H - T - B);
        const muted = css('--kw-text-muted', '#888'), acc = css('--color-accent', '#F39F5A');
        ctx.strokeStyle = 'rgba(255,255,255,.12)'; ctx.fillStyle = muted; ctx.lineWidth = dpr;
        ctx.font = `${11 * dpr}px system-ui, sans-serif`;
        for (let i = 0; i <= 4; i++) {
            const v = ymax * i / 4, y = Y(v);
            ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(W - R, y); ctx.stroke();
            ctx.textAlign = 'right'; ctx.fillText(`${num(v, v < 10 ? 1 : 0)}″`, L - 6 * dpr, y + 4 * dpr);
        }
        ctx.textAlign = 'center';
        for (let i = 0; i <= 5; i++) { const z = zmax * i / 5; ctx.fillText(z.toFixed(2), X(z), H - B + 16 * dpr); }
        ctx.fillText('lens redshift z_l', (L + W - R) / 2, H - 2 * dpr);
        ctx.strokeStyle = acc; ctx.lineWidth = 2 * dpr; ctx.beginPath();
        xs.forEach((z, i) => (i ? ctx.lineTo(X(z), Y(ys[i])) : ctx.moveTo(X(z), Y(ys[i]))));
        ctx.stroke();
        const cur = thetaE(S.model, M, dists(S.zl, S.zs));
        ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(X(S.zl), Y(cur), 4.5 * dpr, 0, 2 * Math.PI); ctx.fill();
        ctx.fillStyle = muted; ctx.textAlign = 'left';
        ctx.fillText(`z_s = ${S.zs.toFixed(2)}`, W - R - 80 * dpr, T + 10 * dpr);
    }

    /* ------------------------------------------------------------ drag the source */
    const srcCv = $('lsSrc');
    let dragging = false;
    function dragTo(ev) {
        if (!view || !view.tE) return;
        const r = srcCv.getBoundingClientRect();
        const x = ((ev.clientX - r.left) / r.width - 0.5) * view.fov, y = (0.5 - (ev.clientY - r.top) / r.height) * view.fov;
        S.bx = Math.max(-2, Math.min(2, x / view.tE));
        S.by = Math.max(-2, Math.min(2, y / view.tE));
        $('lsPreset').value = '';
        syncControls(); schedule();
    }
    srcCv.addEventListener('pointerdown', (ev) => { dragging = true; srcCv.classList.add('is-drag'); srcCv.setPointerCapture(ev.pointerId); dragTo(ev); });
    srcCv.addEventListener('pointermove', (ev) => { if (dragging) dragTo(ev); });
    const end = () => { dragging = false; srcCv.classList.remove('is-drag'); };
    srcCv.addEventListener('pointerup', end);
    srcCv.addEventListener('pointercancel', end);
    window.addEventListener('resize', schedule);

    $('lsPreset').value = '0';
    syncControls();
    render();
})();
