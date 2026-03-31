let obsFilters = [];
let logTriggerFilters = [];
let logObservedFilters = [];
let logDict = {};
let cachedLogData = [];
let cachedLogYear = null;
let cachedLogMonth = null;
let availableLogMonths = [];
let searchTimeout = null;
let targetCoordDisplayMode = 'sexagesimal';

document.addEventListener('DOMContentLoaded', function() {
    console.log("Private Area loaded.");
    loadTargets();
    initObservationLog();

    // Close search dropdown when clicking outside
    document.addEventListener('click', function(e) {
        const dropdown = document.getElementById('search-results-dropdown');
        const nameInput = document.getElementById('obs-name');
        if (dropdown && nameInput && !nameInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });
});

// Ensure filters are displayed in a fixed, preferred order.
function sortFiltersInPlace(arr) {
    if (!Array.isArray(arr) || arr.length <= 1) return;
    const order = ['up','gp','rp','ip','zp','yp','u','b','v','r','i','other'];
    arr.forEach((it, idx) => { it._origIndex = idx; });
    arr.sort((a, b) => {
        const ka = (a.filter || '').toString().trim().toLowerCase();
        const kb = (b.filter || '').toString().trim().toLowerCase();
        const ia = order.indexOf(ka);
        const ib = order.indexOf(kb);
        const ra = ia === -1 ? 999 : ia;
        const rb = ib === -1 ? 999 : ib;
        if (ra !== rb) return ra - rb;
        return a._origIndex - b._origIndex;
    });
    arr.forEach(it => { delete it._origIndex; });
}

// Sorting helper specifically for log display: supports calibration-only sorting
function sortLogFilters(arr, isCalibrationTarget) {
    if (!Array.isArray(arr) || arr.length <= 1) return;
    const order = ['up','gp','rp','ip','zp','yp','u','b','v','r','i','other'];
    arr.forEach((it, idx) => { it._origIndex = idx; });
    arr.sort((a, b) => {
        const fa = (a.filter || '').toString().trim().toLowerCase();
        const fb = (b.filter || '').toString().trim().toLowerCase();
        const ea = Number(a.exp) || 0;
        const eb = Number(b.exp) || 0;

        if (isCalibrationTarget) {
            // For calibration targets (DARK/BIAS) sort by exposure seconds ascending
            if (ea !== eb) return ea - eb;
            if (a.count !== b.count) return (Number(a.count)||0) - (Number(b.count)||0);
            return a._origIndex - b._origIndex;
        }

        // For normal targets: sort by preferred filter order, then by exposure seconds asc
        const ia = order.indexOf(fa);
        const ib = order.indexOf(fb);
        const ra = ia === -1 ? 999 : ia;
        const rb = ib === -1 ? 999 : ib;
        if (ra !== rb) return ra - rb;
        if (ea !== eb) return ea - eb;
        return a._origIndex - b._origIndex;
    });
    arr.forEach(it => { delete it._origIndex; });
}

function switchTab(tabId) {
    const tabs = ['SLT', 'LOT'];
    tabs.forEach(t => {
        document.getElementById('content-' + t).style.display = (t === tabId) ? 'block' : 'none';
        const btn = document.getElementById('tab-' + t);
        const addBtn = document.getElementById('btn-add-' + t.toLowerCase());
        
        if (t === tabId) {
            btn.classList.add('active');
            if(addBtn) addBtn.style.display = 'flex';
        } else {
            btn.classList.remove('active');
            if(addBtn) addBtn.style.display = 'none';
        }
    });
}

// ===================== Target Search =====================
function searchTarget(query) {
    const dropdown = document.getElementById('search-results-dropdown');
    if (!dropdown) return;

    if (query.length < 2) {
        dropdown.style.display = 'none';
        return;
    }

    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            const resp = await fetch('/api/search_target?q=' + encodeURIComponent(query));
            const data = await resp.json();
            if (data.results && data.results.length > 0) {
                dropdown.innerHTML = '';
                data.results.forEach(obj => {
                    const item = document.createElement('div');
                    item.className = 'pa-search-item';

                    const raDeg  = obj.ra  != null ? parseFloat(obj.ra).toFixed(5)  : '';
                    const decDeg = obj.dec != null ? parseFloat(obj.dec).toFixed(5) : '';
                    const magStr = obj.mag != null ? parseFloat(obj.mag).toFixed(1)  : '';
                    const typeStr = obj.type ? obj.type : 'AT';
                    const internalStr = obj.internal_names ? obj.internal_names : '';

                    // Row 1: [Name type mag]  [RA]
                    // Row 2: [InternalName]   [DEC]
                    item.innerHTML =
                        '<div class="pa-search-item-main">' +
                            '<span class="pa-search-item-name">' + obj.prefix + obj.name + '</span>' +
                            '<span class="pa-search-item-type">' + typeStr + '</span>' +
                            (magStr ? '<span class="pa-search-item-mag">mag&nbsp;' + magStr + '</span>' : '') +
                        '</div>' +
                        '<span class="pa-search-item-ra">' + raDeg + '</span>' +
                        '<span class="pa-search-item-internal">' + internalStr + '</span>' +
                        '<span class="pa-search-item-dec">' + decDeg + '</span>';

                    item.onclick = () => selectSearchResult(obj);
                    dropdown.appendChild(item);
                });
                dropdown.style.display = 'block';
            } else {
                dropdown.innerHTML = '<div class="pa-search-empty">No results found</div>';
                dropdown.style.display = 'block';
            }
        } catch (e) {
            console.error('Search error:', e);
            dropdown.style.display = 'none';
        }
    }, 300);
}

function selectSearchResult(obj) {
    document.getElementById('obs-name').value = obj.prefix + obj.name;

    // Convert RA from degrees to hh:mm:ss
    if (obj.ra != null) {
        document.getElementById('obs-ra').value = degToHMS(parseFloat(obj.ra));
    }
    // Convert Dec from degrees to dd:mm:ss
    if (obj.dec != null) {
        document.getElementById('obs-dec').value = degToDMS(parseFloat(obj.dec));
    }
    // Fill magnitude
    if (obj.mag != null) {
        document.getElementById('obs-mag').value = parseFloat(obj.mag).toFixed(1);
    }

    document.getElementById('search-results-dropdown').style.display = 'none';
}

function degToHMS(deg) {
    let h = deg / 15.0;
    let hh = Math.floor(h);
    let remainder = (h - hh) * 60;
    let mm = Math.floor(remainder);
    let ss = (remainder - mm) * 60;
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0') + ':' + ss.toFixed(2).padStart(5, '0');
}

function degToDMS(deg) {
    let sign = deg < 0 ? '-' : '+';
    let absDeg = Math.abs(deg);
    let dd = Math.floor(absDeg);
    let remainder = (absDeg - dd) * 60;
    let mm = Math.floor(remainder);
    let ss = (remainder - mm) * 60;
    return sign + String(dd).padStart(2, '0') + ':' + String(mm).padStart(2, '0') + ':' + ss.toFixed(1).padStart(4, '0');
}

function parseRAToDeg(rawRA) {
    if (rawRA == null) return null;
    const s = String(rawRA).trim();
    if (!s) return null;

    if (s.includes(':')) {
        const parts = s.split(':').map(p => parseFloat(p));
        if (parts.some(v => Number.isNaN(v))) return null;
        const hh = parts[0] || 0;
        const mm = parts[1] || 0;
        const ss = parts[2] || 0;
        return (hh + mm / 60 + ss / 3600) * 15;
    }

    const v = parseFloat(s);
    return Number.isNaN(v) ? null : v;
}

function parseDecToDeg(rawDec) {
    if (rawDec == null) return null;
    const s = String(rawDec).trim();
    if (!s) return null;

    if (s.includes(':')) {
        const sign = s.startsWith('-') ? -1 : 1;
        const clean = s.replace(/^[-+]/, '');
        const parts = clean.split(':').map(p => parseFloat(p));
        if (parts.some(v => Number.isNaN(v))) return null;
        const dd = parts[0] || 0;
        const mm = parts[1] || 0;
        const ss = parts[2] || 0;
        return sign * (dd + mm / 60 + ss / 3600);
    }

    const v = parseFloat(s);
    return Number.isNaN(v) ? null : v;
}

function formatTargetCoordValue(rawRA, rawDec) {
    const raDeg = parseRAToDeg(rawRA);
    const decDeg = parseDecToDeg(rawDec);

    if (targetCoordDisplayMode === 'decimal') {
        return {
            ra: raDeg != null ? raDeg.toFixed(5) : (rawRA || '-'),
            dec: decDeg != null ? decDeg.toFixed(5) : (rawDec || '-')
        };
    }

    return {
        ra: raDeg != null ? degToHMS(raDeg) : (rawRA || '-'),
        dec: decDeg != null ? degToDMS(decDeg) : (rawDec || '-')
    };
}

function toggleTargetCoordDisplayMode() {
    targetCoordDisplayMode = targetCoordDisplayMode === 'sexagesimal' ? 'decimal' : 'sexagesimal';
    if (!Array.isArray(allTargetsCache) || allTargetsCache.length === 0) return;
    
    ['SLT', 'LOT'].forEach(telescope => {
        let targets = allTargetsCache.filter(function(t) { return t.telescope === telescope; });
        let state = currentSortState[telescope];
        if (state) {
            targets = applySort(targets, state.column, state.dir);
        }
        renderTable(telescope, targets);
    });
}

// ===================== Modal =====================
function openTargetModal(telescope) {
    document.getElementById('targetModal').style.display = 'flex'; // Changed to flex for centering
    document.getElementById('obs-telescope').value = telescope;
    document.getElementById('add-target-form').reset();
    obsFilters = [];
    toggleTelescopeUI(telescope);
    renderFilterRows();
    // Clear name hint on open
    var hint = document.getElementById('obs-name-hint');
    if (hint) { hint.textContent = ''; hint.className = 'pa-name-hint'; }
}

// Real-time name hint as user types
// Hard-block survey IDs (exclude ZTF — it becomes orange warn + confirm)
var SURVEY_PREFIXES_CHECK = ['ATLAS', 'PS', 'PS1', 'PS2', 'MASTER', 'GAIA', 'TNS', 'CSS', 'CRTS', 'ASAS', 'OGLE', 'SDSS', 'DES', 'LSQ', 'MLS', 'SSS', 'PTF', 'IPTF', 'MUSSES'];
function checkTargetNameHint(value) {
    var hint = document.getElementById('obs-name-hint');
    if (!hint) return;
    var v = value.trim();
    if (!v) { hint.textContent = ''; hint.className = 'pa-name-hint'; return; }
    var upper = v.toUpperCase();
    if (upper.startsWith('ZTF')) {
        hint.textContent = '\u26a0\ufe0f ZTF ID \u2014 prefer TNS/IAU or EP name. Confirmation required.';
        hint.className = 'pa-name-hint warn';
    } else {
        var badPrefix = SURVEY_PREFIXES_CHECK.find(function(p) { return upper.startsWith(p); });
        if (badPrefix) {
            hint.textContent = '\u26d4 Survey ID (' + badPrefix + ') \u2014 please use TNS/IAU or EP name.';
            hint.className = 'pa-name-hint error';
        } else if (/^(AT|SN|EP)\s/i.test(v) || /^(AT|SN|EP)\d/i.test(v)) {
            hint.textContent = '\u2713 Good \u2014 TNS/IAU or EP name detected.';
            hint.className = 'pa-name-hint ok';
        } else {
            hint.textContent = '\u26a0\ufe0f Prefix not AT/SN/EP \u2014 confirmation required on submit.';
            hint.className = 'pa-name-hint warn';
        }
    }
}

function closeTargetModal() {
    document.getElementById('targetModal').style.display = 'none';
    const dd = document.getElementById('search-results-dropdown');
    if (dd) dd.style.display = 'none';
    editingTargetId = null;
}

function toggleTelescopeUI(telescope) {
    const lotContainer = document.getElementById('lot-programs-container');
    const sltAutoExpContainer = document.getElementById('slt-auto-exp-container');

    if (lotContainer) {
        lotContainer.style.display = (telescope === 'LOT') ? 'block' : 'none';
    }
    if (sltAutoExpContainer) {
        sltAutoExpContainer.style.display = (telescope === 'SLT') ? 'flex' : 'none';
    }

    renderFilterRows();
}

// ===================== Auto Exposure Button =====================
async function applyAutoExposure() {
    const telescope = document.getElementById('obs-telescope').value;
    const magInput = document.getElementById('obs-mag').value.trim();
    const hintEl = document.getElementById('auto-exp-hint');

    if (!magInput) {
        if (hintEl) hintEl.innerText = 'Please enter magnitude first';
        setTimeout(() => { if (hintEl) hintEl.innerText = ''; }, 3000);
        return;
    }

    const mag = parseFloat(magInput);
    if (isNaN(mag)) {
        if (hintEl) hintEl.innerText = 'Invalid magnitude value';
        setTimeout(() => { if (hintEl) hintEl.innerText = ''; }, 3000);
        return;
    }

    if (hintEl) hintEl.innerText = 'Loading...';

    try {
        const resp = await fetch('/api/auto_exposure?mag=' + encodeURIComponent(magInput) + '&telescope=' + encodeURIComponent(telescope));
        const data = await resp.json();

        if (data.error) {
            if (hintEl) hintEl.innerText = data.error;
            setTimeout(() => { if (hintEl) hintEl.innerText = ''; }, 4000);
            return;
        }

        if (data.success && data.filters) {
            obsFilters = data.filters.map(f => ({ filter: f.filter, exp: f.exp, count: f.count }));
            const summary = obsFilters.map(f => f.filter + ' ' + f.exp + 's x' + f.count).join(', ');
            if (hintEl) hintEl.innerText = 'Auto: ' + summary;
            setTimeout(() => { if (hintEl) hintEl.innerText = ''; }, 5000);
            renderFilterRows();
        }
    } catch (e) {
        console.error('Auto exposure error:', e);
        if (hintEl) hintEl.innerText = 'Network error';
        setTimeout(() => { if (hintEl) hintEl.innerText = ''; }, 3000);
    }
}

// ===================== Filter Rows =====================
function addFilterRow(filterName) {
    obsFilters.push({ filter: filterName || '', exp: 300, count: 1 });
    renderFilterRows();
}

function addAllFilters(filters) {
    const existing = obsFilters.map(f => f.filter);
    filters.forEach(f => {
        if (!existing.includes(f)) {
            obsFilters.push({ filter: f, exp: 300, count: 1 });
        }
    });
    renderFilterRows();
}

function removeFilterRow(index) {
    obsFilters.splice(index, 1);
    renderFilterRows();
}

function updateFilterRow(index, field, value) {
    obsFilters[index][field] = value;
    renderFilterRows();
}

function renderFilterRows() {
    const container = document.getElementById('filter-rows-container');
    const totalContainer = document.getElementById('total-exposure-container');
    const totalText = document.getElementById('total-exposure-text');

    if (!container) return;
    // Sort obsFilters into preferred order before rendering
    sortFiltersInPlace(obsFilters);
    container.innerHTML = '';

    let totalSec = 0;
    const predefinedFilters = ['up', 'gp', 'rp', 'ip', 'zp'];

    obsFilters.forEach(function(row, idx) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'pa-filter-row';

        const isPredefined = predefinedFilters.includes(row.filter);
        const dropdownValue = isPredefined ? row.filter : (row.filter ? 'custom' : '');
        const customDisplay = (!isPredefined && row.filter) ? 'inline-block' : 'none';

        let rowHtml = '<div class="pa-field filter-name" style="position: relative;">' +
            '<span class="pa-field-label">Filter</span>' +
            '<select onchange="if(this.value === \'custom\') { this.nextElementSibling.style.display=\'inline-block\'; this.nextElementSibling.focus(); } else { this.nextElementSibling.style.display=\'none\'; updateFilterRow(' + idx + ', \'filter\', this.value); }">' +
                '<option value="" ' + (!row.filter ? 'selected' : '') + ' disabled>Select...</option>' +
                '<option value="up" ' + (row.filter === 'up' ? 'selected' : '') + '>up</option>' +
                '<option value="gp" ' + (row.filter === 'gp' ? 'selected' : '') + '>gp</option>' +
                '<option value="rp" ' + (row.filter === 'rp' ? 'selected' : '') + '>rp</option>' +
                '<option value="ip" ' + (row.filter === 'ip' ? 'selected' : '') + '>ip</option>' +
                '<option value="zp" ' + (row.filter === 'zp' ? 'selected' : '') + '>zp</option>' +
                '<option value="custom" ' + (dropdownValue === 'custom' ? 'selected' : '') + '>Custom...</option>' +
            '</select>' +
            '<input type="text" value="' + (!isPredefined ? row.filter : '') + '" placeholder="Custom Filter" style="display:' + customDisplay + '; margin-top: 5px; width: 100%;" onchange="updateFilterRow(' + idx + ', \'filter\', this.value)">' +
            '</div>';

        rowHtml += '<div class="pa-field filter-exp">' +
            '<span class="pa-field-label">Exp (sec)</span>' +
            '<input type="number" value="' + row.exp + '" min="0" onchange="updateFilterRow(' + idx + ', \'exp\', parseInt(this.value)||0)">' +
            '</div>';

        rowHtml += '<div class="pa-field filter-count">' +
            '<span class="pa-field-label">Count</span>' +
            '<input type="number" value="' + row.count + '" min="1" onchange="updateFilterRow(' + idx + ', \'count\', parseInt(this.value)||1)">' +
            '</div>';

        rowHtml += '<div class="pa-filter-subtotal">= ' + (row.exp * row.count) + 's</div>';
        totalSec += (row.exp * row.count);

        rowHtml += '<button type="button" onclick="removeFilterRow(' + idx + ')" class="pa-btn-remove-filter">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="8" y1="12" x2="16" y2="12"></line></svg>' +
            '</button>';

        rowDiv.innerHTML = rowHtml;
        container.appendChild(rowDiv);
    });

    if (obsFilters.length > 0) {
        if (totalContainer) totalContainer.style.display = 'block';
        if (totalText) totalText.innerText = totalSec + 's (' + (totalSec / 60).toFixed(1) + ' min)';
    } else {
        if (totalContainer) totalContainer.style.display = 'none';
    }
}

// ===================== Save Target =====================
async function addObservationTarget(event) {
    event.preventDefault();

    const telescope = document.getElementById('obs-telescope').value;
    const name = document.getElementById('obs-name').value.trim();

    // Validate target name prefix
    const nameTrimmed = name.trim();
    const upperName = nameTrimmed.toUpperCase();
// Hard-block (ATLAS, PS1, etc.) but ZTF only needs confirm
    const SURVEY_BLOCK = ['ATLAS', 'PS', 'PS1', 'PS2', 'MASTER', 'GAIA', 'TNS', 'CSS', 'CRTS', 'ASAS', 'OGLE', 'SDSS', 'DES', 'LSQ', 'MLS', 'SSS', 'PTF', 'IPTF', 'MUSSES'];
    const hasBlockPrefix = SURVEY_BLOCK.some(function(p) { return upperName.startsWith(p); });
    const hasGoodPrefix = /^(AT|SN|EP)\s/i.test(nameTrimmed) || /^(AT|SN|EP)\d/i.test(nameTrimmed);
    const isZTF = upperName.startsWith('ZTF');

    if (hasBlockPrefix) {
        alert('Please use the TNS/IAU name (AT/SN prefix) or EP name instead of a survey ID (' + SURVEY_BLOCK.find(function(p){ return upperName.startsWith(p); }) + ').');
        return;
    }
    if (isZTF || !hasGoodPrefix) {
        const msg = isZTF
            ? 'The name "' + nameTrimmed + '" looks like a ZTF ID.\n\nPlease use the TNS/IAU (AT/SN) or EP name whenever possible.\n\nContinue with ZTF name?'
            : 'The target name "' + nameTrimmed + '" does not start with AT, SN, or EP.\n\nPlease use the TNS/IAU name (AT/SN) or EP name whenever possible.\n\nAre you sure you want to continue with this name?';
        const confirmed = window.confirm(msg);
        if (!confirmed) return;
    }

    const mag = document.getElementById('obs-mag') ? document.getElementById('obs-mag').value : '';
    const ra = document.getElementById('obs-ra').value;
    const dec = document.getElementById('obs-dec').value;
    const priority = document.getElementById('obs-priority').value;
    const repeatCount = document.getElementById('obs-count') ? parseInt(document.getElementById('obs-count').value) : 0;

    let plan = document.getElementById('obs-plan').value || '';
    let note_gl = document.getElementById('obs-note-gl') ? document.getElementById('obs-note-gl').value || '' : '';
    if (priority === 'Urgent' && !plan.trim()) {
        alert('Urgent priority requires a note!');
        return;
    }

    const lotProgram = document.getElementById('obs-program') ? document.getElementById('obs-program').value.trim() : '';
    if (telescope === 'LOT' && !lotProgram) {
        alert('Program is required for LOT e.g. R01!');
        return;
    }

    if (obsFilters.length === 0) {
        alert('Please add at least one filter configuration.');
        return;
    }

    const targetData = {
        telescope: telescope,
        name: name,
        mag: mag,
        ra: ra,
        dec: dec,
        priority: priority,
        repeat_count: repeatCount,
        auto_exposure: false,
        filters: obsFilters,
        plan: plan,
        note_gl: note_gl,
        program: lotProgram
    };

    try {
        let url = '/api/targets';
        let method = 'POST';
        if (editingTargetId) {
            url = '/api/targets/' + editingTargetId;
            method = 'PUT';
        }
        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(targetData)
        });
        const resData = await response.json();
        if (resData.success) {
            loadTargets();
            closeTargetModal();
        } else {
            alert('Failed to save target: ' + resData.error);
        }
    } catch (e) {
        console.error(e);
        alert('Error saving target');
    }
}

// ===================== Load & Render =====================
let sortDirections = {};
let currentSortState = {
    'SLT': { column: 'priority', dir: 'desc' },
    'LOT': { column: 'priority', dir: 'desc' }
};

function applySort(targets, column, dir) {
    const priorityValues = { 'Urgent': 4, 'High': 3, 'Normal': 2, 'Low': 1 };
    return targets.sort((a, b) => {
        // Always put inactive targets at the bottom
        const aActive = a.is_active !== false ? 0 : 1;
        const bActive = b.is_active !== false ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;

        let valA, valB;
        if (column === 'priority') {
            valA = priorityValues[a.priority] || 0;
            valB = priorityValues[b.priority] || 0;
        } else if (column === 'total_exp') {
            valA = 0;
            if (a.filters) {
                a.filters.forEach(f => {
                    if (f.exp && f.count) valA += parseInt(f.exp) * parseInt(f.count);
                });
            }
            valB = 0;
            if (b.filters) {
                b.filters.forEach(f => {
                    if (f.exp && f.count) valB += parseInt(f.exp) * parseInt(f.count);
                });
            }
        }
        
        if (valA < valB) return dir === 'asc' ? -1 : 1;
        if (valA > valB) return dir === 'asc' ? 1 : -1;
        return 0;
    });
}

function sortTargets(telescope, column) {
    let key = telescope + '_' + column;
    if (!sortDirections[key]) {
        sortDirections[key] = 'asc';
    } else {
        sortDirections[key] = sortDirections[key] === 'asc' ? 'desc' : 'asc';
    }
    let dir = sortDirections[key];
    
    currentSortState[telescope] = { column: column, dir: dir };
    
    let targets = allTargetsCache.filter(function(t) { return t.telescope === telescope; });
    targets = applySort(targets, column, dir);
    
    renderTable(telescope, targets);
    
    // Update sort icon
    const tableId = telescope.toLowerCase() + '-head';
    const ths = document.querySelectorAll('#' + tableId + ' th.pa-sortable span');
    ths.forEach(span => span.textContent = '↕');
    
    const thSpan = document.querySelector('#' + tableId + ' th[onclick*="' + column + '"] span');
    if (thSpan) {
        thSpan.textContent = dir === 'asc' ? '↑' : '↓';
    }
}

async function loadTargets() {
    try {
        const response = await fetch('/api/targets');
        const data = await response.json();
        if (data.success) {
            allTargetsCache = data.targets;
            
            // Ensure first programmatic sort triggers 'desc' order
            sortDirections['SLT_priority'] = 'asc';
            sortDirections['LOT_priority'] = 'asc';
            
            sortTargets('SLT', 'priority');
            sortTargets('LOT', 'priority');

            // Populate astro info (moon sep, transit, mini plot) in background
            setTimeout(loadAstroInfoForTargets, 400);
        }
    } catch (e) {
        console.error('Error loading targets:', e);
    }
}

// ===================== Astro Info (moon sep / transit / mini plot) =====================

async function loadAstroInfoForTargets() {
    const targets = allTargetsCache.filter(function(t) { return t.ra && t.dec; });
    if (!targets.length) return;

    // Build name → [ids] map to handle same target in both SLT + LOT
    var nameToIds = {};
    targets.forEach(function(t) {
        if (!nameToIds[t.name]) nameToIds[t.name] = [];
        nameToIds[t.name].push(t.id);
    });

    // Deduplicate by name before sending to API
    var seen = {};
    var uniqueTargets = targets.filter(function(t) {
        if (seen[t.name]) return false;
        seen[t.name] = true;
        return true;
    });

    const now = new Date();
    if (now.getHours() < 12) now.setDate(now.getDate() - 1);
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    const dateStr = yyyy + '-' + mm + '-' + dd;

    try {
        const resp = await fetch('/api/visibility_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                date: dateStr,
                location: '120:52:21 23:28:10 2862',
                timezone: '8',
                telescope: 'ALL',
                targets: uniqueTargets.map(function(t) { return { name: t.name, ra: t.ra, dec: t.dec }; }),
                n_steps: 80
            })
        });
        const data = await resp.json();
        if (!data.success) return;

        // Fill ALL targets that share the same name (handles SLT + LOT duplicates)
        data.targets.forEach(function(td) {
            var ids = nameToIds[td.name] || [];
            ids.forEach(function(id) {
                fillAstroInfo(id, td, data.twilight_local);
            });
        });
    } catch (e) {
        console.error('Astro info fetch error:', e);
    }
}

function fillAstroInfo(targetId, td, twilightLocal) {
    var astroRow = document.getElementById('astro-row-' + targetId);
    var miniPlot = document.getElementById('mini-vp-' + targetId);
    if (!astroRow && !miniPlot) return;

    var moonSep = td.moon_separation != null ? td.moon_separation + '°' : '—';
    var transitLocal = td.transit_time_local ? td.transit_time_local.slice(11, 16) : '—';
    var peakAlt = td.altitudes && td.altitudes.length ? Math.round(Math.max.apply(null, td.altitudes)) : null;
    var peakAltStr = peakAlt != null ? peakAlt + '°' : '—';

    if (astroRow) {
        var spans = astroRow.querySelectorAll('span > span');
        if (spans[0]) spans[0].textContent = moonSep;
        if (spans[1]) spans[1].textContent = transitLocal;
        if (spans[2]) spans[2].textContent = peakAltStr;
        // Color moon sep
        var moonEl = astroRow.querySelector('.pa-astro-moon');
        if (moonEl) moonEl.style.color = moonSepColor(td.moon_separation);
        // Color peak alt
        var peakEl = astroRow.querySelector('.pa-astro-peak');
        if (peakEl) peakEl.style.color = peakAlt != null && peakAlt >= 30 ? 'rgba(100,220,130,0.85)' : 'rgba(255,120,100,0.85)';
    }

    if (miniPlot && td.altitudes && td.altitudes.length) {
        miniPlot.innerHTML = drawMiniVisibilitySVG(td.altitudes, twilightLocal);
    }
}

function moonSepColor(sep) {
    if (sep == null) return 'rgba(255,255,255,0.35)';
    if (sep < 30) return '#ff7675';
    if (sep < 60) return '#ffa94d';
    return '#69db7c';
}

function drawMiniVisibilitySVG(altitudes, twilightLocal) {
    var W = 120, H = 34;
    var N = altitudes.length;
    if (!N) return '';

    // Y coordinate for given altitude
    function yFor(a) { return H - Math.max(0, Math.min(a, 90)) / 90 * H; }

    // Build a two-color polyline: above 30° vs below
    var above = [], below = [];
    var prevAbove = null;
    for (var i = 0; i < N; i++) {
        var x = (i / (N - 1)) * W;
        var y = yFor(altitudes[i]);
        var isAbove = altitudes[i] >= 30;
        if (isAbove) { above.push(x + ',' + y); if (prevAbove === false) above.push(x + ',' + y); }
        else { below.push(x + ',' + y); if (prevAbove === true) below.push(x + ',' + y); }
        prevAbove = isAbove;
    }

    var h30 = yFor(30);
    var h0 = yFor(0);

    return '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" style="display:block; overflow:visible;">' +
        '<line x1="0" y1="' + h0 + '" x2="' + W + '" y2="' + h0 + '" stroke="rgba(255,255,255,0.08)" stroke-width="0.8"/>' +
        '<line x1="0" y1="' + h30 + '" x2="' + W + '" y2="' + h30 + '" stroke="rgba(255,255,255,0.15)" stroke-width="0.8" stroke-dasharray="2,2"/>' +
        (below.length > 1 ? '<polyline points="' + below.join(' ') + '" fill="none" stroke="rgba(255,100,100,0.5)" stroke-width="1.5" stroke-linejoin="round"/>' : '') +
        (above.length > 1 ? '<polyline points="' + above.join(' ') + '" fill="none" stroke="rgba(77,184,255,0.85)" stroke-width="1.5" stroke-linejoin="round"/>' : '') +
        '</svg>';
}

function getObjectRouteName(name) {
    if (!name || typeof name !== 'string') return null;

    const trimmedName = name.trim();
    const routeName = trimmedName.replace(/^(AT|SN)\s*/i, '').trim();
    if (!routeName) return null;

    const upperName = routeName.toUpperCase();
    if (upperName === 'AUTOFLAT' || upperName === 'BIAS' || upperName === 'DARK') {
        return null;
    }

    return routeName;
}

function renderObjectNameLink(name, label) {
    const routeName = getObjectRouteName(name);
    const displayLabel = label || name || '-';

    if (!routeName) {
        return '<span style="vertical-align:middle;">' + displayLabel + '</span>';
    }

    return '<a href="/object/' + encodeURIComponent(routeName) + '" target="_blank" rel="noopener noreferrer" style="vertical-align:middle; color: inherit; text-decoration: none;">' + displayLabel + '</a>';
}

function renderTable(telescope, targets) {
    const tableBody = document.getElementById(telescope.toLowerCase() + '-list');
    if (!tableBody) return;

    tableBody.innerHTML = '';

    if (targets.length === 0) {
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = '<td colspan="8" class="pa-empty-row">No ' + telescope + ' targets added yet.</td>';
        tableBody.appendChild(emptyRow);
        return;
    }

    targets.forEach(function(t) {
        let priorityColor = '#fff';
        if (t.priority === 'Urgent') priorityColor = '#ff4d4d';
        else if (t.priority === 'High') priorityColor = '#ffa64d';

        let filterExpHTML = '';
        let totalExp = 0;

        if (!t.filters || t.filters.length === 0) {
            filterExpHTML = '-';
        } else {
            filterExpHTML = '<div class="pa-filter-stack" style="display: flex; flex-direction: column; gap: 4px;">';
            t.filters.forEach(function(f) {
                if (!f || !f.filter) return;
                
                if (f.exp && f.count) {
                    totalExp += (parseInt(f.exp) * parseInt(f.count));
                }

                let bgStyle = 'linear-gradient(to bottom, rgba(255,255,255,0.2), rgba(255,255,255,0.05))';
                let fStr = f.filter.toLowerCase();
                
                if (fStr === 'up' || fStr === 'u') {
                    bgStyle = 'linear-gradient(to bottom, #8e44ad, #b368d9)';
                } else if (fStr === 'gp' || fStr === 'g') {
                    bgStyle = 'linear-gradient(to bottom, #1785ec, #00a71f)';
                } else if (fStr === 'rp' || fStr === 'r') {
                    bgStyle = 'linear-gradient(to bottom, #ffb74d, #f53500)';
                } else if (fStr === 'ip' || fStr === 'i') {
                    bgStyle = 'linear-gradient(to bottom, #ef5350, #a52a2a)';
                } else if (fStr === 'zp' || fStr === 'z') {
                    bgStyle = 'linear-gradient(to bottom, #a52a2a, #580101)';
                }
                
                let badge = '<span style="background: ' + bgStyle + '; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; color: #fff; min-width: 25px; text-align: center; display: inline-block; font-family: monospace; border: 1px solid rgba(0,0,0,0.1); text-shadow: 0 1px 1px rgba(0,0,0,0.3);">' + f.filter + '</span>';
                
                filterExpHTML += '<div style="display: flex; align-items: center; white-space: nowrap; font-size: 0.85rem;"><span style="display: inline-block; width: 35px; text-align: center;">' + badge + '</span> <span style="margin-left: 8px; color: #aaa; font-family: monospace;">' + f.exp + 's &times; ' + f.count + '</span></div>';
            });
            filterExpHTML += '</div>';
        }

        let programBadge = '';
        if (t.telescope === 'LOT' && t.program) {
            programBadge = '<span class="pa-program-badge">' + t.program + '</span>';
        }
        let magDisplay = '';
        if (t.mag) {
            magDisplay = '<span class="pa-mag-display">[Mag: ' + t.mag + ']</span>';
        }

        let repeatInfo = '';
        if (t.repeat_count > 0) {
            repeatInfo = '<br>(repeat: ' + t.repeat_count + ')';
        }

        let activeToggle = '<label class="pa-action-switch" title="Toggle API visibility">' +
            '<input type="checkbox" onchange="toggleTargetActive(' + t.id + ', this.checked)" ' + (t.is_active !== false ? 'checked' : '') + '>' +
            '<span class="pa-action-slider"></span>' +
            '</label>';

        const tr = document.createElement('tr');
        if (t.is_active === false) {
            tr.style.opacity = '0.5';
        }

        const targetNameHtml = renderObjectNameLink(t.name, t.name);
        const coordDisplay = formatTargetCoordValue(t.ra, t.dec);

        tr.innerHTML = '<td class="pa-td-name" style="vertical-align: middle;">' +
            '<div class="pa-td-name-content" style="display:flex; flex-direction:column; align-items:flex-start; justify-content:center;">' +
                '<div style="display:flex; align-items:center; gap:8px;">' + targetNameHtml + ' ' + programBadge + '</div>' +
                '<div style="margin-top: 4px;">' + magDisplay + '</div>' +
                '<div class="pa-astro-row" id="astro-row-' + t.id + '">' +
                    '<span class="pa-astro-item pa-astro-moon" title="Moon separation">☽ <span>—</span></span>' +
                    '<span class="pa-astro-item pa-astro-transit" title="Transit time (local)">⟳ <span>—</span></span>' +
                    '<span class="pa-astro-item pa-astro-peak" title="Peak altitude">↑ <span>—</span></span>' +
                '</div>' +
                '<div class="pa-mini-plot" id="mini-vp-' + t.id + '"></div>' +
            '</div>' +
            '</td>' +
            '<td class="pa-td-coord" style="cursor:pointer;" onclick="toggleTargetCoordDisplayMode()" title="Click to switch coordinate format">' + coordDisplay.ra + ' <br> ' + coordDisplay.dec + '</td>' +
            '<td class="pa-td-priority" style="color:' + priorityColor + ';">' + t.priority + repeatInfo + '</td>' +
            '<td class="pa-td-filter-exp">' + filterExpHTML + '</td>' +
            '<td class="pa-td-total-exp">' + totalExp + ' s</td>' +
            '<td class="pa-td-note">' + (t.plan || '-') + '</td>' +
            '<td class="pa-td-note-gl">' + (t.note_gl || '-') + '</td>' +
            '<td class="pa-td-actions">' +
                activeToggle +
                '<button onclick="editTarget(' + t.id + ')" class="pa-btn-edit">Edit</button>' +
                '<button onclick="deleteTarget(' + t.id + ')" class="pa-btn-remove">Remove</button>' +
            '</td>';
        tableBody.appendChild(tr);
    });
}

// ===================== Edit Target =====================
let editingTargetId = null;
let allTargetsCache = [];

async function editTarget(id) {
    // Find target from cache or re-fetch
    if (allTargetsCache.length === 0) {
        try {
            const resp = await fetch('/api/targets');
            const data = await resp.json();
            if (data.success) allTargetsCache = data.targets;
        } catch (e) { console.error(e); return; }
    }

    const t = allTargetsCache.find(function(x) { return x.id === id; });
    if (!t) { alert('Target not found'); return; }

    editingTargetId = id;

    // Open modal and fill fields
    document.getElementById('targetModal').style.display = 'flex';
    document.getElementById('obs-telescope').value = t.telescope;
    document.getElementById('obs-name').value = t.name || '';
    document.getElementById('obs-mag').value = t.mag || '';
    document.getElementById('obs-ra').value = t.ra || '';
    document.getElementById('obs-dec').value = t.dec || '';
    document.getElementById('obs-priority').value = t.priority || 'Normal';
    document.getElementById('obs-count').value = t.repeat_count || 0;
    document.getElementById('obs-plan').value = t.plan || '';
    if (document.getElementById('obs-note-gl')) {
        document.getElementById('obs-note-gl').value = t.note_gl || '';
    }

    var programEl = document.getElementById('obs-program');
    if (programEl) programEl.value = t.program || '';

    // Restore filters
    obsFilters = (t.filters && Array.isArray(t.filters)) ? t.filters.map(function(f) {
        return { filter: f.filter || '', exp: f.exp || 300, count: f.count || 1 };
    }) : [];

    toggleTelescopeUI(t.telescope);
    renderFilterRows();
}

async function deleteTarget(id) {
    if (!confirm('Are you sure you want to delete this target?')) return;
    try {
        const response = await fetch('/api/targets/' + id, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            loadTargets();
        } else {
            alert('Failed to delete target: ' + data.error);
        }
    } catch (e) {
        console.error(e);
        alert('Error deleting target');
    }
}

async function toggleTargetActive(id, isActive) {
    try {
        const response = await fetch('/api/targets/' + id + '/toggle', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: isActive })
        });
        const data = await response.json();
        if (data.success) {
            loadTargets();
        } else {
            alert('Failed to update status: ' + data.error);
            loadTargets();
        }
    } catch (e) {
        console.error(e);
        alert('Error updating status');
        loadTargets();
    }
}

// ===================== Observation Log =====================

function initObservationLog() {
    const yearSelect = document.getElementById('log-year');
    const monthSelect = document.getElementById('log-month');
    
    if (!yearSelect || !monthSelect) return;

    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

    const populateMonthsForYear = (year, preferredMonth = null) => {
        const y = parseInt(year);
        const months = availableLogMonths
            .filter(x => parseInt(x.year) === y)
            .map(x => parseInt(x.month))
            .sort((a, b) => b - a);

        monthSelect.innerHTML = '';
        months.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = monthNames[m - 1];
            monthSelect.appendChild(opt);
        });

        if (months.length === 0) return false;
        const useMonth = preferredMonth && months.includes(parseInt(preferredMonth))
            ? parseInt(preferredMonth)
            : months[0];
        monthSelect.value = String(useMonth);
        return true;
    };

    fetch('/api/observation_log_months')
        .then(res => res.json())
        .then(data => {
            availableLogMonths = (data && data.success && Array.isArray(data.months)) ? data.months : [];

            yearSelect.innerHTML = '';
            monthSelect.innerHTML = '';

            if (availableLogMonths.length === 0) {
                yearSelect.innerHTML = '<option value="">No Data</option>';
                monthSelect.innerHTML = '<option value="">No Data</option>';
                return;
            }

            const years = Array.from(new Set(availableLogMonths.map(x => parseInt(x.year)))).sort((a, b) => b - a);
            years.forEach(y => {
                const opt = document.createElement('option');
                opt.value = y;
                opt.textContent = y;
                yearSelect.appendChild(opt);
            });

            const latest = availableLogMonths
                .map(x => ({ year: parseInt(x.year), month: parseInt(x.month) }))
                .sort((a, b) => (b.year - a.year) || (b.month - a.month))[0];

            yearSelect.value = String(latest.year);
            populateMonthsForYear(latest.year, latest.month);

            yearSelect.onchange = () => {
                const ok = populateMonthsForYear(yearSelect.value);
                if (ok) renderLogGrid(false);
            };
            monthSelect.onchange = () => renderLogGrid(false);

            // Ensure members are loaded before the initial log render so avatars appear
            try {
                fetchMembers().then(() => {
                    renderLogGrid(true);
                }).catch(() => {
                    renderLogGrid(true);
                });
            } catch (e) {
                renderLogGrid(true);
            }
        })
        .catch(() => {
            yearSelect.innerHTML = '<option value="">No Data</option>';
            monthSelect.innerHTML = '<option value="">No Data</option>';
        });
}

function splitLogCsv(rawValue) {
    if (rawValue === null || rawValue === undefined) return [];
    const s = String(rawValue).trim();
    if (!s) return [];
    return s.split(',').map(x => x.trim()).filter(Boolean);
}

function parseLogFilterRows(filterVal, expVal, countVal) {
    if (!filterVal) return [];

    try {
        const parsed = JSON.parse(filterVal);
        if (Array.isArray(parsed)) {
            return parsed
                .filter(x => x && x.filter)
                .map(x => ({
                    filter: x.filter,
                    exp: x.exp != null && x.exp !== '' ? Number(x.exp) : 0,
                    count: x.count != null && x.count !== '' ? Number(x.count) : 1
                }));
        }
    } catch (e) {
        // Keep legacy non-JSON paths below.
    }

    const filters = splitLogCsv(filterVal);
    const expList = splitLogCsv(expVal);
    const countList = splitLogCsv(countVal);

    return filters.map((f, idx) => {
        const expRaw = expList[idx] !== undefined ? expList[idx] : (expList.length === 1 ? expList[0] : '0');
        const cntRaw = countList[idx] !== undefined ? countList[idx] : (countList.length === 1 ? countList[0] : '1');
        return {
            filter: f,
            exp: Number(expRaw) || 0,
            count: Number(cntRaw) || 1
        };
    });
}

function packLogFilterColumns(filters) {
    if (!Array.isArray(filters) || filters.length === 0) {
        return { filter: null, exp: null, count: null };
    }

    const clean = filters
        .filter(x => x && x.filter && String(x.filter).trim())
        .map(x => ({
            filter: String(x.filter).trim(),
            exp: Number(x.exp) || 0,
            count: Number(x.count) || 1
        }));

    if (clean.length === 0) {
        return { filter: null, exp: null, count: null };
    }

    return {
        filter: clean.map(x => x.filter).join(','),
        exp: clean.map(x => String(x.exp)).join(','),
        count: clean.map(x => String(x.count)).join(',')
    };
}

async function renderLogGrid(initialLoad = false, skipFetch = false) {
    const yearSelect = document.getElementById('log-year');
    const monthSelect = document.getElementById('log-month');
    const thead = document.getElementById('log-grid-head');
    const tbody = document.getElementById('log-grid-body');

    if (!yearSelect || !monthSelect || !thead || !tbody) return;

    const year = parseInt(yearSelect.value);
    const month = parseInt(monthSelect.value);
    if (!year || !month) {
        thead.innerHTML = '';
        tbody.innerHTML = '';
        return;
    }

    // Calculate days in month
    const daysInMonth = new Date(year, month, 0).getDate();

    // Generate dates array
    const dates = [];
    for (let d = 1; d <= daysInMonth; d++) {
        // Pad with zero
        const ds = d < 10 ? '0'+d : d;
        const ms = month < 10 ? '0'+month : month;
        dates.push({
            dateStr: `${year}-${ms}-${ds}`,
            day: d
        });
    }

    // Fetch targets and corresponding logs
    let logTargets = [];
    let logData = [];
    const isCacheValid = skipFetch && allTargetsCache.length > 0 && cachedLogYear === year && cachedLogMonth === month;
    if (isCacheValid) {
        logTargets = allTargetsCache;
        logData = cachedLogData;
    } else {
        try {
            const [respTargets, respLogs] = await Promise.all([
                fetch('/api/targets'),
                fetch(`/api/observation_logs?year=${year}&month=${month}`)
            ]);
            
            const dataTargets = await respTargets.json();
            const dataLogs = await respLogs.json();
            
            if (dataTargets.success) {
                allTargetsCache = dataTargets.targets;
                logTargets = dataTargets.targets;
            }
            if (dataLogs.success) {
                logData = dataLogs.logs;
                cachedLogData = dataLogs.logs;
                cachedLogYear = year;
                cachedLogMonth = month;
            }
        } catch (e) {
            console.error("Log Grid Fetch error", e);
        }
    }
    
    // Quick lookup dict for logs by target_name + date
    logDict = {};
    const activeTargetNames = new Set();
    
    // Check missing suffixes and optionally add them for consistency here before UI loads it.
    logData.forEach(log => {
        let tName = (log.target_name || '').trim();
        if (!tName) return;

        // Ensure we assign telescope to log for proper sorting and UI display later without suffix
        log._inferred_telescope = log.telescope_use || 'SLT';
        
        // Strip suffix from name if it exists, so we don't display it
        tName = tName.replace(/-LOT$/, '').replace(/-SLT$/, '');
        log.target_name = tName; // mutate the log for view
        
        let teleKey = log._inferred_telescope || 'UNKNOWN';
        let uniqueTargetKey = `${tName}___${teleKey}`;
        logDict[`${uniqueTargetKey}_${log.obs_date}`] = log;

        // Include target if there's an actual trigger or observed log for it in this month
        if (log.is_triggered || log.is_observed) {
            activeTargetNames.add(uniqueTargetKey);
        }
    });

    // If there are no active target logs in this month at all, clear grid
    if (activeTargetNames.size === 0) {
        thead.innerHTML = '';
        tbody.innerHTML = '<tr><td style="padding:20px;text-align:center;color:#aaa;" colspan="100%">No observation records for this month.</td></tr>';
        return;
    }

    const targetByUnique = new Map();
    logTargets.forEach(t => {
        const baseName = (t.name || '').trim().replace(/-LOT$/, '').replace(/-SLT$/, '');
        let tele = (t.telescope || 'UNKNOWN').toUpperCase();
        
        if (tele !== 'LOT' && tele !== 'SLT') {
            tele = 'SLT'; // Fallback
        }
        
        const key = `${baseName}___${tele}`;
        if (!targetByUnique.has(key)) targetByUnique.set(key, t);
    });

    const monthlyTargets = [];
    activeTargetNames.forEach(uniqueKey => {
        let parts = uniqueKey.split('___');
        let bName = parts[0];
        let tScope = parts[1];
        
        if (targetByUnique.has(uniqueKey)) {
            let dbTarget = targetByUnique.get(uniqueKey);
            let t = Object.assign({}, dbTarget, { name: bName, telescope: tScope, _unique_key: uniqueKey });
            monthlyTargets.push(t);
        } else {
            // Check if there is ANY target with this baseName to copy some generic info if we want,
            // but it's fundamentally discontinued for this specific telescope.
            monthlyTargets.push({
                id: null,
                name: bName,
                telescope: tScope,
                is_active: false,
                is_discontinued: true,
                _unique_key: uniqueKey
            });
        }
    });

    // Filter SLT and LOT: only show targets that have at least one log in this month
    const calibrationNames = ['AUTOFLAT', 'BIAS', 'DARK'];

    // Separate active vs inactive DB targets (SLT/LOT), and discontinued (not in DB)
    let activeLotTargets = monthlyTargets.filter(t => t.telescope === 'LOT' && t.is_active !== false);
    let activeSltTargets = monthlyTargets.filter(t => t.telescope === 'SLT' && t.is_active !== false);
    let inactiveDbTargets = monthlyTargets.filter(t =>
        (t.telescope === 'LOT' || t.telescope === 'SLT') &&
        t.is_active === false &&
        !calibrationNames.includes((t.name || '').trim().toUpperCase())
    );
    let discontinuedTargets = monthlyTargets.filter(t =>
        t.telescope !== 'SLT' && t.telescope !== 'LOT' &&
        !calibrationNames.includes((t.name || '').trim().toUpperCase())
    );
    let calibrationTargets = monthlyTargets.filter(t => calibrationNames.includes((t.name || '').trim().toUpperCase()));

    // Keep legacy aliases for backward compat (used in urgent extraction below)
    let sltTargets = activeSltTargets;
    let lotTargets = activeLotTargets;

    const getPriorityRank = (priority) => {
        const p = (priority || '').toString().trim().toLowerCase();
        if (p.includes('urgent')) return 0;
        if (p.includes('high')) return 1;
        if (p.includes('normal')) return 2;
        return 9;
    };

    const sortByPriority = (targets) => {
        return targets.sort((a, b) => {
            const rankDiff = getPriorityRank(a.priority) - getPriorityRank(b.priority);
            if (rankDiff !== 0) return rankDiff;
            return (a.name || '').localeCompare((b.name || ''));
        });
    };

    sortByPriority(sltTargets);
    sortByPriority(lotTargets);
    sortByPriority(inactiveDbTargets);
    sortByPriority(discontinuedTargets);
    sortByPriority(calibrationTargets);

    // Extract urgent targets: active only (is_active !== false, not discontinued)
    const urgentTargets = monthlyTargets.filter(t => {
        const p = ((t.priority || '') + '').toString().trim().toLowerCase();
        return p.includes('urgent') && !t.is_discontinued && t.is_active !== false;
    });

    // Sort Urgent targets by LOT then SLT
    urgentTargets.sort((a, b) => {
        const tA = (a.telescope || '').toUpperCase();
        const tB = (b.telescope || '').toUpperCase();
        if (tA === 'LOT' && tB !== 'LOT') return -1;
        if (tA !== 'LOT' && tB === 'LOT') return 1;
        return 0; // if both are same, preserve existing order
    });

    // We must uniquely identify records when extracting them from overall target lists.
    // Use `_unique_key` if available.
    const urgentKeys = new Set(urgentTargets.map(t => t._unique_key));
    sltTargets = sltTargets.filter(t => !urgentKeys.has(t._unique_key));
    lotTargets = lotTargets.filter(t => !urgentKeys.has(t._unique_key));
    inactiveDbTargets = inactiveDbTargets.filter(t => !urgentKeys.has(t._unique_key));
    discontinuedTargets = discontinuedTargets.filter(t => !urgentKeys.has(t._unique_key));
    calibrationTargets = calibrationTargets.filter(t => !urgentKeys.has(t._unique_key));

    // Apply target name filter if provided
    const targetSearchEl = document.getElementById('log-target-search');
    const targetSearchVal = targetSearchEl ? targetSearchEl.value.trim().toLowerCase() : '';
    const nameMatchFn = t => !targetSearchVal || (t.name || '').toLowerCase().includes(targetSearchVal);
    const filteredUrgent = urgentTargets.filter(nameMatchFn);
    const filteredLOT = lotTargets.filter(nameMatchFn);
    const filteredSLT = sltTargets.filter(nameMatchFn);
    const filteredInactive = inactiveDbTargets.filter(nameMatchFn);
    const filteredDisc = discontinuedTargets.filter(nameMatchFn);
    const filteredCal = calibrationTargets.filter(nameMatchFn);

    // Build the grid
    let headHtml = '<tr><th>Target \\ Date</th>';
    dates.forEach(d => {
        headHtml += `<th data-col-date="${d.dateStr}">${d.day}</th>`;
    });
    headHtml += '</tr>';
    thead.innerHTML = headHtml;

    const today = new Date();
    const todayStr = `${today.getFullYear()}-${(today.getMonth()+1).toString().padStart(2,'0')}-${today.getDate().toString().padStart(2,'0')}`;

    tbody.innerHTML = '';
    
    const checkSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#4caf50" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    const crossSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f44336" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;

    const filterBadgeHTML = (filterName) => {
        if (!filterName) return '';
        const fStr = filterName.toLowerCase();
        let bg = 'linear-gradient(to bottom, rgba(255,255,255,0.2), rgba(255,255,255,0.05))';
        if      (fStr === 'up' || fStr === 'u') bg = 'linear-gradient(to bottom, #8e44ad, #b368d9)';
        else if (fStr === 'b')                  bg = 'linear-gradient(to bottom, #2196f3, #64b5f6)';
        else if (fStr === 'v')                  bg = 'linear-gradient(to bottom, #4caf50, #81c784)';
        else if (fStr === 'gp' || fStr === 'g') bg = 'linear-gradient(to bottom, #1785ec, #00a71f)';
        else if (fStr === 'rp' || fStr === 'r') bg = 'linear-gradient(to bottom, #ffb74d, #f53500)';
        else if (fStr === 'ip' || fStr === 'i') bg = 'linear-gradient(to bottom, #ef5350, #a52a2a)';
        else if (fStr === 'zp' || fStr === 'z') bg = 'linear-gradient(to bottom, #a52a2a, #580101)';
        return `<span style="background:${bg};padding:1px 5px;border-radius:3px;font-size:11px;color:#fff;font-family:monospace;border:1px solid rgba(0,0,0,0.15);text-shadow:0 1px 1px rgba(0,0,0,0.3);">${filterName}</span>`;
    };

    // Function to render rows
    const renderRows = (targets, prefix) => {
        targets.forEach(t => {
            const calibNoFilterNames = new Set(['DARK', 'BIAS']);
            const tr = document.createElement('tr');
            
            let displayName = t.name;
            const nameHtml = renderObjectNameLink(t.name, displayName);
            let displayTarget = nameHtml;

            let targetClass = 'pa-log-target-missing';
            let cornerColorStyle = '';
            
            if (t.is_discontinued) {
                targetClass = 'pa-log-target-missing';
                if (t.telescope === 'LOT') cornerColorStyle = '--corner-color: #2bd9ff;';
                else if (t.telescope === 'SLT') cornerColorStyle = '--corner-color: #ff9f43;';
            } else if (t.is_active === false) {
                targetClass = 'pa-log-target-off';
                if (t.telescope === 'LOT') cornerColorStyle = '--corner-color: #2bd9ff;';
                else if (t.telescope === 'SLT') cornerColorStyle = '--corner-color: #ff9f43;';
            } else if (t.telescope === 'LOT') {
                targetClass = 'pa-log-target-active';
            } else if (t.telescope === 'SLT') {
                targetClass = 'pa-log-target-slt';
            }

            // Target column
            tr.innerHTML = `<td class="${targetClass}" style="vertical-align: middle; ${cornerColorStyle}">${displayTarget}</td>`;

            // Dates cells
            let dateCells = '';
            dates.forEach(d => {
                const logKey = `${t._unique_key}_${d.dateStr}`;
                const log = logDict[logKey];
                
                if (log) {
                    const trigIcon = log.is_triggered ? checkSvg : crossSvg;
                    const obsIcon = log.is_observed ? checkSvg : crossSvg;
                    const user = log.user_name || '-';
                    const normalizedUser = normalizeLogUserName(user);

                    const renderFilterList = (filters) => {
                        const tNameUpper = ((t.name||'')+ '').toString().trim().toUpperCase();
                        if (!filters || filters.length === 0) return '';
                        const isCalib = calibNoFilterNames.has(tNameUpper);
                        const rows = filters.map(f => {
                            let badge = '';
                            if (isCalib) {
                                // Show a small grey single-letter badge: B for BIAS, D for DARK
                                const letter = (tNameUpper === 'BIAS') ? 'B' : (tNameUpper === 'DARK' ? 'D' : ((String(f.filter||'')||'').charAt(0) || '?').toUpperCase());
                                badge = `<span style="background:#9e9e9e;padding:1px 6px;border-radius:3px;font-size:11px;color:#fff;font-family:monospace;border:1px solid rgba(0,0,0,0.15);text-shadow:0 1px 1px rgba(0,0,0,0.3);">${letter}</span>`;
                            } else {
                                badge = filterBadgeHTML(f.filter || '?');
                            }
                            const expCount = [f.exp ? `${f.exp}s` : '', f.count ? `×${f.count}` : ''].filter(Boolean).join(' ');
                            return `<div style="display:flex;align-items:center;white-space:nowrap;font-size:0.82rem;">` +
                                   `<span style="display:inline-block;width:32px;text-align:center;">${badge}</span>` +
                                   `<span style="margin-left:6px;color:#aaa;font-family:monospace;">${expCount}</span>` +
                                   `</div>`;
                        }).join('');
                        return `<div style="display:flex;flex-direction:column;gap:3px;margin-top:3px;">${rows}</div>`;
                    };

                    const trigFilters = parseLogFilterRows(log.trigger_filter, log.trigger_exp, log.trigger_count);
                    const obsFiltersLog = parseLogFilterRows(log.observed_filter, log.observed_exp, log.observed_count);
                    // Determine if this target is a calibration (DARK/BIAS)
                    const tNameUpperLocal = ((t.name||'')+ '').toString().trim().toUpperCase();
                    const isCalibLocal = calibNoFilterNames.has(tNameUpperLocal);
                    // Sort filters for log display: calibration by exposure asc; otherwise by filter order then exp asc
                    sortLogFilters(trigFilters, isCalibLocal);
                    sortLogFilters(obsFiltersLog, isCalibLocal);
                    
                    const isFilterVisible = document.getElementById('log-show-filter-checkbox') ? document.getElementById('log-show-filter-checkbox').checked : true;
                    const trigDetail = isFilterVisible ? renderFilterList(trigFilters) : '';
                    const obsDetail  = isFilterVisible ? renderFilterList(obsFiltersLog) : '';

                    const priorityBadge = (() => {
                        const p = (log.priority || '').trim();
                        if (!p) return '<span style="color:#555;">—</span>';

                        let priorityKey = p;
                        if (p.includes('-')) {
                            priorityKey = p.split('-')[0].trim();
                        }

                        let color = '#aaa';
                        if (priorityKey.toLowerCase() === 'urgent') color = '#ef5350';
                        else if (priorityKey.toLowerCase() === 'high') color = '#ff9f43';
                        return `<span style="color:${color};font-weight:600;font-size:11px;">${p}</span>`;
                    })();
                    
                    const userDisplay = (() => {
                        let mb = membersMap[normalizedUser] || membersMap[user] || null;
                        if (!mb && typeof user === 'string') {
                            let match = user.match(/\(([^)]+)\)/);
                            if (match) mb = membersMap[match[1]];
                        }

                        let displayName = (normalizedUser || user || '').split(' ')[0]; // Default to first part

                        if (mb) {
                            let fullName = mb.name || mb.email.split('@')[0];
                            displayName = fullName.split(' ')[0]; // Extract just the first word

                            if (mb.picture) {
                                return `<img src="${mb.picture}" style="width:14px;height:14px;border-radius:50%;object-fit:cover;" title="${fullName}"> ${displayName}`;
                            } else {
                                // Fallback to an initial-based avatar or simple text if picture is null
                                const intl = (displayName || '?').charAt(0).toUpperCase();
                                return `<span style="display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:#4db8ff;color:#fff;font-size:9px;font-weight:bold;" title="${fullName}">${intl}</span> ${displayName}`;
                            }
                        }
                        return displayName;
                    })();
                    const editBtn = `<button onclick="openLogModalEdit(decodeURIComponent('${encodeURIComponent(t._unique_key || t.name || '')}'),'${d.dateStr}')" title="Edit" style="background:none;border:none;cursor:pointer;padding:0;margin-left:6px;color:#888;display:flex;align-items:center;" onmouseover="this.style.color='#4db8ff'" onmouseout="this.style.color='#888'"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>`;

                    dateCells += `
                        <td data-cell-date="${d.dateStr}" data-target-name="${(t.name || '').replace(/\"/g, '&quot;')}" style="${d.dateStr === todayStr ? 'background-color: rgba(46, 125, 50, 0.15);' : ''}">
                            <div class="pa-log-cell" style="width:100%;">
                                <div class="pa-log-cell-top" style="display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;">
                                    <div style="display:flex;align-items:center;gap:8px;min-width:0;">${userDisplay}</div>
                                    <div style="flex:0 0 auto;margin:0 8px;text-align:center;">${priorityBadge}</div>
                                    <div style="flex:0 0 auto;">${editBtn}</div>
                                </div>

                                <div class="pa-log-cell-status-row" style="display:flex;justify-content:space-between;gap:12px;margin-top:8px;width:100%;align-items:center;">
                                    <div style="width:48%;text-align:center;display:flex;align-items:center;justify-content:center;gap:6px;"><span style="font-size:12px;color:#fff;">Trigger</span><span style="margin-left:6px;">${trigIcon}</span></div>
                                    <div style="width:48%;text-align:center;display:flex;align-items:center;justify-content:center;gap:6px;"><span style="font-size:12px;color:#fff;">Observed</span><span style="margin-left:6px;">${obsIcon}</span></div>
                                </div>

                                <div class="pa-log-cell-filters" style="margin-top:8px;width:100%;display:flex;justify-content:space-between;gap:12px;">
                                    <div class="pa-log-trigger-filters" style="width:48%;display:flex;flex-direction:column;gap:4px;align-items:flex-start;">
                                        ${trigDetail || (isFilterVisible ? '<div style="font-size:11px;color:#555;">--</div>' : '')}
                                    </div>
                                    <div class="pa-log-observed-filters" style="width:48%;display:flex;flex-direction:column;gap:4px;align-items:flex-end;">
                                        ${obsDetail || (isFilterVisible ? '<div style="font-size:11px;color:#555;">--</div>' : '')}
                                    </div>
                                </div>
                            </div>
                        </td>
                    `;
                } else {
                    const editBtnEmpty = `<button onclick="openLogModalEdit(decodeURIComponent('${encodeURIComponent(t._unique_key || t.name || '')}'),'${d.dateStr}')" title="Add log" style="background:none;border:none;cursor:pointer;padding:0;margin-left:6px;color:#555;display:flex;align-items:center;" onmouseover="this.style.color='#4db8ff'" onmouseout="this.style.color='#555'"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>`;
                    dateCells += `
                        <td data-cell-date="${d.dateStr}" data-target-name="${(t.name || '').replace(/\"/g, '&quot;')}" style="${d.dateStr === todayStr ? 'background-color: rgba(46, 125, 50, 0.15);' : ''}">
                            <div class="pa-log-cell" style="width:100%;">
                                <div class="pa-log-cell-top" style="display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;color:#666;">
                                    <div style="display:flex;align-items:center;gap:8px;min-width:0;">- ${editBtnEmpty}</div>
                                    <div style="flex:0 0 auto;margin:0 8px;text-align:center;color:#666;"><span style="color:#777;">—</span></div>
                                    <div style="flex:0 0 auto;"></div>
                                </div>

                                <div class="pa-log-cell-status-row" style="display:flex;justify-content:space-between;gap:12px;margin-top:8px;width:100%;align-items:center;color:#666;">
                                    <div style="width:48%;text-align:center;display:flex;align-items:center;justify-content:center;gap:6px;"><span style="font-size:12px;color:#fff;">Trigger</span><span style="margin-left:6px;color:#fff;">-</span></div>
                                    <div style="width:48%;text-align:center;display:flex;align-items:center;justify-content:center;gap:6px;"><span style="font-size:12px;color:#fff;">Observed</span><span style="margin-left:6px;color:#fff;">-</span></div>
                                </div>
                            </div>
                        </td>
                    `;
                }
            });
            tr.innerHTML += dateCells;
            tbody.appendChild(tr);
        });
    };

    // Render order: Urgent -> LOT -> SLT -> Inactive DB targets -> Discontinued -> Calibration
    if (filteredUrgent && filteredUrgent.length) {
        renderRows(filteredUrgent, 'URGENT');
    }

    renderRows(filteredLOT, 'LOT');
    renderRows(filteredSLT, 'SLT');
    renderRows(filteredInactive, 'INACTIVE');
    renderRows(filteredDisc, 'DISCONTINUED');
    renderRows(filteredCal, 'CALIBRATION');

    if (initialLoad) {
        setTimeout(scrollToToday, 500); // Give DOM time to render
    }
}

function scrollToToday() {
    const today = new Date();
    const y = today.getFullYear();
    const m = (today.getMonth() + 1).toString().padStart(2, '0');
    const d = today.getDate().toString().padStart(2, '0');
    const todayStr = `${y}-${m}-${d}`;

    const container = document.getElementById('log-grid-container');
    const todayTh = document.querySelector(`th[data-col-date="${todayStr}"]`);

    if (todayTh && container) {
        // Scroll so today's cell is in view (center it roughly)
        const containerCenter = container.clientWidth / 2;
        const offset = todayTh.offsetLeft - containerCenter + (todayTh.clientWidth / 2);
        container.scrollTo({
            left: offset,
            behavior: 'smooth'
        });
    } else {
        // If today is not in the current selected month/year, switch to today's month/year
        const yearSelect = document.getElementById('log-year');
        const monthSelect = document.getElementById('log-month');
        if (yearSelect && monthSelect) {
            yearSelect.value = today.getFullYear();
            monthSelect.value = today.getMonth() + 1;
            renderLogGrid(true);
        }
    }
}

// ==========================================
// Log Modal (Add/Edit)
// ==========================================

function toggleLogFilterDisplay() {
    // Re-render the grid without fetching data from network again
    // For simplicity we just call renderLogGrid but without changing data.
    // It will fetch again right now, which is safe but you can optimize to cache if needed.
    renderLogGrid(false);
}

let membersCache = [];
let membersMap = {};

// Legacy log user names mapping to current member names.
// Add more pairs here when old records use outdated names.
const LOG_USER_NAME_MAP = {
    'Amar': 'Amar Aryan',
    'M H Lee': '李孟翰',
    'Aiswarya': 'Aiswarya Sankar Kachiprath',
    'Janet': 'Ting-Wan Chen',
    'Cheng-Han': '賴政翰',
    'Ze Ning': '王泽宁',
    "Auto Pipeline": "AutoPipeline",

};

function normalizeLogUserName(rawName) {
    const key = (rawName || '').toString().trim();
    if (!key) return '';
    return LOG_USER_NAME_MAP[key] || key;
}

function fetchMembers() {
    return fetch('/api/members')
        .then(res => res.json())
        .then(data => {
            if (data.success || data.status === 'success') {
                membersCache = data.members || data.data || [];
                const selectUser = document.getElementById('log-edit-user');
                if (selectUser) selectUser.innerHTML = '<option value="">-- Select Member --</option>';
                membersCache.forEach(m => {
                    const email = m.email || m.id;
                    const name = m.name || email;
                    membersMap[name] = m;
                    membersMap[email] = m;
                    if (selectUser) selectUser.innerHTML += `<option value="${name}">${name}</option>`;
                });
            }
            return data;
        })
        .catch(err => {
            console.error('Failed to fetch members', err);
            throw err;
        });
}

function addLogFilterRow(type, filterName) {
    const arr = type === 'trigger' ? logTriggerFilters : logObservedFilters;
    arr.push({ filter: filterName || '', exp: 300, count: 1 });
    renderLogFilterRows(type);
}

function removeLogFilterRow(type, index) {
    const arr = type === 'trigger' ? logTriggerFilters : logObservedFilters;
    arr.splice(index, 1);
    renderLogFilterRows(type);
}

function updateLogFilterRow(type, index, field, value) {
    const arr = type === 'trigger' ? logTriggerFilters : logObservedFilters;
    arr[index][field] = value;
}

function renderLogFilterRows(type) {
    const arr = type === 'trigger' ? logTriggerFilters : logObservedFilters;
    const container = document.getElementById(`log-${type}-filter-rows`);
    if (!container) return;
    // If editing a calibration target (DARK/BIAS), don't render filters
    const editTarget = (document.getElementById('log-edit-target-id') || {}).value || '';
    const editTargetUpper = (editTarget || '').toString().trim().toUpperCase();
    if (editTargetUpper === 'DARK' || editTargetUpper === 'BIAS') {
        container.innerHTML = '';
        return;
    }
    // Sort the log filter array into preferred order before rendering
    sortFiltersInPlace(arr);
    container.innerHTML = '';
    const predefinedFilters = ['up', 'gp', 'rp', 'ip', 'zp'];

    arr.forEach((row, idx) => {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'pa-filter-row';
        const isPredefined = predefinedFilters.includes(row.filter);
        const dropdownValue = isPredefined ? row.filter : (row.filter ? 'custom' : '');
        const customDisplay = (!isPredefined && row.filter) ? 'inline-block' : 'none';

        rowDiv.innerHTML =
            `<div class="pa-field filter-name" style="position: relative;">` +
                `<span class="pa-field-label">Filter</span>` +
                `<select onchange="if(this.value === 'custom') { this.nextElementSibling.style.display='inline-block'; this.nextElementSibling.focus(); } else { this.nextElementSibling.style.display='none'; updateLogFilterRow('${type}', ${idx}, 'filter', this.value); }">` +
                    `<option value="" ${!row.filter ? 'selected' : ''} disabled>Select...</option>` +
                    `<option value="up" ${row.filter === 'up' ? 'selected' : ''}>up</option>` +
                    `<option value="gp" ${row.filter === 'gp' ? 'selected' : ''}>gp</option>` +
                    `<option value="rp" ${row.filter === 'rp' ? 'selected' : ''}>rp</option>` +
                    `<option value="ip" ${row.filter === 'ip' ? 'selected' : ''}>ip</option>` +
                    `<option value="zp" ${row.filter === 'zp' ? 'selected' : ''}>zp</option>` +
                    `<option value="custom" ${dropdownValue === 'custom' ? 'selected' : ''}>Custom...</option>` +
                `</select>` +
                `<input type="text" value="${!isPredefined ? row.filter : ''}" placeholder="Custom Filter" style="display:${customDisplay}; margin-top: 5px; width: 100%;" onchange="updateLogFilterRow('${type}', ${idx}, 'filter', this.value)">` +
            `</div>` +
            `<div class="pa-field filter-exp">` +
                `<span class="pa-field-label">Exp (sec)</span>` +
                `<input type="number" value="${row.exp}" min="0" onchange="updateLogFilterRow('${type}', ${idx}, 'exp', parseInt(this.value)||0)">` +
            `</div>` +
            `<div class="pa-field filter-count">` +
                `<span class="pa-field-label">Count</span>` +
                `<input type="number" value="${row.count}" min="1" onchange="updateLogFilterRow('${type}', ${idx}, 'count', parseInt(this.value)||1)">` +
            `</div>` +
            `<div class="pa-filter-subtotal">= ${row.exp * row.count}s</div>` +
            `<button type="button" onclick="removeLogFilterRow('${type}', ${idx})" class="pa-btn-remove-filter">` +
                `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="8" y1="12" x2="16" y2="12"></line></svg>` +
            `</button>`;
        container.appendChild(rowDiv);
    });
}

function openLogModal() {
    const modal = document.getElementById('logModal');
    if (!modal) return;
    modal.style.display = 'flex';

    // Reset hidden date/target (filled in openLogModalEdit)
    document.getElementById('log-edit-date').value = '';
    document.getElementById('log-edit-target-id').value = '';
    const targetDisplay = document.getElementById('log-edit-target-display');
    if (targetDisplay) targetDisplay.textContent = '-';

    // Reset all fields
    document.getElementById('log-edit-user').value = '';
    document.getElementById('log-edit-priority').value = 'Normal';
    document.getElementById('log-edit-program').value = '';
    document.getElementById('log-edit-trigger-status').checked = false;
    document.getElementById('log-edit-obs-status').checked = false;
    logTriggerFilters = [];
    logObservedFilters = [];
    renderLogFilterRows('trigger');
    renderLogFilterRows('observed');
    toggleLogFields();
}

function closeLogModal() {
    const modal = document.getElementById('logModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function openLogModalEdit(uniqueTargetId, dateStr) {
    openLogModal();

    let parts = (uniqueTargetId || '').split('___');
    let rawTargetId = parts[0];
    let telescope = parts[1] || '';

    let isLot = telescope === 'LOT';
    let isSlt = telescope === 'SLT';

    document.getElementById('log-edit-target-id').value = rawTargetId;
    document.getElementById('log-edit-date').value = dateStr || '';
    document.getElementById('log-edit-telescope').value = telescope || '';
    
    const targetDisplay = document.getElementById('log-edit-target-display');
    if (targetDisplay) targetDisplay.textContent = rawTargetId || '-';

    // Pre-fill from existing log if exists
    const log = logDict[`${uniqueTargetId}_${dateStr}`];

    // Priority/Program - pre-fill from log or default to target's current values
    const prioritySelect = document.getElementById('log-edit-priority');
    const programInput = document.getElementById('log-edit-program');
    if (prioritySelect) {
        const baseTargetName = rawTargetId;
        const targetInfo = (allTargetsCache || []).find(t => {
            const tName = (t.name || '').trim();
            const tTele = (t.telescope || '').toUpperCase();
            // Try to match both name and telescope if possible
            return tName === baseTargetName && tTele === telescope;
        }) || (allTargetsCache || []).find(t => {
            const tName = (t.name || '').trim();
            return tName === baseTargetName;
        });

        const rawPriority = ((log && log.priority) ? log.priority : ((targetInfo && targetInfo.priority) || 'Normal')).toString().trim();

        let basePriority = rawPriority;
        let programText = '';
        if (rawPriority.includes('-')) {
            const partsPri = rawPriority.split('-');
            basePriority = (partsPri.shift() || 'Normal').trim();
            programText = partsPri.join('-').trim();
        } else if (targetInfo && targetInfo.program) {
            programText = targetInfo.program;
        }

        // If user creates a new log on a LOT row and no program exists yet, keep it, but they might need to set it.
        if (isLot && targetInfo?.program) {
             programText = targetInfo.program;
        }

        const pLower = basePriority.toLowerCase();
        if (pLower === 'urgent') prioritySelect.value = 'Urgent';
        else if (pLower === 'high') prioritySelect.value = 'High';
        else prioritySelect.value = 'Normal';

        if (programInput) programInput.value = programText;
    }

    if (!log) return;

    // User
    const selectUser = document.getElementById('log-edit-user');
    const mappedUser = normalizeLogUserName(log.user_name || '');
    selectUser.value = mappedUser || log.user_name || '';

    // Checkboxes
    document.getElementById('log-edit-trigger-status').checked = !!log.is_triggered;
    document.getElementById('log-edit-obs-status').checked    = !!log.is_observed;

    logTriggerFilters  = parseLogFilterRows(log.trigger_filter,  log.trigger_exp,  log.trigger_count);
    logObservedFilters = parseLogFilterRows(log.observed_filter, log.observed_exp, log.observed_count);
    renderLogFilterRows('trigger');
    renderLogFilterRows('observed');
    toggleLogFields();
}

function clearLogEditFields() {
    document.getElementById('log-edit-user').value = '';
    document.getElementById('log-edit-priority').value = 'Normal';
    document.getElementById('log-edit-program').value = '';
    document.getElementById('log-edit-trigger-status').checked = false;
    document.getElementById('log-edit-obs-status').checked = false;
    logTriggerFilters = [];
    logObservedFilters = [];
    renderLogFilterRows('trigger');
    renderLogFilterRows('observed');
    toggleLogFields();
}

function deleteObservationLog() {
    const target_name = document.getElementById('log-edit-target-id').value;
    const obs_date = document.getElementById('log-edit-date').value;
    const telescope_use = document.getElementById('log-edit-telescope').value || null;

    if (!target_name || !obs_date) {
        alert('Missing target or date for delete.');
        return;
    }

    if (!confirm('Delete this observation log?')) return;

    fetch('/api/observation_logs', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            action: 'delete',
            target_name: target_name,
            obs_date: obs_date,
            telescope_use: telescope_use
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeLogModal();
            renderLogGrid(false);
        } else {
            alert('Failed to delete log: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error deleting observation log:', error);
        alert('Server error deleting observation log.');
    });
}

function toggleLogFields() {
    const trig = document.getElementById('log-edit-trigger-status').checked;
    const obs  = document.getElementById('log-edit-obs-status').checked;
    const tFields = document.getElementById('trigger-fields');
    const oFields = document.getElementById('observed-fields');
    if (tFields) tFields.style.display = trig ? 'block' : 'none';
    if (oFields) oFields.style.display = obs  ? 'block' : 'none';
}

function saveObservationLog(event) {
    if (event) event.preventDefault();

    let target_name = document.getElementById('log-edit-target-id').value;
    const obs_date = document.getElementById('log-edit-date').value;
    const telescope_use = document.getElementById('log-edit-telescope').value || null;
    const user_id = document.getElementById('log-edit-user').value;
    const trigger_status = document.getElementById('log-edit-trigger-status').checked;
    const obs_status = document.getElementById('log-edit-obs-status').checked;

    if (!target_name || !obs_date || !user_id) {
        alert("Missing required fields: Date, Target, or User.");
        return;
    }

    const basePriority = (document.getElementById('log-edit-priority') || {}).value || '';
    const program = ((document.getElementById('log-edit-program') || {}).value || '').trim();
    const priority = basePriority ? (program ? `${basePriority} - ${program}` : basePriority) : null;

    const triggerPacked = packLogFilterColumns(logTriggerFilters);
    const observedPacked = packLogFilterColumns(logObservedFilters);

    const payload = {
        target_name:     target_name,
        obs_date:        obs_date,
        user_name:       user_id,
        is_triggered:    trigger_status,
        is_observed:     obs_status,
        trigger_filter:  triggerPacked.filter,
        trigger_exp:     triggerPacked.exp,
        trigger_count:   triggerPacked.count,
        observed_filter: observedPacked.filter,
        observed_exp:    observedPacked.exp,
        observed_count:  observedPacked.count,
        priority:        priority,
        telescope_use:   telescope_use
    };

    fetch('/api/observation_logs', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeLogModal();
            renderLogGrid(false);
        } else {
            alert('Failed to save log: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error saving observation log:', error);
        alert('Server error saving observation log.');
    });
}

// ==========================================
// Visibility Plot Modal
// ==========================================
let vpCurrentData = null;
const TARGET_COLORS = ['#fbbf24', '#ff7675', '#a78bfa', '#34d399', '#38bdf8', '#fb7185', '#818cf8', '#f87171', '#4ade80'];

function closeVisibilityPlot() {
    document.getElementById('visibilityPlotModal').style.display = 'none';
    Plotly.purge('vp-plot-area'); // Clear Plotly internal state completely to ensure re-render works next time
}

async function openVisibilityPlot() {
    const activeTelescope = document.getElementById('tab-SLT').classList.contains('active') ? 'SLT' : 'LOT';
    document.getElementById('vp-tab-name').textContent = activeTelescope;
    document.getElementById('visibilityPlotModal').style.display = 'flex';
    
    // Clear previous plot but keep loading text
    document.getElementById('vp-plot-area').innerHTML = '';
    document.getElementById('vp-target-list').innerHTML = '';
    const loadingEl = document.getElementById('vp-loading');
    if (loadingEl) loadingEl.style.display = 'block';

    // Wait for the targets to be fully loaded if not already
    let targetsForPlot = allTargetsCache.filter(t => t.telescope === activeTelescope);
    if (!allTargetsCache || allTargetsCache.length === 0) {
        await loadTargets();
        targetsForPlot = allTargetsCache.filter(t => t.telescope === activeTelescope);
    }
    if (!targetsForPlot || targetsForPlot.length === 0) {
        if (loadingEl) loadingEl.style.display = 'none';
        document.getElementById('vp-plot-area').innerHTML = '<div style="color:#aaa; text-align:center; padding-top: 50px;">No targets available to plot.</div>';
        return;
    }

    // Format targets for API
    const targets = targetsForPlot.filter(t => t.ra && t.dec).map(t => ({
        name: t.name,
        ra: t.ra,
        dec: t.dec
    }));

    if (targets.length === 0) {
        if (loadingEl) loadingEl.style.display = 'none';
        document.getElementById('vp-plot-area').innerHTML = '<div style="color:#aaa; text-align:center; padding-top: 50px;">No targets with valid RA/Dec.</div>';
        return;
    }

    // Determine Date (if hour < 12, use yesterday)
    const now = new Date();
    if (now.getHours() < 12) {
        now.setDate(now.getDate() - 1);
    }
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    const dateStr = `${yyyy}-${mm}-${dd}`;

    try {
        const resp = await fetch('/api/visibility_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                date: dateStr,
                location: "120:52:21 23:28:10 2862",
                timezone: "8",
                telescope: activeTelescope,
                targets: targets
            })
        });
        const data = await resp.json();
        if (data.success) {
            vpCurrentData = data;
            renderVisibilityPlot();
            renderVisibilityToggleList();
            if (loadingEl) loadingEl.style.display = 'none';
        } else {
            console.error('API Error:', data.error);
            if (loadingEl) loadingEl.style.display = 'none';
            document.getElementById('vp-plot-area').innerHTML = `<div style="color:#f44336; text-align:center; padding-top: 50px;">Error: ${data.error}</div>`;
        }
    } catch (e) {
        console.error('Network error:', e);
        if (loadingEl) loadingEl.style.display = 'none';
        document.getElementById('vp-plot-area').innerHTML = '<div style="color:#f44336; text-align:center; padding-top: 50px;">Network error.</div>';
    }
}

function renderVisibilityToggleList() {
    if (!vpCurrentData || !vpCurrentData.targets) return;
    
    // We also need the original target data to know if it's active
    const activeTelescope = document.getElementById('tab-SLT').classList.contains('active') ? 'SLT' : 'LOT';
    const targetsForPlot = allTargetsCache.filter(t => t.telescope === activeTelescope && t.ra && t.dec);

    const listEl = document.getElementById('vp-target-list');
    let html = '';
    
    vpCurrentData.targets.forEach((t, i) => {
        const color = TARGET_COLORS[i % TARGET_COLORS.length];
        
        // Find matching target in cache to get its ID and current active status
        const cacheTarget = targetsForPlot.find(ct => ct.name === t.name);
        const isActive = cacheTarget && cacheTarget.is_active !== false;
        
        html += `
            <label style="display: flex; align-items: center; justify-content: space-between; cursor: pointer; padding: 6px; background: rgba(255,255,255,0.03); border-radius: 4px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 12px; height: 12px; border-radius: 50%; background-color: ${color}; opacity: ${isActive ? '1' : '0.3'};" id="vp-color-${i}"></div>
                    <span style="color: ${isActive ? '#eee' : '#666'}; font-size: 13px;" id="vp-label-${i}">${t.name}</span>
                </div>
                <input type="checkbox" ${isActive ? 'checked' : ''} 
                       onchange="toggleVPTraceAndDB(${i}, this.checked, ${cacheTarget ? cacheTarget.id : 'null'})" 
                       style="accent-color: #4db8ff;">
            </label>
        `;
    });
    listEl.innerHTML = html;
}

async function toggleVPTraceAndDB(targetIndex, isChecked, targetId) {
    if (!vpCurrentData) return;
    // Trace order: Sun + Moon + Targets
    const baseTraces = 2; 
    const traceIdx = baseTraces + targetIndex;
    
    Plotly.restyle('vp-plot-area', {
        visible: isChecked ? true : 'legendonly'
    }, [traceIdx]);
    
    // Update visual style in the list
    const labelEl = document.getElementById(`vp-label-${targetIndex}`);
    const colorEl = document.getElementById(`vp-color-${targetIndex}`);
    if (labelEl) labelEl.style.color = isChecked ? '#eee' : '#666';
    if (colorEl) colorEl.style.opacity = isChecked ? '1' : '0.3';

    // Update DB with the new toggle state (wait for it to sync so normal list triggers updates)
    if (targetId) {
        try {
            await fetch('/api/targets/' + targetId + '/toggle', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isChecked })
            });
            // Also need to refresh the normal target list in the background
            loadTargets();
        } catch (e) {
            console.error('Failed to toggle target in DB:', e);
        }
    }
}

function renderVisibilityPlot() {
    const data = vpCurrentData;
    const times = data.times_utc;
    const tw = data.twilight_utc;

    const traces = [];
    const shapes = [];
    const annotations = [];

    // Twilight fills
    if (tw) {
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.sunset[0], x1: tw.civil[0], y0: 0, y1: 1, fillcolor: 'rgba(100,140,200,0.18)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.civil[0], x1: tw.nautical[0], y0: 0, y1: 1, fillcolor: 'rgba(40,60,120,0.28)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.nautical[0], x1: tw.astronomical[0], y0: 0, y1: 1, fillcolor: 'rgba(15,15,60,0.40)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.astronomical[0], x1: tw.astronomical[1], y0: 0, y1: 1, fillcolor: 'rgba(0,0,20,0.55)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.astronomical[1], x1: tw.nautical[1], y0: 0, y1: 1, fillcolor: 'rgba(15,15,60,0.40)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.nautical[1], x1: tw.civil[1], y0: 0, y1: 1, fillcolor: 'rgba(40,60,120,0.28)', line: { width: 0 }, layer: 'below' });
        shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: tw.civil[1], x1: tw.sunset[1], y0: 0, y1: 1, fillcolor: 'rgba(100,140,200,0.18)', line: { width: 0 }, layer: 'below' });

        annotations.push(
            { x: tw.sunset[0], y: 87, text: 'Sunset', showarrow: false, font: { size: 9, color: 'rgba(255,255,255,0.5)' }, textangle: -90, yref: 'y' },
            { x: tw.astronomical[0], y: 87, text: 'Ast.Twi.', showarrow: false, font: { size: 9, color: 'rgba(255,255,255,0.45)' }, textangle: -90, yref: 'y' },
            { x: tw.astronomical[1], y: 87, text: 'Ast.Twi.', showarrow: false, font: { size: 9, color: 'rgba(255,255,255,0.45)' }, textangle: -90, yref: 'y' },
            { x: tw.sunset[1], y: 87, text: 'Sunrise', showarrow: false, font: { size: 9, color: 'rgba(255,255,255,0.5)' }, textangle: -90, yref: 'y' }
        );
    }

    // 0: Sun
    traces.push({
        x: times, y: data.sun_alts,
        mode: 'lines', name: 'Sun',
        line: { color: '#FFD700', width: 1.5, dash: 'dash' },
        hovertemplate: 'Alt: %{y:.1f}°<extra></extra>',
        showlegend: false
    });

    // 1: Moon
    traces.push({
        x: times, y: data.moon_alts,
        mode: 'lines', name: `Moon (${data.moon_info.phase}%)`,
        line: { color: 'rgba(200,200,200,0.6)', width: 1.5, dash: 'dot' },
        hovertemplate: 'Alt: %{y:.1f}°<extra></extra>',
        showlegend: false
    });

    // Targets (starts from index 2)
    const activeTelescope = document.getElementById('tab-SLT').classList.contains('active') ? 'SLT' : 'LOT';
    const targetsForPlot = allTargetsCache.filter(t => t.telescope === activeTelescope && t.ra && t.dec);

    data.targets.forEach((t, i) => {
        const color = TARGET_COLORS[i % TARGET_COLORS.length];
        const cacheTarget = targetsForPlot.find(ct => ct.name === t.name);
        const isActive = cacheTarget && cacheTarget.is_active !== false;

        const hoverTexts = t.altitudes.map((alt) => {
            const am = alt > 0 ? (1 / Math.sin(alt * Math.PI / 180)).toFixed(2) : '--';
            return `Alt: ${alt.toFixed(1)}° | AM: ${am}`;
        });
        
        traces.push({
            x: times, y: t.altitudes,
            mode: 'lines', name: t.name,
            line: { color: color, width: 2.5 },
            text: hoverTexts,
            hovertemplate: '%{text}<extra></extra>',
            showlegend: false,
            visible: isActive ? true : 'legendonly'
        });
    });

    // Dummy trace — forces xaxis2 (top local) to render
    traces.push({
        x: [times[0]], y: [0],
        xaxis: 'x2',
        mode: 'markers',
        marker: { opacity: 0, size: 0 },
        showlegend: false,
        hoverinfo: 'skip'
    });

    // 30° guideline
    shapes.push({
        type: 'line', xref: 'x', yref: 'y',
        x0: times[0], x1: times[times.length - 1], y0: 30, y1: 30,
        line: { color: 'rgba(255,255,255,0.12)', width: 1, dash: 'dot' }
    });

    // Top X-Axis Local Time Setup
    const toUtcMs = s => new Date((s.includes('Z') || s.match(/[+-]\d{2}:\d{2}$/)) ? s : s.replace(' ', 'T') + 'Z').getTime();
    const firstMs = toUtcMs(times[0]);
    const lastMs  = toUtcMs(times[times.length - 1]);
    const offsetMs = data.timezone_offset * 3600000;
    const topTickVals  = [];
    const topTickTexts = [];
    let tickMs = (Math.floor(firstMs / 3600000) + 1) * 3600000;
    while (tickMs <= lastMs) {
        topTickVals.push(new Date(tickMs).toISOString().slice(0, 19));
        const lt = new Date(tickMs + offsetMs);
        topTickTexts.push(lt.getUTCHours().toString().padStart(2, '0') + ':' + lt.getUTCMinutes().toString().padStart(2, '0'));
        tickMs += 3600000;
    }

    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(12,12,30,0)',
        font: { family: 'Inter, sans-serif', color: 'rgba(255,255,255,0.85)' },
        margin: { t: 40, r: 40, b: 40, l: 40 },
        xaxis: {
            title: '',
            gridcolor: 'rgba(255,255,255,0.06)',
            tickfont: { size: 10 },
            showgrid: true,
            tickformat: '%H:%M',
            dtick: 3600000
        },
        xaxis2: {
            overlaying: 'x', side: 'top', matches: 'x',
            title: '',
            tickvals: topTickVals, ticktext: topTickTexts,
            tickfont: { size: 10, color: 'rgba(255,255,255,0.6)' },
            showgrid: false, zeroline: false
        },
        yaxis: {
            title: { text: 'Alt [°]', font: { size: 11 } },
            range: [0, 90],
            gridcolor: 'rgba(255,255,255,0.06)',
            tickfont: { size: 10 },
            dtick: 10, zeroline: true, zerolinecolor: 'rgba(255,100,100,0.3)'
        },
        shapes: shapes,
        annotations: annotations,
        hovermode: 'x unified',
        dragmode: 'zoom'
    };

    const config = { responsive: true, displayModeBar: false };
    Plotly.react('vp-plot-area', traces, layout, config);
}

