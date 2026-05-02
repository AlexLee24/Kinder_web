// ═══════════════════════════════════════════════════════════════════
//  LC Plotter — Interactive light curve plotter
// ═══════════════════════════════════════════════════════════════════

// Load filter color map from server-injected JSON (see app/data/filter_colors.json)
const FILTER_COLORS = JSON.parse(document.getElementById('filterColorsData').textContent);

// Per-user filter color overrides stored in localStorage
const _LCP_USER_EMAIL = JSON.parse(document.getElementById('lcpUserEmail').textContent) || '';
const _LCP_LS_KEY = _LCP_USER_EMAIL ? `lcp_filter_colors_${_LCP_USER_EMAIL}` : 'lcp_filter_colors_guest';
let colorOverrides = {};
try { colorOverrides = JSON.parse(localStorage.getItem(_LCP_LS_KEY) || '{}'); } catch (_) {}

function _saveColorOverrides() {
    seriesList.forEach(s => { if (s.groupVal !== '__all__') colorOverrides[s.groupVal] = s.color; });
    try { localStorage.setItem(_LCP_LS_KEY, JSON.stringify(colorOverrides)); } catch (_) {}
}

const AUTO_COLORS = [
    '#4fc3f7', '#ef5350', '#66bb6a', '#ffa726', '#ab47bc',
    '#26c6da', '#d4e157', '#ff7043', '#42a5f5', '#ec407a',
    '#80cbc4', '#ffcc02', '#ce93d8', '#a5d6a7', '#ffab91',
];

const MARKER_SHAPES = [
    { value: 'circle',           label: '● Circle' },
    { value: 'circle-open',      label: '○ Circle open' },
    { value: 'square',           label: '■ Square' },
    { value: 'square-open',      label: '□ Square open' },
    { value: 'diamond',          label: '◆ Diamond' },
    { value: 'diamond-open',     label: '◇ Diamond open' },
    { value: 'triangle-up',      label: '▲ Triangle ▲' },
    { value: 'triangle-up-open', label: '△ Triangle open' },
    { value: 'triangle-down',    label: '▼ Triangle ▼' },
    { value: 'cross',            label: '+ Cross' },
    { value: 'x',                label: '✕ X' },
    { value: 'star',             label: '★ Star' },
    { value: 'pentagon',         label: '⬠ Pentagon' },
    { value: 'hexagon',          label: '⬡ Hexagon' },
];

const LINE_STYLES = [
    { value: 'solid',   label: '─ Solid' },
    { value: 'dash',    label: '╌ Dash' },
    { value: 'dot',     label: '··· Dot' },
    { value: 'dashdot', label: '-·- Dash-dot' },
];

// Filter display order: u U B g V r R i I z y w o, then alphabetical for others
const FILTER_ORDER = ['u','U','B','g','V','r','R','i','I','z','y','w','o'];

// ─── State ───────────────────────────────────────────────────────
let parsedData   = null;
let seriesList   = [];
let plotRendered = false;
let _syncing     = false;
let _eventsAttached = false;

// ─── Secondary axis helpers ───────────────────────────────────────
function getTopXMode()  { return document.getElementById('topXMode').value; }
function getRightYMode(){ return document.getElementById('rightYMode').value; }

function onTopXChange() {
    const mode = getTopXMode();
    document.getElementById('phaseOpts').style.display = mode === 'phase' ? '' : 'none';
    document.getElementById('dateOpts').style.display  = mode === 'date'  ? '' : 'none';
}

function onRightYChange() {
    document.getElementById('absMagOpts').style.display =
        getRightYMode() === 'absmag' ? '' : 'none';
}

// MJD → ISO date string for Plotly date axis
function mjdToISODate(mjd) {
    // MJD 40587 = 1970-01-01 00:00:00 UTC
    const d = new Date((mjd - 40587) * 86400000);
    const y  = d.getUTCFullYear();
    const mo = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dy = String(d.getUTCDate()).padStart(2, '0');
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mi = String(d.getUTCMinutes()).padStart(2, '0');
    return `${y}-${mo}-${dy} ${hh}:${mi}`;
}

// Build a linear interpolation function: bottomXCol values → targetCol values
function buildColInterp(bottomColName, targetColName) {
    if (!parsedData) return null;
    const h    = parsedData.headers;
    const xIdx = h.indexOf(bottomColName);
    const cIdx = h.indexOf(targetColName);
    if (xIdx < 0 || cIdx < 0) return null;
    const pairs = parsedData.rows
        .map(r => [parseFloat(r[xIdx]), parseFloat(r[cIdx])])
        .filter(p => !isNaN(p[0]) && !isNaN(p[1]))
        .sort((a, b) => a[0] - b[0]);
    if (pairs.length < 2) return null;
    return (x) => {
        if (x <= pairs[0][0]) return pairs[0][1];
        if (x >= pairs[pairs.length - 1][0]) return pairs[pairs.length - 1][1];
        let lo = 0, hi = pairs.length - 1;
        while (hi - lo > 1) { const m = (lo + hi) >> 1; if (pairs[m][0] <= x) lo = m; else hi = m; }
        const t = (x - pairs[lo][0]) / (pairs[hi][0] - pairs[lo][0]);
        return pairs[lo][1] + t * (pairs[hi][1] - pairs[lo][1]);
    };
}

function getExplosionMJD() {
    const mjdVal = document.getElementById('lcExpMJD').value;
    return mjdVal ? parseFloat(mjdVal) : null;
}

function getDistanceModulus() {
    const z = parseFloat(document.getElementById('lcRedshift').value);
    if (!z || isNaN(z) || z <= 0) return 0;
    // MW extinction is applied per-series at data level in buildTraces
    return computeDistanceModulus(z, 0);
}

// ─── File Parsing ─────────────────────────────────────────────────
function parseFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const result = parseText(e.target.result, file.name);
            if (!result) { showToast('Could not parse file.', 'error'); return; }
            parsedData = result;
            onDataLoaded(file.name, file.size);
        } catch (err) {
            showToast('Parse error: ' + err.message, 'error');
        }
    };
    reader.onerror = () => showToast('File read error.', 'error');
    reader.readAsText(file);
}

function parseText(text, filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const allLines = text.split('\n').map(l => l.replace(/\r$/, ''));
    // Extract #setting_key:value lines (embedded settings from exportDAT)
    const settings = {};
    allLines.forEach(l => {
        const m = l.trim().match(/^#setting_([^:]+):(.*)$/);
        if (m) settings[m[1]] = m[2];
    });
    const rawLines = allLines.filter(l => l.trim() && !l.trim().startsWith('#'));
    if (rawLines.length < 2) return null;

    const sample = rawLines[0];
    let delimiter;
    if (ext === 'csv') {
        delimiter = ',';
    } else if ((sample.match(/\t/g) || []).length >= 1) {
        delimiter = '\t';
    } else if ((sample.match(/,/g) || []).length >= 1) {
        delimiter = ',';
    } else {
        delimiter = null;
    }

    const splitLine = delimiter
        ? (l) => l.split(delimiter).map(s => s.trim())
        : (l) => l.trim().split(/\s+/);

    const headers = splitLine(rawLines[0]);
    const firstIsHeader = headers.some(h => isNaN(parseFloat(h)) || h.trim() === '');
    let dataLines, finalHeaders;
    if (firstIsHeader) {
        finalHeaders = headers.map(h => h.replace(/^["']|["']$/g, ''));
        dataLines = rawLines.slice(1);
    } else {
        finalHeaders = headers.map((_, i) => `col${i}`);
        dataLines = rawLines;
    }

    const rows = dataLines
        .map(l => splitLine(l))
        .filter(r => r.length > 0 && r.some(v => v !== ''));

    return { headers: finalHeaders, rows, filename, settings };
}

// ─── On Data Loaded ───────────────────────────────────────────────
function onDataLoaded(filename, filesize) {
    const info = document.getElementById('fileInfo');
    info.style.display = 'flex';
    info.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        <strong>${escHtml(filename)}</strong>
        &nbsp;·&nbsp; ${parsedData.rows.length} rows × ${parsedData.headers.length} cols
        &nbsp;·&nbsp; ${(filesize / 1024).toFixed(1)} KB
    `;
    populateSelects();
    const hasSaved = parsedData.settings && Object.keys(parsedData.settings).length > 0;
    if (hasSaved) _applySettingsUI(parsedData.settings);
    else autoDetectColumns();
    showPreview();
    updateSeries();
    if (hasSaved) _applySettingsSeries(parsedData.settings);
    showToast(hasSaved ? `Settings restored (${parsedData.rows.length} rows)` : `Loaded ${parsedData.rows.length} rows`, 'ok');
}

// ─── Populate All Column Selectors ────────────────────────────────
function populateSelects() {
    const headers = parsedData.headers;

    // Primary X/Y: placeholder + "Data Column" optgroup
    ['xCol','yCol'].forEach(id => {
        const sel  = document.getElementById(id);
        const prev = sel.value;
        sel.innerHTML = '<option value="">— select —</option>';
        const grp = document.createElement('optgroup');
        grp.label = 'Data Column';
        headers.forEach(h => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = h;
            if (h === prev) opt.selected = true;
            grp.appendChild(opt);
        });
        sel.appendChild(grp);
    });

    // "none" selects (no optgroup needed)
    ['yErrCol','xErrCol','groupCol','lcFilterCol','lcULFlagCol','lcULLimCol'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const prev = sel.value;
        sel.innerHTML = '<option value="">— none —</option>';
        headers.forEach(h => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = h;
            if (h === prev) opt.selected = true;
            sel.appendChild(opt);
        });
    });

    // UL mag col
    const ulMagSel = document.getElementById('lcULMagCol');
    if (ulMagSel) {
        const prev = ulMagSel.value;
        ulMagSel.innerHTML = '<option value="">(same as Y)</option>';
        headers.forEach(h => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = h;
            if (h === prev) opt.selected = true;
            ulMagSel.appendChild(opt);
        });
    }

    // Date mode MJD col
    const dateMJDSel = document.getElementById('dateXMJDCol');
    if (dateMJDSel) {
        const prev = dateMJDSel.value;
        dateMJDSel.innerHTML = '<option value="">(same as X)</option>';
        headers.forEach(h => {
            const opt = document.createElement('option');
            opt.value = opt.textContent = h;
            if (h === prev) opt.selected = true;
            dateMJDSel.appendChild(opt);
        });
    }

    // Secondary axes: refresh "Data Column" optgroup preserving computed options
    _refreshSecondaryColGroup('topXMode',  'topXDataGroup');
    _refreshSecondaryColGroup('rightYMode','rightYDataGroup');
}

function _refreshSecondaryColGroup(selId, grpId) {
    const sel  = document.getElementById(selId);
    const prev = sel.value;
    const old  = document.getElementById(grpId);
    if (old) old.remove();
    const grp = document.createElement('optgroup');
    grp.id    = grpId;
    grp.label = 'Data Column';
    parsedData.headers.forEach(h => {
        const opt = new Option(h, 'col:' + h);
        if ('col:' + h === prev) opt.selected = true;
        grp.appendChild(opt);
    });
    sel.appendChild(grp);
}

// ─── Auto Detect Common Column Names ──────────────────────────────
function autoDetectColumns() {
    const h = parsedData.headers.map(x => x.toLowerCase());
    const pick = (candidates, selId) => {
        const sel = document.getElementById(selId);
        if (sel.value) return;
        const found = candidates.find(c => h.includes(c.toLowerCase()));
        if (found) {
            const real = parsedData.headers[h.indexOf(found.toLowerCase())];
            sel.value = real;
        }
    };
    pick(['mjd','jd','time','date','phase','x','epoch','t'], 'xCol');
    pick(['mag','magnitude','flux','fnujy','y','brightness'], 'yCol');
    pick(['magerr','mag_err','emag','e_mag','sigma','err','error','unc','dmag','e_flux','flux_err'], 'yErrCol');
    pick(['filter','band','filt','passband'], 'groupCol');
    pick(['filter','band','filt','passband'], 'lcFilterCol');
    pick(['ul','upperlimit','upper_limit','nondetection','flag'], 'lcULFlagCol');
    pick(['lim','limit','limmag','ul_mag','mag_lim'], 'lcULLimCol');

    const fc = document.getElementById('lcFilterCol').value;
    const gc = document.getElementById('groupCol');
    if (fc && !gc.value) gc.value = fc;

    onColumnChange();
    onGroupChange();
}

// ─── Preview Table ────────────────────────────────────────────────
function showPreview() {
    const wrap = document.getElementById('previewWrap');
    const tbl  = document.getElementById('previewTable');
    tbl.innerHTML = '';
    const thead = document.createElement('thead');
    const hrow  = document.createElement('tr');
    parsedData.headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    tbl.appendChild(thead);
    const tbody = document.createElement('tbody');
    parsedData.rows.slice(0, 5).forEach(row => {
        const tr = document.createElement('tr');
        parsedData.headers.forEach((_, i) => {
            const td = document.createElement('td');
            td.textContent = row[i] !== undefined ? row[i] : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.style.display = '';
}

function showAllRows() {
    if (!parsedData) return;
    // Build modal overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
    const box = document.createElement('div');
    box.style.cssText = 'background:#1a1a2e;border:1px solid rgba(255,255,255,0.15);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;max-width:90vw;max-height:85vh;min-width:400px';
    const hd = document.createElement('div');
    hd.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.1);flex-shrink:0';
    hd.innerHTML = `<span style="color:#e8e8f0;font-size:0.85rem;font-weight:600">${escHtml(parsedData.headers.join(' · '))} &nbsp;·&nbsp; ${parsedData.rows.length} rows</span>`;
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'background:none;border:none;color:#aaa;font-size:1rem;cursor:pointer;padding:2px 6px';
    closeBtn.onclick = () => document.body.removeChild(overlay);
    hd.appendChild(closeBtn);
    box.appendChild(hd);
    const scrollWrap = document.createElement('div');
    scrollWrap.style.cssText = 'overflow:auto;flex:1';
    const tbl = document.createElement('table');
    tbl.style.cssText = 'border-collapse:collapse;width:100%;font-size:0.78rem;white-space:nowrap';
    const thead = document.createElement('thead');
    const hrow = document.createElement('tr');
    parsedData.headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        th.style.cssText = 'padding:6px 10px;background:#12121e;color:#ccccdd;border-bottom:1px solid rgba(255,255,255,0.1);position:sticky;top:0;text-align:left';
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    tbl.appendChild(thead);
    const tbody = document.createElement('tbody');
    parsedData.rows.forEach((row, ri) => {
        const tr = document.createElement('tr');
        tr.style.background = ri % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.03)';
        parsedData.headers.forEach((_, i) => {
            const td = document.createElement('td');
            td.textContent = row[i] !== undefined ? row[i] : '';
            td.style.cssText = 'padding:4px 10px;color:#ccccdd;border-bottom:1px solid rgba(255,255,255,0.04)';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    scrollWrap.appendChild(tbl);
    box.appendChild(scrollWrap);
    overlay.appendChild(box);
    overlay.addEventListener('click', e => { if (e.target === overlay) document.body.removeChild(overlay); });
    document.body.appendChild(overlay);
}

// ─── Series Management ────────────────────────────────────────────
function getGroupValues() {
    if (!parsedData) return ['__all__'];
    const colName = document.getElementById('groupCol').value;
    if (!colName) return ['__all__'];
    const idx = parsedData.headers.indexOf(colName);
    if (idx < 0) return ['__all__'];
    const vals = [...new Set(parsedData.rows.map(r => r[idx] || ''))].filter(Boolean).sort();
    return vals.length ? vals : ['__all__'];
}

function updateSeries() {
    let groups = getGroupValues();
    // Always sort by standard filter order; unknowns go last alphabetically
    groups = [...groups].sort((a, b) => {
        const ia = FILTER_ORDER.indexOf(a), ib = FILTER_ORDER.indexOf(b);
        const ka = ia >= 0 ? ia : FILTER_ORDER.length;
        const kb = ib >= 0 ? ib : FILTER_ORDER.length;
        return ka !== kb ? ka - kb : a.localeCompare(b);
    });
    const prevMap = Object.fromEntries(seriesList.map(s => [s.groupVal, s]));
    seriesList = groups.map((gv, i) => {
        if (prevMap[gv]) return prevMap[gv];
        return {
            id: i, groupVal: gv,
            label: gv === '__all__' ? 'Series 1' : gv,
            color: colorOverrides[gv] || FILTER_COLORS[gv] || AUTO_COLORS[i % AUTO_COLORS.length],
            shape: 'circle', showLine: false, lineStyle: 'solid',
            lineWidth: 1.5, markerSize: 8,
            starIndices: new Set(), visible: true,
            ulLabel: 'upper limit', ulInLegend: true,
            mwExt: 0,
            starSize: 14,
        };
    });
    renderSeriesManager();
    document.getElementById('seriesCard').style.display = seriesList.length ? '' : 'none';
}

function renderSeriesManager() {
    const container = document.getElementById('seriesManager');
    container.innerHTML = '';
    const useUL    = document.getElementById('lcUpperLimit').checked;
    const useMWExt = document.getElementById('lcMWExt').checked;
    seriesList.forEach((cfg, idx) => {
        const item       = document.createElement('div');
        item.className   = 'lcp-series-item';
        const color      = cfg.color || '#aaaaaa';
        const colorSolid = hexToRgba(color, 1.0);
        const colorFill  = hexToRgba(color, 1.0);
        const lineEl     = cfg.showLine
            ? `<line x1="0" y1="7" x2="26" y2="7" stroke="${colorSolid}" stroke-width="1.5"/>`
            : '';
        const shapeOpts = MARKER_SHAPES.map(s =>
            `<option value="${s.value}" ${cfg.shape === s.value ? 'selected' : ''}>${s.label}</option>`
        ).join('');
        const lineOpts = LINE_STYLES.map(s =>
            `<option value="${s.value}" ${cfg.lineStyle === s.value ? 'selected' : ''}>${s.label}</option>`
        ).join('');
        item.innerHTML = `
            <div class="lcp-series-header">
                <input type="checkbox" class="s-vis" ${cfg.visible ? 'checked' : ''} title="Visible">
                <svg class="lcp-legend-swatch" width="26" height="14" viewBox="0 0 26 14">${lineEl}
                    <circle cx="13" cy="7" r="4" fill="${colorFill}" stroke="${colorSolid}" stroke-width="1"/>
                </svg>
                <input type="text" class="lcp-series-label s-label" value="${escHtml(cfg.label)}">
                <input type="color" class="lcp-series-color s-color" value="${colorToHex(cfg.color)}" title="Color">
            </div>
            <div class="lcp-series-body">
                <div class="lcp-series-row">
                    <span>Shape</span>
                    <select class="s-shape" style="flex:1">${shapeOpts}</select>
                    <span>size</span>
                    <input type="number" class="lcp-input-small s-size" min="2" max="30" step="1" value="${cfg.markerSize}">
                </div>
                <div class="lcp-series-row">
                    <span>Line</span>
                    <input type="checkbox" class="s-line" ${cfg.showLine ? 'checked' : ''}>
                    <select class="s-lstyle" style="flex:1">${lineOpts}</select>
                    <input type="number" class="lcp-input-small s-lwidth" min="0.5" max="8" step="0.5" value="${cfg.lineWidth}" title="Line width">
                </div>
                <div class="lcp-series-row" style="flex-wrap:wrap;gap:4px">
                    <span title="X-values or row indices (0-based) to mark as ★">★ pts</span>
                    <input type="text" class="lcp-input-full s-stars"
                        placeholder="x-values or row indices, comma separated"
                        value="${[...cfg.starIndices].join(', ')}">
                    <span title="Star marker size">★ sz</span>
                    <input type="number" class="lcp-input-small s-starsize" min="4" max="40" step="1" value="${cfg.starSize != null ? cfg.starSize : 14}">
                </div>
                <div class="lcp-series-row s-mwext-row" style="${useMWExt ? '' : 'display:none'}">
                    <span title="Milky Way extinction A (mag)">A_MW</span>
                    <input type="number" class="lcp-input-full s-mwext" step="0.001" min="0" max="10"
                        placeholder="0.000" value="${cfg.mwExt != null ? cfg.mwExt : 0}">
                    <span style="font-size:0.68rem;color:var(--lcp-muted);white-space:nowrap">mag</span>
                </div>
            </div>
        `;
        item.querySelector('.s-vis').addEventListener('change',    e => { seriesList[idx].visible    = e.target.checked;  updateLegendPreview(); });
        item.querySelector('.s-label').addEventListener('input',   e => { seriesList[idx].label      = e.target.value;    updateLegendPreview(); });
        item.querySelector('.s-color').addEventListener('input',   e => { seriesList[idx].color      = e.target.value;    updateLegendPreview(); _saveColorOverrides(); });
        item.querySelector('.s-shape').addEventListener('change',  e => { seriesList[idx].shape      = e.target.value; });
        item.querySelector('.s-size').addEventListener('change',   e => { seriesList[idx].markerSize = +e.target.value; });
        item.querySelector('.s-starsize').addEventListener('change', e => { seriesList[idx].starSize  = +e.target.value; });
        item.querySelector('.s-line').addEventListener('change',   e => { seriesList[idx].showLine   = e.target.checked;  updateLegendPreview(); });
        item.querySelector('.s-lstyle').addEventListener('change', e => { seriesList[idx].lineStyle  = e.target.value; });
        item.querySelector('.s-lwidth').addEventListener('change', e => { seriesList[idx].lineWidth  = +e.target.value; });
        item.querySelector('.s-mwext').addEventListener('change',  e => { seriesList[idx].mwExt     = parseFloat(e.target.value) || 0; });
        item.querySelector('.s-stars').addEventListener('change',  e => {
            const vals = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
            const xValues = getSeriesXValues(seriesList[idx]);
            const snapped = vals.map(v => {
                const n = parseFloat(v);
                if (isNaN(n) || !xValues.length) return v;
                let best = xValues[0], bestDist = Math.abs(xValues[0] - n);
                for (const x of xValues) {
                    const d = Math.abs(x - n);
                    if (d < bestDist) { bestDist = d; best = x; }
                }
                return String(best);
            });
            seriesList[idx].starIndices = new Set(snapped);
            e.target.value = snapped.join(', ');
        });
        container.appendChild(item);
    });
    updateLegendPreview();
}

function updateLegendPreview() {
    const el = document.getElementById('legendPreview');
    if (!el) return;
    if (!seriesList.length) { el.style.display = 'none'; return; }
    const useUL = document.getElementById('lcUpperLimit').checked;
    el.style.display = '';

    el.innerHTML = '<div class="lcp-legend-preview-hd">Legend Preview — edit text directly</div>';

    seriesList.forEach((cfg, idx) => {
        if (!cfg.visible) return;
        const color  = cfg.color || '#aaaaaa';
        const cSolid = hexToRgba(color, 1.0);
        const cFill  = hexToRgba(color, 1.0);
        const lineEl = cfg.showLine
            ? `<line x1="0" y1="7" x2="26" y2="7" stroke="${cSolid}" stroke-width="1.5"/>`
            : '';

        // Main row: editable label
        const mainRow = document.createElement('div');
        mainRow.className = 'lcp-legend-item';
        mainRow.innerHTML = `<svg class="lcp-legend-swatch" width="26" height="14" viewBox="0 0 26 14">${lineEl}
            <circle cx="13" cy="7" r="4" fill="${cFill}" stroke="${cSolid}" stroke-width="1"/>
        </svg>`;
        const labelInput = document.createElement('input');
        labelInput.type      = 'text';
        labelInput.className = 'lcp-legend-label-edit';
        labelInput.value     = cfg.label;
        labelInput.addEventListener('input', e => {
            seriesList[idx].label = e.target.value;
            // sync series header label input
            const sLabel = document.querySelector(`#seriesManager .lcp-series-item:nth-child(${idx + 1}) .s-label`);
            if (sLabel) sLabel.value = e.target.value;
        });
        mainRow.appendChild(labelInput);
        el.appendChild(mainRow);

        // UL row: checkbox (show in legend) + label prefix (read-only) + editable suffix
        if (useUL) {
            const ulRow = document.createElement('div');
            ulRow.className = 'lcp-legend-item';
            ulRow.innerHTML = `<svg class="lcp-legend-swatch" width="26" height="14" viewBox="0 0 26 14">
                <polygon points="3,1 23,1 13,13" fill="${hexToRgba(color, 0.25)}" stroke="${cSolid}" stroke-width="1.5"/>
            </svg>`;
            // UL-in-legend checkbox
            const ulChk = document.createElement('input');
            ulChk.type    = 'checkbox';
            ulChk.checked = cfg.ulInLegend !== false;
            ulChk.title   = 'Show UL in legend';
            ulChk.style.cssText = 'flex-shrink:0;accent-color:var(--lcp-gold,#f0c040);cursor:pointer';
            ulChk.addEventListener('change', e => { seriesList[idx].ulInLegend = e.target.checked; });
            const ulPrefix = document.createElement('span');
            ulPrefix.className = 'lcp-legend-ul-prefix';
            ulPrefix.textContent = cfg.label + ' ';
            const ulInput = document.createElement('input');
            ulInput.type      = 'text';
            ulInput.className = 'lcp-legend-label-edit lcp-legend-ul-edit';
            ulInput.value     = cfg.ulLabel || 'upper limit';
            ulInput.title     = 'UL legend suffix';
            ulInput.addEventListener('input', e => {
                seriesList[idx].ulLabel = e.target.value;
                ulPrefix.textContent = seriesList[idx].label + ' ';
            });
            ulRow.appendChild(ulChk);
            ulRow.appendChild(ulPrefix);
            ulRow.appendChild(ulInput);
            el.appendChild(ulRow);
        }
    });
}

// Return all non-UL x-values for a series (used for ★ pts snap)
function getSeriesXValues(cfg) {
    if (!parsedData) return [];
    const headers = parsedData.headers;
    const xIdx    = headers.indexOf(document.getElementById('xCol').value);
    const gIdx    = headers.indexOf(document.getElementById('groupCol').value);
    if (xIdx < 0) return [];
    return parsedData.rows
        .filter(row => cfg.groupVal === '__all__' || gIdx < 0 || (row[gIdx] || '__null__') === cfg.groupVal)
        .map(row => parseFloat(row[xIdx]))
        .filter(x => !isNaN(x));
}

function autoMapFilterColors() {
    const filterColName = document.getElementById('lcFilterCol').value;
    if (!filterColName || !parsedData) { showToast('Select a filter column first', 'warn'); return; }
    let mapped = 0;
    seriesList.forEach(cfg => {
        const fc = FILTER_COLORS[cfg.groupVal];
        if (fc) { cfg.color = fc; mapped++; }
    });
    renderSeriesManager();
    showToast(`Mapped ${mapped} filter colors`, 'ok');
    _saveColorOverrides();
}

// ─── LC Math ──────────────────────────────────────────────────────
// Flat ΛCDM (H0=67.7, Om0=0.309) luminosity distance via numerical integration
// Returns total offset for M = m - computeDistanceModulus(z, A):
//   offset = μ + K_corr + A   where  K = 2.5*log10(1+z)
function computeDistanceModulus(z, extA = 0) {
    if (!z || z <= 0) return 0;
    const H0 = 67.7, c = 299792.458;
    const Om0 = 0.309, OL0 = 0.691;
    // Numerical integration of 1/E(z) for comoving distance
    const n = 500;
    let dc = 0;
    for (let i = 0; i < n; i++) {
        const zi = (i + 0.5) * z / n;
        dc += 1.0 / Math.sqrt(Om0 * Math.pow(1 + zi, 3) + OL0);
    }
    dc *= z / n;
    const dL_mpc = (c / H0) * dc * (1 + z);
    const mu     = 5 * Math.log10(dL_mpc * 1e6) - 5;  // distance modulus
    const k_corr = 2.5 * Math.log10(1 + z);            // K-correction
    return mu + k_corr + extA;
}

function dateToMJD(dateStr) {
    if (!dateStr) return null;
    const d = new Date(dateStr + 'T00:00:00Z');
    if (isNaN(d)) return null;
    const jd = d.getTime() / 86400000.0 + 2440587.5;
    return jd - 2400000.5;
}

// ─── Build Traces ─────────────────────────────────────────────────
// Data is always plotted in RAW values. Secondary axes handle transformations visually.
function buildTraces() {
    const headers = parsedData.headers;
    const rows    = parsedData.rows;

    const xIdx    = headers.indexOf(document.getElementById('xCol').value);
    const yIdx    = headers.indexOf(document.getElementById('yCol').value);
    const yErrIdx = headers.indexOf(document.getElementById('yErrCol').value);
    const xErrIdx = headers.indexOf(document.getElementById('xErrCol').value);
    const gIdx    = headers.indexOf(document.getElementById('groupCol').value);

    const useUL        = document.getElementById('lcUpperLimit').checked;
    const ulMode       = useUL ? document.getElementById('lcULMode').value : 'flag';
    const ulFlagColName= document.getElementById('lcULFlagCol').value;
    const ulFlagVal    = document.getElementById('lcULFlagVal').value.trim().toLowerCase();
    const ulMagColName = document.getElementById('lcULMagCol').value;
    const ulLimColName = document.getElementById('lcULLimCol').value;
    const ulFlagIdx    = ulFlagColName ? headers.indexOf(ulFlagColName) : -1;
    const ulMagIdx     = ulMagColName  ? headers.indexOf(ulMagColName)  : -1;
    const useMWExt     = document.getElementById('lcMWExt').checked;
    const cfgMap       = Object.fromEntries(seriesList.map(s => [s.groupVal, s]));
    const ulLimIdx     = ulLimColName  ? headers.indexOf(ulLimColName)  : -1;

    // Bucket rows by group value
    const buckets = {};
    rows.forEach((row, rowIdx) => {
        const gVal = gIdx >= 0 ? (row[gIdx] || '__null__') : '__all__';
        if (!buckets[gVal]) buckets[gVal] = [];
        const xRaw = parseFloat(row[xIdx]);
        if (isNaN(xRaw)) return;

        let isUL = false;
        let yVal = parseFloat(row[yIdx]);
        const mwExt = (useMWExt && cfgMap[gVal]) ? (cfgMap[gVal].mwExt || 0) : 0;

        if (useUL) {
            if (ulMode === 'flag') {
                if (ulFlagIdx >= 0) {
                    const fs = String(row[ulFlagIdx]).trim().toLowerCase();
                    isUL = (fs === ulFlagVal) ||
                           (ulFlagVal === '1' && fs === 'true') ||
                           (ulFlagVal === 'true' && fs === '1');
                }
                // If flag matches and a separate mag col is set, override yVal
                if (isUL && ulMagIdx >= 0) {
                    const mv = parseFloat(row[ulMagIdx]);
                    if (!isNaN(mv)) yVal = mv;
                }
            } else {
                // direct mode: limit col has the magnitude; row is UL if non-NaN there
                if (ulLimIdx >= 0) {
                    const lv = parseFloat(row[ulLimIdx]);
                    if (!isNaN(lv)) { isUL = true; yVal = lv; }
                }
            }
        }

        if (isNaN(yVal)) return;
        const yErr = yErrIdx >= 0 ? parseFloat(row[yErrIdx]) : NaN;
        const xErr = xErrIdx >= 0 ? parseFloat(row[xErrIdx]) : NaN;
        buckets[gVal].push({ x: xRaw, y: yVal - mwExt, yErr, xErr, isUL, rowIdx });
    });

    const traces = [];

    seriesList.forEach(cfg => {
        if (!cfg.visible) return;
        const items = buckets[cfg.groupVal] || [];
        if (!items.length) return;

        const color     = cfg.color || '#aaaaaa';
        const colorSolid = hexToRgba(color, 1.0);
        const colorFill  = hexToRgba(color, 1.0);

        const regular = [], ulPts = [], starPts = [];
        items.forEach(pt => {
            const isStar = cfg.starIndices.has(String(pt.x)) || cfg.starIndices.has(String(pt.rowIdx));
            if (isStar) starPts.push(pt);
            else if (pt.isUL) ulPts.push(pt);
            else regular.push(pt);
        });

        // Merge regular + star into one trace; line (if enabled) connects through ★ points.
        // Per-point symbol/size arrays differentiate star vs normal markers.
        const nonUL = [...regular, ...starPts].sort((a, b) => a.x - b.x);
        if (nonUL.length) {
            const _isStar = pt => cfg.starIndices.has(String(pt.x)) || cfg.starIndices.has(String(pt.rowIdx));
            const t = {
                name: cfg.label, type: 'scatter',
                mode: cfg.showLine ? 'lines+markers' : 'markers',
                x: nonUL.map(p => p.x), y: nonUL.map(p => p.y),
                customdata: nonUL.map(p => p.rowIdx),
                hovertemplate: `<b>${escHtml(cfg.label)}</b><br>x: %{x:.4f}<br>y: %{y:.4f}<extra></extra>`,
                marker: {
                    symbol: nonUL.map(p => _isStar(p) ? 'star' : (cfg.shape || 'circle')),
                    size:   nonUL.map(p => _isStar(p) ? (cfg.starSize || 14) : cfg.markerSize),
                    color:  colorFill,
                    line: { color: colorSolid, width: 1 },
                },
                line: cfg.showLine ? {
                    color: colorSolid, dash: cfg.lineStyle, width: cfg.lineWidth,
                } : undefined,
            };
            const hasYErr = nonUL.some(p => !isNaN(p.yErr));
            const hasXErr = nonUL.some(p => !isNaN(p.xErr));
            if (hasYErr) t.error_y = {
                type: 'data', array: nonUL.map(p => isNaN(p.yErr) ? 0 : p.yErr),
                visible: true, color: colorSolid, thickness: 1.5, width: 4,
            };
            if (hasXErr) t.error_x = {
                type: 'data', array: nonUL.map(p => isNaN(p.xErr) ? 0 : p.xErr),
                visible: true, color: colorSolid, thickness: 1.5, width: 4,
            };
            traces.push(t);
        }

        // Upper limit trace
        if (ulPts.length) {
            traces.push({
                name: cfg.label + ' ' + (cfg.ulLabel || 'upper limit'),
                showlegend: cfg.ulInLegend !== false,
                type: 'scatter', mode: 'markers',
                x: ulPts.map(p => p.x), y: ulPts.map(p => p.y),
                hovertemplate: `<b>UL</b><br>x: %{x:.4f}<br>y ≤ %{y:.4f}<extra></extra>`,
                marker: {
                    symbol: 'triangle-down-open', size: cfg.markerSize + 3,
                    color: hexToRgba(color, 0.45),
                    line: { color: colorSolid, width: 1.5 },
                },
            });
        }
    });

    // Dummy traces to force secondary axes to render
    const topX   = getTopXMode();
    const rightY = getRightYMode();
    if (topX !== 'none') {
        traces.push({
            type: 'scatter', mode: 'markers', x: [null], y: [null],
            xaxis: 'x2', yaxis: 'y',
            showlegend: false, hoverinfo: 'skip',
            marker: { opacity: 0, size: 1 },
        });
    }
    if (rightY !== 'none') {
        traces.push({
            type: 'scatter', mode: 'markers', x: [null], y: [null],
            xaxis: 'x', yaxis: 'y2',
            showlegend: false, hoverinfo: 'skip',
            marker: { opacity: 0, size: 1 },
        });
    }

    return traces;
}

// ─── Build Layout ─────────────────────────────────────────────────
function buildLayout() {
    const topX   = getTopXMode();
    const rightY = getRightYMode();
    const invertY  = document.getElementById('invertY').checked;
    const invertX  = document.getElementById('invertX').checked;
    const logX     = document.getElementById('logX').checked;
    const logY     = document.getElementById('logY').checked;
    const showGrid = document.getElementById('showGrid').checked;
    const title    = document.getElementById('plotTitle').value;

    const titleSize = parseInt(document.getElementById('staticTitleSize').value) || 16;
    const axisSize  = parseInt(document.getElementById('staticAxisSize').value)  || 13;
    const tickSize  = parseInt(document.getElementById('staticTickSize').value)  || 11;
    const xTickInt  = parseFloat(document.getElementById('xTickInterval').value) || null;
    const yTickInt  = parseFloat(document.getElementById('yTickInterval')?.value) || null;

    const xColName = document.getElementById('xCol').value;
    const yColName = document.getElementById('yCol').value;
    const xLabel   = document.getElementById('xLabel').value || xColName;
    const yLabel   = document.getElementById('yLabel').value || yColName;

    const isWhiteBg = (document.getElementById('liveBgColor')?.value || 'dark') === 'white';
    const axisStyle = isWhiteBg ? {
        gridcolor:     showGrid ? 'rgba(0,0,0,0.12)' : 'rgba(0,0,0,0)',
        zerolinecolor: 'rgba(0,0,0,0.25)',
        linecolor:     'rgba(0,0,0,0.25)',
        tickcolor:     'rgba(0,0,0,0.35)',
        tickfont:      { color: '#333333', size: tickSize },
        titlefont:     { color: '#111111', size: axisSize },
        showgrid: showGrid,
        exponentformat: 'none',
    } : {
        gridcolor:     showGrid ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0)',
        zerolinecolor: 'rgba(255,255,255,0.15)',
        linecolor:     'rgba(255,255,255,0.2)',
        tickcolor:     'rgba(255,255,255,0.25)',
        tickfont:      { color: '#ccccdd', size: tickSize },
        titlefont:     { color: '#ddddee', size: axisSize },
        showgrid: showGrid,
        exponentformat: 'none',
    };

    const marginTop    = (topX !== 'none') ? (title ? 92 : 62) : (title ? 50 : 28);
    const marginRight  = (rightY !== 'none') ? 80 : 30;

    const layout = {
        title: title ? { text: title, font: { color: isWhiteBg ? '#111111' : '#e8e8f0', size: titleSize, family: 'Inter, sans-serif' }, pad: { t: 8 } } : undefined,
        paper_bgcolor: isWhiteBg ? '#ffffff' : 'rgba(0,0,0,0)',
        plot_bgcolor:  isWhiteBg ? '#ffffff' : 'rgba(18,18,32,0.5)',
        font: { color: isWhiteBg ? '#333333' : '#ccccdd', family: 'Inter, sans-serif', size: tickSize },
        xaxis: {
            title: { text: xLabel, standoff: 10 },
            type: logX ? 'log' : 'linear',
            autorange: invertX ? 'reversed' : true,
            ...(xTickInt && !logX ? { dtick: xTickInt, tickmode: 'linear' } : {}),
            ...axisStyle,
        },
        yaxis: {
            title: { text: yLabel, standoff: 10 },
            autorange: invertY ? 'reversed' : true,
            type: logY ? 'log' : 'linear',
            ...(yTickInt && !logY ? { dtick: yTickInt, tickmode: 'linear' } : {}),
            ...axisStyle,
        },
        legend: _getLegendPos(tickSize),
        margin: {
            l: 70,
            r: document.getElementById('legendPos').value === 'out-r' ? Math.max(marginRight, 160) : marginRight,
            t: marginTop,
            b: document.getElementById('legendPos').value === 'out-b' ? 130 : 60,
        },
        hovermode: 'closest',
        hoverlabel: {
            bgcolor: 'rgba(20,20,35,0.9)', bordercolor: 'rgba(197,160,89,0.5)',
            font: { color: '#e8e8f0', size: tickSize },
        },
    };

    const secAxisStyle = {
        showgrid: false, zeroline: false,
        linecolor: isWhiteBg ? 'rgba(0,0,0,0.25)'   : 'rgba(197,160,89,0.4)',
        tickcolor: isWhiteBg ? 'rgba(0,0,0,0.3)'    : 'rgba(197,160,89,0.4)',
        tickfont:  { color: isWhiteBg ? '#333333' : 'rgba(197,160,89,0.8)', size: tickSize },
        titlefont: { color: isWhiteBg ? '#111111' : 'rgba(197,160,89,0.8)', size: axisSize },
    };

    if (topX === 'phase') {
        const phUnit = document.getElementById('phaseUnit')?.value || 'days';
        const phLabel = phUnit === 'years' ? 'Phase (years from explosion)' : 'Phase (days from explosion)';
        layout.xaxis2 = {
            overlaying: 'x', side: 'top',
            title: { text: phLabel, standoff: 8 },
            autorange: false, range: [0, 1],
            ...secAxisStyle,
        };
    } else if (topX === 'date') {
        layout.xaxis2 = {
            overlaying: 'x', side: 'top', type: 'date',
            title: { text: 'Date', standoff: 8 },
            autorange: false, range: ['2000-01-01', '2000-01-02'],
            ...secAxisStyle,
        };
    } else if (topX.startsWith('col:')) {
        const colName = topX.slice(4);
        layout.xaxis2 = {
            overlaying: 'x', side: 'top',
            title: { text: colName, standoff: 8 },
            autorange: false, range: [0, 1],
            ...secAxisStyle,
        };
    }

    if (rightY === 'absmag') {
        layout.yaxis2 = {
            overlaying: 'y', side: 'right',
            title: { text: 'Absolute Magnitude', standoff: 8 },
            autorange: false, range: [0, 1],
            showgrid: false, zeroline: false,
            linecolor: isWhiteBg ? 'rgba(0,0,0,0.25)'  : 'rgba(79,195,247,0.4)',
            tickcolor: isWhiteBg ? 'rgba(0,0,0,0.3)'   : 'rgba(79,195,247,0.4)',
            tickfont:  { color: isWhiteBg ? '#333333' : 'rgba(79,195,247,0.8)', size: tickSize },
            titlefont: { color: isWhiteBg ? '#111111' : 'rgba(79,195,247,0.8)', size: axisSize },
        };
    } else if (rightY.startsWith('col:')) {
        const colName = rightY.slice(4);
        layout.yaxis2 = {
            overlaying: 'y', side: 'right',
            title: { text: colName, standoff: 8 },
            autorange: false, range: [0, 1],
            showgrid: false, zeroline: false,
            linecolor: isWhiteBg ? 'rgba(0,0,0,0.25)'  : 'rgba(79,195,247,0.4)',
            tickcolor: isWhiteBg ? 'rgba(0,0,0,0.3)'   : 'rgba(79,195,247,0.4)',
            tickfont:  { color: isWhiteBg ? '#333333' : 'rgba(79,195,247,0.8)', size: tickSize },
            titlefont: { color: isWhiteBg ? '#111111' : 'rgba(79,195,247,0.8)', size: axisSize },
        };
    }

    return layout;
}

// ─── Sync Secondary Axes ──────────────────────────────────────────
function syncSecondaryAxes() {
    if (_syncing) return;
    const gd = document.getElementById('plotlyDiv');
    if (!gd._fullLayout) return;

    const updates = {};
    const topX   = getTopXMode();
    const rightY = getRightYMode();

    if (topX === 'phase') {
        const t0 = getExplosionMJD();
        if (t0 !== null) {
            const xr    = gd._fullLayout.xaxis.range;
            const scale = (document.getElementById('phaseUnit')?.value || 'days') === 'years' ? 1 / 365.25 : 1;
            updates['xaxis2.range']     = [(xr[0] - t0) * scale, (xr[1] - t0) * scale];
            updates['xaxis2.autorange'] = false;
        }
    } else if (topX === 'date') {
        const xr = gd._fullLayout.xaxis.range;
        const mjdColName = document.getElementById('dateXMJDCol').value;
        const xColName   = document.getElementById('xCol').value;
        let d0, d1;
        if (mjdColName && mjdColName !== xColName) {
            // Convert via interpolation: bottomX → MJD col → date
            const interp = buildColInterp(xColName, mjdColName);
            if (interp) {
                d0 = mjdToISODate(interp(xr[0]));
                d1 = mjdToISODate(interp(xr[1]));
            }
        } else {
            // Bottom X is already MJD
            d0 = mjdToISODate(xr[0]);
            d1 = mjdToISODate(xr[1]);
        }
        if (d0 && d1) {
            updates['xaxis2.range']     = [d0, d1];
            updates['xaxis2.autorange'] = false;
        }
    } else if (topX.startsWith('col:')) {
        const colName  = topX.slice(4);
        const xColName = document.getElementById('xCol').value;
        const interp   = buildColInterp(xColName, colName);
        if (interp) {
            const xr = gd._fullLayout.xaxis.range;
            updates['xaxis2.range']     = [interp(xr[0]), interp(xr[1])];
            updates['xaxis2.autorange'] = false;
        }
    }

    if (rightY === 'absmag') {
        const mu = getDistanceModulus();
        const yr = gd._fullLayout.yaxis.range;
        updates['yaxis2.range']     = [yr[0] - mu, yr[1] - mu];
        updates['yaxis2.autorange'] = false;
    } else if (rightY.startsWith('col:')) {
        const colName  = rightY.slice(4);
        const yColName = document.getElementById('yCol').value;
        const interp   = buildColInterp(yColName, colName);
        if (interp) {
            const yr = gd._fullLayout.yaxis.range;
            updates['yaxis2.range']     = [interp(yr[0]), interp(yr[1])];
            updates['yaxis2.autorange'] = false;
        }
    }

    if (Object.keys(updates).length > 0) {
        _syncing = true;
        Plotly.relayout('plotlyDiv', updates).then(() => { _syncing = false; });
    }
}

// ─── Render Plot ──────────────────────────────────────────────────
function renderPlot() {
    if (!parsedData) { showToast('Upload a data file first', 'warn'); return; }
    if (!document.getElementById('xCol').value || !document.getElementById('yCol').value) {
        showToast('Select X and Y columns', 'warn'); return;
    }

    const traces = buildTraces();
    const realTraces = traces.filter(t => t.hoverinfo !== 'skip' && t.x && t.x[0] !== null);
    if (!realTraces.length) { showToast('No visible data to plot', 'warn'); return; }

    const layout = buildLayout();
    const config = {
        responsive: true, displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toImage'],
        displaylogo: false,
    };

    document.getElementById('plotPlaceholder').style.display = 'none';
    const plotDiv = document.getElementById('plotlyDiv');
    plotDiv.style.display = '';

    Plotly.react('plotlyDiv', traces, layout, config).then(() => {
        plotRendered = true;
        syncSecondaryAxes();
        if (!_eventsAttached) {
            plotDiv.on('plotly_relayout', () => syncSecondaryAxes());
            plotDiv.on('plotly_click', onPlotClick);
            _eventsAttached = true;
        }
        const staticMode = document.querySelector('input[name="previewMode"]:checked')?.value === 'static';
        const staticImg  = document.getElementById('staticPreviewImg');
        const noteEl     = document.getElementById('previewNote');
        if (staticMode && staticImg) {
            _renderStaticPreview(staticImg, plotDiv, noteEl);
        } else {
            if (staticImg) staticImg.style.display = 'none';
            if (noteEl) noteEl.style.display = '';
        }
    });
}

function onPreviewModeChange() {
    if (!plotRendered) return;
    renderPlot();
}

// Build a static preview using the same pipeline as doExport
async function _renderStaticPreview(imgEl, livePlotDiv, noteEl) {
    const bg     = document.getElementById('plotBgColor').value;
    const traces = buildTraces();
    const layout = buildLayout();
    _syncRangesFromLive(layout);
    _applyExportTheme(layout, bg);

    const tmpDiv = document.createElement('div');
    tmpDiv.style.cssText = 'position:fixed;left:-9999px;top:0;width:1600px;height:900px;';
    document.body.appendChild(tmpDiv);
    try {
        await Plotly.newPlot(tmpDiv, traces, layout, { staticPlot: true, responsive: false });
        const url = await Plotly.toImage(tmpDiv, { format: 'png', width: 1600, height: 900, scale: 2 });
        imgEl.src = url;
        imgEl.style.display = '';
        livePlotDiv.style.display = 'none';
        if (noteEl) noteEl.style.display = 'none';
    } finally {
        Plotly.purge(tmpDiv);
        document.body.removeChild(tmpDiv);
    }
}

// ─── Click to Toggle Star ─────────────────────────────────────────
function onPlotClick(eventData) {
    if (!eventData || !eventData.points.length) return;
    const pt  = eventData.points[0];
    const rowIdx = pt.customdata;
    if (rowIdx === undefined) return;
    const traceName = pt.data.name;
    const cfg = seriesList.find(s => s.label === traceName);
    if (!cfg) return;
    const key = String(rowIdx);
    if (cfg.starIndices.has(key)) cfg.starIndices.delete(key);
    else cfg.starIndices.add(key);
    renderSeriesManager();
    renderPlot();
    showToast(cfg.starIndices.has(key) ? '★ Marked as star' : '☆ Unmarked', 'ok');
}

// ─── Column Change Handlers ────────────────────────────────────────
function onColumnChange() {
    const xCol = document.getElementById('xCol').value;
    const yCol = document.getElementById('yCol').value;
    const xLbl = document.getElementById('xLabel');
    const yLbl = document.getElementById('yLabel');
    if (xCol && !xLbl.value) xLbl.placeholder = xCol;
    if (yCol && !yLbl.value) yLbl.placeholder = yCol;
}

function onGroupChange() {
    updateSeries();
    const fc = document.getElementById('lcFilterCol').value;
    const gc = document.getElementById('groupCol').value;
    if (gc && !fc) document.getElementById('lcFilterCol').value = gc;
}

function toggleUpperLimit() {
    document.getElementById('lcULOpts').style.display =
        document.getElementById('lcUpperLimit').checked ? '' : 'none';
    renderSeriesManager();
}

function toggleMWExt() {
    document.getElementById('lcMWExtOpts').style.display =
        document.getElementById('lcMWExt').checked ? '' : 'none';
    renderSeriesManager();
}

async function autoFillMWExt() {
    const ra  = parseFloat(document.getElementById('mwExtRA').value);
    const dec = parseFloat(document.getElementById('mwExtDec').value);
    if (isNaN(ra) || isNaN(dec)) { showToast('Enter RA and Dec first', 'warn'); return; }
    const filters = [...new Set(seriesList.map(s => s.groupVal).filter(g => g !== '__all__'))];
    if (!filters.length) { showToast('No filter names to query (need group-by filter col)', 'warn'); return; }
    const btn = document.getElementById('mwExtAutoBtn');
    btn.disabled = true; btn.textContent = 'Querying…';
    try {
        const resp = await fetch('/lc_plotter/mw_extinction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ra, dec, filters }),
        });
        const result = await resp.json();
        if (result.error) { showToast('Server: ' + result.error, 'error'); return; }
        let filled = 0;
        seriesList.forEach(s => {
            if (s.groupVal in result && result[s.groupVal] !== null) {
                s.mwExt = result[s.groupVal];
                filled++;
            }
        });
        renderSeriesManager();
        showToast(`Filled ${filled} filter(s) with MW extinction`, 'ok');
    } catch (err) {
        showToast('MW extinction request failed', 'error');
    } finally {
        btn.disabled = false; btn.textContent = 'Auto-fill by coord';
    }
}

function onULModeChange() {
    const mode = document.getElementById('lcULMode').value;
    document.getElementById('lcULFlagOpts').style.display   = mode === 'flag'   ? '' : 'none';
    document.getElementById('lcULDirectOpts').style.display = mode === 'direct' ? '' : 'none';
}

function toggleFilterSection() {
    const body = document.getElementById('filterCollapseBody');
    const icon = document.getElementById('filterCollapseIcon');
    const isOpen = body.style.display !== 'none';
    body.style.display = isOpen ? 'none' : '';
    icon.style.transform = isOpen ? 'rotate(-90deg)' : 'rotate(0deg)';
}

function resetSeries() {
    seriesList = [];
    updateSeries();
}

function toggleAllLines() {
    if (!seriesList.length) return;
    // If any series has line off, turn all on; else turn all off
    const anyOff = seriesList.some(s => !s.showLine);
    seriesList.forEach(s => { s.showLine = anyOff; });
    renderSeriesManager();
    const btn = document.getElementById('allLinesBtn');
    if (btn) btn.textContent = anyOff ? '─ All Lines' : '◯ All Lines';
}

// ─── Legend position helper ─────────────────────────────────────
function _getLegendPos(tickSize) {
    const pos = document.getElementById('legendPos').value;
    const base = {
        borderwidth: 1,
        font: { color: '#ccccdd', size: tickSize },
        itemsizing: 'constant',
    };
    switch (pos) {
        case 'in-tl': return { ...base, x: 0.01, y: 0.99, xanchor: 'left',   yanchor: 'top',    bgcolor: 'rgba(0,0,0,0.5)',  bordercolor: 'rgba(255,255,255,0.15)' };
        case 'in-br': return { ...base, x: 0.99, y: 0.01, xanchor: 'right',  yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0.5)',  bordercolor: 'rgba(255,255,255,0.15)' };
        case 'in-bl': return { ...base, x: 0.01, y: 0.01, xanchor: 'left',   yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0.5)',  bordercolor: 'rgba(255,255,255,0.15)' };
        case 'out-r': return { ...base, x: 1.02, y: 0.5,  xanchor: 'left',   yanchor: 'middle', bgcolor: 'rgba(0,0,0,0)',    bordercolor: 'rgba(0,0,0,0)' };
        case 'out-b': return { ...base, x: 0.5,  y: -0.18, xanchor: 'center', yanchor: 'top',   bgcolor: 'rgba(0,0,0,0)',    bordercolor: 'rgba(0,0,0,0)', orientation: 'h' };
        default:      return { ...base, x: 0.99, y: 0.99, xanchor: 'right',  yanchor: 'top',    bgcolor: 'rgba(0,0,0,0.5)',  bordercolor: 'rgba(255,255,255,0.15)' };
    }
}

// ─── Export theme helper ──────────────────────────────────────────
function _applyExportTheme(layout, bg) {
    const tickSz = layout.xaxis.tickfont.size;
    const axisSz = layout.xaxis.titlefont.size;
    if (bg === 'white') {
        layout.paper_bgcolor = '#ffffff';
        layout.plot_bgcolor  = '#ffffff';
        layout.font          = { ...layout.font, color: '#1a1a2e' };
        if (layout.title) layout.title.font.color = '#111';
        layout.legend = { ...layout.legend, bgcolor: 'rgba(255,255,255,0.9)',
            bordercolor: 'rgba(0,0,0,0.15)', font: { color: '#222', size: layout.legend.font.size } };
        const lightAxis = {
            gridcolor: 'rgba(0,0,0,0.1)', zerolinecolor: 'rgba(0,0,0,0.25)',
            linecolor: 'rgba(0,0,0,0.4)', tickcolor: 'rgba(0,0,0,0.4)',
            tickfont: { color: '#333', size: tickSz }, titlefont: { color: '#222', size: axisSz },
            exponentformat: 'none',
        };
        ['xaxis','yaxis','xaxis2','yaxis2'].forEach(ax => { if (layout[ax]) Object.assign(layout[ax], lightAxis); });
        layout.margin = { l: 80, r: (layout.margin.r || 30) + 20, t: (layout.margin.t || 28) + 10, b: Math.max(72, layout.margin.b || 0) };
    } else {
        layout.paper_bgcolor = '#0d0d1a';
        layout.plot_bgcolor  = '#12121e';
    }
}

// ─── Get secondary axis ranges from live plot ──────────────────────
function _syncRangesFromLive(layout) {
    const gd = document.getElementById('plotlyDiv');
    if (!gd || !gd._fullLayout) return;
    if (layout.xaxis2 && gd._fullLayout.xaxis2) layout.xaxis2.range = [...gd._fullLayout.xaxis2.range];
    if (layout.yaxis2 && gd._fullLayout.yaxis2) layout.yaxis2.range = [...gd._fullLayout.yaxis2.range];
}

// ─── Export ───────────────────────────────────────────────────────
async function doExport(format) {
    const bg   = document.getElementById('plotBgColor').value;
    const name = (document.getElementById('plotTitle').value || 'lc_plot').replace(/\s+/g, '_');
    const traces = buildTraces();
    const layout = buildLayout();
    _syncRangesFromLive(layout);
    _applyExportTheme(layout, bg);

    const tmpDiv = document.createElement('div');
    tmpDiv.style.cssText = 'position:fixed;left:-9999px;top:0;width:1px;height:1px;';
    document.body.appendChild(tmpDiv);
    try {
        await Plotly.newPlot(tmpDiv, traces, layout, { staticPlot: true, responsive: false });
        await Plotly.downloadImage(tmpDiv, { format, width: 1600, height: 900, filename: name });
    } finally {
        Plotly.purge(tmpDiv);
        document.body.removeChild(tmpDiv);
    }
}

// ─── Share ────────────────────────────────────────────────────────
async function shareChart(isStatic) {
    if (!plotRendered) { showToast('Render a plot first', 'warn'); return; }
    const bg     = document.getElementById('plotBgColor').value;
    const traces = buildTraces();
    const layout = buildLayout();
    _syncRangesFromLive(layout);
    if (isStatic) _applyExportTheme(layout, bg);

    showToast('Creating link…', 'ok');
    try {
        const resp = await fetch('/lc_plotter/share', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ traces, layout, isStatic }),
        });
        if (!resp.ok) throw new Error(`Server error ${resp.status}`);
        const { id } = await resp.json();
        const url = `${location.origin}/lc_plotter/shared/${id}`;
        try { await navigator.clipboard.writeText(url); } catch (_) {}
        window.open(url, '_blank');
        showToast('Link copied & opened!', 'ok');
    } catch (e) {
        showToast('Share failed: ' + e.message, 'error');
    }
}
function exportPNG() {
    if (!plotRendered) { showToast('Render a plot first', 'warn'); return; }
    doExport('png');
}
function exportSVG() {
    if (!plotRendered) { showToast('Render a plot first', 'warn'); return; }
    doExport('svg');
}
function exportCSV() {
    if (!parsedData) { showToast('No data loaded', 'warn'); return; }
    const lines = [parsedData.headers.join(',')];
    parsedData.rows.forEach(r => lines.push(r.map(v => `"${v}"`).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (parsedData.filename || 'data') + '_export.csv';
    a.click();
    URL.revokeObjectURL(a.href);
}

// ─── DAT Export / Settings Save ──────────────────────────────────
function _getEl(id) { return document.getElementById(id); }
function _elVal(id) {
    const el = _getEl(id);
    if (!el) return undefined;
    return el.type === 'checkbox' ? String(el.checked) : el.value;
}
function collectSettings() {
    const s = {};
    [
        'plotTitle','xLabel','yLabel',
        'invertY','invertX','logX','logY','showGrid',
        'xCol','xErrCol','yCol','yErrCol','magErrCol','groupCol','lcFilterCol',
        'lcUpperLimit','lcULMode','lcULFlagCol','lcULFlagVal','lcULMagCol','lcULLimCol',
        'lcMWExt','mwExtRA','mwExtDec',
        'topXMode','lcExpMJD','phaseUnit','dateXMJDCol',
        'rightYMode','lcRedshift',
        'staticTitleSize','staticAxisSize','staticTickSize','xTickInterval','yTickInterval',
        'plotBgColor','liveBgColor','legendPos',
    ].forEach(id => { const v = _elVal(id); if (v != null) s[id] = v; });
    s._series = JSON.stringify(seriesList.map(ss => ({
        groupVal: ss.groupVal, label: ss.label, color: ss.color,
        shape: ss.shape, showLine: ss.showLine, lineStyle: ss.lineStyle,
        lineWidth: ss.lineWidth, markerSize: ss.markerSize, starSize: ss.starSize,
        starIndices: [...ss.starIndices], ulLabel: ss.ulLabel, ulInLegend: ss.ulInLegend,
        mwExt: ss.mwExt, visible: ss.visible,
    })));
    return s;
}
function _applySettingsUI(s) {
    const set = (id, val) => {
        if (val === undefined || val === null) return;
        const el = _getEl(id);
        if (!el) return;
        if (el.type === 'checkbox') el.checked = (val === 'true' || val === true);
        else el.value = val;
    };
    [
        'plotTitle','xLabel','yLabel',
        'invertY','invertX','logX','logY','showGrid',
        'xCol','xErrCol','yCol','yErrCol','magErrCol','groupCol','lcFilterCol',
        'lcULMode','lcULFlagCol','lcULFlagVal','lcULMagCol','lcULLimCol',
        'mwExtRA','mwExtDec',
        'topXMode','lcExpMJD','phaseUnit','dateXMJDCol',
        'rightYMode','lcRedshift',
        'staticTitleSize','staticAxisSize','staticTickSize','xTickInterval','yTickInterval',
        'plotBgColor','liveBgColor','legendPos',
    ].forEach(id => set(id, s[id]));
    // toggles that show/hide sub-panels
    set('lcUpperLimit', s.lcUpperLimit);
    if (s.lcUpperLimit === 'true') toggleUpperLimit();
    set('lcMWExt', s.lcMWExt);
    if (s.lcMWExt === 'true') toggleMWExt();
    if (s.topXMode && s.topXMode !== 'none')    { set('topXMode', s.topXMode);   onTopXChange(); }
    if (s.rightYMode && s.rightYMode !== 'none') { set('rightYMode', s.rightYMode); onRightYChange(); }
    if (s.lcULMode) onULModeChange();
}
function _applySettingsSeries(s) {
    if (!s._series) return;
    try {
        const saved = JSON.parse(s._series);
        saved.forEach(ss => {
            const found = seriesList.find(x => x.groupVal === ss.groupVal);
            if (!found) return;
            Object.assign(found, ss);
            found.starIndices = new Set(ss.starIndices || []);
        });
        renderSeriesManager();
    } catch (_) {}
}
function exportDAT() {
    if (!parsedData) { showToast('Load data first', 'warn'); return; }
    const s = collectSettings();
    const settingLines = Object.entries(s).map(([k, v]) => `#setting_${k}:${v}`);
    const dataLines = [parsedData.headers.join('\t')];
    parsedData.rows.forEach(r => dataLines.push(r.join('\t')));
    const content = settingLines.join('\n') + '\n' + dataLines.join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const a = document.createElement('a');
    const base = (parsedData.filename || 'data').replace(/\.[^.]+$/, '');
    a.download = base + '.dat';
    a.href = URL.createObjectURL(blob);
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('Saved ' + a.download, 'ok');
}
// ─── Utilities ────────────────────────────────────────────────────
function hexToRgba(hex, alpha) {
    if (!hex) return `rgba(128,128,128,${alpha})`;
    if (hex.startsWith('rgba(')) return hex.replace(/[\d.]+\)$/, `${alpha})`);
    if (hex.startsWith('rgb('))  return hex.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`);
    const r = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return r
        ? `rgba(${parseInt(r[1],16)},${parseInt(r[2],16)},${parseInt(r[3],16)},${alpha})`
        : `rgba(128,128,128,${alpha})`;
}
function colorToHex(color) {
    if (!color) return '#888888';
    if (color.startsWith('#') && color.length === 7) return color;
    if (color.startsWith('#') && color.length === 4)
        return '#' + color.slice(1).split('').map(c => c+c).join('');
    const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (m) return '#' + [m[1],m[2],m[3]].map(x => (+x).toString(16).padStart(2,'0')).join('');
    return '#888888';
}
function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(msg, type = 'ok') {
    const el = document.getElementById('lcpToast');
    el.textContent = msg;
    el.className = 'lcp-toast lcp-toast-' + type + ' lcp-toast-show';
    clearTimeout(el._timeout);
    el._timeout = setTimeout(() => el.classList.remove('lcp-toast-show'), 2500);
}

// ─── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const dropZone  = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) parseFile(file);
    });
    fileInput.addEventListener('change', e => { if (e.target.files[0]) parseFile(e.target.files[0]); });
    document.getElementById('lcUpperLimit').addEventListener('change', toggleUpperLimit);
});
