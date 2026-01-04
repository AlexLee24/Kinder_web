document.addEventListener('DOMContentLoaded', function() {
    loadTargets();
    
    // Initialize exposure settings
    toggleAutoExposure(document.getElementById('target-auto'));
    
    document.getElementById('add-target-form').addEventListener('submit', function(e) {
        e.preventDefault();
        addTarget();
    });
});

function toggleAutoExposure(checkbox) {
    const manualContainer = document.getElementById('manual-exposures-container');
    const autoInfo = document.getElementById('auto-info-text');
    
    if (checkbox.checked) {
        manualContainer.style.display = 'none';
        autoInfo.style.display = 'block';
    } else {
        manualContainer.style.display = 'flex';
        autoInfo.style.display = 'none';
        
        // Add one row if empty
        const list = document.getElementById('exposure-list');
        if (list.children.length === 0) {
            addExposureRow();
        }
    }
}

function addExposureRow() {
    const list = document.getElementById('exposure-list');
    const template = document.getElementById('exposure-row-template');
    
    if (!template) {
        console.error('Template not found');
        return;
    }
    
    const clone = template.content.cloneNode(true);
    list.appendChild(clone);
}

function removeExposureRow(btn) {
    const row = btn.closest('.exposure-row');
    const list = row.parentElement;
    if (list.children.length > 1) {
        row.remove();
    } else {
        // Don't remove the last one, just reset it or alert
        // For now, let's just reset values
        row.querySelector('.field-filter').value = 'rp';
        row.querySelector('.field-exp').value = '300';
        row.querySelector('.field-count').value = '3';
    }
}

function loadTargets() {
    fetch('/api/custom_targets')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderTargets(data.targets);
            } else {
                // Handle access denied or other errors
                if (data.error && data.error.includes('Access denied')) {
                    document.querySelector('.main-content').innerHTML = 
                        '<div class="alert alert-danger" style="text-align:center; padding: 50px;">' + 
                        '<h3>Access Denied</h3><p>You need administrator privileges to manage custom targets.</p></div>';
                } else {
                    alert('Error loading targets: ' + data.error);
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error loading targets');
        });
}

function renderTargets(targets) {
    const tbody = document.querySelector('#targets-table tbody');
    tbody.innerHTML = '';
    
    if (targets.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="8" class="empty-state">No custom targets found. Add one to get started!</td>';
        tbody.appendChild(row);
        return;
    }
    
    targets.forEach(target => {
        const row = document.createElement('tr');
        
        // Format exposure info
        let exposureInfo = '<span style="color: #aaa; font-style: italic;">Auto</span>';
        if (!target.is_auto_exposure) {
            if (target.filters) {
                const filters = target.filters.split(',');
                const exps = target.exposures.split(',');
                const counts = target.counts.split(',');
                
                exposureInfo = filters.map((f, i) => {
                    const filterName = f.replace('p', ''); // rp -> r
                    return `<span class="badge" style="background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; margin-right: 4px; font-size: 0.85em;">${filterName}: ${exps[i]}s x${counts[i]}</span>`;
                }).join('<br>');
            } else {
                exposureInfo = 'Manual (No settings)';
            }
        }
        
        row.innerHTML = `
            <td>${escapeHtml(target.name)}</td>
            <td>${escapeHtml(target.ra)}</td>
            <td>${escapeHtml(target.dec)}</td>
            <td>${target.mag || '-'}</td>
            <td>${target.priority}</td>
            <td>${exposureInfo}</td>
            <td>${escapeHtml(target.note || '')}</td>
            <td>
                <button class="btn btn-danger" onclick="deleteTarget(${target.id})">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function addTarget() {
    const name = document.getElementById('target-name').value;
    const ra = document.getElementById('target-ra').value;
    const dec = document.getElementById('target-dec').value;
    const mag = document.getElementById('target-mag').value;
    const priority = document.getElementById('target-priority').value;
    const note = document.getElementById('target-note').value;
    
    // Exposure settings
    const isAuto = document.getElementById('target-auto').checked;
    let filters = [], exps = [], counts = [];
    
    if (!isAuto) {
        const rows = document.querySelectorAll('#exposure-list .exposure-row');
        rows.forEach(row => {
            filters.push(row.querySelector('.field-filter').value);
            exps.push(row.querySelector('.field-exp').value);
            counts.push(row.querySelector('.field-count').value);
        });
    }
    
    const data = {
        name: name,
        ra: ra,
        dec: dec,
        mag: mag,
        priority: priority,
        note: note,
        is_auto_exposure: isAuto,
        filters: filters.join(','),
        exposures: exps.join(','),
        counts: counts.join(',')
    };
    
    fetch('/api/custom_targets/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.getElementById('add-target-form').reset();
            // Reset exposure UI
            document.getElementById('target-auto').checked = true;
            toggleAutoExposure(document.getElementById('target-auto'));
            
            loadTargets();
        } else {
            alert('Error adding target: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error adding target');
    });
}

function deleteTarget(id) {
    if (!confirm('Are you sure you want to delete this target?')) {
        return;
    }
    
    fetch(`/api/custom_targets/delete/${id}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            loadTargets();
        } else {
            alert('Error deleting target: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error deleting target');
    });
}

function escapeHtml(text) {
    if (text == null) return '';
    return text
        .toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Permissions Modal Functions
function openPermissionsModal() {
    const modal = document.getElementById('permissionsModal');
    modal.style.display = 'block';
    loadPermissions();
}

function closePermissionsModal() {
    document.getElementById('permissionsModal').style.display = 'none';
}

function loadPermissions() {
    fetch('/api/custom_targets/permissions')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderPermissionsLists(data);
            } else {
                alert('Error loading permissions: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error loading permissions');
        });
}

function renderPermissionsLists(data) {
    const groupsList = document.getElementById('groups-list');
    const usersList = document.getElementById('users-list');
    
    // Render Groups
    groupsList.innerHTML = '';
    if (data.groups.length === 0) {
        groupsList.innerHTML = '<p class="text-muted">No groups found.</p>';
    } else {
        data.groups.forEach(group => {
            const isChecked = data.allowed_groups.includes(group);
            const div = document.createElement('div');
            div.className = 'permission-item';
            div.style.padding = '8px';
            div.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
            div.innerHTML = `
                <label class="checkbox-label" style="width: 100%; cursor: pointer;">
                    <input type="checkbox" class="group-checkbox" value="${escapeHtml(group)}" ${isChecked ? 'checked' : ''}>
                    <span style="margin-left: 8px;">${escapeHtml(group)}</span>
                </label>
            `;
            groupsList.appendChild(div);
        });
    }
    
    // Render Users
    usersList.innerHTML = '';
    data.users.forEach(user => {
        const isChecked = data.allowed_users.includes(user.email);
        const div = document.createElement('div');
        div.className = 'permission-item';
        div.style.padding = '8px';
        div.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
        
        let badge = '';
        if (user.is_admin) {
            badge = '<span class="badge" style="background: #C5A059; color: #000; font-size: 0.7em; padding: 2px 4px; border-radius: 3px; margin-left: 5px;">Admin</span>';
        }
        
        div.innerHTML = `
            <label class="checkbox-label" style="width: 100%; cursor: pointer; display: flex; align-items: center;">
                <input type="checkbox" class="user-checkbox" value="${escapeHtml(user.email)}" ${isChecked ? 'checked' : ''} ${user.is_admin ? 'disabled checked' : ''}>
                <span style="margin-left: 8px;">${escapeHtml(user.name)} <small style="color: #aaa;">(${escapeHtml(user.email)})</small>${badge}</span>
            </label>
        `;
        usersList.appendChild(div);
    });
}

function savePermissions() {
    const allowedGroups = Array.from(document.querySelectorAll('.group-checkbox:checked')).map(cb => cb.value);
    const allowedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);
    
    fetch('/api/custom_targets/permissions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            allowed_groups: allowedGroups,
            allowed_users: allowedUsers
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Permissions saved successfully');
            closePermissionsModal();
        } else {
            alert('Error saving permissions: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error saving permissions');
    });
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('permissionsModal');
    if (event.target == modal) {
        modal.style.display = "none";
    }
}
