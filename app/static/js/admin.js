let currentUserEmail = '';
let allUsers = [];
let filteredUsers = [];
let currentGroupName = '';
let availableUsers = [];

// Initialize users data when page loads
document.addEventListener('DOMContentLoaded', function() {
    loadUsersData();
    // Auto-check consistency when page loads
    setTimeout(checkDataConsistency, 1000);
});

// Load users data for search functionality
function loadUsersData() {
    const userRows = document.querySelectorAll('.users-table tbody tr');
    allUsers = [];
    
    userRows.forEach(row => {
        const cells = row.cells;
        allUsers.push({
            element: row,
            name: cells[1].textContent.toLowerCase(),
            email: cells[2].textContent.toLowerCase(),
            isAdmin: cells[3].textContent.includes('Admin'),
            groups: Array.from(cells[4].querySelectorAll('.group-badge')).map(badge => badge.textContent.toLowerCase())
        });
    });
    filteredUsers = [...allUsers];
}

// Search users functionality
function searchUsers() {
    const searchTerm = document.getElementById('userSearch').value.toLowerCase();
    const showAdminOnly = document.getElementById('adminFilter').checked;
    const groupFilter = document.getElementById('groupFilter').value.toLowerCase();
    
    filteredUsers = allUsers.filter(user => {
        const matchesSearch = user.name.includes(searchTerm) || user.email.includes(searchTerm);
        const matchesAdmin = !showAdminOnly || user.isAdmin;
        const matchesGroup = !groupFilter || user.groups.includes(groupFilter);
        
        return matchesSearch && matchesAdmin && matchesGroup;
    });
    
    updateUsersDisplay();
}

// Update users table display
function updateUsersDisplay() {
    allUsers.forEach(user => {
        user.element.style.display = 'none';
    });
    
    filteredUsers.forEach(user => {
        user.element.style.display = '';
    });
    
    // Update results count
    const resultCount = document.getElementById('searchResults');
    if (resultCount) {
        resultCount.textContent = `${filteredUsers.length} users found`;
    }
}

// Clear search
function clearSearch() {
    document.getElementById('userSearch').value = '';
    document.getElementById('adminFilter').checked = false;
    document.getElementById('groupFilter').value = '';
    filteredUsers = [...allUsers];
    updateUsersDisplay();
}

// Tab functionality
function showTab(tabName) {
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => content.classList.remove('active'));
    
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => button.classList.remove('active'));
    
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
}

// Modal functions
function showInviteUserModal() {
    document.getElementById('inviteUserModal').style.display = 'block';
}

function showCreateGroupModal() {
    document.getElementById('createGroupModal').style.display = 'block';
}

function showGroupModal(userEmail) {
    currentUserEmail = userEmail;
    document.getElementById('selectedUserEmail').textContent = userEmail;
    loadUserGroups(userEmail);
    document.getElementById('manageGroupsModal').style.display = 'block';
}

// Load user's current groups
async function loadUserGroups(userEmail) {
    try {
        const response = await fetch(`/admin/user-groups/${encodeURIComponent(userEmail)}`);
        const result = await response.json();
        
        if (result.success) {
            updateGroupsModalDisplay(result.user_groups, result.available_groups);
        } else {
            alert('Error loading user groups: ' + result.error);
        }
    } catch (error) {
        alert('An error occurred: ' + error.message);
    }
}

// Update groups display in modal
function updateGroupsModalDisplay(userGroups, availableGroups) {
    const currentGroupsList = document.getElementById('currentGroupsList');
    const availableGroupsList = document.getElementById('availableGroupsList');
    
    // Display current groups
    currentGroupsList.innerHTML = '';
    userGroups.forEach(groupName => {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'group-item current-group';
        groupDiv.innerHTML = `
            <span>${groupName}</span>
            <button class="btn-small btn-danger" onclick="removeFromGroup('${currentUserEmail}', '${groupName}')">Remove</button>
        `;
        currentGroupsList.appendChild(groupDiv);
    });
    
    if (userGroups.length === 0) {
        currentGroupsList.innerHTML = '<p class="no-groups">No groups assigned</p>';
    }
    
    // Display available groups
    availableGroupsList.innerHTML = '';
    availableGroups.forEach(groupName => {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'group-item available-group';
        groupDiv.innerHTML = `
            <span>${groupName}</span>
            <button class="btn-small btn-primary" onclick="addToGroup('${groupName}')">Add</button>
        `;
        availableGroupsList.appendChild(groupDiv);
    });
    
    if (availableGroups.length === 0) {
        availableGroupsList.innerHTML = '<p class="no-groups">All groups assigned</p>';
    }
}

// Batch add multiple groups
function showBatchGroupModal(userEmail) {
    currentUserEmail = userEmail;
    document.getElementById('batchSelectedUserEmail').textContent = userEmail;
    loadBatchGroupsData(userEmail);
    document.getElementById('batchGroupsModal').style.display = 'block';
}

// Load batch groups data
async function loadBatchGroupsData(userEmail) {
    try {
        const response = await fetch(`/admin/user-groups/${encodeURIComponent(userEmail)}`);
        const result = await response.json();
        
        if (result.success) {
            updateBatchGroupsDisplay(result.user_groups, result.all_groups);
        } else {
            alert('Error loading groups: ' + result.error);
        }
    } catch (error) {
        alert('An error occurred: ' + error.message);
    }
}

// Update batch groups display
function updateBatchGroupsDisplay(userGroups, allGroups) {
    const groupsContainer = document.getElementById('batchGroupsContainer');
    groupsContainer.innerHTML = '';
    
    allGroups.forEach(groupName => {
        const isChecked = userGroups.includes(groupName);
        const groupDiv = document.createElement('div');
        groupDiv.className = 'batch-group-item';
        groupDiv.innerHTML = `
            <label class="checkbox-label">
                <input type="checkbox" value="${groupName}" ${isChecked ? 'checked' : ''}>
                <span class="checkmark"></span>
                ${groupName}
            </label>
        `;
        groupsContainer.appendChild(groupDiv);
    });
}

// Save batch groups with better feedback
async function saveBatchGroups() {
    const checkboxes = document.querySelectorAll('#batchGroupsContainer input[type="checkbox"]');
    const selectedGroups = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => cb.value);
    
    try {
        const response = await fetch('/admin/batch-update-groups', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: currentUserEmail,
                groups: selectedGroups
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Groups updated successfully!', 'success');
            closeModal('batchGroupsModal');
            // Refresh the main table
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Modified addToGroup to refresh modal
async function addToGroup(groupName) {
    try {
        const response = await fetch('/admin/add-to-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: currentUserEmail,
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Refresh the modal display immediately
            await loadUserGroups(currentUserEmail);
            // Show success message
            showNotification('User added to group successfully!', 'success');
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Modified removeFromGroup to refresh modal instead of page reload
async function removeFromGroup(userEmail, groupName) {
    if (!confirm(`Remove ${userEmail} from group "${groupName}"?`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/remove-from-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: userEmail,
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // If modal is open, refresh it; otherwise reload page
            if (document.getElementById('manageGroupsModal').style.display === 'block') {
                await loadUserGroups(currentUserEmail);
                showNotification('User removed from group successfully!', 'success');
            } else {
                location.reload();
            }
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
    const form = document.querySelector(`#${modalId} form`);
    if (form) {
        form.reset();
    }
}

// Close modals when clicking outside
window.onclick = function(event) {
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        if (event.target === modal) {
            modal.style.display = 'none';
        }
    });
}

// Invite User
async function inviteUser(event) {
    event.preventDefault();
    
    const email = document.getElementById('userEmail').value;
    const isAdmin = document.getElementById('isAdmin').checked;
    const sendEmail = document.getElementById('sendEmail').checked;
    
    try {
        const response = await fetch('/admin/invite-user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                email: email,
                is_admin: isAdmin,
                send_email: sendEmail
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            let message = 'Invitation sent successfully!';
            if (sendEmail) {
                message += result.email_sent ? 
                    ' Email notification sent.' : 
                    ' Email notification failed to send.';
            }
            showNotification(message, 'success');
            closeModal('inviteUserModal');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Create Group
async function createGroup(event) {
    event.preventDefault();
    
    const name = document.getElementById('groupName').value;
    const description = document.getElementById('groupDescription').value;
    
    try {
        const response = await fetch('/admin/create-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: name,
                description: description
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Group created successfully!', 'success');
            closeModal('createGroupModal');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Add User to Group
async function addToGroup(groupName) {
    try {
        const response = await fetch('/admin/add-to-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: currentUserEmail,
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('User added to group successfully!');
            updateGroupsDisplay();
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('An error occurred: ' + error.message);
    }
}

// Remove User from Group
async function removeFromGroup(userEmail, groupName) {
    if (!confirm(`Remove ${userEmail} from group "${groupName}"?`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/remove-from-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: userEmail,
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('User removed from group successfully!');
            location.reload();
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('An error occurred: ' + error.message);
    }
}

// Toggle Admin Status
async function toggleAdminStatus(userEmail) {
    const action = confirm(`Change admin status for ${userEmail}?`);
    if (!action) return;
    
    try {
        const response = await fetch('/admin/toggle-admin', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: userEmail
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(result.message, 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Delete User
async function deleteUser(userEmail) {
    if (!confirm(`Are you sure you want to delete user ${userEmail}? This action cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/delete-user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: userEmail
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('User deleted successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Delete Group
async function deleteGroup(groupName) {
    if (!confirm(`Are you sure you want to delete the group "${groupName}"? This action cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/delete-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Group deleted successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Update Groups Display in Modal
function updateGroupsDisplay() {
    // This would need to fetch current user groups via AJAX
    // For now, we'll reload the page after each action
}

// Copy Invitation Link with notification
function copyInvitationLink(token) {
    const link = `${window.location.origin}/invitation/${token}`;
    
    navigator.clipboard.writeText(link).then(() => {
        showNotification('Invitation link copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy: ', err);
        const textArea = document.createElement('textarea');
        textArea.value = link;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showNotification('Invitation link copied to clipboard!', 'success');
    });
}

// Add notification system
function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelector('.notification');
    if (existing) {
        existing.remove();
    }
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 3000);
}

// Clean accepted invitations
async function cleanAcceptedInvitations() {
    if (!confirm('Are you sure you want to clean all accepted invitations? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/admin/clean-invitations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Cleaned ${result.cleaned_count} accepted invitations`, 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Delete single invitation
async function deleteInvitation(token) {
    if (!confirm('Are you sure you want to delete this invitation? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/admin/delete-invitation', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                token: token
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Invitation deleted successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Group details toggle functionality
function toggleGroupDetails(groupName, index) {
    const detailsElement = document.getElementById(`details-${index}`);
    const iconElement = document.getElementById(`icon-${index}`);
    
    if (detailsElement.style.display === 'none' || detailsElement.style.display === '') {
        detailsElement.style.display = 'block';
        iconElement.textContent = '▲';
    } else {
        detailsElement.style.display = 'none';
        iconElement.textContent = '▼';
    }
}

// Show add members modal
async function showAddMembersModal(groupName) {
    currentGroupName = groupName;
    document.getElementById('selectedGroupName').textContent = groupName;
    
    try {
        const response = await fetch(`/admin/available-users/${encodeURIComponent(groupName)}`);
        const result = await response.json();
        
        if (result.success) {
            availableUsers = result.available_users;
            updateAvailableUsersDisplay(availableUsers);
            document.getElementById('addMembersModal').style.display = 'block';
        } else {
            showNotification('Error loading available users: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Update available users display
function updateAvailableUsersDisplay(users) {
    const container = document.getElementById('availableUsersContainer');
    container.innerHTML = '';
    
    if (users.length === 0) {
        container.innerHTML = '<p class="no-users">All users are already in this group.</p>';
        return;
    }
    
    users.forEach(user => {
        const userDiv = document.createElement('div');
        userDiv.className = 'available-user-item';
        userDiv.innerHTML = `
            <label class="user-checkbox-label">
                <input type="checkbox" value="${user.email}" class="user-checkbox">
                <div class="user-info">
                    <img src="${user.picture}" alt="Avatar" class="user-avatar-small">
                    <div class="user-details">
                        <span class="user-name">${user.name}</span>
                        <span class="user-email">${user.email}</span>
                    </div>
                </div>
            </label>
        `;
        container.appendChild(userDiv);
    });
}

// Filter available users
function filterAvailableUsers() {
    const searchTerm = document.getElementById('memberSearch').value.toLowerCase();
    const filteredUsers = availableUsers.filter(user => 
        user.name.toLowerCase().includes(searchTerm) || 
        user.email.toLowerCase().includes(searchTerm)
    );
    updateAvailableUsersDisplay(filteredUsers);
}

// Add selected members to group
async function addSelectedMembers() {
    const checkboxes = document.querySelectorAll('.user-checkbox:checked');
    const selectedUsers = Array.from(checkboxes).map(cb => cb.value);
    
    if (selectedUsers.length === 0) {
        showNotification('Please select at least one user to add.', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/admin/add-multiple-to-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                group_name: currentGroupName,
                user_emails: selectedUsers
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Successfully added ${result.added_count} users to group!`, 'success');
            closeModal('addMembersModal');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Modified removeFromGroup for group page
async function removeFromGroup(userEmail, groupName) {
    if (!confirm(`Remove ${userEmail} from group "${groupName}"?`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/remove-from-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_email: userEmail,
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('User removed from group successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Delete Group with confirmation
async function deleteGroup(groupName) {
    if (!confirm(`Are you sure you want to delete the group "${groupName}"? This action will remove all members and cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch('/admin/delete-group', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                group_name: groupName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Group deleted successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

// Data consistency check and cleanup
async function checkDataConsistency() {
    const statusElement = document.getElementById('consistencyStatus');
    statusElement.textContent = 'Checking...';
    statusElement.className = 'consistency-status checking';
    
    try {
        const response = await fetch('/admin/check-consistency');
        const result = await response.json();
        
        if (result.success) {
            if (result.has_issues) {
                statusElement.textContent = `${result.issues.total_issues} issues found`;
                statusElement.className = 'consistency-status issues-found';
                showConsistencyResults(result.issues);
            } else {
                statusElement.textContent = 'No issues found';
                statusElement.className = 'consistency-status no-issues';
                showNotification('Data consistency check passed - no issues found!', 'success');
            }
        } else {
            statusElement.textContent = 'Check failed';
            statusElement.className = 'consistency-status error';
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        statusElement.textContent = 'Check failed';
        statusElement.className = 'consistency-status error';
        showNotification('An error occurred: ' + error.message, 'error');
    }
}

function showConsistencyResults(issues) {
    const resultsContainer = document.getElementById('consistencyResults');
    const actionsContainer = document.getElementById('consistencyActions');
    
    let html = '<div class="consistency-summary">';
    html += `<h4>Data Consistency Issues Found: ${issues.total_issues}</h4>`;
    html += '</div>';
    
    if (issues.orphaned_user_groups.length > 0) {
        html += '<div class="issue-section">';
        html += `<h5>Orphaned User-Group Relations (${issues.orphaned_user_groups.length})</h5>`;
        html += '<p class="issue-description">Users that no longer exist but still have group associations:</p>';
        html += '<ul class="issue-list">';
        issues.orphaned_user_groups.forEach(item => {
            html += `<li>User: ${item[0]} → Group: ${item[1]}</li>`;
        });
        html += '</ul>';
        html += '</div>';
    }
    
    if (issues.orphaned_group_users.length > 0) {
        html += '<div class="issue-section">';
        html += `<h5>Orphaned Group-User Relations (${issues.orphaned_group_users.length})</h5>`;
        html += '<p class="issue-description">Groups that no longer exist but still have user associations:</p>';
        html += '<ul class="issue-list">';
        issues.orphaned_group_users.forEach(item => {
            html += `<li>User: ${item[0]} → Group: ${item[1]}</li>`;
        });
        html += '</ul>';
        html += '</div>';
    }
    
    html += '<div class="cleanup-warning">';
    html += '<p><strong>⚠️ Warning:</strong> Cleaning these issues will permanently remove the orphaned relationships. This action cannot be undone.</p>';
    html += '</div>';
    
    resultsContainer.innerHTML = html;
    actionsContainer.style.display = 'flex';
    document.getElementById('consistencyModal').style.display = 'block';
}

async function cleanDataConsistency() {
    if (!confirm('Are you sure you want to clean all data consistency issues? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/admin/clean-consistency', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Successfully cleaned ${result.cleaned_count} data consistency issues!`, 'success');
            closeModal('consistencyModal');
            
            // Update status
            const statusElement = document.getElementById('consistencyStatus');
            statusElement.textContent = 'Cleaned - No issues';
            statusElement.className = 'consistency-status no-issues';
            
            // Reload page after a short delay
            setTimeout(() => location.reload(), 1500);
        } else {
            showNotification('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('An error occurred: ' + error.message, 'error');
    }
}