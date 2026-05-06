const epState = {
    targets: [],
    selectedIndex: -1,
    summary: null,
    batches: [],
    typeOptions: [],
    reportingGroupByTarget: {}
};

const PHASE_OPTIONS = ['Pre-Peak', 'Around Peak', 'Post-Peak'];
const FALLBACK_TYPE_OPTIONS = ['AT', 'SN Ia', 'SN II', 'SN Ib/c'];

function prioritizeSTypeOptions(options) {
    const list = Array.isArray(options) ? options : [];
    const sFirst = [];
    const others = [];

    list.forEach((item) => {
        const text = String(item || '');
        if (/^s/i.test(text.trim())) {
            sFirst.push(item);
        } else {
            others.push(item);
        }
    });

    return sFirst.concat(others);
}

const epUploadBtn = document.getElementById('epUploadBtn');
const epFileInput = document.getElementById('epFileInput');
const epPreviewBtn = document.getElementById('epPreviewBtn');
const epRefreshBtn = document.getElementById('epRefreshBtn');
const epAutoRefreshToggle = document.getElementById('epAutoRefreshToggle');
let autoRefreshTimer = null;

function startAutoRefresh() {
    if (autoRefreshTimer) return;
    autoRefreshTimer = setInterval(async () => {
        await loadSession({ refreshWidget: false });
    }, 10000);
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}
const epClearBtn = document.getElementById('epClearBtn');
const epPrevBtn = document.getElementById('epPrevBtn');
const epNextBtn = document.getElementById('epNextBtn');
const epRemoveTargetBtn = document.getElementById('epRemoveTargetBtn');
const epCounter = document.getElementById('epCounter');
const epTypeSummary = document.getElementById('epTypeSummary');
const epStatus = document.getElementById('epStatus');
const epTargetList = document.getElementById('epTargetList');
const epTargetWidget = document.getElementById('epTargetWidget');

function setStatus(message) {
    epStatus.textContent = message;
}

function updateActionButtons() {
    const hasTarget = epState.targets.length > 0;
    epPreviewBtn.disabled = !hasTarget;
    epClearBtn.disabled = !hasTarget;
    epPrevBtn.disabled = !hasTarget || epState.selectedIndex <= 0;
    epNextBtn.disabled = !hasTarget || epState.selectedIndex >= epState.targets.length - 1;
    epRemoveTargetBtn.disabled = !hasTarget || epState.selectedIndex < 0;
}

function updateCounter() {
    const done = epState.summary ? epState.summary.done_targets : 0;
    const total = epState.summary ? epState.summary.total_targets : 0;
    epCounter.textContent = `${done} / ${total}`;
    updateTypeSummary();
}

function getTypeCounts() {
    const counts = {};
    epState.targets.forEach((t) => {
        const type = ((t.user_fields && t.user_fields.type) || '').trim() || 'Unknown';
        counts[type] = (counts[type] || 0) + 1;
    });
    return counts;
}

function updateTypeSummary() {
    if (!epTypeSummary) return;
    const counts = getTypeCounts();
    const items = Object.entries(counts)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([k, v]) => `${k} x${v}`);
    epTypeSummary.textContent = items.length ? items.join(' | ') : 'Type: -';
}

function mmFitContain(imgW, imgH, boxW, boxH) {
    if (!imgW || !imgH) return { w: boxW, h: boxH, x: 0, y: 0 };
    const scale = Math.min(boxW / imgW, boxH / imgH);
    const w = imgW * scale;
    const h = imgH * scale;
    return { w, h, x: (boxW - w) / 2, y: (boxH - h) / 2 };
}

async function imageToDataUrl(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('image fetch failed');
    const blob = await resp.blob();
    return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

async function loadTargetImagesForPdf(target) {
    const fields = normalizeUserFields(target.user_fields);
    const imgs = (fields.images || []).slice(0, 4);
    const out = [];
    for (const item of imgs) {
        const filename = String(item.filename || '').trim();
        if (!filename) continue;
        const url = '/api/epessto_support/image/' + encodeURIComponent(filename);
        try {
            const dataUrl = await imageToDataUrl(url);
            const img = await new Promise((resolve, reject) => {
                const i = new Image();
                i.onload = () => resolve(i);
                i.onerror = reject;
                i.src = dataUrl;
            });
            out.push({ dataUrl, width: img.naturalWidth, height: img.naturalHeight });
        } catch (_) {}
    }
    return out;
}

function drawSummaryPages(doc) {
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const left = 10;
    const right = pageW - 10;

    const counts = getTypeCounts();
    const countText = Object.entries(counts)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([k, v]) => `${k} x${v}`)
        .join(' | ') || 'No type data';

    doc.setFontSize(16);
    doc.text('ePessto++ Support Report', left, 14);
    doc.setFontSize(10);
    const d = epState.summary ? epState.summary.today_date : new Date().toISOString().slice(0, 10);
    doc.text(`Date: ${d}`, left, 20);
    doc.text(`Done/Total: ${(epState.summary && epState.summary.done_targets) || 0}/${(epState.summary && epState.summary.total_targets) || 0}`, left, 25);
    doc.text(`Type Count: ${countText}`, left, 30, { maxWidth: right - left });

    const cols = [
        { key: 'name', label: 'Name', w: 32 },
        { key: 'host', label: 'Host', w: 36 },
        { key: 'type', label: 'Type', w: 24 },
        { key: 'phase', label: 'Phase', w: 26 },
        { key: 'app', label: 'Classification Method', w: 42 },
        { key: 'z_est', label: 'Estimate z', w: 16 },
        { key: 'z_host', label: 'Host z', w: 16 }
    ];

    let y = 38;
    const rowH = 7;
    const fitCellText = (rawText, innerW, baseSize, minSize) => {
        const maxW = Math.max(innerW, 2);
        const original = String(rawText || '-');
        let text = original;
        let size = baseSize;

        doc.setFontSize(size);
        while (size > minSize && doc.getTextWidth(text) > maxW) {
            size = Math.max(minSize, size - 0.2);
            doc.setFontSize(size);
        }

        if (doc.getTextWidth(text) > maxW) {
            while (text.length > 1 && doc.getTextWidth(text + '...') > maxW) {
                text = text.slice(0, -1);
            }
            text = text.length < original.length ? (text + '...') : text;
        }

        return { text, size };
    };

    const drawCellText = (text, x, y0, w, baseSize, minSize) => {
        const innerW = w - 2.4;
        const fitted = fitCellText(text, innerW, baseSize, minSize);
        doc.setFontSize(fitted.size);
        doc.text(fitted.text, x + 1.2, y0 + 4.7);
    };

    const drawHeader = () => {
        let x = left;
        cols.forEach((c) => {
            doc.rect(x, y, c.w, rowH);
            drawCellText(c.label, x, y, c.w, 8, 6.2);
            x += c.w;
        });
        y += rowH;
    };

    drawHeader();
    epState.targets.forEach((t) => {
        if (y + rowH > pageH - 10) {
            doc.addPage();
            y = 12;
            drawHeader();
        }
        const f = normalizeUserFields(t.user_fields);
        const nameDisplay = t.is_discuss ? `${t.target_name} (Discussion)` : t.target_name;
        const values = {
            name: nameDisplay,
            host: f.host,
            type: f.type,
            phase: f.phase,
            app: f.app,
            z_est: f.z_estimate,
            z_host: f.z_from_host
        };
        const isDiscussRow = Boolean(t.is_discuss);
        if (isDiscussRow) doc.setTextColor(180, 60, 60);
        let x = left;
        cols.forEach((c) => {
            doc.rect(x, y, c.w, rowH);
            const txt = String(values[c.key] || '-');
            drawCellText(txt, x, y, c.w, 7.5, 5.2);
            x += c.w;
        });
        if (isDiscussRow) doc.setTextColor(0, 0, 0);
        y += rowH;
    });
}

async function drawTargetPage(doc, target) {
    doc.addPage();
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const left = 10;
    const right = pageW - 10;

    const f = normalizeUserFields(target.user_fields);
    doc.setFontSize(15);
    doc.text(target.target_name, left, 14);
    doc.setFontSize(10);
    doc.text(`Type: ${f.type || '-'}`, left, 20);
    doc.text(`Phase: ${f.phase || '-'}`, left, 25);
    doc.text(`Estimate z: ${f.z_estimate || '-'} / Host z: ${f.z_from_host || '-'}`, left, 30);

    const top = 36;
    const bottom = pageH - 10;
    const areaW = right - left;
    const areaH = bottom - top;
    const gap = 4;

    const images = await loadTargetImagesForPdf(target);
    if (!images.length) {
        doc.setFontSize(11);
        doc.text('No images', left, top + 6);
        return;
    }

    const place = (img, x, y, w, h) => {
        const fit = mmFitContain(img.width, img.height, w, h);
        doc.rect(x, y, w, h);
        doc.addImage(img.dataUrl, 'PNG', x + fit.x, y + fit.y, fit.w, fit.h);
    };

    if (images.length === 1) {
        place(images[0], left, top, areaW, areaH);
        return;
    }
    if (images.length === 2 || images.length === 3) {
        const count = images.length;
        const h = (areaH - gap * (count - 1)) / count;
        for (let i = 0; i < count; i += 1) {
            const y = top + i * (h + gap);
            place(images[i], left, y, areaW, h);
        }
        return;
    }

    const w = (areaW - gap) / 2;
    const h = (areaH - gap) / 2;
    for (let i = 0; i < Math.min(images.length, 4); i += 1) {
        const row = Math.floor(i / 2);
        const col = i % 2;
        const x = left + col * (w + gap);
        const y = top + row * (h + gap);
        place(images[i], x, y, w, h);
    }
}

async function generateReportPdf(previewMode) {
    if (!window.jspdf || !window.jspdf.jsPDF) {
        setStatus('PDF library not loaded.');
        return;
    }
    if (!epState.targets.length) {
        setStatus('No targets to export.');
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });

    setStatus('Generating PDF summary...');
    drawSummaryPages(doc);

    for (const t of epState.targets) {
        setStatus('Rendering target page: ' + t.target_name);
        await drawTargetPage(doc, t);
    }

    const dateStr = epState.summary ? epState.summary.today_date : 'today';
    const filename = 'epessto_report_' + dateStr + '.pdf';

    if (previewMode) {
        const blob = doc.output('blob');
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank', 'noopener,noreferrer');
        setStatus('PDF preview opened.');
    } else {
        doc.save(filename);
        setStatus('PDF downloaded.');
    }
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function buildObjectLink(targetName) {
    const normalized = String(targetName || '').trim().replace(/\s+/g, '');
    if (!normalized) return '#';
    return '/object/' + encodeURIComponent(normalized);
}

function getCurrentTargetKey() {
    const current = epState.targets[epState.selectedIndex];
    return current ? current.target_key : null;
}

function normalizeUserFields(fields) {
    const src = fields || {};
    const images = Array.isArray(src.images) ? src.images : [];
    return {
        host: src.host || '',
        z_from_host: src.z_from_host || '',
        z_estimate: src.z_estimate || '',
        type: src.type || '',
        phase: src.phase || '',
        app: src.app || '',
        images,
        completed: Boolean(src.completed),
        discuss: Boolean(src.discuss)
    };
}

function getLcPanelIds(targetKey) {
    return {
        plot: `epLcPlot_${targetKey}`,
        extToggle: `epLcExtToggle_${targetKey}`,
        kcorrToggle: `epLcKCorrToggle_${targetKey}`,
        fetchBtn: `epLcFetchBtn_${targetKey}`,
        refreshBtn: `epLcRefreshBtn_${targetKey}`
    };
}

function extractObjectApiName(rawName) {
    const s = String(rawName || '').trim();
    if (!s) return '';

    const compact = s.replace(/\s+/g, '');
    const m = compact.match(/^(?:AT|SN)?(20\d{2}[a-zA-Z]+)$/i);
    if (m && m[1]) return m[1];
    return compact;
}

async function resolveObjectApiName(targetName) {
    const fallback = extractObjectApiName(targetName);
    try {
        const resp = await fetch('/api/search_target?q=' + encodeURIComponent(targetName));
        const data = await resp.json();
        if (!resp.ok || !data.results || !data.results.length) return fallback;

        const exact = data.results.find(
            r => ((r.prefix || '') + (r.name || '')).replace(/\s+/g, '').toLowerCase() ===
                 String(targetName || '').replace(/\s+/g, '').toLowerCase()
        ) || data.results[0];

        const apiName = extractObjectApiName(exact.name || targetName);
        return apiName || fallback;
    } catch (_) {
        return fallback;
    }
}

async function resolveReportingGroup(targetName) {
    const key = String(targetName || '').trim().toLowerCase();
    if (!key) return '';
    if (Object.prototype.hasOwnProperty.call(epState.reportingGroupByTarget, key)) {
        return epState.reportingGroupByTarget[key] || '';
    }

    let group = '';
    try {
        const resp = await fetch('/api/search_target?q=' + encodeURIComponent(targetName));
        const data = await resp.json();
        if (resp.ok && data.results && data.results.length) {
            const exact = data.results.find(
                r => ((r.prefix || '') + (r.name || '')).replace(/\s+/g, '').toLowerCase() ===
                     String(targetName || '').replace(/\s+/g, '').toLowerCase()
            ) || data.results[0];

            group = String(exact.reporting_group || exact.source_group || '').trim();
        }
    } catch (_) {}

    epState.reportingGroupByTarget[key] = group;
    return group;
}

async function renderTargetLightCurve(target, options = {}) {
    const applyExtinction = options.applyExtinction !== false;
    const applyKCorr = Boolean(options.applyKCorr);
    const ids = getLcPanelIds(target.target_key);
    const plotEl = document.getElementById(ids.plot);
    if (!plotEl) return;

    plotEl.innerHTML = '<div class="ep-lc-hint">Loading light curve...</div>';
    try {
        const objectApiName = await resolveObjectApiName(target.target_name);
        if (!objectApiName) {
            plotEl.innerHTML = '<div class="ep-lc-hint">Invalid target name</div>';
            return;
        }

        const url = '/api/object/' + encodeURIComponent(objectApiName) +
            '/photometry/plot?extinction=' + (applyExtinction ? 'true' : 'false') +
            '&k_corr=' + (applyKCorr ? 'true' : 'false');
        const resp = await fetch(url);
        const data = await resp.json();
        if (!resp.ok || !data.success || !data.plot_json) {
            plotEl.innerHTML = '<div class="ep-lc-hint">No light curve data</div>';
            return;
        }

        let plotJson = data.plot_json;
        if (typeof plotJson === 'string') {
            plotJson = JSON.parse(plotJson);
        }

        if (!window.Plotly) {
            plotEl.innerHTML = '<div class="ep-lc-hint">Plotly not available</div>';
            return;
        }

        const layout = Object.assign({}, plotJson.layout || {}, {
            margin: { l: 44, r: 16, t: 18, b: 34 },
            height: 300,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(255,255,255,0.04)',
            font: Object.assign({}, (plotJson.layout || {}).font || {}, { size: 11 })
        });
        const config = { displayModeBar: false, responsive: true, scrollZoom: false };
        plotEl.innerHTML = '';
        await window.Plotly.react(plotEl, plotJson.data || [], layout, config);
    } catch (_) {
        plotEl.innerHTML = '<div class="ep-lc-hint">Failed to load light curve</div>';
    }
}

async function fetchPhotometryPoints(target, silent = false) {
    if (!silent && !confirm('Fetch photometry for ' + target.target_name + ' from TNS?')) {
        return;
    }
    const objectApiName = await resolveObjectApiName(target.target_name);
    if (!objectApiName) {
        throw new Error('Invalid target name');
    }

    const resp = await fetch('/api/object/' + encodeURIComponent(objectApiName) + '/fetch_photometry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to fetch photometry');
    }
}

function ensureImageModal() {
    let modal = document.getElementById('epImageModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'epImageModal';
    modal.className = 'ep-image-modal';
    modal.innerHTML = `
        <button type="button" class="ep-image-modal-close" data-action="close-image-modal">x</button>
        <img id="epImageModalImg" src="" alt="preview">
    `;
    document.body.appendChild(modal);

    modal.addEventListener('click', (event) => {
        if (event.target === modal || event.target.dataset.action === 'close-image-modal') {
            modal.classList.remove('show');
        }
    });
    return modal;
}

function openImageModal(src) {
    const modal = ensureImageModal();
    const img = document.getElementById('epImageModalImg');
    if (!img) return;
    img.src = src;
    modal.classList.add('show');
}

function renderTargetList() {
    if (!epState.targets.length) {
        epTargetList.innerHTML = '<div class="ep-empty">No targets</div>';
        return;
    }

    const rows = epState.targets.map((target, index) => {
        const activeClass = index === epState.selectedIndex ? 'active' : '';
        const stateClass = target.is_done_today ? 'done' : (target.is_discuss ? 'discuss' : 'pending');
        const typeText = (target.user_fields && target.user_fields.type) ? target.user_fields.type : '';
        return `
            <button class="ep-target-item ${stateClass} ${activeClass}" data-index="${index}" type="button">
                <div class="ep-target-item-name">${escapeHtml(target.target_name)}</div>
                ${typeText ? `<div class="ep-target-item-type">${escapeHtml(typeText)}</div>` : ''}
            </button>
        `;
    });

    epTargetList.innerHTML = rows.join('');

    epTargetList.querySelectorAll('.ep-target-item').forEach((item) => {
        item.addEventListener('click', () => {
            const idx = Number(item.dataset.index);
            if (Number.isFinite(idx)) {
                epState.selectedIndex = idx;
                renderSelectedTarget();
            }
        });
    });
}

function buildWidgetHTML(target, info) {
    const objectLink = buildObjectLink(target.target_name);
    const userFields = normalizeUserFields(target.user_fields);
    const isDone = Boolean(target.is_done_today || userFields.completed);
    const isDiscuss = Boolean(target.is_discuss || userFields.discuss);
    const doneLabel = isDone ? 'cancel done' : 'mark done';
    const discussLabel = isDiscuss ? 'cancel discuss' : 'mark discuss';

    const typeOptionsHtml = ['<option value="">Select Type</option>']
        .concat(epState.typeOptions.map((t) => {
            const selected = userFields.type === t ? ' selected' : '';
            return `<option value="${escapeHtml(t)}"${selected}>${escapeHtml(t)}</option>`;
        }))
        .join('');

    const phaseOptionsHtml = ['<option value="">Select Phase</option>']
        .concat(PHASE_OPTIONS.map((phase) => {
            const selected = userFields.phase === phase ? ' selected' : '';
            return `<option value="${escapeHtml(phase)}"${selected}>${escapeHtml(phase)}</option>`;
        }))
        .join('');

    const imageCards = userFields.images.map((img) => {
        const filename = String(img.filename || '');
        const imgUrl = '/api/epessto_support/image/' + encodeURIComponent(filename);
        return `
            <div class="ep-image-card">
                <img src="${imgUrl}" alt="target image" data-action="open-image" data-src="${imgUrl}">
                <button type="button" class="ep-image-delete" data-action="delete-image" data-target-key="${escapeHtml(target.target_key)}" data-filename="${escapeHtml(filename)}">delete</button>
            </div>
        `;
    }).join('');

    const canUploadMore = userFields.images.length < 4;
    const uploadBox = canUploadMore
        ? `<div class="ep-paste-box" data-action="paste-image" data-target-key="${escapeHtml(target.target_key)}" tabindex="0">Paste image here (max 4)</div>`
        : `<div class="ep-paste-box is-full">Image limit reached (4/4)</div>`;

    const lcIds = getLcPanelIds(target.target_key);
    const reportingGroup = info && info.reportingGroup ? String(info.reportingGroup).trim() : '';

    const fileRows = target.files.map((file) => {
        const observedOn = file.observed_on || '-';
        const grism = file.grism || '-';
        const obsMeta = file.obs_meta ? ` <span class="ep-widget-file-meta">${escapeHtml(file.obs_meta)}</span>` : '';
        return `
            <div class="ep-widget-file-row ${file.is_today ? 'today' : ''}">
                <span class="ep-widget-file-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</span>
                <span class="ep-widget-file-grism">${escapeHtml(grism)}</span>
                <span class="ep-widget-file-date">${escapeHtml(observedOn)}</span>
            </div>
        `;
    }).join('');

    return `
        <article class="ep-widget-main">
            <div class="ep-widget-title-row">
                <a href="${objectLink}" class="ep-widget-title-link" target="_blank">${escapeHtml(target.target_name)}</a>
                <div class="ep-widget-title-actions">
                    <button type="button" class="ep-btn ep-widget-done-btn ${isDone ? 'is-done' : ''}" data-action="toggle-done" data-target-key="${escapeHtml(target.target_key)}">${doneLabel}</button>
                    <button type="button" class="ep-btn ep-widget-discuss-btn ${isDiscuss ? 'is-discuss' : ''}" data-action="toggle-discuss" data-target-key="${escapeHtml(target.target_key)}">${discussLabel}</button>
                </div>
            </div>
            <div class="ep-widget-reporting-group">Reporting Group: ${escapeHtml(reportingGroup || '-')}</div>
            <div class="ep-widget-meta-grid">
                <label class="ep-field">
                    <span>Host</span>
                    <input class="ep-field-input" type="text" value="${escapeHtml(userFields.host)}" data-target-key="${escapeHtml(target.target_key)}" data-field="host">
                </label>
                <label class="ep-field">
                    <span>z (From Host)</span>
                    <input class="ep-field-input" type="text" value="${escapeHtml(userFields.z_from_host)}" data-target-key="${escapeHtml(target.target_key)}" data-field="z_from_host">
                </label>
                <label class="ep-field">
                    <span>z (Estimate)</span>
                    <input class="ep-field-input" type="text" value="${escapeHtml(userFields.z_estimate)}" data-target-key="${escapeHtml(target.target_key)}" data-field="z_estimate">
                </label>
                <label class="ep-field">
                    <span>Type</span>
                    <select class="ep-field-input" data-target-key="${escapeHtml(target.target_key)}" data-field="type">${typeOptionsHtml}</select>
                </label>
                <label class="ep-field">
                    <span>Phase</span>
                    <select class="ep-field-input" data-target-key="${escapeHtml(target.target_key)}" data-field="phase">${phaseOptionsHtml}</select>
                </label>
                <label class="ep-field">
                    <span>Classification Method</span>
                    <input class="ep-field-input" type="text" value="${escapeHtml(userFields.app)}" data-target-key="${escapeHtml(target.target_key)}" data-field="app">
                </label>
            </div>
            <div class="ep-widget-image-area">
                <div class="ep-lc-board">
                    <div class="ep-lc-toolbar">
                        <div class="ep-lc-title">Light curve</div>
                        <div class="ep-lc-controls">
                            <label class="ep-lc-toggle"><input id="${lcIds.extToggle}" type="checkbox" checked> Extinction</label>
                            <label class="ep-lc-toggle"><input id="${lcIds.kcorrToggle}" type="checkbox"> K-correction</label>
                            <button id="${lcIds.fetchBtn}" type="button" class="ep-btn ep-btn-mini" data-action="fetch-photometry" data-target-key="${escapeHtml(target.target_key)}">Fetch</button>
                            <button id="${lcIds.refreshBtn}" type="button" class="ep-btn ep-btn-mini" data-action="refresh-lc" data-target-key="${escapeHtml(target.target_key)}">Refresh</button>
                        </div>
                    </div>
                    <div id="${lcIds.plot}" class="ep-lc-plot"><div class="ep-lc-hint">Loading light curve...</div></div>
                </div>
                <div class="ep-widget-file-header">
                    <span>Filename</span>
                    <span>Grism</span>
                    <span>Date</span>
                </div>
                <div class="ep-file-list-wrap">${fileRows || '<div class="ep-empty">No files</div>'}</div>
                <div class="ep-image-board">
                    <div class="ep-image-board-title">Images</div>
                    ${uploadBox}
                    <div class="ep-image-grid">${imageCards || ''}</div>
                </div>
            </div>
        </article>
    `;
}

async function renderTargetWidget(target) {
    if (!target) {
        epTargetWidget.innerHTML = '<div class="ep-empty">Select a target from the list</div>';
        return;
    }
    const currentKey = target.target_key;
    epTargetWidget.innerHTML = buildWidgetHTML(target, { reportingGroup: '' });

    const reportingGroup = await resolveReportingGroup(target.target_name);
    const latest = epState.targets[epState.selectedIndex];
    if (!latest || latest.target_key !== currentKey) {
        return;
    }

    epTargetWidget.innerHTML = buildWidgetHTML(target, { reportingGroup });

    const ids = getLcPanelIds(target.target_key);
    const extToggle = document.getElementById(ids.extToggle);
    const kcorrToggle = document.getElementById(ids.kcorrToggle);
    const rerender = () => {
        renderTargetLightCurve(target, {
            applyExtinction: extToggle ? extToggle.checked : true,
            applyKCorr: kcorrToggle ? kcorrToggle.checked : false
        });
    };
    if (extToggle) {
        extToggle.addEventListener('change', rerender);
    }
    if (kcorrToggle) {
        kcorrToggle.addEventListener('change', rerender);
    }
    rerender();
}

function renderSelectedTarget(options = {}) {
    const refreshWidget = options.refreshWidget !== false;
    const target = epState.targets[epState.selectedIndex] || null;
    renderTargetList();
    if (refreshWidget) {
        renderTargetWidget(target);  // async
    }
    updateActionButtons();
}

function buildSummaryText() {
    if (!epState.summary) return 'No data\n';

    const rows = [];
    rows.push('ePessto++ Summary');
    rows.push('Date: ' + epState.summary.today_date);
    rows.push('Done/Total: ' + epState.summary.done_targets + '/' + epState.summary.total_targets);
    rows.push('Total files: ' + epState.summary.total_files);
    rows.push('Remaining targets: ' + epState.summary.remaining_targets);
    rows.push('');

    epState.targets.forEach((target, idx) => {
        rows.push((idx + 1) + '. ' + target.target_name + ' [' + (target.is_done_today ? 'done' : 'pending') + ']');
        rows.push('   files: ' + target.file_count);
        rows.push('   dates: ' + (target.dates.length ? target.dates.join(', ') : 'none'));
    });

    rows.push('');
    return rows.join('\n');
}

function buildReportMarkdown() {
    const rows = [];
    const dateStr = epState.summary ? epState.summary.today_date : new Date().toISOString().slice(0, 10);
    rows.push('# ePessto++ Support Report');
    rows.push('');
    rows.push('- Date: ' + dateStr);
    if (epState.summary) {
        rows.push('- Done/Total: ' + epState.summary.done_targets + '/' + epState.summary.total_targets);
        rows.push('- Remaining: ' + epState.summary.remaining_targets);
        rows.push('- Uploaded files: ' + epState.summary.total_files);
    }
    rows.push('');

    epState.targets.forEach((target) => {
        rows.push('## ' + target.target_name);
        rows.push('');
        rows.push('- Done today: ' + (target.is_done_today ? 'yes' : 'no'));
        rows.push('- File count: ' + target.file_count);
        rows.push('- Dates: ' + (target.dates.length ? target.dates.join(', ') : 'none'));
        rows.push('');
        target.files.forEach((f) => {
            rows.push('- ' + f.filename + ' (' + (f.observed_on || 'no-date') + ')');
        });
        rows.push('');
    });

    return rows.join('\n');
}

function downloadBlob(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function applySessionData(data, options = {}) {
    const refreshWidget = options.refreshWidget !== false;
    const currentKey = getCurrentTargetKey();
    epState.targets = (data.targets || []).slice().sort((a, b) =>
        String(a.target_name || '').localeCompare(String(b.target_name || ''), 'en', { sensitivity: 'base' })
    );
    epState.summary = data.summary || null;
    epState.batches = data.batches || [];
    if (!epState.targets.length) {
        epState.selectedIndex = -1;
    } else if (currentKey) {
        const idx = epState.targets.findIndex(t => t.target_key === currentKey);
        epState.selectedIndex = idx >= 0 ? idx : 0;
    } else {
        epState.selectedIndex = 0;
    }
    updateCounter();
    renderSelectedTarget({ refreshWidget });
}

async function loadTypeOptions() {
    try {
        const resp = await fetch('/api/classifications');
        const data = await resp.json();
        if (resp.ok && data.success && Array.isArray(data.classifications) && data.classifications.length) {
            epState.typeOptions = prioritizeSTypeOptions(data.classifications);
            return;
        }
    } catch (_) {}
    epState.typeOptions = prioritizeSTypeOptions(FALLBACK_TYPE_OPTIONS);
}

async function updateTargetState(targetKey, updates, options = {}) {
    const resp = await fetch('/api/epessto_support/target_state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_key: targetKey, updates })
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to save target state');
    }
    applySessionData(data, options);
}

function bindWidgetInteractions() {
    epTargetWidget.addEventListener('click', async (event) => {
        const btn = event.target.closest('[data-action="toggle-done"]');
        if (!btn) return;
        const targetKey = btn.dataset.targetKey || '';
        const target = epState.targets.find(t => t.target_key === targetKey);
        if (!target) return;

        const currentDone = Boolean(target.is_done_today);
        try {
            await updateTargetState(targetKey, {
                completed: !currentDone,
                discuss: !currentDone ? false : Boolean(target.is_discuss)
            });
            const summary = epState.summary || { done_targets: 0, total_targets: 0 };
            setStatus(
                'Updated: ' + target.target_name + ' -> ' + (!currentDone ? 'done' : 'pending') +
                ' (' + summary.done_targets + '/' + summary.total_targets + ')'
            );
        } catch (err) {
            setStatus('Save failed: ' + err.message);
        }
    });

    epTargetWidget.addEventListener('click', async (event) => {
        const btn = event.target.closest('[data-action="toggle-discuss"]');
        if (!btn) return;
        const targetKey = btn.dataset.targetKey || '';
        const target = epState.targets.find(t => t.target_key === targetKey);
        if (!target) return;

        const currentDiscuss = Boolean(target.is_discuss);
        try {
            await updateTargetState(targetKey, {
                discuss: !currentDiscuss,
                completed: !currentDiscuss ? false : Boolean(target.is_done_today)
            });
            setStatus('Updated discuss state for ' + target.target_name + '.');
        } catch (err) {
            setStatus('Save failed: ' + err.message);
        }
    });

    epTargetWidget.addEventListener('click', async (event) => {
        const fetchBtn = event.target.closest('[data-action="fetch-photometry"]');
        if (!fetchBtn) return;
        const targetKey = fetchBtn.dataset.targetKey || '';
        const target = epState.targets.find(t => t.target_key === targetKey);
        if (!target) return;
        try {
            setStatus('Fetching photometry points...');
            await fetchPhotometryPoints(target, false);
            renderTargetWidget(target);
            setStatus('Photometry fetch completed.');
        } catch (err) {
            setStatus('Fetch failed: ' + err.message);
        }
    });

    epTargetWidget.addEventListener('click', (event) => {
        const refreshBtn = event.target.closest('[data-action="refresh-lc"]');
        if (!refreshBtn) return;
        const targetKey = refreshBtn.dataset.targetKey || '';
        const target = epState.targets.find(t => t.target_key === targetKey);
        if (!target) return;
        renderTargetWidget(target);
        setStatus('Light curve refreshed.');
    });

    epTargetWidget.addEventListener('click', (event) => {
        const img = event.target.closest('[data-action="open-image"]');
        if (!img) return;
        const src = img.dataset.src || img.getAttribute('src');
        if (!src) return;
        openImageModal(src);
    });

    epTargetWidget.addEventListener('change', async (event) => {
        const field = event.target.dataset.field;
        const targetKey = event.target.dataset.targetKey;
        if (!field || !targetKey) return;
        if (!['host', 'z_from_host', 'z_estimate', 'type', 'phase', 'app'].includes(field)) return;

        try {
            const value = event.target.value || '';
            await updateTargetState(targetKey, { [field]: value }, { refreshWidget: false });
            setStatus('Saved ' + field + ' for ' + targetKey + '.');
        } catch (err) {
            setStatus('Save failed: ' + err.message);
        }
    });

    epTargetWidget.addEventListener('paste', async (event) => {
        const box = event.target.closest('[data-action="paste-image"]');
        if (!box) return;
        const targetKey = box.dataset.targetKey || '';
        if (!targetKey) return;

        const clipboardItems = event.clipboardData ? event.clipboardData.items : [];
        const imageItem = Array.from(clipboardItems).find((item) => item.type && item.type.startsWith('image/'));
        if (!imageItem) return;

        const blob = imageItem.getAsFile();
        if (!blob) return;
        event.preventDefault();

        const formData = new FormData();
        formData.append('target_key', targetKey);
        formData.append('image', blob, 'paste.png');

        try {
            const resp = await fetch('/api/epessto_support/target_image', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Upload image failed');
            }
            applySessionData(data);
            setStatus('Image uploaded.');
        } catch (err) {
            setStatus('Image upload failed: ' + err.message);
        }
    });

    epTargetWidget.addEventListener('click', async (event) => {
        const delBtn = event.target.closest('[data-action="delete-image"]');
        if (!delBtn) return;

        const targetKey = delBtn.dataset.targetKey || '';
        const filename = delBtn.dataset.filename || '';
        if (!targetKey || !filename) return;

        try {
            const resp = await fetch('/api/epessto_support/target_image', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_key: targetKey, filename })
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Delete image failed');
            }
            applySessionData(data);
            setStatus('Image deleted.');
        } catch (err) {
            setStatus('Delete image failed: ' + err.message);
        }
    });

}

async function removeCurrentTarget() {
    const target = epState.targets[epState.selectedIndex];
    if (!target) return;

    const targetKey = target.target_key;
    const targetName = target.target_name || targetKey;

    const c1 = confirm('Remove target "' + targetName + '" and all its uploaded files?');
    if (!c1) return;
    const c2 = confirm('Second confirmation: this action cannot be undone. Continue?');
    if (!c2) return;
    const c3 = confirm('Final confirmation: permanently delete this target now?');
    if (!c3) return;

    try {
        const resp = await fetch('/api/epessto_support/target', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_key: targetKey })
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.error || 'Remove target failed');
        }
        applySessionData(data);
        setStatus('Target removed: ' + targetName + ' (' + (data.removed || 0) + ' file(s) deleted).');
    } catch (err) {
        setStatus('Remove target failed: ' + err.message);
    }
}

async function loadSession(options = {}) {
    const refreshWidget = options.refreshWidget !== false;
    try {
        const resp = await fetch('/api/epessto_support/session');
        const data = await resp.json();
        if (data.success && data.targets && data.targets.length) {
            applySessionData(data, { refreshWidget });
            const batchCount = (data.batches || []).length;
            setStatus(
                'Restored ' + data.summary.total_files + ' files across ' + batchCount +
                ' batch(es) — ' + data.summary.done_targets + '/' + data.summary.total_targets +
                ' done today.'
            );
        } else {
            setStatus('Please upload .asci files.');
        }
    } catch (_) {
        setStatus('Please upload .asci files.');
    }
}

async function clearSession() {
    const c1 = confirm('Clear all uploaded files from this session?');
    if (!c1) return;
    const c2 = confirm('Second confirmation: this action cannot be undone. Continue?');
    if (!c2) return;
    const c3 = confirm('Final confirmation: permanently clear all now?');
    if (!c3) return;
    try {
        const resp = await fetch('/api/epessto_support/clear', { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) {
            epState.targets = [];
            epState.summary = null;
            epState.batches = [];
            epState.selectedIndex = -1;
            epFileInput.value = '';
            updateCounter();
            renderSelectedTarget();
            setStatus('Session cleared. ' + data.removed + ' file(s) removed.');
        }
    } catch (err) {
        setStatus('Clear failed: ' + err.message);
    }
}

async function handleUpload(files) {
    if (!files.length) return;
    const formData = new FormData();
    Array.from(files).forEach((file) => {
        formData.append('files', file, file.name);
    });

    setStatus('Uploading and parsing .asci files...');

    try {
        const response = await fetch('/api/epessto_support/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Upload failed');
        }

        applySessionData(data);
        const batchCount = (data.batches || []).length;
        setStatus(
            'Loaded ' + epState.summary.total_files + ' files (' + batchCount +
            ' batch) — ' + epState.summary.done_targets + '/' + epState.summary.total_targets +
            ' done today (' + epState.summary.today_date + ').'
        );
    } catch (error) {
        epState.targets = [];
        epState.summary = null;
        epState.selectedIndex = -1;
        updateCounter();
        renderSelectedTarget();
        setStatus('Upload failed: ' + error.message);
    }
}

epClearBtn.addEventListener('click', clearSession);

epUploadBtn.addEventListener('click', () => {
    epFileInput.click();
});

epFileInput.addEventListener('change', (event) => {
    handleUpload(event.target.files);
});

epPreviewBtn.addEventListener('click', () => {
    generateReportPdf(true);
});

epPrevBtn.addEventListener('click', () => {
    if (epState.selectedIndex > 0) {
        epState.selectedIndex -= 1;
        renderSelectedTarget();
    }
});

epNextBtn.addEventListener('click', () => {
    if (epState.selectedIndex < epState.targets.length - 1) {
        epState.selectedIndex += 1;
        renderSelectedTarget();
    }
});

epRemoveTargetBtn.addEventListener('click', removeCurrentTarget);

epRefreshBtn.addEventListener('click', async () => {
    await loadSession({ refreshWidget: false });
    setStatus('Refreshed latest shared state.');
});

epAutoRefreshToggle.addEventListener('change', () => {
    if (epAutoRefreshToggle.checked) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
    }
});

bindWidgetInteractions();

updateCounter();
renderSelectedTarget();

(async function initPage() {
    await loadTypeOptions();
    await loadSession();
})();
