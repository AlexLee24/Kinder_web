/* Lab › Special Run › Lens Simulator — 3D light paths and the teaching guide (special_run_lens_sim.html).
   Thin-lens geometry from the 2D simulator (lens_sim.js hands it over as LensSim.last / the 'lenssim:render' event):
   observer at z = 0, lens plane at z_L, source plane at z = 10, with z_L = 10 (1 − D_ls / D_s) so that a ray through the
   image position θ, bent at the lens, lands exactly on the source position β (β = θ − α, with α = α̂ D_ls / D_s).
   Angles are exaggerated (shown in the panel) so the paths are visible. Drawn with a small perspective projection on a
   2D canvas: drag to orbit, wheel to zoom, double-click to reset. */
(() => {
    const page = document.getElementById('lsPage'), cv = document.getElementById('ls3d');
    if (!page || !cv || !window.LensSim) return;
    const $ = (id) => document.getElementById(id);
    const ARC = 206264.806, ZS = 10;
    const COLS = ['#ffd166', '#06d6a0', '#ef476f', '#4cc9f0', '#c77dff', '#f78c6b', '#a7c957'];
    const CAMS = {oblique: {yaw: 58, pitch: 20, dist: 17}, side: {yaw: 90, pitch: 0, dist: 15.5}, observer: {yaw: 0, pitch: 0, dist: 7.5}};
    const O = {rays: true, apparent: true, straight: true, arrows: false, labels: true, noLens: false, play: false};
    let cam = {...CAMS.oblique}, D = window.LensSim.last, t0 = performance.now(), raf = 0;

    /* ------------------------------------------------------------ projection */
    const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
    let W = 0, H = 0, F = 0, eye, R, U, Fw, dpr = 1;
    function setupCamera() {
        dpr = window.devicePixelRatio || 1;
        W = Math.round(cv.clientWidth * dpr); H = Math.round(cv.clientHeight * dpr);
        if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
        const T = cam.yaw === 0 && cam.pitch === 0 ? [0, 0, ZS] : [0, 0, ZS / 2];
        const y = cam.yaw * Math.PI / 180, p = cam.pitch * Math.PI / 180;
        eye = cam.yaw === 0 && cam.pitch === 0 ? [0, 0, -cam.dist + 7] :
            [T[0] + cam.dist * Math.sin(y) * Math.cos(p), T[1] + cam.dist * Math.sin(p), T[2] - cam.dist * Math.cos(y) * Math.cos(p)];
        Fw = norm(sub(T, eye)); R = norm(cross([0, 1, 0], Fw)); U = cross(Fw, R);
        F = Math.min(W, H) * (cam.yaw === 0 && cam.pitch === 0 ? 1.9 : 1.15);
    }
    function P(p) {   // world → screen [x, y, depth]
        const v = sub(p, eye), z = dot(v, Fw);
        if (z < 0.05) return null;
        return [W / 2 + F * dot(v, R) / z, H / 2 - F * dot(v, U) / z, z];
    }

    /* ------------------------------------------------------------ scene */
    function geom() {
        const zL = Math.max(0.15, ZS * (1 - D.Dls / D.Ds));
        const s = 0.42 / (D.fov / 2);                      // slope per arcsec (the angle exaggeration)
        return {zL, s, L: (x, y) => [x * s * zL, y * s * zL, zL], Sx: (x, y) => [x * s * ZS, y * s * ZS, ZS]};
    }

    function line(ctx, a, b, col, w, dash) {
        const p = P(a), q = P(b);
        if (!p || !q) return;
        ctx.strokeStyle = col; ctx.lineWidth = w * dpr; ctx.setLineDash(dash ? dash.map((d) => d * dpr) : []);
        ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke(); ctx.setLineDash([]);
    }
    function label(ctx, p3, text, col, dx = 6, dy = -6, size = 12, align = 'left') {
        const p = P(p3);
        if (!p) return;
        ctx.font = `${size * dpr}px system-ui, sans-serif`; ctx.textAlign = align;
        ctx.fillStyle = 'rgba(0,0,0,.55)';
        const w = ctx.measureText(text).width, x = align === 'center' ? p[0] + dx * dpr - w / 2 : p[0] + dx * dpr;
        ctx.fillRect(x - 3 * dpr, p[1] + dy * dpr - 12 * dpr, w + 6 * dpr, 16 * dpr);
        ctx.fillStyle = col; ctx.fillText(text, p[0] + dx * dpr, p[1] + dy * dpr);
    }
    function glow(ctx, p3, rWorld, col, a = 1) {
        const p = P(p3);
        if (!p) return;
        const r = Math.max(2 * dpr, F * rWorld / p[2]);
        const g = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
        g.addColorStop(0, `rgba(${col},${a})`); g.addColorStop(0.35, `rgba(${col},${0.45 * a})`); g.addColorStop(1, `rgba(${col},0)`);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 2 * Math.PI); ctx.fill();
    }
    function plane(ctx, z, h, fill, stroke, n = 6) {
        const c = [[-h, -h, z], [h, -h, z], [h, h, z], [-h, h, z]].map(P);
        if (c.some((q) => !q)) return;
        ctx.fillStyle = fill; ctx.strokeStyle = stroke; ctx.lineWidth = dpr;
        ctx.beginPath(); c.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]))); ctx.closePath(); ctx.fill(); ctx.stroke();
        for (let i = 1; i < n; i++) {   // faint grid
            const t = -h + 2 * h * i / n;
            line(ctx, [t, -h, z], [t, h, z], 'rgba(255,255,255,.05)', 1); line(ctx, [-h, t, z], [h, t, z], 'rgba(255,255,255,.05)', 1);
        }
    }
    const rgb = (c) => c.map((v) => Math.round(255 * v)).join(',');

    // a photon travels source → lens → observer; returns its world position at fraction u of the trip
    function along(path, u) {
        const segs = [], lens = [];
        let tot = 0;
        for (let i = 0; i < path.length - 1; i++) { const l = Math.hypot(...sub(path[i + 1], path[i])); segs.push(l); tot += l; }
        let d = u * tot;
        for (let i = 0; i < segs.length; i++) {
            if (d <= segs[i] || i === segs.length - 1) {
                const f = Math.min(1, d / segs[i]);
                return [0, 1, 2].map((k) => path[i][k] + f * (path[i + 1][k] - path[i][k]));
            }
            d -= segs[i];
        }
        void lens;
        return path[path.length - 1];
    }

    function draw() {
        if (!D) return;
        setupCamera();
        const ctx = cv.getContext('2d'), g = geom(), now = (performance.now() - t0) / 1000;
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#05070c'; ctx.fillRect(0, 0, W, H);
        const hL = (D.fov / 2) * g.s * g.zL, hS = (D.fov / 2) * g.s * ZS;
        const obs = [0, 0, 0], srcW = g.Sx(D.src.x, D.src.y);

        // planes, far one first
        const planes = [[ZS, hS, 'rgba(76,201,240,.06)', 'rgba(76,201,240,.35)'], [g.zL, hL, 'rgba(255,190,120,.06)', 'rgba(255,190,120,.35)']]
            .map((q) => ({q, d: (P([0, 0, q[0]]) || [0, 0, 0])[2]})).sort((a, b) => b.d - a.d);
        for (const {q} of planes) plane(ctx, ...q);

        // source plane: caustics and the source
        if (!O.noLens) for (const [x, y] of D.caus) { const p = P(g.Sx(x, y)); if (p) { ctx.fillStyle = 'rgba(255,107,138,.8)'; ctx.fillRect(p[0] - dpr, p[1] - dpr, 2 * dpr, 2 * dpr); } }
        glow(ctx, srcW, Math.max(0.12, (D.src.re || 0) * g.s * ZS * 2.2), '120,190,255', 1);
        if (D.src.sn) glow(ctx, g.Sx(D.src.sn[0], D.src.sn[1]), 0.08, '255,255,255', 1);

        // lens plane: galaxies, critical curve, deflection arrows
        if (!O.noLens) {
            for (const l of D.lenses) glow(ctx, g.L(l.x, l.y), Math.max(0.05, l.re * g.s * g.zL * 2.5), rgb(l.col), Math.min(1, 0.35 + 0.15 * l.L));
            for (const [x, y] of D.crit) { const p = P(g.L(x, y)); if (p) { ctx.fillStyle = 'rgba(243,159,90,.85)'; ctx.fillRect(p[0] - dpr, p[1] - dpr, 2 * dpr, 2 * dpr); } }
            if (O.arrows) {
                const n = 7, step = D.fov * 0.9 / (n - 1);
                let amax = 1e-9;
                const field = [];
                for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
                    const x = -D.fov * 0.45 + i * step, y = -D.fov * 0.45 + j * step, a = D.defl(x, y);
                    field.push([x, y, a]); amax = Math.max(amax, Math.hypot(a[0], a[1]));
                }
                for (const [x, y, a] of field) {   // a ray through (x, y) is bent towards the mass: −α
                    const k = 0.6 * step / amax, ex = x - a[0] * k, ey = y - a[1] * k;
                    line(ctx, g.L(x, y), g.L(ex, ey), 'rgba(255,224,138,.85)', 1.8);
                    const p = P(g.L(ex, ey)); if (p) { ctx.fillStyle = 'rgba(255,224,138,.9)'; ctx.beginPath(); ctx.arc(p[0], p[1], 2 * dpr, 0, 7); ctx.fill(); }
                }
            }
        }

        // rays
        const paths = [];
        if (O.noLens) {
            paths.push({path: [srcW, obs], col: '#ffd166', delay: 0});
        } else if (D.pts.length) {
            const ims = D.pts.filter((im) => Math.abs(im.mu) > 0.05).sort((a, b) => (a.order || 9) - (b.order || 9));
            const maxDt = Math.max(1e-9, ...ims.map((im) => im.dt));
            ims.forEach((im, i) => {
                const col = COLS[i % COLS.length], onL = g.L(im.x, im.y);
                if (O.apparent) line(ctx, obs, g.Sx(im.x, im.y), 'rgba(160,210,255,.45)', 1, [5, 5]);
                if (O.apparent) glow(ctx, g.Sx(im.x, im.y), 0.09, '160,210,255', 0.55);
                paths.push({path: [srcW, onL, obs], col, delay: im.dt / maxDt, im, onL});
            });
        } else {
            for (const [x, y, bx, by] of D.arcRays) paths.push({path: [g.Sx(bx, by), g.L(x, y), obs], col: 'rgba(255,209,102,.28)', thin: true, delay: Math.random()});
            if (O.apparent) for (const [x, y] of D.arcRays.filter((_, i) => i % 4 === 0)) line(ctx, obs, g.Sx(x, y), 'rgba(160,210,255,.12)', 1, [3, 5]);
        }
        if (O.straight) line(ctx, srcW, obs, 'rgba(200,200,200,.55)', 1.2, [2, 6]);
        if (O.rays) for (const r of paths) {
            line(ctx, r.path[0], r.path[1], r.col, r.thin ? 0.8 : 2);
            if (r.path[2]) line(ctx, r.path[1], r.path[2], r.col, r.thin ? 0.8 : 2);
        }
        for (const r of paths) if (r.onL) { const p = P(r.onL); if (p) { ctx.fillStyle = r.col; ctx.beginPath(); ctx.arc(p[0], p[1], 3.2 * dpr, 0, 7); ctx.fill(); } }

        // photons (source → observer); images with a longer delay leave the same event later
        const arrived = [];
        if (O.play) {
            const trip = 2.6, cycle = trip + 2.2 + 1.2;
            const tc = now % cycle;
            for (const r of paths) {
                if (r.thin && Math.random() > 0.5) continue;
                const u = (tc - (r.thin ? r.delay * trip : r.delay * 2.2)) / trip;
                if (u < 0) continue;
                if (u >= 1) { if (r.im) arrived.push(r); continue; }
                const p = P(along(r.path, u));
                if (p) { ctx.fillStyle = r.thin ? 'rgba(255,240,200,.9)' : '#fff'; ctx.beginPath(); ctx.arc(p[0], p[1], (r.thin ? 1.6 : 3.4) * dpr, 0, 7); ctx.fill(); }
            }
        }

        // observer (not drawn when we look through the observer's own eyes)
        const eyeView = cam.yaw === 0 && cam.pitch === 0;
        if (!eyeView) glow(ctx, obs, 0.18, '120,255,200', 1);
        if (O.labels) {
            if (!eyeView) label(ctx, obs, 'You (observer)', '#9ff5d6', 10, 18);
            label(ctx, [hS, hS, ZS], `Source plane · z = ${D.zs.toFixed(2)}`, '#8fd8ff', -4, -6, 12, 'left');
            if (!O.noLens) label(ctx, [hL, hL, g.zL], `Lens plane · z = ${D.zl.toFixed(2)}`, '#ffc58f', -4, -6, 12, 'left');
            const sv = Math.abs(Math.abs(cam.yaw % 360) - 90) < 25 && Math.abs(cam.pitch) < 20;   // side view only
            if (sv) {   // distances along the line of sight (angular-diameter distances do not add up)
                const y0 = -Math.max(hS, 1) * 1.15;
                line(ctx, [0, y0, 0], [0, y0, ZS], 'rgba(255,255,255,.25)', 1);
                const gp = (d) => (d > 1000 ? `${(d / 1000).toFixed(2)} Gpc` : `${d.toFixed(0)} Mpc`);
                label(ctx, [0, y0, g.zL / 2], `D_l = ${gp(D.Dl)}`, '#ffc58f', 0, 18, 12, 'center');
                label(ctx, [0, y0, (g.zL + ZS) / 2], `D_ls = ${gp(D.Dls)}`, '#ddd', 0, 18, 12, 'center');
                label(ctx, [0, y0 * 1.25, ZS / 2], `D_s = ${gp(D.Ds)}   (D_l + D_ls ≠ D_s in an expanding universe)`, '#8fd8ff', 0, 18, 12, 'center');
            }
            if (!eyeView && !O.noLens && paths[0] && paths[0].onL && !paths[0].thin) {   // name the angles on the brightest image
                const th = along([obs, paths[0].onL], 0.33), be = along([obs, srcW], 0.38);
                label(ctx, th, 'θ — where you see it', '#ffd166', 8, -14, 12);
                label(ctx, be, 'β — where it really is', '#cfcfcf', 8, 26, 12);
                label(ctx, paths[0].onL, 'bent by α̂ here', '#ffe08a', 10, 16, 11);
            }
        }
        if (O.play && arrived.length) {
            ctx.font = `600 ${13 * dpr}px system-ui, sans-serif`; ctx.textAlign = 'left';
            arrived.sort((a, b) => a.delay - b.delay).forEach((r, i) => {
                ctx.fillStyle = r.col;
                ctx.fillText(`● image ${i + 1} arrived${r.im.order > 1 ? `  (+${r.im.dt < 1 ? (r.im.dt * 24).toFixed(1) + ' h' : r.im.dt.toFixed(r.im.dt < 10 ? 1 : 0) + ' d'})` : ''}`, 14 * dpr, (24 + 18 * i) * dpr);
            });
        }
        $('ls3dExag').textContent = `angles shown × ${Math.round(g.s * ARC).toLocaleString()} · distances to scale along the line of sight`;
        if (O.play) { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); }
    }

    /* ------------------------------------------------------------ controls */
    const redraw = () => { if (!O.play) { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); } };
    function syncBar() {
        document.querySelectorAll('[data-cam]').forEach((b) => b.classList.toggle('is-on', CAMS[b.dataset.cam] && CAMS[b.dataset.cam].yaw === cam.yaw && CAMS[b.dataset.cam].pitch === cam.pitch));
        document.querySelectorAll('[data-opt]').forEach((c) => { c.checked = !!O[c.dataset.opt]; });
        $('ls3dPlay').textContent = O.play ? 'Pause photons' : 'Play photons';
    }
    document.querySelectorAll('[data-cam]').forEach((b) => b.addEventListener('click', () => { cam = {...CAMS[b.dataset.cam]}; syncBar(); redraw(); }));
    document.querySelectorAll('[data-opt]').forEach((c) => c.addEventListener('change', () => { O[c.dataset.opt] = c.checked; redraw(); }));
    $('ls3dPlay').addEventListener('click', () => { O.play = !O.play; t0 = performance.now(); syncBar(); draw(); });
    let drag = null;
    cv.addEventListener('pointerdown', (e) => { drag = [e.clientX, e.clientY, cam.yaw, cam.pitch]; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener('pointermove', (e) => {
        if (!drag) return;
        cam.yaw = drag[2] + (e.clientX - drag[0]) * 0.4;
        cam.pitch = Math.max(-80, Math.min(80, drag[3] + (e.clientY - drag[1]) * 0.3));
        syncBar(); redraw();
    });
    cv.addEventListener('pointerup', () => { drag = null; });
    cv.addEventListener('wheel', (e) => { e.preventDefault(); cam.dist = Math.max(4, Math.min(40, cam.dist * (e.deltaY > 0 ? 1.08 : 0.93))); redraw(); }, {passive: false});
    cv.addEventListener('dblclick', () => { cam = {...CAMS.oblique}; syncBar(); redraw(); });
    page.addEventListener('lenssim:render', (e) => { D = e.detail; redraw(); });
    window.addEventListener('resize', redraw);

    /* ------------------------------------------------------------ teaching guide */
    // preset indices follow lens_sim.js PRESETS
    const STEPS = [
        {t: 'Light travels in straight lines', preset: 0, patch: {src: 'point', bx: 0.8, by: 0.3, mag: 21}, o: {noLens: true, arrows: false, play: true}, cam: 'side',
         b: 'With nothing in the way, light from a distant source reaches us along one straight line (grey dashed). Press <b>Next</b> to put a galaxy in its path.'},
        {t: 'Mass bends light', preset: 0, patch: {src: 'point', bx: 0.6, by: 0, q: 0.97, gamma: 0, mag: 21}, o: {noLens: false, arrows: true, play: false}, cam: 'oblique',
         b: 'Mass curves space-time, so a ray passing a galaxy is bent towards it by α̂ = 4GM/(c²b) — twice the Newtonian value. The yellow arrows on the lens plane show the bend a ray would get at each point: larger close to the centre.'},
        {t: 'Two paths, two images', preset: 0, patch: {src: 'point', bx: 0.6, by: 0, q: 0.97, gamma: 0, mag: 21}, o: {arrows: false}, cam: 'observer',
         b: 'Two different paths reach your eye, one on each side of the lens. You see the source in the direction each ray arrives from (dashed blue), not where it really is: two images at angles θ₁ and θ₂, while the true direction is β. Drag the source in the 2D source-plane panel above and watch both paths move.'},
        {t: 'Perfect alignment: the Einstein ring', preset: 0, patch: {src: 'galaxy', re: 0.8, bx: 0, by: 0, q: 0.98, gamma: 0, mag: 21.5}, o: {apparent: true}, cam: 'oblique',
         b: 'When source, lens and observer line up exactly, every direction around the lens works: the rays form a cone and the image becomes a ring of radius θ<sub>E</sub>, the Einstein radius. θ<sub>E</sub> measures the mass inside the ring.'},
        {t: 'An elliptical lens: four images', preset: 0, patch: {src: 'point', q: 0.7, gamma: 0.05, bx: 0.06, by: 0.04, mag: 21}, o: {}, cam: 'observer',
         b: 'An elliptical lens has a diamond-shaped caustic in the source plane (pink). A source inside the diamond gives four bright images (plus a very faint one in the centre); outside it, two. Drag the source across the caustic in the 2D panel: images appear or merge in pairs on the critical curve (orange).'},
        {t: 'Arcs from an extended galaxy', preset: 1, patch: {}, o: {}, cam: 'oblique',
         b: 'A real background galaxy is extended. The parts lying close to the caustic are stretched along the critical curve into arcs: magnified a lot along the arc, hardly at all across it. This is the Cosmic Horseshoe.'},
        {t: 'Distances matter', preset: 3, patch: {}, o: {labels: true}, cam: 'side',
         b: 'θ<sub>E</sub> = √(4GM/c² · D<sub>ls</sub>/(D<sub>l</sub>D<sub>s</sub>)). Move z<sub>l</sub> and z<sub>s</sub> on the left and watch the chart below the stats: the same mass makes the biggest ring when the lens sits roughly half-way. These are angular-diameter distances, so D<sub>l</sub> + D<sub>ls</sub> ≠ D<sub>s</sub>.'},
        {t: 'Time delays', preset: 7, patch: {showDelays: true}, o: {play: true}, cam: 'oblique',
         b: 'The paths have different lengths and pass through different depths of the gravitational potential, so the images of one supernova appear at different times (labels on the observed image). Measured delays plus a lens model give the Hubble constant (Refsdal 1964): SN 2025wny gave H₀ ≈ 67–71 km/s/Mpc.'},
        {t: 'Surface brightness is conserved', preset: 1, patch: {}, o: {play: false}, cam: 'observer',
         b: 'Lensing moves and stretches light but never makes a patch of sky brighter per arcsec². An arc is brighter in total only because it is bigger. Compare the source plane and the arc above: same colour, same surface brightness.'},
        {t: 'What a telescope sees', preset: 7, patch: {tel: 'lot', band: 'r', seeing: 1.3, exp: 3.556}, o: {}, cam: 'observer',
         b: 'Everything above assumes perfect optics. Through the atmosphere (≈ 1.3″ seeing at Lulin) images closer than about 1″ blend into one blob. Switch the Telescope panel to HST or JWST to see them separate again.'},
    ];
    let step = -1;
    $('lsGuideList').innerHTML = STEPS.map((s, i) => `<button type="button" class="ls-step" data-step="${i}"><span>${i + 1}</span>${s.t}</button>`).join('');
    function go(i) {
        step = Math.max(0, Math.min(STEPS.length - 1, i));
        const s = STEPS[step];
        window.LensSim.preset(s.preset);
        if (Object.keys(s.patch).length) window.LensSim.apply(s.patch);
        Object.assign(O, {noLens: false, arrows: false, apparent: true, rays: true, straight: true, labels: true, play: false}, s.o);
        cam = {...CAMS[s.cam]}; t0 = performance.now();
        $('lsGuideTitle').textContent = `${step + 1}. ${s.t}`;
        $('lsGuideBody').innerHTML = s.b;
        $('lsGuidePrev').disabled = step === 0; $('lsGuideNext').disabled = step === STEPS.length - 1;
        document.querySelectorAll('.ls-step').forEach((b) => b.classList.toggle('is-on', +b.dataset.step === step));
        syncBar();
        if (O.play) draw(); else redraw();
        $('ls3dPanel').scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
    document.querySelectorAll('.ls-step').forEach((b) => b.addEventListener('click', () => go(+b.dataset.step)));
    $('lsGuidePrev').addEventListener('click', () => go(step - 1));
    $('lsGuideNext').addEventListener('click', () => go(step + 1));

    syncBar();
    redraw();
})();
