document.addEventListener('DOMContentLoaded', function() {
    // Initialize with one empty row if table is empty
    if (document.getElementById('targets-body').children.length === 0) {
        // Optional: Start empty or with one row. Let's start empty and show empty state.
        updateEmptyState();
    }
    
    // Set default date to today (YYYY/MM/DD)
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const today = `${year}/${month}/${day}`;
    
    const dateInput = document.getElementById('observation-date');
    if (dateInput) {
        dateInput.value = today;
    }
});

function formatCoordinate(coord) {
    if (coord === null || coord === undefined) return '';
    const coordStr = String(coord);
    
    // Check if it matches HH:MM:SS.sss or DD:MM:SS.sss format
    // We want to truncate/round to 3 decimal places
    
    // Simple regex to find the seconds part
    // Matches: ...:SS.sssss
    const match = coordStr.match(/(.*:)(\d+\.\d+)/);
    if (match) {
        const prefix = match[1];
        const seconds = parseFloat(match[2]);
        // Format to 3 decimal places
        const formattedSeconds = seconds.toFixed(3).padStart(6, '0'); // 00.000
        return prefix + formattedSeconds;
    }
    return coordStr;
}

function updateEmptyState() {
    const tbody = document.getElementById('targets-body');
    const emptyState = document.getElementById('empty-state');
    if (tbody.children.length === 0) {
        emptyState.style.display = 'block';
    } else {
        emptyState.style.display = 'none';
    }
}

function addTargetRow(data = null) {
    const tbody = document.getElementById('targets-body');
    const template = document.getElementById('row-template');
    const clone = template.content.cloneNode(true);
    const row = clone.querySelector('tr');

    if (data) {
        row.querySelector('.field-name').value = data['object name'] || '';
        row.querySelector('.field-ra').value = formatCoordinate(data['RA'] || '');
        row.querySelector('.field-dec').value = formatCoordinate(data['Dec'] || '');
        row.querySelector('.field-mag').value = data['Mag'] || '';
        row.querySelector('.field-priority').value = data['Priority'] || 'Normal';
        row.querySelector('.field-repeat').value = data['Repeat'] || '0';
        row.querySelector('.field-info').value = data['Info'] || '';
        
        const autoExp = data['Exp_By_Mag'] === 'True' || data['Exp_By_Mag'] === true;
        const autoCheckbox = row.querySelector('.field-auto');
        autoCheckbox.checked = autoExp;
        
        // Initialize exposure settings
        toggleAutoExposure(autoCheckbox);
        
        if (!autoExp) {
            // If manual, populate exposure rows
            const filters = (data['Filter'] || 'rp').split(',');
            const exps = (data['Exp_Time'] || '300').split(',');
            const counts = (data['Num_of_Frame'] || '3').split(',');
            
            // Clear default empty row if any (though toggleAutoExposure might handle visibility)
            const exposureList = row.querySelector('.exposure-list');
            exposureList.innerHTML = '';
            
            const maxLen = Math.max(filters.length, exps.length, counts.length);
            for (let i = 0; i < maxLen; i++) {
                addExposureRow(row.querySelector('.add-exposure-btn'), {
                    filter: filters[i] || filters[0],
                    exp: exps[i] || exps[0],
                    count: counts[i] || counts[0]
                });
            }
        }
    } else {
        // New empty row
        const autoCheckbox = row.querySelector('.field-auto');
        toggleAutoExposure(autoCheckbox);
    }

    tbody.appendChild(row);
    updateEmptyState();
}

function toggleAutoExposure(checkbox) {
    const cell = checkbox.closest('.exposure-settings-cell');
    const manualDiv = cell.querySelector('.manual-exposures');
    const autoInfo = cell.querySelector('.auto-info');
    
    if (checkbox.checked) {
        manualDiv.style.display = 'none';
        autoInfo.style.display = 'block';
    } else {
        manualDiv.style.display = 'block';
        autoInfo.style.display = 'none';
        
        // If no rows, add one default
        const list = manualDiv.querySelector('.exposure-list');
        if (list.children.length === 0) {
            addExposureRow(manualDiv.querySelector('.add-exposure-btn'));
        }
    }
}

function addExposureRow(btn, data = null) {
    const list = btn.previousElementSibling; // .exposure-list
    const template = document.getElementById('exposure-row-template');
    const clone = template.content.cloneNode(true);
    const row = clone.querySelector('.exposure-row');
    
    if (data) {
        row.querySelector('.field-filter').value = data.filter.trim();
        row.querySelector('.field-exp').value = data.exp.trim();
        row.querySelector('.field-count').value = data.count.trim();
    }
    
    list.appendChild(row);
}

function removeExposureRow(btn) {
    const row = btn.closest('.exposure-row');
    const list = row.parentElement;
    if (list.children.length > 1) {
        row.remove();
    } else {
        alert("At least one exposure setting is required for manual mode.");
    }
}

function removeRow(btn) {
    const row = btn.closest('tr');
    row.remove();
    updateEmptyState();
}

function clearAllTargets() {
    if (confirm('Are you sure you want to clear all targets?')) {
        document.getElementById('targets-body').innerHTML = '';
        updateEmptyState();
    }
}

async function fetchFollowUpTargets() {
    const btn = document.querySelector('button[onclick="fetchFollowUpTargets()"]');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<svg class="icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg> Fetching...';
    btn.disabled = true;

    try {
        const response = await fetch('/astronomy_tools/get_followup_targets');
        const result = await response.json();
        
        if (result.success) {
            const tbody = document.getElementById('targets-body');
            if (tbody.children.length > 0) {
                if (confirm('Clear existing targets before adding fetched ones?')) {
                    tbody.innerHTML = '';
                }
            }

            const targets = result.data.targets;
            if (targets.length === 0) {
                alert('No follow-up targets found.');
            } else {
                targets.forEach(target => addTargetRow(target));
            }
            
            if (result.data.settings) {
                if (result.data.settings.IS_LOT) {
                    document.getElementById('telescope-select').value = result.data.settings.IS_LOT === 'True' ? 'LOT' : 'SLT';
                }
            }
        } else {
            alert('Error fetching targets: ' + result.error);
        }
    } catch (error) {
        alert('Error fetching targets: ' + error);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function collectData() {
    const rows = document.querySelectorAll('.target-row');
    const targets = [];
    
    rows.forEach(row => {
        const autoExp = row.querySelector('.field-auto').checked;
        let filter = "rp";
        let exp = "300";
        let count = "3";
        
        if (!autoExp) {
            const expRows = row.querySelectorAll('.exposure-row');
            const filters = [];
            const exps = [];
            const counts = [];
            
            expRows.forEach(expRow => {
                filters.push(expRow.querySelector('.field-filter').value);
                exps.push(expRow.querySelector('.field-exp').value);
                counts.push(expRow.querySelector('.field-count').value);
            });
            
            filter = filters.join(',');
            exp = exps.join(',');
            count = counts.join(',');
        }

        targets.push({
            "object name": row.querySelector('.field-name').value,
            "RA": row.querySelector('.field-ra').value,
            "Dec": row.querySelector('.field-dec').value,
            "Mag": row.querySelector('.field-mag').value,
            "Priority": row.querySelector('.field-priority').value,
            "Filter": filter,
            "Exp_Time": exp,
            "Num_of_Frame": count,
            "Repeat": parseInt(row.querySelector('.field-repeat').value) || 0,
            "Info": row.querySelector('.field-info').value,
            "Exp_By_Mag": autoExp ? "True" : "False"
        });
    });

    const settings = {
        "IS_LOT": document.getElementById('telescope-select').value === 'LOT' ? "True" : "False",
        "send_to_control_room": document.getElementById('send-control').checked ? "True" : "False"
    };

    return { settings, targets };
}

function formatForPlot(value, isRA) {
    if (!value) return value;
    
    // If it looks like decimal (no colons, no spaces, no letters)
    if (/^-?\d+(\.\d+)?$/.test(value)) {
        let val = parseFloat(value);
        if (isRA) {
            // Convert RA from degrees to hours
            val = val / 15;
        }
        
        const sign = val < 0 ? '-' : '';
        val = Math.abs(val);
        
        const h = Math.floor(val);
        const m = Math.floor((val - h) * 60);
        const s = ((val - h - m/60) * 3600).toFixed(2);
        
        return `${sign}${h}:${m}:${s}`;
    }
    
    // If it has spaces, replace with colons to be safe
    if (value.includes(' ')) {
        return value.trim().replace(/\s+/g, ':');
    }
    
    return value;
}

async function generateScript() {
    const data = collectData();
    
    if (data.targets.length === 0) {
        alert('Please add at least one target.');
        return;
    }

    const btn = document.querySelector('button[onclick="generateScript()"]');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<svg class="icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg> Generating...';
    btn.disabled = true;

    try {
        // 1. Generate Script
        const scriptResponse = await fetch('/astronomy_tools/generate_script', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        const scriptResult = await scriptResponse.json();
        
        if (scriptResult.success) {
            document.getElementById('script-output').value = scriptResult.script;
            
            // 2. Generate Plot (if date is selected)
            const date = document.getElementById('observation-date').value;
            if (date) {
                const plotPayload = {
                    date: date,
                    telescope: document.getElementById('telescope-select').value,
                    location: "120.873611 23.468611 2862", // Lulin Observatory
                    timezone: "8",
                    targets: data.targets.map(t => ({
                        object_name: t["object name"],
                        ra: formatForPlot(t["RA"], true),
                        dec: formatForPlot(t["Dec"], false)
                    }))
                };

                try {
                    const plotResponse = await fetch('/generate_plot', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(plotPayload)
                    });
                    const plotResult = await plotResponse.json();
                    
                    if (plotResult.success) {
                        const img = document.getElementById('visibility-plot');
                        img.src = plotResult.plot_url + '?t=' + new Date().getTime();
                        document.getElementById('plot-container').style.display = 'block';
                    }
                } catch (plotError) {
                    console.error("Plot generation failed:", plotError);
                    // Don't block script display if plot fails
                }
            }

            // Scroll to output
            document.querySelector('.output-panel').scrollIntoView({ behavior: 'smooth' });
        } else {
            alert('Error generating script: ' + scriptResult.error);
        }
    } catch (error) {
        alert('Error generating script: ' + error);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function copyToClipboard() {
    const copyText = document.getElementById("script-output");
    copyText.select();
    copyText.setSelectionRange(0, 99999); /* For mobile devices */
    navigator.clipboard.writeText(copyText.value).then(() => {
        const btn = document.querySelector('.btn-copy');
        const originalText = btn.innerText;
        btn.innerText = 'Copied!';
        setTimeout(() => btn.innerText = originalText, 2000);
    });
}

function fetchCustomTargets() {
    const btn = document.querySelector('button[onclick="fetchCustomTargets()"]');
    const originalText = btn.innerHTML;
    btn.innerHTML = 'Fetching...';
    btn.disabled = true;

    fetch('/api/custom_targets')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (data.targets.length === 0) {
                    alert('No custom targets found. Please add some in the Custom Targets page.');
                } else {
                    data.targets.forEach(target => {
                        addTargetRow({
                            'object name': target.name,
                            'RA': target.ra,
                            'Dec': target.dec,
                            'Mag': target.mag,
                            'Priority': target.priority,
                            'Info': target.note,
                            'Exp_By_Mag': target.is_auto_exposure,
                            'Filter': target.filters,
                            'Exp_Time': target.exposures,
                            'Num_of_Frame': target.counts
                        });
                    });
                }
            } else {
                alert('Error fetching custom targets: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error fetching custom targets');
        })
        .finally(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        });
}

