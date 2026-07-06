// Global variables
const ICONS = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
    delete: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
    undo: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>',
    edit: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
    view: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    user: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
    save: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>',
    noData: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>',
    followup: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-telescope-icon lucide-telescope"><path d="m10.065 12.493-6.18 1.318a.934.934 0 0 1-1.108-.702l-.537-2.15a1.07 1.07 0 0 1 .691-1.265l13.504-4.44"/><path d="m13.56 11.747 4.332-.924"/><path d="m16 21-3.105-6.21"/><path d="M16.485 5.94a2 2 0 0 1 1.455-2.425l1.09-.272a1 1 0 0 1 1.212.727l1.515 6.06a1 1 0 0 1-.727 1.213l-1.09.272a2 2 0 0 1-2.425-1.455z"/><path d="m6.158 8.633 1.114 4.456"/><path d="m8 21 3.105-6.21"/><circle cx="12" cy="13" r="2"/></svg>',
    inbox: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-mailbox-icon lucide-mailbox"><path d="M22 17a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9.5C2 7 4 5 6.5 5H18c2.2 0 4 1.8 4 4v8Z"/><polyline points="15,9 18,9 18,11"/><path d="M6.5 5C9 5 11 7 11 9.5V17a2 2 0 0 1-2 2"/><line x1="6" x2="7" y1="10" y2="10"/></svg>',
    finished: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-book-check-icon lucide-book-check"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/><path d="m9 9.5 2 2 4-4"/></svg>',
    snoozed: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-snowflake-icon lucide-snowflake"><path d="m10 20-1.25-2.5L6 18"/><path d="M10 4 8.75 6.5 6 6"/><path d="m14 20 1.25-2.5L18 18"/><path d="m14 4 1.25 2.5L18 6"/><path d="m17 21-3-6h-4"/><path d="m17 3-3 6 1.5 3"/><path d="M2 12h6.5L10 9"/><path d="m20 10-1.5 2 1.5 2"/><path d="M22 12h-6.5L14 15"/><path d="m4 10 1.5 2L4 14"/><path d="m7 21 3-6-1.5-3"/><path d="m7 3 3 6h4"/></svg>',
    flag: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-flag"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/></svg>'
};

let objectData = null;
let objectName = '';
let cleanObjectName = '';
let photometryData = [];
let isEditingPhotometry = false;
let photometryChanges = {
    toDelete: [],
    toAdd: []
};
let editTableFilter = { telescope: '', filter: '' };
let editTableSort = { col: 'mjd', dir: 'asc' };
let editSelectedIds = new Set();

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Object detail page loaded, initializing...');
    
    // Default hiding page loading overlay to prevent blocking the whole UI
    const loadingOverlay = document.getElementById('loadingOverlay');
    if (loadingOverlay) loadingOverlay.style.display = 'none';

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
    
    _buildSpecChipsUI();

    if (objectName) {
        loadObjectData();
        // checkFlagStatus(); // Flag disabled
        checkPinStatus();
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
    
    // We do not show global loading initially anymore. Use inline loading later if needed.
    
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
        // showLoading(false);
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
                console.log('[SUCCESS] Object data loaded successfully:', objectData);
                updatePageContent();
                convertCoordinates();
                // showLoading(false);
            } else {
                console.log(`[ERROR] Search failed for "${candidate}", trying next...`);
                searchWithCandidates(candidates, index + 1);
            }
        })
        .catch(error => {
            console.error(`Error searching for "${candidate}":`, error);
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
async function updatePageContent() {
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
    const displayInternalNames = objectData.internal_names ? objectData.internal_names.split(',').map(s => s.trim()).join(', ') : 'N/A';
    updateElementText('internalName', displayInternalNames);
    updateElementText('timeReceived', objectData.time_received || 'N/A');
    
    // Update additional data
    updateElementText('remarks', objectData.remarks || 'None');
    updateElementText('bibcode', objectData.bibcode || 'None');
    updateElementText('externalId', objectData.ext_catalogs || 'None');
    
    const currentStatus = objectData.tag;
    
    // Update badges
    updateClassificationBadge(objectData.type);
    updateStatusBadge(currentStatus);
    renderCustomTags(objectData.tags);

    // Load all panels in parallel; detect starts immediately
    loadLocationImage();
    loadSpectrumPlot();
    loadComments();
    initializeAladinWhenReady();
    loadDetectData();
    loadDetectImages();  // Pre-fetch image_id so Chart tab works immediately
    loadPhotometryPlot();

    console.log('Page content updated');
}

function forceDetectRun() {
    const detectBody = document.getElementById('detectBody');
    if (!detectBody) return Promise.resolve();
    const detectName = encodeURIComponent(cleanObjectName || objectName);
    
    detectBody.innerHTML = `
        <div style="display:flex; justify-content:center; align-items:center; height:100%;">
            <div class="loading-spinner-small" style="margin-right:8px;"></div> Running cross-match...
        </div>
    `;

    return fetch(`/api/object/${detectName}/detect_cross_match?force=true&_ts=${Date.now()}`, { cache: 'no-store' })
        .then(async response => {
            const ct = response.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                const txt = await response.text();
                throw new Error(txt || `HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                renderDetectData(data.results);
                // Auto-update chart image if generated server-side
                if (data.detect_image_id) {
                    _detectImageId = data.detect_image_id;
                    // If user is on chart tab, refresh the view with new image
                    if (_detectTabMode === 'chart') _renderDetectChartView();
                }
            } else {
                detectBody.innerHTML = `<div style="color:#ff6b6b; padding:10px;">Error: ${data.error || 'Failed to run cross-match'}</div>`;
            }
        })
        .catch(err => {
            console.error('Error forcefully running detect:', err);
            // Fallback: if force-run fails but DB already has results, show those instead of generic network error.
            fetch(`/api/object/${detectName}/detect_cross_match?_ts=${Date.now()}`, { cache: 'no-store' })
                .then(async r => {
                    const ct = r.headers.get('content-type') || '';
                    if (!ct.includes('application/json')) {
                        const txt = await r.text();
                        throw new Error(txt || `HTTP ${r.status}`);
                    }
                    return r.json();
                })
                .then(d => {
                    if (d && d.success && Array.isArray(d.results) && d.results.length > 0) {
                        renderDetectData(d.results);
                    } else {
                        const msg = (err && err.message) ? err.message : 'Network error running cross-match';
                        detectBody.innerHTML = `<div style="color:#ff6b6b; padding:10px;">${msg}</div>`;
                    }
                })
                .catch(() => {
                    const msg = (err && err.message) ? err.message : 'Network error running cross-match';
                    detectBody.innerHTML = `<div style="color:#ff6b6b; padding:10px;">${msg}</div>`;
                });
        });
}

function renderDetectData(results) {
    _detectResultsCache = results;
    if (_detectTabMode === 'chart') return; // Don't overwrite chart view
    const detectBody = document.getElementById('detectBody');
    if (!detectBody) return;
    
    if (!results || results.length === 0) {
        detectBody.innerHTML = '<div style="display:flex; justify-content:center; align-items:center; height:100%; color:#888;">No matches found</div>';
        return;
    }

    let html = '<ul style="list-style:none; padding:0; margin:0;">';
    results.forEach(res => {
        let sep = parseFloat(res.separation_arcsec).toFixed(2);
        let catalog = res.catalog_name;
        let mdata = {};
        try {
            mdata = typeof res.match_data === 'string' ? JSON.parse(res.match_data) : (res.match_data || {});
        } catch(e) {
            mdata = {};
        }
        
        let extraInfo = '';
        const has = (obj, key) => !!obj && typeof obj === 'object' && key in obj && obj[key] !== null && obj[key] !== '';

        // Redshift: DB z column first, then match_data fallback
        const dbZ = (res.z !== null && res.z !== undefined) ? res.z : null;
        if (dbZ !== null) {
            extraInfo += ` | z=${parseFloat(dbZ).toFixed(4)}`;
        } else if (has(mdata, 'z_lens')) {
            extraInfo += ` | z_lens=${parseFloat(mdata.z_lens).toFixed(3)}`;
        } else if (has(mdata, 'z')) {
            extraInfo += ` | z=${parseFloat(mdata.z).toFixed(3)}`;
        } else if (has(mdata, 'z_spec')) {
            extraInfo += ` | z_spec=${parseFloat(mdata.z_spec).toFixed(3)}`;
        } else if (has(mdata, 'Z_SPEC')) {
            extraInfo += ` | z_spec=${parseFloat(mdata.Z_SPEC).toFixed(3)}`;
        }

        if (has(mdata, 'z_source')) extraInfo += ` | z_src=${parseFloat(mdata.z_source).toFixed(3)}`;
        if (has(mdata, 'grade')) extraInfo += ` | grade=${mdata.grade}`;
        if (has(mdata, 'lens_probability')) extraInfo += ` | prob=${parseFloat(mdata.lens_probability).toFixed(3)}`;
        if (has(mdata, 'rein')) extraInfo += ` | rein_E=${parseFloat(mdata.rein).toFixed(2)}"`;

        // Coords (match_ra/match_dec explicit columns, fallback to match_data)
        const mRa  = res.match_ra  !== null && res.match_ra  !== undefined ? res.match_ra  : (mdata.ra  || mdata._RAJ2000 || null);
        const mDec = res.match_dec !== null && res.match_dec !== undefined ? res.match_dec : (mdata.dec || mdata._DEJ2000 || null);
        if (mRa !== null && mDec !== null) {
            extraInfo += ` | coords=(${parseFloat(mRa).toFixed(4)}, ${parseFloat(mDec).toFixed(4)})`;
        }
        
        if (has(mdata, 'priority_tag')) {
            extraInfo += ` | <span style="color:#ffbe0b; font-size:0.8em; border:1px solid #ffbe0b; border-radius:4px; padding:1px 4px;">${mdata.priority_tag.replace(/_/g, ' ')}</span>`;
        } else if (has(mdata, 'type') && catalog.includes('DESI')) {
            extraInfo += ` | type=${mdata.type}`;
        } else if (has(mdata, 'type') && catalog.includes('LENS_CATALOGUE')) {
            extraInfo += ` | flag=${mdata.type}`;
        }

        html += `
            <li style="border-bottom: 1px solid rgba(255,255,255,0.1); padding: 8px 0; font-size: 0.9em;">
                <div style="font-weight:bold; color:#00f5d4;">${catalog.replace(/_/g, ' ')}</div>
                <div style="color:#ccc;">Sep: ${sep}" ${extraInfo}</div>
            </li>
        `;
    });
    html += '</ul>';
    
    detectBody.innerHTML = html;

    // DETECT chip summary (no longer used, kept as no-op)
    const chip = document.getElementById('detectChipSummary');
    if (chip && results.length > 0) {
        const best = results[0];
        const sep = parseFloat(best.separation_arcsec).toFixed(1);
        const cat = (best.catalog_name || '').replace(/_/g, ' ');
        chip.textContent = `${cat} ${sep}"`;
        chip.style.display = 'inline-flex';
    }
}

function loadDetectData() {
    const detectBody = document.getElementById('detectBody');
    if (!detectBody) return Promise.resolve();
    const detectName = encodeURIComponent(cleanObjectName || objectName);

    return fetch(`/api/object/${detectName}/detect_cross_match?_ts=${Date.now()}`, { cache: 'no-store' })
        .then(async response => {
            const ct = response.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                const txt = await response.text();
                throw new Error(txt || `HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                renderDetectData(data.results);
                if (data.detect_image_id) {
                    _detectImageId = data.detect_image_id;
                    if (_detectTabMode === 'chart') _renderDetectChartView();
                }
            } else {
                detectBody.innerHTML = `<div style="color:var(--danger-color); padding:10px;">${data.error || 'Failed to analyze'}</div>`;
            }
        })
        .catch(err => {
            console.error('DETECT Error:', err);
            const msg = (err && err.message) ? err.message : 'Error running DETECT';
            detectBody.innerHTML = `<div style="color:var(--danger-color); padding:10px;">${msg}</div>`;
        });
}

// ---------------------------------------------------------------------------
// DETECT tab toggle + finder chart (single image, overwrites on generate)
// ---------------------------------------------------------------------------

let _detectTabMode = 'data';   // 'data' | 'chart'
let _detectResultsCache = [];
let _detectImageId = null;

function switchDetectTab(mode) {
    _detectTabMode = mode;
    const tabData  = document.getElementById('detectTabData');
    const tabChart = document.getElementById('detectTabChart');
    if (tabData && tabChart) {
        const onStyle  = 'background:rgba(0,245,212,0.15); color:#00f5d4; font-weight:600;';
        const offStyle = 'background:transparent; color:#666; font-weight:400;';
        tabData.style.cssText  += mode === 'data'  ? onStyle : offStyle;
        tabChart.style.cssText += mode === 'chart' ? onStyle : offStyle;
    }
    if (mode === 'data') {
        renderDetectData(_detectResultsCache);
    } else {
        _renderDetectChartView();
    }
}

function _renderDetectChartView() {
    const detectBody = document.getElementById('detectBody');
    if (!detectBody) return;
    if (_detectImageId) {
        detectBody.innerHTML = `<img src="/detect_image_by_id/${_detectImageId}"
            alt="Finder chart"
            style="max-width:100%; border-radius:6px; display:block; margin:0 auto;" />`;
    } else {
        detectBody.innerHTML = '<div style="color:#555; padding:20px; text-align:center; font-size:0.85rem;">No finder chart yet — click Generate Chart</div>';
    }
}

function loadDetectImages() {
    const name = encodeURIComponent(cleanObjectName || objectName);
    fetch(`/api/object/${name}/detect_images`)
        .then(r => r.json())
        .then(data => {
            if (data.success && Array.isArray(data.images) && data.images.length > 0) {
                _detectImageId = data.images[0].image_id;
                if (_detectTabMode === 'chart') _renderDetectChartView();
            }
        })
        .catch(() => {});
}

function generateDetectImages() {
    const btn  = document.getElementById('detectImgGenBtn');
    const name = encodeURIComponent(cleanObjectName || objectName);
    if (btn) btn.disabled = true;

    // Switch to chart tab and show loading
    _detectTabMode = 'chart';
    const tabData  = document.getElementById('detectTabData');
    const tabChart = document.getElementById('detectTabChart');
    if (tabData)  { tabData.style.background  = 'transparent'; tabData.style.color  = '#666'; }
    if (tabChart) { tabChart.style.background = 'rgba(0,245,212,0.15)'; tabChart.style.color = '#00f5d4'; }

    const detectBody = document.getElementById('detectBody');
    if (detectBody) {
        detectBody.innerHTML = `<div style="display:flex; justify-content:center; align-items:center;
            height:100%; gap:8px; color:#888;"><div class="loading-spinner-small"></div> Generating finder chart…</div>`;
    }

    fetch(`/api/object/${name}/detect_images/generate`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btn) btn.disabled = false;
            if (data.success && Array.isArray(data.images) && data.images.length > 0) {
                _detectImageId = data.images[0].image_id;
                _renderDetectChartView();
            } else {
                if (detectBody) detectBody.innerHTML = `<div style="color:#ff6b6b; padding:20px; text-align:center;">${data.error || 'Generation failed'}</div>`;
            }
        })
        .catch(err => {
            if (btn) btn.disabled = false;
            if (detectBody) detectBody.innerHTML = '<div style="color:#ff6b6b; padding:20px; text-align:center;">Generation failed — check console</div>';
            console.error('generateDetectImages:', err);
        });
}

function loadLocationImage() {
    return new Promise((resolve) => {
        if (!objectData || !objectData.ra || !objectData.declination) {
            showImageError('No coordinates available');
            resolve();
            return;
        }
        
        const ra = parseFloat(objectData.ra);
        const dec = parseFloat(objectData.declination);
        
        const jpg_url = `https://www.legacysurvey.org/viewer/cutout.jpg?ra=${ra}&dec=${dec}&pixscale=0.1&layer=ls-dr10-grz&size=600&zoom=16&desi-spec-dr1`;
        
        console.log(`Loading location image from: ${jpg_url}`);
        
        const imageElement = document.getElementById('locationImageSrc');
        const loadingElement = document.getElementById('imageLoading');
        const markerElement = document.getElementById('locationMarker');
        
        if (imageElement && loadingElement && markerElement) {
            loadingElement.style.display = 'flex';
            imageElement.style.display = 'none';
            markerElement.style.display = 'none';
            
            const img = new Image();
            
            img.onload = function() {
                console.log('Location image loaded successfully');
                imageElement.src = jpg_url;
                imageElement.style.display = 'block';
                loadingElement.style.display = 'none';
                markerElement.style.display = 'block';
                
                window.currentLocationImageUrl = jpg_url;
                resolve();
            };
            
            img.onerror = function() {
                console.error('Failed to load location image');
                showImageError('Failed to load image');
                resolve();
            };
            
            img.src = jpg_url;
        } else {
            resolve();
        }
    });
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
            <span class="error-icon">${ICONS.error}</span>
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
        badge.className = 'badge type-badge';
        badge.textContent = type;
    }
}

function updateStatusBadge(tag) {
    const badge = document.getElementById('statusBadge');
    if (badge) {
        const status = tag || 'object';
        badge.className = `badge tag-badge ${status}`;
        badge.innerHTML = getStatusDisplayName(status);
    }
}

function renderCustomTags(tags) {
    const container = document.getElementById('tagsContainer');
    if (!container) return;
    if (!tags) { container.innerHTML = ''; return; }
    const parts = tags.split(',').map(s => s.trim()).filter(Boolean);
    container.innerHTML = parts.map(t => {
        const cls = t.toUpperCase().startsWith('EP') ? 'custom-tag ep' : 'custom-tag';
        return `<span class="${cls}">${t}</span>`;
    }).join('');
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

// Coordinate display mode: 'hms' or 'deg'
let _coordMode = 'hms';
let _raHMSStr = '', _decDMSStr = '';

// Convert coordinates to HMS/DMS format
function convertCoordinates() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        return;
    }
    try {
        const ra = parseFloat(objectData.ra);
        const dec = parseFloat(objectData.declination);
        _raHMSStr = convertRAToHMS(ra);
        _decDMSStr = convertDecToDMS(dec);
        _renderCoords();
        console.log('Coordinates converted:', _raHMSStr, _decDMSStr);
    } catch (error) {
        console.error('Error converting coordinates:', error);
    }
}

function _renderCoords() {
    const raEl  = document.getElementById('raCoord');
    const decEl = document.getElementById('decCoord');
    const raLbl = document.getElementById('raLabel');
    const decLbl = document.getElementById('decLabel');
    if (!raEl || !decEl) return;
    if (_coordMode === 'hms') {
        raEl.textContent  = _raHMSStr;
        decEl.textContent = _decDMSStr;
        if (raLbl)  raLbl.textContent  = 'RA (HMS)';
        if (decLbl) decLbl.textContent = 'Dec (DMS)';
    } else {
        const ra  = parseFloat(objectData.ra).toFixed(6);
        const dec = parseFloat(objectData.declination).toFixed(6);
        raEl.textContent  = ra + '°';
        decEl.textContent = (parseFloat(dec) >= 0 ? '+' : '') + dec + '°';
        if (raLbl)  raLbl.textContent  = 'RA (deg)';
        if (decLbl) decLbl.textContent = 'Dec (deg)';
    }
}

function toggleCoordMode() {
    _coordMode = (_coordMode === 'hms') ? 'deg' : 'hms';
    _renderCoords();
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

// Copy coordinates to clipboard — respects current display mode
function copyCoordinates() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('No coordinates available to copy', 'warning');
        return;
    }
    let coordText;
    if (_coordMode === 'hms') {
        coordText = `${_raHMSStr}  ${_decDMSStr}`;
    } else {
        const ra  = parseFloat(objectData.ra).toFixed(6);
        const dec = parseFloat(objectData.declination).toFixed(6);
        coordText = `${ra} ${dec}`;
    }
    navigator.clipboard.writeText(coordText).then(() => {
        showNotification(`Copied (${_coordMode === 'hms' ? 'HMS' : 'Degrees'})`, 'success');
    }).catch(error => {
        console.error('Error copying coordinates:', error);
        showNotification('Failed to copy coordinates', 'error');
    });
}

// Open finding chart page with current object pre-filled
function openFindingChart() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('No coordinates available', 'warning');
        return;
    }
    const name = encodeURIComponent(objectName || '');
    const ra   = encodeURIComponent(parseFloat(objectData.ra).toFixed(6));
    const dec  = encodeURIComponent(parseFloat(objectData.declination).toFixed(6));
    const url  = `/finding_chart?object_name=${name}&ra=${ra}&dec=${dec}&survey=DSS2+Red&fov=13&show_stars=0&auto=1`;
    window.open(url, '_blank');
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
    const DESIUrl = `https://www.legacysurvey.org/viewer?ra=${ra}&dec=${dec}&zoom=14&mark=${ra},${dec}&layer=ls-dr10-grz&zoom=16&desi-spec-dr1`
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

function openExtinction() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        showNotification('Coordinates not available for Extinction Calculator', 'warning');
        return;
    }
    
    const ra = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);
    
    // Format: lon=152.629166d&lat=+10.327177d
    // Ensure dec has + sign if positive
    const decStr = dec >= 0 ? `+${dec}` : `${dec}`;
    
    const extinctionUrl = `https://ned.ipac.caltech.edu/cgi-bin/nph-calc?in_csys=Equatorial&in_equinox=J2000.0&obs_epoch=2000.0&lon=${ra}d&lat=${decStr}d&pa=0.0&out_csys=Galactic&out_equinox=J2000.0`;
    
    window.open(extinctionUrl, '_blank');
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
        'followup': 'DETECT Follow up',
        'finished': 'Finished',
        'snoozed': 'Snoozed',
        'clear': 'Clear'
    };
    
    // Show confirmation for status change
    const currentStatus = objectData.tag || 'object';
    const currentStatusName = statusNames[currentStatus] || 'Unknown';
    const newStatusName = statusNames[newStatus] || newStatus;
    
    if (currentStatus === newStatus && newStatus !== 'clear') {
        showNotification(`Object is already marked as ${newStatusName}`, 'info');
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
            if (newStatus === 'clear') {
                location.reload();
                return;
            }

            // Update local object data
            objectData.tag = newStatus;
            
            // Update status display immediately
            updateStatusDisplay(newStatus);
            
            // Show success notification
            showNotification(`Status changed to ${newStatusName} successfully!`, 'success');
            
            // Optional: Slight page refresh for status-related elements
            setTimeout(() => {
                // Refresh only the status badge without full page reload
                const statusBadge = document.getElementById('statusBadge');
                if (statusBadge) {
                    statusBadge.className = `badge tag-badge ${newStatus}`;
                    statusBadge.innerHTML = getStatusDisplayName(newStatus);
                }
            }, 500);
            
        } else {
            showNotification(`Error changing status: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        showLoading(false);
        console.error('Error changing status:', error);
        showNotification('Network error occurred while changing status', 'error');
    });
}

function updateStatusDisplay(newStatus) {
    const statusNames = {
        'object': 'Inbox',
        'followup': 'DETECT Follow up',
        'finished': 'Finished',
        'snoozed': 'Snoozed',
        'clear': 'Clear'
    };
    
    const statusBadge = document.getElementById('statusBadge');
    if (statusBadge) {
        if (newStatus === 'clear') {
            statusBadge.className = 'badge tag-badge';
            statusBadge.textContent = 'Cleared';
        } else {
            statusBadge.className = `badge tag-badge ${newStatus}`;
            statusBadge.innerHTML = getStatusDisplayName(newStatus);
        }
    }
}

function getStatusDisplayName(status) {
    const icon = ICONS[status] || ICONS.inbox;
    // Add style to the SVG string for spacing with text
    const styledIcon = icon.replace('<svg', '<svg style="margin-right: 4px; vertical-align: text-bottom;"');
    
    const statusNames = {
        'object': 'Inbox',
        'followup': 'DETECT Follow up',
        'finished': 'Finished',
        'snoozed': 'Snoozed'
    };
    return `${styledIcon} ${statusNames[status] || 'Inbox'}`;
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
function showLoading(show, message = 'Loading object details...') {
    const loadingOverlay = document.getElementById('loadingOverlay');
    if (loadingOverlay) {
        loadingOverlay.style.display = show ? 'flex' : 'none';
        const loadingText = loadingOverlay.querySelector('.loading-text');
        if (loadingText) {
            loadingText.textContent = message;
        }
    }
}

function getNotificationIcon(type) {
    const icons = {
        'success': ICONS.success,
        'error': ICONS.error,
        'warning': ICONS.warning,
        'info': ICONS.info
    };
    return icons[type] || ICONS.info;
}

// Keep default LC view from over-zooming when points are very close in time.
function enforceMinLcXAxisSpan(figData, minSpanDays = 1) {
    if (!figData || !Array.isArray(figData.data) || figData.data.length === 0) return;

    const numericX = [];
    const dateXMs = [];

    figData.data.forEach(trace => {
        if (!trace || !Array.isArray(trace.x)) return;

        trace.x.forEach(value => {
            if (typeof value === 'number' && Number.isFinite(value)) {
                numericX.push(value);
                return;
            }

            if (typeof value !== 'string') return;
            const text = value.trim();
            if (!text) return;

            if (/^-?\d+(\.\d+)?$/.test(text)) {
                const num = Number(text);
                if (Number.isFinite(num)) numericX.push(num);
                return;
            }

            const ms = Date.parse(text);
            if (Number.isFinite(ms)) dateXMs.push(ms);
        });
    });

    figData.layout = figData.layout || {};
    figData.layout.xaxis = figData.layout.xaxis || {};

    if (numericX.length > 0 && dateXMs.length === 0) {
        const minX = Math.min(...numericX);
        const maxX = Math.max(...numericX);
        const span = maxX - minX;
        if (span < minSpanDays) {
            const center = (minX + maxX) / 2;
            const forcedMin = center - minSpanDays / 2;
            const forcedMax = center + minSpanDays / 2;
            figData.layout.xaxis.range = [forcedMin, forcedMax];
            figData.layout.xaxis.autorange = false;
            figData.layout.xaxis.tickmode = 'linear';
            figData.layout.xaxis.dtick = minSpanDays;
            figData.layout.xaxis.tick0 = Math.floor(forcedMin);
        }
        return;
    }

    if (dateXMs.length > 0 && numericX.length === 0) {
        const minSpanMs = minSpanDays * 24 * 60 * 60 * 1000;
        const minX = Math.min(...dateXMs);
        const maxX = Math.max(...dateXMs);
        const span = maxX - minX;
        if (span < minSpanMs) {
            const center = (minX + maxX) / 2;
            const forcedMin = center - minSpanMs / 2;
            const forcedMax = center + minSpanMs / 2;
            const tick0Date = new Date(forcedMin);
            tick0Date.setUTCHours(0, 0, 0, 0);
            figData.layout.xaxis.range = [new Date(forcedMin), new Date(forcedMax)];
            figData.layout.xaxis.autorange = false;
            figData.layout.xaxis.tickmode = 'linear';
            figData.layout.xaxis.dtick = minSpanMs;
            figData.layout.xaxis.tick0 = tick0Date;
        }
    }
}

const PHOTOMETRY_FETCH_TIMEOUT_MS = 120000;

function fetchJsonWithTimeout(url, timeoutMs = PHOTOMETRY_FETCH_TIMEOUT_MS, options = {}) {
    const controller = new AbortController();
    const timerId = setTimeout(() => controller.abort(), timeoutMs);

    return fetch(url, {
        ...options,
        signal: controller.signal
    })
        .then(async response => {
            if (!response.ok) {
                let body = null;
                try {
                    body = await response.json();
                } catch (_) {
                    body = null;
                }
                const err = new Error((body && body.error) ? body.error : `HTTP ${response.status}`);
                err.status = response.status;
                throw err;
            }
            return response.json();
        })
        .finally(() => clearTimeout(timerId));
}

// Photometry plot loading with improved loading states
function loadPhotometryPlot() {
    if (!cleanObjectName) return Promise.resolve();
    
    console.log('Loading photometry plot...');
    console.log('Clean object name:', cleanObjectName);
    
    const photometryContainer = document.querySelector('#photometryPlot');
    const loadingDiv = document.querySelector('#photometryLoading');
    
    // Show loading
    const isFetching = photometryContainer && photometryContainer.innerHTML.includes('Fetching latest');
    if (loadingDiv && !isFetching) loadingDiv.style.display = 'flex';
    if (photometryContainer && !isFetching) photometryContainer.innerHTML = '';
    
    const applyExtinction = document.getElementById('applyExtinction')?.checked ?? false;
    const applyKCorr = document.getElementById('applyKCorr')?.checked ?? false;

    // Load both plot and raw data
    return Promise.all([
        fetchJsonWithTimeout(`/api/object/${encodeURIComponent(cleanObjectName)}/photometry/plot?extinction=${applyExtinction}&k_corr=${applyKCorr}`),
        fetchJsonWithTimeout(`/api/object/${encodeURIComponent(cleanObjectName)}/photometry`)
    ]).then(([plotData, rawData]) => {
        console.log('Plot data:', plotData);
        console.log('Raw data:', rawData);
        
        // Hide loading
        if (loadingDiv) loadingDiv.style.display = 'none';
        
        // Store raw data for editing
        if (rawData.success) {
            photometryData = rawData.photometry || [];

            // Default peak MJD for KN model = brightest detection; init slider range
            const _validPts = photometryData.filter(p => p.magnitude != null && p.magnitude_error != null);
            if (_validPts.length) {
                const _mjds = _validPts.map(p => parseFloat(p.mjd)).filter(m => !isNaN(m));
                const _minMjd = Math.min(..._mjds);
                const _maxMjd = Math.max(..._mjds);
                const _brightest = _validPts.reduce((a, b) => parseFloat(a.magnitude) < parseFloat(b.magnitude) ? a : b);
                const _defMjd = parseFloat(_brightest.mjd);
                const _slider = document.getElementById('knPeakSlider');
                if (_slider) {
                    const _pad = Math.max((_maxMjd - _minMjd) * 0.3, 5);
                    _slider.min   = (_minMjd - _pad).toFixed(1);
                    _slider.max   = (_maxMjd + _pad).toFixed(1);
                    _slider.step  = '0.1';
                    _slider.value = _defMjd.toFixed(1);
                    const _lbl = document.getElementById('knMjdLabel');
                    if (_lbl) _lbl.textContent = _defMjd.toFixed(2);
                }
            }

            // Populate and render sub-plots (color index & Δ mag)
            _populateSubplotSelects(photometryData);
            renderColorIndexPlot();
            renderMagDeltaPlot();

            // Display Peak Abs Mag Extra info (MJD and filter)
            if (photometryData.length > 0) {
                const validPoints = photometryData.filter(p => p.magnitude != null && p.magnitude !== '' && p.magnitude_error > 0 && parseFloat(p.magnitude_error) <= 0.3 && !String(p.magnitude).includes('>'));
                if (validPoints.length > 0) {
                    const brightestPt = validPoints.reduce((min, p) => parseFloat(p.magnitude) < parseFloat(min.magnitude) ? p : min, validPoints[0]);
                    
                    // find the label using array mapping instead of :contains which is not valid in standard querySelector
                    const allLabels = Array.from(document.querySelectorAll('.detail-label'));
                    const peakLabel = allLabels.find(lbl => lbl.textContent.includes('Peak Abs Mag'));
                    
                    if (peakLabel) {
                        const peakValue = peakLabel.nextElementSibling;
                        if (peakValue && !peakValue.innerHTML.includes('at MJD')) {
                            // Only append if not already appended (could be from template but it's empty)
                            let currentVal = peakValue.innerText.trim().split(' ')[0];
                            if (currentVal !== '--' && currentVal !== '') {
                                peakValue.innerHTML = `${currentVal} <span style="font-size:0.9em; color:#aaa;">at MJD ${parseFloat(brightestPt.mjd).toFixed(2)} (${brightestPt.filter})</span>`;
                            }
                        }
                    }
                }
            }
            
            // Update Last Photometry Date in header
            if (Array.isArray(photometryData) && photometryData.length > 0) {
                // Find max MJD - ensure values are numbers
                const mjds = photometryData.map(p => parseFloat(p.mjd)).filter(m => !isNaN(m));
                
                if (mjds.length > 0) {
                    const maxMjd = Math.max(...mjds);
                    
                    // Convert MJD to Date string
                    // MJD 40587 is 1970-01-01
                    const unixTime = (maxMjd - 40587) * 86400 * 1000;
                    const date = new Date(unixTime);
                    
                    // Format as YYYY-MM-DD HH:MM:SS
                    const year = date.getUTCFullYear();
                    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
                    const day = String(date.getUTCDate()).padStart(2, '0');
                    const hours = String(date.getUTCHours()).padStart(2, '0');
                    const minutes = String(date.getUTCMinutes()).padStart(2, '0');
                    const seconds = String(date.getUTCSeconds()).padStart(2, '0');
                    
                    const dateStr = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
                    
                    const lastPhotSpan = document.getElementById('lastPhotometryDate');
                    if (lastPhotSpan) {
                        lastPhotSpan.textContent = `(Last photometry: ${dateStr})`;
                    }
                }
            }
        }
        
        // Display plot
        if (plotData.success) {
            if (photometryContainer) {
                if (plotData.plot_json) {
                    photometryContainer.innerHTML = '<div id="phot-plotly-div" style="width:100%; height:450px;"></div>';
                    try {
                        const figData = JSON.parse(plotData.plot_json);
                        // Override template to match page dark theme
                        if (figData.layout) {
                            figData.layout.paper_bgcolor = 'rgba(0,0,0,0)';
                            figData.layout.plot_bgcolor  = 'rgba(0,0,0,0)';
                            figData.layout.font = figData.layout.font || {};
                            figData.layout.font.color = '#ccc';
                            figData.layout.showlegend = false;
                            figData.layout.margin = Object.assign(figData.layout.margin || {}, { t: 45 });
                        }
                        enforceMinLcXAxisSpan(figData, 1);
                        Plotly.newPlot('phot-plotly-div', figData.data, figData.layout, {responsive: true});
                        _buildTelescopeToggles(figData.data);
                        _buildFilterLegend(figData.data);

                        // Store distance modulus & re-apply KN model if active
                        _knDistMod = typeof plotData.distance_modulus === 'number' ? plotData.distance_modulus : 0;
                        if (plotData.redshift) _objectRedshift = plotData.redshift;
                        const dmLabel = document.getElementById('knDistModLabel');
                        if (dmLabel) dmLabel.textContent = _knDistMod > 0 ? `μ = ${_knDistMod.toFixed(2)}` : '';
                        if (_knModelActive) _applyKnModelOverlay();

                        console.log('Photometry plot rendered successfully');
                        setTimeout(() => { matchStarMapHeight(); }, 200);
                    } catch (error) {
                        console.error('Error rendering photometry plot:', error);
                        photometryContainer.innerHTML = `
                            <div class="no-data">
                                <span class="no-data-icon">${ICONS.error}</span>
                                <span class="no-data-text">Error rendering plot</span>
                            </div>
                        `;
                    }
                } else {
                    // Check if it's currently fetching in background
                    const isFetching = photometryContainer.innerHTML.includes('Fetching latest');
                    if (!isFetching) {
                        photometryContainer.innerHTML = `
                            <div class="no-data">
                                <span class="no-data-icon">${ICONS.noData}</span>
                                <span class="no-data-text">${plotData.message || 'No photometry data available'}</span>
                            </div>
                        `;
                    }
                    setTimeout(() => { matchStarMapHeight(); }, 100);
                }
            }
        } else {
            console.error('Error loading photometry plot:', plotData.error);
            if (photometryContainer) {
                photometryContainer.innerHTML = `
                    <div class="no-data">
                        <span class="no-data-icon">${ICONS.error}</span>
                        <span class="no-data-text">Error loading photometry data</span>
                    </div>
                `;
                setTimeout(() => { matchStarMapHeight(); }, 100);
            }
        }
    }).catch(error => {
        console.error('Error loading photometry data:', error);
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (photometryContainer) {
            const timedOut = error && error.name === 'AbortError';
            photometryContainer.innerHTML = `
                <div class="no-data">
                    <span class="no-data-icon">${ICONS.error}</span>
                    <span class="no-data-text">${timedOut ? 'Photometry request timed out. Please try again.' : 'Error loading photometry data'}</span>
                </div>
            `;
            
            // Match star-map height even on catch error
            setTimeout(() => {
                matchStarMapHeight();
            }, 100);
        }
    });
}

// ── Kilonova Model Overlay ──────────────────────────────────────────────────

let _knModelActive    = false;
let _knModelData      = null;   // cached model JSON
let _knModelTraceCount = 0;     // number of KN traces added (2 per filter: fill + line)
let _knDistMod        = 0;      // distance modulus (set when plot loads)

/** KN model filter → hex color (use the same filter color map) */
const _KN_FILTER_COLORS = { g: '#00a86b', r: '#ff0000', i: '#8b0000' };

function toggleKnModel() {
    _knModelActive = !_knModelActive;
    const btn = document.getElementById('knModelBtn');
    const ctrl = document.getElementById('knModelControls');
    if (_knModelActive) {
        btn.style.background    = 'rgba(0,245,212,0.18)';
        btn.style.borderColor   = 'rgba(0,245,212,0.5)';
        btn.style.color         = '#00f5d4';
        if (ctrl) ctrl.style.display = 'flex';
        _applyKnModelOverlay();
    } else {
        btn.style.background  = '';
        btn.style.borderColor = '';
        btn.style.color       = '';
        if (ctrl) ctrl.style.display = 'none';
        _removeKnModelOverlay();
    }
}

function updateKnModelOverlay() {
    if (_knModelActive) _applyKnModelOverlay();
}

function onKnSliderInput(val) {
    const lbl = document.getElementById('knMjdLabel');
    if (lbl) lbl.textContent = parseFloat(val).toFixed(2);
    if (_knModelActive) _applyKnModelOverlay();
}

function _removeKnModelOverlay() {
    const plotDiv = document.getElementById('phot-plotly-div');
    if (!plotDiv || !plotDiv.data || _knModelTraceCount === 0) return;
    const total = plotDiv.data.length;
    const indices = Array.from({ length: _knModelTraceCount }, (_, i) => total - _knModelTraceCount + i);
    Plotly.deleteTraces('phot-plotly-div', indices);
    _knModelTraceCount = 0;
}

async function _applyKnModelOverlay() {
    const plotDiv = document.getElementById('phot-plotly-div');
    if (!plotDiv) return;

    const peakMjd = parseFloat(document.getElementById('knPeakSlider')?.value);
    if (isNaN(peakMjd)) return;

    // Fetch model data once
    if (!_knModelData) {
        try {
            const res = await fetch('/api/kn_model');
            const d = await res.json();
            if (!d.success) return;
            _knModelData = d.model;
        } catch (e) { console.error('KN model fetch error', e); return; }
    }

    // Remove any previously added KN traces
    _removeKnModelOverlay();

    const traces = [];
    const filterOrder = ['g', 'r', 'i'];

    filterOrder.forEach(f => {
        const fd = _knModelData[f];
        if (!fd) return;
        const color = _KN_FILTER_COLORS[f] || '#aaa';

        // Shift: apparent = absolute + distance_modulus; x = peakMjd + days
        const xs     = fd.time.map(t => peakMjd + t);
        const yMin   = fd.min.map(v => v + _knDistMod);
        const yMax   = fd.max.map(v => v + _knDistMod);
        const yMed   = fd.median.map(v => v + _knDistMod);

        // Fill band (min → max)
        const xFill  = [...xs, ...xs.slice().reverse()];
        const yFill  = [...yMin, ...yMax.slice().reverse()];
        traces.push({
            x: xFill, y: yFill,
            fill: 'toself',
            fillcolor: _hexToRgba(color, 0.15),
            line: { color: 'transparent', width: 0 },
            mode: 'lines',
            type: 'scatter',
            hoverinfo: 'skip',
            showlegend: false,
        });

        // Median line
        traces.push({
            x: xs, y: yMed,
            mode: 'lines',
            type: 'scatter',
            name: `KN ${f}`,
            line: { color: color, width: 1.5, dash: 'dot' },
            hovertemplate: `KN ${f}<br>MJD %{x:.2f}<br>%{y:.2f} mag<extra></extra>`,
            showlegend: true,
        });
    });

    if (!traces.length) return;
    _knModelTraceCount = traces.length;
    Plotly.addTraces('phot-plotly-div', traces);
}

function _hexToRgba(hex, alpha) {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

// ── Shared photometry visibility state ────────────────────────────────────
let _photTelActive   = null;  // Set<string> — active telescopes
let _photTraceActive = null;  // Set<string> — active trace names

// Parse telescope from trace name: "{filter} - {telescope}" or "{filter} - {telescope} - Limit"
function _telFromTraceName(name) {
    if (!name) return null;
    const base = name.endsWith(' - Limit') ? name.slice(0, -8).trimEnd() : name;
    const idx = base.lastIndexOf(' - ');
    return idx >= 0 ? base.slice(idx + 3) : null;
}

function _applyPhotVis() {
    const plotDiv = document.getElementById('phot-plotly-div');
    if (!plotDiv || !plotDiv.data) return;
    const visArr = plotDiv.data.map(tr => {
        if (tr.showlegend === false || !tr.name) return true;
        const tel = _telFromTraceName(tr.name);
        const telOk   = !_photTelActive   || !tel || _photTelActive.has(tel);
        const traceOk = !_photTraceActive || _photTraceActive.has(tr.name);
        return (telOk && traceOk) ? true : 'legendonly';
    });
    Plotly.restyle('phot-plotly-div', 'visible', visArr);

    // Sync filter-legend button visual state
    document.querySelectorAll('.phot-filter-btn').forEach(btn => {
        const name = btn.dataset.traceName;
        const tel = _telFromTraceName(name);
        const traceOn = !_photTraceActive || _photTraceActive.has(name);
        const telOn   = !_photTelActive   || !tel || _photTelActive.has(tel);
        btn.classList.toggle('active',  traceOn && telOn);
        btn.classList.toggle('tel-off', traceOn && !telOn);
    });
}

// Build telescope quick-toggle buttons above photometry plot
function _buildTelescopeToggles(traces) {
    const container = document.getElementById('telescopeToggles');
    if (!container) return;

    const telescopes = [];
    const seen = new Set();
    traces.forEach(t => {
        const tel = _telFromTraceName(t.name);
        if (tel && !seen.has(tel)) { seen.add(tel); telescopes.push(tel); }
    });

    _photTelActive = new Set(telescopes);

    if (telescopes.length <= 1) { container.style.display = 'none'; return; }

    container.innerHTML = '';
    container.style.display = 'flex';

    telescopes.forEach(tel => {
        const btn = document.createElement('button');
        btn.className = 'phot-tel-btn active';
        btn.textContent = tel;
        btn.dataset.telescope = tel;
        btn.addEventListener('click', function () {
            if (_photTelActive.has(tel)) { _photTelActive.delete(tel); btn.classList.remove('active'); }
            else                         { _photTelActive.add(tel);    btn.classList.add('active');    }
            _applyPhotVis();
        });
        container.appendChild(btn);
    });
}

// ── Photometry filter legend (below chart, replaces Plotly built-in legend) ──
function _buildFilterLegend(traces) {
    const container = document.getElementById('photLegend');
    if (!container) return;
    container.innerHTML = '';

    const entries = [];
    const seen = new Set();
    traces.forEach(t => {
        if (t.showlegend === false || !t.name) return;
        if (seen.has(t.name)) return;
        seen.add(t.name);
        const color = (t.marker && t.marker.color) ? t.marker.color : '#888';
        const tel   = _telFromTraceName(t.name) || '';
        const isUp  = t.name.endsWith(' - Limit');
        // filter label = part before the last " - telescope" segment
        const base  = isUp ? t.name.slice(0, -8).trimEnd() : t.name;
        const filterLabel = base.slice(0, base.lastIndexOf(' - ') >= 0 ? base.lastIndexOf(' - ') : base.length);
        entries.push({ name: t.name, color, isUp, tel, filterLabel });
    });

    _photTraceActive = new Set(entries.map(e => e.name));

    if (entries.length === 0) { container.style.display = 'none'; return; }

    // Sort: by telescope name, then detections before limits, then filter name
    entries.sort((a, b) => {
        if (a.tel !== b.tel) return a.tel.localeCompare(b.tel);
        if (a.isUp !== b.isUp) return a.isUp ? 1 : -1;
        return a.filterLabel.localeCompare(b.filterLabel);
    });

    // Group by telescope — build groups with a header label
    let currentTel = null;
    entries.forEach(({ name, color, isUp, tel, filterLabel }) => {
        // Telescope group header
        if (tel !== currentTel) {
            currentTel = tel;
            if (container.childElementCount > 0) {
                // thin divider between groups
                const sep = document.createElement('span');
                sep.className = 'phot-legend-sep';
                container.appendChild(sep);
            }
            const hdr = document.createElement('span');
            hdr.className = 'phot-legend-tel';
            hdr.textContent = tel || '—';
            container.appendChild(hdr);
        }

        const btn = document.createElement('button');
        btn.className = 'phot-filter-btn active';
        btn.dataset.traceName = name;
        btn.style.setProperty('--fc', color);

        const dot = document.createElement('span');
        dot.className = isUp ? 'phot-filter-up' : 'phot-filter-dot';

        const label = document.createElement('span');
        label.textContent = isUp ? filterLabel + ' - Limit' : filterLabel;

        btn.appendChild(dot);
        btn.appendChild(label);

        btn.addEventListener('click', function () {
            if (_photTraceActive.has(name)) _photTraceActive.delete(name);
            else                            _photTraceActive.add(name);
            _applyPhotVis();
        });

        container.appendChild(btn);
    });

    container.style.display = 'flex';
}

// ── Photometry Sub-plots: Color Index & Δ Magnitude ────────────────────────

const _COLOR_INDEX_PAIRS = [['g','r'],['B','V'],['g','i'],['r','i'],['r','z'],['g','z'],['u','g'],['u','r'],['c','o']];
const _MAG_DELTA_DEFAULT  = 'r';

/** Canonical filter → hex color (mirrors app/data/filter_colors.json) */
const _FILTER_COLORS = {
    uvw2:'#311432', uvm2:'#4b0082', uvw1:'#8a2be2',
    u:'#800080', U:'#800080',
    B:'#0000ff', b:'#0000ff',
    g:'#00a86b',
    V:'#9acd32', v:'#9acd32',
    c:'#00ffff', C:'#00ffff',
    w:'#eeb861', W:'#eeb861',
    o:'#ffa500',
    r:'#ff0000', R:'#ff0000',
    i:'#8b0000', I:'#8b0000',
    z:'#4a0000', Z:'#4a0000',
    y:'#cc6600', Y:'#cc6600',
    J:'#a0522d', H:'#8b4513', K:'#5c4033', Ks:'#5c4033', L:'#362511',
};
function _filterColor(f) { return _FILTER_COLORS[f] || '#888888'; }

function _subplotCommonLayout(yLabel) {
    return {
        margin: { t: 10, r: 12, b: 44, l: 52 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor:  'rgba(0,0,0,0)',
        font: { color: '#ccc', size: 10 },
        xaxis: {
            title: { text: 'MJD', font: { size: 10 } },
            showgrid: true, gridcolor: 'rgba(255,255,255,0.05)',
            zeroline: false, tickcolor: 'rgba(255,255,255,0.25)', tickfont: { size: 9 },
            tickformat: '.2f',
            exponentformat: 'none',
        },
        yaxis: {
            title: { text: yLabel, font: { size: 10 } },
            showgrid: true, gridcolor: 'rgba(255,255,255,0.05)',
            zeroline: false, tickcolor: 'rgba(255,255,255,0.25)', tickfont: { size: 9 },
        },
        showlegend: false,
        hovermode: 'closest',
    };
}

/** Populate filter <select> dropdowns from photometry data */
function _populateSubplotSelects(photData) {
    const selA = document.getElementById('colorFilterA');
    const selB = document.getElementById('colorFilterB');
    const selD = document.getElementById('magDeltaFilter');
    if (!selA || !selB || !selD) return;

    const seen = new Set();
    const filters = [];
    photData.forEach(p => {
        const f = p.filter;
        if (f && !seen.has(f) && p.magnitude != null && p.magnitude_error != null) {
            seen.add(f); filters.push(f);
        }
    });

    if (!filters.length) {
        const row = document.getElementById('photSubplotsRow');
        if (row) row.style.display = 'none';
        return;
    }

    const prevA = selA.value, prevB = selB.value, prevD = selD.value;
    [selA, selB, selD].forEach(s => { s.innerHTML = ''; });
    filters.forEach(f => {
        [selA, selB, selD].forEach(s => {
            const o = document.createElement('option');
            o.value = f; o.textContent = f;
            s.appendChild(o);
        });
    });

    // Smart default for color index
    let defA = filters[0], defB = filters.length > 1 ? filters[1] : filters[0];
    for (const [a, b] of _COLOR_INDEX_PAIRS) {
        if (filters.includes(a) && filters.includes(b)) { defA = a; defB = b; break; }
    }
    selA.value = (prevA && filters.includes(prevA)) ? prevA : defA;
    selB.value = (prevB && filters.includes(prevB) && prevB !== selA.value) ? prevB : defB;
    if (selB.value === selA.value) {
        const alt = filters.find(f => f !== selA.value);
        if (alt) selB.value = alt;
    }

    const defD = filters.includes(_MAG_DELTA_DEFAULT) ? _MAG_DELTA_DEFAULT : filters[0];
    selD.value = (prevD && filters.includes(prevD)) ? prevD : defD;

    const row = document.getElementById('photSubplotsRow');
    if (row) row.style.display = 'grid';
}

/** Color index subplot: filterA − filterB vs MJD */
function renderColorIndexPlot() {
    const selA = document.getElementById('colorFilterA');
    const selB = document.getElementById('colorFilterB');
    const plotDiv = document.getElementById('colorIndexPlot');
    if (!selA || !selB || !plotDiv || !photometryData) return;

    const fA = selA.value, fB = selB.value;
    const nodata = (msg) => {
        Plotly.react(plotDiv, [], Object.assign(_subplotCommonLayout(''), {
            annotations: [{ text: msg, showarrow: false, xref: 'paper', yref: 'paper',
                x: 0.5, y: 0.5, font: { color: 'rgba(255,255,255,0.35)', size: 11 } }]
        }), { responsive: true, displayModeBar: false });
    };

    if (!fA || !fB || fA === fB) { nodata('Select two different filters'); return; }

    const getValid = f => photometryData
        .filter(p => p.filter === f && p.magnitude != null && p.magnitude_error != null)
        .map(p => ({ mjd: parseFloat(p.mjd), mag: parseFloat(p.magnitude) }))
        .filter(p => !isNaN(p.mjd) && !isNaN(p.mag))
        .sort((a, b) => a.mjd - b.mjd);

    const ptsA = getValid(fA), ptsB = getValid(fB);
    if (!ptsA.length || !ptsB.length) { nodata(`No detections for ${fA} or ${fB}`); return; }

    const pairs = [];
    ptsA.forEach(pa => {
        let best = null, bestD = 0.5;
        ptsB.forEach(pb => { const d = Math.abs(pa.mjd - pb.mjd); if (d < bestD) { bestD = d; best = pb; } });
        if (best) pairs.push({ mjd: (pa.mjd + best.mjd) / 2, ci: pa.mag - best.mag });
    });

    if (!pairs.length) { nodata(`No contemporaneous ${fA}/${fB} obs (within 0.5 d)`); return; }

    const trace = {
        x: pairs.map(p => p.mjd),
        y: pairs.map(p => p.ci),
        mode: 'markers',
        type: 'scatter',
        marker: { size: 6, color: _filterColor(fA) },
        hovertemplate: `MJD %{x:.2f}<br>${fA}−${fB} = %{y:.3f} mag<extra></extra>`,
    };

    Plotly.react(plotDiv, [trace], _subplotCommonLayout(`${fA}−${fB} (mag)`), { responsive: true, displayModeBar: false });
}

/** Δ magnitude subplot: change between consecutive N-day bins (median per bin) */
function renderMagDeltaPlot() {
    const selFilter = document.getElementById('magDeltaFilter');
    const selBin    = document.getElementById('magDeltaBin');
    const plotDiv   = document.getElementById('magDeltaPlot');
    if (!selFilter || !plotDiv || !photometryData) return;

    const filter  = selFilter.value;
    const binDays = selBin ? parseFloat(selBin.value) || 1 : 1;
    const nodata  = (msg) => {
        Plotly.react(plotDiv, [], Object.assign(_subplotCommonLayout(''), {
            annotations: [{ text: msg, showarrow: false, xref: 'paper', yref: 'paper',
                x: 0.5, y: 0.5, font: { color: 'rgba(255,255,255,0.35)', size: 11 } }]
        }), { responsive: true, displayModeBar: false });
    };
    if (!filter) { nodata('No filter selected'); return; }

    const pts = photometryData
        .filter(p => p.filter === filter && p.magnitude != null && p.magnitude_error != null)
        .map(p => ({ mjd: parseFloat(p.mjd), mag: parseFloat(p.magnitude) }))
        .filter(p => !isNaN(p.mjd) && !isNaN(p.mag))
        .sort((a, b) => a.mjd - b.mjd);

    if (pts.length < 2) { nodata(`Need ≥ 2 ${filter}-band detections`); return; }

    // ── Bin by N-day windows ──────────────────────────────────────────────
    const origin = pts[0].mjd;
    const binMap = new Map(); // binIndex → [mag, ...]
    pts.forEach(p => {
        const idx = Math.floor((p.mjd - origin) / binDays);
        if (!binMap.has(idx)) binMap.set(idx, []);
        binMap.get(idx).push(p.mag);
    });

    // Convert map to sorted array of { binIdx, mjdCenter, median }
    const _median = arr => {
        const s = [...arr].sort((a, b) => a - b);
        const m = Math.floor(s.length / 2);
        return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    };

    const bins = [...binMap.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([idx, mags]) => ({
            mjdCenter: origin + idx * binDays + binDays / 2,
            median:    _median(mags),
            n:         mags.length,
        }));

    if (bins.length < 2) { nodata(`Need ≥ 2 bins of ${binDays} d with ${filter}-band data`); return; }

    // ── Compute delta between consecutive bins ────────────────────────────
    const deltas = bins.slice(1).map((b, i) => ({
        mjd:   b.mjdCenter,
        delta: b.median - bins[i].median,
        nCur:  b.n,
        nPrev: bins[i].n,
        dtBin: +(b.mjdCenter - bins[i].mjdCenter).toFixed(1),
    }));

    const filterHex = _filterColor(filter);
    const trace = {
        x: deltas.map(d => d.mjd),
        y: deltas.map(d => d.delta),
        mode: 'markers',
        type: 'scatter',
        marker: { size: 7, color: filterHex },
        customdata: deltas.map(d => [d.dtBin, d.nCur, d.nPrev]),
        hovertemplate:
            `MJD %{x:.2f}<br>Δ${filter} = %{y:+.3f} mag` +
            `<br>Δt = %{customdata[0]} d` +
            `<br>pts: prev=%{customdata[2]}, cur=%{customdata[1]}<extra></extra>`,
    };

    const xMin = deltas[0].mjd, xMax = deltas[deltas.length - 1].mjd;
    const zeroline = {
        x: [xMin, xMax], y: [0, 0],
        mode: 'lines', type: 'scatter',
        line: { color: 'rgba(255,255,255,0.18)', width: 1, dash: 'dot' },
        hoverinfo: 'skip', showlegend: false,
    };

    const layout = _subplotCommonLayout(`Δ ${filter} / ${binDays} d (mag)`);
    Plotly.react(plotDiv, [zeroline, trace], layout, { responsive: true, displayModeBar: false });
}

function togglePhotometryEditMode() {
    if (isEditingPhotometry) {
        exitPhotometryEditMode();
    } else {
        enterPhotometryEditMode();
    }
}

function enterPhotometryEditMode() {
    isEditingPhotometry = true;

    const editBtn = document.getElementById('photometryEditBtn');
    if (editBtn) {
        editBtn.innerHTML = 'Editing...';
        editBtn.title = 'Currently editing — click to close';
    }

    const modal = document.getElementById('editPhotometryModal');
    if (modal) modal.style.display = 'flex';

    photometryChanges = { toDelete: [], toAdd: [] };
    editSelectedIds = new Set();
    editTableFilter = { telescope: '', filter: '' };
    editTableSort = { col: 'mjd', dir: 'asc' };

    _buildEditFilterDropdowns();
    populatePhotometryTable();
}

function _buildEditFilterDropdowns() {
    const telescopes = [...new Set(photometryData.map(p => p.telescope || 'Unknown'))].sort();
    const filters = [...new Set(photometryData.map(p => p.filter || 'N/A'))].sort();

    const telSel = document.getElementById('editTelescopeFilter');
    const filtSel = document.getElementById('editFilterFilter');
    if (!telSel || !filtSel) return;

    telSel.innerHTML = '<option value="">All</option>' +
        telescopes.map(t => `<option value="${t}">${t}</option>`).join('');
    filtSel.innerHTML = '<option value="">All</option>' +
        filters.map(f => `<option value="${f}">${f}</option>`).join('');
}

function populatePhotometryTable() {
    const tableBody = document.getElementById('photometryTableBody');
    if (!tableBody) return;

    // Filter
    let rows = photometryData.map((point, index) => ({ point, index }));
    if (editTableFilter.telescope) {
        rows = rows.filter(r => (r.point.telescope || 'Unknown') === editTableFilter.telescope);
    }
    if (editTableFilter.filter) {
        rows = rows.filter(r => (r.point.filter || 'N/A') === editTableFilter.filter);
    }

    // Sort
    const col = editTableSort.col;
    const dir = editTableSort.dir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
        let va = a.point[col] ?? '';
        let vb = b.point[col] ?? '';
        if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
        return String(va).localeCompare(String(vb)) * dir;
    });

    // Update sort arrows
    ['mjd','magnitude','filter','telescope'].forEach(c => {
        const el = document.getElementById(`sortArrow-${c}`);
        if (!el) return;
        el.textContent = c === col ? (editTableSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    });

    tableBody.innerHTML = '';

    rows.forEach(({ point, index }) => {
        const row = document.createElement('tr');
        row.dataset.index = index;
        row.dataset.pointId = point.id;

        const isUpperLimit = point.magnitude_error === null ||
                             point.magnitude_error === undefined ||
                             Number.isNaN(point.magnitude_error) ||
                             (typeof point.magnitude_error === 'number' && !isFinite(point.magnitude_error));

        const isMarked = photometryChanges.toDelete.includes(point.id);
        const isSelected = editSelectedIds.has(point.id);

        if (isMarked) row.classList.add('marked-for-deletion');

        row.innerHTML = `
            <td style="padding:6px 10px;">
                <input type="checkbox" class="edit-row-cb" data-id="${point.id}" data-index="${index}"
                       ${isSelected ? 'checked' : ''}
                       onchange="toggleEditRowSelect(this)"
                       style="width:14px; height:14px; cursor:pointer;">
            </td>
            <td>${point.mjd}</td>
            <td>${isUpperLimit ? '>' : ''}${point.magnitude}</td>
            <td>${point.magnitude_error || 'N/A'}</td>
            <td>${point.filter || 'N/A'}</td>
            <td>${point.telescope || 'Unknown'}</td>
            <td>
                <button class="btn-small ${isMarked ? 'btn-secondary' : 'btn-danger'}"
                        onclick="markForDeletion(${index}, ${point.id})"
                        title="${isMarked ? 'Undo deletion' : 'Delete this point'}">
                    <span class="btn-icon">${isMarked ? ICONS.undo : ICONS.delete}</span>
                </button>
            </td>
        `;

        tableBody.appendChild(row);
    });

    _updateEditSelectionCount();
    _syncSelectAllCheckbox();
}

function applyEditTableFilter() {
    editTableFilter.telescope = document.getElementById('editTelescopeFilter')?.value || '';
    editTableFilter.filter = document.getElementById('editFilterFilter')?.value || '';
    editSelectedIds = new Set();
    populatePhotometryTable();
}

function setEditSort(col) {
    if (editTableSort.col === col) {
        editTableSort.dir = editTableSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
        editTableSort.col = col;
        editTableSort.dir = 'asc';
    }
    populatePhotometryTable();
}

function toggleEditRowSelect(cb) {
    const id = parseInt(cb.dataset.id);
    if (cb.checked) {
        editSelectedIds.add(id);
    } else {
        editSelectedIds.delete(id);
    }
    _updateEditSelectionCount();
    _syncSelectAllCheckbox();
}

function toggleEditSelectAll(cb) {
    const checkboxes = document.querySelectorAll('.edit-row-cb');
    checkboxes.forEach(c => {
        const id = parseInt(c.dataset.id);
        c.checked = cb.checked;
        if (cb.checked) {
            editSelectedIds.add(id);
        } else {
            editSelectedIds.delete(id);
        }
    });
    _updateEditSelectionCount();
}

function _updateEditSelectionCount() {
    const el = document.getElementById('editSelectionCount');
    if (!el) return;
    el.textContent = editSelectedIds.size > 0 ? `${editSelectedIds.size} selected` : '';
}

function _syncSelectAllCheckbox() {
    const cb = document.getElementById('editSelectAll');
    if (!cb) return;
    const all = document.querySelectorAll('.edit-row-cb');
    if (all.length === 0) { cb.checked = false; cb.indeterminate = false; return; }
    const checkedCount = [...all].filter(c => c.checked).length;
    cb.indeterminate = checkedCount > 0 && checkedCount < all.length;
    cb.checked = checkedCount === all.length;
}

function deleteSelectedPhotometry() {
    if (editSelectedIds.size === 0) {
        showNotification('No rows selected', 'info');
        return;
    }
    editSelectedIds.forEach(id => {
        if (!photometryChanges.toDelete.includes(id)) {
            photometryChanges.toDelete.push(id);
        }
    });
    editSelectedIds = new Set();
    populatePhotometryTable();
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
            btn.innerHTML = `<span class="btn-icon">${ICONS.delete}</span>`;
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
            btn.innerHTML = `<span class="btn-icon">${ICONS.undo}</span>`;
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
    
    const editBtn = document.getElementById('photometryEditBtn');
    if (editBtn) {
        editBtn.innerHTML = 'Edit';
        editBtn.title = 'Edit photometry data';
    }
    
    const modal = document.getElementById('editPhotometryModal');
    if (modal) modal.style.display = 'none';
}

async function addPhotometryPoint() {
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
    
    // Prepare data for API
    const newPoint = {
        mjd: mjd,
        magnitude: magnitude,
        magnitude_error: isUpperLimit ? null : magnitudeError,
        filter: filter,
        telescope: telescope
    };
    
    // Directly save to database via API
    try {
        const response = await fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/photometry`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(newPoint)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Photometry point added successfully', 'success');
            closeAddPhotometryModal();
            
            // Reload photometry data and re-populate edit table
            loadPhotometryPlot().then(() => {
                if (isEditingPhotometry) {
                    _buildEditFilterDropdowns();
                    populatePhotometryTable();
                }
            });
        } else {
            if (errorDiv && errorText) {
                errorText.innerHTML = result.error || 'Failed to add photometry point';
                errorDiv.style.display = 'flex';
            }
        }
    } catch (error) {
        console.error('Error adding photometry point:', error);
        if (errorDiv && errorText) {
            errorText.innerHTML = 'Network error: ' + error.message;
            errorDiv.style.display = 'flex';
        }
    }
}

function cancelPhotometryEdit() {
    if (photometryChanges.toDelete.length > 0 || photometryChanges.toAdd.length > 0) {
        if (!confirm('You have unsaved changes. Are you sure you want to cancel?')) {
            return;
        }
    }
    
    // Reset changes and reload data
    photometryChanges = { toDelete: [], toAdd: [] };
    editSelectedIds = new Set();
    loadPhotometryPlot(); // This will reload fresh data
    exitPhotometryEditMode();
}

async function savePhotometryChanges() {
    if (photometryChanges.toDelete.length === 0 && photometryChanges.toAdd.length === 0) {
        showNotification('No changes to save', 'info');
        return;
    }
    
    const saveBtn = document.getElementById('photometrySaveBtn');
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
        for (const newPoint of photometryChanges.toAdd) {
            try {
                const response = await fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/photometry`, {
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
function _specQueryParams() {
    const restFrame    = document.getElementById('specRestFrame')?.checked;
    const normalise    = document.getElementById('specNormalise')?.checked;
    const stackOffset  = document.getElementById('specStackOffset')?.checked;
    if (restFrame && (!objectData || objectData.redshift == null)) {
        // Only warn when there is actually spectrum data loaded
        const spectrumPlot = document.getElementById('spectrumPlot');
        const hasSpecData = !!(spectrumPlot && spectrumPlot.querySelector('.plotly-graph-div'));
        if (hasSpecData) {
            showNotification('This object has no redshift — please fill it in before using Rest Frame.', 'warning');
        }
        const cb = document.getElementById('specRestFrame');
        if (cb) cb.checked = false;
        return { rest_frame: false, normalise: normalise || false, stack: stackOffset || false };
    }
    return { rest_frame: restFrame || false, normalise: normalise || false, stack: stackOffset || false };
}

function onSpecToggle() {
    loadSpectrumPlot();
}

function inferSpectrumTelescopeFromFilename(fileName) {
    const stem = String(fileName || '').replace(/\.[^.]+$/, '');
    const firstToken = stem.split(/[^A-Za-z0-9]+/).find(Boolean) || '';
    const lettersOnly = firstToken.replace(/[^A-Za-z]/g, '');
    return /^[A-Za-z]{2,10}$/.test(lettersOnly) ? lettersOnly.toUpperCase() : '';
}

function inferSpectrumDateFromFilename(fileName) {
    const stem = String(fileName || '').replace(/\.[^.]+$/, '');
    const patterns = [
        /(?:^|\D)(20\d{2})(\d{2})(\d{2})(?:[T_\-]?\d{2}\d{2}\d{2})?(?:\D|$)/,
        /(?:^|\D)(20\d{2})[-_](\d{2})[-_](\d{2})(?:[T_\-]?\d{2}[-_]?\d{2}[-_]?\d{2})?(?:\D|$)/,
    ];
    for (const pattern of patterns) {
        const match = stem.match(pattern);
        if (!match) continue;
        const year = Number(match[1]);
        const month = Number(match[2]);
        const day = Number(match[3]);
        const dt = new Date(Date.UTC(year, month - 1, day));
        if (
            dt.getUTCFullYear() === year
            && dt.getUTCMonth() + 1 === month
            && dt.getUTCDate() === day
        ) {
            return `${match[1]}-${match[2]}-${match[3]}`;
        }
    }
    return '';
}

// ── Spectral Lines Overlay ────────────────────────────────────────────────────

// Built-in fallback line list (used until NIST cache is ready).
// Rest-frame air wavelengths (Å). `ion` carries the full transition for hover detail.
const _SPEC_LINES_BUILTIN = [
    // ── Hydrogen (Balmer + Paschen) ──
    { w: 6562.8, label: 'Hα',  ion: 'H I (Balmer α)',  group: 'H' },
    { w: 4861.3, label: 'Hβ',  ion: 'H I (Balmer β)',  group: 'H' },
    { w: 4340.5, label: 'Hγ',  ion: 'H I (Balmer γ)',  group: 'H' },
    { w: 4101.7, label: 'Hδ',  ion: 'H I (Balmer δ)',  group: 'H' },
    { w: 3970.1, label: 'Hε',  ion: 'H I (Balmer ε)',  group: 'H' },
    { w: 3889.1, label: 'Hζ',  ion: 'H I (Balmer ζ)',  group: 'H' },
    { w: 3835.4, label: 'Hη',  ion: 'H I (Balmer η)',  group: 'H' },
    { w: 9229.0, label: 'Pa9', ion: 'H I (Paschen 9)', group: 'H' },
    { w: 9545.9, label: 'Pa8', ion: 'H I (Paschen 8)', group: 'H' },
    // ── Helium ──
    { w: 3888.6, label: 'He I 3889', ion: 'He I',  group: 'He' },
    { w: 4026.2, label: 'He I 4026', ion: 'He I',  group: 'He' },
    { w: 4471.5, label: 'He I 4471', ion: 'He I',  group: 'He' },
    { w: 4921.9, label: 'He I 4922', ion: 'He I',  group: 'He' },
    { w: 5015.7, label: 'He I 5016', ion: 'He I',  group: 'He' },
    { w: 5875.6, label: 'He I 5876', ion: 'He I',  group: 'He' },
    { w: 6678.2, label: 'He I 6678', ion: 'He I',  group: 'He' },
    { w: 7065.2, label: 'He I 7065', ion: 'He I',  group: 'He' },
    { w: 7281.4, label: 'He I 7281', ion: 'He I',  group: 'He' },
    { w: 4685.7, label: 'He II 4686',ion: 'He II', group: 'He' },
    { w: 5411.5, label: 'He II 5412',ion: 'He II', group: 'He' },
    // ── Calcium ──
    { w: 3933.7, label: 'Ca II K',     ion: 'Ca II (H&K)',          group: 'Ca' },
    { w: 3968.5, label: 'Ca II H',     ion: 'Ca II (H&K)',          group: 'Ca' },
    { w: 4226.7, label: 'Ca I 4227',   ion: 'Ca I',                 group: 'Ca' },
    { w: 8498.0, label: 'Ca II 8498',  ion: 'Ca II (NIR triplet)',  group: 'Ca' },
    { w: 8542.1, label: 'Ca II 8542',  ion: 'Ca II (NIR triplet)',  group: 'Ca' },
    { w: 8662.1, label: 'Ca II 8662',  ion: 'Ca II (NIR triplet)',  group: 'Ca' },
    { w: 7291.5, label: '[Ca II] 7291',ion: '[Ca II] forbidden',    group: 'Ca' },
    { w: 7323.9, label: '[Ca II] 7324',ion: '[Ca II] forbidden',    group: 'Ca' },
    // ── Silicon ──
    { w: 4128.1, label: 'Si II 4128', ion: 'Si II', group: 'Si' },
    { w: 4130.9, label: 'Si II 4131', ion: 'Si II', group: 'Si' },
    { w: 5041.0, label: 'Si II 5041', ion: 'Si II', group: 'Si' },
    { w: 5055.9, label: 'Si II 5056', ion: 'Si II', group: 'Si' },
    { w: 5957.6, label: 'Si II 5958', ion: 'Si II', group: 'Si' },
    { w: 5978.9, label: 'Si II 5979', ion: 'Si II', group: 'Si' },
    { w: 6347.1, label: 'Si II 6347', ion: 'Si II', group: 'Si' },
    { w: 6371.4, label: 'Si II 6371', ion: 'Si II (λ6355 blend)', group: 'Si' },
    { w: 4552.6, label: 'Si III 4553',ion: 'Si III', group: 'Si' },
    // ── Oxygen ──
    { w: 7771.9, label: 'O I 7772',   ion: 'O I (triplet)',    group: 'O' },
    { w: 8446.4, label: 'O I 8446',   ion: 'O I',              group: 'O' },
    { w: 6300.3, label: '[O I] 6300', ion: '[O I] forbidden',  group: 'O' },
    { w: 6363.8, label: '[O I] 6364', ion: '[O I] forbidden',  group: 'O' },
    { w: 3727.4, label: '[O II] 3727',ion: '[O II] forbidden', group: 'O' },
    { w: 4363.2, label: '[O III] 4363',ion: '[O III] forbidden',group: 'O' },
    { w: 4958.9, label: '[O III] 4959',ion: '[O III] forbidden',group: 'O' },
    { w: 5006.8, label: '[O III] 5007',ion: '[O III] forbidden',group: 'O' },
    // ── Sodium ──
    { w: 5889.9, label: 'Na I D2', ion: 'Na I D',   group: 'Na' },
    { w: 5895.9, label: 'Na I D1', ion: 'Na I D',   group: 'Na' },
    { w: 8183.3, label: 'Na I 8183',ion: 'Na I',    group: 'Na' },
    { w: 8194.8, label: 'Na I 8195',ion: 'Na I',    group: 'Na' },
    // ── Iron ──
    { w: 4233.2, label: 'Fe II 4233', ion: 'Fe II', group: 'Fe' },
    { w: 4549.5, label: 'Fe II 4550', ion: 'Fe II', group: 'Fe' },
    { w: 4923.9, label: 'Fe II 4924', ion: 'Fe II (mult. 42)', group: 'Fe' },
    { w: 5018.4, label: 'Fe II 5018', ion: 'Fe II (mult. 42)', group: 'Fe' },
    { w: 5169.0, label: 'Fe II 5169', ion: 'Fe II (mult. 42)', group: 'Fe' },
    { w: 5276.0, label: 'Fe II 5276', ion: 'Fe II', group: 'Fe' },
    { w: 5316.6, label: 'Fe II 5317', ion: 'Fe II', group: 'Fe' },
    { w: 4658.1, label: '[Fe III] 4658', ion: '[Fe III] forbidden', group: 'Fe' },
    { w: 5270.4, label: '[Fe III] 5270', ion: '[Fe III] forbidden', group: 'Fe' },
    { w: 7155.2, label: '[Fe II] 7155',  ion: '[Fe II] forbidden',  group: 'Fe' },
    // ── Sulfur ──
    { w: 5454.0, label: 'S II 5454', ion: 'S II (W feature)', group: 'S' },
    { w: 5640.0, label: 'S II 5640', ion: 'S II (W feature)', group: 'S' },
    { w: 6716.4, label: '[S II] 6716',ion: '[S II] forbidden', group: 'S' },
    { w: 6730.8, label: '[S II] 6731',ion: '[S II] forbidden', group: 'S' },
    { w: 6312.1, label: '[S III] 6312',ion: '[S III] forbidden',group: 'S' },
    { w: 9068.6, label: '[S III] 9069',ion: '[S III] forbidden',group: 'S' },
    { w: 9530.6, label: '[S III] 9531',ion: '[S III] forbidden',group: 'S' },
    // ── Carbon ──
    { w: 4267.0, label: 'C II 4267', ion: 'C II',  group: 'C' },
    { w: 6578.1, label: 'C II 6578', ion: 'C II',  group: 'C' },
    { w: 7231.3, label: 'C II 7231', ion: 'C II',  group: 'C' },
    { w: 4647.4, label: 'C III 4647',ion: 'C III', group: 'C' },
    { w: 5695.9, label: 'C III 5696',ion: 'C III', group: 'C' },
    { w: 5801.3, label: 'C IV 5801', ion: 'C IV',  group: 'C' },
    { w: 5811.9, label: 'C IV 5812', ion: 'C IV',  group: 'C' },
    // ── Magnesium ──
    { w: 4571.1, label: 'Mg I] 4571', ion: 'Mg I] intercombination', group: 'Mg' },
    { w: 5167.3, label: 'Mg I b1',    ion: 'Mg I (b triplet)',       group: 'Mg' },
    { w: 5172.7, label: 'Mg I b2',    ion: 'Mg I (b triplet)',       group: 'Mg' },
    { w: 5183.6, label: 'Mg I b3',    ion: 'Mg I (b triplet)',       group: 'Mg' },
    { w: 4481.1, label: 'Mg II 4481', ion: 'Mg II',                  group: 'Mg' },
    // ── Nitrogen ──
    { w: 5754.6, label: '[N II] 5755',ion: '[N II] forbidden', group: 'N' },
    { w: 6548.0, label: '[N II] 6548',ion: '[N II] forbidden', group: 'N' },
    { w: 6583.5, label: '[N II] 6584',ion: '[N II] forbidden', group: 'N' },
    { w: 4640.6, label: 'N III 4641', ion: 'N III',            group: 'N' },
    // ── Titanium ──
    { w: 4395.0, label: 'Ti II 4395', ion: 'Ti II', group: 'Ti' },
    { w: 4501.3, label: 'Ti II 4501', ion: 'Ti II', group: 'Ti' },
    { w: 4805.1, label: 'Ti II 4805', ion: 'Ti II', group: 'Ti' },
    { w: 5188.7, label: 'Ti II 5189', ion: 'Ti II', group: 'Ti' },
    // ── Barium ──
    { w: 4554.0, label: 'Ba II 4554', ion: 'Ba II', group: 'Ba' },
    { w: 4934.1, label: 'Ba II 4934', ion: 'Ba II', group: 'Ba' },
    { w: 6141.7, label: 'Ba II 6142', ion: 'Ba II', group: 'Ba' },
    { w: 6496.9, label: 'Ba II 6497', ion: 'Ba II', group: 'Ba' },
];

// Telluric (atmospheric) absorption bands — observed frame, not redshifted with object
const _TELLURIC_BANDS = [
    { w0: 6860, w1: 6895, label: 'O₂ B' },
    { w0: 7160, w1: 7340, label: 'H₂O'  },
    { w0: 7580, w1: 7700, label: 'O₂ A' },
    { w0: 8100, w1: 8380, label: 'H₂O'  },
];

const _SPEC_LINE_COLORS = {
    H: '#4a9eff', He: '#ffd700', Ca: '#bf7fff', Si: '#ff9060',
    O: '#00e5ff', Na: '#adff2f', Fe: '#cd853f', S: '#7fff00',
    C: '#ff6347', Mg: '#40e0d0', N: '#ff5ec7', Ti: '#76d7c4',
    Ba: '#f5b700', Tel: '#b8a060',
};

// NIST-fetched lines (null = not yet loaded, use builtin fallback)
let _specLinesNist  = null;
function _activeSpecLines() { return _specLinesNist ?? _SPEC_LINES_BUILTIN; }

let _specActiveKeys = new Set(); // allowlist: labels of lines currently shown on plot
let _specTelActive  = false;     // whether telluric bands are shown
let _objectRedshift = null;        // filled when plot data loads
let _origMarginT    = null;        // saved before first line overlay
let _specLineRedshift = null;      // trial z for line overlay; null = use object z
let _specZUserSet     = false;     // true once the user edits the trial z field
let _specDataXRange   = [null, null]; // raw [min, max] Å from data at load time
let _specWaveMin      = null;      // current user x-axis min (display Å)
let _specWaveMax      = null;      // current user x-axis max (display Å)

// Object's canonical redshift (from DB / loaded data). Used for telluric placement
// and as the default for the trial-z control.
function _specObjRedshift() {
    let z = (objectData && objectData.redshift != null) ? parseFloat(objectData.redshift) : NaN;
    if (isNaN(z) && _objectRedshift != null) z = parseFloat(_objectRedshift);
    return isNaN(z) ? 0 : z;
}

// Redshift actually used to place atomic lines — trial value when set, else object z.
function _specLinesZ() {
    return _specLineRedshift != null ? _specLineRedshift : _specObjRedshift();
}

// Seed the trial-z input with the object redshift until the user overrides it.
function _initSpecRedshiftInput() {
    const inp = document.getElementById('specLineRedshift');
    if (!inp) return;
    if (!_specZUserSet) {
        const z = _specObjRedshift();
        inp.value = z ? z : '';
        inp.placeholder = z ? String(z) : '0.0';
    }
}

function onSpecRedshiftInput(val) {
    _specZUserSet = true;
    const z = parseFloat(val);
    _specLineRedshift = isNaN(z) ? null : z;
    _applySpecLines();
}

function resetSpecRedshift() {
    _specZUserSet = false;
    _specLineRedshift = null;
    _initSpecRedshiftInput();
    _applySpecLines();
}

function _applySpecXRange() {
    if (_specWaveMin == null || _specWaveMax == null) return;
    const plotDiv = document.querySelector('#spectrumPlot .js-plotly-plot');
    if (!plotDiv) return;
    try { Plotly.relayout(plotDiv, { 'xaxis.range': [_specWaveMin, _specWaveMax], 'xaxis.autorange': false }); } catch(e) {}
}

function _initSpecWaveRange() {
    const plotDiv = document.querySelector('#spectrumPlot .js-plotly-plot');
    if (!plotDiv?._fullLayout?.xaxis) return;
    const r = plotDiv._fullLayout.xaxis.range;
    if (!r || r.length < 2) return;
    const rawMin = parseFloat(r[0]);
    const rawMax = parseFloat(r[1]);
    if (isNaN(rawMin) || isNaN(rawMax)) return;
    _specDataXRange = [rawMin, rawMax];
    const dMin = Math.min(rawMin, 4000);
    const dMax = Math.max(rawMax, 7000);
    _specWaveMin = dMin;
    _specWaveMax = dMax;
    const inpMin = document.getElementById('specWaveMin');
    const inpMax = document.getElementById('specWaveMax');
    if (inpMin) inpMin.value = Math.round(dMin);
    if (inpMax) inpMax.value = Math.round(dMax);
    _applySpecXRange(); // apply once at load; does NOT reset zoom on line toggles
}

function onSpecWaveInput(which, val) {
    const v = parseFloat(val);
    if (which === 'min') _specWaveMin = isNaN(v) ? null : v;
    else                 _specWaveMax = isNaN(v) ? null : v;
    _applySpecXRange(); // explicit user change → apply zoom
    _applySpecLines();  // re-filter visible line labels
}

function resetSpecWaveRange() {
    if (_specDataXRange[0] == null) return;
    const [rawMin, rawMax] = _specDataXRange;
    const dMin = Math.min(rawMin, 4000);
    const dMax = Math.max(rawMax, 7000);
    _specWaveMin = dMin;
    _specWaveMax = dMax;
    const inpMin = document.getElementById('specWaveMin');
    const inpMax = document.getElementById('specWaveMax');
    if (inpMin) inpMin.value = Math.round(dMin);
    if (inpMax) inpMax.value = Math.round(dMax);
    _applySpecXRange(); // explicit reset → apply zoom
    _applySpecLines();  // re-filter visible line labels
}

async function _fetchNistSpecLines() {
    if (_specLinesNist !== null) return;   // already loaded
    try {
        const res  = await fetch('/api/spectral-lines');
        const data = await res.json();
        if (!data.success || !data.lines?.length) {
            _updateNistBadge('building');
            return;
        }
        _specLinesNist = data.lines;
        _updateNistBadge('nist');
        if (_specActiveKeys.size > 0 || _specTelActive) _applySpecLines();
    } catch (e) {
        _updateNistBadge('builtin');
    }
}

function _updateNistBadge(state) {
    const el = document.getElementById('specLineSourceBadge');
    if (!el) return;
    const cfg = {
        nist:     { text: 'NIST',     title: 'Spectral lines from NIST Atomic Spectra Database', cls: 'spec-source-nist'    },
        building: { text: 'Building…', title: 'NIST cache is being built — using built-in lines', cls: 'spec-source-building' },
        builtin:  { text: 'Built-in', title: 'Using built-in spectral line list',                 cls: 'spec-source-builtin'  },
    }[state] || { text: state, title: '', cls: '' };
    el.textContent = cfg.text;
    el.title       = cfg.title;
    el.className   = `spec-source-badge ${cfg.cls}`;
}

const _GROUP_ORDER = ['H','He','Ca','Si','O','Na','Fe','S','C','Mg','N','Ti','Ba'];

// Derive compact chip text: strip element name, keep ionization + identifier.
// "[O III] 5007" → "[OIII] 5007", "He II 4686" → "II 4686", "Hα" → "Hα"
function _chipText(l) {
    const s = l.label;
    const m1 = s.match(/^\[(\w+)\s+(\w+)\]\s*(.+)$/);
    if (m1) return `[${m1[1]}${m1[2]}] ${m1[3]}`.trim();
    const m2 = s.match(/^\w+\s+([IVX]+\]?\s+.+)$/);
    if (m2) return m2[1].replace(']', '').trim();
    return s;
}

function _buildSpecChipsUI() {
    const grid = document.getElementById('specChipsGrid');
    if (!grid) return;
    grid.innerHTML = '';

    _GROUP_ORDER.forEach(g => {
        const col = _SPEC_LINE_COLORS[g];
        const row = document.createElement('div');
        row.className = 'spec-chip-row';
        row.dataset.group = g;

        const lbl = document.createElement('button');
        lbl.className = 'spec-group-lbl';
        lbl.style.color = col;
        lbl.style.setProperty('--clr', col);
        lbl.textContent = g;
        lbl.title = 'Toggle all ' + g + ' lines';
        lbl.onclick = () => toggleSpecGroup(g);
        row.appendChild(lbl);

        _SPEC_LINES_BUILTIN.filter(l => l.group === g).forEach(l => {
            const btn = document.createElement('button');
            btn.className = 'spec-chip';
            btn.dataset.key = l.label;
            btn.style.setProperty('--clr', col);
            btn.textContent = _chipText(l);
            btn.title = `${l.label}\n${l.ion} — ${l.w.toFixed(1)} Å`;
            btn.onclick = () => toggleSpecChip(l.label);
            row.appendChild(btn);
        });

        grid.appendChild(row);
    });

    // Telluric row
    const telCol = _SPEC_LINE_COLORS['Tel'];
    const telRow = document.createElement('div');
    telRow.className = 'spec-chip-row';
    telRow.dataset.group = 'Tel';

    const telLbl = document.createElement('button');
    telLbl.className = 'spec-group-lbl';
    telLbl.style.color = telCol;
    telLbl.style.setProperty('--clr', telCol);
    telLbl.textContent = 'Tel';
    telLbl.title = 'Toggle telluric absorption bands';
    telLbl.onclick = () => toggleTelluric();
    telRow.appendChild(telLbl);

    _TELLURIC_BANDS.forEach(b => {
        const btn = document.createElement('button');
        btn.className = 'spec-chip tel-chip';
        btn.dataset.key = 'Tel_' + b.w0;
        btn.style.setProperty('--clr', telCol);
        btn.textContent = b.label;
        btn.title = `Telluric ${b.label}\n${b.w0}–${b.w1} Å (observed frame)`;
        btn.onclick = () => toggleTelluric();
        telRow.appendChild(btn);
    });

    grid.appendChild(telRow);
    _refreshChipStates();
}

function _refreshChipStates() {
    document.querySelectorAll('#specChipsGrid .spec-chip').forEach(btn => {
        const g = btn.closest('[data-group]')?.dataset.group;
        const active = g === 'Tel' ? _specTelActive : _specActiveKeys.has(btn.dataset.key);
        btn.classList.toggle('active', active);
    });
    document.querySelectorAll('#specChipsGrid .spec-group-lbl').forEach(lbl => {
        const g = lbl.closest('[data-group]')?.dataset.group;
        if (!g) return;
        let anyActive;
        if (g === 'Tel') {
            anyActive = _specTelActive;
        } else {
            anyActive = _SPEC_LINES_BUILTIN.filter(l => l.group === g).some(l => _specActiveKeys.has(l.label));
        }
        lbl.classList.toggle('any-active', anyActive);
    });
}

function toggleSpecGroup(g) {
    const lines = _SPEC_LINES_BUILTIN.filter(l => l.group === g);
    const allActive = lines.every(l => _specActiveKeys.has(l.label));
    lines.forEach(l => allActive ? _specActiveKeys.delete(l.label) : _specActiveKeys.add(l.label));
    _refreshChipStates();
    _applySpecLines();
}

function toggleSpecChip(label) {
    if (_specActiveKeys.has(label)) _specActiveKeys.delete(label);
    else _specActiveKeys.add(label);
    _refreshChipStates();
    _applySpecLines();
}

function toggleTelluric() {
    _specTelActive = !_specTelActive;
    _refreshChipStates();
    _applySpecLines();
}

function _applySpecLines() {
    const plotDiv = document.querySelector('#spectrumPlot .js-plotly-plot');
    if (!plotDiv) return;

    if (_specActiveKeys.size === 0 && !_specTelActive) {
        const restore = { shapes: [], annotations: [] };
        if (_origMarginT !== null) restore['margin.t'] = _origMarginT;
        try { Plotly.relayout(plotDiv, restore); } catch(e) {}
        return;
    }

    // Save the plot's original top margin before first overlay
    if (_origMarginT === null) {
        _origMarginT = plotDiv._fullLayout?.margin?.t ?? 20;
    }

    const restFrame = document.getElementById('specRestFrame')?.checked ?? true;
    const zObj   = _specObjRedshift();      // object frame (data de-redshift in rest mode)
    const zLines = _specLinesZ();           // trial value for atomic lines
    // In rest-frame mode the plot x-axis is already divided by (1+zObj); convert the
    // observed line position (rest_λ × (1+zLines)) into that frame.
    const denom  = restFrame ? (1 + zObj) : 1;

    const shapes = [], annotations = [];

    // Atomic spectral lines — only those explicitly selected (allowlist)
    _activeSpecLines()
        .filter(l => _specActiveKeys.has(l.label))
        .forEach(l => {
            const xPos = (l.w * (1 + zLines)) / denom;
            if (_specWaveMin != null && (xPos < _specWaveMin || xPos > _specWaveMax)) return;
            const col  = _SPEC_LINE_COLORS[l.group] || '#aaa';
            shapes.push({
                type: 'line', x0: xPos, x1: xPos, y0: 0, y1: 1, yref: 'paper',
                line: { color: col, width: 1, dash: 'dot' },
            });
            const detail = `<b>${l.label}</b><br>${l.ion || ''}<br>`
                         + `Rest λ: ${l.w.toFixed(1)} Å`
                         + (Math.abs(xPos - l.w) > 0.5 ? `<br>Plotted: ${xPos.toFixed(1)} Å (z=${zLines})` : '');
            annotations.push({
                x: xPos, y: 1.0, yref: 'paper',
                text: l.label,
                showarrow: false, textangle: -90,
                font: { size: 11, color: col },
                yanchor: 'bottom', xanchor: 'center',
                bgcolor: 'rgba(0,0,0,0)',
                hovertext: detail,
                captureevents: true,
                hoverlabel: { bgcolor: 'rgba(15,15,25,0.96)', bordercolor: col,
                              font: { size: 13, color: '#fff' } },
            });
        });

    // Telluric absorption bands — atmospheric, fixed in the observed frame.
    if (_specTelActive) {
        const col = _SPEC_LINE_COLORS['Tel'];
        _TELLURIC_BANDS.forEach(b => {
            const x0   = b.w0 / denom;
            const x1   = b.w1 / denom;
            if (_specWaveMin != null && (x1 < _specWaveMin || x0 > _specWaveMax)) return;
            const xMid = (x0 + x1) / 2;
            shapes.push({
                type: 'rect', x0, x1, y0: 0, y1: 1, yref: 'paper',
                fillcolor: 'rgba(184,160,96,0.10)',
                line: { color: 'rgba(184,160,96,0.35)', width: 1 },
            });
            annotations.push({
                x: xMid, y: 1.0, yref: 'paper',
                text: `⊕ ${b.label}`,
                showarrow: false, textangle: -90,
                font: { size: 11, color: col },
                yanchor: 'bottom', xanchor: 'center',
                bgcolor: 'rgba(0,0,0,0)',
                hovertext: `<b>Telluric ${b.label}</b><br>Atmospheric absorption<br>${b.w0}–${b.w1} Å (observed)`,
                captureevents: true,
                hoverlabel: { bgcolor: 'rgba(15,15,25,0.96)', bordercolor: col,
                              font: { size: 13, color: '#fff' } },
            });
        });
    }

    try {
        Plotly.relayout(plotDiv, {
            shapes,
            annotations,
            'margin.t': Math.max(_origMarginT, 70),
        });
    } catch(e) {}
}

function loadSpectrumPlot() {
    if (!cleanObjectName) return Promise.resolve();

    console.log('Loading spectrum plot...');
    
    const spectrumContainer = document.querySelector('#spectrumPlot');
    const loadingDiv = document.querySelector('#spectrumLoading');
    
    // Show loading
    _origMarginT = null;  // reset so the new plot's margin is re-sampled
    _specDataXRange = [null, null];
    _specWaveMin = null;
    _specWaveMax = null;
    if (loadingDiv) loadingDiv.style.display = 'flex';
    if (spectrumContainer) spectrumContainer.innerHTML = '';
    
    // Use generic API endpoint to support both TNS name and generic object name
    const { rest_frame, normalise, stack } = _specQueryParams();
    const params = new URLSearchParams();
    if (rest_frame) params.set('rest_frame', '1');
    if (normalise)  params.set('normalise', '1');
    if (stack)      params.set('stack', '1');
    const apiUrl = `/api/object/${encodeURIComponent(cleanObjectName)}/spectrum/plot${params.toString() ? '?' + params.toString() : ''}`;
    console.log('API URL:', apiUrl);
    
    return fetch(apiUrl)
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
                                // Seed trial-z field, then re-apply spectral lines if active
                                _initSpecRedshiftInput();
                                if (_specActiveKeys.size > 0 || _specTelActive) _applySpecLines();
                                // Seed wavelength range inputs from data extent
                                _initSpecWaveRange();
                                // Attempt to upgrade to NIST lines (no-op if already loaded)
                                _fetchNistSpecLines();
                            } catch (error) {
                                console.error('Error executing spectrum plot scripts:', error);
                                spectrumContainer.innerHTML = `
                                    <div class="no-data">
                                        <span class="no-data-icon">${ICONS.error}</span>
                                        <span class="no-data-text">Error rendering spectrum plot</span>
                                    </div>
                                `;
                            }
                        }, 100);
                        
                    } else {
                        spectrumContainer.innerHTML = `
                            <div class="no-data">
                                <span class="no-data-icon">${ICONS.noData}</span>
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
                            <span class="no-data-icon">${ICONS.error}</span>
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
                        <span class="no-data-icon">${ICONS.error}</span>
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

// ============================================================
// DOWNLOAD PHOTOMETRY
// ============================================================
function openDownloadModal() {
    if (!photometryData || photometryData.length === 0) {
        showNotification('No photometry data loaded yet.', 'warning');
        return;
    }

    const modal = document.getElementById('downloadPhotometryModal');
    if (!modal) return;

    // Unique telescopes & filters
    const telescopes = [...new Set(photometryData.map(p => p.telescope || 'Unknown').filter(Boolean))].sort();
    const filters    = [...new Set(photometryData.map(p => p.filter || '').filter(Boolean))].sort();
    const mjds       = photometryData.map(p => parseFloat(p.mjd)).filter(m => !isNaN(m));

    // Pre-fill MJD range
    const minEl = document.getElementById('dlMjdMin');
    const maxEl = document.getElementById('dlMjdMax');
    if (minEl) minEl.value = '';
    if (maxEl) maxEl.value = '';

    // Build telescope checkboxes
    const telList = document.getElementById('dlTelescopeList');
    if (telList) {
        telList.innerHTML = '';
        telescopes.forEach(t => {
            const lbl = document.createElement('label');
            lbl.style.cssText = 'display:flex; align-items:center; gap:5px; cursor:pointer; color:rgba(255,255,255,0.8); font-size:0.82rem; background:rgba(255,255,255,0.06); padding:3px 9px; border-radius:4px;';
            lbl.innerHTML = `<input type="checkbox" checked data-dl="telescope" value="${t}" style="width:13px; height:13px;"> ${t}`;
            telList.appendChild(lbl);
        });
    }

    // Build filter checkboxes
    const fltList = document.getElementById('dlFilterList');
    if (fltList) {
        fltList.innerHTML = '';
        filters.forEach(f => {
            const lbl = document.createElement('label');
            lbl.style.cssText = 'display:flex; align-items:center; gap:5px; cursor:pointer; color:rgba(255,255,255,0.8); font-size:0.82rem; background:rgba(255,255,255,0.06); padding:3px 9px; border-radius:4px;';
            lbl.innerHTML = `<input type="checkbox" checked data-dl="filter" value="${f}" style="width:13px; height:13px;"> ${f}`;
            fltList.appendChild(lbl);
        });
    }

    const countEl = document.getElementById('dlCount');
    if (countEl) countEl.textContent = `${photometryData.length} points total`;

    modal.style.display = 'flex';
}

function closeDownloadModal() {
    const modal = document.getElementById('downloadPhotometryModal');
    if (modal) modal.style.display = 'none';
}

function dlToggleAll(type, checked) {
    document.querySelectorAll(`[data-dl="${type}"]`).forEach(cb => { cb.checked = checked; });
}

function doDownloadPhotometry() {
    if (!cleanObjectName) return;

    const selTelescopes = [...document.querySelectorAll('[data-dl="telescope"]:checked')].map(cb => cb.value);
    const selFilters    = [...document.querySelectorAll('[data-dl="filter"]:checked')].map(cb => cb.value);
    const mjdMin        = document.getElementById('dlMjdMin')?.value || '';
    const mjdMax        = document.getElementById('dlMjdMax')?.value || '';
    const includeND     = document.getElementById('dlIncludeNondet')?.checked !== false;

    const params = new URLSearchParams();
    if (selTelescopes.length) params.set('telescopes', selTelescopes.join(','));
    if (selFilters.length)    params.set('filters', selFilters.join(','));
    if (mjdMin)               params.set('mjd_min', mjdMin);
    if (mjdMax)               params.set('mjd_max', mjdMax);
    if (!includeND)           params.set('include_nondet', 'false');

    const url = `/api/object/${cleanObjectName}/photometry/download?${params.toString()}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `${cleanObjectName}_phot.dat`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    closeDownloadModal();
}

async function downloadCurrentSpectrum() {
    if (!cleanObjectName) return;
    try {
        const response = await fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/spectroscopy`);
        const data = await response.json();
        const spectra = Array.isArray(data?.spectra) ? data.spectra : [];
        if (!data?.success || spectra.length === 0) {
            showNotification('No spectrum available for download.', 'warning');
            return;
        }

        const target = spectra[0];
        const spectrumId = target?.spectrum_id;
        if (!spectrumId) {
            showNotification('No spectrum available for download.', 'warning');
            return;
        }

        const selectedLabel = target?.spectrum_label || target?.telescope || target?.spectrum_id || 'spectrum';
        const a = document.createElement('a');
        a.href = `/api/spectrum/${encodeURIComponent(spectrumId)}/download`;
        a.download = `${cleanObjectName}_spec_${selectedLabel.replace(/[^\w\-]+/g, '_')}.dat`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    } catch (error) {
        console.error('Error preparing spectrum download:', error);
        showNotification('Failed to prepare spectrum download.', 'error');
    }
}

function uploadSpectrum() {
    const modal = document.getElementById('uploadSpectrumModal');
    if (modal) {
        modal.style.display = 'block';
        resetSpectrumUploadModal();
        setupSpectrumFileUpload();
    }
}

function closeSpectrumUploadModal() {
    const modal = document.getElementById('uploadSpectrumModal');
    if (modal) {
        modal.style.display = 'none';
        resetSpectrumUploadModal();
    }
}

function resetSpectrumUploadModal() {
    const elements = {
        spectrumFile: document.getElementById('spectrumFile'),
        selectedFile: document.getElementById('spectrumSelectedFile'),
        fileDropZone: document.getElementById('spectrumFileDropZone'),
        uploadPreview: document.getElementById('spectrumUploadPreview'),
        uploadError: document.getElementById('spectrumUploadError'),
        uploadBtn: document.getElementById('spectrumUploadBtn'),
        telescopeInput: document.getElementById('spectrumTelescope'),
        obsDateInput: document.getElementById('spectrumObsDate')
    };
    
    if (elements.spectrumFile) elements.spectrumFile.value = '';
    if (elements.selectedFile) elements.selectedFile.style.display = 'none';
    if (elements.fileDropZone) elements.fileDropZone.style.display = 'block';
    if (elements.uploadPreview) elements.uploadPreview.style.display = 'none';
    if (elements.uploadError) elements.uploadError.style.display = 'none';
    if (elements.uploadBtn) elements.uploadBtn.disabled = true;
    if (elements.telescopeInput) elements.telescopeInput.value = '';
    if (elements.obsDateInput) elements.obsDateInput.value = '';
    window.currentSpectrumData = [];
}

function setupSpectrumFileUpload() {
    const fileInput = document.getElementById('spectrumFile');
    const dropZone = document.getElementById('spectrumFileDropZone');
    
    if (!fileInput || !dropZone) {
        console.error('File input elements not found');
        return;
    }
    
    const newDropZone = dropZone.cloneNode(true);
    dropZone.parentNode.replaceChild(newDropZone, dropZone);
    const newFileInput = fileInput.cloneNode(true);
    fileInput.parentNode.replaceChild(newFileInput, fileInput);
    
    newDropZone.addEventListener('click', () => { newFileInput.click(); });
    newFileInput.addEventListener('change', handleSpectrumFileSelect);
    newDropZone.addEventListener('dragover', (e) => { e.preventDefault(); newDropZone.classList.add('dragover'); });
    newDropZone.addEventListener('dragleave', () => { newDropZone.classList.remove('dragover'); });
    newDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        newDropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            newFileInput.files = e.dataTransfer.files;
            handleSpectrumFileSelect();
        }
    });
}

function handleSpectrumFileSelect() {
    const fileInput = document.getElementById('spectrumFile');
    const file = fileInput.files[0];
    if (!file) return;
    
    const fileName = document.getElementById('spectrumFileName');
    const selectedFile = document.getElementById('spectrumSelectedFile');
    const dropZone = document.getElementById('spectrumFileDropZone');
    const telescopeInput = document.getElementById('spectrumTelescope');
    const obsDateInput = document.getElementById('spectrumObsDate');

    if (fileName) fileName.textContent = file.name;
    if (selectedFile) selectedFile.style.display = 'flex';
    if (dropZone) dropZone.style.display = 'none';
    if (telescopeInput && !telescopeInput.value.trim()) {
        const inferred = inferSpectrumTelescopeFromFilename(file.name);
        if (inferred) telescopeInput.value = inferred;
    }
    if (obsDateInput && !obsDateInput.value) {
        const inferredDate = inferSpectrumDateFromFilename(file.name);
        if (inferredDate) obsDateInput.value = inferredDate;
    }

    const reader = new FileReader();
    reader.onload = function(e) { validateSpectrumData(e.target.result); };
    reader.readAsText(file);
}

function removeSpectrumSelectedFile() {
    resetSpectrumUploadModal();
}

function validateSpectrumData(content) {
    const lines = content.split('\n');
    const validData = [];
    const errors = [];
    let lineNumber = 0;
    
    for (let line of lines) {
        lineNumber++;
        line = line.trim();
        
        if (!line || line.startsWith('#') || /^[a-zA-Z]/.test(line)) continue;
        
        const parts = line.split(/[\s,]+/);
        if (parts.length < 2) continue;
        
        const wavelength = parseFloat(parts[0]);
        const intensity = parseFloat(parts[1]);
        
        if (isNaN(wavelength) || isNaN(intensity)) {
            errors.push(`Line ${lineNumber}: Invalid number format`);
            continue;
        }
        
        validData.push({ wavelength, intensity });
    }
    
    window.currentSpectrumData = validData;
    showSpectrumPreview(validData, errors);
}

function showSpectrumPreview(data, errors) {
    const previewDiv = document.getElementById('spectrumUploadPreview');
    const errorDiv = document.getElementById('spectrumUploadError');
    const tableBody = document.getElementById('spectrumPreviewTableBody');
    const summary = document.getElementById('spectrumPreviewSummary');
    const uploadBtn = document.getElementById('spectrumUploadBtn');
    
    tableBody.innerHTML = '';
    
    if (errors.length > 0 && errorDiv) {
        errorDiv.style.display = 'flex';
        const errorText = document.getElementById('spectrumErrorText');
        if (errorText) errorText.innerHTML = errors.join('<br>');
    } else if (errorDiv) {
        errorDiv.style.display = 'none';
    }
    
    if (data.length === 0) {
        uploadBtn.disabled = true;
        return;
    }
    
    previewDiv.style.display = 'block';
    
    let displayData = data;
    if (data.length > 10) {
        displayData = [...data.slice(0, 5), { isEllipsis: true }, ...data.slice(-5)];
    }
    
    displayData.forEach(point => {
        const row = document.createElement('tr');
        if (point.isEllipsis) {
            row.innerHTML = `<td colspan="2" style="text-align: center;">... (${data.length - 10} more rows) ...</td>`;
        } else {
            row.innerHTML = `
                <td>${point.wavelength.toFixed(4)}</td>
                <td>${point.intensity.toExponential(4)}</td>
            `;
        }
        tableBody.appendChild(row);
    });
    
    if (summary) summary.innerHTML = `<strong>Total valid points:</strong> ${data.length}`;
    uploadBtn.disabled = false;
}

function submitSpectrumData() {
    if (!window.currentSpectrumData || window.currentSpectrumData.length === 0) return;
    
    const telescope = document.getElementById('spectrumTelescope').value || 'Unknown';
    const observationDate = (document.getElementById('spectrumObsDate')?.value || '').trim();
    const spectrumFile = document.getElementById('spectrumFile');
    const originalFilename = spectrumFile?.files?.[0]?.name || null;
    const uploadBtn = document.getElementById('spectrumUploadBtn');
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';
    
    const payload = {
        wavelength: window.currentSpectrumData.map(d => d.wavelength),
        intensity: window.currentSpectrumData.map(d => d.intensity),
        telescope: telescope,
        original_filename: originalFilename,
        observation_date: observationDate || null
    };
    
    const apiUrl = `/api/object/${encodeURIComponent(cleanObjectName)}/spectroscopy`;
    
    fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeSpectrumUploadModal();
            showNotification('Spectroscopy uploaded successfully!', 'success');
            loadSpectrumPlot();
        } else {
            throw new Error(data.error || 'Upload failed');
        }
    })
    .catch(error => {
        console.error('Error uploading spectrum:', error);
        showNotification('Failed to upload spectrum: ' + error.message, 'error');
    })
    .finally(() => {
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload Spectrum';
    });
}

function closeUploadModal() {
    const modal = document.getElementById('uploadPhotometryModal');
    if (modal) {
        modal.style.display = 'none';
        resetUploadModal();
    }
}

function resetUploadModal() {
    const ids = ['photometryFile', 'selectedFile', 'fileDropZone', 'uploadPreview',
                 'uploadError', 'uploadBtn', 'columnMappingSection', 'uploadProgressSection'];
    const el = {};
    ids.forEach(id => { el[id] = document.getElementById(id); });

    if (el.photometryFile) el.photometryFile.value = '';
    if (el.selectedFile) el.selectedFile.style.display = 'none';
    if (el.fileDropZone) el.fileDropZone.style.display = 'block';
    if (el.uploadPreview) el.uploadPreview.style.display = 'none';
    if (el.uploadError) el.uploadError.style.display = 'none';
    if (el.uploadBtn) { el.uploadBtn.disabled = true; el.uploadBtn.textContent = 'Upload Data'; }
    if (el.columnMappingSection) el.columnMappingSection.style.display = 'none';
    if (el.uploadProgressSection) el.uploadProgressSection.style.display = 'none';
    window.rawFileLines = null;
    window.rawFileHeaders = null;
    window.rawFileParseRow = null;
    window.parsedPhotometryData = [];
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

    const fileName = document.getElementById('fileName');
    const selectedFile = document.getElementById('selectedFile');
    const dropZone = document.getElementById('fileDropZone');
    if (fileName) fileName.textContent = file.name;
    if (selectedFile) selectedFile.style.display = 'flex';
    if (dropZone) dropZone.style.display = 'none';

    // Hide previous results
    const uploadPreview = document.getElementById('uploadPreview');
    const uploadError = document.getElementById('uploadError');
    const uploadBtn = document.getElementById('uploadBtn');
    if (uploadPreview) uploadPreview.style.display = 'none';
    if (uploadError) uploadError.style.display = 'none';
    if (uploadBtn) uploadBtn.disabled = true;

    const reader = new FileReader();
    reader.onload = function(e) { parsePhotometryFile(e.target.result); };
    reader.readAsText(file);
}

function parsePhotometryFile(content) {
    const allLines = content.split('\n');

    // Check for a '#'-prefixed header line appearing before any data
    // e.g. "# MJD magnitude error filter telescope"
    let commentHeaderParts = null;
    for (const line of allLines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (trimmed.startsWith('#')) {
            const body = trimmed.replace(/^#+\s*/, '').trim();
            if (!body) continue;
            const parts = body.includes(',')
                ? body.split(',').map(s => s.trim())
                : body.split(/\s+/);
            // Only treat as header if at least one token is non-numeric (a column name)
            if (parts.some(p => isNaN(parseFloat(p)))) {
                commentHeaderParts = parts.map(h => h.toLowerCase().trim());
            }
        } else {
            break; // first real data line — stop scanning for comment headers
        }
    }

    const dataLines = allLines.filter(l => l.trim() && !l.trim().startsWith('#'));

    if (dataLines.length === 0) {
        showUploadError('File is empty or contains only comments.');
        return;
    }

    const firstLine = dataLines[0].trim();
    const delimiter = firstLine.includes(',') ? ',' : null;
    const parseRow = delimiter
        ? (l) => l.split(',').map(s => s.trim())
        : (l) => l.trim().split(/\s+/);

    const firstParts = parseRow(firstLine);

    let headers, dataStartIdx, autoDetected;

    if (commentHeaderParts) {
        // Header came from a leading # comment line
        headers = commentHeaderParts;
        dataStartIdx = 0;
        autoDetected = true;
    } else {
        // Check if first data line itself is a text header row
        const firstLineHasText = firstParts.some(p => {
            const stripped = p.replace(/^>/, '').trim();
            return stripped !== '' && isNaN(parseFloat(stripped));
        });
        if (firstLineHasText) {
            headers = firstParts.map(h => h.toLowerCase().trim());
            dataStartIdx = 1;
            autoDetected = true;
        } else {
            // Headerless: assign positional labels, all lines are data
            headers = firstParts.map((_, i) => `col_${i + 1}`);
            dataStartIdx = 0;
            autoDetected = false;
        }
    }

    const sampleLines = dataLines.slice(dataStartIdx, dataStartIdx + 3);
    window.rawFileLines = dataLines.slice(dataStartIdx);
    window.rawFileHeaders = headers;
    window.rawFileParseRow = parseRow;

    const mapping = detectColumnMapping(headers);
    const allRequired = mapping.mjd >= 0 && mapping.mag >= 0 && mapping.filter >= 0;
    const mappingSection = document.getElementById('columnMappingSection');

    if (autoDetected && allRequired) {
        // Header found and all required columns identified → skip UI, go straight to preview
        if (mappingSection) mappingSection.style.display = 'none';
        parseWithMapping(window.rawFileLines, mapping, window.rawFileParseRow);
    } else {
        // Ambiguous or missing columns → show column mapping UI
        renderColumnMappingUI(headers, mapping, sampleLines, parseRow);
        if (mappingSection) mappingSection.style.display = 'block';
    }
}

function detectColumnMapping(headers) {
    const mapping = { mjd: -1, mag: -1, err: -1, filter: -1, telescope: -1 };
    headers.forEach((col, i) => {
        const c = col.toLowerCase().trim();
        if (mapping.mjd < 0 && (c === 'mjd' || c === 'jd'))
            mapping.mjd = i;
        if (mapping.filter < 0 && (c === 'filter' || c === 'band' || c === 'flt' || c === 'passband'))
            mapping.filter = i;
        if (mapping.mag < 0 && (c === 'mag' || c === 'magnitude'))
            mapping.mag = i;
        if (mapping.err < 0 && (c === 'err' || c === 'magerr' || c === 'mag_err' || c === 'error'
                || c === 'dmag' || c.endsWith('err') || c.endsWith('error') || c.endsWith('_err')))
            mapping.err = i;
        if (mapping.telescope < 0 && (c === 'telescope' || c === 'tel' || c === 'instrument' || c === 'observer'))
            mapping.telescope = i;
    });
    return mapping;
}

function renderColumnMappingUI(headers, mapping, sampleLines, parseRow) {
    const grid = document.getElementById('columnMappingGrid');
    if (!grid) return;

    // Show raw sample lines
    const sampleDisplay = document.getElementById('fileSampleDisplay');
    if (sampleDisplay && sampleLines && sampleLines.length > 0) {
        sampleDisplay.textContent = sampleLines.join('\n');
    }

    // Extract first-row sample values per column index
    const sampleValues = [];
    if (sampleLines && parseRow && sampleLines.length > 0) {
        parseRow(sampleLines[0]).forEach((v, i) => { sampleValues[i] = v; });
    }

    const fields = [
        { key: 'mjd',       label: 'MJD *',      required: true },
        { key: 'mag',       label: 'Magnitude *', required: true },
        { key: 'err',       label: 'Error',       required: false },
        { key: 'filter',    label: 'Filter *',    required: true },
        { key: 'telescope', label: 'Telescope',   required: false }
    ];

    grid.innerHTML = '';
    fields.forEach(field => {
        const wrapper = document.createElement('div');
        wrapper.className = 'col-map-item';

        const label = document.createElement('label');
        label.textContent = field.label;

        const select = document.createElement('select');
        select.id = `colMap_${field.key}`;

        if (!field.required) {
            const noneOpt = document.createElement('option');
            noneOpt.value = '-1';
            noneOpt.textContent = '— not used —';
            select.appendChild(noneOpt);
        }

        headers.forEach((h, i) => {
            const opt = document.createElement('option');
            opt.value = i;
            const sample = sampleValues[i] !== undefined ? ` (${sampleValues[i]})` : '';
            opt.textContent = `${h}${sample}`;
            select.appendChild(opt);
        });

        select.value = mapping[field.key] >= 0 ? mapping[field.key] : '-1';
        wrapper.appendChild(label);
        wrapper.appendChild(select);
        grid.appendChild(wrapper);
    });
}

function applyColumnMapping() {
    const keys = ['mjd', 'mag', 'err', 'filter', 'telescope'];
    const mapping = {};
    keys.forEach(k => {
        const sel = document.getElementById(`colMap_${k}`);
        mapping[k] = sel ? parseInt(sel.value, 10) : -1;
    });

    if (mapping.mjd < 0 || mapping.mag < 0 || mapping.filter < 0) {
        showUploadError('Please map the MJD, Magnitude, and Filter columns.');
        return;
    }

    const uploadError = document.getElementById('uploadError');
    if (uploadError) uploadError.style.display = 'none';

    parseWithMapping(window.rawFileLines, mapping, window.rawFileParseRow);
}

function parseWithMapping(lines, mapping, parseRow) {
    const validData = [];
    const errors = [];
    let lineNumber = 0;
    const errMapped = mapping.err >= 0;

    for (const raw of lines) {
        lineNumber++;
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;

        const parts = parseRow(line);

        const mjdStr    = (parts[mapping.mjd] || '').trim();
        const magStr    = (parts[mapping.mag] || '').trim();
        // errStr is null when error column not mapped (distinct from mapped-but-empty)
        const errStr    = errMapped ? (parts[mapping.err] || '').trim() : null;
        const filter    = (mapping.filter >= 0 ? (parts[mapping.filter] || '') : '').trim();
        const telescope = (mapping.telescope >= 0 ? (parts[mapping.telescope] || '') : 'Unknown').trim() || 'Unknown';

        const mjd = parseFloat(mjdStr);
        const dataPoint = { lineNumber, mjd, magnitude: null, magnitude_error: null, filter,
                            telescope, isUpperLimit: false, status: 'valid', statusText: 'Valid' };

        if (isNaN(mjd) || mjd < 20000 || mjd > 100000) {
            dataPoint.status = 'error';
            dataPoint.statusText = 'Invalid MJD';
            errors.push(`Line ${lineNumber}: Invalid MJD "${mjdStr}"`);
        }

        const errLower = errStr !== null ? errStr.toLowerCase() : null;
        // Upper limit when: '>' prefix on magnitude, OR error column mapped but value is nan/empty/none/-
        const isUL = magStr.startsWith('>')
            || (errLower !== null && (errLower === 'nan' || errLower === 'none'
                || errLower === 'null' || errLower === '' || errLower === '-'));

        if (isUL) {
            dataPoint.isUpperLimit = true;
            dataPoint.magnitude = parseFloat(magStr.replace(/^>/, ''));
            dataPoint.magnitude_error = null;
            if (dataPoint.status === 'valid') { dataPoint.status = 'warning'; dataPoint.statusText = 'Upper Limit'; }
        } else {
            dataPoint.magnitude = parseFloat(magStr);
            dataPoint.magnitude_error = errMapped ? parseFloat(errStr) : null;
            if (isNaN(dataPoint.magnitude)) {
                dataPoint.status = 'error';
                dataPoint.statusText = 'Invalid magnitude';
                errors.push(`Line ${lineNumber}: Invalid magnitude "${magStr}"`);
            }
            if (errMapped && (isNaN(dataPoint.magnitude_error) || dataPoint.magnitude_error < 0)) {
                dataPoint.isUpperLimit = true;
                dataPoint.magnitude_error = null;
                if (dataPoint.status === 'valid') { dataPoint.status = 'warning'; dataPoint.statusText = 'Upper Limit'; }
            }
        }

        if (!filter || filter.length > 10) {
            dataPoint.status = 'error';
            dataPoint.statusText = 'Invalid filter';
            errors.push(`Line ${lineNumber}: Invalid filter "${filter}"`);
        }

        validData.push(dataPoint);
    }

    window.parsedPhotometryData = validData;
    showPreview(validData, errors);
}

function showUploadError(msg) {
    const errorDiv = document.getElementById('uploadError');
    const errorText = document.getElementById('errorText');
    if (errorDiv) { errorDiv.style.display = 'flex'; }
    if (errorText) errorText.innerHTML = typeof msg === 'string' ? msg : msg.join('<br>');
}

function removeSelectedFile() {
    resetUploadModal();
}

// validatePhotometryData is replaced by parsePhotometryFile + parseWithMapping
function _validatePhotometryData_legacy(content) {
    const lines = content.split('\n');
    const validData = [];
    const errors = [];
    let lineNumber = 0;
    
    for (let line of lines) {
        lineNumber++;
        line = line.trim();
        
        if (!line || line.startsWith('#')) continue;
        const parts = line.split(/\s+/);
        if (parts.length < 4) {
            errors.push(`Line ${lineNumber}: Insufficient columns`);
            continue;
        }
        
        const mjd = parseFloat(parts[0]);
        const magStr = parts[1];
        const errStr = parts[2];
        const filter = parts[3];
        const telescope = parts[4] || 'Unknown';
        
        const dataPoint = { lineNumber, mjd, magnitude: null, magnitude_error: null, filter,
                            telescope, isUpperLimit: false, status: 'valid', statusText: 'Valid' };
        
        if (isNaN(mjd) || mjd < 50000 || mjd > 70000) {
            dataPoint.status = 'error'; dataPoint.statusText = 'Invalid MJD';
            errors.push(`Line ${lineNumber}: Invalid MJD value`);
        }
        
        const errLower = errStr.toLowerCase();
        const isNonDetection = errLower === 'nan' || errLower === 'none' || errLower === 'null' || errLower === '' || errLower === '-';
        
        if (magStr.startsWith('>') || isNonDetection) {
            dataPoint.isUpperLimit = true;
            dataPoint.magnitude = magStr.startsWith('>') ? parseFloat(magStr.substring(1)) : parseFloat(magStr);
            dataPoint.magnitude_error = null;
            if (dataPoint.status === 'valid') { dataPoint.status = 'warning'; dataPoint.statusText = 'Upper Limit'; }
        } else {
            dataPoint.magnitude = parseFloat(magStr);
            dataPoint.magnitude_error = parseFloat(errStr);
            
            if (isNaN(dataPoint.magnitude)) {
                dataPoint.status = 'error';
                dataPoint.statusText = 'Invalid magnitude';
                errors.push(`Line ${lineNumber}: Invalid magnitude value`);
            }
            
            if (isNaN(dataPoint.magnitude_error) || dataPoint.magnitude_error < 0) {
                // Treat as upper limit if error is invalid
                dataPoint.isUpperLimit = true;
                dataPoint.magnitude_error = null;
                if (dataPoint.status === 'valid') {
                    dataPoint.status = 'warning';
                    dataPoint.statusText = 'Upper Limit';
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

    if (!previewDiv || !tableBody || !uploadBtn) return;

    tableBody.innerHTML = '';

    if (errors.length > 0 && errorDiv) {
        errorDiv.style.display = 'flex';
        const errorText = document.getElementById('errorText');
        if (errorText) errorText.innerHTML = errors.slice(0, 10).join('<br>') + (errors.length > 10 ? `<br>...and ${errors.length - 10} more` : '');
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
    if (!cleanObjectName) { showNotification('Object name not found', 'error'); return; }

    const allData = window.parsedPhotometryData || [];
    const validRows = allData.filter(p => p.status !== 'error');
    if (validRows.length === 0) { showNotification('No valid rows to upload', 'error'); return; }

    const uploadBtn = document.getElementById('uploadBtn');
    const progressSection = document.getElementById('uploadProgressSection');
    const progressBar = document.getElementById('uploadProgressBar');
    const progressText = document.getElementById('uploadProgressText');

    if (uploadBtn) { uploadBtn.disabled = true; uploadBtn.textContent = 'Uploading...'; }
    if (progressSection) progressSection.style.display = 'block';
    if (progressBar) progressBar.style.width = '20%';
    if (progressText) progressText.textContent = `${validRows.length} points...`;

    const points = validRows.map(p => ({
        mjd: p.mjd,
        magnitude: p.magnitude,
        magnitude_error: p.isUpperLimit ? null : p.magnitude_error,
        filter: p.filter,
        telescope: p.telescope || 'Unknown'
    }));

    try {
        if (progressBar) progressBar.style.width = '60%';

        const response = await fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/photometry/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points })
        });

        if (progressBar) progressBar.style.width = '90%';
        const result = await response.json();

        if (result.success) {
            if (progressBar) progressBar.style.width = '100%';
            if (progressText) progressText.textContent = `${result.inserted} / ${result.total} inserted`;

            // Mark table rows as uploaded
            const tableBody = document.getElementById('previewTableBody');
            if (tableBody) {
                tableBody.querySelectorAll('tr').forEach(row => {
                    const statusCell = row.cells[5];
                    if (statusCell && !statusCell.classList.contains('status-error')) {
                        statusCell.className = 'status-valid';
                        statusCell.textContent = 'Uploaded';
                    }
                });
            }

            showNotification(`Uploaded ${result.inserted} photometry points`, 'success');
            setTimeout(() => { loadPhotometryPlot(); closeUploadModal(); }, 900);
        } else {
            throw new Error(result.error || 'Upload failed');
        }
    } catch (err) {
        showNotification('Upload failed: ' + err.message, 'error');
        if (uploadBtn) { uploadBtn.disabled = false; uploadBtn.textContent = 'Upload Data'; }
        if (progressSection) progressSection.style.display = 'none';
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
            <span style="font-size: 18px; display: flex; align-items: center;">${type === 'success' ? ICONS.success : type === 'error' ? ICONS.error : type === 'warning' ? ICONS.warning : ICONS.info}</span>
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
        
        const url = `/interactive_planner?${params.toString()}`;
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

    // Update mini panel count badge
    const badge = document.getElementById('commentsCount');
    if (badge) {
        badge.textContent = comments.length;
        badge.style.display = comments.length > 0 ? 'inline-flex' : 'none';
    }
}

function createCommentElement(comment) {
    const commentDiv = document.createElement('div');
    commentDiv.className = 'comment-item';
    commentDiv.dataset.commentId = comment.id;
    
    // Parse date - backend now returns ISO format string
    const createdAt = new Date(comment.created_at);
    
    // Format as UTC string: YYYY-MM-DD HH:MM:SS (UTC)
    const year = createdAt.getUTCFullYear();
    const month = String(createdAt.getUTCMonth() + 1).padStart(2, '0');
    const day = String(createdAt.getUTCDate()).padStart(2, '0');
    const hours = String(createdAt.getUTCHours()).padStart(2, '0');
    const minutes = String(createdAt.getUTCMinutes()).padStart(2, '0');
    const seconds = String(createdAt.getUTCSeconds()).padStart(2, '0');
    
    const utcTimeStr = `${year}-${month}-${day} ${hours}:${minutes}:${seconds} (UTC)`;
    
    // Check if current user is admin
    const isAdmin = document.querySelector('[data-admin="true"]') !== null;
    const userEmailEl = document.querySelector('[data-user-email]');
    const currentUserEmail = userEmailEl ? userEmailEl.getAttribute('data-user-email') : null;
    const canEdit = isAdmin || (currentUserEmail && comment.user_email === currentUserEmail);
    
    // Create avatar
    const avatarContent = comment.user_picture ? 
        `<img src="${comment.user_picture}" alt="${comment.user_name}" referrerpolicy="no-referrer" onerror='this.parentNode.classList.add("no-image"); this.outerHTML=\`${ICONS.user}\`;'>` :
        ICONS.user;
    
    commentDiv.innerHTML = `
        <div class="comment-avatar ${!comment.user_picture ? 'no-image' : ''}">
            ${avatarContent}
        </div>
        <div class="comment-content">
            <div class="comment-header">
                <span class="comment-author">${escapeHtml(comment.user_name)}</span>
                <span class="comment-time">${utcTimeStr}</span>
            </div>
            <div class="comment-text" id="comment-text-${comment.id}">${escapeHtml(comment.content).replace(/\\n/g, '<br>')}</div>
            <div class="comment-edit-box" id="comment-edit-box-${comment.id}" style="display:none; margin-top:8px;">
                <textarea id="comment-edit-textarea-${comment.id}" style="width:100%; background:rgba(0,0,0,0.3); color:#fff; border:1px solid rgba(255,255,255,0.2); border-radius:6px; padding:8px; resize:vertical; font-family:inherit;">${escapeHtml(comment.content)}</textarea>
                <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:4px;">
                    <button class="btn-modern" style="padding:2px 8px; font-size:0.8rem; border:none;" onclick="cancelEditComment(${comment.id})">Cancel</button>
                    <button class="btn-modern" style="padding:2px 8px; font-size:0.8rem; background:#00f5d4; color:#000; border:none;" onclick="saveEditComment(${comment.id})">Save</button>
                </div>
            </div>
        </div>
        ${canEdit ? `
        <div class="comment-actions">
            <button class="comment-action-btn" onclick="startEditComment(${comment.id})" title="Edit comment">
                ${ICONS.edit}
            </button>
            <button class="comment-delete-btn" onclick="deleteComment(${comment.id})" title="Delete comment">
                ${ICONS.delete}
            </button>
        </div>
        ` : (isAdmin ? `
        <div class="comment-actions">
            <button class="comment-delete-btn" onclick="deleteComment(${comment.id})" title="Delete comment">
                ${ICONS.delete}
            </button>
        </div>
        ` : '')}
    `;
    
    return commentDiv;
}

function startEditComment(commentId) {
    document.getElementById(`comment-text-${commentId}`).style.display = 'none';
    document.getElementById(`comment-edit-box-${commentId}`).style.display = 'block';
}

function cancelEditComment(commentId) {
    document.getElementById(`comment-text-${commentId}`).style.display = 'block';
    document.getElementById(`comment-edit-box-${commentId}`).style.display = 'none';
}

async function saveEditComment(commentId) {
    const textarea = document.getElementById(`comment-edit-textarea-${commentId}`);
    const newContent = textarea.value.trim();
    
    if (!newContent) {
        showNotification('Comment cannot be empty', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/comments/${commentId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content: newContent })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Comment updated successfully', 'success');
            loadComments();
        } else {
            showNotification(result.error || 'Failed to update comment', 'error');
        }
    } catch (error) {
        console.error('Error updating comment:', error);
        showNotification('Error updating comment', 'error');
    }
}

// ── Comments / DETECT modal open-close (DOM-move approach) ────────────────
function openCommentsModal(openForm) {
    const modal    = document.getElementById('commentsModal');
    const slot     = document.getElementById('commentsModalSlot');
    const container = document.getElementById('commentsContainer');
    if (modal && slot && container) {
        container.style.maxHeight = 'none';
        slot.appendChild(container);
        modal.style.display = 'flex';
    }
    if (openForm) setTimeout(showAddCommentForm, 50);
}
function closeCommentsModal() {
    const modal     = document.getElementById('commentsModal');
    const miniSlot  = document.getElementById('commentsMiniSlot');
    const container = document.getElementById('commentsContainer');
    cancelAddComment();
    if (miniSlot && container) {
        container.style.maxHeight = '110px';
        miniSlot.appendChild(container);
    }
    if (modal) modal.style.display = 'none';
}
function openDetectModal() {
    const modal    = document.getElementById('detectModal');
    const slot     = document.getElementById('detectModalSlot');
    const body     = document.getElementById('detectBody');
    if (modal && slot && body) {
        body.style.maxHeight = 'none';
        body.style.flex = '1';
        body.style.padding = '14px 20px';
        body.style.fontSize = '0.88rem';
        slot.appendChild(body);
        modal.style.display = 'flex';
    }
}
function closeDetectModal() {
    const modal    = document.getElementById('detectModal');
    const miniSlot = document.getElementById('detectMiniSlot');
    const body     = document.getElementById('detectBody');
    if (miniSlot && body) {
        body.style.maxHeight = '110px';
        body.style.flex = '';
        body.style.padding = '6px 2px';
        body.style.fontSize = '0.82rem';
        miniSlot.appendChild(body);
    }
    if (modal) modal.style.display = 'none';
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
            <div class="comments-error-icon">${ICONS.error}</div>
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
                    <h3>${ICONS.edit} Edit Object Data</h3>
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
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editRedshift">Redshift</label>
                                <input type="number" step="0.0001" id="editRedshift" placeholder="e.g., 0.0123">
                                <div class="form-help">Spectroscopic or photometric redshift</div>
                            </div>
                        </div>

                        <div class="form-row">
                            <div class="form-group">
                                <label for="editInternalNames">Internal Names</label>
                                <input type="text" id="editInternalNames" placeholder="e.g., EP260321a, AT2024abc">
                                <div class="form-help">Comma-separated alias names (e.g., EP source IDs)</div>
                            </div>
                        </div>

                        <div class="form-row">
                            <div class="form-group">
                                <label for="editTags">Tags</label>
                                <input type="text" id="editTags" placeholder="e.g., EP, peculiar, young">
                                <div class="form-help">Comma-separated custom labels. EP tag will be highlighted in blue.</div>
                            </div>
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
                        ${ICONS.save} Save Changes
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
        'editRedshift': objectData.redshift != null ? objectData.redshift : '',
        'editInternalNames': objectData.internal_names || '',
        'editTags': objectData.tags || ''
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
    
    const redshiftValue = document.getElementById('editRedshift').value;
    const internalNamesValue = document.getElementById('editInternalNames')?.value?.trim() ?? null;
    const tagsValue = document.getElementById('editTags')?.value?.trim() ?? null;

    const cleanData = {
        objid: objectData.objid || null,
        redshift: redshiftValue !== '' ? parseFloat(redshiftValue) : null,
        internal_names: internalNamesValue || null,
        tags: tagsValue || null
    };
    
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
            // Update in-memory objectData and DOM immediately
            if (cleanData.internal_names !== undefined) {
                objectData.internal_names = cleanData.internal_names;
                const el = document.getElementById('internalName');
                if (el) {
                    el.textContent = cleanData.internal_names
                        ? cleanData.internal_names.split(',').map(s => s.trim()).join(', ')
                        : 'N/A';
                }
            }
            if (cleanData.tags !== undefined) {
                objectData.tags = cleanData.tags;
                renderCustomTags(cleanData.tags);
            }
            showEditResult('success', 'Success!', data.message);
            showNotification('Object updated successfully! Page will refresh in 2 seconds...', 'success');
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
                        <span style="display: inline-block; margin-right: 10px;">${ICONS.success}</span> Object "${fullObjectName}" updated successfully!
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
        showNotification('Network error occurred while updating object', 'error');
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
        
        iconDiv.innerHTML = type === 'success' ? ICONS.success : ICONS.error;
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
    const confirmationMessage = `DELETE OBJECT CONFIRMATION\n\n` +
                               `You are about to permanently DELETE:\n` +
                               `Object: "${fullObjectName}"\n\n` +
                               `This action will permanently remove:\n` +
                               `• Object data from the database\n` +
                               `• All photometry data\n` +
                               `• All spectroscopy data\n` +
                               `• All comments and notes\n\n` +
                               `THIS CANNOT BE UNDONE!\n\n` +
                               `To confirm deletion, type "DELETE" exactly:`;
    
    const userInput = prompt(confirmationMessage);
    
    if (userInput !== 'DELETE') {
        if (userInput !== null) { // User didn't cancel
            showNotification('Deletion cancelled - must type "DELETE" exactly', 'warning');
        }
        return;
    }
    
    // Additional confirmation for critical action
    const finalConfirm = confirm(`FINAL CONFIRMATION\n\nAre you absolutely sure you want to delete "${fullObjectName}"?\n\nThis action CANNOT be undone!\n\nClick OK to proceed with deletion.`);
    
    if (!finalConfirm) {
        showNotification('Deletion cancelled by user', 'info');
        return;
    }
    
    // Show loading state
    showLoading(true);
    showNotification('Deleting object and all related data...', 'info');
    
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
            <span style="display: inline-block; margin-right: 10px;">${ICONS.delete}</span> Deleting object "${fullObjectName}"...
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
                    <span style="display: inline-block; margin-right: 10px;">${ICONS.success}</span> Object "${fullObjectName}" deleted successfully!
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
            showNotification(`Object "${fullObjectName}" deleted successfully! Redirecting to Marshal...`, 'success');
            
            // Redirect to marshal page after a short delay
            setTimeout(() => {
                window.location.href = '/marshal';
            }, 3000);
            
        } else {
            // Remove overlay and show error
            document.body.removeChild(overlay);
            showNotification(`Error deleting object: ${data.error}`, 'error');
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
        showNotification('Network error occurred while deleting object', 'error');
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

// Aladin Lite variables and functions
let aladinInstance = null;
// let currentSurvey = 'CDS/P/DESI-Legacy-Surveys/DR10/color';
// let currentSurvey = 'https://alasky.cds.unistra.fr/CDS/P/DSS2/color';
let currentSurvey = 'CDS/P/DSS2/color';
// let currentSurvey = 'https://alasky.cds.unistra.fr/DSS/DSS2Color';
let currentFOV = 60 / 3600;  // match DESI cutout: 600px × 0.1"/px = 60" = 0.0167°

// Initialize Aladin Lite
function initializeAladin() {
    if (!objectData || !objectData.ra || !objectData.declination) {
        console.warn('No coordinates available for Aladin');
        showAladinError('No coordinates available');
        return;
    }

    const ra = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);

    console.log(`Initializing Aladin with coordinates: RA=${ra}, Dec=${dec}`);

    try {
        // Show loading
        showAladinLoading(true);

        const aladinContainer = document.getElementById('aladin-lite-div');
        if (!aladinContainer) return;

        const targetName = getFullObjectName(objectData) || objectName;

        const html = `
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: transparent; }
        #aladin-lite { width: 100%; height: 100%; }
        /* Fix the input field wrapping visually inside iframe */
        .aladin-lite input { color: #000; background: #fff; border: 1px solid #ccc;  display: inline-block; width: auto; max-width: none; }
        .aladin-copyCoords { color: #fff; display: flex; align-items: center; white-space: nowrap; }
    </style>
    <script type="text/javascript" src="https://code.jquery.com/jquery-3.6.0.min.js"><\/script>
    <script type="text/javascript" src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js" crossorigin="anonymous"><\/script>
</head>
<body>
    <div id="aladin-lite"></div>
    <script>
        let aladinInstance;
        window.onload = function() {
            A.init.then(() => {
                aladinInstance = A.aladin('#aladin-lite', {
                    survey: '${currentSurvey}',
                    fov: ${currentFOV},
                    target: '${ra} ${dec}',
                    cooFrame: 'ICRS',
                    showReticle: true,
                    showZoomControl: false,
                    showFullscreenControl: true,
                    showLayersControl: false,
                    showGotoControl: false,
                    showShareControl: false,
                    showCatalog: false,
                    showFrame: false,
                    showCooGrid: false,
                    showProjectionControl: false,
                    showSimbadPointerControl: false,
                    showCooGridControl: false,
                    showSettings: false,
                    showLogo: true,
                    showContextMenu: false,
                    allowFullZoomout: true,
                    realFullscreen: true,
                    reticleColor: '#ff0000',
                    reticleSize: 20,
                    showStatusBar: false,
                });

                const cat = A.catalog({
                    name: 'Target',
                    color: '#ff0000',
                    sourceSize: 12,
                    shape: 'cross'
                });
                
                cat.addSources([A.source(${ra}, ${dec}, {name: '${targetName}'})]);
                aladinInstance.addCatalog(cat);

                // Notify parent that setup is done
                window.parent.postMessage({type: 'aladinReady'}, window.location.origin);
            });
        };

        let _nedCat = null, _nedSrcs = null;
        function _removeNEDCat() {
            if (!_nedCat || !aladinInstance) return;
            const view = aladinInstance.view;
            if (view) {
                ['allOverlayLayers', 'overlays', 'catalogs'].forEach(function(p) {
                    if (view[p]) { const i = view[p].indexOf(_nedCat); if (i !== -1) view[p].splice(i, 1); }
                });
                view.requestRedraw && view.requestRedraw();
            }
            _nedCat = null;
        }
        function _addNEDCat() {
            _removeNEDCat();
            _nedCat = A.catalog({ name: 'NED', color: '#f59e0b', sourceSize: 10, shape: 'circle' });
            _nedCat.addSources((_nedSrcs || []).map(function(s) {
                return A.source(s.ra, s.dec, {name: s.name, type: s.type || '', idx: s.idx});
            }));
            aladinInstance.addCatalog(_nedCat);
        }

        window.addEventListener('message', function(event) {
            if (!event.data) return;
            const d = event.data;
            if (d.type === 'changeSurvey' && aladinInstance) { aladinInstance.setImageSurvey(d.survey); }
            else if (d.type === 'addNEDCatalog') { _nedSrcs = d.sources; if (d.visible !== false) _addNEDCat(); }
            else if (d.type === 'toggleNEDCatalog') { if (d.visible) _addNEDCat(); else _removeNEDCat(); }
        });
    <\/script>
</body>
</html>`;

        const iframe = document.createElement('iframe');
        iframe.id = 'aladin-iframe';
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.allowFullscreen = true;
        iframe.srcdoc = html;

        aladinContainer.innerHTML = '';
        aladinContainer.appendChild(iframe);
        aladinContainer.style.display = 'block';

        showAladinLoading(false);
        console.log('Aladin inner iframe injected successfully');

    } catch (error) {
        console.error('Error initializing Aladin:', error);
        showAladinError('Failed to initialize star map');
    }
}

// Change survey
function changeSurvey() {
    const surveySelect = document.getElementById('surveySelect');
    if (!surveySelect) return;

    currentSurvey = surveySelect.value;
    console.log(`Changing survey to: ${currentSurvey}`);

    try {
        const iframe = document.getElementById('aladin-iframe');
        if (iframe && iframe.contentWindow) {
            iframe.contentWindow.postMessage({
                type: 'changeSurvey',
                survey: currentSurvey
            }, window.location.origin);
        } else if (aladinInstance) {
            // Fallback if iframe approach fails
            aladinInstance.setImageSurvey(currentSurvey);
        }
    } catch (error) {
        console.error('Error changing survey:', error);
        showNotification('Failed to change survey', 'error');
    }
}

// Refresh star map
function refreshStarMap() {
    console.log('Refreshing star map...');

    const aladinDiv = document.getElementById('aladin-lite-div');
    if (aladinDiv) {
        aladinDiv.innerHTML = '';
    }
    
    // Reinitialize
    setTimeout(() => {
        initializeAladin();
    }, 100);
}

// Show Aladin loading state
function showAladinLoading(show) {
    const loadingElement = document.getElementById('aladinLoading');
    const aladinDiv = document.getElementById('aladin-lite-div');
    
    if (loadingElement) {
        loadingElement.style.display = show ? 'flex' : 'none';
    }
    
    if (aladinDiv) {
        aladinDiv.style.display = show ? 'none' : 'block';
    }
}

// Show Aladin error
function showAladinError(message) {
    const loadingElement = document.getElementById('aladinLoading');
    const aladinDiv = document.getElementById('aladin-lite-div');
    
    if (loadingElement) {
        loadingElement.innerHTML = `
            <div class="error-icon">${ICONS.warning}</div>
            <span>${message}</span>
        `;
        loadingElement.style.display = 'flex';
    }
    
    if (aladinDiv) {
        aladinDiv.style.display = 'none';
    }
}

// Initialize Aladin when object data is loaded
function initializeAladinWhenReady() {
    if (objectData && objectData.ra && objectData.declination) {
        // Match star-map height with photometry card
        matchStarMapHeight();
        initializeAladin();
    }
}

// Match star-map height with photometry card
function matchStarMapHeight() {
    const photometryCard = document.querySelector('.detail-left .info-card:first-child');
    const starMapCard = document.getElementById('star-map');
    
    if (photometryCard && starMapCard) {
        // Wait for layout to be complete
        setTimeout(() => {
            const photometryHeight = photometryCard.offsetHeight;
            console.log(`Setting star-map height to match photometry: ${photometryHeight}px`);
            starMapCard.style.height = `${photometryHeight}px`;
            
            // Also adjust the aladin container
            const aladinContainer = starMapCard.querySelector('.aladin-container');
            if (aladinContainer) {
                const cardHeader = starMapCard.querySelector('.card-header');
                const aladinControls = starMapCard.querySelector('.aladin-controls');
                const headerHeight = cardHeader ? cardHeader.offsetHeight : 0;
                const controlsHeight = aladinControls ? aladinControls.offsetHeight : 0;
                const availableHeight = photometryHeight - headerHeight - controlsHeight - 20; // 20px for padding
                aladinContainer.style.height = `${Math.max(400, availableHeight)}px`;
            }
        }, 100);
    }
}

// Add window resize listener to maintain height matching
window.addEventListener('resize', debounce(() => {
    matchStarMapHeight();
}, 250));

// Debounce function to prevent excessive calls
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function fetchPhotometry(silent = false) {
    if (!objectName) {
        if (!silent) showNotification('Object name not available', 'error');
        return;
    }
    
    if (!silent && !confirm(`Fetch photometry for ${objectName} from TNS? This process may take a moment.`)) {
        return;
    }
    
    // Only show loading if it's a manual triggered click (not silent)
    if (!silent) {
        showLoading(true, 'Downloading data, please do not close...');
    }
    
    // If silently fetched, you might want to show a small subtle indicator somewhere
    if (silent) {
        console.log(`[Auto-Fetch] Fetching photometry for ${objectName} in background...`);
        const photometryContainer = document.querySelector('#photometryPlot');
        // Only show fetching message if currently showing "No data"
        if (photometryContainer && photometryContainer.innerHTML.includes('No photometry data available')) {
            photometryContainer.innerHTML = `
                <div class="no-data" style="color: #00f5d4;">
                    <div class="loading-spinner-small" style="margin-bottom: 8px;"></div>
                    <span class="no-data-text">Fetching latest photometry from TNS...</span>
                </div>
            `;
        }
    }
    
    fetchJsonWithTimeout(
        `/api/object/${encodeURIComponent(objectName)}/fetch_photometry`,
        PHOTOMETRY_FETCH_TIMEOUT_MS,
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        }
    )
    .then(data => {
        if (data.success) {
            if (!silent) {
                showNotification('Photometry fetch completed successfully', 'success');
                // Reload the page to show updated data
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                console.log(`[Auto-Fetch] Photometry background fetch successful. Refreshing plot silently.`);
                // If silent fetch worked, just refresh the plot data without reloading the whole page
                loadPhotometryPlot();
            }
        } else {
            if (!silent) {
                showNotification(`Error: ${data.error}`, 'error');
                showLoading(false);
            } else {
                console.warn(`[Auto-Fetch] Error from backend: ${data.error}`);
            }
        }
    })
    .catch(error => {
        console.error('Error fetching photometry:', error);
        const timedOut = error && error.name === 'AbortError';
        if (!silent) {
            showNotification(timedOut ? 'Photometry fetch timed out. Please try again.' : 'Failed to fetch photometry', 'error');
            showLoading(false);
        }
    });
}

// Permission Management Functions
function togglePermissionManager() {
    const manager = document.getElementById('permissionManager');
    if (manager.style.display === 'none') {
        manager.style.display = 'block';
        loadGroups();
        loadPermissions();
    } else {
        manager.style.display = 'none';
    }
}

function loadGroups() {
    const select = document.getElementById('groupSelect');
    select.innerHTML = '<option value="">Loading groups...</option>';
    
    fetch('/api/groups')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                select.innerHTML = '<option value="">Select Group...</option>';
                data.groups.forEach(group => {
                    const option = document.createElement('option');
                    option.value = group.name;
                    option.textContent = group.name;
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">Error loading groups</option>';
            }
        })
        .catch(error => {
            console.error('Error loading groups:', error);
            select.innerHTML = '<option value="">Error loading groups</option>';
        });
}

function loadPermissions() {
    const statusDiv = document.getElementById('permissionStatus');
    const listDiv = document.getElementById('currentPermissionsList');
    
    listDiv.innerHTML = 'Loading...';
    
    fetch(`/api/object/${encodeURIComponent(objectName)}/permissions`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (data.permissions.length === 0) {
                    listDiv.innerHTML = '<span style="color: #999; font-style: italic;">No specific permissions granted (Admin only)</span>';
                } else {
                    listDiv.innerHTML = '';
                    data.permissions.forEach(perm => {
                        const item = document.createElement('div');
                        item.style.marginBottom = '2px';
                        item.innerHTML = `• ${perm.group_name}`;
                        listDiv.appendChild(item);
                    });
                }
            } else {
                listDiv.innerHTML = 'Error loading permissions';
            }
        })
        .catch(error => {
            console.error('Error loading permissions:', error);
            listDiv.innerHTML = 'Error loading permissions';
        });
}

function grantPermission() {
    const select = document.getElementById('groupSelect');
    const groupName = select.value;
    const statusDiv = document.getElementById('permissionStatus');
    
    if (!groupName) {
        statusDiv.textContent = 'Please select a group first';
        statusDiv.style.color = '#dc3545';
        return;
    }
    
    statusDiv.textContent = 'Granting permission...';
    statusDiv.style.color = '#666';
    
    fetch(`/api/object/${encodeURIComponent(objectName)}/permissions`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ group_name: groupName })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            statusDiv.textContent = 'Permission granted successfully';
            statusDiv.style.color = '#28a745';
            loadPermissions();
        } else {
            statusDiv.textContent = `Error: ${data.error}`;
            statusDiv.style.color = '#dc3545';
        }
    })
    .catch(error => {
        console.error('Error granting permission:', error);
        statusDiv.textContent = 'Error granting permission';
        statusDiv.style.color = '#dc3545';
    });
}

function revokePermission() {
    const select = document.getElementById('groupSelect');
    const groupName = select.value;
    const statusDiv = document.getElementById('permissionStatus');
    
    if (!groupName) {
        statusDiv.textContent = 'Please select a group first';
        statusDiv.style.color = '#dc3545';
        return;
    }
    
    if (!confirm('Are you sure you want to revoke access for this group?')) {
        return;
    }
    
    statusDiv.textContent = 'Revoking permission...';
    statusDiv.style.color = '#666';
    
    fetch(`/api/object/${encodeURIComponent(objectName)}/permissions`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ group_name: groupName })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            statusDiv.textContent = 'Permission revoked successfully';
            statusDiv.style.color = '#28a745';
            loadPermissions();
        } else {
            statusDiv.textContent = `Error: ${data.error}`;
            statusDiv.style.color = '#dc3545';
        }
    })
    .catch(error => {
        console.error('Error revoking permission:', error);
        statusDiv.textContent = 'Error revoking permission';
        statusDiv.style.color = '#dc3545';
    });
}

/* Flag Management — disabled
function checkFlagStatus() {
    if (!cleanObjectName) return;
    if (!cleanObjectName && objectName) {
        cleanObjectName = extractYearAndLetters(objectName);
    } 
    if (!cleanObjectName) return;
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/flag_status`)
        .then(response => response.json())
        .then(data => {
            const btn = document.getElementById('flagBtn');
            if (btn && data.is_flagged) {
                btn.classList.add('active');
                btn.innerHTML = `${ICONS.flag} Remove Flag`;
                btn.title = "Remove flag from this object";
            } else if (btn) {
                btn.classList.remove('active');
                btn.innerHTML = `${ICONS.flag} Flag`;
                btn.title = "Flag this object as important";
            }
        })
        .catch(err => console.error('Error checking flag status:', err));
}
*/

// Pin Management
function checkPinStatus() {
    if (!cleanObjectName) return;
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/pin_status`)
        .then(r => r.json())
        .then(data => _applyPinUI(data.is_pinned))
        .catch(err => console.error('Error checking pin status:', err));
}

function _applyPinUI(isPinned) {
    const btn = document.getElementById('pinBtn');
    if (!btn) return;
    if (isPinned) {
        btn.style.color = '#a78bfa';
        btn.querySelector('svg').setAttribute('fill', '#a78bfa');
        btn.title = 'Unpin this object';
    } else {
        btn.style.color = '#a78bfa';
        btn.querySelector('svg').setAttribute('fill', 'none');
        btn.title = 'Pin this object';
    }
}

function togglePin() {
    if (!cleanObjectName) return;
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/toggle_pin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _applyPinUI(data.is_pinned);
            showNotification(data.is_pinned ? 'Object pinned' : 'Object unpinned', 'success');
        } else {
            showNotification(data.error || 'Failed to toggle pin', 'error');
        }
    })
    .catch(err => {
        console.error('Error toggling pin:', err);
        showNotification('Error toggling pin', 'error');
    });
}

/* toggleFlag — disabled
function toggleFlag() {
    if (!cleanObjectName) {
        if (objectName) cleanObjectName = extractYearAndLetters(objectName);
        else return;
    }
    const btn = document.getElementById('flagBtn');
    if (!btn) return;
    const isCurrentlyFlagged = btn.classList.contains('active');
    const newState = !isCurrentlyFlagged;
    if (newState) {
        btn.classList.add('active');
        btn.innerHTML = `${ICONS.flag} Remove Flag`;
        btn.title = "Remove flag from this object";
    } else {
        btn.classList.remove('active');
        btn.innerHTML = `${ICONS.flag} Flag`;
        btn.title = "Flag this object as important";
    }
    fetch(`/api/object/${encodeURIComponent(cleanObjectName)}/toggle_flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flag: newState })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            showNotification('Failed to toggle flag', 'error');
            if (isCurrentlyFlagged) {
                btn.classList.add('active'); btn.innerHTML = `${ICONS.flag} Remove Flag`;
            } else {
                btn.classList.remove('active'); btn.innerHTML = `${ICONS.flag} Flag`;
            }
        } else {
            showNotification(newState ? 'Object flagged' : 'Flag removed', 'success');
        }
    })
    .catch(err => {
        console.error('Error toggling flag:', err);
        showNotification('Error toggling flag', 'error');
        if (isCurrentlyFlagged) {
            btn.classList.add('active'); btn.innerHTML = `${ICONS.flag} Remove Flag`;
        } else {
            btn.classList.remove('active'); btn.innerHTML = `${ICONS.flag} Flag`;
        }
    });
}
*/

// ==========================================
// ==========================================
// Data Source Permissions (admin)
// ==========================================

let _permCurrentTab = 'phot';
let _permData = { phot: {}, spec: {} };
let _permSources = { phot: [], spec: [] };
let _permAllGroups = [];
let _permDefaults = {};

// ── Auto-save state ──────────────────────
let _permDirty   = false;
let _permSaveTimer = null;
const _PERM_AUTOSAVE_DELAY = 1500; // ms

function _permMarkDirty() {
    _permDirty = true;
    _permSetStatus('unsaved');
    clearTimeout(_permSaveTimer);
    _permSaveTimer = setTimeout(() => savePermissions(true), _PERM_AUTOSAVE_DELAY);
}

function _permSetStatus(state) {
    const el = document.getElementById('permSaveStatus');
    if (!el) return;
    el.className = 'perm-save-status perm-save-' + state;
    el.textContent = state === 'unsaved' ? '● Unsaved changes'
                   : state === 'saving'  ? '↻ Saving…'
                   : state === 'saved'   ? '✓ Saved'
                   : state === 'error'   ? '✕ Save failed'
                   : '';
    if (state === 'saved') setTimeout(() => { if (el.classList.contains('perm-save-saved')) { el.className = 'perm-save-status perm-save-idle'; el.textContent = ''; } }, 2500);
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.perm-panel')) {
        loadPermissionsPanel();
    }
});

async function loadPermissionsPanel() {
    try {
        const [srcRes, permRes, grpRes] = await Promise.all([
            fetch(`/api/object/${cleanObjectName}/sources`),
            fetch(`/api/object/${cleanObjectName}/source-permissions`),
            fetch('/api/groups')
        ]);
        const srcData = await srcRes.json();
        const permDataResp = await permRes.json();
        const grpData = await grpRes.json();

        _permSources.phot = srcData.phot_sources || [];
        _permSources.spec = srcData.spec_sources || [];
        _permAllGroups = (grpData.groups || []).map(g => typeof g === 'object' ? (g.name || g.id) : g);

        _permData = { phot: {}, spec: {} };
        // Build defaults map
        _permDefaults = {};
        for (const d of (permDataResp.defaults || [])) {
            _permDefaults[d.source] = d;
        }
        // Per-object overrides (highest priority)
        for (const p of (permDataResp.permissions || [])) {
            _permData[p.data_type][p.source_name] = {
                allowed_groups: p.allowed_groups,
                is_public: !!p.is_public
            };
        }
        // Pre-populate from defaults for sources not yet overridden,
        // so renderPermTable shows correct state on first load.
        for (const type of ['phot', 'spec']) {
            for (const src of _permSources[type]) {
                if (_permData[type][src]) continue; // already has per-object override
                const d = _permDefaults[src];
                if (d) {
                    const isPublic = d.permission === 'public';
                    // 'groups' permission: allowed_groups is already a list of group names
                    const ag = (d.permission === 'groups') ? (d.allowed_groups || []) : null;
                    _permData[type][src] = { allowed_groups: ag, is_public: isPublic };
                } else {
                    const isTNS = src.toUpperCase().includes('TNS');
                    _permData[type][src] = { allowed_groups: null, is_public: isTNS };
                }
            }
        }
        renderPermTable();
    } catch(e) {
        console.error('Error loading permissions:', e);
        const c = document.getElementById('permTableContainer');
        if (c) c.innerHTML = '<div class="perm-empty">Error loading sources.</div>';
    }
}

function switchPermTab(tab) {
    _permCurrentTab = tab;
    document.getElementById('permTabPhot').classList.toggle('active', tab === 'phot');
    document.getElementById('permTabSpec').classList.toggle('active', tab === 'spec');
    renderPermTable();
}

const _PERM_OPTS = [
    { val: 'public',  label: 'Public',  icon: '🌐', cls: 'perm-pill-public'  },
    { val: 'all',     label: 'Members', icon: '🔓', cls: 'perm-pill-all'     },
    { val: 'groups',  label: 'Groups',  icon: '👥', cls: 'perm-pill-groups'  },
    { val: 'blocked', label: 'Blocked', icon: '🚫', cls: 'perm-pill-blocked' },
];

function _permGetVis(perm, isTNS) {
    if (isTNS || perm.is_public) return 'public';
    if (perm.allowed_groups === null) return 'all';
    if (Array.isArray(perm.allowed_groups) && perm.allowed_groups.length === 0) return 'blocked';
    return 'groups';
}

function _permChipsHtml(type, src, groups) {
    return (groups || []).map(g =>
        `<span class="perm-chip">${escapeHtml(g)}<span class="perm-chip-remove" onclick="removePermGroup('${type}','${escapeHtml(src)}','${escapeHtml(g)}')">&times;</span></span>`
    ).join('');
}

function _permGroupSelectHtml(type, src) {
    return `<select class="perm-add-group-select" onchange="addPermGroup('${type}','${escapeHtml(src)}',this)">
        <option value="">+ group</option>
        ${_permAllGroups.map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join('')}
    </select>`;
}

function renderPermTable() {
    const container = document.getElementById('permTableContainer');
    if (!container) return;
    const sources = _permSources[_permCurrentTab];

    if (!sources || sources.length === 0) {
        container.innerHTML = '<div class="perm-empty">No data sources found. Upload data first, then click "Refresh Sources".</div>';
        return;
    }

    const cards = sources.map(src => {
        const isTNS = src.toUpperCase().includes('TNS');
        const perm = _permData[_permCurrentTab][src] || { allowed_groups: null, is_public: isTNS };
        const vis = _permGetVis(perm, isTNS);

        if (isTNS) {
            return `<div class="perm-card perm-card-locked">
                <div class="perm-card-check-wrap"><input type="checkbox" class="perm-row-check" disabled></div>
                <div class="perm-card-source"><span class="perm-source-name">${escapeHtml(src)}</span></div>
                <div class="perm-card-pills">
                    <span class="perm-locked-label">🌐 Always public (TNS)</span>
                </div>
            </div>`;
        }

        const pills = _PERM_OPTS.map(o =>
            `<button class="perm-pill ${o.cls}${vis === o.val ? ' active' : ''}"
                onclick="onPermVisChange('${_permCurrentTab}','${escapeHtml(src)}','${o.val}')"
                title="${o.val === 'public' ? 'Visible to everyone including non-logged visitors' :
                         o.val === 'all'    ? 'Visible to all logged-in members' :
                         o.val === 'groups' ? 'Restricted to selected groups only' :
                                             'Hidden from everyone except admins'}"
            >${o.icon} ${o.label}</button>`
        ).join('');

        const groupsDisplay = vis === 'groups' ? 'flex' : 'none';
        return `<div class="perm-card" data-src="${escapeHtml(src)}" data-type="${_permCurrentTab}">
            <div class="perm-card-check-wrap">
                <input type="checkbox" class="perm-row-check" onchange="_permRowCheckChanged()">
            </div>
            <div class="perm-card-source">
                <span class="perm-source-name">${escapeHtml(src)}</span>
            </div>
            <div class="perm-card-pills">
                <div class="perm-pill-group">${pills}</div>
            </div>
            <div class="perm-card-groups" id="perm-groups-${_permCurrentTab}-${escapeHtml(src)}" style="display:${groupsDisplay}">
                <div class="perm-chips-row" id="perm-chips-${_permCurrentTab}-${escapeHtml(src)}">${_permChipsHtml(_permCurrentTab, src, perm.allowed_groups)}</div>
                ${_permGroupSelectHtml(_permCurrentTab, src)}
            </div>
        </div>`;
    }).join('');

    container.innerHTML = `
        <div class="perm-toolbar" id="permToolbar">
            <div class="perm-toolbar-idle" id="permToolbarIdle">
                <label class="perm-select-all-label">
                    <input type="checkbox" id="permSelectAll" onchange="_permSelectAll(this.checked)">
                    <span class="perm-select-all-text">Select all</span>
                </label>
                <span class="perm-toolbar-hint">Check sources to batch-edit</span>
            </div>
            <div class="perm-toolbar-active" id="permToolbarActive" style="display:none;">
                <label class="perm-select-all-label perm-select-all-inline">
                    <input type="checkbox" id="permSelectAllActive" onchange="_permSelectAll(this.checked)">
                    <span class="perm-batch-count-badge" id="permBatchCount">0</span>
                    <span class="perm-batch-count-label">selected</span>
                </label>
                <span class="perm-batch-divider"></span>
                <span class="perm-batch-apply-label">Apply:</span>
                ${_PERM_OPTS.map(o =>
                    `<button class="perm-batch-btn perm-pill ${o.cls}" onclick="batchApplyPerm('${o.val}')" title="${
                        o.val==='public'?'Set selected to Public':o.val==='all'?'Set selected to Members only':o.val==='groups'?'Set selected to Groups only':'Block selected'
                    }">${o.icon} ${o.label}</button>`
                ).join('')}
                <button class="perm-batch-clear-btn" onclick="_permSelectAll(false)" title="Clear selection">✕</button>
            </div>
        </div>
        <div class="perm-card-list">${cards}</div>`;
}

function onPermVisChange(type, source, value) {
    if (!_permData[type][source]) _permData[type][source] = { allowed_groups: null, is_public: false };
    if (value === 'public') {
        _permData[type][source].is_public = true;
        _permData[type][source].allowed_groups = null;
    } else if (value === 'all') {
        _permData[type][source].is_public = false;
        _permData[type][source].allowed_groups = null;
    } else if (value === 'blocked') {
        _permData[type][source].is_public = false;
        _permData[type][source].allowed_groups = [];
    } else { // groups
        _permData[type][source].is_public = false;
        if (!Array.isArray(_permData[type][source].allowed_groups) || _permData[type][source].allowed_groups === null) {
            _permData[type][source].allowed_groups = [];
        }
    }
    // Update pill active states
    const card = document.querySelector(`.perm-card[data-src="${CSS.escape(source)}"][data-type="${type}"]`);
    if (card) {
        card.querySelectorAll('.perm-pill').forEach((btn, i) => {
            btn.classList.toggle('active', _PERM_OPTS[i].val === value);
        });
    }
    const cell = document.getElementById(`perm-groups-${type}-${source}`);
    if (cell) cell.style.display = value === 'groups' ? 'flex' : 'none';
    _permMarkDirty();
}

function _permRowCheckChanged() {
    const checked = document.querySelectorAll('.perm-row-check:checked').length;
    const total   = document.querySelectorAll('.perm-row-check:not(:disabled)').length;
    const cnt     = document.getElementById('permBatchCount');
    const idle    = document.getElementById('permToolbarIdle');
    const active  = document.getElementById('permToolbarActive');
    const saAll   = document.getElementById('permSelectAll');
    const saAllA  = document.getElementById('permSelectAllActive');
    if (cnt) cnt.textContent = checked;
    const isActive = checked > 0;
    if (idle)   idle.style.display   = isActive ? 'none' : 'flex';
    if (active) active.style.display = isActive ? 'flex' : 'none';
    [saAll, saAllA].forEach(cb => {
        if (!cb) return;
        cb.checked       = checked === total && total > 0;
        cb.indeterminate = checked > 0 && checked < total;
    });
}

function _permSelectAll(checked) {
    document.querySelectorAll('.perm-row-check:not(:disabled)').forEach(cb => cb.checked = checked);
    _permRowCheckChanged();
}

function batchApplyPerm(value) {
    document.querySelectorAll('.perm-card[data-src]').forEach(card => {
        const cb = card.querySelector('.perm-row-check');
        if (!cb || !cb.checked) return;
        onPermVisChange(card.dataset.type, card.dataset.src, value);
    });
    _permSelectAll(false);
}

function addPermGroup(type, source, select) {
    const grp = select.value;
    if (!grp) return;
    select.value = '';
    if (!_permData[type][source]) _permData[type][source] = { allowed_groups: [], is_public: false };
    const groups = _permData[type][source].allowed_groups || [];
    if (!groups.includes(grp)) {
        groups.push(grp);
        _permData[type][source].allowed_groups = groups;
        const chips = document.getElementById(`perm-chips-${type}-${source}`);
        if (chips) chips.innerHTML = _permChipsHtml(type, source, groups);
        _permMarkDirty();
    }
}

function removePermGroup(type, source, grp) {
    if (!_permData[type]?.[source]?.allowed_groups) return;
    _permData[type][source].allowed_groups = _permData[type][source].allowed_groups.filter(g => g !== grp);
    const chips = document.getElementById(`perm-chips-${type}-${source}`);
    if (chips) chips.innerHTML = _permChipsHtml(type, source, _permData[type][source].allowed_groups);
    _permMarkDirty();
}

async function savePermissions(isAuto = false) {
    clearTimeout(_permSaveTimer);
    _permSetStatus('saving');
    const batch = [];
    for (const type of ['phot', 'spec']) {
        for (const [source, perm] of Object.entries(_permData[type])) {
            batch.push({ data_type: type, source_name: source,
                allowed_groups: perm.allowed_groups, is_public: perm.is_public });
        }
    }
    try {
        const res = await fetch(`/api/object/${cleanObjectName}/source-permissions/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ permissions: batch })
        });
        const data = await res.json();
        if (data.success) {
            _permDirty = false;
            _permSetStatus('saved');
            if (!isAuto) showNotification('Permissions saved', 'success');
        } else {
            _permSetStatus('error');
            showNotification(data.error || 'Error saving', 'error');
        }
    } catch(e) {
        _permSetStatus('error');
        showNotification('Failed to save permissions', 'error');
    }
}

async function refreshPermSources() {
    const c = document.getElementById('permTableContainer');
    if (c) c.innerHTML = '<div class="perm-loading">Refreshing\u2026</div>';
    await loadPermissionsPanel();
    showNotification('Sources refreshed', 'success');
}

// ============================================================
// NED Overlay & Explorer
// ============================================================
let nedData = null;
let _nedHoverListener = null;
let _nedRadiusArcsec = 30;

function _getNEDRadiusArcsec() {
    const input = document.getElementById('nedRadiusInput');
    const raw = input ? Number(input.value) : _nedRadiusArcsec;
    const r = Number.isFinite(raw) ? Math.max(1, Math.min(600, Math.round(raw))) : 30;
    if (input) input.value = String(r);
    _nedRadiusArcsec = r;
    return r;
}

let _nedTimedOut   = false;
let _nedRetryTimer  = null;
let _nedFromCache   = false;
let _nedSearchedAt  = null;
let _nedCurrentHostName = '';

async function fetchNEDData(radiusArcsec = _nedRadiusArcsec, force = false) {
    if (!objectData || !objectData.ra || !objectData.declination) return null;
    _nedTimedOut = false;
    _nedFromCache = false;
    _nedSearchedAt = null;
    _nedCurrentHostName = '';
    const ra  = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);
    const name = encodeURIComponent(objectName || '');
    const forceParam = force ? '1' : '0';
    try {
        const resp = await fetch(
            `/api/ned/cone?ra=${ra}&dec=${dec}&radius_arcsec=${radiusArcsec}` +
            `&object_name=${name}&force=${forceParam}`
        );
        if (!resp.ok) {
            if (resp.status === 502) {
                let body = {};
                try { body = await resp.json(); } catch (_) {}
                const msg = (body.error || '').toLowerCase();
                if (msg.includes('timeout') || msg.includes('timed out')) { _nedTimedOut = true; }
            }
            throw new Error(`proxy ${resp.status}`);
        }
        const json = await resp.json();
        if (!json.success) throw new Error(json.error || 'NED error');
        nedData = json.results || [];
        _nedFromCache  = json.from_cache  || false;
        _nedSearchedAt = json.searched_at || null;
        _nedCurrentHostName = json.current_host || '';
        return nedData;
    } catch (e) {
        console.error('NED fetch failed:', e);
        return null;
    }
}

function changeNEDSurvey() {
    const sel = document.getElementById('nedSurveySelect');
    if (!sel) return;
    const iframe = document.getElementById('ned-aladin-iframe');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({type: 'changeSurvey', survey: sel.value}, window.location.origin);
    }
}

function openNEDExplorer() {
    const modal = document.getElementById('nedExplorerModal');
    if (modal) { modal.style.display = 'flex'; }
    // Always hit backend once per open so server-side NED logs are recorded.
    // Backend will return DB cache unless forceNED=true.
    _initNEDExplorer(true, false);
}

function rerunNEDSearch() {
    if (_nedRetryTimer) { clearInterval(_nedRetryTimer); _nedRetryTimer = null; }
    nedData = null;  // clear cache so fetchNEDData runs with force=true
    _initNEDExplorer(true, true);  // forceRefresh=true, forceNED=true
}

function closeNEDExplorer() {
    const modal = document.getElementById('nedExplorerModal');
    if (modal) modal.style.display = 'none';
    if (_nedHoverListener) { window.removeEventListener('message', _nedHoverListener); _nedHoverListener = null; }
    if (_nedRetryTimer) { clearInterval(_nedRetryTimer); _nedRetryTimer = null; }
}

async function setNEDHost(idx, btnEl) {
    if (!Array.isArray(nedData) || idx < 0 || idx >= nedData.length) return;
    const row = nedData[idx] || {};
    if (!row.objname) {
        showNotification('NED row has no object name', 'error');
        return;
    }

    const btn = btnEl || null;
    if (btn) { btn.disabled = true; btn.textContent = 'Setting...'; }

    try {
        const resp = await fetch('/api/ned/set_host', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                target_name: objectName,
                host_name: row.objname,
                ra: row.ra,
                dec: row.dec,
                type: row.type || '',
                redshift: row.redshift,
                redshift_type: row.redshift_type || '',
                distance_arcmin: row.distance_arcmin,
            }),
        });
        const json = await resp.json();
        if (!resp.ok || !json.success) {
            throw new Error(json.error || json.message || `HTTP ${resp.status}`);
        }

        _nedCurrentHostName = row.objname;
        _initNEDExplorer(false, false);

        if (json.updated_redshift && json.redshift != null) {
            const zNum = Number(json.redshift);
            objectData.redshift = Number.isFinite(zNum) ? zNum : json.redshift;
            const zEl = document.getElementById('redshiftValue');
            if (zEl && Number.isFinite(zNum)) zEl.textContent = zNum.toFixed(5);
            showNotification(`Host set to ${row.objname}; redshift updated`, 'success');
        } else {
            showNotification(`Host set to ${row.objname}; redshift unchanged (z flag not S*)`, 'success');
        }
    } catch (e) {
        console.error('setNEDHost failed:', e);
        showNotification(`Set host failed: ${e.message || e}`, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Set as Host';
        }
    }
}

async function unsetNEDHost(idx, btnEl) {
    if (!Array.isArray(nedData) || idx < 0 || idx >= nedData.length) return;
    const row = nedData[idx] || {};
    if (!row.objname) return;

    const btn = btnEl || null;
    if (btn) { btn.disabled = true; btn.textContent = 'Removing...'; }

    try {
        const resp = await fetch('/api/ned/unset_host', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ target_name: objectName }),
        });
        const json = await resp.json();
        if (!resp.ok || !json.success) {
            throw new Error(json.error || json.message || `HTTP ${resp.status}`);
        }
        _nedCurrentHostName = '';
        _initNEDExplorer(false, false);
        showNotification(`Host removed: ${row.objname}`, 'success');
    } catch (e) {
        console.error('unsetNEDHost failed:', e);
        showNotification(`Unset host failed: ${e.message || e}`, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Unset Host';
        }
    }
}

async function _initNEDExplorer(forceRefresh = false, forceNED = false) {
    const container = document.getElementById('nedAladinContainer');
    const loading   = document.getElementById('nedAladinLoading');
    const countEl   = document.getElementById('nedResultCount');
    const tbody     = document.getElementById('nedResultBody');
    if (!objectData) return;

    const ra  = parseFloat(objectData.ra);
    const dec = parseFloat(objectData.declination);

    const radiusArcsec = _getNEDRadiusArcsec();
    if (loading) loading.style.display = 'flex';
    countEl.textContent = `Fetching NED data (${radiusArcsec}")…`;
    if (forceRefresh || !nedData) {
        await fetchNEDData(radiusArcsec, forceNED);
    }

    // Handle NED upstream timeout — show countdown and auto-retry
    if (_nedTimedOut) {
        if (loading) loading.style.display = 'none';
        let remaining = 10;
        countEl.textContent = `NED request timed out. Retrying in ${remaining}s…`;
        tbody.innerHTML = `<tr><td colspan="9" style="padding:20px; text-align:center; color:#f59e0b;">NED server did not respond. Retrying automatically…</td></tr>`;
        if (_nedRetryTimer) clearInterval(_nedRetryTimer);
        _nedRetryTimer = setInterval(function() {
            remaining -= 1;
            const modal = document.getElementById('nedExplorerModal');
            if (!modal || modal.style.display === 'none') {
                clearInterval(_nedRetryTimer); _nedRetryTimer = null; return;
            }
            if (remaining <= 0) {
                clearInterval(_nedRetryTimer); _nedRetryTimer = null;
                _initNEDExplorer(true);
            } else {
                countEl.textContent = `NED request timed out. Retrying in ${remaining}s…`;
            }
        }, 1000);
        return;
    }

    const sources = (nedData || [])
        .map((o, i) => ({ra: Number(o.ra), dec: Number(o.dec), name: o.objname || '', type: o.type || '', idx: i}))
        .filter(s => Number.isFinite(s.ra) && Number.isFinite(s.dec));
    const _cacheNote = _nedFromCache && _nedSearchedAt
        ? ` · <span style="color:#f59e0b; font-size:0.75rem;" title="Loaded from database cache">cached ${new Date(_nedSearchedAt).toLocaleString()}</span>`
        : ` · <span style="color:#4ade80; font-size:0.75rem;">live from NED</span>`;
    const _hostNote = _nedCurrentHostName
        ? ` · <span style="color:#00f5d4; font-size:0.75rem;">host: ${_nedCurrentHostName}</span>`
        : '';
    countEl.innerHTML = (sources.length
        ? `${sources.length} NED object(s) within ${radiusArcsec}"`
        : `No NED objects found within ${radiusArcsec}"`) + _cacheNote + _hostNote;

    // Build table
    tbody.innerHTML = '';
    if (!nedData || nedData.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="padding:20px; text-align:center; color:#666;">No NED objects found within ${radiusArcsec}"</td></tr>`;
    } else {
        nedData.forEach((obj, i) => {
            const z   = obj.redshift != null ? parseFloat(obj.redshift) : null;
            const cz  = z != null ? Math.round(z * 299792.458).toLocaleString() : '—';
            const canSetZ = String(obj.redshift_type || '').startsWith('S') && z != null;
            const isCurrentHost = !!_nedCurrentHostName && (String(obj.objname || '') === String(_nedCurrentHostName));
            const tr  = document.createElement('tr');
            tr.dataset.idx = i;
            tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.06); cursor:default; transition:background 0.1s;';
            tr.innerHTML = `
                <td style="padding:5px 8px; color:#555;">${i + 1}</td>
                <td style="padding:5px 8px; color:#00f5d4; white-space:nowrap;">${obj.objname || '—'}${isCurrentHost ? ' <span style="color:#00f5d4; font-size:0.7rem; border:1px solid rgba(0,245,212,0.5); border-radius:999px; padding:1px 6px; margin-left:6px;">HOST</span>' : ''}</td>
                <td style="padding:5px 8px;">${obj.type || '—'}</td>
                <td style="padding:5px 8px; text-align:right; font-family:monospace;">${obj.ra != null ? parseFloat(obj.ra).toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right; font-family:monospace;">${obj.dec != null ? parseFloat(obj.dec).toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right;">${z != null ? z.toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right;">${cz}</td>
                <td style="padding:5px 8px; color:#aaa;">${obj.redshift_type || '—'}</td>
                <td style="padding:4px 8px; text-align:center; white-space:nowrap;">
                    ${isCurrentHost
                        ? `<button class="ned-host-btn" onclick="unsetNEDHost(${i}, this)" title="Unset current host" style="font-size:0.72rem; padding:2px 8px; border:1px solid rgba(248,113,113,0.6); border-radius:6px; background:rgba(248,113,113,0.08); color:#f87171; cursor:pointer;">Unset Host</button>`
                        : `<button class="ned-host-btn" onclick="setNEDHost(${i}, this)" title="Set this NED object as host${canSetZ ? ' (redshift will update)' : ' (redshift will NOT update: z flag not S*)'}" style="font-size:0.72rem; padding:2px 8px; border:1px solid rgba(255,255,255,0.2); border-radius:6px; background:rgba(255,255,255,0.04); color:#ddd; cursor:pointer;">Set as Host</button>`}
                </td>`;
            tr.addEventListener('mouseenter', () => {
                document.querySelectorAll('#nedResultBody tr').forEach(r => r.style.background = '');
                tr.style.background = 'rgba(0,245,212,0.1)';
                const iframe = document.getElementById('ned-aladin-iframe');
                if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage({type: 'highlightNED', idx: i}, window.location.origin);
            });
            tr.addEventListener('mouseleave', () => {
                tr.style.background = '';
                const iframe = document.getElementById('ned-aladin-iframe');
                if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage({type: 'highlightNED', idx: -1}, window.location.origin);
            });
            tbody.appendChild(tr);
        });
    }

    _buildNEDAladinIframe(container, loading, ra, dec, sources, radiusArcsec);

    // Receive hover events back from iframe
    if (_nedHoverListener) window.removeEventListener('message', _nedHoverListener);
    _nedHoverListener = function(e) {
        if (!e.data) return;
        if (e.data.type === 'nedHover') {
            const idx = e.data.idx;
            document.querySelectorAll('#nedResultBody tr').forEach(r => {
                r.style.background = parseInt(r.dataset.idx) === idx ? 'rgba(0,245,212,0.1)' : '';
            });
            if (idx >= 0) {
                const row = document.querySelector(`#nedResultBody tr[data-idx="${idx}"]`);
                if (row) row.scrollIntoView({block: 'nearest', behavior: 'smooth'});
            }
        }
    };
    window.addEventListener('message', _nedHoverListener);
}

function _buildNEDAladinIframe(container, loading, ra, dec, sources, radiusArcsec) {
    const old = document.getElementById('ned-aladin-iframe');
    if (old) old.remove();

    const targetName = ((objectData && (objectData.name || objectData.iauname)) || objectName || '').replace(/'/g, "\\'");
    const fov = Math.max((radiusArcsec * 2.4) / 3600, 0.01).toFixed(6);

    const html = `<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
  body,html{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#000;}
  #al{width:100%;height:100%;}
</style>
<script src="https://code.jquery.com/jquery-3.6.0.min.js"><\/script>
<script src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js" crossorigin="anonymous"><\/script>
</head><body>
<div id="al"></div>
<script>
  const T_RA = ${ra}, T_DEC = ${dec};
  let al, nedCat;

  A.init.then(function() {
    al = A.aladin('#al', {
      survey: '${currentSurvey}',
      fov: ${fov},
      target: T_RA + ' ' + T_DEC,
      cooFrame: 'ICRS',
      showReticle: false,
      showZoomControl: true,
      showFullscreenControl: false,
      showLayersControl: false,
      showGotoControl: false,
      showShareControl: false,
      showFrame: false,
      showCooGrid: false,
      showProjectionControl: false,
      showSimbadPointerControl: false,
      showCooGridControl: false,
      showSettings: false,
      showLogo: true,
      showContextMenu: false,
      allowFullZoomout: true,
      showStatusBar: false,
    });

    // Target marker
    var tCat = A.catalog({name:'Target', color:'#ff4444', sourceSize:16, shape:'cross'});
    tCat.addSources([A.source(T_RA, T_DEC, {name:'${targetName}', idx:-1})]);
    al.addCatalog(tCat);

    // Register hover events
    al.on('objectHovered', function(obj) {
      if (obj && obj.data && typeof obj.data.idx !== 'undefined' && obj.data.idx >= 0)
        window.parent.postMessage({type:'nedHover', idx: obj.data.idx}, window.location.origin);
    });
    al.on('objectHoveredStop', function() {
      window.parent.postMessage({type:'nedHover', idx:-1}, window.location.origin);
    });

    // Signal parent that Aladin is ready
    window.parent.postMessage({type:'nedAladinReady'}, window.location.origin);
  });

  window.addEventListener('message', function(e) {
    if (!e.data || !al) return;
    var d = e.data;
    if (d.type === 'addNEDSources') {
      if (nedCat) { try { al.removeCatalog && al.removeCatalog(nedCat); } catch(_) {} }
      nedCat = A.catalog({name:'NED', color:'#f59e0b', sourceSize:14, shape:'circle'});
      al.addCatalog(nedCat);
      var srcs = (d.sources || []).map(function(s) {
        return A.source(s.ra, s.dec, {name: s.name, type: s.type, idx: s.idx});
      });
      nedCat.addSources(srcs);
    } else if (d.type === 'changeSurvey') {
      al.setImageSurvey(d.survey);
    } else if (d.type === 'highlightNED' && nedCat) {
      var idx = d.idx;
      nedCat.getSources().forEach(function(s){ s.color = null; });
      if (idx >= 0) {
        var match = nedCat.getSources().find(function(s){ return s.data && s.data.idx === idx; });
        if (match) match.color = '#00f5d4';
      }
      al.view && al.view.requestRedraw();
    }
  });
<\/script>
</body></html>`;

    const iframe = document.createElement('iframe');
    iframe.id    = 'ned-aladin-iframe';
    iframe.style.cssText = 'width:100%; height:100%; border:none;';
    iframe.srcdoc = html;
    container.appendChild(iframe);

    // Once Aladin signals ready, hide loading overlay and send NED sources
    const onReady = function(e) {
        if (e.data && e.data.type === 'nedAladinReady') {
            window.removeEventListener('message', onReady);
            if (loading) loading.style.display = 'none';
            // Send sources now that Aladin is fully initialized
            const iframeEl = document.getElementById('ned-aladin-iframe');
            if (iframeEl && iframeEl.contentWindow) {
                iframeEl.contentWindow.postMessage({type: 'addNEDSources', sources: sources}, window.location.origin);
            }
        }
    };
    window.addEventListener('message', onReady);
}
