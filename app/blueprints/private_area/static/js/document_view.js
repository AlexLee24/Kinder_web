// One document (document_view.html): render the Markdown, build the contents list from its headings,
// highlight the section being read, show reading progress / time left, and zoom images.
(function () {
    'use strict';
    const root = document.getElementById('docRead');
    const body = document.getElementById('docBody');
    if (!root || !body) return;
    const filename = root.dataset.filename;
    const title = (root.dataset.title || '').trim();
    const minutes = Number(root.dataset.minutes) || 1;

    const render = (md) => {
        if (window.marked && window.DOMPurify) body.innerHTML = DOMPurify.sanitize(marked.parse(md || ''));
        else body.textContent = md || '';
    };

    const slug = (text, used) => {
        let s = text.toLowerCase().trim().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '') || 'section';
        let out = s, n = 2;
        while (used.has(out)) out = `${s}-${n++}`;
        used.add(out);
        return out;
    };

    function buildToc() {
        // The first heading repeats the title shown above it: drop it.
        const first = body.firstElementChild;
        if (first && /^H1$/.test(first.tagName) && first.textContent.trim() === title) first.remove();
        const heads = [...body.querySelectorAll('h1, h2, h3')];
        const top = heads.some((h) => h.tagName === 'H1') ? ['H1', 'H2'] : ['H2', 'H3'];
        const used = new Set();
        const items = heads.filter((h) => top.includes(h.tagName)).map((h) => {
            h.id = h.id || slug(h.textContent, used);
            return { id: h.id, text: h.textContent.trim(), sub: h.tagName === top[1] };
        });
        if (items.length < 2) return [];
        const html = items.map((it) => `<li class="${it.sub ? 'l3' : 'l2'}"><a href="#${encodeURIComponent(it.id)}" data-toc="${it.id}"></a></li>`).join('');
        for (const id of ['docToc', 'docTocMobile']) {
            const ol = document.getElementById(id);
            ol.innerHTML = html;
            ol.querySelectorAll('a').forEach((a, i) => { a.textContent = items[i].text; });
        }
        document.getElementById('docRail').hidden = false;
        document.getElementById('docTocM').hidden = false;
        document.getElementById('docTocN').textContent = items.length;
        return items.map((it) => document.getElementById(it.id));
    }

    function track(heads) {
        const bar = document.getElementById('docProgress');
        const left = document.getElementById('docLeft');
        const links = [...document.querySelectorAll('[data-toc]')];
        let raf = 0;
        const update = () => {
            raf = 0;
            const r = body.getBoundingClientRect();
            const total = Math.max(1, r.height - window.innerHeight * 0.6);
            const done = Math.min(1, Math.max(0, -r.top / total));
            bar.style.width = `${(done * 100).toFixed(1)}%`;
            if (left) {
                const m = Math.ceil(minutes * (1 - done));
                left.textContent = done >= 0.98 ? 'Finished' : `About ${m} min left`;
            }
            let on = null;
            for (const h of heads) if (h.getBoundingClientRect().top < 140) on = h.id;
            links.forEach((a) => a.classList.toggle('is-on', a.dataset.toc === on));
        };
        const ask = () => { if (!raf) raf = requestAnimationFrame(update); };
        window.addEventListener('scroll', ask, { passive: true });
        window.addEventListener('resize', ask);
        update();
    }

    // Close the phone contents block after a jump.
    document.getElementById('docTocMobile').addEventListener('click', (e) => {
        if (e.target.closest('a')) document.getElementById('docTocM').open = false;
    });

    // Images: click to see them full size.
    const box = document.getElementById('docLightbox');
    document.addEventListener('click', (e) => {
        const img = e.target.closest('.doc-md img, img[data-zoom]');
        if (img && box && box.showModal) {
            box.querySelector('img').src = img.currentSrc || img.src;
            box.showModal();
            return;
        }
        if (e.target.closest('#docLightbox')) box.close();
    });

    (async () => {
        try {
            const resp = await fetch(`/api/documents/${encodeURIComponent(filename)}/content`);
            const data = await resp.json();
            if (!resp.ok || !data.success) throw new Error(data.error || 'Could not load the document');
            render(data.content);
            const heads = buildToc();
            track(heads);
            if (location.hash) {
                const t = document.getElementById(decodeURIComponent(location.hash.slice(1)));
                if (t) t.scrollIntoView();
            }
        } catch (e) {
            body.innerHTML = '';
            const p = document.createElement('p');
            p.className = 'doc-loading';
            p.textContent = e.message;
            body.appendChild(p);
        }
    })();
})();
