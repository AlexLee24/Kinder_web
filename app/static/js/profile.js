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
            })
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
