// ===============================================================================
// EDIT NAME FUNCTIONALITY
// ===============================================================================

function showEditNameModal() {
    const modal = document.getElementById('editNameModal');
    const nameInput = document.getElementById('newName');
    
    modal.style.display = 'block';
    nameInput.focus();
    nameInput.select();
    
    updateCharCounter();
}

function closeEditNameModal() {
    const modal = document.getElementById('editNameModal');
    modal.style.display = 'none';
    
    // Reset form
    const form = modal.querySelector('form');
    if (form) {
        form.reset();
        const nameInput = document.getElementById('newName');
        nameInput.value = document.getElementById('userName').textContent;
        updateCharCounter();
    }
}

function updateCharCounter() {
    const nameInput = document.getElementById('newName');
    const charCount = document.getElementById('charCount');
    
    if (nameInput && charCount) {
        charCount.textContent = nameInput.value.length;
        
        // Update color based on character count
        const count = nameInput.value.length;
        if (count > 90) {
            charCount.style.color = '#ff6b6b';
        } else if (count > 75) {
            charCount.style.color = '#feca57';
        } else {
            charCount.style.color = 'rgba(255, 255, 255, 0.6)';
        }
    }
}

async function updateName(event) {
    event.preventDefault();
    
    const newName = document.getElementById('newName').value.trim();
    const currentName = document.getElementById('userName').textContent;
    
    if (!newName) {
        showNotification('Name cannot be empty', 'error');
        return;
    }
    
    if (newName === currentName) {
        showNotification('Name is the same as current name', 'warning');
        return;
    }
    
    if (newName.length > 80) {
        showNotification('Name is too long (maximum 80 characters)', 'error');
        return;
    }
    
    // Show loading state
    const submitBtn = event.target.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Updating...';
    submitBtn.disabled = true;
    
    try {
        const response = await fetch('/update-profile', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: newName
            }) // DO NOT OVERWRITE EXISTING PICTURE HERE
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Update the display name
            document.getElementById('userName').textContent = newName;
            
            // Update the input value for next time
            document.getElementById('newName').value = newName;
            
            showNotification('Name updated successfully!', 'success');
            closeEditNameModal();
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    } finally {
        // Reset button state
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    }
}

// ===============================================================================
// UPLOAD AVATAR
// ===============================================================================
function shrinkImageDataUrl(dataUrl, maxSide) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round(img.width * scale));
            canvas.height = Math.max(1, Math.round(img.height * scale));
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        img.onerror = () => reject(new Error('unreadable image'));
        img.src = dataUrl;
    });
}

async function uploadAvatar(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Check file type
    const validTypes = ['image/jpeg', 'image/png', 'image/jpg'];
    if (!validTypes.includes(file.type)) {
        showNotification('Only JPG and PNG files are allowed', 'error');
        // Reset file input
        event.target.value = '';
        return;
    }

    // The photo is shrunk in the browser before upload, so only very large files are refused.
    if (file.size > 30 * 1024 * 1024) {
        showNotification('Image size must be less than 30MB', 'error');
        // Reset file input
        event.target.value = '';
        return;
    }

    // Shrink in the browser first (max 256 px) so a multi-MB photo is not uploaded
    // in full; the server re-encodes it again anyway.
    const reader = new FileReader();
    reader.onload = async function(e) {
        let base64Image;
        try {
            base64Image = await shrinkImageDataUrl(e.target.result, 256);
        } catch (err) {
            showNotification('The image could not be read', 'error');
            event.target.value = '';
            return;
        }
        const currentName = document.getElementById('userName').textContent;

        try {
            showNotification('Uploading image...', 'info');
            const response = await fetch('/update-profile', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: currentName,
                    picture: base64Image
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Update the display image (it may have been a hidden placeholder next to the initial)
                const profileImg = document.getElementById('profile-avatar-img');
                profileImg.src = base64Image;
                profileImg.hidden = false;
                const initial = document.querySelector('.profile-avatar-initial');
                if (initial) initial.remove();
                
                // Also update the navbar avatar if it exists
                const navAvatars = document.querySelectorAll('.user-avatar');
                navAvatars.forEach(av => {
                    if (av.tagName === 'IMG' && av.id !== 'profile-avatar-img') {
                        av.src = base64Image;
                    } else if (av.querySelector('img') && av.querySelector('img').id !== 'profile-avatar-img') {
                        av.querySelector('img').src = base64Image;
                    }
                });

                showNotification('Profile picture updated successfully!', 'success');
            } else {
                showNotification('Error updating picture: ' + result.error, 'error');
            }
        } catch (error) {
            showNotification('Failed to upload image: ' + error.message, 'error');
        }
    };
    reader.readAsDataURL(file);
}

// ===============================================================================
// NOTIFICATION SYSTEM
// ===============================================================================

function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelector('.notification');
    if (existing) {
        existing.remove();
    }
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    const container = document.getElementById('notificationContainer');
    if (container) {
        container.appendChild(notification);
    } else {
        document.body.appendChild(notification);
    }
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.style.animation = 'notificationSlideOut 0.3s ease-in forwards';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 300);
        }
    }, 3000);
}

// ===============================================================================
// ASK TO JOIN GROUP / LEAVE GROUP
// ===============================================================================

async function askToJoinCustomGroup(event) {
    event.preventDefault();
    
    const groupName = document.getElementById('joinGroupName').value.trim();
    const reason = document.getElementById('joinReason').value.trim();
    
    if (!groupName) {
        showNotification('Please enter a group name', 'error');
        return;
    }
    
    // Show loading state
    const submitBtn = event.target.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Sending Request...';
    submitBtn.disabled = true;
    
    try {
        await new Promise(resolve => setTimeout(resolve, 800));
        
        showNotification(`Request to join "${groupName}" sent successfully! Admin will review your request.`, 'success');
        event.target.reset(); // clear the form
        
    } catch (error) {
        showNotification('Failed to send request: ' + error.message, 'error');
    } finally {
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    }
}

async function askToJoinGroup(groupName) {
    if (!groupName) return;
    
    if (confirm(`Do you want to send a request to join "${groupName}"?`)) {
        try {
            const response = await fetch('/api/profile/join_group', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_name: groupName })
            });
            const result = await response.json();
            if (result.success) {
                showNotification(result.message, 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                showNotification(result.error, 'error');
            }
        } catch (error) {
            showNotification('An error occurred: ' + error.message, 'error');
        }
    }
}

async function leaveGroup(groupName) {
    if (!groupName) return;
    
    if (confirm(`Are you sure you want to leave "${groupName}"?`)) {
        try {
            const response = await fetch('/api/profile/leave_group', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_name: groupName })
            });
            const result = await response.json();
            if (result.success) {
                showNotification(result.message, 'info');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                showNotification(result.error, 'error');
            }
        } catch (error) {
            showNotification('An error occurred: ' + error.message, 'error');
        }
    }
}

// ===============================================================================
// EVENT LISTENERS
// ===============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Character counter for name input
    const nameInput = document.getElementById('newName');
    if (nameInput) {
        nameInput.addEventListener('input', updateCharCounter);
    }
    
    // Close modal when clicking outside
    window.addEventListener('click', function(event) {
        const modal = document.getElementById('editNameModal');
        if (event.target === modal) {
            closeEditNameModal();
        }
    });
    
    // Close modal with Escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            const modal = document.getElementById('editNameModal');
            if (modal && modal.style.display === 'block') {
                closeEditNameModal();
            }
        }
    });
});

// (the notificationSlideOut keyframes live in _theme.css)

// ===============================================================================
// API KEY FUNCTIONALITY
// ===============================================================================

// Show a freshly issued API key exactly once (it is stored hashed server-side).
// Built with textContent / value only, never innerHTML, so the key is never parsed as HTML.
function showApiKeyOnce(apiKey) {
    const overlay = document.createElement('div');
    overlay.className = 'modal kw-modal';
    overlay.style.display = 'block';

    const box = document.createElement('div');
    box.className = 'modal-content kw-modal-card';

    const title = document.createElement('h3');
    title.textContent = 'Your new API key';

    const warn = document.createElement('p');
    warn.style.color = 'rgba(255,120,120,0.95)';
    warn.textContent = 'Copy it now: it will not be shown again. Your previous key no longer works.';

    const input = document.createElement('input');
    input.type = 'text';
    input.readOnly = true;
    input.value = apiKey;
    input.style.cssText = 'width:100%;padding:10px;font-family:monospace;background:rgba(0,0,0,0.3);color:#fff;border:1px solid rgba(255,255,255,0.2);border-radius:4px;box-sizing:border-box;';

    const actions = document.createElement('div');
    actions.className = 'kw-modal-actions';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'kw-btn kw-btn-primary';
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(apiKey);
        } catch (e) {
            input.select();
            document.execCommand('copy');
        }
        showNotification('API key copied to clipboard', 'success');
    });
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'kw-btn';
    closeBtn.textContent = 'Done';
    closeBtn.addEventListener('click', () => { overlay.remove(); location.reload(); });
    actions.append(copyBtn, closeBtn);

    box.append(title, warn, input, actions);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    input.focus();
    input.select();
}

async function regenerateApiKey(event) {
    if (!confirm('Generate a new API key? Your current key stops working immediately.')) return;
    const btn = event.currentTarget;
    const ogText = btn.textContent;
    btn.textContent = 'Generating…';
    btn.disabled = true;
    try {
        const response = await fetch('/api/profile/regenerate_api_key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        if (data.success && data.api_key) {
            const status = document.getElementById('apiKeyStatus');
            if (status) status.textContent = 'Active (…' + (data.api_key_hint || '') + ')';
            showApiKeyOnce(data.api_key);
        } else {
            showNotification('Error: ' + (data.error || 'Failed'), 'error');
        }
    } catch (error) {
        showNotification('Network error', 'error');
    }
    btn.textContent = ogText;
    btn.disabled = false;
}

async function requestApiKey(event, isReset) {
    const confirmMsg = isReset
        ? 'Request a key reset? Your current key stays active until an admin issues a new one.'
        : 'Submit a request for an API key? An admin will review it.';
    if (!confirm(confirmMsg)) return;

    const btn = event.currentTarget;
    const ogText = btn.textContent;
    btn.textContent = 'Submitting…';
    btn.disabled = true;

    try {
        const response = await fetch('/api/profile/request_api_key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        if (data.success) {
            showNotification(data.message || 'Request submitted. An admin will review it.', 'success');
            const _clockSvg = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
            btn.innerHTML = _clockSvg + (isReset ? ' Reset Requested' : ' Request Pending');
            btn.style.display = 'inline-flex';
            btn.style.alignItems = 'center';
            btn.style.gap = '6px';
        } else {
            showNotification('Error: ' + (data.error || 'Failed'), 'error');
            btn.textContent = ogText;
            btn.disabled = false;
        }
    } catch (error) {
        showNotification('Network error', 'error');
        btn.textContent = ogText;
        btn.disabled = false;
    }
}
