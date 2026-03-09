let obsFilters = [];
let logTriggerFilters = [];
let logObservedFilters = [];
let logDict = {};
let searchTimeout = null;

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

function switchTab(tabId) {
    const tabs = ['SLT', 'LOT'];
    tabs.forEach(t => {
        document.getElementById('content-' + t).style.display = (t === tabId) ? 'block' : 'none';
        const btn = document.getElementById('tab-' + t);
        if (t === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
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

                    const raDeg = obj.ra != null ? parseFloat(obj.ra).toFixed(5) : '';
                    const decDeg = obj.dec != null ? parseFloat(obj.dec).toFixed(5) : '';
                    const magStr = obj.mag != null ? parseFloat(obj.mag).toFixed(1) : '';
                    const typeStr = obj.type ? obj.type : 'AT';

                    item.innerHTML = '<div>' +
                        '<span class="pa-search-item-name">' + obj.prefix + obj.name + '</span>' +
                        '<span class="pa-search-item-type">' + typeStr + '</span>' +
                        (magStr ? '<span class="pa-search-item-mag">mag ' + magStr + '</span>' : '') +
                        '</div>' +
                        '<div class="pa-search-item-coord">' + raDeg + ', ' + decDeg + '</div>';

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

// ===================== Modal =====================
function openTargetModal(telescope) {
    document.getElementById('targetModal').style.display = 'flex'; // Changed to flex for centering
    document.getElementById('obs-telescope').value = telescope;
    document.getElementById('add-target-form').reset();
    obsFilters = [];
    toggleTelescopeUI(telescope);
    renderFilterRows();
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
    container.innerHTML = '';

    let totalSec = 0;

    obsFilters.forEach(function(row, idx) {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'pa-filter-row';

        let rowHtml = '<div class="pa-field filter-name">' +
            '<span class="pa-field-label">Filter</span>' +
            '<input type="text" value="' + row.filter + '" onchange="updateFilterRow(' + idx + ', \'filter\', this.value)">' +
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
    const name = document.getElementById('obs-name').value;
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
async function loadTargets() {
    try {
        const response = await fetch('/api/targets');
        const data = await response.json();
        if (data.success) {
            allTargetsCache = data.targets;
            renderTable('SLT', data.targets.filter(function(t) { return t.telescope === 'SLT'; }));
            renderTable('LOT', data.targets.filter(function(t) { return t.telescope === 'LOT'; }));
        }
    } catch (e) {
        console.error('Error loading targets:', e);
    }
}

function renderTable(telescope, targets) {
    const tableBody = document.getElementById(telescope.toLowerCase() + '-list');
    if (!tableBody) return;

    tableBody.innerHTML = '';

    if (targets.length === 0) {
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = '<td colspan="7" class="pa-empty-row">No ' + telescope + ' targets added yet.</td>';
        tableBody.appendChild(emptyRow);
        return;
    }

    targets.forEach(function(t) {
        let priorityColor = '#fff';
        if (t.priority === 'Urgent') priorityColor = '#ff4d4d';
        else if (t.priority === 'High') priorityColor = '#ffa64d';

        let filterExpHTML = '';

        if (!t.filters || t.filters.length === 0) {
            filterExpHTML = '-';
        } else {
            filterExpHTML = '<div class="pa-filter-stack" style="display: flex; flex-direction: column; gap: 4px;">';
            t.filters.forEach(function(f) {
                if (!f || !f.filter) return;
                
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

        const tr = document.createElement('tr');
        tr.innerHTML = '<td class="pa-td-name">' + t.name + ' ' + programBadge + ' <br>' + magDisplay + '</td>' +
            '<td class="pa-td-coord">' + (t.ra || '') + ' <br> ' + (t.dec || '') + '</td>' +
            '<td class="pa-td-priority" style="color:' + priorityColor + ';">' + t.priority + repeatInfo + '</td>' +
            '<td class="pa-td-filter-exp">' + filterExpHTML + '</td>' +
            '<td class="pa-td-note">' + (t.plan || '-') + '</td>' +
            '<td class="pa-td-note-gl">' + (t.note_gl || '-') + '</td>' +
            '<td class="pa-td-actions">' +
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

// ===================== Observation Log =====================

function initObservationLog() {
    const yearSelect = document.getElementById('log-year');
    const monthSelect = document.getElementById('log-month');
    
    if (!yearSelect || !monthSelect) return;

    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;

    // Populate years (e.g., 2024 to 2030)
    for (let y = currentYear - 2; y <= currentYear + 3; y++) {
        let opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        if (y === currentYear) opt.selected = true;
        yearSelect.appendChild(opt);
    }

    // Populate months
    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    for (let m = 1; m <= 12; m++) {
        let opt = document.createElement('option');
        opt.value = m;
        opt.textContent = monthNames[m-1];
        if (m === currentMonth) opt.selected = true;
        monthSelect.appendChild(opt);
    }

    renderLogGrid(true); // pass true to indicate initial load to scroll to today
}

async function renderLogGrid(initialLoad = false) {
    const yearSelect = document.getElementById('log-year');
    const monthSelect = document.getElementById('log-month');
    const thead = document.getElementById('log-grid-head');
    const tbody = document.getElementById('log-grid-body');

    if (!yearSelect || !monthSelect || !thead || !tbody) return;

    const year = parseInt(yearSelect.value);
    const month = parseInt(monthSelect.value);

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
        }
    } catch (e) {
        console.error("Log Grid Fetch error", e);
    }
    
    // Quick lookup dict for logs by target_id + date
    logDict = {};
    const activeTargetIds = new Set();
    logData.forEach(log => {
        logDict[`${log.target_id}_${log.obs_date}`] = log;
        // Include target if there's ANY log entry for it in this month (not just triggered ones)
        activeTargetIds.add(log.target_id);
    });

    // Filter SLT and LOT: only show targets that have at least one log in this month
    let sltTargets = logTargets.filter(t => t.telescope === 'SLT' && activeTargetIds.has(t.id));
    let lotTargets = logTargets.filter(t => t.telescope === 'LOT' && activeTargetIds.has(t.id));

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
        else if (fStr === 'gp' || fStr === 'g') bg = 'linear-gradient(to bottom, #1785ec, #00a71f)';
        else if (fStr === 'rp' || fStr === 'r') bg = 'linear-gradient(to bottom, #ffb74d, #f53500)';
        else if (fStr === 'ip' || fStr === 'i') bg = 'linear-gradient(to bottom, #ef5350, #a52a2a)';
        else if (fStr === 'zp' || fStr === 'z') bg = 'linear-gradient(to bottom, #a52a2a, #580101)';
        return `<span style="background:${bg};padding:1px 5px;border-radius:3px;font-size:11px;color:#fff;font-family:monospace;border:1px solid rgba(0,0,0,0.15);text-shadow:0 1px 1px rgba(0,0,0,0.3);">${filterName}</span>`;
    };

    // Function to render rows
    const renderRows = (targets, prefix) => {
        targets.forEach(t => {
            const tr = document.createElement('tr');
            
            let displayName = t.name;
            let displayTarget = '';
            if (prefix === 'LOT') {
                let prog = t.program ? `${t.program}` : '';
                displayTarget = `LOT ${prog} - ${displayName}`;
            } else {
                displayTarget = `SLT - ${displayName}`;
            }

            // Target column
            tr.innerHTML = `<td class="pa-log-target-active">${displayTarget}</td>`;

            // Dates cells
            let dateCells = '';
            dates.forEach(d => {
                const logKey = `${t.id}_${d.dateStr}`;
                const log = logDict[logKey];
                
                if (log) {
                    const trigIcon = log.is_triggered ? checkSvg : crossSvg;
                    const obsIcon = log.is_observed ? checkSvg : crossSvg;
                    const user = log.user_name || '-';

                    // Parse filter list (JSON array or legacy single value)
                    const parseLogFilters = (filterVal, exp, count) => {
                        if (!filterVal) return [];
                        try {
                            const parsed = JSON.parse(filterVal);
                            if (Array.isArray(parsed)) return parsed;
                        } catch(e) {}
                        return [{ filter: filterVal, exp: exp, count: count }];
                    };
                    const renderFilterList = (filters) => {
                        if (!filters || filters.length === 0) return '';
                        const rows = filters.map(f => {
                            const badge = filterBadgeHTML(f.filter || '?');
                            const expCount = [f.exp ? `${f.exp}s` : '', f.count ? `\u00d7${f.count}` : ''].filter(Boolean).join(' ');
                            return `<div style="display:flex;align-items:center;white-space:nowrap;font-size:0.82rem;">` +
                                   `<span style="display:inline-block;width:32px;text-align:center;">${badge}</span>` +
                                   `<span style="margin-left:6px;color:#aaa;font-family:monospace;">${expCount}</span>` +
                                   `</div>`;
                        }).join('');
                        return `<div style="display:flex;flex-direction:column;gap:3px;margin-top:3px;">${rows}</div>`;
                    };

                    const trigFilters = parseLogFilters(log.trigger_filter, log.trigger_exp, log.trigger_count);
                    const obsFiltersLog = parseLogFilters(log.observed_filter, log.observed_exp, log.observed_count);
                    const trigDetail = renderFilterList(trigFilters);
                    const obsDetail  = renderFilterList(obsFiltersLog);
                    
                    const userDisplay = (() => {
                        let mb = membersMap[user] || null;
                        if (!mb && typeof user === 'string') {
                            let match = user.match(/\(([^)]+)\)/);
                            if (match) mb = membersMap[match[1]];
                        }
                        if (mb) {
                            return `<img src="${mb.picture || '/static/photo/default_avatar.png'}" style="width:14px;height:14px;border-radius:50%;object-fit:cover;"> ${mb.name || mb.email.split('@')[0]}`;
                        }
                        return user;
                    })();
                    const editBtn = `<button onclick="openLogModalEdit(${t.id},'${d.dateStr}')" title="Edit" style="background:none;border:none;cursor:pointer;padding:0;margin-left:auto;color:#888;display:flex;align-items:center;" onmouseover="this.style.color='#4db8ff'" onmouseout="this.style.color='#888'"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>`;

                    dateCells += `
                        <td data-cell-date="${d.dateStr}" data-target-id="${t.id}" style="${d.dateStr === todayStr ? 'background-color: rgba(46, 125, 50, 0.15);' : ''}">
                            <div class="pa-log-cell">
                                <div class="pa-log-cell-user" style="display:flex; align-items:center; gap:4px; font-size:12px;">
                                    ${userDisplay}${editBtn}
                                </div>
                                <div class="pa-log-cell-status" style="font-size:12px; margin-top:4px;">
                                    <div style="display:flex;align-items:center;gap:4px;">Trigger ${trigIcon}</div>
                                    ${trigDetail || '<div style="font-size:11px;color:#555;padding-left:4px;">--</div>'}
                                </div>
                                <div class="pa-log-cell-status" style="font-size:12px; margin-top:4px;">
                                    <div style="display:flex;align-items:center;gap:4px;">Observed ${obsIcon}</div>
                                    ${obsDetail || '<div style="font-size:11px;color:#555;padding-left:4px;">--</div>'}
                                </div>
                            </div>
                        </td>
                    `;
                } else {
                    const editBtnEmpty = `<button onclick="openLogModalEdit(${t.id},'${d.dateStr}')" title="Add log" style="background:none;border:none;cursor:pointer;padding:0;margin-left:auto;color:#555;display:flex;align-items:center;" onmouseover="this.style.color='#4db8ff'" onmouseout="this.style.color='#555'"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg></button>`;
                    dateCells += `
                        <td data-cell-date="${d.dateStr}" data-target-id="${t.id}" style="${d.dateStr === todayStr ? 'background-color: rgba(46, 125, 50, 0.15);' : ''}">
                            <div class="pa-log-cell">
                                <div class="pa-log-cell-user" style="display:flex;align-items:center;color:#666;">-${editBtnEmpty}</div>
                                <div class="pa-log-cell-status" style="color: #666;">Trigger -</div>
                                <div class="pa-log-cell-status" style="color: #666;">Observed -</div>
                            </div>
                        </td>
                    `;
                }
            });
            tr.innerHTML += dateCells;
            tbody.appendChild(tr);
        });
    };

    renderRows(sltTargets, 'SLT');
    renderRows(lotTargets, 'LOT');

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

let membersCache = [];
let membersMap = {};

function fetchMembers() {
    fetch('/api/members')
        .then(res => res.json())
        .then(data => {
            if (data.success || data.status === 'success') {
                membersCache = data.members || data.data;
                const selectUser = document.getElementById('log-edit-user');
                selectUser.innerHTML = '<option value="">-- Select Member --</option>';
                membersCache.forEach(m => {
                    const email = m.email || m.id;
                    const name = m.name || email;
                    membersMap[name] = m;
                    membersMap[email] = m;
                    selectUser.innerHTML += `<option value="${name}">${name}</option>`;
                });
            }
        });
}

// Fetch members once on page load
fetchMembers();

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
    container.innerHTML = '';
    arr.forEach((row, idx) => {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'pa-filter-row';
        rowDiv.innerHTML =
            `<div class="pa-field filter-name">` +
                `<span class="pa-field-label">Filter</span>` +
                `<input type="text" value="${row.filter}" onchange="updateLogFilterRow('${type}', ${idx}, 'filter', this.value)">` +
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

    // Populate Target options
    const selectTarget = document.getElementById('log-edit-target-id');
    selectTarget.innerHTML = '<option value="">-- Select Target --</option>';
    if (typeof allTargetsCache !== 'undefined') {
        allTargetsCache.forEach(t => {
            selectTarget.innerHTML += `<option value="${t.id}">${t.name} (${t.telescope})</option>`;
        });
    }

    // Default Date to today
    const tzoffset = (new Date()).getTimezoneOffset() * 60000;
    const localISOTime = (new Date(Date.now() - tzoffset)).toISOString().slice(0, 10);
    document.getElementById('log-edit-date').value = localISOTime;

    // Reset all fields
    document.getElementById('log-edit-user').value = '';
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

function openLogModalEdit(targetId, dateStr) {
    openLogModal();

    // Pre-fill target
    const selectTarget = document.getElementById('log-edit-target-id');
    selectTarget.value = targetId;

    // Pre-fill date
    document.getElementById('log-edit-date').value = dateStr;

    // Pre-fill from existing log if exists
    const log = logDict[`${targetId}_${dateStr}`];
    if (!log) return;

    // User
    const selectUser = document.getElementById('log-edit-user');
    selectUser.value = log.user_name || '';

    // Checkboxes
    document.getElementById('log-edit-trigger-status').checked = !!log.is_triggered;
    document.getElementById('log-edit-obs-status').checked    = !!log.is_observed;

    // Parse and fill filter rows
    const parseLogFiltersEdit = (filterVal, exp, count) => {
        if (!filterVal) return [];
        try {
            const parsed = JSON.parse(filterVal);
            if (Array.isArray(parsed)) return parsed;
        } catch(e) {}
        return [{ filter: filterVal, exp: exp || 0, count: count || 1 }];
    };

    logTriggerFilters  = parseLogFiltersEdit(log.trigger_filter,  log.trigger_exp,  log.trigger_count);
    logObservedFilters = parseLogFiltersEdit(log.observed_filter, log.observed_exp, log.observed_count);
    renderLogFilterRows('trigger');
    renderLogFilterRows('observed');
    toggleLogFields();
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

    const target_id = document.getElementById('log-edit-target-id').value;
    const obs_date = document.getElementById('log-edit-date').value;
    const user_id = document.getElementById('log-edit-user').value;
    const trigger_status = document.getElementById('log-edit-trigger-status').checked;
    const obs_status = document.getElementById('log-edit-obs-status').checked;

    if (!target_id || !obs_date || !user_id) {
        alert("Please select Date, Target, and User.");
        return;
    }

    const payload = {
        target_id:       parseInt(target_id),
        obs_date:        obs_date,
        user_name:       user_id,
        is_triggered:    trigger_status,
        is_observed:     obs_status,
        trigger_filter:  logTriggerFilters.length > 0 ? JSON.stringify(logTriggerFilters) : null,
        trigger_exp:     null,
        trigger_count:   null,
        observed_filter: logObservedFilters.length > 0 ? JSON.stringify(logObservedFilters) : null,
        observed_exp:    null,
        observed_count:  null
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
            renderLogGrid(false); // Reload logs
            setTimeout(() => { location.reload(); }, 500);
        } else {
            alert('Failed to save log: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error saving observation log:', error);
        alert('Server error saving observation log.');
    });
}

// Admin Permissions Management for Private Area
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('active-permissions')) {
        loadPrivateAreaPermissions();
    }
});

function loadPrivateAreaPermissions() {
    fetch('/api/object/private_area/permissions')
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const container = document.getElementById('active-permissions');
                // Keep the locked GREATLab group
                container.innerHTML = `<div style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); padding: 5px 12px; border-radius: 15px; font-size: 0.85rem; color: #aaa; display: flex; align-items: center; gap: 5px;">
                    <span>greatlab</span>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                </div>`;
                
                data.permissions.forEach(perm => {
                    const groupName = perm.group_name || perm.name || perm;
                    if (groupName === 'greatlab') return; // Skip if greatlab was somehow in DB
                    
                    const badge = document.createElement('div');
                    badge.style.cssText = 'background: rgba(77,184,255,0.15); border: 1px solid rgba(77,184,255,0.3); padding: 5px 12px; border-radius: 15px; font-size: 0.85rem; color: #4db8ff; display: flex; align-items: center; gap: 8px;';
                    badge.innerHTML = `
                        <span>${groupName}</span>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="cursor: pointer; opacity: 0.7;" onclick="removePrivateAreaPermission('${groupName}')" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    `;
                    container.appendChild(badge);
                });
            }
        });
}

function addPrivateAreaPermission() {
    const groupName = document.getElementById('new-permission-group').value;
    if (!groupName) return;
    
    fetch('/api/object/private_area/permissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_name: groupName })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            document.getElementById('new-permission-group').value = '';
            loadPrivateAreaPermissions();
        } else {
            alert(data.error || 'Failed to add permission');
        }
    });
}

function removePrivateAreaPermission(groupName) {
    if (!confirm(`Are you sure you want to remove access for ${groupName}?`)) return;
    
    fetch('/api/object/private_area/permissions', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_name: groupName })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            loadPrivateAreaPermissions();
        } else {
            alert(data.error || 'Failed to remove permission');
        }
    });
}


