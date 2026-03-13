document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('createDocumentBtn');
    const filenameInput = document.getElementById('newDocumentFilename');
    const message = document.getElementById('documentsAdminMessage');

    const setMessage = (text, isError = false) => {
        if (!message) return;
        message.textContent = text;
        message.style.color = isError ? '#ff7b72' : '#98c379';
    };

    if (createBtn) {
        createBtn.addEventListener('click', async () => {
            const filename = (filenameInput?.value || '').trim();
            if (!filename) {
                setMessage('Please enter a filename.', true);
                return;
            }

            setMessage('Creating document...');
            try {
                const resp = await fetch('/api/documents/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename })
                });
                const data = await resp.json();
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Create failed');
                }
                window.location.href = `/documents/${encodeURIComponent(data.filename)}`;
            } catch (err) {
                setMessage(`Failed to create: ${err.message}`, true);
            }
        });
    }

    // Drag and Drop ordering
    const docList = document.getElementById('docList');
    if (docList) {
        let draggedItem = null;

        docList.addEventListener('dragstart', (e) => {
            const item = e.target.closest('.doc-item');
            if (!item || !item.hasAttribute('draggable')) return;
            draggedItem = item;
            setTimeout(() => item.classList.add('dragging'), 0);
        });

        docList.addEventListener('dragend', (e) => {
            const item = e.target.closest('.doc-item');
            if (item) item.classList.remove('dragging');
            draggedItem = null;
            
            // Allow time for DOM updates before saving
            setTimeout(() => saveOrderAndPinState(), 50);
        });

        docList.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (!draggedItem) return;
            const item = e.target.closest('.doc-item');
            if (!item || item === draggedItem) return;
            
            const rect = item.getBoundingClientRect();
            const offset = rect.y + (rect.height / 2);
            if (e.clientY < offset) {
                docList.insertBefore(draggedItem, item);
            } else {
                docList.insertBefore(draggedItem, item.nextElementSibling);
            }
        });
    }
});

// Toggle pin state
window.togglePin = function(filename, willPin) {
    const docList = document.getElementById('docList');
    if (!docList) return;
    
    const items = Array.from(docList.querySelectorAll('.doc-item'));
    const targetItem = items.find(el => el.dataset.filename === filename);
    if (!targetItem) return;

    // Toggle pin active class based on state (purely visual until reload)
    const btn = targetItem.querySelector('.btn-icon');
    if (btn) {
        if (willPin) {
            btn.classList.add('active');
            btn.setAttribute('onclick', `togglePin('${filename}', false)`);
            btn.title = 'Unpin';
            
            // Add icon to link if doesn't exist
            const link = targetItem.querySelector('a');
            if (link && !link.querySelector('.pin-icon')) {
                link.insertAdjacentHTML('afterbegin', `<svg class="pin-icon" width="16" height="16" viewBox="0 0 24 24" fill="#f6c453" stroke="#f6c453" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.68V6a3 3 0 1 0-6 0v4.68a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"></path></svg>`);
            }
        } else {
            btn.classList.remove('active');
            btn.setAttribute('onclick', `togglePin('${filename}', true)`);
            btn.title = 'Pin to top';
            
            // Remove icon from link
            const pinIcon = targetItem.querySelector('a .pin-icon');
            if (pinIcon) pinIcon.remove();
        }
    }

    // Move pinned to top roughly in UI
    if (willPin) {
        docList.insertBefore(targetItem, docList.firstChild);
    }
    
    saveOrderAndPinState();
};

async function saveOrderAndPinState() {
    const docList = document.getElementById('docList');
    if (!docList) return;
    
    const items = Array.from(docList.querySelectorAll('.doc-item'));
    const order = items.map(item => item.dataset.filename);
    const pinned = items
        .filter(item => {
            const btn = item.querySelector('.btn-icon');
            return btn && btn.classList.contains('active');
        })
        .map(item => item.dataset.filename);
        
    try {
        const resp = await fetch('/api/documents/metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order, pinned })
        });
        const data = await resp.json();
        if (data.success) {
            // Optional: Show a brief tiny success indicator or just silently save
            console.log('Document order saved.');
        } else {
            console.error('Failed to save document order.');
        }
    } catch (err) {
        console.error(err);
    }
}
