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
const epAutoRefreshLabel = document.getElementById('epAutoRefreshLabel');
const epRefreshDot = document.getElementById('epRefreshDot');
let autoRefreshTimer = null;

function pulseRefreshDot() {
    if (!epRefreshDot) return;
    epRefreshDot.classList.remove('pulse');
    void epRefreshDot.offsetWidth; // reflow to restart animation
    epRefreshDot.classList.add('pulse');
}

function startAutoRefresh() {
    if (autoRefreshTimer) return;
    autoRefreshTimer = setInterval(async () => {
        pulseRefreshDot();
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
const epHomePanel = document.getElementById('epHomePanel');
const epWorkspacePanel = document.getElementById('epWorkspacePanel');
const epCreateRoomName = document.getElementById('epCreateRoomName');
const epCreateRoomPassword = document.getElementById('epCreateRoomPassword');
const epCreateRoomBtn = document.getElementById('epCreateRoomBtn');
const epCreatedRoomInfo = document.getElementById('epCreatedRoomInfo');
const epLiveRooms = document.getElementById('epLiveRooms');
const epJoinRoomId = document.getElementById('epJoinRoomId');
const epJoinRoomBtn = document.getElementById('epJoinRoomBtn');
const epRoomBadge = document.getElementById('epRoomBadge');
const epLeaveRoomBtn = document.getElementById('epLeaveRoomBtn');
const epRoomMembersBtn = document.getElementById('epRoomMembersBtn');
const epCopyInviteBtn = document.getElementById('epCopyInviteBtn');
const epRoomMembersModal = document.getElementById('epRoomMembersModal');
const epRoomMembersHint = document.getElementById('epRoomMembersHint');
const epRoomMembersList = document.getElementById('epRoomMembersList');

let epRoomId = null;
let epRoomName = '';
let epInviteToken = '';

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
    const roomSlug = epRoomName ? epRoomName.replace(/[^a-zA-Z0-9_\-]/g, '_') : 'room';
    const filename = roomSlug + '_' + dateStr + '.pdf';

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
                    <button type="button" class="ep-btn" onclick="epOpenNEDExplorer()" title="NED cone search near target">NED</button>
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

function setRoomUI(joined) {
    if (epHomePanel) epHomePanel.style.display = joined ? 'none' : 'flex';
    if (epWorkspacePanel) epWorkspacePanel.style.display = joined ? '' : 'none';
    if (epRoomBadge) {
        const label = epRoomId ? (epRoomId + (epRoomName ? ' · ' + epRoomName : '')) : '-';
        epRoomBadge.textContent = 'Room: ' + label;
    }
}

async function fetchLiveRooms() {
    if (!epLiveRooms) return;
    try {
        const resp = await fetch('/api/epessto_support/rooms/live');
        const data = await resp.json();
        const rooms = (resp.ok && data.success && Array.isArray(data.rooms)) ? data.rooms : [];
        if (!rooms.length) {
            epLiveRooms.innerHTML = '<div class="ep-empty">No live rooms</div>';
            return;
        }
        epLiveRooms.innerHTML = rooms.map((r) => {
            const roomId = String(r.room_id || '');
            const roomName = String(r.room_name || roomId);
            const t = r.updated_at ? new Date(r.updated_at).toLocaleString() : '-';
            const by = String(r.updated_by || '').trim();
            return `
                <div class="ep-live-room">
                    <div>
                        <div class="ep-live-room-id">${roomId} · ${roomName}</div>
                        <div class="ep-live-room-time">last update: ${t}${by ? ' · ' + by : ''}</div>
                    </div>
                    <button type="button" class="ep-btn" data-action="quick-join" data-room-id="${roomId}">join</button>
                </div>
            `;
        }).join('');
    } catch (_) {
        epLiveRooms.innerHTML = '<div class="ep-empty">Load failed</div>';
    }
}

async function loadCurrentRoom() {
    const resp = await fetch('/api/epessto_support/room/current');
    const data = await resp.json();
    if (resp.ok && data.success && data.joined) {
        epRoomId = data.room_id;
        epRoomName = String(data.room_name || '');
        epInviteToken = String(data.invite_token || '');
        setRoomUI(true);
        return true;
    }
    epRoomId = null;
    epRoomName = '';
    epInviteToken = '';
    setRoomUI(false);
    return false;
}

async function createRoom() {
    const roomName = (epCreateRoomName ? epCreateRoomName.value : '').trim();
    const password = (epCreateRoomPassword ? epCreateRoomPassword.value : '').trim();
    if (!roomName) {
        if (epCreatedRoomInfo) epCreatedRoomInfo.textContent = 'Please set a room name first.';
        return;
    }
    if (!password) {
        if (epCreatedRoomInfo) epCreatedRoomInfo.textContent = 'Please set a password first.';
        return;
    }
    const resp = await fetch('/api/epessto_support/rooms/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_name: roomName, password })
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Create room failed');
    }
    epRoomId = data.room_id;
    epRoomName = String(data.room_name || roomName);
    epInviteToken = String(data.invite_token || '');
    if (epCreatedRoomInfo) epCreatedRoomInfo.textContent = 'Created room: ' + epRoomId + ' · ' + epRoomName;
    if (epJoinRoomId) epJoinRoomId.value = epRoomId;
    if (epCreateRoomName) epCreateRoomName.value = '';
    if (epCreateRoomPassword) epCreateRoomPassword.value = '';
    setRoomUI(true);
}

async function joinRoom(roomIdInput, passwordInput) {
    const room_id = String(roomIdInput || '').trim().toUpperCase();
    const password = String(passwordInput || '').trim();
    if (!room_id || !password) {
        throw new Error('Room ID and password are required');
    }
    const resp = await fetch('/api/epessto_support/rooms/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id, password })
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Join room failed');
    }
    epRoomId = data.room_id;
    epRoomName = String(data.room_name || '');
    epInviteToken = String(data.invite_token || '');
    setRoomUI(true);
}

async function joinRoomByInvite(inviteToken) {
    const token = String(inviteToken || '').trim();
    if (!token) throw new Error('Invalid invite link');
    const resp = await fetch('/api/epessto_support/rooms/join_by_invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_token: token })
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Invite join failed');
    }
    epRoomId = data.room_id;
    epRoomName = String(data.room_name || '');
    epInviteToken = String(data.invite_token || token);
    setRoomUI(true);
}

async function leaveRoom() {
    await fetch('/api/epessto_support/room/leave', { method: 'POST' });
    stopAutoRefresh();
    if (epAutoRefreshToggle) epAutoRefreshToggle.checked = false;
    if (epAutoRefreshLabel) epAutoRefreshLabel.classList.remove('is-active');
    epRoomId = null;
    epRoomName = '';
    epInviteToken = '';
    setRoomUI(false);
    epState.targets = [];
    epState.summary = null;
    epState.batches = [];
    epState.selectedIndex = -1;
    updateCounter();
    renderSelectedTarget();
    setStatus('Please join or create a room.');
    await fetchLiveRooms();
}

function _inviteLinkFromToken(token) {
    const url = new URL(window.location.href);
    url.search = '';
    url.searchParams.set('invite', token);
    return url.toString();
}

async function copyInviteLink() {
    if (!epRoomId || !epInviteToken) {
        setStatus('No room invite token available.');
        return;
    }
    const link = _inviteLinkFromToken(epInviteToken);
    await navigator.clipboard.writeText(link);
    setStatus('Invite link copied.');
}

function epCloseRoomMembers() {
    if (epRoomMembersModal) epRoomMembersModal.style.display = 'none';
}
window.epCloseRoomMembers = epCloseRoomMembers;

async function openRoomMembers() {
    if (!epRoomId) return;
    const resp = await fetch('/api/epessto_support/room/members');
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Load members failed');
    }
    const members = Array.isArray(data.members) ? data.members : [];
    if (epRoomMembersHint) {
        epRoomMembersHint.textContent = data.can_manage
            ? 'You can kick members (except creator and yourself).'
            : 'View only. Creator/Admin can kick members.';
    }
    if (epRoomMembersList) {
        if (!members.length) {
            epRoomMembersList.innerHTML = '<div class="ep-empty">No members</div>';
        } else {
            epRoomMembersList.innerHTML = members.map((m) => {
                const role = m.is_owner
                    ? '<span class="ep-room-member-role owner">creator</span>'
                    : (m.is_admin ? '<span class="ep-room-member-role admin">admin</span>' : '');
                const seen = m.last_seen ? new Date(m.last_seen).toLocaleString() : '-';
                return `
                    <div class="ep-room-member-row">
                        <div>
                            <div><strong>${m.display_name}</strong>${role}${m.is_self ? ' <span class="ep-room-member-role">you</span>' : ''}</div>
                            <div class="ep-live-room-time">${m.email} · last seen: ${seen}</div>
                        </div>
                        ${m.can_kick ? `<button type="button" class="ep-btn ep-btn-clear" data-action="kick-member" data-email="${m.email}">kick</button>` : ''}
                    </div>
                `;
            }).join('');
        }
    }
    if (epRoomMembersModal) epRoomMembersModal.style.display = 'flex';
}

async function kickRoomMember(memberEmail) {
    const resp = await fetch('/api/epessto_support/room/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ member_email: memberEmail })
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Kick failed');
    }
}

async function updateTargetState(targetKey, updates, options = {}) {
    if (!epRoomId) {
        throw new Error('Join a room first');
    }
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
    if (!epRoomId) return;
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
    if (!epRoomId) {
        setStatus('Please join or create a room.');
        return;
    }
    try {
        const resp = await fetch('/api/epessto_support/session');
        const data = await resp.json();
        if (resp.status === 401) {
            epRoomId = null;
            setRoomUI(false);
            setStatus('Please join or create a room.');
            await fetchLiveRooms();
            return;
        }
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
    if (!epRoomId) return;
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
    if (!epRoomId) {
        setStatus('Please join or create a room first.');
        return;
    }
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
    setStatus('Refreshed latest room state.');
});

epAutoRefreshToggle.addEventListener('change', () => {
    if (epAutoRefreshToggle.checked) {
        startAutoRefresh();
        epAutoRefreshLabel.classList.add('is-active');
    } else {
        stopAutoRefresh();
        epAutoRefreshLabel.classList.remove('is-active');
    }
});

if (epCreateRoomBtn) {
    epCreateRoomBtn.addEventListener('click', async () => {
        try {
            await createRoom();
            await loadSession();
            await fetchLiveRooms();
            setStatus('Room ready: ' + epRoomId);
        } catch (err) {
            if (epCreatedRoomInfo) epCreatedRoomInfo.textContent = '';
            setStatus('Create room failed: ' + err.message);
        }
    });
}

if (epJoinRoomBtn) {
    epJoinRoomBtn.addEventListener('click', async () => {
        try {
            const roomId = epJoinRoomId ? epJoinRoomId.value : '';
            const pwd = prompt('Enter password for room ' + String(roomId || '').toUpperCase() + ':');
            if (pwd == null) return;
            await joinRoom(roomId, pwd);
            await loadSession();
            setStatus('Joined room: ' + epRoomId);
        } catch (err) {
            setStatus('Join failed: ' + err.message);
        }
    });
}

if (epRoomMembersBtn) {
    epRoomMembersBtn.addEventListener('click', async () => {
        try {
            await openRoomMembers();
        } catch (err) {
            setStatus('Load members failed: ' + err.message);
        }
    });
}

if (epCopyInviteBtn) {
    epCopyInviteBtn.addEventListener('click', async () => {
        try {
            await copyInviteLink();
        } catch (err) {
            setStatus('Copy invite failed: ' + err.message);
        }
    });
}

if (epRoomMembersList) {
    epRoomMembersList.addEventListener('click', async (event) => {
        const btn = event.target.closest('[data-action="kick-member"]');
        if (!btn) return;
        const email = btn.dataset.email || '';
        if (!email) return;
        const ok = confirm('Kick ' + email + ' from this room?');
        if (!ok) return;
        try {
            await kickRoomMember(email);
            await openRoomMembers();
            setStatus('Member kicked: ' + email);
        } catch (err) {
            setStatus('Kick failed: ' + err.message);
        }
    });
}

if (epLiveRooms) {
    epLiveRooms.addEventListener('click', async (event) => {
        const btn = event.target.closest('[data-action="quick-join"]');
        if (!btn) return;
        const roomId = btn.dataset.roomId || '';
        if (epJoinRoomId) epJoinRoomId.value = roomId;
        const pwd = prompt('Enter password for room ' + roomId + ':');
        if (pwd == null) return;
        try {
            await joinRoom(roomId, pwd);
            await loadSession();
            setStatus('Joined room: ' + epRoomId);
        } catch (err) {
            setStatus('Join failed: ' + err.message);
        }
    });
}

if (epLeaveRoomBtn) {
    epLeaveRoomBtn.addEventListener('click', async () => {
        await leaveRoom();
    });
}

bindWidgetInteractions();

updateCounter();
renderSelectedTarget();

// ─── NED Explorer (widget context) ──────────────────────────────────────────

let _epNedData = null;
let _epNedHoverListener = null;
let _epNedRadiusArcsec = 30;
let _epNedTimedOut = false;
let _epNedRetryTimer = null;
let _epNedFromCache = false;
let _epNedSearchedAt = null;
let _epNedCurrentHost = '';
let _epNedSurvey = 'CDS/P/DSS2/color';
let _epNedRa = null;
let _epNedDec = null;
let _epNedTargetName = '';

function _epGetNEDRadiusArcsec() {
    const input = document.getElementById('epNedRadiusInput');
    const raw = input ? Number(input.value) : _epNedRadiusArcsec;
    const r = Number.isFinite(raw) ? Math.max(1, Math.min(600, Math.round(raw))) : 30;
    if (input) input.value = String(r);
    _epNedRadiusArcsec = r;
    return r;
}

async function _epResolveTargetCoords(targetName) {
    try {
        const resp = await fetch('/api/search_target?q=' + encodeURIComponent(targetName));
        const data = await resp.json();
        if (!resp.ok || !data.results || !data.results.length) return null;
        const exact = data.results.find(
            r => ((r.prefix || '') + (r.name || '')).replace(/\s+/g, '').toLowerCase() ===
                 String(targetName || '').replace(/\s+/g, '').toLowerCase()
        ) || data.results[0];
        const ra  = exact.ra  != null ? parseFloat(exact.ra)  : null;
        const dec = exact.dec != null ? parseFloat(exact.dec) : null;
        if (!Number.isFinite(ra) || !Number.isFinite(dec)) return null;
        return { ra, dec };
    } catch (_) { return null; }
}

async function _epFetchNEDData(radiusArcsec, force) {
    if (_epNedRa == null || _epNedDec == null) return null;
    _epNedTimedOut = false;
    _epNedFromCache = false;
    _epNedSearchedAt = null;
    _epNedCurrentHost = '';
    const name = encodeURIComponent(_epNedTargetName || '');
    const forceParam = force ? '1' : '0';
    try {
        const resp = await fetch(
            `/api/ned/cone?ra=${_epNedRa}&dec=${_epNedDec}&radius_arcsec=${radiusArcsec}` +
            `&object_name=${name}&force=${forceParam}`
        );
        if (!resp.ok) {
            if (resp.status === 502) {
                let body = {};
                try { body = await resp.json(); } catch (_) {}
                const msg = (body.error || '').toLowerCase();
                if (msg.includes('timeout') || msg.includes('timed out')) { _epNedTimedOut = true; }
            }
            throw new Error(`proxy ${resp.status}`);
        }
        const json = await resp.json();
        if (!json.success) throw new Error(json.error || 'NED error');
        _epNedData = json.results || [];
        _epNedFromCache  = json.from_cache  || false;
        _epNedSearchedAt = json.searched_at || null;
        _epNedCurrentHost = json.current_host || '';
        return _epNedData;
    } catch (e) {
        console.error('EP NED fetch failed:', e);
        return null;
    }
}

function epChangeNEDSurvey() {
    const sel = document.getElementById('epNedSurveySelect');
    if (!sel) return;
    _epNedSurvey = sel.value;
    const iframe = document.getElementById('ep-ned-aladin-iframe');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({type: 'changeSurvey', survey: sel.value}, '*');
    }
}

async function epOpenNEDExplorer() {
    const target = epState.targets[epState.selectedIndex];
    if (!target) { setStatus('No target selected.'); return; }

    const modal = document.getElementById('epNedExplorerModal');
    if (modal) modal.style.display = 'flex';

    _epNedTargetName = target.target_name || '';
    _epNedData = null;
    _epNedRa = null;
    _epNedDec = null;

    const countEl = document.getElementById('epNedResultCount');
    if (countEl) countEl.textContent = `Resolving coordinates for ${_epNedTargetName}…`;

    const coords = await _epResolveTargetCoords(_epNedTargetName);
    if (!coords) {
        if (countEl) countEl.textContent = `Could not resolve RA/Dec for ${_epNedTargetName}`;
        return;
    }
    _epNedRa  = coords.ra;
    _epNedDec = coords.dec;

    _epInitNEDExplorer(true, false);
}

function epRerunNEDSearch() {
    if (_epNedRetryTimer) { clearInterval(_epNedRetryTimer); _epNedRetryTimer = null; }
    _epNedData = null;
    _epInitNEDExplorer(true, true);
}

function epCloseNEDExplorer() {
    const modal = document.getElementById('epNedExplorerModal');
    if (modal) modal.style.display = 'none';
    if (_epNedHoverListener) { window.removeEventListener('message', _epNedHoverListener); _epNedHoverListener = null; }
    if (_epNedRetryTimer) { clearInterval(_epNedRetryTimer); _epNedRetryTimer = null; }
}

async function epSetNEDHost(idx, btnEl) {
    if (!Array.isArray(_epNedData) || idx < 0 || idx >= _epNedData.length) return;
    const row = _epNedData[idx] || {};
    if (!row.objname) { setStatus('NED row has no object name.'); return; }

    const btn = btnEl || null;
    if (btn) { btn.disabled = true; btn.textContent = 'Setting...'; }

    const target = epState.targets[epState.selectedIndex];
    if (!target) { if (btn) { btn.disabled = false; btn.textContent = 'Set as Host'; } return; }

    try {
        const resp = await fetch('/api/ned/set_host', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                target_name: _epNedTargetName,
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
        if (!resp.ok || !json.success) throw new Error(json.error || json.message || `HTTP ${resp.status}`);

        _epNedCurrentHost = row.objname;

        // Update widget fields
        const updates = { host: row.objname };
        if (json.updated_redshift && json.redshift != null) {
            const zNum = Number(json.redshift);
            updates.z_from_host = Number.isFinite(zNum) ? String(zNum) : String(json.redshift);
        }
        await updateTargetState(target.target_key, updates, { refreshWidget: false });

        // Update DOM inputs immediately for instant feedback
        const hostInput = epTargetWidget.querySelector('[data-field="host"]');
        if (hostInput) { hostInput.value = row.objname; }
        if (updates.z_from_host) {
            const zInput = epTargetWidget.querySelector('[data-field="z_from_host"]');
            if (zInput) { zInput.value = updates.z_from_host; }
        }

        _epInitNEDExplorer(false, false);
        const msg = json.updated_redshift
            ? `Host set to ${row.objname}; redshift updated in widget`
            : `Host set to ${row.objname}; redshift unchanged (z flag not S*)`;
        setStatus(msg);
    } catch (e) {
        console.error('epSetNEDHost failed:', e);
        setStatus(`Set host failed: ${e.message || e}`);
        if (btn) { btn.disabled = false; btn.textContent = 'Set as Host'; }
    }
}

async function epUnsetNEDHost(idx, btnEl) {
    if (!Array.isArray(_epNedData) || idx < 0 || idx >= _epNedData.length) return;
    const row = _epNedData[idx] || {};
    if (!row.objname) return;

    const btn = btnEl || null;
    if (btn) { btn.disabled = true; btn.textContent = 'Removing...'; }

    try {
        const resp = await fetch('/api/ned/unset_host', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ target_name: _epNedTargetName }),
        });
        const json = await resp.json();
        if (!resp.ok || !json.success) throw new Error(json.error || json.message || `HTTP ${resp.status}`);
        _epNedCurrentHost = '';

        // Clear host & z_from_host in DB session and widget DOM
        const target = epState.targets[epState.selectedIndex];
        if (target) {
            await updateTargetState(target.target_key, { host: '', z_from_host: '' }, { refreshWidget: false });
            const hostInput = epTargetWidget.querySelector('[data-field="host"]');
            if (hostInput) hostInput.value = '';
            const zInput = epTargetWidget.querySelector('[data-field="z_from_host"]');
            if (zInput) zInput.value = '';
        }

        _epInitNEDExplorer(false, false);
        setStatus(`Host removed: ${row.objname}`);
    } catch (e) {
        console.error('epUnsetNEDHost failed:', e);
        setStatus(`Unset host failed: ${e.message || e}`);
        if (btn) { btn.disabled = false; btn.textContent = 'Unset Host'; }
    }
}

async function _epInitNEDExplorer(forceRefresh = false, forceNED = false) {
    const container = document.getElementById('epNedAladinContainer');
    const loading   = document.getElementById('epNedAladinLoading');
    const countEl   = document.getElementById('epNedResultCount');
    const tbody     = document.getElementById('epNedResultBody');
    if (_epNedRa == null || _epNedDec == null) return;

    const radiusArcsec = _epGetNEDRadiusArcsec();
    if (loading) loading.style.display = 'flex';
    if (countEl) countEl.textContent = `Fetching NED data (${radiusArcsec}")…`;
    if (forceRefresh || !_epNedData) {
        await _epFetchNEDData(radiusArcsec, forceNED);
    }

    if (_epNedTimedOut) {
        if (loading) loading.style.display = 'none';
        let remaining = 10;
        if (countEl) countEl.textContent = `NED request timed out. Retrying in ${remaining}s…`;
        if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="padding:20px; text-align:center; color:#f59e0b;">NED server did not respond. Retrying automatically…</td></tr>`;
        if (_epNedRetryTimer) clearInterval(_epNedRetryTimer);
        _epNedRetryTimer = setInterval(function() {
            remaining -= 1;
            const modal = document.getElementById('epNedExplorerModal');
            if (!modal || modal.style.display === 'none') {
                clearInterval(_epNedRetryTimer); _epNedRetryTimer = null; return;
            }
            if (remaining <= 0) {
                clearInterval(_epNedRetryTimer); _epNedRetryTimer = null;
                _epInitNEDExplorer(true);
            } else {
                if (countEl) countEl.textContent = `NED request timed out. Retrying in ${remaining}s…`;
            }
        }, 1000);
        return;
    }

    const sources = (_epNedData || [])
        .map((o, i) => ({ra: Number(o.ra), dec: Number(o.dec), name: o.objname || '', type: o.type || '', idx: i}))
        .filter(s => Number.isFinite(s.ra) && Number.isFinite(s.dec));

    const cacheNote = _epNedFromCache && _epNedSearchedAt
        ? ` · <span style="color:#f59e0b; font-size:0.75rem;" title="Loaded from database cache">cached ${new Date(_epNedSearchedAt).toLocaleString()}</span>`
        : ` · <span style="color:#4ade80; font-size:0.75rem;">live from NED</span>`;
    const hostNote = _epNedCurrentHost
        ? ` · <span style="color:#00f5d4; font-size:0.75rem;">host: ${_epNedCurrentHost}</span>`
        : '';
    if (countEl) countEl.innerHTML = (sources.length
        ? `${sources.length} NED object(s) within ${radiusArcsec}"`
        : `No NED objects found within ${radiusArcsec}"`) + cacheNote + hostNote;

    if (!tbody) return;
    tbody.innerHTML = '';
    if (!_epNedData || _epNedData.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="padding:20px; text-align:center; color:#666;">No NED objects found within ${radiusArcsec}"</td></tr>`;
    } else {
        _epNedData.forEach((obj, i) => {
            const z  = obj.redshift != null ? parseFloat(obj.redshift) : null;
            const cz = z != null ? Math.round(z * 299792.458).toLocaleString() : '—';
            const canSetZ = String(obj.redshift_type || '').startsWith('S') && z != null;
            const isHost = !!_epNedCurrentHost && (String(obj.objname || '') === String(_epNedCurrentHost));
            const tr = document.createElement('tr');
            tr.dataset.idx = i;
            tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.06); cursor:default; transition:background 0.1s;';
            if (isHost) tr.style.borderLeft = '3px solid rgba(0,245,212,0.6)';
            tr.innerHTML = `
                <td style="padding:5px 8px; color:#555;">${i + 1}</td>
                <td style="padding:5px 8px; color:#00f5d4; white-space:nowrap;">${obj.objname || '—'}${isHost ? ' <span style="color:#00f5d4; font-size:0.7rem; border:1px solid rgba(0,245,212,0.5); border-radius:999px; padding:1px 6px; margin-left:6px;">HOST</span>' : ''}</td>
                <td style="padding:5px 8px;">${obj.type || '—'}</td>
                <td style="padding:5px 8px; text-align:right; font-family:monospace;">${obj.ra != null ? parseFloat(obj.ra).toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right; font-family:monospace;">${obj.dec != null ? parseFloat(obj.dec).toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right;">${z != null ? z.toFixed(5) : '—'}</td>
                <td style="padding:5px 8px; text-align:right;">${cz}</td>
                <td style="padding:5px 8px; color:#aaa;">${obj.redshift_type || '—'}</td>
                <td style="padding:4px 8px; text-align:center; white-space:nowrap;">
                    ${isHost
                        ? `<button class="ep-ned-host-btn" onclick="epUnsetNEDHost(${i}, this)" style="font-size:0.72rem; padding:2px 8px; border:1px solid rgba(248,113,113,0.6); border-radius:6px; background:rgba(248,113,113,0.08); color:#f87171; cursor:pointer;">Unset Host</button>`
                        : `<button class="ep-ned-host-btn" onclick="epSetNEDHost(${i}, this)" title="${canSetZ ? 'redshift will update' : 'redshift will NOT update: z flag not S*'}" style="font-size:0.72rem; padding:2px 8px; border:1px solid rgba(255,255,255,0.2); border-radius:6px; background:rgba(255,255,255,0.04); color:#ddd; cursor:pointer;">Set as Host</button>`}
                </td>`;
            tr.addEventListener('mouseenter', () => {
                tbody.querySelectorAll('tr').forEach(r => r.style.background = '');
                tr.style.background = 'rgba(0,245,212,0.1)';
                const iframe = document.getElementById('ep-ned-aladin-iframe');
                if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage({type: 'highlightNED', idx: i}, '*');
            });
            tr.addEventListener('mouseleave', () => {
                tr.style.background = '';
                const iframe = document.getElementById('ep-ned-aladin-iframe');
                if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage({type: 'highlightNED', idx: -1}, '*');
            });
            tbody.appendChild(tr);
        });
    }

    _epBuildNEDAladinIframe(container, loading, _epNedRa, _epNedDec, sources, radiusArcsec);

    if (_epNedHoverListener) window.removeEventListener('message', _epNedHoverListener);
    _epNedHoverListener = function(e) {
        if (!e.data || e.data.type !== 'nedHover') return;
        const idx = e.data.idx;
        tbody.querySelectorAll('tr').forEach(r => {
            r.style.background = parseInt(r.dataset.idx) === idx ? 'rgba(0,245,212,0.1)' : '';
        });
        if (idx >= 0) {
            const row = tbody.querySelector(`tr[data-idx="${idx}"]`);
            if (row) row.scrollIntoView({block: 'nearest', behavior: 'smooth'});
        }
    };
    window.addEventListener('message', _epNedHoverListener);
}

function _epBuildNEDAladinIframe(container, loading, ra, dec, sources, radiusArcsec) {
    const old = document.getElementById('ep-ned-aladin-iframe');
    if (old) old.remove();
    if (!container) return;

    const fov = Math.max((radiusArcsec * 2.4) / 3600, 0.01).toFixed(6);
    const targetName = String(_epNedTargetName || '').replace(/'/g, "\\'");
    const survey = _epNedSurvey || 'CDS/P/DSS2/color';

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
      survey: '${survey}',
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
    var tCat = A.catalog({name:'Target', color:'#ff4444', sourceSize:16, shape:'cross'});
    tCat.addSources([A.source(T_RA, T_DEC, {name:'${targetName}', idx:-1})]);
    al.addCatalog(tCat);
    al.on('objectHovered', function(obj) {
      if (obj && obj.data && typeof obj.data.idx !== 'undefined' && obj.data.idx >= 0)
        window.parent.postMessage({type:'nedHover', idx: obj.data.idx}, '*');
    });
    al.on('objectHoveredStop', function() {
      window.parent.postMessage({type:'nedHover', idx:-1}, '*');
    });
    window.parent.postMessage({type:'nedAladinReady'}, '*');
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
    iframe.id = 'ep-ned-aladin-iframe';
    iframe.style.cssText = 'width:100%; height:100%; border:none;';
    iframe.srcdoc = html;
    container.appendChild(iframe);

    const onReady = function(e) {
        if (e.data && e.data.type === 'nedAladinReady') {
            window.removeEventListener('message', onReady);
            if (loading) loading.style.display = 'none';
            const iframeEl = document.getElementById('ep-ned-aladin-iframe');
            if (iframeEl && iframeEl.contentWindow) {
                iframeEl.contentWindow.postMessage({type: 'addNEDSources', sources: sources}, '*');
            }
        }
    };
    window.addEventListener('message', onReady);
}

(async function initPage() {
    await loadTypeOptions();
    const params = new URLSearchParams(window.location.search);
    const inviteToken = params.get('invite');
    let joined = false;
    if (inviteToken) {
        try {
            await joinRoomByInvite(inviteToken);
            joined = true;
            const cleanUrl = new URL(window.location.href);
            cleanUrl.searchParams.delete('invite');
            window.history.replaceState({}, '', cleanUrl.toString());
        } catch (err) {
            setStatus('Invite join failed: ' + err.message);
        }
    }
    if (!joined) {
        joined = await loadCurrentRoom();
    }
    await fetchLiveRooms();
    if (joined) {
        await loadSession();
    } else {
        setStatus('Please join or create a room.');
    }
})();
