document.addEventListener('DOMContentLoaded', () => {
    const meta = document.getElementById('documentMeta');
    const contentDiv = document.getElementById('content');
    const editor = document.getElementById('markdownEditor');
    const editorHint = document.getElementById('editorHint');
    const toggleEditBtn = document.getElementById('toggleEditBtn');
    const saveBtn = document.getElementById('saveDocBtn');
    const cancelBtn = document.getElementById('cancelEditBtn');
    const statusText = document.getElementById('docStatusText');
    const editToggle = document.getElementById('documentsEditableToggle');

    if (!meta || !contentDiv) return;

    const filename = meta.dataset.filename;
    const isAdmin = meta.dataset.isAdmin === 'true';
    let editable = meta.dataset.editable === 'true';

    let markdownText = '';
    let rawMarkdownText = '';

    const setStatus = (text, isError = false) => {
        if (!statusText) return;
        statusText.textContent = text;
        statusText.style.color = isError ? '#ff7b72' : '#98a2b3';
    };

    if (editToggle) {
        editToggle.addEventListener('change', async () => {
            const isChecked = editToggle.checked;
            try {
                const resp = await fetch('/api/documents/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        documents_editable: isChecked,
                        important_message: ''
                    })
                });
                const data = await resp.json();
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Failed to update settings');
                }
                editable = isChecked;
                if (toggleEditBtn) toggleEditBtn.disabled = !editable;
                if (!editable && editing) {
                    switchMode(false);
                }
                setStatus('Settings updated.', false);
            } catch (err) {
                editToggle.checked = !isChecked; 
                setStatus(err.message, true);
            }
        });
    }

    const renderMarkdown = () => {
        contentDiv.innerHTML = marked.parse(markdownText || '');
    };

    const switchMode = (enableEdit) => {
        editing = enableEdit;
        
        const editorContainer = document.getElementById('editorContainer');
        if (editorContainer) {
            editorContainer.style.display = enableEdit ? 'flex' : 'none';
        } else if (editor) {
            editor.style.display = enableEdit ? 'block' : 'none';
        }
        
        contentDiv.style.display = enableEdit ? 'none' : 'block';
        if (editorHint) editorHint.style.display = enableEdit ? 'block' : 'none';

        if (toggleEditBtn) toggleEditBtn.style.display = enableEdit ? 'none' : 'inline-block';
        if (saveBtn) saveBtn.style.display = enableEdit ? 'inline-block' : 'none';
        if (cancelBtn) cancelBtn.style.display = enableEdit ? 'inline-block' : 'none';

        if (enableEdit) {
            if (editor) {
                editor.value = rawMarkdownText || markdownText;
                editor.focus();
                const previewPane = document.getElementById('previewPane');
                if (previewPane) {
                    previewPane.innerHTML = marked.parse(editor.value || '');
                }
            }
            setStatus('', false);
        } else {
            setStatus(editable ? '' : 'Editing is disabled by admin setting.', false);
        }
    };

    if (editor) {
        editor.addEventListener('input', () => {
            const previewPane = document.getElementById('previewPane');
            if (previewPane) {
                previewPane.innerHTML = marked.parse(editor.value || '');
            }
        });
    }

    const loadDocument = async () => {
        try {
            const resp = await fetch(`/api/documents/${encodeURIComponent(filename)}/content`);
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Load failed');
            }
            markdownText = data.content || '';
            rawMarkdownText = data.raw_content || markdownText;
            renderMarkdown();
        } catch (err) {
            contentDiv.innerHTML = `
                <div class="loading-doc" style="color: #ef4444;">
                    Error loading document: ${err.message}
                </div>
            `;
            setStatus('Failed to load document.', true);
        }
    };

    const saveDocument = async () => {
        if (!isAdmin || !editable) return;
        if (!editor) return;

        setStatus('Saving...', false);
        try {
            const resp = await fetch(`/api/documents/${encodeURIComponent(filename)}/content`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: editor.value })
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Save failed');
            }
            await loadDocument(); // Reload to get newly parsed markdown (if any new {{hide=...}} added)
            switchMode(false);
            setStatus('Saved.', false);
        } catch (err) {
            setStatus(`Save failed: ${err.message}`, true);
        }
    };

    const uploadPastedImage = async (file, textarea) => {
        const formData = new FormData();
        formData.append('image', file, file.name || 'pasted.png');

        const resp = await fetch('/api/documents/upload-image', {
            method: 'POST',
            body: formData
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.error || 'Upload failed');
        }

        const insertion = `${data.markdown}\n`;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const before = textarea.value.slice(0, start);
        const after = textarea.value.slice(end);
        textarea.value = before + insertion + after;
        const nextCursor = start + insertion.length;
        textarea.selectionStart = nextCursor;
        textarea.selectionEnd = nextCursor;
    };

    if (toggleEditBtn) {
        toggleEditBtn.addEventListener('click', () => {
            if (!editable) {
                setStatus('Editing is disabled by admin setting.', true);
                return;
            }
            switchMode(true);
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', saveDocument);
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            switchMode(false);
        });
    }

    if (editor) {
        editor.addEventListener('paste', async (event) => {
            if (!isAdmin || !editable || !editing) return;
            const items = event.clipboardData?.items || [];
            const imageItem = Array.from(items).find(item => item.type && item.type.startsWith('image/'));
            if (!imageItem) return;

            event.preventDefault();
            const file = imageItem.getAsFile();
            if (!file) return;

            setStatus('Uploading pasted image...', false);
            try {
                await uploadPastedImage(file, editor);
                setStatus('Image uploaded. Markdown inserted.', false);
            } catch (err) {
                setStatus(`Image upload failed: ${err.message}`, true);
            }
        });
    }

    if (!isAdmin) {
        if (statusText) statusText.style.display = 'none';
    }

    loadDocument();
    switchMode(false);
});
