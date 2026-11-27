// Lab Info › Docs feed (documents.html): the ⋯ menu on each card — mark important (pin) and delete.
(function () {
    'use strict';
    const feed = document.getElementById('docFeed');
    if (!feed) return;

    async function post(url, body) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error(data.error || `Request failed (${resp.status})`);
        return data;
    }
    const say = (msg, kind) => (window.showToast ? window.showToast(msg, kind) : alert(msg));

    feed.addEventListener('click', async (ev) => {
        const card = ev.target.closest('.doc-post');
        if (!card) return;
        const name = card.dataset.filename;
        const pin = ev.target.closest('[data-doc-pin]');
        if (pin) {
            try {
                await post(`/api/documents/${encodeURIComponent(name)}/pin`, { pinned: pin.dataset.docPin === '1' });
                location.reload();
            } catch (e) { say(e.message, 'error'); }
            return;
        }
        if (ev.target.closest('[data-doc-delete]')) {
            const title = card.querySelector('.doc-post-title').textContent.trim();
            if (!confirm(`Delete "${title}"?\n\nThe file is moved to tutorials/.trash on the server, so it can still be brought back by hand.`)) return;
            try {
                await post(`/api/documents/${encodeURIComponent(name)}/delete`);
                card.remove();
                if (!feed.children.length) location.reload();
            } catch (e) { say(e.message, 'error'); }
        }
    });

    // One ⋯ menu open at a time; a click elsewhere closes it.
    document.addEventListener('click', (ev) => {
        document.querySelectorAll('.doc-post-actions[open]').forEach((d) => { if (!d.contains(ev.target)) d.open = false; });
    });
})();
