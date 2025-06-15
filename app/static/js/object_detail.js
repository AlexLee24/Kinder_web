// Global variables
let objectData = null;
let objectName = '';
let cleanObjectName = '';
let photometryData = [];
let isEditingPhotometry = false;
let photometryChanges = {
    toDelete: [],
    toAdd: []
};

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Object detail page loaded, initializing...');
    
    const upperLimitCheckbox = document.getElementById('addIsUpperLimit');
    const magnitudeErrorInput = document.getElementById('addMagnitudeError');
    
    if (upperLimitCheckbox && magnitudeErrorInput) {
        upperLimitCheckbox.addEventListener('change', function() {
            if (this.checked) {
                magnitudeErrorInput.disabled = true;
                magnitudeErrorInput.value = '';
                magnitudeErrorInput.placeholder = 'Not applicable for upper limits';
            } else {
                magnitudeErrorInput.disabled = false;
                magnitudeErrorInput.placeholder = '';
            }
        });
    }

    // Get object name from URL or page data
    const pathParts = window.location.pathname.split('/');
    objectName = decodeURIComponent(pathParts[pathParts.length - 1]);
    
    // Extract clean object name (year + letters only)
    cleanObjectName = extractYearAndLetters(objectName);
    console.log(`Original name: ${objectName}, Clean name (year+letters): ${cleanObjectName}`);
    
    if (objectName) {
        loadObjectData();
    } else {
        showNotification('Object name not found', 'error');
    }
    
    console.log('Object detail initialization complete');
});


// Extract year and letters from object name (e.g., "AT2024abc" -> "2024abc")
function extractYearAndLetters(fullName) {
    const match = fullName.match(/(\d{4}[a-zA-Z0-9]+)/);
    
    if (match) {
        const extracted = match[1];
        console.log(`Extracted year+letters: '${extracted}' from '${fullName}'`);
        return extracted;
    }
    
    console.log(`No year+letters pattern found in '${fullName}', using original name`);
    return fullName;
}

// Load object data
function loadObjectData() {
    if (!objectName) {
        showNotification('Object name not provided', 'error');
        return;
    }
    
    showLoading(true);
    
    console.log(`=== Starting search for: "${objectName}" ===`);
    console.log(`Clean name (year+letters): "${cleanObjectName}"`);
    
    const searchCandidates = [
        objectName,
        cleanObjectName,
    ];
    
    if (objectName !== cleanObjectName) {
        const withoutAT = objectName.replace(/^AT/, '');
        const withoutSN = objectName.replace(/^SN/, '');
        if (withoutAT !== objectName) searchCandidates.push(withoutAT);
        if (withoutSN !== objectName) searchCandidates.push(withoutSN);
    }
    
    console.log('Search candidates:', searchCandidates);
    
    searchWithCandidates(searchCandidates, 0);
}

function searchWithCandidates(candidates, index) {
    if (index >= candidates.length) {
        showLoading(false);
        showNotification('Object not found with any search term', 'error');
        return;
    }
    
    const candidate = candidates[index];
    console.log(`Trying search candidate [${index}]: "${candidate}"`);
    
    searchObjectByName(candidate)
        .then(data => {
            console.log(`Search result for "${candidate}":`, data);
            
            if (data.success && data.object) {
                objectData = data.object;
                console.log('✅ Object data loaded successfully:', objectData);
                updatePageContent();
                convertCoordinates();
                showLoading(false);
            } else {
                console.log(`❌ Search failed for "${candidate}", trying next...`);
                searchWithCandidates(candidates, index + 1);
            }
        })
        .catch(error => {
            console.error(`Error searching for "${candidate}":`, error);
            // 嘗試下一個候選
            searchWithCandidates(candidates, index + 1);
        });
}

// Helper function to search object by name
function searchObjectByName(searchName) {
    console.log(`API call: /api/object/${encodeURIComponent(searchName)}`);
    
    return fetch(`/api/object/${encodeURIComponent(searchName)}`)
        .then(response => {
            console.log(`Response status: ${response.status}`);
            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('API response:', data);
            return data;
        });
}

// Update page content with object data
function updatePageContent() {
    if (!objectData) return;
    
    const displayName = getFullObjectName(objectData) || objectName;
    
    // Update page title
    document.title = `${displayName} - Object Detail - Kinder`;
    
    // Update breadcrumb
    const breadcrumbCurrent = document.getElementById('breadcrumbCurrent');
    if (breadcrumbCurrent) {
        breadcrumbCurrent.textContent = displayName;
    }

    // Update basic information if elements exist
    updateElementText('objectName', displayName);
    updateElementText('objectType', objectData.type || 'AT');
    updateElementText('discoveryDate', objectData.discoverydate ? objectData.discoverydate.substring(0, 10) : 'Unknown');
    
    // Update coordinates
    updateElementText('raDecimal', objectData.ra ? parseFloat(objectData.ra).toFixed(6) + '°' : 'N/A');
    updateElementText('decDecimal', objectData.declination ? parseFloat(objectData.declination).toFixed(6) + '°' : 'N/A');
    
    // Update photometry
    updateElementText('discoveryMag', objectData.discoverymag || 'N/A');
    updateElementText('redshift', objectData.redshift || 'N/A');
    updateElementText('hostGalaxy', objectData.hostname || 'N/A');
    updateElementText('hostRedshift', objectData.host_redshift || 'N/A');
    
    // Update discovery information
    updateElementText('reportingGroup', objectData.reporting_group || 'N/A');
    updateElementText('discoverySurvey', objectData.source_group || 'N/A');
    updateElementText('timeReceived', objectData.time_received || 'N/A');
    
    // Update additional data
    updateElementText('remarks', objectData.remarks || 'None');
    updateElementText('bibcode', objectData.bibcode || 'None');
    updateElementText('externalId', objectData.ext_catalogs || 'None');
    
    // 直接使用資料庫中的狀態，移除快取相關代碼
    const currentStatus = objectData.tag;
    
    // Update badges
    updateClassificationBadge(objectData.type);
    updateStatusBadge(currentStatus);
    
    // Load location image
    loadLocationImage();

    // Load photometry and spectrum plots
    loadPhotometryPlot();
    loadSpectrumPlot();

    // Load comment
    loadComments();

    console.log('Page content updated');
}


function loadLocationImage() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showImageError('No coordinates available');
        return;
    }
    
    const ra = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);
    
    const jpg_url = `https://www.legacysurvey.org/viewer/cutout.jpg?ra=${ra}&dec=${dec}&pixscale=0.1&layer=ls-dr10-grz&size=600`;
    
    console.log(`Loading location image from: ${jpg_url}`);
    
    const imageElement = document.getElementById('locationImageSrc');
    const loadingElement = document.getElementById('imageLoading');
    const markerElement = document.getElementById('locationMarker');
    
    if (imageElement && loadingElement && markerElement) {
        // 顯示載入狀態
        loadingElement.style.display = 'flex';
        imageElement.style.display = 'none';
        markerElement.style.display = 'none';
        
        // 載入圖片
        const img = new Image();
        
        img.onload = function() {
            console.log('Location image loaded successfully');
            imageElement.src = jpg_url;
            imageElement.style.display = 'block';
            loadingElement.style.display = 'none';
            markerElement.style.display = 'block';
            
            window.currentLocationImageUrl = jpg_url;
        };
        
        img.onerror = function() {
            console.error('Failed to load location image');
            showImageError('Failed to load image');
        };
        
        img.src = jpg_url;
    }
}

function showImageError(message) {
    const locationImageContainer = document.getElementById('locationImage');
    const loadingElement = document.getElementById('imageLoading');
    const markerElement = document.getElementById('locationMarker');
    
    if (locationImageContainer && loadingElement) {
        loadingElement.style.display = 'none';
        markerElement.style.display = 'none';
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'image-error';
        errorDiv.innerHTML = `
            <span class="error-icon">❌</span>
            <span>${message}</span>
        `;
        
        const existingError = locationImageContainer.querySelector('.image-error');
        if (existingError) {
            existingError.remove();
        }
        
        locationImageContainer.appendChild(errorDiv);
    }
}

function updateClassificationBadge(type) {
    const badge = document.getElementById('classificationBadge');
    if (badge && type) {
        badge.className = `classification-badge ${type.toLowerCase()}`;
        badge.textContent = type.toUpperCase();
    }
}

function updateStatusBadge(tag) {
    const badge = document.getElementById('statusBadge');
    if (badge) {
        const status = tag || 'object';
        badge.className = `tag-badge ${status}`;
        badge.textContent = getStatusDisplayName(status);
        
        console.log('Status badge updated to:', status, getStatusDisplayName(status));
    }
}

// Get full object name from database object
function getFullObjectName(objData) {
    if (objData.name_prefix && objData.name) {
        return objData.name_prefix + objData.name;
    } else if (objData.name) {
        return objData.name;
    } else if (objData.name_prefix) {
        return objData.name_prefix;
    }
    return null;
}

// Helper function to update element text
function updateElementText(id, text) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = text;
    }
}

// Convert coordinates to HMS/DMS format
function convertCoordinates() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        return;
    }
    
    try {
        const ra = parseFloat(objectData.ra);
        const dec = parseFloat(objectData.declination);
        
        // Convert RA to HMS
        const raHMS = convertRAToHMS(ra);
        const raHMSElement = document.getElementById('raHMS');
        if (raHMSElement) {
            raHMSElement.textContent = raHMS;
        }
        
        // Convert Dec to DMS
        const decDMS = convertDecToDMS(dec);
        const decDMSElement = document.getElementById('decDMS');
        if (decDMSElement) {
            decDMSElement.textContent = decDMS;
        }
        
        console.log('Coordinates converted:', raHMS, decDMS);
    } catch (error) {
        console.error('Error converting coordinates:', error);
    }
}

// Convert RA decimal degrees to HMS
function convertRAToHMS(ra) {
    const hours = ra / 15.0;
    const h = Math.floor(hours);
    const minutes = (hours - h) * 60;
    const m = Math.floor(minutes);
    const seconds = (minutes - m) * 60;
    const s = seconds.toFixed(2);
    
    return `${h.toString().padStart(2, '0')}h ${m.toString().padStart(2, '0')}m ${s.padStart(5, '0')}s`;
}

// Convert Dec decimal degrees to DMS
function convertDecToDMS(dec) {
    const sign = dec >= 0 ? '+' : '-';
    const absDec = Math.abs(dec);
    const d = Math.floor(absDec);
    const minutes = (absDec - d) * 60;
    const m = Math.floor(minutes);
    const seconds = (minutes - m) * 60;
    const s = seconds.toFixed(1);
    
    return `${sign}${d.toString().padStart(2, '0')}° ${m.toString().padStart(2, '0')}' ${s.padStart(4, '0')}"`;
}

// Copy coordinates to clipboard
function copyCoordinates() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('No coordinates available to copy', 'warning');
        return;
    }
    
    const fullName = getFullObjectName(objectData) || objectName;
    const ra = parseFloat(objectData.ra).toFixed(6);
    const dec = parseFloat(objectData.declination).toFixed(6);
    const coordText = `${ra}\n${dec}`;
    
    navigator.clipboard.writeText(coordText).then(() => {
        showNotification('Coordinates copied to clipboard', 'success');
    }).catch(error => {
        console.error('Error copying coordinates:', error);
        showNotification('Failed to copy coordinates', 'error');
    });
}

// External link functions - 使用完整名稱
function openTNSPage() {
    if (!objectData) {
        showNotification('Object data not available', 'warning');
        return;
    }
    
    const fullName = getFullObjectName(objectData) || objectName;
    const tnsUrl = `https://www.wis-tns.org/object/${encodeURIComponent(cleanObjectName)}`;
    window.open(tnsUrl, '_blank');
}

function openDESI() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('Coordinates not available for DESI LS search', 'warning');
        return;
    }
    
    const ra = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);
    const DESIUrl = `https://www.legacysurvey.org/viewer?ra=${ra}&dec=${dec}&zoom=14&mark=${ra},${dec}&layer=ls-dr10-grz`
    window.open(DESIUrl, '_blank');
}

function openNED() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('Coordinates not available for NED search', 'warning');
        return;
    }
    
    const ra = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);
    
    // Convert RA to HH:MM:SS format
    const raHMS = convertRAToHMSForURL(ra);
    
    // Convert Dec to DD:MM:SS format  
    const decDMS = convertDecToDMSForURL(dec);
    
    console.log(`NED coordinates: RA=${raHMS}, Dec=${decDMS}`);
    
    // URL encode the coordinates (: becomes %3A)
    const raEncoded = encodeURIComponent(raHMS);
    const decEncoded = encodeURIComponent(decDMS);
    
    const nedUrl = `https://ned.ipac.caltech.edu/conesearch?search_type=Near%20Position%20Search&in_csys=Equatorial&in_equinox=J2000&ra=${raEncoded}&dec=${decEncoded}&radius=0.5&Z_CONSTRAINT=Unconstrained`;
    
    console.log(`Opening NED URL: ${nedUrl}`);
    window.open(nedUrl, '_blank');
}

// Convert RA decimal degrees to HH:MM:SS format for URLs
function convertRAToHMSForURL(ra) {
    const hours = ra / 15.0;
    const h = Math.floor(hours);
    const minutes = (hours - h) * 60;
    const m = Math.floor(minutes);
    const seconds = (minutes - m) * 60;
    const s = seconds.toFixed(2);
    
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.padStart(5, '0')}`;
}

// Convert Dec decimal degrees to DD:MM:SS format for URLs
function convertDecToDMSForURL(dec) {
    const sign = dec >= 0 ? '+' : '-';
    const absDec = Math.abs(dec);
    const d = Math.floor(absDec);
    const minutes = (absDec - d) * 60;
    const m = Math.floor(minutes);
    const seconds = (minutes - m) * 60;
    const s = seconds.toFixed(1);
    
    return `${sign}${d.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.padStart(4, '0')}`;
}

// Status management (admin only)
function changeStatus(newStatus) {
    if (!objectData) {
        showNotification('Object data not available', 'error');
        return;
    }
    
    const fullObjectName = getFullObjectName(objectData) || objectName;
    const statusNames = {
        'object': 'Inbox',
        'followup': 'Follow-up',
        'finished': 'Finished',
        'snoozed': 'Snoozed'
    };
    
    // Show confirmation for status change
    const currentStatus = objectData.tag || 'object';
    const currentStatusName = statusNames[currentStatus] || 'Unknown';
    const newStatusName = statusNames[newStatus] || newStatus;
    
    if (currentStatus === newStatus) {
        showNotification(`ℹ️ Object is already marked as ${newStatusName}`, 'info');
        return;
    }
    
    const confirmChange = confirm(`Change object status?\n\nFrom: ${currentStatusName}\nTo: ${newStatusName}\n\nObject: ${fullObjectName}`);
    
    if (!confirmChange) {
        return;
    }
    
    // Show loading state
    showLoading(true);
    
    fetch(`/api/object/${encodeURIComponent(fullObjectName)}/status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ status: newStatus })
    })
    .then(response => response.json())
    .then(data => {
        showLoading(false);
        
        if (data.success) {
            // Update local object data
            objectData.tag = newStatus;
            
            // Update status display immediately
            updateStatusDisplay(newStatus);
            
            // Show success notification
            showNotification(`✅ Status changed to ${newStatusName} successfully!`, 'success');
            
            // Optional: Slight page refresh for status-related elements
            setTimeout(() => {
                // Refresh only the status badge without full page reload
                const statusBadge = document.getElementById('statusBadge');
                if (statusBadge) {
                    statusBadge.className = `tag-badge ${newStatus}`;
                    statusBadge.textContent = newStatusName;
                }
            }, 500);
            
        } else {
            showNotification(`❌ Error changing status: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        showLoading(false);
        console.error('Error changing status:', error);
        showNotification('❌ Network error occurred while changing status', 'error');
    });
}

function updateStatusDisplay(newStatus) {
    const statusNames = {
        'object': 'Inbox',
        'followup': 'Follow-up', 
        'finished': 'Finished',
        'snoozed': 'Snoozed'
    };
    
    const statusBadge = document.getElementById('statusBadge');
    if (statusBadge) {
        statusBadge.className = `tag-badge ${newStatus}`;
        statusBadge.textContent = statusNames[newStatus] || newStatus;
    }
}

function getStatusDisplayName(status) {
    const statusNames = {
        'object': 'Inbox',
        'followup': 'Follow-up',
        'finished': 'Finished',
        'snoozed': 'Snoozed'
    };
    return statusNames[status] || 'Inbox';
}

function exportObject() {
    if (!objectData) {
        showNotification('No object data to export', 'warning');
        return;
    }
    
    const fullName = getFullObjectName(objectData) || objectName;
    
    // Create a simple JSON export
    const exportData = {
        name: fullName,
        type: objectData.type,
        ra: objectData.ra,
        declination: objectData.declination,
        discovery_date: objectData.discoverydate,
        discovery_magnitude: objectData.discoverymag,
        redshift: objectData.redshift,
        source_group: objectData.source_group,
        remarks: objectData.remarks
    };
    
    const dataStr = JSON.stringify(exportData, null, 2);
    const dataBlob = new Blob([dataStr], {type: 'application/json'});
    
    const link = document.createElement('a');
    link.href = URL.createObjectURL(dataBlob);
    link.download = `${fullName}_data.json`;
    link.click();
    
    showNotification('Object data exported', 'success');
}

// Loading and notification functions
function showLoading(show) {
    const loadingOverlay = document.getElementById('loadingOverlay');
    if (loadingOverlay) {
        loadingOverlay.style.display = show ? 'flex' : 'none';
    }
}

function getNotificationIcon(type) {
    const icons = {
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    };
    return icons[type] || 'ℹ️';
}

// Photometry plot loading with improved loading states
function loadPhotometryPlot() {
    if (!cleanObjectName) return;
    
    console.log('Loading photometry plot...');
    console.log('Clean object name:', cleanObjectName);
    
    const photometryContainer = document.querySelector('#photometryPlot');
    const loadingDiv = document.querySelector('#photometryLoading');
    
    // Show loading
    if (loadingDiv) loadingDiv.style.display = 'flex';
    if (photometryContainer) photometryContainer.innerHTML = '';
    
    const match = cleanObjectName.match(/(\d{4})([a-zA-Z]+)/);
    if (!match) {
        console.error('Cannot parse year and letters from:', cleanObjectName);
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (photometryContainer) {
            photometryContainer.innerHTML = `
                <div class="no-data">
                    <span class="no-data-icon">❌</span>
                    <span class="no-data-text">Invalid object name format</span>
                </div>
            `;
        }
        return;
    }
    
    const year = match[1];
    const letters = match[2];
    
    // Load both plot and raw data
    Promise.all([
        fetch(`/api/object/${year}${letters}/photometry/plot`),
        fetch(`/api/object/${year}${letters}/photometry`)
    ]).then(responses => {
        return Promise.all(responses.map(r => r.json()));
    }).then(([plotData, rawData]) => {
        console.log('Plot data:', plotData);
        console.log('Raw data:', rawData);
        
        // Hide loading
        if (loadingDiv) loadingDiv.style.display = 'none';
        
        // Store raw data for editing
        if (rawData.success) {
            photometryData = rawData.photometry || [];
        }
        
        // Display plot
        if (plotData.success) {
            if (photometryContainer) {
                if (plotData.plot_html) {
                    console.log('Inserting plot HTML into container...');
                    
                    photometryContainer.innerHTML = plotData.plot_html;
                    
                    setTimeout(() => {
                        try {
                            const scripts = photometryContainer.querySelectorAll('script');
                            console.log(`Found ${scripts.length} scripts in plot HTML`);
                            
                            scripts.forEach((script, index) => {
                                console.log(`Executing script ${index + 1}...`);
                                const newScript = document.createElement('script');
                                newScript.innerHTML = script.innerHTML;
                                document.head.appendChild(newScript);
                                document.head.removeChild(newScript);
                            });
                            
                            console.log('Photometry plot rendered successfully');
                        } catch (error) {
                            console.error('Error executing plot scripts:', error);
                            photometryContainer.innerHTML = `
                                <div class="no-data">
                                    <span class="no-data-icon">❌</span>
                                    <span class="no-data-text">Error rendering plot</span>
                                </div>
                            `;
                        }
                    }, 100);
                    
                } else {
                    photometryContainer.innerHTML = `
                        <div class="no-data">
                            <span class="no-data-icon">📊</span>
                            <span class="no-data-text">${plotData.message || 'No photometry data available'}</span>
                        </div>
                    `;
                }
            }
        } else {
            console.error('Error loading photometry plot:', plotData.error);
            if (photometryContainer) {
                photometryContainer.innerHTML = `
                    <div class="no-data">
                        <span class="no-data-icon">❌</span>
                        <span class="no-data-text">Error loading photometry data</span>
                    </div>
                `;
            }
        }
    }).catch(error => {
        console.error('Error loading photometry data:', error);
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (photometryContainer) {
            photometryContainer.innerHTML = `
                <div class="no-data">
                    <span class="no-data-icon">❌</span>
                    <span class="no-data-text">Error loading photometry data</span>
                </div>
            `;
        }
    });
}

function togglePhotometryEditMode() {
    if (isEditingPhotometry) {
        exitPhotometryEditMode();
    } else {
        enterPhotometryEditMode();
    }
}

function enterPhotometryEditMode() {
    if (photometryData.length === 0) {
        showNotification('No photometry data to edit', 'warning');
        return;
    }
    
    isEditingPhotometry = true;
    
    // Update button states
    const editBtn = document.getElementById('photometryEditBtn');
    const addBtn = document.getElementById('addPhotometryBtn');
    const plotContainer = document.getElementById('photometryPlot');
    const tableContainer = document.getElementById('photometryTableContainer');
    
    if (editBtn) {
        editBtn.innerHTML = '<span class="btn-icon">👁️</span> View Plot';
        editBtn.title = 'Switch back to plot view';
    }
    if (addBtn) addBtn.style.display = 'inline-flex';
    if (plotContainer) plotContainer.style.display = 'none';
    if (tableContainer) tableContainer.style.display = 'block';
    
    // Populate table
    populatePhotometryTable();
    
    // Reset changes
    photometryChanges = { toDelete: [], toAdd: [] };
}

function populatePhotometryTable() {
    const tableBody = document.getElementById('photometryTableBody');
    if (!tableBody) return;
    
    tableBody.innerHTML = '';
    
    photometryData.forEach((point, index) => {
        const row = document.createElement('tr');
        row.dataset.index = index;
        row.dataset.pointId = point.id;
        
        const isUpperLimit = point.magnitude_error === null || point.magnitude_error === 0;
        
        row.innerHTML = `
            <td>${point.mjd}</td>
            <td>${isUpperLimit ? '>' : ''}${point.magnitude}</td>
            <td>${point.magnitude_error || 'N/A'}</td>
            <td>${point.filter_name}</td>
            <td>${point.telescope || 'Unknown'}</td>
            <td>
                <button class="btn-small btn-danger" onclick="markForDeletion(${index}, ${point.id})" title="Delete this point">
                    <span class="btn-icon">🗑️</span>
                </button>
            </td>
        `;
        
        tableBody.appendChild(row);
    });
}

function markForDeletion(index, pointId) {
    const row = document.querySelector(`tr[data-index="${index}"]`);
    if (!row) return;
    
    if (row.classList.contains('marked-for-deletion')) {
        // Unmark
        row.classList.remove('marked-for-deletion');
        photometryChanges.toDelete = photometryChanges.toDelete.filter(id => id !== pointId);
        
        const btn = row.querySelector('button');
        if (btn) {
            btn.className = 'btn-small btn-danger';
            btn.innerHTML = '<span class="btn-icon">🗑️</span>';
            btn.title = 'Delete this point';
        }
    } else {
        // Mark for deletion
        row.classList.add('marked-for-deletion');
        if (!photometryChanges.toDelete.includes(pointId)) {
            photometryChanges.toDelete.push(pointId);
        }
        
        const btn = row.querySelector('button');
        if (btn) {
            btn.className = 'btn-small btn-secondary';
            btn.innerHTML = '<span class="btn-icon">↶</span>';
            btn.title = 'Undo deletion';
        }
    }
    
    console.log('Points marked for deletion:', photometryChanges.toDelete);
}

function showAddPhotometryForm() {
    const modal = document.getElementById('addPhotometryModal');
    if (modal) {
        modal.style.display = 'flex';
        
        // Reset form
        const form = document.getElementById('addPhotometryForm');
        if (form) form.reset();
        
        const errorDiv = document.getElementById('addFormError');
        if (errorDiv) errorDiv.style.display = 'none';
        
        // Set default telescope if available
        const telescopeInput = document.getElementById('addTelescope');
        if (telescopeInput && photometryData.length > 0) {
            const lastTelescope = photometryData[photometryData.length - 1].telescope;
            if (lastTelescope && lastTelescope !== 'Unknown') {
                telescopeInput.value = lastTelescope;
            }
        }
    }
}

function closeAddPhotometryModal() {
    const modal = document.getElementById('addPhotometryModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function exitPhotometryEditMode() {
    isEditingPhotometry = false;
    
    // Update button states
    const editBtn = document.getElementById('photometryEditBtn');
    const addBtn = document.getElementById('addPhotometryBtn');
    const plotContainer = document.getElementById('photometryPlot');
    const tableContainer = document.getElementById('photometryTableContainer');
    
    if (editBtn) {
        editBtn.innerHTML = '<span class="btn-icon">✏️</span> Edit';
        editBtn.title = 'Edit photometry data';
    }
    if (addBtn) addBtn.style.display = 'none';
    if (plotContainer) plotContainer.style.display = 'block';
    if (tableContainer) tableContainer.style.display = 'none';
}

function addPhotometryPoint() {
    const form = document.getElementById('addPhotometryForm');
    const errorDiv = document.getElementById('addFormError');
    const errorText = document.getElementById('addErrorText');
    
    if (!form) return;
    
    // Get form data
    const mjd = parseFloat(document.getElementById('addMjd').value);
    const magnitude = parseFloat(document.getElementById('addMagnitude').value);
    const magnitudeError = parseFloat(document.getElementById('addMagnitudeError').value);
    const filter = document.getElementById('addFilter').value.trim();
    const telescope = document.getElementById('addTelescope').value.trim() || 'Unknown';
    const isUpperLimit = document.getElementById('addIsUpperLimit').checked;
    
    // Validate data
    const errors = [];
    
    if (isNaN(mjd) || mjd < 50000 || mjd > 70000) {
        errors.push('Invalid MJD (should be between 50000-70000)');
    }
    
    if (isNaN(magnitude) || magnitude < 5 || magnitude > 30) {
        errors.push('Invalid magnitude (should be between 5-30)');
    }
    
    if (!isUpperLimit && (isNaN(magnitudeError) || magnitudeError < 0)) {
        errors.push('Invalid magnitude error (should be positive for detections)');
    }
    
    if (!filter || filter.length > 10) {
        errors.push('Invalid filter name');
    }
    
    if (errors.length > 0) {
        if (errorDiv && errorText) {
            errorText.innerHTML = errors.join('<br>');
            errorDiv.style.display = 'flex';
        }
        return;
    }
    
    // Hide error
    if (errorDiv) errorDiv.style.display = 'none';
    
    // Add to pending changes
    const newPoint = {
        mjd: mjd,
        magnitude: magnitude,
        magnitude_error: isUpperLimit ? null : magnitudeError,
        filter_name: filter,
        telescope: telescope,
        isNew: true
    };
    
    photometryChanges.toAdd.push(newPoint);
    
    // Add to local data for immediate display
    photometryData.push({
        ...newPoint,
        id: 'new_' + Date.now(), // Temporary ID
    });
    
    // Refresh table
    populatePhotometryTable();
    
    // Close modal
    closeAddPhotometryModal();
    
    showNotification('Point added to pending changes', 'success');
}

function cancelPhotometryEdit() {
    if (photometryChanges.toDelete.length > 0 || photometryChanges.toAdd.length > 0) {
        if (!confirm('You have unsaved changes. Are you sure you want to cancel?')) {
            return;
        }
    }
    
    // Reset changes and reload data
    photometryChanges = { toDelete: [], toAdd: [] };
    loadPhotometryPlot(); // This will reload fresh data
    exitPhotometryEditMode();
}

async function savePhotometryChanges() {
    if (photometryChanges.toDelete.length === 0 && photometryChanges.toAdd.length === 0) {
        showNotification('No changes to save', 'info');
        return;
    }
    
    const saveBtn = document.querySelector('#photometryTableContainer .btn-primary');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
    }
    
    let successCount = 0;
    let errorCount = 0;
    
    try {
        // Delete points
        for (const pointId of photometryChanges.toDelete) {
            try {
                const response = await fetch(`/api/photometry/${pointId}`, {
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });
                
                const result = await response.json();
                if (result.success) {
                    successCount++;
                } else {
                    errorCount++;
                    console.error('Failed to delete point:', pointId, result.error);
                }
            } catch (error) {
                errorCount++;
                console.error('Error deleting point:', pointId, error);
            }
        }
        
        // Add new points
        const match = cleanObjectName.match(/(\d{4})([a-zA-Z]+)/);
        if (match) {
            const year = match[1];
            const letters = match[2];
            
            for (const newPoint of photometryChanges.toAdd) {
                try {
                    const response = await fetch(`/api/object/${year}${letters}/photometry`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(newPoint)
                    });
                    
                    const result = await response.json();
                    if (result.success) {
                        successCount++;
                    } else {
                        errorCount++;
                        console.error('Failed to add point:', newPoint, result.error);
                    }
                } catch (error) {
                    errorCount++;
                    console.error('Error adding point:', newPoint, error);
                }
            }
        }
        
        // Show results
        if (successCount > 0) {
            showNotification(`Successfully saved ${successCount} changes`, 'success');
        }
        if (errorCount > 0) {
            showNotification(`${errorCount} changes failed to save`, 'error');
        }
        
        // Reload data and exit edit mode
        setTimeout(() => {
            loadPhotometryPlot();
            exitPhotometryEditMode();
        }, 1000);
        
    } catch (error) {
        console.error('Error saving changes:', error);
        showNotification('Error saving changes', 'error');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save Changes';
        }
    }
}

// Spectrum plot loading with improved loading states
function loadSpectrumPlot() {
    if (!cleanObjectName) return;
    
    console.log('Loading spectrum plot...');
    
    const spectrumContainer = document.querySelector('#spectrumPlot');
    const loadingDiv = document.querySelector('#spectrumLoading');
    
    // Show loading
    if (loadingDiv) loadingDiv.style.display = 'flex';
    if (spectrumContainer) spectrumContainer.innerHTML = '';
    
    const match = cleanObjectName.match(/(\d{4})([a-zA-Z]+)/);
    if (!match) {
        console.error('Cannot parse year and letters from:', cleanObjectName);
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (spectrumContainer) {
            spectrumContainer.innerHTML = `
                <div class="no-data">
                    <span class="no-data-icon">❌</span>
                    <span class="no-data-text">Invalid object name format</span>
                </div>
            `;
        }
        return;
    }
    
    const year = match[1];
    const letters = match[2];
    
    const apiUrl = `/api/object/${year}${letters}/spectrum/plot`;
    console.log('API URL:', apiUrl);
    
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            // Hide loading
            if (loadingDiv) loadingDiv.style.display = 'none';
            
            if (data.success) {
                if (spectrumContainer) {
                    if (data.plot_html) {
                        console.log('Inserting spectrum plot HTML into container...');
                        
                        spectrumContainer.innerHTML = data.plot_html;
                        
                        setTimeout(() => {
                            try {
                                const scripts = spectrumContainer.querySelectorAll('script');
                                console.log(`Found ${scripts.length} spectrum scripts`);
                                
                                scripts.forEach((script, index) => {
                                    console.log(`Executing spectrum script ${index + 1}...`);
                                    const newScript = document.createElement('script');
                                    newScript.innerHTML = script.innerHTML;
                                    document.head.appendChild(newScript);
                                    document.head.removeChild(newScript);
                                });
                                
                                console.log('Spectrum plot rendered successfully');
                            } catch (error) {
                                console.error('Error executing spectrum plot scripts:', error);
                                spectrumContainer.innerHTML = `
                                    <div class="no-data">
                                        <span class="no-data-icon">❌</span>
                                        <span class="no-data-text">Error rendering spectrum plot</span>
                                    </div>
                                `;
                            }
                        }, 100);
                        
                    } else {
                        spectrumContainer.innerHTML = `
                            <div class="no-data">
                                <span class="no-data-icon">📈</span>
                                <span class="no-data-text">${data.message || 'No spectrum data available'}</span>
                            </div>
                        `;
                    }
                }
            } else {
                console.error('Error loading spectrum plot:', data.error);
                if (spectrumContainer) {
                    spectrumContainer.innerHTML = `
                        <div class="no-data">
                            <span class="no-data-icon">❌</span>
                            <span class="no-data-text">Error loading spectrum data</span>
                        </div>
                    `;
                }
            }
        })
        .catch(error => {
            console.error('Error loading spectrum plot:', error);
            if (loadingDiv) loadingDiv.style.display = 'none';
            if (spectrumContainer) {
                spectrumContainer.innerHTML = `
                    <div class="no-data">
                        <span class="no-data-icon">❌</span>
                        <span class="no-data-text">Error loading spectrum data</span>
                    </div>
                `;
            }
        });
}

function loadSpecificSpectrum() {
    const selector = document.getElementById('spectrumSelector');
    if (!selector) return;
    
    const spectrumId = selector.value;
    console.log('Loading specific spectrum:', spectrumId);
    
    if (!cleanObjectName) return;
    
    const spectrumContainer = document.querySelector('#spectrumPlot');
    const loadingDiv = document.querySelector('#spectrumLoading');
    
    // Show loading
    if (loadingDiv) loadingDiv.style.display = 'flex';
    if (spectrumContainer) spectrumContainer.innerHTML = '';
    
    const url = spectrumId ? 
        `/api/object/${cleanObjectName}/spectrum/plot?spectrum_id=${spectrumId}` :
        `/api/object/${cleanObjectName}/spectrum/plot`;
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            // Hide loading
            if (loadingDiv) loadingDiv.style.display = 'none';
            
            if (data.success) {
                if (spectrumContainer) {
                    if (data.plot_html) {
                        spectrumContainer.innerHTML = data.plot_html;
                    } else {
                        spectrumContainer.innerHTML = `
                            <div class="no-data">
                                <span class="no-data-icon">📈</span>
                                <span class="no-data-text">${data.message || 'No spectrum data available'}</span>
                            </div>
                        `;
                    }
                }
            } else {
                console.error('Error loading spectrum plot:', data.error);
                if (spectrumContainer) {
                    spectrumContainer.innerHTML = `
                        <div class="no-data">
                            <span class="no-data-icon">❌</span>
                            <span class="no-data-text">Error loading spectrum data</span>
                        </div>
                    `;
                }
            }
        })
        .catch(error => {
            console.error('Error loading spectrum plot:', error);
            if (loadingDiv) loadingDiv.style.display = 'none';
            if (spectrumContainer) {
                spectrumContainer.innerHTML = `
                    <div class="no-data">
                        <span class="no-data-icon">❌</span>
                        <span class="no-data-text">Error loading spectrum data</span>
                    </div>
                `;
            }
        });
}

// Upload modal functions
function uploadPhotometry() {
    const modal = document.getElementById('uploadPhotometryModal');
    if (!modal) {
        console.error('Upload modal not found');
        return;
    }
    
    modal.style.display = 'flex';
    
    // Reset modal state
    resetUploadModal();
    
    // Setup file input
    setupFileUpload();
}

function uploadSpectrum() {
    showNotification('Spectrum upload - Feature coming soon!', 'info');
}

function closeUploadModal() {
    const modal = document.getElementById('uploadPhotometryModal');
    if (modal) {
        modal.style.display = 'none';
        resetUploadModal();
    }
}

function resetUploadModal() {
    const elements = {
        photometryFile: document.getElementById('photometryFile'),
        selectedFile: document.getElementById('selectedFile'),
        fileDropZone: document.getElementById('fileDropZone'),
        uploadPreview: document.getElementById('uploadPreview'),
        uploadError: document.getElementById('uploadError'),
        uploadBtn: document.getElementById('uploadBtn')
    };
    
    if (elements.photometryFile) elements.photometryFile.value = '';
    if (elements.selectedFile) elements.selectedFile.style.display = 'none';
    if (elements.fileDropZone) elements.fileDropZone.style.display = 'block';
    if (elements.uploadPreview) elements.uploadPreview.style.display = 'none';
    if (elements.uploadError) elements.uploadError.style.display = 'none';
    if (elements.uploadBtn) elements.uploadBtn.disabled = true;
}

function setupFileUpload() {
    const fileInput = document.getElementById('photometryFile');
    const dropZone = document.getElementById('fileDropZone');
    
    if (!fileInput || !dropZone) {
        console.error('File input elements not found');
        return;
    }
    
    // Remove existing event listeners to avoid duplicates
    const newDropZone = dropZone.cloneNode(true);
    dropZone.parentNode.replaceChild(newDropZone, dropZone);
    
    const newFileInput = fileInput.cloneNode(true);
    fileInput.parentNode.replaceChild(newFileInput, fileInput);
    
    // Click to select file
    newDropZone.addEventListener('click', () => {
        newFileInput.click();
    });
    
    // File selection
    newFileInput.addEventListener('change', handleFileSelect);
    
    // Drag and drop
    newDropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        newDropZone.classList.add('dragover');
    });
    
    newDropZone.addEventListener('dragleave', () => {
        newDropZone.classList.remove('dragover');
    });
    
    newDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        newDropZone.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            newFileInput.files = files;
            handleFileSelect();
        }
    });
}

function handleFileSelect() {
    const fileInput = document.getElementById('photometryFile');
    const file = fileInput.files[0];
    
    if (!file) return;
    
    // Show selected file
    const fileName = document.getElementById('fileName');
    const selectedFile = document.getElementById('selectedFile');
    const dropZone = document.getElementById('fileDropZone');
    
    if (fileName) fileName.textContent = file.name;
    if (selectedFile) selectedFile.style.display = 'flex';
    if (dropZone) dropZone.style.display = 'none';
    
    // Read and validate file
    const reader = new FileReader();
    reader.onload = function(e) {
        const content = e.target.result;
        validatePhotometryData(content);
    };
    reader.readAsText(file);
}

function removeSelectedFile() {
    const elements = {
        photometryFile: document.getElementById('photometryFile'),
        selectedFile: document.getElementById('selectedFile'),
        fileDropZone: document.getElementById('fileDropZone'),
        uploadPreview: document.getElementById('uploadPreview'),
        uploadError: document.getElementById('uploadError'),
        uploadBtn: document.getElementById('uploadBtn')
    };
    
    if (elements.photometryFile) elements.photometryFile.value = '';
    if (elements.selectedFile) elements.selectedFile.style.display = 'none';
    if (elements.fileDropZone) elements.fileDropZone.style.display = 'block';
    if (elements.uploadPreview) elements.uploadPreview.style.display = 'none';
    if (elements.uploadError) elements.uploadError.style.display = 'none';
    if (elements.uploadBtn) elements.uploadBtn.disabled = true;
}

function validatePhotometryData(content) {
    const lines = content.split('\n');
    const validData = [];
    const errors = [];
    let lineNumber = 0;
    
    for (let line of lines) {
        lineNumber++;
        line = line.trim();
        
        // Skip empty lines and comments
        if (!line || line.startsWith('#')) continue;
        
        // Split by whitespace
        const parts = line.split(/\s+/);
        
        if (parts.length < 4) {
            errors.push(`Line ${lineNumber}: Insufficient columns (need at least MJD, mag, err, filter)`);
            continue;
        }
        
        const mjd = parseFloat(parts[0]);
        const magStr = parts[1];
        const errStr = parts[2];
        const filter = parts[3];
        const telescope = parts[4] || 'Unknown';
        
        // Validate data
        const dataPoint = {
            lineNumber,
            mjd,
            magnitude: null,
            magnitude_error: null,
            filter,
            telescope,
            isUpperLimit: false,
            status: 'valid',
            statusText: 'Valid'
        };
        
        // Validate MJD
        if (isNaN(mjd) || mjd < 50000 || mjd > 70000) {
            dataPoint.status = 'error';
            dataPoint.statusText = 'Invalid MJD';
            errors.push(`Line ${lineNumber}: Invalid MJD value`);
        }
        
        // Handle magnitude (could be upper limit)
        if (magStr.startsWith('>')) {
            dataPoint.isUpperLimit = true;
            dataPoint.magnitude = parseFloat(magStr.substring(1));
            dataPoint.magnitude_error = null;
            if (dataPoint.status === 'valid') {
                dataPoint.status = 'warning';
                dataPoint.statusText = 'Upper Limit';
            }
        } else {
            dataPoint.magnitude = parseFloat(magStr);
            dataPoint.magnitude_error = parseFloat(errStr);
            
            if (isNaN(dataPoint.magnitude)) {
                dataPoint.status = 'error';
                dataPoint.statusText = 'Invalid magnitude';
                errors.push(`Line ${lineNumber}: Invalid magnitude value`);
            }
            
            if (isNaN(dataPoint.magnitude_error) || dataPoint.magnitude_error < 0) {
                if (dataPoint.status === 'valid') {
                    dataPoint.status = 'warning';
                    dataPoint.statusText = 'Invalid error';
                }
            }
        }
        
        // Validate filter
        if (!filter || filter.length > 10) {
            dataPoint.status = 'error';
            dataPoint.statusText = 'Invalid filter';
            errors.push(`Line ${lineNumber}: Invalid filter name`);
        }
        
        validData.push(dataPoint);
    }
    
    // Show results
    showPreview(validData, errors);
}

function showPreview(data, errors) {
    const previewDiv = document.getElementById('uploadPreview');
    const errorDiv = document.getElementById('uploadError');
    const tableBody = document.getElementById('previewTableBody');
    const summary = document.getElementById('previewSummary');
    const uploadBtn = document.getElementById('uploadBtn');
    
    if (!previewDiv || !tableBody || !uploadBtn) {
        console.error('Preview elements not found');
        return;
    }
    
    // Clear previous data
    tableBody.innerHTML = '';
    
    if (errors.length > 0 && errorDiv) {
        errorDiv.style.display = 'flex';
        const errorText = document.getElementById('errorText');
        if (errorText) errorText.innerHTML = errors.join('<br>');
    } else if (errorDiv) {
        errorDiv.style.display = 'none';
    }
    
    if (data.length === 0) {
        uploadBtn.disabled = true;
        return;
    }
    
    // Show preview table
    previewDiv.style.display = 'block';
    
    let validCount = 0;
    let warningCount = 0;
    let errorCount = 0;
    
    data.forEach(point => {
        const row = document.createElement('tr');
        
        const statusClass = point.status === 'valid' ? 'status-valid' : 
                           point.status === 'warning' ? 'status-warning' : 'status-error';
        
        row.innerHTML = `
            <td>${point.mjd.toFixed(3)}</td>
            <td>${point.isUpperLimit ? '>' : ''}${point.magnitude ? point.magnitude.toFixed(3) : 'N/A'}</td>
            <td>${point.magnitude_error ? point.magnitude_error.toFixed(3) : 'N/A'}</td>
            <td>${point.filter}</td>
            <td>${point.telescope}</td>
            <td class="${statusClass}">${point.statusText}</td>
        `;
        
        tableBody.appendChild(row);
        
        if (point.status === 'valid') validCount++;
        else if (point.status === 'warning') warningCount++;
        else errorCount++;
    });
    
    // Show summary
    if (summary) {
        summary.innerHTML = `
            <strong>Summary:</strong> ${data.length} total rows | 
            <span class="status-valid">${validCount} valid</span> | 
            <span class="status-warning">${warningCount} warnings</span> | 
            <span class="status-error">${errorCount} errors</span>
        `;
    }
    
    // Enable upload button if no errors
    uploadBtn.disabled = errorCount > 0;
}

async function uploadPhotometryData() {
    if (!cleanObjectName) {
        showNotification('Object name not found', 'error');
        return;
    }
    
    const match = cleanObjectName.match(/(\d{4})([a-zA-Z]+)/);
    if (!match) {
        showNotification('Invalid object name format', 'error');
        return;
    }
    
    const year = match[1];
    const letters = match[2];
    
    const tableBody = document.getElementById('previewTableBody');
    const uploadBtn = document.getElementById('uploadBtn');
    
    if (!tableBody || !uploadBtn) {
        console.error('Upload elements not found');
        return;
    }
    
    const rows = tableBody.querySelectorAll('tr');
    
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';
    
    let successCount = 0;
    let errorCount = 0;
    
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const cells = row.querySelectorAll('td');
        
        // Skip error rows
        if (cells[5].classList.contains('status-error')) {
            errorCount++;
            continue;
        }
        
        const mjd = parseFloat(cells[0].textContent);
        const magText = cells[1].textContent;
        const errText = cells[2].textContent;
        const filter = cells[3].textContent;
        const telescope = cells[4].textContent;
        
        // Parse magnitude (handle upper limits)
        let magnitude = null;
        let magnitude_error = null;
        
        if (magText.startsWith('>')) {
            magnitude = parseFloat(magText.substring(1));
            magnitude_error = null; // Upper limit
        } else {
            magnitude = parseFloat(magText);
            magnitude_error = errText !== 'N/A' ? parseFloat(errText) : null;
        }
        
        try {
            const response = await fetch(`/api/object/${year}${letters}/photometry`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    mjd: mjd,
                    magnitude: magnitude,
                    magnitude_error: magnitude_error,
                    filter: filter,
                    telescope: telescope
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                successCount++;
                // Update row status
                cells[5].className = 'status-valid';
                cells[5].textContent = 'Uploaded';
            } else {
                errorCount++;
                cells[5].className = 'status-error';
                cells[5].textContent = 'Failed';
            }
        } catch (error) {
            errorCount++;
            cells[5].className = 'status-error';
            cells[5].textContent = 'Failed';
            console.error('Upload error:', error);
        }
        
        // Small delay to avoid overwhelming the server
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    uploadBtn.textContent = 'Upload Data';
    uploadBtn.disabled = false;
    
    // Show results
    if (successCount > 0) {
        showNotification(`Successfully uploaded ${successCount} photometry points`, 'success');
        // Refresh the plot
        setTimeout(() => {
            loadPhotometryPlot();
            closeUploadModal();
        }, 1000);
    }
    
    if (errorCount > 0) {
        showNotification(`${errorCount} points failed to upload`, 'error');
    }
}

function showNotification(message, type = 'info') {
    // Create notification container if it doesn't exist
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.className = 'notification-container';
        document.body.appendChild(container);
    }
    
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 18px;">${type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'}</span>
            <span>${message}</span>
        </div>
    `;
    
    container.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 5000);
}

function openVisibilityPlot() {
    if (!objectData) {
        showNotification('Object data not available', 'error');
        return;
    }
    
    try {
        // Extract coordinates
        const ra = objectData.ra;
        const dec = objectData.declination;
        
        if (!ra || !dec) {
            showNotification('Object coordinates not available', 'error');
            return;
        }
        
        // Convert RA from decimal degrees to HMS format
        const raHMS = convertRADecimalToHMS(ra);
        const decDMS = convertDecDecimalToDMS(dec);
        
        // Create URL parameters
        const params = new URLSearchParams({
            object_name: cleanObjectName || objectName,
            ra: raHMS,
            dec: decDMS
        });
        
        const url = `/object_plot?${params.toString()}`;
        window.open(url, '_blank');
        
    } catch (error) {
        console.error('Error opening visibility plot:', error);
        showNotification('Error opening visibility plot', 'error');
    }
}

// Helper function to convert RA decimal degrees to HMS
function convertRADecimalToHMS(raDeg) {
    const ra = parseFloat(raDeg);
    const hours = ra / 15.0;
    const h = Math.floor(hours);
    const remainingMinutes = (hours - h) * 60;
    const m = Math.floor(remainingMinutes);
    const s = (remainingMinutes - m) * 60;
    
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}`;
}

// Helper function to convert Dec decimal degrees to DMS
function convertDecDecimalToDMS(decDeg) {
    const dec = parseFloat(decDeg);
    const sign = dec >= 0 ? '+' : '-';
    const absDec = Math.abs(dec);
    const d = Math.floor(absDec);
    const remainingMinutes = (absDec - d) * 60;
    const m = Math.floor(remainingMinutes);
    const s = (remainingMinutes - m) * 60;
    
    return `${sign}${d.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}`;
}


// Close modal when clicking outside
document.addEventListener('click', function(event) {
    const uploadModal = document.getElementById('uploadPhotometryModal');
    const addModal = document.getElementById('addPhotometryModal');
    
    if (uploadModal && event.target === uploadModal) {
        closeUploadModal();
    }
    if (addModal && event.target === addModal) {
        closeAddPhotometryModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const uploadModal = document.getElementById('uploadPhotometryModal');
        const addModal = document.getElementById('addPhotometryModal');
        
        if (uploadModal && uploadModal.style.display === 'flex') {
            closeUploadModal();
        } else if (addModal && addModal.style.display === 'flex') {
            closeAddPhotometryModal();
        }
    }
});

function loadComments() {
    if (!cleanObjectName) return;
    
    console.log('Loading comments for:', cleanObjectName);
    
    const commentsContainer = document.getElementById('commentsContainer');
    const commentsLoading = document.getElementById('commentsLoading');
    const noComments = document.getElementById('noComments');
    const commentsList = document.getElementById('commentsList');
    
    // Show loading
    if (commentsLoading) commentsLoading.style.display = 'flex';
    if (noComments) noComments.style.display = 'none';
    if (commentsList) commentsList.innerHTML = '';
    
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/comments`)
        .then(response => response.json())
        .then(data => {
            if (commentsLoading) commentsLoading.style.display = 'none';
            
            if (data.success) {
                displayComments(data.comments);
            } else {
                showCommentsError('Failed to load comments');
            }
        })
        .catch(error => {
            console.error('Error loading comments:', error);
            if (commentsLoading) commentsLoading.style.display = 'none';
            showCommentsError('Error loading comments');
        });
}

function displayComments(comments) {
    const commentsList = document.getElementById('commentsList');
    const noComments = document.getElementById('noComments');
    
    if (!comments || comments.length === 0) {
        if (noComments) noComments.style.display = 'flex';
        if (commentsList) commentsList.innerHTML = '';
        return;
    }
    
    if (noComments) noComments.style.display = 'none';
    if (!commentsList) return;
    
    commentsList.innerHTML = '';
    
    comments.forEach(comment => {
        const commentElement = createCommentElement(comment);
        commentsList.appendChild(commentElement);
    });
}

function createCommentElement(comment) {
    const commentDiv = document.createElement('div');
    commentDiv.className = 'comment-item';
    commentDiv.dataset.commentId = comment.id;
    
    // Format time - use the simpler approach
    const timeAgo = getTimeAgoSimple(comment.created_at);
    
    let createdAt;
    if (comment.created_at.includes('Z') || comment.created_at.includes('+') || comment.created_at.includes('-')) {
        createdAt = new Date(comment.created_at);
    } else {
        createdAt = new Date(comment.created_at + 'Z');
    }
    
    const fullTime = createdAt.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short'
    });
    
    // Check if current user is admin
    const isAdmin = document.querySelector('[data-admin="true"]') !== null;
    
    // Create avatar
    const avatarContent = comment.user_picture ? 
        `<img src="${comment.user_picture}" alt="${comment.user_name}" onerror="this.parentNode.innerHTML='👤'; this.parentNode.classList.add('no-image');">` :
        '👤';
    
    commentDiv.innerHTML = `
        <div class="comment-avatar ${!comment.user_picture ? 'no-image' : ''}">
            ${avatarContent}
        </div>
        <div class="comment-content">
            <div class="comment-header">
                <span class="comment-author">${escapeHtml(comment.user_name)}</span>
                <span class="comment-time" title="${fullTime}">${timeAgo}</span>
            </div>
            <div class="comment-text">${escapeHtml(comment.content)}</div>
        </div>
        ${isAdmin ? `
        <div class="comment-actions">
            <button class="comment-delete-btn" onclick="deleteComment(${comment.id})" title="Delete comment">
                🗑️
            </button>
        </div>
        ` : ''}
    `;
    
    return commentDiv;
}

function showAddCommentForm() {
    const addCommentForm = document.getElementById('addCommentForm');
    const addCommentBtn = document.getElementById('addCommentBtn');
    const commentContent = document.getElementById('commentContent');
    
    if (addCommentForm) {
        addCommentForm.style.display = 'block';
        if (commentContent) {
            commentContent.focus();
        }
    }
    
    if (addCommentBtn) {
        addCommentBtn.style.display = 'none';
    }
    
    // Setup character counter
    setupCharacterCounter();
}

function cancelAddComment() {
    const addCommentForm = document.getElementById('addCommentForm');
    const addCommentBtn = document.getElementById('addCommentBtn');
    const commentContent = document.getElementById('commentContent');
    
    if (addCommentForm) addCommentForm.style.display = 'none';
    if (addCommentBtn) addCommentBtn.style.display = 'flex';
    if (commentContent) commentContent.value = '';
    
    updateCharacterCounter();
}

function setupCharacterCounter() {
    const commentContent = document.getElementById('commentContent');
    const charCounter = document.getElementById('charCounter');
    
    if (!commentContent || !charCounter) return;
    
    // Remove existing event listeners
    commentContent.removeEventListener('input', updateCharacterCounter);
    
    // Add event listener
    commentContent.addEventListener('input', updateCharacterCounter);
    
    // Initial update
    updateCharacterCounter();
}

function updateCharacterCounter() {
    const commentContent = document.getElementById('commentContent');
    const charCounter = document.getElementById('charCounter');
    
    if (!commentContent || !charCounter) return;
    
    const length = commentContent.value.length;
    const maxLength = 1000;
    
    charCounter.textContent = `${length}/${maxLength}`;
    
    if (length > maxLength) {
        charCounter.classList.add('over-limit');
    } else {
        charCounter.classList.remove('over-limit');
    }
}

function submitComment() {
    const commentContent = document.getElementById('commentContent');
    
    if (!commentContent) return;
    
    const content = commentContent.value.trim();
    
    if (!content) {
        showNotification('Please enter a comment', 'warning');
        return;
    }
    
    if (content.length > 1000) {
        showNotification('Comment is too long (maximum 1000 characters)', 'error');
        return;
    }
    
    if (!cleanObjectName) {
        showNotification('Object name not found', 'error');
        return;
    }
    
    // Disable submit button
    const submitButton = document.querySelector('.add-comment-form .btn-primary');
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = 'Posting...';
    }
    
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/comments`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            content: content
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Comment posted successfully', 'success');
            cancelAddComment();
            loadComments(); // Reload comments
        } else {
            showNotification(`Failed to post comment: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error posting comment:', error);
        showNotification('Error posting comment', 'error');
    })
    .finally(() => {
        // Re-enable submit button
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = 'Post Comment';
        }
    });
}

function deleteComment(commentId) {
    if (!confirm('Are you sure you want to delete this comment?')) {
        return;
    }
    
    fetch(`/api/comments/${commentId}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Comment deleted successfully', 'success');
            
            // Remove comment from UI with animation
            const commentElement = document.querySelector(`[data-comment-id="${commentId}"]`);
            if (commentElement) {
                commentElement.classList.add('removing');
                setTimeout(() => {
                    loadComments(); // Reload comments
                }, 300);
            }
        } else {
            showNotification(`Failed to delete comment: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error deleting comment:', error);
        showNotification('Error deleting comment', 'error');
    });
}

function showCommentsError(message) {
    const commentsContainer = document.getElementById('commentsContainer');
    const noComments = document.getElementById('noComments');
    const commentsList = document.getElementById('commentsList');
    
    if (noComments) noComments.style.display = 'none';
    if (commentsList) commentsList.innerHTML = '';
    
    if (commentsContainer) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'comments-error';
        errorDiv.innerHTML = `
            <div class="comments-error-icon">❌</div>
            <div class="comments-error-text">${message}</div>
        `;
        
        // Remove existing error if any
        const existingError = commentsContainer.querySelector('.comments-error');
        if (existingError) {
            existingError.remove();
        }
        
        commentsContainer.appendChild(errorDiv);
    }
}

// Utility functions
function getTimeAgo(date) {
    const now = new Date();
    
    // Convert UTC date to local timezone for comparison
    const utcDate = new Date(date.getTime() + (date.getTimezoneOffset() * 60000));
    const localDate = new Date(utcDate.getTime() + (now.getTimezoneOffset() * 60000));
    
    const diffInSeconds = Math.floor((now - localDate) / 1000);
    
    if (diffInSeconds < 60) {
        return 'just now';
    } else if (diffInSeconds < 3600) {
        const minutes = Math.floor(diffInSeconds / 60);
        return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
    } else if (diffInSeconds < 86400) {
        const hours = Math.floor(diffInSeconds / 3600);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    } else if (diffInSeconds < 2592000) {
        const days = Math.floor(diffInSeconds / 86400);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    } else {
        // For older dates, show the actual local date
        return localDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
}

function getTimeAgoSimple(dateString) {
    const now = new Date();
    let commentDate;
    
    // Handle different date formats
    if (dateString.includes('Z') || dateString.includes('+') || dateString.includes('-')) {
        // Date string already has timezone info
        commentDate = new Date(dateString);
    } else {
        // Assume it's UTC if no timezone specified - add Z to indicate UTC
        commentDate = new Date(dateString + 'Z');
    }
    
    // Check if date is valid
    if (isNaN(commentDate.getTime())) {
        return 'Unknown time';
    }
    
    const diffInSeconds = Math.floor((now - commentDate) / 1000);
    
    if (diffInSeconds < 60) {
        return 'just now';
    } else if (diffInSeconds < 3600) {
        const minutes = Math.floor(diffInSeconds / 60);
        return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
    } else if (diffInSeconds < 86400) {
        const hours = Math.floor(diffInSeconds / 3600);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    } else if (diffInSeconds < 2592000) {
        const days = Math.floor(diffInSeconds / 86400);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    } else {
        return commentDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
}

// Edit object functionality
function editObjects() {
    if (!objectData) {
        showNotification('Object data not available', 'error');
        return;
    }
    
    showEditModal();
}

function showEditModal() {
    // Create edit modal if it doesn't exist
    let editModal = document.getElementById('editObjectModal');
    if (!editModal) {
        createEditModal();
        editModal = document.getElementById('editObjectModal');
    }
    
    // Populate form with current data
    populateEditForm();
    
    // Show modal
    editModal.style.display = 'flex';
}

function createEditModal() {
    const modalHTML = `
        <div class="modal" id="editObjectModal" style="display: none;">
            <div class="modal-content edit-modal-content">
                <div class="modal-header">
                    <h3>✏️ Edit Object Data</h3>
                    <span class="close" onclick="closeEditModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <form id="editObjectForm">
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editObjectName">Object Name</label>
                                <input type="text" id="editObjectName" readonly>
                                <div class="form-help">Object name cannot be changed</div>
                            </div>
                            
                            <div class="form-group">
                                <label for="editObjectType">Classification</label>
                                <input type="text" id="editObjectType" placeholder="e.g., AT, SN Ia, SN II">
                                <div class="form-help">Object classification type</div>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editObjectRA">Right Ascension (RA)</label>
                                <input type="number" step="0.000001" id="editObjectRA" placeholder="Decimal degrees (J2000)">
                                <div class="form-help">Decimal degrees (0-360)</div>
                            </div>
                            
                            <div class="form-group">
                                <label for="editObjectDEC">Declination (DEC)</label>
                                <input type="number" step="0.000001" id="editObjectDEC" placeholder="Decimal degrees (J2000)">
                                <div class="form-help">Decimal degrees (-90 to +90)</div>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editRedshift">Redshift</label>
                                <input type="number" step="0.0001" id="editRedshift" placeholder="e.g., 0.0123">
                                <div class="form-help">Spectroscopic or photometric redshift</div>
                            </div>
                            
                            <div class="form-group">
                                <label for="editDiscoveryMag">Discovery Magnitude</label>
                                <input type="number" step="0.01" id="editDiscoveryMag" placeholder="e.g., 18.5">
                                <div class="form-help">Discovery magnitude</div>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editDiscoveryFilter">Discovery Filter</label>
                                <input type="text" id="editDiscoveryFilter" placeholder="e.g., g, r, i, V, B">
                                <div class="form-help">Filter used for discovery magnitude</div>
                            </div>
                            
                            <div class="form-group">
                                <label for="editDiscoveryDate">Discovery Date</label>
                                <input type="date" id="editDiscoveryDate">
                                <div class="form-help">Date of discovery</div>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editSourceGroup">Source/Discoverer</label>
                                <input type="text" id="editSourceGroup" placeholder="e.g., ATLAS, ZTF, Gaia">
                                <div class="form-help">Discovering survey or group</div>
                            </div>
                            
                            <div class="form-group">
                                <label for="editReportingGroup">Reporting Group</label>
                                <input type="text" id="editReportingGroup" placeholder="e.g., University, Observatory">
                                <div class="form-help">Group that reported to TNS</div>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="editRemarks">Remarks</label>
                            <textarea id="editRemarks" rows="3" placeholder="Additional notes or remarks..." maxlength="200"></textarea>
                            <div class="form-help">Optional remarks (max 200 characters)</div>
                        </div>
                    </form>
                    
                    <div class="edit-result" id="editResult" style="display: none;">
                        <div class="result-content">
                            <div class="result-icon" id="editResultIcon"></div>
                            <div class="result-text" id="editResultText"></div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeEditModal()" id="editCancelBtn">Cancel</button>
                    <button class="btn btn-primary" onclick="submitEditObject()" id="editSubmitBtn">
                        💾 Save Changes
                    </button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHTML);
}

function populateEditForm() {
    if (!objectData) return;
    
    const fullName = getFullObjectName(objectData) || objectName;
    
    // Populate form fields with current data
    const fields = {
        'editObjectName': fullName,
        'editObjectType': objectData.type || '',
        'editObjectRA': objectData.ra || '',
        'editObjectDEC': objectData.declination || '',
        'editRedshift': objectData.redshift || '',
        'editDiscoveryMag': objectData.discoverymag || '',
        'editDiscoveryFilter': objectData.discoveryfilter || objectData.filter || '',
        'editDiscoveryDate': objectData.discoverydate ? objectData.discoverydate.substring(0, 10) : '',
        'editSourceGroup': objectData.source_group || '',
        'editReportingGroup': objectData.reporting_group || '',
        'editRemarks': objectData.remarks || ''
    };
    
    for (const [fieldId, value] of Object.entries(fields)) {
        const element = document.getElementById(fieldId);
        if (element) {
            element.value = value;
        }
    }
}

function closeEditModal() {
    const editModal = document.getElementById('editObjectModal');
    if (editModal) {
        editModal.style.display = 'none';
        
        // Reset form
        const form = document.getElementById('editObjectForm');
        if (form) form.reset();
        
        // Hide result
        const result = document.getElementById('editResult');
        if (result) result.style.display = 'none';
    }
}

function submitEditObject() {
    if (!objectData) {
        showNotification('Object data not available', 'error');
        return;
    }
    
    const fullObjectName = getFullObjectName(objectData) || objectName;
    
    // Collect form data
    const formData = {
        type: document.getElementById('editObjectType').value.trim() || null,
        ra: document.getElementById('editObjectRA').value || null,
        declination: document.getElementById('editObjectDEC').value || null,
        redshift: document.getElementById('editRedshift').value || null,
        discoverymag: document.getElementById('editDiscoveryMag').value || null,
        discoveryfilter: document.getElementById('editDiscoveryFilter').value.trim() || null,
        discoverydate: document.getElementById('editDiscoveryDate').value || null,
        source_group: document.getElementById('editSourceGroup').value.trim() || null,
        reporting_group: document.getElementById('editReportingGroup').value.trim() || null,
        remarks: document.getElementById('editRemarks').value.trim() || null
    };
    
    // Remove empty values
    const cleanData = {};
    for (const [key, value] of Object.entries(formData)) {
        if (value !== null && value !== '') {
            cleanData[key] = value;
        }
    }
    
    if (Object.keys(cleanData).length === 0) {
        showEditResult('error', 'No Changes', 'No fields were modified');
        return;
    }
    
    // Disable submit button
    const submitBtn = document.getElementById('editSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';
    }
    
    console.log('Submitting edit data:', cleanData);
    
    fetch(`/api/object/${encodeURIComponent(fullObjectName)}/edit`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(cleanData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showEditResult('success', 'Success!', data.message);
            showNotification('✅ Object updated successfully! Page will refresh in 2 seconds...', 'success');
            setTimeout(() => {
                closeEditModal();
                
                const overlay = document.createElement('div');
                overlay.style.cssText = `
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.8);
                    color: white;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    z-index: 10000;
                    font-size: 18px;
                    text-align: center;
                `;
                overlay.innerHTML = `
                    <div style="background: #28a745; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
                        ✅ Object "${fullObjectName}" updated successfully!
                    </div>
                    <div style="font-size: 16px;">
                        Refreshing page to show updated data...
                    </div>
                    <div style="margin-top: 20px;">
                        <div class="loading-spinner-small"></div>
                    </div>
                `;
                document.body.appendChild(overlay);
                
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }, 1000);
            
        } else {
            showEditResult('error', 'Error', data.error || 'Failed to update object');
        }
    })
    .catch(error => {
        console.error('Error updating object:', error);
        showEditResult('error', 'Error', 'Network error occurred');
        showNotification('❌ Network error occurred while updating object', 'error');
    })
    .finally(() => {
        // Re-enable submit button
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = '💾 Save Changes';
        }
    });
}

function showEditResult(type, title, message) {
    const resultDiv = document.getElementById('editResult');
    const iconDiv = document.getElementById('editResultIcon');
    const textDiv = document.getElementById('editResultText');
    
    if (resultDiv && iconDiv && textDiv) {
        resultDiv.style.display = 'block';
        resultDiv.className = `edit-result ${type}`;
        
        iconDiv.textContent = type === 'success' ? '✅' : '❌';
        textDiv.innerHTML = `<strong>${title}</strong><br>${message}`;
    }
}

// Delete object functionality
function deleteObjects() {
    if (!objectData) {
        showNotification('Object data not available', 'error');
        return;
    }
    
    const fullObjectName = getFullObjectName(objectData) || objectName;
    
    // Show confirmation dialog with more specific information
    const confirmationMessage = `⚠️ DELETE OBJECT CONFIRMATION ⚠️\n\n` +
                               `You are about to permanently DELETE:\n` +
                               `📌 Object: "${fullObjectName}"\n\n` +
                               `This action will permanently remove:\n` +
                               `• Object data from the database\n` +
                               `• All photometry data\n` +
                               `• All spectroscopy data\n` +
                               `• All comments and notes\n\n` +
                               `🚨 THIS CANNOT BE UNDONE! 🚨\n\n` +
                               `To confirm deletion, type "DELETE" exactly:`;
    
    const userInput = prompt(confirmationMessage);
    
    if (userInput !== 'DELETE') {
        if (userInput !== null) { // User didn't cancel
            showNotification('⚠️ Deletion cancelled - must type "DELETE" exactly', 'warning');
        }
        return;
    }
    
    // Additional confirmation for critical action
    const finalConfirm = confirm(`🚨 FINAL CONFIRMATION 🚨\n\nAre you absolutely sure you want to delete "${fullObjectName}"?\n\nThis action CANNOT be undone!\n\nClick OK to proceed with deletion.`);
    
    if (!finalConfirm) {
        showNotification('ℹ️ Deletion cancelled by user', 'info');
        return;
    }
    
    // Show loading state
    showLoading(true);
    showNotification('🗑️ Deleting object and all related data...', 'info');
    
    // Create immediate visual feedback
    const overlay = document.createElement('div');
    overlay.id = 'deleteOverlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.9);
        color: white;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        z-index: 10000;
        font-size: 18px;
        text-align: center;
    `;
    overlay.innerHTML = `
        <div style="background: #dc3545; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
            🗑️ Deleting object "${fullObjectName}"...
        </div>
        <div style="font-size: 16px; margin-bottom: 20px;">
            Please wait while we remove all data...
        </div>
        <div class="loading-spinner-small"></div>
        <div style="font-size: 14px; margin-top: 20px; opacity: 0.8;">
            This may take a few moments
        </div>
    `;
    document.body.appendChild(overlay);
    
    fetch(`/api/object/${encodeURIComponent(fullObjectName)}/delete`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        showLoading(false);
        
        if (data.success) {
            // Update overlay to show success
            overlay.innerHTML = `
                <div style="background: #28a745; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
                    ✅ Object "${fullObjectName}" deleted successfully!
                </div>
                <div style="font-size: 16px; margin-bottom: 20px;">
                    Redirecting to Marshal page...
                </div>
                <div class="loading-spinner-small"></div>
                <div style="font-size: 14px; margin-top: 20px; opacity: 0.8;">
                    You will be redirected in 3 seconds
                </div>
            `;
            
            // Show success notification
            showNotification(`✅ Object "${fullObjectName}" deleted successfully! Redirecting to Marshal...`, 'success');
            
            // Redirect to marshal page after a short delay
            setTimeout(() => {
                window.location.href = '/marshal';
            }, 3000);
            
        } else {
            // Remove overlay and show error
            document.body.removeChild(overlay);
            showNotification(`❌ Error deleting object: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        showLoading(false);
        
        // Remove overlay and show error
        const overlayElement = document.getElementById('deleteOverlay');
        if (overlayElement) {
            document.body.removeChild(overlayElement);
        }
        
        console.error('Error deleting object:', error);
        showNotification('❌ Network error occurred while deleting object', 'error');
    });
}

// Close edit modal when clicking outside or pressing Escape
document.addEventListener('click', function(event) {
    const editModal = document.getElementById('editObjectModal');
    if (editModal && event.target === editModal) {
        closeEditModal();
    }
});

document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const editModal = document.getElementById('editObjectModal');
        if (editModal && editModal.style.display === 'flex') {
            closeEditModal();
        }
    }
});

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}