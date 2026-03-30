document.addEventListener('DOMContentLoaded', function () {
    // Email obfuscation
    const emailElement = document.getElementById('obfuscated-email');
    if (emailElement) {
        const user = emailElement.getAttribute('data-user');
        const domain = emailElement.getAttribute('data-domain');
        emailElement.textContent = user + '@' + domain;
    }

    // Slideshow
    const imgEl = document.querySelector('.slideshow-img');
    const titleEl = document.querySelector('.slide-title');
    const captionEl = document.querySelector('.slide-caption');
    const authorEl = document.querySelector('.slide-author');
    const textCardEl = document.querySelector('.slide-text-card');
    const dotsEl = document.querySelector('.slide-dots');

    if (!imgEl) return;

    let slides = [];
    let currentIndex = 0;
    let intervalId = null;
    let intervalMs = 6500;
    let transitionMs = 500;

    function buildDots() {
        dotsEl.innerHTML = '';
        slides.forEach((_, i) => {
            const dot = document.createElement('span');
            dot.className = 'slide-dot' + (i === currentIndex ? ' active' : '');
            dot.addEventListener('click', () => goTo(i));
            dotsEl.appendChild(dot);
        });
    }

    function updateDots() {
        const dots = dotsEl.querySelectorAll('.slide-dot');
        dots.forEach((d, i) => d.classList.toggle('active', i === currentIndex));
    }

    function applySlide(index) {
        imgEl.style.opacity = '0';
        if (textCardEl) textCardEl.style.opacity = '0';

        setTimeout(() => {
            const slide = slides[index];
            imgEl.src = slide.url;
            if (titleEl) titleEl.textContent = slide.title || '';
            if (captionEl) captionEl.textContent = slide.caption || '';
            if (authorEl) {
                authorEl.textContent = slide.author ? '\u00a9 ' + slide.author : '';
                authorEl.style.display = slide.author ? '' : 'none';
            }

            // fit=true: cover (fill box, no transparent areas)
            // fit=false: contain (keep aspect ratio, may show transparent bg)
            imgEl.style.objectFit = slide.fit ? 'cover' : 'contain';

            // Hide text card if title, caption and author are all empty
            const hasText = slide.title || slide.caption || slide.author;
            if (textCardEl) textCardEl.style.display = hasText ? '' : 'none';

            imgEl.style.opacity = '1';
            if (textCardEl && hasText) textCardEl.style.opacity = '1';
            updateDots();
        }, transitionMs);
    }

    function goTo(index) {
        currentIndex = (index + slides.length) % slides.length;
        applySlide(currentIndex);
    }

    function next() {
        goTo(currentIndex + 1);
    }

    function startInterval() {
        if (intervalId) clearInterval(intervalId);
        intervalId = setInterval(next, intervalMs);
    }

    fetch('/api/slideshow')
        .then(r => r.json())
        .then(data => {
            slides = data.slides || [];
            intervalMs = data.interval || 6500;
            transitionMs = data.transition || 500;

            if (slides.length === 0) {
                imgEl.style.display = 'none';
                if (textCardEl) textCardEl.style.display = 'none';
                if (dotsEl) dotsEl.style.display = 'none';
                return;
            }

            // Preload images
            slides.forEach(s => { const i = new Image(); i.src = s.url; });

            // Show first slide immediately
            const first = slides[0];
            imgEl.src = first.url;
            if (titleEl) titleEl.textContent = first.title || '';
            if (captionEl) captionEl.textContent = first.caption || '';
            if (authorEl) {
                authorEl.textContent = first.author ? '\u00a9 ' + first.author : '';
                authorEl.style.display = first.author ? '' : 'none';
            }
            imgEl.style.objectFit = first.fit ? 'cover' : 'contain';
            const firstHasText = first.title || first.caption || first.author;
            if (textCardEl) textCardEl.style.display = firstHasText ? '' : 'none';
            imgEl.style.opacity = '1';
            if (textCardEl && firstHasText) textCardEl.style.opacity = '1';

            buildDots();

            if (slides.length > 1) {
                startInterval();
            }
        })
        .catch(() => {
            // Fail silently — hide slideshow area
            if (imgEl) imgEl.style.display = 'none';
            if (textCardEl) textCardEl.style.display = 'none';
            if (dotsEl) dotsEl.style.display = 'none';
        });
});

// ============================================================
// Meteor shower — canvas overlay on .main-banner
// ============================================================
(function initMeteorShower() {
    const banner = document.querySelector('.main-banner');
    if (!banner) return;

    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;z-index:1;pointer-events:none;';
    banner.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    let W, H;

    function resize() {
        W = banner.offsetWidth;
        H = banner.offsetHeight;
        canvas.width = W;
        canvas.height = H;
    }
    resize();
    window.addEventListener('resize', resize);

    const meteors = [];
    let nextSpawnAt = 0;

    // ---- Spawn interval: MIN_SPAWN ~ MAX_SPAWN ms between meteors ----
    const MIN_SPAWN = 10000;
    const MAX_SPAWN = 300000;
    // ---- Sky boundary: meteors fully fade out before this Y fraction ----
    const SKY_FADE_START = 0.35; // begin fading at 35% height
    const SKY_FADE_END   = 0.52; // fully gone by 52% height

    function spawnMeteor(now) {
        // Angle: 30–50° below horizontal, traveling left-downward
        const angleDeg = 30 + Math.random() * 20;
        const angleRad = angleDeg * Math.PI / 180;
        const speed = 7 + Math.random() * 8;
        const length = 100 + Math.random() * 160;
        const maxOpacity = 0.45 + Math.random() * 0.45;
        const lineWidth = 1.4 + Math.random() * 1.0;

        // velocity: left (negative x) and down (positive y)
        const vx = -Math.cos(angleRad) * speed;
        const vy = Math.sin(angleRad) * speed;

        // Spawn: 70% from top edge, 30% from right edge (upper 30% only)
        let x0, y0;
        if (Math.random() < 0.7) {
            x0 = W * 0.2 + Math.random() * W * 0.8;
            y0 = -length * Math.sin(angleRad) - 5;
        } else {
            x0 = W + length * Math.cos(angleRad) + 5;
            y0 = Math.random() * H * 0.30;  // right-edge spawns only in top 30%
        }

        const travelDist = Math.sqrt((W + length) * (W + length) + (H + length) * (H + length));
        const life = (travelDist / speed) * (1000 / 60);

        meteors.push({ x0, y0, vx, vy, length, maxOpacity, born: now, life, lineWidth });
        nextSpawnAt = now + MIN_SPAWN + Math.random() * (MAX_SPAWN - MIN_SPAWN);
    }

    function draw(now) {
        ctx.clearRect(0, 0, W, H);

        if (now >= nextSpawnAt) spawnMeteor(now);

        for (let i = meteors.length - 1; i >= 0; i--) {
            const m = meteors[i];
            const age = now - m.born;
            const t = age / m.life;

            if (t >= 1) { meteors.splice(i, 1); continue; }

            const frames = age / (1000 / 60);
            const hx = m.x0 + m.vx * frames;
            const hy = m.y0 + m.vy * frames;

            // Cull once head passes sky boundary or exits left
            if (hy > H * SKY_FADE_END || hx < -80) { meteors.splice(i, 1); continue; }

            // Time-based opacity: fade in 6%, hold, fade out last 20%
            let opacity;
            if (t < 0.06)      opacity = (t / 0.06) * m.maxOpacity;
            else if (t > 0.80) opacity = ((1 - t) / 0.20) * m.maxOpacity;
            else               opacity = m.maxOpacity;

            // Y-based fade: smoothly extinguish as meteor enters lower half
            if (hy > H * SKY_FADE_START) {
                const yFade = 1 - (hy - H * SKY_FADE_START) / (H * (SKY_FADE_END - SKY_FADE_START));
                opacity *= Math.max(0, yFade);
            }

            if (opacity <= 0) continue;

            // Tail direction = opposite of velocity
            const tailAngle = Math.atan2(-m.vy, -m.vx);
            const tx = hx + Math.cos(tailAngle) * m.length;
            const ty = hy + Math.sin(tailAngle) * m.length;

            // Gradient: transparent at tail → bright at head
            const grad = ctx.createLinearGradient(tx, ty, hx, hy);
            grad.addColorStop(0,    'rgba(255,255,255,0)');
            grad.addColorStop(0.55, `rgba(200,222,255,${opacity * 0.35})`);
            grad.addColorStop(1,    `rgba(255,255,255,${opacity})`);

            ctx.beginPath();
            ctx.moveTo(tx, ty);
            ctx.lineTo(hx, hy);
            ctx.strokeStyle = grad;
            ctx.lineWidth = m.lineWidth;
            ctx.lineCap = 'round';
            ctx.stroke();

            // Head glow
            const glowR = 2.5 + m.lineWidth;
            const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, glowR);
            glow.addColorStop(0, `rgba(255,255,255,${opacity})`);
            glow.addColorStop(1, 'rgba(200,220,255,0)');
            ctx.beginPath();
            ctx.arc(hx, hy, glowR, 0, Math.PI * 2);
            ctx.fillStyle = glow;
            ctx.fill();
        }

        requestAnimationFrame(draw);
    }

    nextSpawnAt = performance.now() + 600 + Math.random() * 1200;
    requestAnimationFrame(draw);
})();

