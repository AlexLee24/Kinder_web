/* Lab › Special Run › Lens Simulator (special_run_lens_sim.html): strong lensing ray-traced in the browser.
   For every image-plane pixel θ the source is sampled at β = θ − α(θ). Lens: point mass, or SIE (Kormann et al.
   1994 normalisation, tiny core) with external shear. Source: Sérsic, clumpy (Sérsic + knots) or a point (quasar / SN).
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
                 fov: 'auto', seeing: 0, crit: true, caus: true};
    const PRESETS = [
        ['Galaxy–galaxy lens (SLACS-like)', {}],
        ['Cosmic Horseshoe (SDSS J1148+1930)', {logm: logMOfSigma(500), zl: 0.444, zs: 2.379, q: 0.85, pa: 100, gamma: 0.02,
            src: 'clumpy', re: 1.6, sq: 0.8, bx: 0.04, by: 0.06, light: 0.6}],
        ['8 o\'clock arc (SDSS J0022+1431)', {logm: logMOfSigma(380), zl: 0.38, zs: 2.73, q: 0.75, pa: 40, gamma: 0.05,
            src: 'clumpy', re: 1.2, sq: 0.6, bx: 0.25, by: 0.12, light: 0.8}],
        ['Abell 370 giant arc (cluster)', {logm: logMOfSigma(1500), zl: 0.375, zs: 0.725, q: 0.65, pa: 100, gamma: 0.06, gpa: 10,
            src: 'clumpy', re: 8, sq: 0.5, spa: 10, bx: 0, by: 0.25, light: 0.35, n: 1}],
        ['MACS J0717 (most massive cluster lens)', {logm: logMOfSigma(1750), zl: 0.546, zs: 2.5, q: 0.6, pa: 135, gamma: 0.08,
            src: 'clumpy', re: 6, sq: 0.6, spa: 45, bx: 0, by: 0.22, light: 0.3}],
        ['Einstein Cross (Q2237+0305)', {logm: logMOfSigma(215), zl: 0.0394, zs: 1.695, q: 0.75, pa: 70, gamma: 0.01,
            src: 'point', bx: 0.03, by: 0.02, light: 1}],
        ['Twin Quasar (Q0957+561)', {logm: logMOfSigma(450), zl: 0.36, zs: 1.41, q: 0.8, pa: 60, gamma: 0.2, gpa: 70,
            src: 'point', bx: 0.35, by: 0.15, light: 0.8}],
        ['Lensed supernova (iPTF16geu-like)', {logm: logMOfSigma(160), zl: 0.216, zs: 0.409, q: 0.8, pa: 50, gamma: 0.05,
            src: 'point', bx: 0.05, by: 0.04, light: 1}],
        ['Point-mass lens (idealised)', {model: 'pm', logm: 12, zl: 0.5, zs: 2, gamma: 0, src: 'galaxy', re: 0.8,
            bx: 0.2, by: 0, light: 0}],
    ];
    let S = {...DEF};

    /* ------------------------------------------------------------ controls */
    const sliders = {logm: 'lsLogM', zl: 'lsZl', q: 'lsQ', pa: 'lsPa', gamma: 'lsGamma', gpa: 'lsGpa', light: 'lsLight',
                     zs: 'lsZs', re: 'lsRe', n: 'lsN', sq: 'lsSq', spa: 'lsSpa', bx: 'lsBx', by: 'lsBy', seeing: 'lsSeeing'};
    const fmt = {
        logm: (v) => `${(10 ** v).toExponential(1).replace('e+', '×10^')} M☉`.replace(/\^(\d+)/, (_, e) => sup(e)),
        zl: (v) => v.toFixed(3), zs: (v) => v.toFixed(3), q: (v) => v.toFixed(2), pa: (v) => `${v}°`, gpa: (v) => `${v}°`,
        gamma: (v) => v.toFixed(3), light: (v) => v.toFixed(2), re: (v) => `${v.toFixed(2)} kpc`, n: (v) => v.toFixed(1),
        sq: (v) => v.toFixed(2), spa: (v) => `${v}°`, bx: (v) => v.toFixed(3), by: (v) => v.toFixed(3),
        seeing: (v) => (v ? `${v.toFixed(2)}″` : 'off'),
    };
    function sup(e) { return String(e).replace(/\d/g, (d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[d]); }

    PRESETS.forEach(([name], i) => $('lsPreset').insertAdjacentHTML('beforeend', `<option value="${i}">${name}</option>`));

    function syncControls() {
        for (const [k, id] of Object.entries(sliders)) {
            $(id).value = S[k];
            const out = document.querySelector(`[data-out="${k}"]`);
            if (out) out.textContent = fmt[k](S[k]);
        }
        $('lsFov').value = String(S.fov);
        $('lsCrit').checked = S.crit;
        $('lsCaus').checked = S.caus;
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
            if (k === 'zl' && S.zs <= S.zl + 0.01) S.zs = Math.min(6, S.zl + 0.01);
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
    $('lsPreset').addEventListener('change', () => {
        const p = PRESETS[+$('lsPreset').value];
        if (!p) return;
        S = {...DEF, ...p[1], fov: 'auto', seeing: S.seeing, crit: S.crit, caus: S.caus};
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
        if (S.src === 'point') {
            const sg = Math.max(0.6 * pix, 0.005), k = 1 / (2 * sg * sg);
            return (x, y) => { const dx = x - cx, dy = y - cy; return Math.exp(-(dx * dx + dy * dy) * k); };
        }
        const n = S.src === 'clumpy' ? 1 : S.n, bn = 1.9992 * n - 0.3271, inv = 1 / n;
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

    function blur(a, N, sigPix) {
        if (sigPix < 0.3) return a;
        const R = Math.ceil(3 * sigPix), ker = [];
        let ks = 0;
        for (let i = -R; i <= R; i++) { const w = Math.exp(-i * i / (2 * sigPix * sigPix)); ker.push(w); ks += w; }
        for (let i = 0; i < ker.length; i++) ker[i] /= ks;
        const t = new Float32Array(a.length), o = new Float32Array(a.length);
        for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
            let v = 0;
            for (let k = -R; k <= R; k++) { const xx = Math.min(N - 1, Math.max(0, x + k)); v += a[y * N + xx] * ker[k + R]; }
            t[y * N + x] = v;
        }
        for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
            let v = 0;
            for (let k = -R; k <= R; k++) { const yy = Math.min(N - 1, Math.max(0, y + k)); v += t[yy * N + x] * ker[k + R]; }
            o[y * N + x] = v;
        }
        return o;
    }

    /* ------------------------------------------------------------ render */
    const N = 340;
    const SRC_RGB = [0.45, 0.72, 1.0], LENS_RGB = [1.0, 0.78, 0.5];
    const off = document.createElement('canvas');
    off.width = off.height = N;
    const offCtx = off.getContext('2d');
    let view = null;     // what the last render used (for dragging and overlays)

    function css(name, fb) { return getComputedStyle(page).getPropertyValue(name).trim() || fb; }

    function render() {
        const d = dists(S.zl, S.zs);
        const M = 10 ** S.logm;
        const tE = thetaE(S.model, M, d);
        const kpcL = d.Dl * 1000 / ARC, kpcS = d.Ds * 1000 / ARC;      // kpc per arcsec at the lens / source
        const reArc = S.re / kpcS;
        const fov = S.fov === 'auto' ? niceFov(Math.max(5 * tE, S.src === 'point' ? 0 : 6 * reArc, 0.5)) : S.fov;
        const pix = fov / N;
        const cx = S.bx * tE, cy = S.by * tE;
        const alpha = deflector(tE), src = sourceFn(cx, cy, reArc, pix);
        const reL = Math.max(Math.min(0.6 * tE, 15 / kpcL), 2 * pix), bnL = 7.669;
        const cL = Math.cos(S.pa * Math.PI / 180), sL = Math.sin(S.pa * Math.PI / 180), qL = S.model === 'pm' ? 1 : S.q;

        const img = new Float32Array(N * N), lens = new Float32Array(N * N), plane = new Float32Array(N * N);
        const AX = new Float32Array(N * N), AY = new Float32Array(N * N);
        const a = [0, 0];
        for (let j = 0; j < N; j++) {
            const y = fov / 2 - (j + 0.5) * pix;
            for (let i = 0; i < N; i++) {
                const x = (i + 0.5) * pix - fov / 2, k = j * N + i;
                alpha(x, y, a);
                AX[k] = a[0]; AY[k] = a[1];
                img[k] = src(x - a[0], y - a[1]);
                plane[k] = src(x, y);
                if (S.light > 0) {
                    const xr = cL * x + sL * y, yr = -sL * x + cL * y;
                    const r = Math.sqrt(qL * xr * xr + yr * yr / qL) / reL;
                    lens[k] = S.light * 2.5 * Math.exp(-bnL * (Math.pow(r + 1e-3, 0.25) - 0.18));
                }
            }
        }
        let sumImg = 0, sumSrc = 0, peak = 0;
        for (let k = 0; k < N * N; k++) { sumImg += img[k]; sumSrc += plane[k]; if (plane[k] > peak) peak = plane[k]; }
        const mu = sumSrc > 0 ? sumImg / sumSrc : NaN;
        const sig = S.seeing / 2.3548 / pix;
        const bImg = blur(img, N, sig), bLens = blur(lens, N, sig), bPlane = blur(plane, N, sig);

        // critical curves (det A changes sign between neighbours) and their caustics
        const crit = [], caus = [];
        const det = new Float32Array(N * N);
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

        const norm = peak > 0 ? 1 / peak : 1;
        paint($('lsSrc'), bPlane, null, norm, fov, S.caus ? caus : [], '#ff6b8a', [cx, cy]);
        paint($('lsImg'), bImg, bLens, norm, fov, S.crit ? crit : [], css('--color-accent', '#F39F5A'));
        scaleBar('lsScaleS', fov); scaleBar('lsScaleI', fov);
        view = {fov, tE};
        stats(d, M, tE, kpcL, reArc, mu, fov);
        chart(M);
    }

    function niceFov(v) {
        const steps = [0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 60, 80, 120, 160, 240, 300, 480, 600];
        return steps.find((s) => s >= v) || 600;
    }

    function paint(cv, A, L, norm, fov, pts, col, mark) {
        const data = offCtx.createImageData(N, N), px = data.data, soft = 0.06, den = Math.asinh(1 / soft);
        for (let k = 0; k < N * N; k++) {
            const s = Math.min(1, Math.asinh(A[k] * norm / soft) / den);
            const l = L ? Math.min(1, Math.asinh(L[k] / soft) / den) : 0;
            px[4 * k] = 255 * Math.min(1, s * SRC_RGB[0] + l * LENS_RGB[0]);
            px[4 * k + 1] = 255 * Math.min(1, s * SRC_RGB[1] + l * LENS_RGB[1]);
            px[4 * k + 2] = 255 * Math.min(1, s * SRC_RGB[2] + l * LENS_RGB[2]);
            px[4 * k + 3] = 255;
        }
        offCtx.putImageData(data, 0, 0);
        const dpr = window.devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr) || 420;
        if (cv.width !== W) { cv.width = W; cv.height = W; }
        const ctx = cv.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(off, 0, 0, W, W);
        const toPx = (x, y) => [(x / fov + 0.5) * W, (0.5 - y / fov) * W];
        ctx.fillStyle = col;
        const r = Math.max(1, dpr * 0.9);
        for (const [x, y] of pts) {
            const [u, v] = toPx(x, y);
            if (u >= 0 && u < W && v >= 0 && v < W) ctx.fillRect(u - r / 2, v - r / 2, r, r);
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

    function stats(d, M, tE, kpcL, reArc, mu, fov) {
        const sigCr = d.Ds / (4 * Math.PI * G_C2 * d.Dl * d.Dls) / 1e12;       // M☉ / pc²
        const RE = tE * kpcL;                                                   // kpc
        const ME = sigCr * 1e6 * Math.PI * RE * RE;                             // M☉ (Σcr in M☉/kpc² × area)
        const rows = [
            ['Einstein radius θ<sub>E</sub>', `${num(tE)}″`, true],
            ['Physical R<sub>E</sub>', `${num(RE)} kpc`, true],
            ['Magnification μ', `${num(mu, 1)}×`, true],
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
