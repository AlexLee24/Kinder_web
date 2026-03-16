// SVG icon strings used in result headings
const _SVG_SCOPE    = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:text-bottom"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`;
const _SVG_STAR     = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:text-bottom"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
const _SVG_CALENDAR = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:text-bottom"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`;
const _SVG_COMPASS  = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:text-bottom"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>`;

function calculateDistance() {
    const redshift = document.getElementById('redshift-value').value;
    const redshiftError = document.getElementById('redshift-error').value;
    const resultDiv = document.getElementById('combined-result');
    
    if (!redshift) {
        showError(resultDiv, 'Please enter a redshift value');
        return;
    }
    
    showLoading(resultDiv);
    
    const data = {
        redshift: parseFloat(redshift)
    };
    
    if (redshiftError) {
        data.redshift_error = parseFloat(redshiftError);
    }
    
    fetch('/calculate_redshift', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        hideLoading(resultDiv);
        console.log('Backend response:', data); // 添加除錯
        if (data.success) {
            showDistanceResult(resultDiv, data.result);
        } else {
            showError(resultDiv, data.error || 'Calculation failed');
        }
    })
    .catch(error => {
        hideLoading(resultDiv);
        showError(resultDiv, 'Network error: ' + error.message);
    });
}

function calculateMagnitude() {
    const apparentMagnitude = document.getElementById('apparent-magnitude').value;
    const redshift = document.getElementById('redshift-value').value;
    const extinction = document.getElementById('extinction').value || '0';
    const resultDiv = document.getElementById('combined-result');
    
    if (!apparentMagnitude || !redshift) {
        showError(resultDiv, 'Please enter both apparent magnitude and redshift');
        return;
    }
    
    showLoading(resultDiv);
    
    const data = {
        apparent_magnitude: parseFloat(apparentMagnitude),
        redshift: parseFloat(redshift),
        extinction: parseFloat(extinction)
    };
    
    fetch('/calculate_absolute_magnitude', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        hideLoading(resultDiv);
        if (data.success) {
            showMagnitudeOnlyResult(resultDiv, data.result);
        } else {
            showError(resultDiv, data.error || 'Calculation failed');
        }
    })
    .catch(error => {
        hideLoading(resultDiv);
        showError(resultDiv, 'Network error: ' + error.message);
    });
}

function calculateBoth() {
    const redshift = document.getElementById('redshift-value').value;
    const apparentMagnitude = document.getElementById('apparent-magnitude').value;
    const resultDiv = document.getElementById('combined-result');
    
    if (!redshift) {
        showError(resultDiv, 'Please enter a redshift value');
        return;
    }
    
    showLoading(resultDiv);
    
    Promise.all([
        calculateDistanceData(redshift),
        apparentMagnitude ? calculateMagnitudeData(apparentMagnitude, redshift) : null
    ]).then(results => {
        hideLoading(resultDiv);
        console.log('Promise results:', results); // 添加除錯
        showCombinedResult(resultDiv, results[0], results[1]);
    }).catch(error => {
        hideLoading(resultDiv);
        showError(resultDiv, 'Calculation error: ' + error.message);
    });
}

function calculateDistanceData(redshift) {
    const redshiftError = document.getElementById('redshift-error').value;
    const data = { redshift: parseFloat(redshift) };
    
    if (redshiftError) {
        data.redshift_error = parseFloat(redshiftError);
    }
    
    return fetch('/calculate_redshift', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).then(response => response.json());
}

function calculateMagnitudeData(apparentMagnitude, redshift) {
    const extinction = document.getElementById('extinction').value || '0';
    const data = {
        apparent_magnitude: parseFloat(apparentMagnitude),
        redshift: parseFloat(redshift),
        extinction: parseFloat(extinction)
    };
    
    return fetch('/calculate_absolute_magnitude', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    }).then(response => response.json());
}

function getSelectedUnit() {
    return document.getElementById('distance-unit').value;
}

function formatDistance(result, unit) {
    console.log('Debug - formatDistance input:', result, unit);
    console.log('Debug - result keys:', Object.keys(result));
    
    const unitLabels = {
        'km': 'km',
        'ly': 'ly',
        'pc': 'pc',
        'Mpc': 'Mpc',
        'Gpc': 'Gpc'
    };
    
    // 修正：處理大小寫問題
    let distance = result[`distance_${unit}`];
    let error = result[`distance_error_${unit}`];
    
    // 如果找不到，嘗試小寫
    if (distance === undefined) {
        distance = result[`distance_${unit.toLowerCase()}`];
        error = result[`distance_error_${unit.toLowerCase()}`];
    }
    
    console.log('Debug - distance value:', distance);
    console.log('Debug - error value:', error);
    
    if (distance === undefined || distance === null || isNaN(distance)) {
        return `Error: No data for ${unitLabels[unit]}`;
    }
    
    let formattedDistance;
    if (unit === 'km' || unit === 'ly' || unit === 'pc') {
        formattedDistance = parseFloat(distance).toLocaleString();
    } else {
        formattedDistance = parseFloat(distance).toFixed(unit === 'Gpc' ? 4 : 2);
    }
    
    let errorText = '';
    if (error && !isNaN(error)) {
        const formattedError = unit === 'Gpc' ? parseFloat(error).toFixed(4) : parseFloat(error).toFixed(2);
        errorText = ` ± ${formattedError}`;
    }
    
    return `${formattedDistance}${errorText} ${unitLabels[unit]}`;
}

function showDistanceResult(container, result) {
    const selectedUnit = getSelectedUnit();
    const distanceText = formatDistance(result, selectedUnit);
    
    let html = '<div class="result-category">';
    html += `<h4>${_SVG_SCOPE} Distance Calculations</h4>`;
    html += '<div class="result-grid">';
    html += `<div class="result-item-compact" style="grid-column: 1 / -1;"><span class="result-label-compact">Distance</span><span class="result-value-compact">${distanceText}</span></div>`;
    html += '</div></div>';
    
    container.innerHTML = html;
    container.className = 'at-result-box';
}

function showCombinedResult(container, distanceResult, magnitudeResult) {
    let html = '';
    
    if (distanceResult && distanceResult.success) {
        const selectedUnit = getSelectedUnit();
        const distanceText = formatDistance(distanceResult.result, selectedUnit);
        
        html += '<div class="result-category">';
        html += `<h4>${_SVG_SCOPE} Distance Calculations</h4>`;
        html += '<div class="result-grid">';
        html += `<div class="result-item-compact" style="grid-column: 1 / -1;"><span class="result-label-compact">Distance</span><span class="result-value-compact">${distanceText}</span></div>`;
        html += '</div></div>';
    }
    
    if (magnitudeResult && magnitudeResult.success) {
        html += '<div class="result-category">';
        html += `<h4>${_SVG_STAR} Magnitude Calculations</h4>`;
        html += '<div class="result-grid">';
        html += `<div class="result-item-compact"><span class="result-label-compact">Absolute Magnitude</span><span class="result-value-compact">${parseFloat(magnitudeResult.result.absolute_magnitude).toFixed(2)}</span></div>`;
        html += `<div class="result-item-compact"><span class="result-label-compact">Distance Modulus</span><span class="result-value-compact">${parseFloat(magnitudeResult.result.distance_modulus).toFixed(2)}</span></div>`;
        
        if (magnitudeResult.result.extinction > 0) {
            html += `<div class="result-item-compact"><span class="result-label-compact">Extinction</span><span class="result-value-compact">${parseFloat(magnitudeResult.result.extinction).toFixed(2)}</span></div>`;
        }
        
        html += '</div></div>';
    }
    
    container.innerHTML = html;
    container.className = 'at-result-box';
}

function showMagnitudeOnlyResult(container, result) {
    let html = '<div class="result-category">';
    html += `<h4>${_SVG_STAR} Magnitude Calculations</h4>`;
    html += '<div class="result-grid">';
    html += `<div class="result-item-compact"><span class="result-label-compact">Absolute Magnitude</span><span class="result-value-compact">${parseFloat(result.absolute_magnitude).toFixed(2)}</span></div>`;
    html += `<div class="result-item-compact"><span class="result-label-compact">Distance Modulus</span><span class="result-value-compact">${parseFloat(result.distance_modulus).toFixed(2)}</span></div>`;
    html += `<div class="result-item-compact"><span class="result-label-compact">Luminosity Distance</span><span class="result-value-compact">${parseFloat(result.distance_mpc).toFixed(2)} Mpc</span></div>`;
    
    if (result.extinction > 0) {
        html += `<div class="result-item-compact"><span class="result-label-compact">Extinction</span><span class="result-value-compact">${parseFloat(result.extinction).toFixed(2)}</span></div>`;
    }
    
    html += '</div></div>';
    container.innerHTML = html;
    container.className = 'at-result-box';
}

function showLoading(container) {
    container.innerHTML = '<div class="at-spinner-wrap"><div class="spinner"></div></div>';
}

function hideLoading(container) {
    // Loading will be replaced by results
}

function convertDate() {
    const mjd = document.getElementById('mjd').value;
    const jd = document.getElementById('jd').value;
    const commonDate = document.getElementById('common-date').value;
    const resultDiv = document.getElementById('date-result');
    
    if (!mjd && !jd && !commonDate) {
        showError(resultDiv, 'Please enter at least one date value');
        return;
    }
    
    const data = {};
    if (mjd) data.mjd = parseFloat(mjd);
    if (jd) data.jd = parseFloat(jd);
    if (commonDate) data.common_date = commonDate;
    
    fetch('/convert_date', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showDateResult(resultDiv, data.result);
        } else {
            showError(resultDiv, data.error || 'Conversion failed');
        }
    })
    .catch(error => {
        showError(resultDiv, 'Network error: ' + error.message);
    });
}

function convertRA() {
    const raHms = document.getElementById('ra-hms').value;
    const raDecimal = document.getElementById('ra-decimal').value;
    const resultDiv = document.getElementById('ra-result');
    
    if (!raHms && !raDecimal) {
        showError(resultDiv, 'Please enter either HMS or decimal degrees');
        return;
    }
    
    const data = {};
    if (raHms) data.ra_hms = raHms;
    if (raDecimal) data.ra_decimal = parseFloat(raDecimal);
    
    fetch('/convert_ra', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showRAResult(resultDiv, data.result);
        } else {
            showError(resultDiv, data.error || 'Conversion failed');
        }
    })
    .catch(error => {
        showError(resultDiv, 'Network error: ' + error.message);
    });
}

function convertDEC() {
    const decDms = document.getElementById('dec-dms').value;
    const decDecimal = document.getElementById('dec-decimal').value;
    const resultDiv = document.getElementById('dec-result');
    
    if (!decDms && !decDecimal) {
        showError(resultDiv, 'Please enter either DMS or decimal degrees');
        return;
    }
    
    const data = {};
    if (decDms) data.dec_dms = decDms;
    if (decDecimal) data.dec_decimal = parseFloat(decDecimal);
    
    fetch('/convert_dec', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showDECResult(resultDiv, data.result);
        } else {
            showError(resultDiv, data.error || 'Conversion failed');
        }
    })
    .catch(error => {
        showError(resultDiv, 'Network error: ' + error.message);
    });
}

function showDateResult(container, result) {
    let html = '<div class="result-category">';
    html += `<h4>${_SVG_CALENDAR} Date Conversions</h4>`;
    html += '<div class="result-grid">';
    html += `<div class="result-item-compact"><span class="result-label-compact">MJD</span><span class="result-value-compact">${parseFloat(result.mjd).toFixed(6)}</span></div>`;
    html += `<div class="result-item-compact"><span class="result-label-compact">JD</span><span class="result-value-compact">${parseFloat(result.jd).toFixed(6)}</span></div>`;
    html += `<div class="result-item-compact" style="grid-column: 1 / -1;"><span class="result-label-compact">Common Date</span><span class="result-value-compact">${result.common_date}</span></div>`;
    html += '</div></div>';
    
    container.innerHTML = html;
    container.className = 'at-result-box';
}

function showRAResult(container, result) {
    let html = '<div class="result-category">';
    html += `<h4>${_SVG_COMPASS} RA Results</h4>`;
    html += '<div class="result-grid">';
    html += `<div class="result-item-compact"><span class="result-label-compact">HMS Format</span><span class="result-value-compact">${result.ra_hms}</span></div>`;
    html += `<div class="result-item-compact"><span class="result-label-compact">Decimal Degrees</span><span class="result-value-compact">${parseFloat(result.ra_decimal).toFixed(6)}°</span></div>`;
    html += '</div></div>';
    
    container.innerHTML = html;
    container.className = 'at-result-box at-result-sm';
}

function showDECResult(container, result) {
    let html = '<div class="result-category">';
    html += `<h4>${_SVG_COMPASS} DEC Results</h4>`;
    html += '<div class="result-grid">';
    html += `<div class="result-item-compact"><span class="result-label-compact">DMS Format</span><span class="result-value-compact">${result.dec_dms}</span></div>`;
    html += `<div class="result-item-compact"><span class="result-label-compact">Decimal Degrees</span><span class="result-value-compact">${parseFloat(result.dec_decimal).toFixed(6)}°</span></div>`;
    html += '</div></div>';
    
    container.innerHTML = html;
    container.className = 'at-result-box at-result-sm';
}

function showError(container, message) {
    container.innerHTML = `<div class="error-message">${message}</div>`;
}

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('distance-unit').addEventListener('change', function() {
        const resultDiv = document.getElementById('combined-result');
        if (resultDiv.innerHTML.includes('Distance Calculations')) {
            calculateBoth();
        }
    });

    document.getElementById('mjd').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('jd').value = '';
            document.getElementById('common-date').value = '';
        }
    });
    
    document.getElementById('jd').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('mjd').value = '';
            document.getElementById('common-date').value = '';
        }
    });
    
    document.getElementById('common-date').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('mjd').value = '';
            document.getElementById('jd').value = '';
        }
    });
    
    document.getElementById('ra-hms').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('ra-decimal').value = '';
        }
    });
    
    document.getElementById('ra-decimal').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('ra-hms').value = '';
        }
    });
    
    document.getElementById('dec-dms').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('dec-decimal').value = '';
        }
    });
    
    document.getElementById('dec-decimal').addEventListener('input', function() {
        if (this.value) {
            document.getElementById('dec-dms').value = '';
        }
    });
    
    document.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const activeElement = document.activeElement;
            
            if (activeElement.closest('.input-section')) {
                calculateBoth();
            } else if (activeElement.closest('#date-grid')) {
                convertDate();
            } else if (activeElement.closest('.coordinate-section')) {
                if (activeElement.id.includes('ra')) {
                    convertRA();
                } else if (activeElement.id.includes('dec')) {
                    convertDEC();
                }
            }
        }
    });
});

