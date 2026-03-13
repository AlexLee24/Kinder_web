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
    
    if (newName.length > 100) {
        showNotification('Name is too long (maximum 100 characters)', 'error');
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

    if (file.size > 10 * 1024 * 1024) { // 10MB limit
        showNotification('Image size must be less than 10MB', 'error');
        // Reset file input
        event.target.value = '';
        return;
    }

    // Convert image to base64
    const reader = new FileReader();
    reader.onload = async function(e) {
        const base64Image = e.target.result;
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
                // Update the display image
                document.getElementById('profile-avatar-img').src = base64Image;
                
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
        showNotification(`Request to join "${groupName}" sent successfully! Admin will review your request.`, 'success');
        // TODO: Real API call
    }
}

async function leaveGroup(groupName) {
    if (!groupName) return;
    
    if (confirm(`Are you sure you want to leave "${groupName}"?`)) {
        showNotification(`You have left "${groupName}".`, 'info');
        // TODO: Real API call
        // setTimeout(() => window.location.reload(), 1500); 
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

// Add slide out animation
const style = document.createElement('style');
style.textContent = `
    @keyframes notificationSlideOut {
        from {
            opacity: 1;
            transform: translateX(0);
        }
        to {
            opacity: 0;
            transform: translateX(100%);
        }
    }
`;
document.head.appendChild(style);

// ===============================================================================
// API KEY FUNCTIONALITY
// ===============================================================================

function toggleApiKeyVisibility(event) {
    const input = document.getElementById('apiKeyDisplay');
    const btn = event.currentTarget;
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = 'Hide';
    } else {
        input.type = 'password';
        btn.textContent = 'Show';
    }
}

function copyApiKey() {
    const input = document.getElementById('apiKeyDisplay');
    if (input.value === 'No API key generated' || !input.value) return;
    
    // temporarily change to text to copy
    const ogType = input.type;
    input.type = 'text';
    input.select();
    document.execCommand('copy');
    input.type = ogType;
    
    showNotification('API Key copied to clipboard!', 'success');
}

async function generateNewApiKey(event) {
    if (!confirm('Are you sure? Any existing integrations using your old key will immediately stop working.')) return;
    
    const btn = event.currentTarget;
    const ogText = btn.textContent;
    btn.textContent = 'Generating...';
    btn.disabled = true;
    
    try {
        const response = await fetch('/api/generate_key', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        if (data.success) {
            document.getElementById('apiKeyDisplay').value = data.api_key;
            showNotification('New API Key generated successfully!', 'success');
            btn.textContent = 'Regenerate API Key';
        } else {
            showNotification('Error: ' + (data.error || 'Failed generating'), 'error');
            btn.textContent = ogText;
        }
    } catch (error) {
        showNotification('An error occurred during generation', 'error');
        btn.textContent = ogText;
    } finally {
        btn.disabled = false;
    }
}
