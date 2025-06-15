// Global variables
let currentView = 'cards';
let currentObjects = [];
let filteredObjects = [];
let currentPage = 1;
let pageSize = 50;
let totalPages = 1;
let totalObjects = 0;
let sortBy = 'last_update';
let sortOrder = 'desc';
let isLoading = false;
let currentFilters = {};
let useApiMode = false;
let currentStatusFilter = '';

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Marshal page loaded, initializing...');
    
    // Add a button or key combination to force refresh (for debugging)
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.shiftKey && e.key === 'R') {
            e.preventDefault();
            forceRefreshAll();
            showNotification('Forced complete refresh', 'info');
        }
    });
    
    // Rest of initialization code...
    currentFilters = {
        search: '',
        classification: '',
        tag: '',
        date_from: '',
        date_to: '',
        app_mag_min: '',
        app_mag_max: '',
        redshift_min: '',
        redshift_max: '',
        discoverer: ''
    };
    
    checkObjectsCount();
    loadInitialObjects();
    setTimeout(() => populateClassificationFilter(), 1000);
    
    loadInitialStats();
    
    updatePagination();
    switchView('cards');
    
    const filterInputs = document.querySelectorAll('.filter-group select, .filter-group input');
    filterInputs.forEach(input => {
        input.addEventListener('focus', function() {
            this.closest('.filter-group').classList.add('active');
        });
        input.addEventListener('blur', function() {
            this.closest('.filter-group').classList.remove('active');
        });
    });

    const tagFilter = document.getElementById('tagFilter');
    if (tagFilter) {
        tagFilter.addEventListener('change', function() {
            const selectedStatus = this.value;
            console.log(`Tag filter changed to: ${selectedStatus}`);
            
            if (selectedStatus === '') {
                // Clear filter
                clearStatusFilter();
            } else {
                // Apply filter
                filterByStatus(selectedStatus);
            }
        });
    }

    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                performSearch();
            }
        });
        
        searchInput.addEventListener('input', function(e) {
            const value = e.target.value.trim();
            if (value.length > 0) {
                console.log(`Search input: ${value}`);
            }
        });
    }

});

function loadInitialStats() {
    fetch('/api/stats')
        .then(response => {
            if (!response.ok) throw new Error(`Stats API error: ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log('Stats API response:', data);
            if (data.success && data.stats) {
                updateCountersFromStats(data.stats);
            } else {
                // If stats API fails, set everything to 0
                updateCountersFromStats({
                    inbox_count: 0,
                    followup_count: 0,
                    finished_count: 0,
                    snoozed_count: 0,
                    at_count: 0,
                    classified_count: 0,
                    total_count: 0
                });
            }
        })
        .catch(error => {
            console.error('Error loading initial stats:', error);
            // On error, set everything to 0
            updateCountersFromStats({
                inbox_count: 0,
                followup_count: 0,
                finished_count: 0,
                snoozed_count: 0,
                at_count: 0,
                classified_count: 0,
                total_count: 0
            });
        });
}

function checkObjectsCount() {
    const totalCountElement = document.querySelector('.total-count');
    if (totalCountElement) {
        const countMatch = totalCountElement.textContent.match(/(\d+)/);
        if (countMatch) {
            const count = parseInt(countMatch[1]);
            totalObjects = count;
            
            const cardElements = document.querySelectorAll('#cardsView .object-card');
            if (count > 5000 || cardElements.length === 0) {
                useApiMode = true;
                console.log(`Switching to API mode (${count} objects, ${cardElements.length} cards)`);
            }
        }
    }
}

function loadInitialObjects() {
    if (useApiMode) {
        loadObjects();
        return;
    }
    
    const cardElements = document.querySelectorAll('#cardsView .object-card');
    currentObjects = [];
    
    if (cardElements.length === 0) {
        useApiMode = true;
        loadObjects();
        return;
    }
    
    console.log(`Found ${cardElements.length} cards in DOM`);
    
    const objectNames = [];
    const objectsFromDOM = [];
    
    cardElements.forEach(card => {
        const nameElement = card.querySelector('.object-name a');
        const classificationElement = card.querySelector('.classification-badge');
        const raElement = card.querySelector('.coord-item:nth-child(1) .coord-value');
        const decElement = card.querySelector('.coord-item:nth-child(2) .coord-value');
        const lastUpdateElement = card.querySelector('.last-update');
        
        let discoveryMag = '', redshift = '', discoveryDate = '', source = '';
        
        const infoItems = card.querySelectorAll('.info-item span');
        infoItems.forEach(item => {
            const text = item.textContent;
            if (text.includes('Discovery Mag =')) {
                discoveryMag = text.replace('Discovery Mag =', '').trim();
            } else if (text.includes('z =')) {
                redshift = text.replace('z =', '').trim();
            } else if (text.includes('Date:')) {
                discoveryDate = text.replace('Date:', '').trim();
            } else if (text.includes('Source:')) {
                source = text.replace('Source:', '').trim();
            }
        });
        
        const objectName = nameElement ? nameElement.textContent.trim() : '';
        
        if (objectName) {
            objectNames.push(objectName);
            
            const obj = {
                name: objectName,
                type: classificationElement ? classificationElement.textContent.trim() : 'AT',
                classification: classificationElement ? classificationElement.textContent.trim() : 'AT',
                discovery_date: card.dataset.discovery || discoveryDate || '',
                tag: 'object',
                magnitude: card.dataset.magnitude || discoveryMag || '',
                redshift: card.dataset.redshift || redshift || '',
                ra: raElement ? raElement.textContent.trim() : '',
                dec: decElement ? decElement.textContent.trim() : '',
                source: source || '',
                last_update: lastUpdateElement ? lastUpdateElement.textContent.trim() : ''
            };
            
            objectsFromDOM.push(obj);
        }
    });
    
    fetchObjectTags(objectsFromDOM)
        .then(updatedObjects => {
            console.log('Updated objects with real tags:', updatedObjects);
            currentObjects = updatedObjects;
            filteredObjects = [...currentObjects];
            updateDOMCardsWithTags(updatedObjects);
            refreshCurrentView();
        })
        .catch(error => {
            console.error('Error fetching tags:', error);
            currentObjects = objectsFromDOM;
            filteredObjects = [...currentObjects];
            refreshCurrentView();
        });
}

async function fetchObjectTags(objects) {
    try {
        const objectNames = objects.map(obj => obj.name);
        console.log('Fetching tags for objects:', objectNames);
        
        const response = await fetch('/api/object-tags', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ object_names: objectNames })
        });
        
        if (!response.ok) {
            throw new Error(`Failed to fetch tags: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Tag API response:', data);
        
        if (data.success && data.tags) {
            return objects.map(obj => {
                const dbTag = data.tags[obj.name];
                const finalTag = dbTag || 'object';
                console.log(`Object ${obj.name}: tag = ${finalTag}`);
                return { ...obj, tag: finalTag };
            });
        } else {
            throw new Error('Invalid response format');
        }
        
    } catch (error) {
        console.error('Error in fetchObjectTags:', error);
        return objects.map(obj => ({ ...obj, tag: 'object' }));
    }
}

function updateDOMCardsWithTags(objects) {
    const cardElements = document.querySelectorAll('#cardsView .object-card');
    
    console.log('Updating DOM cards with tags...');
    
    cardElements.forEach(card => {
        const nameElement = card.querySelector('.object-name a');
        if (!nameElement) return;
        
        const objectName = nameElement.textContent.trim();
        const objectData = objects.find(obj => obj.name === objectName);
        
        if (objectData && objectData.tag) {
            const oldTag = card.dataset.tag;
            const newTag = objectData.tag;
            
            console.log(`Object ${objectName}: ${oldTag} -> ${newTag}`);
            card.dataset.tag = newTag;
            card.classList.remove('tag-object', 'tag-followup', 'tag-finished', 'tag-snoozed');
            card.classList.add(`tag-${newTag}`);
            const tagBadge = card.querySelector('.tag-badge');
            if (tagBadge) {
                tagBadge.classList.remove('object', 'followup', 'finished', 'snoozed');
                tagBadge.classList.add(newTag);
                tagBadge.textContent = getTagDisplayName(newTag);
            }
            
            console.log(`Updated DOM card ${objectName} with tag: ${newTag}`);
        }
    });
}

function loadObjects(resetPage = false) {
    if (isLoading) return;
    
    if (resetPage) currentPage = 1;
    
    isLoading = true;
    showLoading(true);
    
    const loadingTimeout = setTimeout(() => {
        if (isLoading) {
            isLoading = false;
            showLoading(false);
            showNotification('Loading timeout, please try again', 'warning');
        }
    }, 15000);
    
    const params = new URLSearchParams({
        page: currentPage,
        per_page: pageSize,
        sort_by: mapSortField(sortBy),
        sort_order: sortOrder,
        search: currentFilters.search || '',
        classification: currentFilters.classification || '',
        tag: currentFilters.tag || '',
        date_from: currentFilters.date_from || '',
        date_to: currentFilters.date_to || ''
    });
    
    fetch(`/api/objects?${params.toString()}`)
        .then(response => {
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            return response.json();
        })
        .then(data => {
            clearTimeout(loadingTimeout);
            
            const objects = data.objects || [];
            const mappedObjects = objects.map(obj => ({
                name: (obj.name_prefix || '') + obj.name,
                type: obj.type || 'AT',
                classification: obj.type || 'AT',
                discovery_date: obj.discoverydate || '',
                tag: obj.tag || 'object',
                magnitude: obj.discoverymag || '',
                redshift: obj.redshift || '',
                ra: obj.ra || '',
                dec: obj.declination || '',
                source: obj.source_group || '',
                last_update: obj.time_received || obj.lastmodified || ''
            }));
            
            currentObjects = mappedObjects;
            filteredObjects = mappedObjects;
            totalObjects = data.total || 0;
            totalPages = data.total_pages || Math.ceil((data.total || 0) / pageSize) || 1;
            
            // CRITICAL FIX: Never update counters from filtered API response
            // Always use a separate stats API call to ensure counters reflect total database state
            // The 'data.stats' from filtered API calls represents filtered stats, not total stats
            
            updatePagination();
            refreshCurrentView();
            
            const classificationFilter = document.getElementById('classificationFilter');
            if (classificationFilter && classificationFilter.options.length <= 1) {
                populateClassificationFilterFromObjects();
            }
            
            // Only update the "total objects" count, not the status counters
            const totalCountElement = document.querySelector('.total-count');
            if (totalCountElement) {
                if (!hasActiveFilters()) {
                    totalCountElement.textContent = `${data.total || 0} objects`;
                }
            }
        })
        .catch(error => {
            clearTimeout(loadingTimeout);
            console.error('API error:', error);
            
            showNotification(`Loading error: ${error.message}`, 'error');
            
            if (error.message.includes('404')) {
                useApiMode = false;
                showNotification('API unavailable, switching to DOM mode', 'warning');
                loadInitialObjects();
                populateClassificationFilterFromObjects();
                loadInitialStats();
            } else {
                currentObjects = [];
                filteredObjects = [];
                refreshCurrentView();
                updatePagination();
            }
        })
        .finally(() => {
            isLoading = false;
            showLoading(false);
        });
}

function hasActiveFilters() {
    return Object.values(currentFilters).some(val => val !== '') || currentStatusFilter !== '';
}

function mapSortField(frontendField) {
    const fieldMap = {
        'name': 'name',
        'classification': 'type',
        'discovery_date': 'discoverydate',
        'magnitude': 'discoverymag',
        'redshift': 'redshift',
        'last_update': 'time_received'
    };
    
    return fieldMap[frontendField] || 'discoverydate';
}

function showLoading(show) {
    let loadingIndicator = document.getElementById('loadingIndicator');
    
    if (!loadingIndicator && show) {
        loadingIndicator = document.createElement('div');
        loadingIndicator.id = 'loadingIndicator';
        loadingIndicator.className = 'loading-overlay';
        loadingIndicator.innerHTML = '<div class="spinner"></div><p>Loading objects...</p>';
        
        const contentArea = document.querySelector('.content-area');
        if (contentArea) {
            contentArea.appendChild(loadingIndicator);
        } else {
            document.body.appendChild(loadingIndicator);
        }
    }
    
    if (loadingIndicator) {
        loadingIndicator.style.display = show ? 'flex' : 'none';
    }
}

function switchView(viewType) {
    document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-view="${viewType}"]`).classList.add('active');
    
    document.getElementById('cardsView').style.display = 'none';
    document.getElementById('tableView').style.display = 'none';
    document.getElementById('compactView').style.display = 'none';
    
    currentView = viewType;
    
    switch(viewType) {
        case 'cards':
            document.getElementById('cardsView').style.display = 'grid';
            if (useApiMode) {
                generateCardsView();
            } else {
                filterCardsView();
            }
            break;
        case 'table':
            document.getElementById('tableView').style.display = 'block';
            generateTableView();
            break;
        case 'compact':
            document.getElementById('compactView').style.display = 'block';
            generateCompactView();
            break;
    }
    
    updatePagination();
}

function generateTableView() {
    const tableBody = document.getElementById('tableBody');
    tableBody.innerHTML = '';
    
    const objectsToShow = useApiMode ? filteredObjects : (() => {
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = pageSize === 'all' ? filteredObjects.length : startIndex + parseInt(pageSize);
        return filteredObjects.slice(startIndex, endIndex);
    })();
    
    objectsToShow.forEach(obj => {
        const row = document.createElement('tr');
        row.dataset.classification = obj.classification;
        row.dataset.discovery = obj.discovery_date;
        row.dataset.tag = obj.tag;
        row.classList.add(`tag-${obj.tag}`);
        
        // 轉義物件名稱中的單引號
        const escapedName = obj.name.replace(/'/g, "\\'");
        
        row.innerHTML = `
            <td class="object-name-cell">
                <a href="javascript:void(0)" onclick="quickView('${escapedName}')">${obj.name}</a>
            </td>
            <td>
                <span class="classification-badge ${obj.classification.toLowerCase().replace(' ', '-')}">${obj.classification}</span>
            </td>
            <td class="coord-cell">${obj.ra || 'N/A'}</td>
            <td class="coord-cell">${obj.dec || 'N/A'}</td>
            <td class="magnitude-cell">${obj.magnitude || 'N/A'}</td>
            <td class="redshift-cell">${obj.redshift || 'N/A'}</td>
            <td class="date-cell">${obj.discovery_date ? obj.discovery_date.slice(0, 10) : 'N/A'}</td>
            <td class="discoverer-cell">${obj.source ? obj.source.slice(0, 30) : 'N/A'}</td>
            <td>
                <span class="tag-badge ${obj.tag}">
                    ${getTagDisplayName(obj.tag)}
                </span>
            </td>
            <td class="actions-cell">
                <button class="action-btn view" onclick="quickView('${escapedName}')" title="View">View</button>
                ${window.isAdmin ? `<button class="action-btn edit" onclick="editTags('${escapedName}')" title="Edit Tags">Edit</button>` : ''}
            </td>
        `;
        
        tableBody.appendChild(row);
    });
}

function generateCompactView() {
    const compactContainer = document.getElementById('compactView');
    compactContainer.innerHTML = '';
    
    const objectsToShow = useApiMode ? filteredObjects : (() => {
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = pageSize === 'all' ? filteredObjects.length : startIndex + parseInt(pageSize);
        return filteredObjects.slice(startIndex, endIndex);
    })();
    
    objectsToShow.forEach(obj => {
        const item = document.createElement('div');
        item.className = 'compact-item';
        item.dataset.tag = obj.tag;
        item.classList.add(`tag-${obj.tag}`);
        
        const escapedName = obj.name.replace(/'/g, "\\'");
        
        item.innerHTML = `
            <div class="compact-main">
                <a href="javascript:void(0)" onclick="quickView('${escapedName}')" class="compact-name">${obj.name}</a>
                <span class="compact-classification ${obj.classification.toLowerCase().replace(' ', '-')}">${obj.classification}</span>
                <span class="compact-coords">${obj.ra || 'N/A'}, ${obj.dec || 'N/A'}</span>
                ${obj.magnitude ? `<span class="compact-magnitude">m=${parseFloat(obj.magnitude).toFixed(1)}</span>` : ''}
                ${obj.redshift ? `<span class="compact-redshift">z=${parseFloat(obj.redshift).toFixed(3)}</span>` : ''}
            </div>
            <div class="compact-meta">
                <span class="compact-date">${obj.discovery_date ? obj.discovery_date.slice(0, 10) : 'N/A'}</span>
                <span class="tag-indicator ${obj.tag}">
                    ${getTagIndicator(obj.tag)}
                </span>
            </div>
        `;
        
        compactContainer.appendChild(item);
    });
}

function generateCardsView() {
    const cardsContainer = document.getElementById('cardsView');
    
    if (!useApiMode) {
        filterCardsView();
        return;
    }
    
    cardsContainer.innerHTML = '';
    
    if (filteredObjects.length === 0) {
        cardsContainer.innerHTML = '<div class="no-objects">No objects found</div>';
        return;
    }
    
    filteredObjects.forEach(obj => {
        const card = document.createElement('div');
        card.className = 'object-card';
        card.dataset.tag = obj.tag;
        card.dataset.classification = obj.classification;
        card.classList.add(`tag-${obj.tag}`);
        
        const formattedRA = obj.ra ? parseFloat(obj.ra).toFixed(3) : 'N/A';
        const formattedDec = obj.dec ? parseFloat(obj.dec).toFixed(3) : 'N/A';
        
        card.innerHTML = `
            <div class="card-header">
                <div class="object-name">
                    <a href="javascript:void(0)" onclick="quickView('${obj.name.replace(/'/g, "\\'")}')">
                        ${obj.name}
                    </a>
                </div>
                <div class="classification-badge ${obj.classification.toLowerCase().replace(' ', '-')}">
                    ${obj.classification}
                </div>
            </div>
            
            <div class="card-content">
                <div class="coordinates">
                    <div class="coord-item">
                        <span class="coord-label">RA:</span>
                        <span class="coord-value">${formattedRA}</span>
                    </div>
                    <div class="coord-item">
                        <span class="coord-label">Dec:</span>
                        <span class="coord-value">${formattedDec}</span>
                    </div>
                </div>
                
                <div class="object-info">
                    ${obj.magnitude ? `
                        <div class="info-item">
                            <span>Discovery Mag = ${obj.magnitude}</span>
                        </div>
                    ` : ''}
                    
                    ${obj.redshift ? `
                        <div class="info-item">
                            <span>z = ${obj.redshift}</span>
                        </div>
                    ` : ''}
                    
                    ${obj.discovery_date ? `
                        <div class="info-item">
                            <span>Date: ${obj.discovery_date.substring(0, 10)}</span>
                        </div>
                    ` : ''}
                    
                    ${obj.source ? `
                        <div class="info-item">
                            <span>Source: ${obj.source}</span>
                        </div>
                    ` : ''}
                </div>
            </div>
            
            <div class="card-footer">
                <div class="tag-badge ${obj.tag}">
                    ${getTagDisplayName(obj.tag)}
                </div>
                <div class="last-update">
                    ${obj.last_update ? obj.last_update.substring(0, 16) : 'No update'}
                </div>
                <div class="card-actions">
                    <button class="quick-action" onclick="quickView('${obj.name.replace(/'/g, "\\'")}')">
                        View
                    </button>
                </div>
            </div>
        `;
        
        cardsContainer.appendChild(card);
    });
    
    console.log('Generated cards with tags:', filteredObjects.map(obj => `${obj.name}: ${obj.tag}`));
}

function getTagDisplayName(tag) {
    const tagNames = {
        'object': 'Inbox',
        'followup': 'Follow-up',
        'finished': 'Finished',
        'snoozed': 'Snoozed'
    };
    return tagNames[tag] || 'Inbox';
}

function getTagIndicator(tag) {
    const indicators = {
        'object': 'I',
        'followup': 'F',
        'finished': 'D',
        'snoozed': 'S'
    };
    return indicators[tag] || 'I';
}

function filterByStatus(status) {
    console.log(`Filtering by status: ${status}`);
    
    document.querySelectorAll('.small-stat-card.clickable').forEach(card => {
        card.classList.remove('active');
    });
    
    if (currentStatusFilter === status) {
        currentStatusFilter = '';
        clearStatusFilter();
        showNotification('Status filter cleared', 'info');
        return;
    }
    
    currentStatusFilter = status;
    
    const statusClasses = {
        'object': 'inbox',
        'followup': 'followup', 
        'finished': 'finished',
        'snoozed': 'snoozed'
    };
    
    const targetCard = document.querySelector(`.small-stat-card.${statusClasses[status]}.clickable`);
    if (targetCard) {
        targetCard.classList.add('active');
    }
    
    // Update filter state
    currentFilters.tag = status;
    
    // Update dropdown to match
    const tagFilter = document.getElementById('tagFilter');
    if (tagFilter) {
        tagFilter.value = status;
    }
    
    // Apply the filter
    currentPage = 1;
    
    if (useApiMode) {
        loadObjects(true);
    } else {
        applyLocalStatusFilter(status);
    }
    
    const statusNames = {
        'object': 'Inbox',
        'followup': 'Follow-up',
        'finished': 'Finished', 
        'snoozed': 'Snoozed'
    };
    
    showNotification(`Filtering ${statusNames[status]} objects`, 'info');
}

function applyStatusFilter(status) {
    if (useApiMode) {
        loadObjects(true);
    } else {
        applyLocalStatusFilter(status);
    }
    // DO NOT update counters here - counters should only be updated from dedicated stats API
}

function applyLocalStatusFilter(status) {
    filteredObjects = currentObjects.filter(obj => {
        return obj.tag === status;
    });
    
    currentPage = 1;
    refreshCurrentView();
    updatePagination();
}

function clearStatusFilter() {
    currentStatusFilter = '';
    currentFilters.tag = '';
    
    const tagFilter = document.getElementById('tagFilter');
    if (tagFilter) {
        tagFilter.value = '';
    }
    
    clearStatusFilterVisual();
    
    currentPage = 1;
    
    if (useApiMode) {
        loadObjects(true);
    } else {
        filteredObjects = [...currentObjects];
        refreshCurrentView();
        updatePagination();
    }
}

function updateStatusFilterVisual(status) {
    document.querySelectorAll('.small-stat-card.clickable').forEach(card => {
        card.classList.remove('active');
    });
    
    const statusClasses = {
        'object': 'inbox',
        'followup': 'followup',
        'finished': 'finished', 
        'snoozed': 'snoozed'
    };
    
    const targetCard = document.querySelector(`.small-stat-card.${statusClasses[status]}.clickable`);
    if (targetCard) {
        targetCard.classList.add('active');
    }
}

function clearStatusFilterVisual() {
    document.querySelectorAll('.small-stat-card.clickable').forEach(card => {
        card.classList.remove('active');
    });
}

function updateCardStyling(card, tag) {
    card.classList.remove('tag-object', 'tag-followup', 'tag-finished', 'tag-snoozed');
    card.classList.add(`tag-${tag}`);
    card.dataset.tag = tag;
    
    const tagBadge = card.querySelector('.tag-badge');
    if (tagBadge) {
        tagBadge.classList.remove('object', 'followup', 'finished', 'snoozed');
        tagBadge.classList.add(tag);
        tagBadge.textContent = getTagDisplayName(tag);
    }
    
    console.log(`Applied styling: tag-${tag} to card:`, card.querySelector('.object-name a')?.textContent);
}

function updateCounters() {
    // ALWAYS use the dedicated stats API for accurate counts - never calculate from local data
    loadInitialStats();
}

function updateCountersFromStats(stats) {
    if (!stats) return;
    
    console.log('Updating counters with stats:', stats);
    
    // Force all counters to match database stats exactly - NEVER calculate from filtered data
    document.getElementById('inboxCount').textContent = stats.inbox_count || 0;
    document.getElementById('followupCount').textContent = stats.followup_count || 0;
    document.getElementById('finishedCount').textContent = stats.finished_count || 0;
    document.getElementById('snoozedCount').textContent = stats.snoozed_count || 0;
    
    const atCountElement = document.querySelector('.big-stat-card.at .stat-number');
    const classifiedCountElement = document.querySelector('.big-stat-card.classified .stat-number');
    
    if (atCountElement) atCountElement.textContent = stats.at_count || 0;
    if (classifiedCountElement) classifiedCountElement.textContent = stats.classified_count || 0;
    
    const totalCountElement = document.querySelector('.total-count');
    if (totalCountElement) totalCountElement.textContent = `${stats.total_count || 0} objects`;
    
    // Clear any active filters and reset view if database is empty
    if (stats.total_count === 0) {
        currentStatusFilter = '';
        currentFilters.tag = '';
        
        const tagFilter = document.getElementById('tagFilter');
        if (tagFilter) tagFilter.value = '';
        
        clearStatusFilterVisual();
        
        // Clear the view containers
        const cardsContainer = document.getElementById('cardsView');
        const tableBody = document.getElementById('tableBody');
        const compactContainer = document.getElementById('compactView');
        
        if (cardsContainer) cardsContainer.innerHTML = '<div class="no-objects">No objects found</div>';
        if (tableBody) tableBody.innerHTML = '';
        if (compactContainer) compactContainer.innerHTML = '';
        
        // Reset global state
        currentObjects = [];
        filteredObjects = [];
        totalObjects = 0;
        currentPage = 1;
        
        updatePagination();
    }
}

function updatePagination() {
    const totalObjectsCount = useApiMode ? totalObjects : filteredObjects.length;
    const totalPagesCount = pageSize === 'all' ? 1 : Math.ceil(totalObjectsCount / pageSize);
    
    if (currentPage > totalPagesCount && totalPagesCount > 0) {
        currentPage = 1;
    }
    
    const startIndex = pageSize === 'all' ? 1 : (currentPage - 1) * pageSize + 1;
    const endIndex = pageSize === 'all' ? totalObjectsCount : Math.min(currentPage * pageSize, totalObjectsCount);
    
    const paginationInfoText = `Showing ${startIndex}-${endIndex} of ${totalObjectsCount} objects`;
    const topPaginationInfo = document.getElementById('topPaginationInfo');
    const bottomPaginationInfo = document.getElementById('paginationInfo');
    
    if (topPaginationInfo) topPaginationInfo.textContent = paginationInfoText;
    if (bottomPaginationInfo) bottomPaginationInfo.textContent = paginationInfoText;
    
    updatePaginationControls('topPaginationControls', totalPagesCount);
    updatePaginationControls('paginationControls', totalPagesCount);
    syncPageSizeSelectors();
}

function syncPageSizeSelectors() {
    const topSelect = document.getElementById('topPageSizeSelect');
    const bottomSelect = document.getElementById('pageSizeSelect');
    
    if (topSelect && bottomSelect) {
        topSelect.value = pageSize;
        bottomSelect.value = pageSize;
    }
}

function updatePaginationControls(controlsId, totalPagesCount) {
    const controls = document.getElementById(controlsId);
    if (!controls) return;
    
    controls.innerHTML = '';
    
    if (totalPagesCount > 1) {
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '‹ Prev';
        prevBtn.className = `pagination-btn ${currentPage === 1 ? 'disabled' : ''}`;
        if (currentPage > 1) {
            prevBtn.onclick = () => changePage(currentPage - 1);
        } else {
            prevBtn.disabled = true;
        }
        controls.appendChild(prevBtn);
        
        const startPage = Math.max(1, currentPage - 3);
        const endPage = Math.min(totalPagesCount, startPage + 6);
        
        if (startPage > 1) {
            const firstBtn = document.createElement('button');
            firstBtn.textContent = '1';
            firstBtn.className = 'pagination-btn';
            firstBtn.onclick = () => changePage(1);
            controls.appendChild(firstBtn);
            
            if (startPage > 2) {
                const ellipsis = document.createElement('span');
                ellipsis.className = 'pagination-ellipsis';
                ellipsis.textContent = '...';
                controls.appendChild(ellipsis);
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.textContent = i;
            pageBtn.className = `pagination-btn ${i === currentPage ? 'active' : ''}`;
            pageBtn.onclick = () => changePage(i);
            controls.appendChild(pageBtn);
        }
        
        if (endPage < totalPagesCount) {
            if (endPage < totalPagesCount - 1) {
                const ellipsis = document.createElement('span');
                ellipsis.className = 'pagination-ellipsis';
                ellipsis.textContent = '...';
                controls.appendChild(ellipsis);
            }
            
            const lastBtn = document.createElement('button');
            lastBtn.textContent = totalPagesCount;
            lastBtn.className = 'pagination-btn';
            lastBtn.onclick = () => changePage(totalPagesCount);
            controls.appendChild(lastBtn);
        }
        
        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next ›';
        nextBtn.className = `pagination-btn ${currentPage === totalPagesCount ? 'disabled' : ''}`;
        if (currentPage < totalPagesCount) {
            nextBtn.onclick = () => changePage(currentPage + 1);
        } else {
            nextBtn.disabled = true;
        }
        controls.appendChild(nextBtn);
    }
}

function changePage(page) {
    if (isLoading) return;
    
    currentPage = page;
    scrollToContentTop();
    
    if (useApiMode) {
        loadObjects();
    } else {
        refreshCurrentView();
        updatePagination();
    }
}

function scrollToContentTop() {
    const contentArea = document.querySelector('.view-controls');
    if (contentArea) {
        contentArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function changePageSize() {
    const newPageSize = event.target.value;
    pageSize = newPageSize;
    currentPage = 1;
    
    const topSelect = document.getElementById('topPageSizeSelect');
    const bottomSelect = document.getElementById('pageSizeSelect');
    
    if (topSelect) topSelect.value = newPageSize;
    if (bottomSelect) bottomSelect.value = newPageSize;
    
    scrollToContentTop();
    
    if (useApiMode) {
        loadObjects();
    } else {
        refreshCurrentView();
        updatePagination();
    }
}

function applySorting() {
    const select = document.getElementById('sortBy');
    sortBy = select.value;
    
    if (useApiMode) {
        loadObjects(true);
    } else {
        sortObjects();
    }
}

function toggleSortOrder() {
    sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    document.getElementById('sortOrderBtn').textContent = sortOrder === 'asc' ? '↑' : '↓';
    
    if (useApiMode) {
        loadObjects(true);
    } else {
        sortObjects();
    }
}

function sortObjects() {
    filteredObjects.sort((a, b) => {
        let aVal = a[sortBy] || '';
        let bVal = b[sortBy] || '';
        
        if (sortBy === 'discovery_date' || sortBy === 'last_update') {
            aVal = aVal ? new Date(aVal) : new Date('1900-01-01');
            bVal = bVal ? new Date(bVal) : new Date('1900-01-01');
        } else if (sortBy === 'magnitude') {
            aVal = aVal ? parseFloat(aVal) : 99;
            bVal = bVal ? parseFloat(bVal) : 99;
        } else if (sortBy === 'redshift') {
            aVal = parseFloat(aVal) || 0;
            bVal = parseFloat(bVal) || 0;
        } else {
            aVal = aVal.toString().toLowerCase();
            bVal = bVal.toString().toLowerCase();
        }
        
        if (sortOrder === 'asc') {
            return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
        } else {
            return aVal < bVal ? 1 : aVal > bVal ? -1 : 0;
        }
    });
    
    currentPage = 1;
    refreshCurrentView();
    updatePagination();
}

function refreshCurrentView() {
    if (currentView === 'cards') {
        generateCardsView();
    } else if (currentView === 'table') {
        generateTableView();
    } else if (currentView === 'compact') {
        generateCompactView();
    }
}

function filterCardsView() {
    const allCards = document.querySelectorAll('#cardsView .object-card');
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = pageSize === 'all' ? filteredObjects.length : startIndex + parseInt(pageSize);
    const objectsToShow = filteredObjects.slice(startIndex, endIndex);
    
    allCards.forEach(card => card.style.display = 'none');
    
    objectsToShow.forEach((obj, index) => {
        allCards.forEach(card => {
            const cardName = card.querySelector('.object-name a');
            if (cardName && cardName.textContent.trim() === obj.name) {
                card.style.display = 'block';
                card.style.order = index;
                updateCardStyling(card, obj.tag);
            }
        });
    });
}

function performSearch() {
    const searchInput = document.getElementById('searchInput');
    const searchTerm = searchInput.value.trim();
    
    if (!searchTerm) {
        showNotification('Please enter search criteria', 'warning');
        searchInput.focus();
        return;
    }
    
    console.log(`Performing search for: "${searchTerm}"`);
    
    useApiMode = true;
    currentFilters.search = searchTerm;
    currentStatusFilter = '';
    currentPage = 1;
    
    loadObjects(true);
    showNotification(`Searching for "${searchTerm}"...`, 'info');
    const url = new URL(window.location);
    url.searchParams.set('search', searchTerm);
    window.history.pushState({}, '', url);
}

function toggleAdvancedFilters() {
    const content = document.getElementById('advancedFiltersContent');
    const toggle = document.getElementById('advancedToggle');
    const arrow = toggle.querySelector('.toggle-arrow');
    
    if (content.style.display === 'none' || !content.classList.contains('show')) {
        content.style.display = 'block';
        setTimeout(() => content.classList.add('show'), 10);
        arrow.textContent = '▲';
        arrow.style.transform = 'rotate(180deg)';
        
        const filterGroups = content.querySelectorAll('.filter-group');
        filterGroups.forEach((group, index) => {
            group.style.animationDelay = `${(index + 1) * 0.1}s`;
        });
    } else {
        content.classList.remove('show');
        setTimeout(() => content.style.display = 'none', 400);
        arrow.textContent = '▼';
        arrow.style.transform = 'rotate(0deg)';
    }
}

function applyAdvancedFilters() {
    // Clear any existing status filter when applying advanced filters
    if (currentStatusFilter) {
        clearStatusFilterVisual();
        currentStatusFilter = '';
    }
    
    currentFilters.search = document.getElementById('searchInput').value.trim();
    currentFilters.classification = document.getElementById('classificationFilter').value;
    currentFilters.tag = document.getElementById('tagFilter').value;
    currentFilters.date_from = document.getElementById('dateFrom').value;
    currentFilters.date_to = document.getElementById('dateTo').value;
    currentFilters.app_mag_min = document.getElementById('appMagMin').value;
    currentFilters.app_mag_max = document.getElementById('appMagMax').value;
    currentFilters.redshift_min = document.getElementById('redshiftMin').value;
    currentFilters.redshift_max = document.getElementById('redshiftMax').value;
    currentFilters.discoverer = document.getElementById('discovererFilter').value;
    
    // If tag filter is set, update status filter and visual state
    if (currentFilters.tag && currentFilters.tag !== currentStatusFilter) {
        currentStatusFilter = currentFilters.tag;
        updateStatusFilterVisual(currentStatusFilter);
    } else if (!currentFilters.tag && currentStatusFilter) {
        currentStatusFilter = '';
        clearStatusFilterVisual();
    }
    
    currentPage = 1;
    
    if (Object.values(currentFilters).some(val => val !== '')) {
        useApiMode = true;
        loadObjects(true);
    } else {
        if (useApiMode) {
            loadObjects(true);
        } else {
            filteredObjects = [...currentObjects];
            refreshCurrentView();
            updatePagination();
        }
    }
    
    showNotification('Applying filters...', 'info');
}

function populateClassificationFilter() {
    if (useApiMode) {
        populateClassificationFilterFromAPI();
    } else {
        populateClassificationFilterFromObjects();
    }
}

async function populateClassificationFilterFromAPI() {
    try {
        const response = await fetch('/api/classifications');
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.classifications) {
                populateClassificationOptions(data.classifications);
                return;
            }
        }
        
        populateClassificationFilterFromObjects();
    } catch (error) {
        console.error('Error fetching classifications:', error);
        populateClassificationFilterFromObjects();
    }
}

function populateClassificationFilterFromObjects() {
    const classificationSet = new Set();
    
    if (currentObjects.length === 0) {
        const cardElements = document.querySelectorAll('#cardsView .object-card');
        cardElements.forEach(card => {
            const classificationElement = card.querySelector('.classification-badge');
            if (classificationElement) {
                const classification = classificationElement.textContent.trim() || 'AT';
                classificationSet.add(classification);
            }
        });
    } else {
        currentObjects.forEach(obj => {
            const classification = obj.type || obj.classification || 'AT';
            classificationSet.add(classification);
        });
    }
    
    if (classificationSet.size === 0) {
        classificationSet.add('AT');
        classificationSet.add('SN Ia');
        classificationSet.add('SN II');
        classificationSet.add('SN Ib/c');
    }
    
    const classifications = Array.from(classificationSet);
    populateClassificationOptions(classifications);
}

function populateClassificationOptions(classifications) {
    const sortedClassifications = classifications.sort((a, b) => {
        if (a === 'AT') return -1;
        if (b === 'AT') return 1;
        return a.localeCompare(b);
    });
    
    const classificationFilter = document.getElementById('classificationFilter');
    if (!classificationFilter) return;
    
    const firstOption = classificationFilter.firstElementChild;
    classificationFilter.innerHTML = '';
    if (firstOption && firstOption.value === '') {
        classificationFilter.appendChild(firstOption);
    } else {
        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = 'All Classifications';
        classificationFilter.appendChild(allOption);
    }
    
    sortedClassifications.forEach(classification => {
        const option = document.createElement('option');
        option.value = classification;
        option.textContent = classification;
        classificationFilter.appendChild(option);
    });
    
    const addModal = document.getElementById('addObjectModalOverlay');
    if (addModal && addModal.style.display === 'flex') {
        populateObjectTypeOptions();
    }
}

function clearAllFilters() {
    document.querySelectorAll('.small-stat-card.clickable').forEach(card => {
        card.classList.remove('active');
    });
    currentStatusFilter = '';
    
    document.getElementById('searchInput').value = '';
    document.getElementById('classificationFilter').value = '';
    document.getElementById('tagFilter').value = '';
    document.getElementById('dateFrom').value = '';
    document.getElementById('dateTo').value = '';
    document.getElementById('appMagMin').value = '';
    document.getElementById('appMagMax').value = '';
    document.getElementById('redshiftMin').value = '';
    document.getElementById('redshiftMax').value = '';
    document.getElementById('discovererFilter').value = '';
    
    currentFilters = {
        search: '',
        classification: '',
        tag: '',
        date_from: '',
        date_to: '',
        app_mag_min: '',
        app_mag_max: '',
        redshift_min: '',
        redshift_max: '',
        discoverer: ''
    };
    
    currentPage = 1;
    
    loadInitialStats();
    
    if (useApiMode) {
        loadObjects(true);
    } else {
        filteredObjects = [...currentObjects];
        refreshCurrentView();
        updatePagination();
    }
    
    showNotification('All filters cleared', 'info');
}

function forceRefreshAll() {
    console.log('Forcing complete refresh...');
    
    // Clear all local state
    currentObjects = [];
    filteredObjects = [];
    currentStatusFilter = '';
    currentFilters = {
        search: '',
        classification: '',
        tag: '',
        date_from: '',
        date_to: '',
        app_mag_min: '',
        app_mag_max: '',
        redshift_min: '',
        redshift_max: '',
        discoverer: ''
    };
    
    // Clear all filters in UI
    document.getElementById('searchInput').value = '';
    document.getElementById('classificationFilter').value = '';
    document.getElementById('tagFilter').value = '';
    document.getElementById('dateFrom').value = '';
    document.getElementById('dateTo').value = '';
    document.getElementById('appMagMin').value = '';
    document.getElementById('appMagMax').value = '';
    document.getElementById('redshiftMin').value = '';
    document.getElementById('redshiftMax').value = '';
    document.getElementById('discovererFilter').value = '';
    
    clearStatusFilterVisual();
    
    // Force API mode for fresh data
    useApiMode = true;
    currentPage = 1;
    
    // Reload everything
    loadInitialStats();
    loadObjects(true);
}

function manualTNSDownload() {
    const syncBtn = document.getElementById('syncBtn');
    const originalText = syncBtn.textContent;
    
    syncBtn.disabled = true;
    syncBtn.textContent = 'Downloading...';
    
    fetch('/api/tns/manual-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({hour_offset: 0})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const lastSyncElement = document.getElementById('lastSync');
            if (lastSyncElement) {
                const now = new Date();
                lastSyncElement.textContent = now.toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
            }
            
            showNotification(
                `Successfully imported ${data.imported_count} new objects and updated ${data.updated_count} existing objects`, 
                'success'
            );
            
            setTimeout(() => location.reload(), 2000);
        } else {
            showNotification('Download failed: ' + data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Download failed: Network error', 'error');
    })
    .finally(() => {
        syncBtn.disabled = false;
        syncBtn.textContent = originalText;
    });
}

function quickView(objectName) {
    console.log(`QuickView called with: "${objectName}"`);
    const pureYearLettersMatch = objectName.match(/^(\d{4})([a-zA-Z]+)$/);
    
    if (pureYearLettersMatch) {
        const year = pureYearLettersMatch[1];
        const letters = pureYearLettersMatch[2];
        console.log(`Using TNS format route: /object/${year}${letters}`);
        window.location.href = `/object/${year}${letters}`;
    } else {
        console.log(`Using generic route: /object/${encodeURIComponent(objectName)}`);
        window.location.href = `/object/${encodeURIComponent(objectName)}`;
    }
}

function editTags(objectName) {
    showNotification(`Edit tags for ${objectName} - Feature coming soon!`, 'info');
}

function showNotification(message, type = 'info') {
    const container = document.getElementById('notificationContainer');
    if (!container) {
        const newContainer = document.createElement('div');
        newContainer.id = 'notificationContainer';
        newContainer.className = 'notification-container';
        document.body.appendChild(newContainer);
    }
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    const finalContainer = document.getElementById('notificationContainer');
    finalContainer.appendChild(notification);
    
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

function manualAutoSnooze() {
    const autoSnoozeBtn = document.getElementById('autoSnoozeBtn');
    const originalText = autoSnoozeBtn.textContent;
    
    autoSnoozeBtn.disabled = true;
    autoSnoozeBtn.textContent = 'Processing...';
    
    showNotification('Running auto-snooze check...', 'info');
    
    fetch('/api/auto-snooze/manual-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const snoozedCount = data.snoozed_count || 0;
            const unsnoozedCount = data.unsnoozed_count || 0;
            const totalProcessed = data.total_processed || 0;
            
            if (totalProcessed > 0) {
                let message = `Auto-snooze completed: `;
                if (snoozedCount > 0) {
                    message += `${snoozedCount} objects snoozed`;
                }
                if (unsnoozedCount > 0) {
                    if (snoozedCount > 0) message += ', ';
                    message += `${unsnoozedCount} objects moved back to inbox`;
                }
                
                showNotification(message, 'success');
                
                // Refresh the page after a short delay to show updated counts
                setTimeout(() => {
                    loadInitialStats();
                    forceRefreshAll();
                }, 1500);
            } else {
                showNotification('Auto-snooze check completed - no changes needed', 'info');
            }
        } else {
            showNotification('Auto-snooze check failed: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        console.error('Error running auto-snooze:', error);
        showNotification('Auto-snooze check failed: Network error', 'error');
    })
    .finally(() => {
        autoSnoozeBtn.disabled = false;
        autoSnoozeBtn.textContent = originalText;
    });
}

function debugObjectTag(objectName) {
    fetch(`/debug/object/${encodeURIComponent(objectName)}`)
        .then(response => response.json())
        .then(data => {
            console.log('Debug results:', data);
            showNotification(`Debug results logged to console`, 'info');
        })
        .catch(error => {
            console.error('Debug error:', error);
            showNotification('Debug failed', 'error');
        });
}

function showAddModal() {
    const modal = document.getElementById('addObjectModalOverlay');
    if (modal) {
        modal.style.display = 'flex';
        resetAddObjectForm();
        
        // 直接複製 classificationFilter 的選項到 objectType
        populateObjectTypeOptions();
        
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('objectDiscoveryDate').value = today;
        
        setTimeout(() => {
            document.getElementById('objectName').focus();
        }, 100);
    }
}

function populateObjectTypeOptions() {
    const classificationFilter = document.getElementById('classificationFilter');
    const objectTypeSelect = document.getElementById('objectType');
    
    if (!classificationFilter || !objectTypeSelect) return;
    
    objectTypeSelect.innerHTML = '<option value="">Select type (optional)</option>';
    
    Array.from(classificationFilter.options).forEach((option, index) => {
        if (index > 0) {
            const newOption = document.createElement('option');
            newOption.value = option.value;
            newOption.textContent = option.textContent;
            objectTypeSelect.appendChild(newOption);
        }
    });
    
    const otherOption = document.createElement('option');
    otherOption.value = 'other';
    otherOption.textContent = 'Other (Custom)';
    objectTypeSelect.appendChild(otherOption);
    
    console.log('Populated object type options from classification filter');
}

function handleTypeSelection() {
    const typeSelect = document.getElementById('objectType');
    const customTypeGroup = document.getElementById('customTypeGroup');
    const customTypeInput = document.getElementById('customObjectType');
    
    if (!typeSelect || !customTypeGroup) return;
    
    const selectedValue = typeSelect.value;
    
    if (selectedValue === 'other') {
        customTypeGroup.style.display = 'block';
        setTimeout(() => {
            customTypeGroup.classList.add('show');
            if (customTypeInput) {
                customTypeInput.focus();
            }
        }, 10);
    } else {
        customTypeGroup.classList.remove('show');
        setTimeout(() => {
            customTypeGroup.style.display = 'none';
            if (customTypeInput) {
                customTypeInput.value = '';
            }
        }, 300);
    }
}

function closeAddObjectModal() {
    const modal = document.getElementById('addObjectModalOverlay');
    if (modal) {
        modal.style.display = 'none';
        resetAddObjectForm();
    }
}

function resetAddObjectForm() {
    const form = document.getElementById('addObjectForm');
    if (form) {
        form.reset();
    }
    
    const customTypeGroup = document.getElementById('customTypeGroup');
    if (customTypeGroup) {
        customTypeGroup.style.display = 'none';
        customTypeGroup.classList.remove('show');
    }
    
    const resultDiv = document.getElementById('addResult');
    if (resultDiv) {
        resultDiv.style.display = 'none';
    }
    
    const submitBtn = document.getElementById('addSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '➕ Add Object';
    }
}

function validateAddObjectForm() {
    const name = document.getElementById('objectName').value.trim();
    const ra = document.getElementById('objectRA').value.trim();
    const dec = document.getElementById('objectDEC').value.trim();
    const typeSelect = document.getElementById('objectType');
    const customTypeInput = document.getElementById('customObjectType');
    
    const errors = [];
    
    if (!name) {
        errors.push('Object name is required');
    } else if (name.length < 3) {
        errors.push('Object name must be at least 3 characters');
    }
    
    if (!ra) {
        errors.push('Right Ascension (RA) is required');
    } else {
        const raFloat = parseFloat(ra);
        if (isNaN(raFloat) || raFloat < 0 || raFloat >= 360) {
            errors.push('RA must be between 0 and 360 degrees');
        }
    }
    
    if (!dec) {
        errors.push('Declination (DEC) is required');
    } else {
        const decFloat = parseFloat(dec);
        if (isNaN(decFloat) || decFloat < -90 || decFloat > 90) {
            errors.push('DEC must be between -90 and 90 degrees');
        }
    }
    
    if (typeSelect && typeSelect.value === 'other') {
        const customType = customTypeInput ? customTypeInput.value.trim() : '';
        if (!customType) {
            errors.push('Custom object type is required when "Other" is selected');
        } else if (customType.length < 2) {
            errors.push('Custom object type must be at least 2 characters');
        } else if (customType.length > 50) {
            errors.push('Custom object type must be 50 characters or less');
        } else if (!/^[a-zA-Z0-9\s\-\/]+$/.test(customType)) {
            errors.push('Custom object type can only contain letters, numbers, spaces, hyphens, and forward slashes');
        }
    }
    
    const magnitude = document.getElementById('objectMagnitude').value.trim();
    if (magnitude) {
        const magFloat = parseFloat(magnitude);
        if (isNaN(magFloat) || magFloat < -5 || magFloat > 30) {
            errors.push('Magnitude should be between -5 and 30');
        }
    }
    
    return errors;
}

function submitAddObject() {
    console.log('Submitting add object form...');
    
    const errors = validateAddObjectForm();
    if (errors.length > 0) {
        showNotification('Please fix the following errors:\n' + errors.join('\n'), 'error');
        return;
    }
    
    const typeSelect = document.getElementById('objectType');
    const customTypeInput = document.getElementById('customObjectType');
    
    let objectType = 'Unknown';
    
    if (typeSelect && typeSelect.value) {
        if (typeSelect.value === 'other') {
            objectType = customTypeInput ? customTypeInput.value.trim() : 'AT';
        } else {
            objectType = typeSelect.value;
        }
    }
    
    const sourceValue = document.getElementById('objectSource').value;
    const source = sourceValue ? sourceValue.trim() : '';
    
    const formData = {
        name: document.getElementById('objectName').value.trim(),
        ra: parseFloat(document.getElementById('objectRA').value.trim()),
        dec: parseFloat(document.getElementById('objectDEC').value.trim()),
        type: objectType,
        magnitude: document.getElementById('objectMagnitude').value.trim() || null,
        discovery_date: document.getElementById('objectDiscoveryDate').value || null,
        source: source || null 
    };
    
    console.log('Form data:', formData);
    
    const submitBtn = document.getElementById('addSubmitBtn');
    const cancelBtn = document.getElementById('addCancelBtn');
    
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Adding...';
    cancelBtn.disabled = true;
    
    fetch('/api/objects', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
    })
    .then(response => {
        console.log('Response status:', response.status);
        return response.json();
    })
    .then(data => {
        console.log('Response data:', data);
        
        if (data.success) {
            showAddResult('success', 'Object Added Successfully!', 
                `${formData.name} has been added to the database with type "${objectType}".`);
            
            showNotification(`Object ${formData.name} added successfully!`, 'success');
            
            setTimeout(() => {
                closeAddObjectModal();
                forceRefreshAll();
            }, 2000);
            
        } else {
            showAddResult('error', 'Failed to Add Object', 
                data.error || 'An unknown error occurred.');
            showNotification('Failed to add object: ' + (data.error || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        console.error('Error adding object:', error);
        showAddResult('error', 'Network Error', 
            'Failed to connect to server. Please try again.');
        showNotification('Network error: ' + error.message, 'error');
    })
    .finally(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = '➕ Add Object';
        cancelBtn.disabled = false;
    });
}

function showAddResult(type, title, message) {
    const resultDiv = document.getElementById('addResult');
    const iconDiv = document.getElementById('addResultIcon');
    const textDiv = document.getElementById('addResultText');
    
    if (!resultDiv || !iconDiv || !textDiv) return;
    
    // 設置圖標
    if (type === 'success') {
        iconDiv.textContent = '✅';
        resultDiv.className = 'add-result success';
    } else {
        iconDiv.textContent = '❌';
        resultDiv.className = 'add-result error';
    }
    textDiv.innerHTML = `<strong>${title}</strong><br>${message}`;
    resultDiv.style.display = 'block';
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

window.isAdmin = document.querySelector('[data-admin="true"]') !== null;