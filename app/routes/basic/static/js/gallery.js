document.addEventListener('DOMContentLoaded', function () {
    const grid = document.getElementById('galleryGrid');
    const lightbox = document.getElementById('lightbox');
    const backdrop = document.getElementById('lightboxBackdrop');
    const lbImg = document.getElementById('lightboxImg');
    const lbTitle = document.getElementById('lightboxTitle');
    const lbCaption = document.getElementById('lightboxCaption');
    const lbAuthor = document.getElementById('lightboxAuthor');
    const btnClose = document.getElementById('lightboxClose');
    const btnPrev = document.getElementById('lightboxPrev');
    const btnNext = document.getElementById('lightboxNext');

    let slides = [];
    let currentIndex = 0;

    // ------------------------------------------------------------------ //
    // Build gallery cards
    // ------------------------------------------------------------------ //
    function buildCards(data) {
        grid.innerHTML = '';
        if (!data.length) {
            grid.innerHTML = '<p style="color:rgba(255,255,255,0.4);text-align:center;grid-column:1/-1;">No images available.</p>';
            return;
        }

        data.forEach((slide, index) => {
            const card = document.createElement('div');
            card.className = 'gallery-card';
            card.setAttribute('role', 'button');
            card.setAttribute('tabindex', '0');
            card.setAttribute('aria-label', slide.title || 'Image ' + (index + 1));

            const thumbWrap = document.createElement('div');
            thumbWrap.className = 'gallery-thumb-wrap';

            const img = document.createElement('img');
            img.className = 'gallery-thumb';
            img.alt = slide.title || '';
            img.loading = 'lazy';
            img.onload = () => img.classList.add('loaded');
            img.src = slide.url;

            thumbWrap.appendChild(img);

            const body = document.createElement('div');
            body.className = 'gallery-card-body';

            if (slide.title) {
                const titleEl = document.createElement('p');
                titleEl.className = 'gallery-card-title';
                titleEl.textContent = slide.title;
                body.appendChild(titleEl);
            }

            if (slide.caption) {
                const capEl = document.createElement('p');
                capEl.className = 'gallery-card-caption';
                capEl.textContent = slide.caption;
                body.appendChild(capEl);
            }

            if (slide.author) {
                const authEl = document.createElement('p');
                authEl.className = 'gallery-card-author';
                authEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>${slide.author}`;
                body.appendChild(authEl);
            }

            card.appendChild(thumbWrap);
            card.appendChild(body);

            card.addEventListener('click', () => openLightbox(index));
            card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openLightbox(index); });

            grid.appendChild(card);
        });
    }

    // ------------------------------------------------------------------ //
    // Lightbox
    // ------------------------------------------------------------------ //
    function openLightbox(index) {
        currentIndex = index;
        renderLightbox(currentIndex, false);
        lightbox.removeAttribute('hidden');
        requestAnimationFrame(() => {
            lightbox.classList.add('visible');
            backdrop.classList.add('visible');
        });
        document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
        lightbox.classList.remove('visible');
        backdrop.classList.remove('visible');
        lightbox.addEventListener('transitionend', () => {
            lightbox.setAttribute('hidden', '');
            document.body.style.overflow = '';
        }, { once: true });
    }

    function renderLightbox(index, animate) {
        const slide = slides[index];
        if (!slide) return;

        if (animate) {
            lbImg.classList.add('fading');
            setTimeout(() => {
                lbImg.src = slide.url;
                lbImg.alt = slide.title || '';
                lbImg.classList.remove('fading');
            }, 250);
        } else {
            lbImg.src = slide.url;
            lbImg.alt = slide.title || '';
        }

        lbTitle.textContent = slide.title || '';
        lbCaption.textContent = slide.caption || '';
        lbAuthor.textContent = slide.author ? '\u00a9 ' + slide.author : '';

        // Show/hide prev/next
        btnPrev.style.display = slides.length > 1 ? '' : 'none';
        btnNext.style.display = slides.length > 1 ? '' : 'none';
    }

    function navigate(dir) {
        currentIndex = (currentIndex + dir + slides.length) % slides.length;
        renderLightbox(currentIndex, true);
    }

    btnClose.addEventListener('click', closeLightbox);
    backdrop.addEventListener('click', closeLightbox);
    btnPrev.addEventListener('click', () => navigate(-1));
    btnNext.addEventListener('click', () => navigate(1));

    document.addEventListener('keydown', e => {
        if (!lightbox.classList.contains('visible')) return;
        if (e.key === 'Escape') closeLightbox();
        if (e.key === 'ArrowLeft') navigate(-1);
        if (e.key === 'ArrowRight') navigate(1);
    });

    // ------------------------------------------------------------------ //
    // Fetch data
    // ------------------------------------------------------------------ //
    fetch('/api/slideshow')
        .then(r => r.json())
        .then(data => {
            slides = data.slides || [];
            buildCards(slides);
        })
        .catch(() => {
            grid.innerHTML = '<p style="color:rgba(255,255,255,0.4);text-align:center;">Failed to load gallery.</p>';
        });
});
