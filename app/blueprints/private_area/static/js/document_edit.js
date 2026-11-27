// Document editor (document_edit.html): live preview, cover upload, paste/drop images into the body, save.
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const wrap = $('docEdit');
    if (!wrap) return;
    const title = $('docTitle'), summary = $('docSummary'), body = $('docBodyInput');
    const status = $('docEditStatus');
    let filename = wrap.dataset.filename || '';
    let dirty = false;
    $('docEditForm').addEventListener('submit', (e) => e.preventDefault());

    const setStatus = (text, isError) => {
        status.textContent = text || '';
        status.classList.toggle('is-error', !!isError);
    };

    // ── Preview ──
    let timer = 0;
    function preview() {
        $('pvTitle').textContent = title.value.trim() || 'Untitled';
        $('pvSummary').textContent = summary.value.trim();
        $('pvSummary').hidden = !summary.value.trim();
        const md = body.value || '';
        $('pvBody').innerHTML = (window.marked && window.DOMPurify) ? DOMPurify.sanitize(marked.parse(md)) : '';
        if (!window.marked) $('pvBody').textContent = md;
        // Same as the reader: a first heading that repeats the title is not shown twice.
        const first = $('pvBody').firstElementChild;
        if (first && first.tagName === 'H1' && first.textContent.trim() === title.value.trim()) first.remove();
    }
    const later = () => { dirty = true; clearTimeout(timer); timer = setTimeout(preview, 120); };
    [title, summary, body].forEach((el) => el.addEventListener('input', later));
    preview();

    // ── Phones: Write / Preview ──
    document.querySelectorAll('.doc-edit-tabs [data-pane]').forEach((b) => b.addEventListener('click', () => {
        wrap.dataset.pane = b.dataset.pane;
        document.querySelectorAll('.doc-edit-tabs [data-pane]').forEach((x) => {
            x.classList.toggle('is-on', x === b);
            x.setAttribute('aria-selected', x === b ? 'true' : 'false');
        });
        if (b.dataset.pane === 'preview') preview();
    }));

    // ── Images ──
    async function upload(file) {
        const fd = new FormData();
        fd.append('image', file, file.name || 'pasted.png');
        const resp = await fetch('/api/documents/upload-image', { method: 'POST', body: fd });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error(data.error || 'Upload failed');
        return data;
    }
    function insertAtCursor(text) {
        const s = body.selectionStart, e = body.selectionEnd;
        body.setRangeText(text, s, e, 'end');
        body.focus();
        later();
    }
    async function addImages(files) {
        for (const f of files) {
            if (!f.type.startsWith('image/')) continue;
            setStatus('Uploading image…');
            try {
                const d = await upload(f);
                insertAtCursor(`\n${d.markdown}\n`);
                setStatus('Image added');
            } catch (err) { setStatus(err.message, true); }
        }
    }
    body.addEventListener('paste', (e) => {
        const files = [...(e.clipboardData?.files || [])];
        if (files.some((f) => f.type.startsWith('image/'))) { e.preventDefault(); addImages(files); }
    });
    body.addEventListener('dragover', (e) => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); });
    body.addEventListener('drop', (e) => {
        const files = [...(e.dataTransfer?.files || [])];
        if (files.length) { e.preventDefault(); addImages(files); }
    });

    const cover = $('docCover'), thumb = $('docCoverThumb'), coverRemove = $('docCoverRemove');
    function showCover(url) {
        cover.value = url || '';
        thumb.innerHTML = '';
        if (url) { const img = document.createElement('img'); img.src = url; img.alt = ''; thumb.appendChild(img); }
        else thumb.textContent = 'None';
        coverRemove.hidden = !url;
        dirty = true;
    }
    $('docCoverFile').addEventListener('change', async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        setStatus('Uploading cover…');
        try { showCover((await upload(f)).image_url); setStatus('Cover added'); } catch (err) { setStatus(err.message, true); }
        e.target.value = '';
    });
    coverRemove.addEventListener('click', () => showCover(''));
    $('docCategory').addEventListener('change', () => { dirty = true; });
    $('docPinned').addEventListener('change', () => { dirty = true; });

    // ── Save ──
    async function save(draft) {
        if (!title.value.trim()) { setStatus('Give the document a title', true); title.focus(); return; }
        setStatus('Saving…');
        $('docSaveDraft').disabled = $('docPublish').disabled = true;
        try {
            const resp = await fetch('/api/documents/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename, draft,
                    title: title.value.trim(), summary: summary.value.trim(), content: body.value,
                    category: $('docCategory').value, cover: cover.value, pinned: $('docPinned').checked,
                }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !data.success) throw new Error(data.error || `Save failed (${resp.status})`);
            dirty = false;
            filename = data.filename;
            if (draft) {
                setStatus('Draft saved');
                if (!wrap.dataset.filename) history.replaceState(null, '', `/documents/${encodeURIComponent(filename)}/edit`);
                wrap.dataset.filename = filename;
            } else {
                location.href = data.url;
            }
        } catch (err) {
            setStatus(err.message, true);
        } finally {
            $('docSaveDraft').disabled = $('docPublish').disabled = false;
        }
    }
    $('docSaveDraft').addEventListener('click', () => save(true));
    $('docPublish').addEventListener('click', () => save(false));
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save(true); }
    });
    window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
})();
