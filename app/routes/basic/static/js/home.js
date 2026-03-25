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

