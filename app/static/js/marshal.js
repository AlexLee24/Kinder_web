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

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Marshal page loaded, initializing...');
    
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
    setTimeout(() => {
        populateClassificationFilter();
    }, 1000);
    updateCounters();
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

    console.log('Marshal initialization complete');
});

// Check object count to determine mode
function checkObjectsCount() {
    const totalCountElement = document.querySelector('.total-count');
    if (totalCountElement) {
        const countText = totalCountElement.textContent;
        const countMatch = countText.match(/(\d+)/);
        if (countMatch) {
            const count = parseInt(countMatch[1]);
            totalObjects = count;
            
            console.log(`Detected ${count} objects in total`);
            
            // Auto switch to API mode if object count is high or no initial cards
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
        console.log('Using API mode for data loading');
        loadObjects();
        return;
    }
    
    const cardElements = document.querySelectorAll('#cardsView .object-card');
    currentObjects = [];
    
    console.log(`Found ${cardElements.length} card elements`);
    
    if (cardElements.length === 0) {
        console.log('No card elements found, switching to API mode');
        useApiMode = true;
        loadObjects();
        return;
    }
    
    cardElements.forEach(card => {
        const nameElement = card.querySelector('.object-name a');
        const classificationElement = card.querySelector('.classification-badge');
        const raElement = card.querySelector('.coord-item:nth-child(1) .coord-value');
        const decElement = card.querySelector('.coord-item:nth-child(2) .coord-value');
        const lastUpdateElement = card.querySelector('.last-update');
        
        let discoveryMag = '';
        let redshift = '';
        let discoveryDate = '';
        let source = '';
        
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
        
        const obj = {
            name: nameElement ? nameElement.textContent.trim() : '',
            type: classificationElement ? classificationElement.textContent.trim() : 'AT',
            classification: classificationElement ? classificationElement.textContent.trim() : 'AT',
            discovery_date: card.dataset.discovery || discoveryDate || '',
            tag: card.dataset.tag || 'object',
            magnitude: card.dataset.magnitude || discoveryMag || '',
            redshift: card.dataset.redshift || redshift || '',
            ra: raElement ? raElement.textContent.trim() : '',
            dec: decElement ? decElement.textContent.trim() : '',
            source: source || '',
            last_update: lastUpdateElement ? lastUpdateElement.textContent.trim() : ''
        };
        
        currentObjects.push(obj);
    });
    
    filteredObjects = [...currentObjects];
    console.log(`Total objects loaded from DOM: ${currentObjects.length}`);
}

function loadObjects(resetPage = false) {
    if (isLoading) {
        console.log('Already loading, skipping request');
        return;
    }
    
    if (resetPage) {
        currentPage = 1;
    }
    
    isLoading = true;
    showLoading(true);
    
    const loadingTimeout = setTimeout(() => {
        if (isLoading) {
            isLoading = false;
            showLoading(false);
            showNotification('Loading timeout, please try again', 'warning');
            console.error('Loading timeout exceeded');
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
    
    console.log(`API request: /api/objects?${params.toString()}`);
    
    fetch(`/api/objects?${params.toString()}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            clearTimeout(loadingTimeout);
            console.log('API response received:', data);
            
            if (!data) {
                throw new Error('Empty API response');
            }
            
            const objects = data.objects || [];
            console.log(`Loaded ${objects.length} objects, total: ${data.total || 0}`);
            
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
            
            if (data.stats) {
                updateCountersFromStats(data.stats);
            } else {
                updateCounters();
            }
            
            updatePagination();
            refreshCurrentView();
            
            // Repopulate classification filter if needed
            const classificationFilter = document.getElementById('classificationFilter');
            if (classificationFilter && classificationFilter.options.length <= 1) {
                populateClassificationFilterFromObjects();
            }
            
            const totalCountElement = document.querySelector('.total-count');
            if (totalCountElement) {
                totalCountElement.textContent = `${data.total || 0} objects`;
            }
            
            console.log(`Successfully updated view with ${filteredObjects.length} objects`);
        })
        .catch(error => {
            clearTimeout(loadingTimeout);
            console.error('API error:', error);
            
            let errorMsg = `Loading error: ${error.message}`;
            showNotification(errorMsg, 'error');
            
            if (error.message.includes('404')) {
                useApiMode = false;
                console.log('Switching back to DOM mode');
                showNotification('API unavailable, switching to DOM mode', 'warning');
                loadInitialObjects();
                populateClassificationFilterFromObjects();
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
            console.log('API request completed');
        });
}

// Map frontend field names to backend API fields
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

// Show/hide loading indicator
function showLoading(show) {
    console.log(`Loading indicator: ${show ? 'showing' : 'hiding'}`);
    
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
            console.warn('Content area not found, appending loading indicator to body');
        }
    }
    
    if (loadingIndicator) {
        loadingIndicator.style.display = show ? 'flex' : 'none';
    }
}

// Switch between different views
function switchView(viewType) {
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.classList.remove('active');
    });
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

// Generate table view
function generateTableView() {
    const tableBody = document.getElementById('tableBody');
    tableBody.innerHTML = '';
    
    // In API mode, no additional pagination needed
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
        row.dataset.magnitude = obj.magnitude;
        row.dataset.redshift = obj.redshift;
        
        row.innerHTML = `
            <td class="object-name-cell">
                <a href="#" onclick="quickView('${obj.name}')">${obj.name}</a>
            </td>
            <td>
                <span class="classification-badge ${obj.classification.toLowerCase().replace(' ', '-')}">${obj.classification}</span>
            </td>
            <td class="coord-cell">${obj.ra || 'N/A'}</td>
            <td class="coord-cell">${obj.dec || 'N/A'}</td>
            <td class="magnitude-cell">${obj.magnitude || 'N/A'}</td>
            <td class="magnitude-cell">N/A</td>
            <td class="redshift-cell">${obj.redshift || 'N/A'}</td>
            <td class="date-cell">${obj.discovery_date ? obj.discovery_date.slice(0, 10) : 'N/A'}</td>
            <td class="discoverer-cell">${obj.source ? obj.source.slice(0, 30) : 'N/A'}</td>
            <td>
                <span class="tag-badge ${obj.tag}">
                    ${getTagDisplayName(obj.tag)}
                </span>
            </td>
            <td class="actions-cell">
                <button class="action-btn view" onclick="quickView('${obj.name}')" title="View">View</button>
                ${window.isAdmin ? `<button class="action-btn edit" onclick="editTags('${obj.name}')" title="Edit Tags">Edit</button>` : ''}
            </td>
        `;
        
        tableBody.appendChild(row);
    });
}

// Generate compact view
function generateCompactView() {
    const compactContainer = document.getElementById('compactView');
    compactContainer.innerHTML = '';
    
    // In API mode, no additional pagination needed
    const objectsToShow = useApiMode ? filteredObjects : (() => {
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = pageSize === 'all' ? filteredObjects.length : startIndex + parseInt(pageSize);
        return filteredObjects.slice(startIndex, endIndex);
    })();
    
    objectsToShow.forEach(obj => {
        const item = document.createElement('div');
        item.className = 'compact-item';
        item.dataset.classification = obj.classification;
        item.dataset.discovery = obj.discovery_date;
        item.dataset.tag = obj.tag;
        item.dataset.magnitude = obj.magnitude;
        item.dataset.redshift = obj.redshift;
        
        item.innerHTML = `
            <div class="compact-main">
                <a href="#" onclick="quickView('${obj.name}')" class="compact-name">${obj.name}</a>
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

// Generate cards view for API mode
function generateCardsView() {
    const cardsContainer = document.getElementById('cardsView');
    
    if (!useApiMode) {
        console.log('Not in API mode, using DOM filtering');
        filterCardsView();
        return;
    }
    
    console.log(`Generating cards view for ${filteredObjects.length} objects`);
    cardsContainer.innerHTML = '';
    
    if (filteredObjects.length === 0) {
        cardsContainer.innerHTML = '<div class="no-objects">No objects found</div>';
        return;
    }
    
    // In API mode, no additional pagination needed as API returns paginated data
    console.log(`Showing ${filteredObjects.length} objects for page ${currentPage}`);
    
    filteredObjects.forEach(obj => {
        const card = document.createElement('div');
        card.className = 'object-card';
        card.dataset.classification = obj.classification;
        card.dataset.discovery = obj.discovery_date;
        card.dataset.tag = obj.tag;
        card.dataset.magnitude = obj.magnitude;
        card.dataset.redshift = obj.redshift;
        
        // Format coordinates to 3 decimal places
        const formattedRA = obj.ra ? parseFloat(obj.ra).toFixed(3) : 'N/A';
        const formattedDec = obj.dec ? parseFloat(obj.dec).toFixed(3) : 'N/A';
        
        card.innerHTML = `
            <div class="card-header">
                <div class="object-name">
                    <a href="#" onclick="quickView('${obj.name}')">
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
                    <button class="quick-action" onclick="quickView('${obj.name}')" title="Quick View">
                        View
                    </button>
                </div>
            </div>
        `;
        
        cardsContainer.appendChild(card);
    });
    
    console.log(`Generated ${filteredObjects.length} cards`);
}

// Helper functions
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

// Update counters
function updateCounters() {
    // In API mode, counters should be updated from stats
    if (useApiMode) {
        console.log('API mode: counters should be updated from stats');
        return;
    }
    
    const tagCounts = {
        object: 0,
        followup: 0,
        finished: 0,
        snoozed: 0
    };

    const classificationCounts = {
        at: 0,
        classified: 0
    };
    
    filteredObjects.forEach(obj => {
        // Count by tag
        if (tagCounts.hasOwnProperty(obj.tag)) {
            tagCounts[obj.tag]++;
        } else {
            tagCounts.object++;
        }
        
        // Count by classification
        if (!obj.classification || obj.classification === 'AT') {
            classificationCounts.at++;
        } else {
            classificationCounts.classified++;
        }
    });
    
    // Update tag counts
    document.getElementById('inboxCount').textContent = tagCounts.object;
    document.getElementById('followupCount').textContent = tagCounts.followup;
    document.getElementById('finishedCount').textContent = tagCounts.finished;
    document.getElementById('snoozedCount').textContent = tagCounts.snoozed;
    
    // Update main classification counts
    const atCountElement = document.querySelector('.big-stat-card.at .stat-number');
    const classifiedCountElement = document.querySelector('.big-stat-card.classified .stat-number');
    
    if (atCountElement) atCountElement.textContent = classificationCounts.at;
    if (classifiedCountElement) classifiedCountElement.textContent = classificationCounts.classified;
    
    // Update total count
    const totalCountElement = document.querySelector('.total-count');
    if (totalCountElement) {
        totalCountElement.textContent = `${filteredObjects.length} objects`;
    }
}

// Update counters from API stats
function updateCountersFromStats(stats) {
    if (!stats) return;
    
    // Update tag counts
    document.getElementById('inboxCount').textContent = stats.inbox_count || 0;
    document.getElementById('followupCount').textContent = stats.followup_count || 0;
    document.getElementById('finishedCount').textContent = stats.finished_count || 0;
    document.getElementById('snoozedCount').textContent = stats.snoozed_count || 0;
    
    // Update main classification counts
    const atCountElement = document.querySelector('.big-stat-card.at .stat-number');
    const classifiedCountElement = document.querySelector('.big-stat-card.classified .stat-number');
    
    if (atCountElement) atCountElement.textContent = stats.at_count || 0;
    if (classifiedCountElement) classifiedCountElement.textContent = stats.classified_count || 0;
}

// Pagination
function updatePagination() {
    const totalObjectsCount = useApiMode ? totalObjects : filteredObjects.length;
    const totalPagesCount = pageSize === 'all' ? 1 : Math.ceil(totalObjectsCount / pageSize);
    
    // Ensure currentPage is within valid range
    if (currentPage > totalPagesCount && totalPagesCount > 0) {
        currentPage = 1;
    }
    
    const startIndex = pageSize === 'all' ? 1 : (currentPage - 1) * pageSize + 1;
    const endIndex = pageSize === 'all' ? totalObjectsCount : Math.min(currentPage * pageSize, totalObjectsCount);
    
    // Update both pagination info sections
    const paginationInfoText = `Showing ${startIndex}-${endIndex} of ${totalObjectsCount} objects`;
    const topPaginationInfo = document.getElementById('topPaginationInfo');
    const bottomPaginationInfo = document.getElementById('paginationInfo');
    
    if (topPaginationInfo) {
        topPaginationInfo.textContent = paginationInfoText;
    }
    if (bottomPaginationInfo) {
        bottomPaginationInfo.textContent = paginationInfoText;
    }
    
    // Update both pagination controls
    updatePaginationControls('topPaginationControls', totalPagesCount);
    updatePaginationControls('paginationControls', totalPagesCount);
    
    // Sync page size selectors
    syncPageSizeSelectors();
    
    console.log(`Pagination updated: page ${currentPage} of ${totalPagesCount}, total objects: ${totalObjectsCount}`);
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
        // Previous button (always show, but disable if on first page)
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '‹ Prev';
        prevBtn.className = `pagination-btn ${currentPage === 1 ? 'disabled' : ''}`;
        if (currentPage > 1) {
            prevBtn.onclick = () => changePage(currentPage - 1);
        } else {
            prevBtn.disabled = true;
        }
        controls.appendChild(prevBtn);
        
        // Page numbers
        const startPage = Math.max(1, currentPage - 3);
        const endPage = Math.min(totalPagesCount, startPage + 6);
        
        // Add first page if we're not starting from it
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
        
        // Page number buttons
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.textContent = i;
            pageBtn.className = `pagination-btn ${i === currentPage ? 'active' : ''}`;
            pageBtn.onclick = () => changePage(i);
            controls.appendChild(pageBtn);
        }
        
        // Add last page if we're not ending with it
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
        
        // Next button (always show, but disable if on last page)
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
    if (isLoading) {
        console.log('Page change blocked - still loading');
        return;
    }
    
    console.log(`Changing to page ${page} from ${currentPage}`);
    currentPage = page;
    
    // Scroll to top of content area
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
        contentArea.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'start' 
        });
    }
}

function changePageSize() {
    const topSelect = document.getElementById('topPageSizeSelect');
    const bottomSelect = document.getElementById('pageSizeSelect');
    
    // Get the value from whichever select was changed
    const newPageSize = event.target.value;
    pageSize = newPageSize;
    currentPage = 1;
    
    // Sync both selectors
    if (topSelect) topSelect.value = newPageSize;
    if (bottomSelect) bottomSelect.value = newPageSize;
    
    // Scroll to top when changing page size
    scrollToContentTop();
    
    // In API mode, page size changes require new data
    if (useApiMode) {
        loadObjects();
    } else {
        refreshCurrentView();
        updatePagination();
    }
}

// Sorting functions
function applySorting() {
    const select = document.getElementById('sortBy');
    sortBy = select.value;
    
    // In API mode, sorting changes require new data
    if (useApiMode) {
        loadObjects(true);
    } else {
        sortObjects();
    }
}

function toggleSortOrder() {
    sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    document.getElementById('sortOrderBtn').textContent = sortOrder === 'asc' ? '↑' : '↓';
    
    // In API mode, sort order changes require new data
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
        
        // Handle different data types
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
        
        // Compare values based on sort order
        if (sortOrder === 'asc') {
            return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
        } else {
            return aVal < bVal ? 1 : aVal > bVal ? -1 : 0;
        }
    });
    
    currentPage = 1;
    refreshCurrentView();
    updatePagination();
    console.log(`Sorted by ${sortBy} (${sortOrder})`);
}

function refreshCurrentView() {
    console.log(`Refreshing ${currentView} view with ${filteredObjects.length} objects`);
    
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
    
    console.log(`Filtering cards: showing ${objectsToShow.length} out of ${filteredObjects.length} objects`);
    
    allCards.forEach(card => {
        card.style.display = 'none';
    });
    
    objectsToShow.forEach((obj, index) => {
        allCards.forEach(card => {
            const cardName = card.querySelector('.object-name a');
            if (cardName && cardName.textContent.trim() === obj.name) {
                card.style.display = 'block';
                card.style.order = index;
            }
        });
    });
}

// Search and filters
function performSearch() {
    const searchInput = document.getElementById('searchInput');
    const searchTerm = searchInput.value.trim().toLowerCase();
    
    if (!searchTerm) {
        showNotification('Please enter search criteria', 'warning');
        return;
    }
    
    // Enable API mode for searching
    useApiMode = true;
    currentFilters.search = searchTerm;
    loadObjects(true);
    
    showNotification(`Searching...`, 'info');
}

// Advanced filters
function toggleAdvancedFilters() {
    const content = document.getElementById('advancedFiltersContent');
    const toggle = document.getElementById('advancedToggle');
    const arrow = toggle.querySelector('.toggle-arrow');
    
    if (content.style.display === 'none' || !content.classList.contains('show')) {
        content.style.display = 'block';
        setTimeout(() => {
            content.classList.add('show');
        }, 10);
        arrow.textContent = '▲';
        arrow.style.transform = 'rotate(180deg)';
        
        const filterGroups = content.querySelectorAll('.filter-group');
        filterGroups.forEach((group, index) => {
            group.style.animationDelay = `${(index + 1) * 0.1}s`;
        });
    } else {
        content.classList.remove('show');
        setTimeout(() => {
            content.style.display = 'none';
        }, 400);
        arrow.textContent = '▼';
        arrow.style.transform = 'rotate(0deg)';
    }
}

function applyAdvancedFilters() {
    // Read all values from advanced filters
    currentFilters.classification = document.getElementById('classificationFilter').value;
    currentFilters.tag = document.getElementById('tagFilter').value;
    currentFilters.date_from = document.getElementById('dateFrom').value;
    currentFilters.date_to = document.getElementById('dateTo').value;
    currentFilters.app_mag_min = document.getElementById('appMagMin').value;
    currentFilters.app_mag_max = document.getElementById('appMagMax').value;
    currentFilters.redshift_min = document.getElementById('redshiftMin').value;
    currentFilters.redshift_max = document.getElementById('redshiftMax').value;
    currentFilters.discoverer = document.getElementById('discovererFilter').value;
    
    console.log('Applying filters:', currentFilters);
    
    // Always enable API mode when using advanced filters
    if (Object.values(currentFilters).some(val => val !== '')) {
        useApiMode = true;
        loadObjects(true);
    } else {
        // If all filter conditions are empty, show all objects
        filteredObjects = currentObjects.filter(obj => {
            return true;
        });
        
        currentPage = 1;
        updateCounters();
        refreshCurrentView();
        updatePagination();
    }
    
    showNotification('Applying filters...', 'info');
}

// Populate classification filter
function populateClassificationFilter() {
    if (useApiMode) {
        populateClassificationFilterFromAPI();
    } else {
        populateClassificationFilterFromObjects();
    }
}

// Fetch classifications from API
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
        
        // Fallback to current objects if API unavailable
        console.log('Classifications API not available, using current objects');
        populateClassificationFilterFromObjects();
        
    } catch (error) {
        console.error('Error fetching classifications:', error);
        populateClassificationFilterFromObjects();
    }
}

// Get classifications from current objects
function populateClassificationFilterFromObjects() {
    const classificationSet = new Set();
    
    // If no currentObjects, try reading from DOM
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
        // Collect from currentObjects
        currentObjects.forEach(obj => {
            const classification = obj.type || obj.classification || 'AT';
            classificationSet.add(classification);
        });
    }
    
    // Add default classifications if none found
    if (classificationSet.size === 0) {
        classificationSet.add('AT');
        classificationSet.add('SN Ia');
        classificationSet.add('SN II');
        classificationSet.add('SN Ib/c');
    }
    
    const classifications = Array.from(classificationSet);
    populateClassificationOptions(classifications);
}

// Populate classification options
function populateClassificationOptions(classifications) {
    // Sort classifications
    const sortedClassifications = classifications.sort((a, b) => {
        // Put AT first, then alphabetically
        if (a === 'AT') return -1;
        if (b === 'AT') return 1;
        return a.localeCompare(b);
    });
    
    // Get select element
    const classificationFilter = document.getElementById('classificationFilter');
    
    if (!classificationFilter) {
        console.error('Classification filter element not found');
        return;
    }
    
    // Clear existing options but keep first "All Classifications" option
    const firstOption = classificationFilter.firstElementChild;
    classificationFilter.innerHTML = '';
    if (firstOption && firstOption.value === '') {
        classificationFilter.appendChild(firstOption);
    } else {
        // Create "All Classifications" option if it doesn't exist
        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = 'All Classifications';
        classificationFilter.appendChild(allOption);
    }
    
    // Add options for each classification
    sortedClassifications.forEach(classification => {
        const option = document.createElement('option');
        option.value = classification;
        option.textContent = classification;
        classificationFilter.appendChild(option);
    });
    
    console.log(`Populated classification filter with ${sortedClassifications.length} types:`, sortedClassifications);
}

function clearAllFilters() {
    console.log('Clearing all filters...');
    
    // Clear all filter inputs
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
    
    // Reset filter conditions
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
    
    // Reload objects in API mode or reset in DOM mode
    if (useApiMode) {
        loadObjects(true);
    } else {
        filteredObjects = [...currentObjects];
        currentPage = 1;
        updateCounters();
        refreshCurrentView();
        updatePagination();
    }
    
    showNotification('All filters cleared', 'info');
}

// TNS Download
function manualTNSDownload() {
    const syncBtn = document.getElementById('syncBtn');
    const originalText = syncBtn.textContent;
    
    syncBtn.disabled = true;
    syncBtn.textContent = 'Downloading...';
    
    fetch('/api/tns/manual-download', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({hour_offset: 0})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update last sync display
            const lastSyncElement = document.getElementById('lastSync');
            if (lastSyncElement) {
                const now = new Date();
                lastSyncElement.textContent = now.toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
            }
            
            showNotification(
                `Successfully imported ${data.imported_count} new objects and updated ${data.updated_count} existing objects`, 
                'success'
            );
            
            // Reload after 2 seconds to show new data
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

// Modal functions
function quickView(objectName) {
    // Navigate to object detail page
    window.location.href = `/object/${encodeURIComponent(objectName)}`;
}

function editTags(objectName) {
    showNotification(`Edit tags for ${objectName} - Feature coming soon!`, 'info');
}

function showAddModal() {
    showNotification('Add object - Feature coming soon!', 'info');
}

function exportData() {
    showNotification('Export data - Feature coming soon!', 'info');
}

// Notification system
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
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

// Set global admin status
window.isAdmin = document.querySelector('[data-admin="true"]') !== null;