/* window.FitsStretch: draw raw float32 images (Euclid cutouts) on a <canvas> with an astronomer's stretch.
   Used by Tools › Euclid (astronomy_tools/static/js/euclid_compare.js) and Lab › Special Run › Euclid-SLSN.

   Settings object S (all optional, see DEFAULTS):
     mode     'stf' (PixInsight Screen Transfer Function / Siril autostretch) | 'asinh' | 'log' | 'sqrt' | 'linear'
     shadows  STF shadows clip in MAD-σ from the median (−2.8 = PixInsight / Siril default)
     target   STF target background (0.25 default)
     black, white  percentiles for the other modes;  soft  asinh / log softening
     cmap     'gray' | 'inferno' | 'viridis' | 'cubehelix';  invert;  linked (RGB: one transfer for the 3 channels)
     marker   draw the target cross
   An image is {w, h, data: Float32Array (FITS order, row 0 = bottom)}; its statistics are cached on it. */
(() => {
    const DEFAULTS = {mode: 'stf', shadows: -2.8, target: 0.25, black: 1.0, white: 99.8, soft: 0.05,
                      cmap: 'gray', invert: false, linked: false, marker: true};

    const STOPS = {
        gray: [[0, 0, 0], [255, 255, 255]],
        inferno: [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]],
        viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
        cubehelix: [[0, 0, 0], [22, 66, 59], [161, 121, 74], [194, 168, 236], [255, 255, 255]],
    };
    const lutCache = new Map();
    function lut(name, invert) {
        const key = `${name}|${invert ? 1 : 0}`;
        if (lutCache.has(key)) return lutCache.get(key);
        const st = STOPS[name] || STOPS.gray, out = new Uint8ClampedArray(256 * 3);
        for (let i = 0; i < 256; i++) {
            const v = (invert ? 255 - i : i) / 255 * (st.length - 1), k = Math.min(Math.floor(v), st.length - 2), f = v - k;
            for (let c = 0; c < 3; c++) out[i * 3 + c] = st[k][c] + (st[k + 1][c] - st[k][c]) * f;
        }
        lutCache.set(key, out);
        return out;
    }

    /* Midtones transfer function: m → 0.5, 0 → 0, 1 → 1 */
    const mtf = (m, x) => ((m - 1) * x) / ((2 * m - 1) * x - m);

    function stats(img) {   // finite range + sorted sample (≤ 60k px) for medians / percentiles, cached on img
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
        if (!sample.length) { lo = 0; hi = 1; sample.push(0); }
        const sorted = Float64Array.from(sample).sort();
        const q = (p) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p / 100 * (sorted.length - 1))))];
        const med = q(50);
        const dev = Float64Array.from(sorted, (v) => Math.abs(v - med)).sort();
        img.stats = {lo, hi, med, mad: 1.4826 * dev[Math.floor(dev.length / 2)], q};
        return img.stats;
    }

    /* value → [0, 1] for the settings */
    function transfer(img, S) {
        const {lo, hi, med, mad, q} = stats(img);
        const span = Math.max(hi - lo, 1e-30);
        if (S.mode === 'stf') {
            const xm = (med - lo) / span, xs = mad / span;
            const c0 = Math.min(Math.max(xm + S.shadows * xs, 0), 1);
            const m = mtf(S.target, Math.max(xm - c0, 1e-6));
            return (v) => mtf(m, Math.min(Math.max(((v - lo) / span - c0) / (1 - c0), 0), 1));
        }
        const b = q(S.black), w = Math.max(q(S.white), b + 1e-30);
        const lin = (v) => Math.min(Math.max((v - b) / (w - b), 0), 1);
        if (S.mode === 'asinh') { const k = Math.asinh(1 / S.soft); return (v) => Math.asinh(lin(v) / S.soft) / k; }
        if (S.mode === 'log') { const k = Math.log1p(1 / S.soft); return (v) => Math.log1p(lin(v) / S.soft) / k; }
        if (S.mode === 'sqrt') return (v) => Math.sqrt(lin(v));
        return lin;
    }

    function drawMarker(ctx, x, y, size, color) {
        const gap = size * 0.035, arm = size * 0.07;
        ctx.lineWidth = Math.max(1.5, size / 160);
        ctx.strokeStyle = color;
        ctx.beginPath();
        ctx.moveTo(x + gap, y); ctx.lineTo(x + gap + arm, y);
        ctx.moveTo(x, y - gap); ctx.lineTo(x, y - gap - arm);
        ctx.stroke();
    }

    /* chans: 1 image (colour map) or 3 images (R, G, B). mark: {x, y} in FITS pixels (or null). */
    function paint(canvas, chans, S, mark, accent) {
        S = {...DEFAULTS, ...S};
        const w = Math.min(...chans.map((c) => c.w)), h = Math.min(...chans.map((c) => c.h));
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d'), im = ctx.createImageData(w, h), px = im.data;
        if (chans.length === 1) {
            const f = transfer(chans[0], S), L = lut(S.cmap, S.invert), d = chans[0].data, cw = chans[0].w;
            for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
                const v = d[y * cw + x], t = Number.isFinite(v) ? Math.round(255 * f(v)) : 0, o = ((h - 1 - y) * w + x) * 4;
                px[o] = L[t * 3]; px[o + 1] = L[t * 3 + 1]; px[o + 2] = L[t * 3 + 2]; px[o + 3] = 255;
            }
        } else {
            let fs;
            if (S.linked) {
                if (!chans.linkedRef) {
                    chans.linkedRef = {w: chans[0].w, h: chans[0].h,
                                       data: chans[0].data.map((v, i) => (v + chans[1].data[i] + chans[2].data[i]) / 3)};
                }
                const f = transfer(chans.linkedRef, S); fs = [f, f, f];
            } else fs = chans.map((c) => transfer(c, S));
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
        if (mark && S.marker && mark.x != null && mark.y != null) {
            drawMarker(ctx, mark.x, h - 1 - mark.y, h, S.cmap === 'gray' ? (accent || '#F39F5A') : '#33e6ff');
        }
    }

    window.FitsStretch = {DEFAULTS, lut, stats, transfer, paint, drawMarker, mtf};
})();
