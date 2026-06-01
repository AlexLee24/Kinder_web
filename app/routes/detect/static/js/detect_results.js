'use strict';
/* ═══════════════════════════════════════════════════════════════
   detect_results.js
   — Interactive Plotly LC, Follow-up Tracker, dynamic host UI,
     image + LC loading spinners.
   ═══════════════════════════════════════════════════════════════ */

// Plotly is loaded synchronously in <head> — window.Plotly is available.

// ── In-memory LC cache ────────────────────────────────────────────────────
const _lcCache = new Map(); // target_name → plot_json string

// ── Card navigation ───────────────────────────────────────────────────────
let _cur   = 0;
let _total = 0;

function _showCard(idx) {
    if (idx < 0 || idx >= _total) return;

    // ── 效能優化：只操作舊卡片與新卡片，避免對全部卡片執行 DOM 重排 ──
    const oldCard = document.getElementById(`card-${_cur}`);
    if (oldCard && _cur !== idx) {
        oldCard.style.display = 'none';
        // 清理隱藏卡片的 Plotly，釋放記憶體
        const pd = document.getElementById(`plotly-card-${_cur}`);
        if (pd && pd._fullLayout) { try { Plotly.purge(pd); } catch (_) {} }
    }

    const newCard = document.getElementById(`card-${idx}`);
    if (newCard) {
        newCard.style.display = '';
    }

    _cur = idx;
    // ────────────────────────────────────────────────────────────────

    // Update counter
    const el = document.getElementById('cardCurrent');
    if (el) el.textContent = idx + 1;

    // Update object name in nav bar
    const nameEl = document.getElementById('cardNavObjName');
    if (nameEl) {
        const titleLink = newCard && newCard.querySelector('.card-obj-title a');
        nameEl.textContent = titleLink
            ? titleLink.textContent.replace(/↗/g, '').trim()
            : '';
    }

    // Highlight matching summary row
    document.querySelectorAll('.summary-row-active').forEach(r => r.classList.remove('summary-row-active'));
    const row = document.querySelector(`[data-card-index="${idx}"]`);
    if (row) row.classList.add('summary-row-active');

    // Update prev/next disabled state
    const prev = document.getElementById('prevCardBtn');
    const next = document.getElementById('nextCardBtn');
    if (prev) prev.disabled = (idx === 0);
    if (next) next.disabled = (idx === _total - 1);

    // Lazy-load the finder image (with spinner)
    if (newCard) {
        const img = newCard.querySelector('img.lazy-img');
        if (img) _loadCardImage(img);
    }

    // Auto-fetch LC for the visible card
    _autoFetchLC(idx);
}

// ── Image lazy-load with spinner ──────────────────────────────────────────
function _loadCardImage(img) {
    if (!img) return;
    // Already fully loaded (first card — src set directly in HTML)
    if (!img.dataset.src && img.complete && img.naturalWidth > 0) return;

    const container = img.parentElement; // .card-image-col
    if (!container) return;
    if (container.querySelector('.card-img-loading')) return; // no duplicate spinners

    const spinner = document.createElement('div');
    spinner.className = 'card-img-loading';
    spinner.innerHTML = '<span class="tracker-spinner"></span>';
    container.insertBefore(spinner, img);
    img.style.opacity    = '0';
    img.style.transition = 'opacity 0.25s';

    const cleanup = () => {
        spinner.remove();
        img.style.opacity = '';
        img.style.transition = '';
    };
    img.addEventListener('load',  cleanup, { once: true });
    img.addEventListener('error', () => { spinner.remove(); }, { once: true });

    // Swap data-src → src to start the load
    if (img.dataset.src) {
        img.src = img.dataset.src;
        img.removeAttribute('data-src');
    }
}

function jumpToCard(idx) {
    _showCard(idx);
    const bar = document.getElementById('cardNavBar');
    if (bar) bar.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function prevCard() { jumpToCard(_cur - 1); }
function nextCard() { jumpToCard(_cur + 1); }

function nextUnreviewed() {
    for (let i = _cur + 1; i < _total; i++) {
        const c = document.getElementById(`card-${i}`);
        if (c && c.dataset.status === 'object') { jumpToCard(i); return; }
    }
    // wrap around from beginning
    for (let i = 0; i < _cur; i++) {
        const c = document.getElementById(`card-${i}`);
        if (c && c.dataset.status === 'object') { jumpToCard(i); return; }
    }
}

document.addEventListener('keydown', e => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    if      (e.key === 'ArrowRight') nextCard();
    else if (e.key === 'ArrowLeft')  prevCard();
    else if (e.key === 'Escape')     closeImgModal();
});

// ── Photometry: interactive Plotly ────────────────────────────────────────
function _autoFetchLC(cardIdx) {
    const plotDiv = document.getElementById(`plotly-card-${cardIdx}`);
    if (!plotDiv) return;
    const target = plotDiv.dataset.targetName;
    if (!target) return;
    // Cached → re-render interactive chart
    if (_lcCache.has(target)) {
        _renderPlotly(plotDiv, _lcCache.get(target), target);
        return;
    }
    // Already has content (user manually triggered) → skip
    if (plotDiv.children.length > 0 && !plotDiv.querySelector('.card-lc-loading')) return;
    // Auto-fetch on first show
    _fetchLC(target, cardIdx, false);
}

function fetchCardLightcurve(targetName, cardIdx) {
    _fetchLC(targetName, cardIdx, false);
}

function refreshCardLightcurve(targetName, cardIdx) {
    _lcCache.delete(targetName);
    const pd = document.getElementById(`plotly-card-${cardIdx}`);
    if (pd && pd._fullLayout) { try { Plotly.purge(pd); } catch (_) {} }
    _fetchLC(targetName, cardIdx, true);
}

function _fetchLC(targetName, cardIdx, forceRefresh) {
    const plotDiv  = document.getElementById(`plotly-card-${cardIdx}`);
    const statusEl = document.getElementById(`lc-status-${cardIdx}`);
    if (!plotDiv) return;

    // Client cache hit
    if (!forceRefresh && _lcCache.has(targetName)) {
        _renderPlotly(plotDiv, _lcCache.get(targetName), targetName);
        return;
    }

    // Show spinner while fetching
    if (plotDiv._fullLayout) { try { Plotly.purge(plotDiv); } catch (_) {} }
    plotDiv.innerHTML = '<div class="card-lc-loading"><span class="tracker-spinner"></span>&nbsp;Loading photometry…</div>';
    if (statusEl) { statusEl.textContent = ''; statusEl.className = 'card-lc-status'; }

    // ====== 加入 Plotly 是否已載入的檢查 ======
    if (typeof Plotly === 'undefined') {
        // 如果使用了 defer，Plotly 可能還沒載入完，延遲一下再試
        setTimeout(() => _fetchLC(targetName, cardIdx, forceRefresh), 200);
        return;
    }

    const url = `/api/detect/lightcurve/${encodeURIComponent(targetName)}` + (forceRefresh ? '?refresh=1' : '');
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (!data.success || !data.plot_json) {
                plotDiv.innerHTML = '<div class="card-no-data">No photometry data</div>';
                if (statusEl) statusEl.textContent = data.message || 'No data';
                return;
            }
            _lcCache.set(targetName, data.plot_json);
            _renderPlotly(plotDiv, data.plot_json, targetName);
            if (statusEl && data.cached) statusEl.textContent = '(cached)';
        })
        .catch(() => {
            plotDiv.innerHTML = '<div class="card-no-data">Failed to load photometry</div>';
            if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'card-lc-status error'; }
        });
}

function _renderPlotly(plotDiv, plotJsonStr, targetName) {
    try {
        if (plotDiv._fullLayout) { try { Plotly.purge(plotDiv); } catch (_) {} }
        plotDiv.innerHTML = '';
        const plotData = JSON.parse(plotJsonStr);
        Plotly.newPlot(
            plotDiv,
            plotData.data,
            plotData.layout,
            Object.assign({ responsive: true, displayModeBar: true }, plotData.config || {})
        );
    } catch (err) {
        console.error('[detect] plot render error for', targetName, err);
        plotDiv.innerHTML = '<div class="card-no-data">Plot render failed</div>';
    }
}

function _formatAbsMag(value, sep) {
    const am = Number(value);
    if (!Number.isFinite(am)) return '—';

    const label = am.toFixed(2);
    const sepValue = Number(sep);
    const dimStyle = Number.isFinite(sepValue) && sepValue >= 10 ? ' style="opacity:0.7"' : '';

    if (am < -20) return `<span class="absmag-chip absmag-verybright"${dimStyle}>${label}</span>`;
    if (am <= -18) return `<span class="absmag-chip absmag-peak">${label}</span>`;
    if (am <= -15) return label;
    return `<span class="absmag-chip absmag-dim">${label}</span>`;
}

// ── Filter summary table ──────────────────────────────────────────────────
function filterSummary(btn, filter) {
    document.querySelectorAll('.tbl-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('#summaryTable tbody tr').forEach(row => {
        const status  = row.dataset.status  || '';
        const hasHost = row.dataset.hasHost === 'true';
        let show = false;
        switch (filter) {
            case 'all':        show = true; break;
            case 'unreviewed': show = (status === 'object'); break;
            case 'followup':   show = (status === 'followup'); break;
            case 'host':       show = hasHost; break;
            case 'nohost':     show = !hasHost; break;
        }
        row.style.display = show ? '' : 'none';
    });
}

// ── Follow-up Tracker ─────────────────────────────────────────────────────
let _trackerOpen     = false;
let _trackerLoaded   = false;
let _trackerRetryTmo = null;

function toggleTracker() {
    _trackerOpen = !_trackerOpen;
    const panel = document.getElementById('followupTrackerPanel');
    const btn   = document.getElementById('trackerToggleBtn');
    if (panel) panel.classList.toggle('collapsed', !_trackerOpen);
    if (btn)   btn.classList.toggle('active', _trackerOpen);
    if (_trackerOpen && !_trackerLoaded) loadTracker(false);
}

function loadTracker(force) {
    const body = document.getElementById('trackerBody');
    if (!body) return;

    if (force) {
        _trackerLoaded = false;
        body.innerHTML = '<div class="tracker-loading"><span class="tracker-spinner"></span> Loading…</div>';
    }

    fetch('/api/detect/followup_tracker')
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                body.innerHTML = '<div class="tracker-empty">Failed to load tracker.</div>';
                return;
            }
            const tracker = data.tracker || [];

            // Cold cache — backend still building; retry automatically
            if (data.building && tracker.length === 0) {
                body.innerHTML = '<div class="tracker-loading"><span class="tracker-spinner"></span> Building tracker…</div>';
                if (_trackerRetryTmo) clearTimeout(_trackerRetryTmo);
                _trackerRetryTmo = setTimeout(() => loadTracker(false), 3000);
                return;
            }

            _trackerLoaded = true;
            const subtitle = document.getElementById('trackerSubtitle');
            const badge    = document.getElementById('trackerCountBadge');
            if (subtitle) subtitle.textContent = `${tracker.length} follow-up objects`;
            if (badge)    badge.textContent    = tracker.length;

            if (tracker.length === 0) {
                body.innerHTML = '<div class="tracker-empty">No follow-up objects yet.</div>';
                return;
            }

            let html = '<div class="tracker-table-wrap"><table class="tracker-table"><thead><tr>'
                + '<th>Object</th>'
                + '<th class="th-absmag">Abs Mag</th>'
                + '<th>z</th>'
                + '<th>Catalog</th>'
                + '<th>Sep (")</th>'
                + '<th class="td-date">Discovery</th>'
                + '</tr></thead><tbody>';

            tracker.forEach(item => {
                const amHtml = _formatAbsMag(item.abs_mag, item.separation_arcsec);
                html += `<tr>
                    <td><a href="/object/${item.name}" class="tracker-obj-link" target="_blank">${item.name}</a></td>
                    <td class="td-absmag">${amHtml}</td>
                    <td>${item.z != null ? item.z.toFixed(4) : '—'}</td>
                    <td class="td-catalog">${item.catalog_name}</td>
                    <td>${item.separation_arcsec != null ? item.separation_arcsec.toFixed(2) : '—'}</td>
                    <td class="td-date">${item.discoverydate}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
            body.innerHTML = html;
        })
        .catch(() => {
            body.innerHTML = '<div class="tracker-empty">Network error loading tracker.</div>';
        });
}

// ── Flag toggle ───────────────────────────────────────────────────────────
function toggleFlag(id, element) {
    event.stopPropagation();
    const newFlag = !element.classList.contains('active');
    element.style.opacity = '0.5';
    fetch('/api/toggle_flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, flag: newFlag })
    })
    .then(r => r.json())
    .then(data => {
        element.style.opacity = '1';
        if (data.success) element.classList.toggle('active', newFlag);
        else alert('Failed to update flag');
    })
    .catch(() => { element.style.opacity = '1'; alert('An error occurred'); });
}

// ── Date selector ─────────────────────────────────────────────────────────
function changeDate(sel) {
    const date = sel.value;
    window.location.href = date ? `/detect?detect_results=${date}` : '/detect';
}

// ── Refresh page ──────────────────────────────────────────────────────────
function refreshPage() { location.reload(); }

// ── Host management ───────────────────────────────────────────────────────
function setHost(matchId, targetName, redshift, source) {
    if (!confirm(`Set this match as host for ${targetName}?\nThis will update the TNS redshift.`)) return;
    _setCardBusy(targetName, true);
    fetch('/api/set_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: matchId, target_name: targetName, redshift, source })
    })
    .then(r => r.json())
    .then(d => {
        if (d.success) _updateUIAfterSetHost(matchId, targetName, redshift);
        else alert('Failed: ' + (d.message || 'Unknown'));
    })
    .catch(() => alert('An error occurred'))
    .finally(() => _setCardBusy(targetName, false));
}

function unsetHost(targetName) {
    if (!confirm(`Clear the host for ${targetName}?`)) return;
    _setCardBusy(targetName, true);
    fetch('/api/unset_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName })
    })
    .then(r => r.json())
    .then(d => {
        if (d.success) _updateUIAfterUnsetHost(targetName);
        else alert('Failed: ' + (d.message || 'Unknown'));
    })
    .catch(() => alert('An error occurred'))
    .finally(() => _setCardBusy(targetName, false));
}

// ── Object status ─────────────────────────────────────────────────────────
function _postStatusAPI(targetName, status) {
    return fetch('/api/set_object_status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName, status })
    }).then(r => r.json());
}

function markChecked(targetName) {
    if (!confirm(`Mark ${targetName} as Checked (Snoozed)?`)) return;
    _setCardBusy(targetName, true);
    _postStatusAPI(targetName, 'snoozed')
        .then(d => { if (d.success) _updateUIAfterMarkChecked(targetName); else alert('Failed: ' + (d.message || 'Unknown')); })
        .catch(() => alert('An error occurred'))
        .finally(() => _setCardBusy(targetName, false));
}

function markNoHost(targetName) {
    if (!confirm(`Mark ${targetName} as having no host?`)) return;
    _setCardBusy(targetName, true);
    fetch('/api/mark_no_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName })
    })
    .then(r => r.json())
    .then(d => { if (d.success) _updateUIAfterMarkNoHost(targetName); else alert('Failed: ' + (d.message || 'Unknown')); })
    .catch(() => alert('An error occurred'))
    .finally(() => _setCardBusy(targetName, false));
}

function unmarkNoHost(targetName) {
    if (!confirm(`Remove "No Host" decision for ${targetName}?`)) return;
    _setCardBusy(targetName, true);
    // Reuse unset_host: sets is_host=False + status → Inbox
    fetch('/api/unset_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName })
    })
    .then(r => r.json())
    .then(d => { if (d.success) _updateUIAfterUnsetHost(targetName); else alert('Failed: ' + (d.message || 'Unknown')); })
    .catch(() => alert('An error occurred'))
    .finally(() => _setCardBusy(targetName, false));
}

// ── DOM helpers shared across update functions ────────────────────────────
function _getSummaryRow(targetName) { return document.getElementById(`summary-row-${targetName}`); }
function _getCardIdx(targetName) {
    const row = _getSummaryRow(targetName);
    return row ? parseInt(row.dataset.cardIndex) : -1;
}
function _getCard(targetName) {
    const idx = _getCardIdx(targetName);
    return idx >= 0 ? document.getElementById(`card-${idx}`) : null;
}

function _setCardBusy(targetName, busy, message = 'Updating card…') {
    const card = _getCard(targetName);
    if (!card) return;

    let overlay = card.querySelector('.card-busy-overlay');
    if (busy) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'card-busy-overlay';
            overlay.setAttribute('role', 'status');
            overlay.setAttribute('aria-live', 'polite');
            card.appendChild(overlay);
        }
        overlay.innerHTML = `<div class="card-busy-box"><span class="tracker-spinner card-busy-spinner"></span><span>${message}</span></div>`;
        card.classList.add('card-busy');
        card.setAttribute('aria-busy', 'true');
        card.querySelectorAll('button').forEach(btn => {
            if (!btn.dataset.busyWasDisabled) {
                btn.dataset.busyWasDisabled = btn.disabled ? 'true' : 'false';
            }
            btn.disabled = true;
        });
        return;
    }

    card.classList.remove('card-busy');
    card.removeAttribute('aria-busy');
    card.querySelectorAll('button[data-busy-was-disabled]').forEach(btn => {
        btn.disabled = btn.dataset.busyWasDisabled === 'true';
        delete btn.dataset.busyWasDisabled;
    });
    if (overlay) overlay.remove();
}

// ── After setHost: is_host=True, status=followup ──────────────────────────
function _updateUIAfterSetHost(matchId, targetName, redshift) {
    // 1. Summary row
    const row = _getSummaryRow(targetName);
    if (row) {
        row.dataset.hasHost = 'true';
        row.dataset.status  = 'followup';
        row.classList.remove('row-unreviewed');
    }
    const hostCell = document.getElementById(`host-cell-${targetName}`);
    if (hostCell) hostCell.innerHTML = '<span class="badge-host" title="Host confirmed">✓ HOST</span>';
    const statusCell = document.getElementById(`status-cell-${targetName}`);
    if (statusCell) statusCell.innerHTML = '<span class="badge-followup">⬤ Follow-up</span>';

    // 2. Card
    const card = _getCard(targetName);
    if (!card) return;
    card.dataset.status = 'followup';
    card.classList.remove('card-unreviewed');

    const badge = document.getElementById(`card-status-${targetName}`);
    if (badge) badge.innerHTML = '<span class="badge-followup">⬤ Follow-up</span>';

    const actionBtns = card.querySelector('.card-action-buttons');
    if (actionBtns) actionBtns.innerHTML = ''; // no No Host when is_host=True

    // 3. Match table
    card.querySelectorAll('.match-detail-table tbody tr').forEach(row2 => {
        const actionCell = row2.querySelector('td:last-child');
        if (!actionCell) return;
        if (String(row2.dataset.matchId) === String(matchId)) {
            row2.dataset.isHost = 'true';
            actionCell.innerHTML =
                `<span class="badge-host">✓ HOST</span>
                 <button class="btn-action btn-remove" onclick="unsetHost('${targetName}')" title="Clear host">Remove</button>
                 <button class="btn-action btn-checked" onclick="markChecked('${targetName}')" title="Host confirmed, no follow-up needed">Check ✓</button>`;
        } else {
            row2.dataset.isHost = 'false';
            actionCell.innerHTML = `<button class="btn-action btn-set-host" disabled title="Another match is already the host">Set Host</button>`;
        }
    });
}

// ── After unsetHost / unmarkNoHost: is_host=False, status=object (Inbox) ──
function _updateUIAfterUnsetHost(targetName) {
    const row = _getSummaryRow(targetName);
    if (row) {
        row.dataset.hasHost = 'false';
        row.dataset.status  = 'object';
        row.classList.add('row-unreviewed');
    }
    const hostCell = document.getElementById(`host-cell-${targetName}`);
    if (hostCell) hostCell.innerHTML = '<span style="color:#444;">—</span>';
    const statusCell = document.getElementById(`status-cell-${targetName}`);
    if (statusCell) statusCell.innerHTML = '<span class="badge-unreviewed">! Review</span>';

    const card = _getCard(targetName);
    if (!card) return;
    card.dataset.status = 'object';
    card.classList.add('card-unreviewed');

    const badge = document.getElementById(`card-status-${targetName}`);
    if (badge) badge.innerHTML = '<span class="badge-unreviewed">! Needs Review</span>';

    const actionBtns = card.querySelector('.card-action-buttons');
    if (actionBtns)
        actionBtns.innerHTML =
            `<button class="btn-action btn-nohost btn-prominent"
                onclick="markNoHost('${targetName}')"
                title="Mark target as having no host">No Host</button>`;

    card.querySelectorAll('.match-detail-table tbody tr[data-is-host="true"]').forEach(row2 => {
        const actionCell = row2.querySelector('td:last-child');
        if (!actionCell) return;
        const mId      = row2.dataset.matchId      || '';
        const mZ       = row2.dataset.matchZ       || '';
        const mCatalog = row2.dataset.matchCatalog || '';
        row2.dataset.isHost = 'false';
        actionCell.innerHTML = mId
            ? `<button class="btn-action btn-set-host btn-prominent"
                onclick="setHost('${mId}', '${targetName}', '${mZ}', '${mCatalog}')">Set Host</button>`
            : `<button class="btn-action btn-set-host" onclick="location.reload()">Set Host</button>`;
    });
    // Enable all other Set Host buttons
    card.querySelectorAll('.match-detail-table tbody tr[data-is-host="false"]').forEach(row2 => {
        const actionCell = row2.querySelector('td:last-child');
        if (!actionCell) return;
        const btn = actionCell.querySelector('.btn-set-host');
        if (btn && btn.disabled) btn.disabled = false;
    });
}

// ── After markChecked: is_host stays True, status=snoozed ────────────────
function _updateUIAfterMarkChecked(targetName) {
    const row = _getSummaryRow(targetName);
    if (row) { row.dataset.status = 'snoozed'; row.classList.remove('row-unreviewed'); }
    const statusCell = document.getElementById(`status-cell-${targetName}`);
    if (statusCell) statusCell.innerHTML = '<span class="badge-checked">✓ Checked</span>';

    const card = _getCard(targetName);
    if (!card) return;
    card.dataset.status = 'snoozed';
    card.classList.remove('card-unreviewed');

    const badge = document.getElementById(`card-status-${targetName}`);
    if (badge) badge.innerHTML = '<span class="badge-checked">✓ Checked</span>';

    const actionBtns = card.querySelector('.card-action-buttons');
    if (actionBtns) actionBtns.innerHTML = ''; // no further actions when checked

    // HOST match row: keep badge + Remove, remove Check ✓
    card.querySelectorAll('.match-detail-table tbody tr[data-is-host="true"]').forEach(row2 => {
        const actionCell = row2.querySelector('td:last-child');
        if (actionCell)
            actionCell.innerHTML =
                `<span class="badge-host">✓ HOST</span>
                 <button class="btn-action btn-remove" onclick="unsetHost('${targetName}')" title="Clear host">Remove</button>`;
    });
}

// ── After markNoHost: is_host=False, status=snoozed ──────────────────────
function _updateUIAfterMarkNoHost(targetName) {
    const row = _getSummaryRow(targetName);
    if (row) {
        row.dataset.hasHost = 'false';
        row.dataset.status  = 'snoozed';
        row.classList.remove('row-unreviewed');
    }
    const hostCell = document.getElementById(`host-cell-${targetName}`);
    if (hostCell) hostCell.innerHTML = '<span style="color:#444;">—</span>';
    const statusCell = document.getElementById(`status-cell-${targetName}`);
    if (statusCell) statusCell.innerHTML = '<span class="badge-nohost">✗ No Host</span>';

    const card = _getCard(targetName);
    if (!card) return;
    card.dataset.status = 'snoozed';
    card.classList.remove('card-unreviewed');

    const badge = document.getElementById(`card-status-${targetName}`);
    if (badge) badge.innerHTML = '<span class="badge-nohost">✗ No Host</span>';

    const actionBtns = card.querySelector('.card-action-buttons');
    if (actionBtns)
        actionBtns.innerHTML =
            `<button class="btn-action btn-remove"
                onclick="unmarkNoHost('${targetName}')" title="Undo no-host decision">Remove</button>`;

    // All match rows → '—'
    card.querySelectorAll('.match-detail-table tbody tr').forEach(row2 => {
        const actionCell = row2.querySelector('td:last-child');
        if (actionCell) actionCell.innerHTML = '<span style="color:#444;">—</span>';
        row2.dataset.isHost = 'false';
    });
}

// ── Image lightbox ────────────────────────────────────────────────────────
function openImgModal(img) {
    const modal = document.getElementById('imgModal');
    const src   = document.getElementById('imgModalSrc');
    if (!modal || !src) return;
    src.src = img.src;
    modal.style.display = 'flex';
}

function closeImgModal() {
    const modal = document.getElementById('imgModal');
    if (modal) modal.style.display = 'none';
}

// ── Back-to-top ───────────────────────────────────────────────────────────
function _initBackToTop() {
    const btn = document.getElementById('backToTopBtn');
    if (!btn) return;
    window.addEventListener('scroll', () => {
        btn.style.display = window.scrollY > 300 ? 'block' : 'none';
    }, { passive: true });
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.target-card');
    _total = cards.length;

    const totalEl = document.getElementById('cardTotal');
    if (totalEl) totalEl.textContent = _total;

    // Count unreviewed and show badge
    let unreviewedCount = 0;
    cards.forEach(c => { if (c.dataset.status === 'object') unreviewedCount++; });
    const unreviewedBadge = document.getElementById('unreviewedCountBadge');
    if (unreviewedBadge && unreviewedCount > 0) {
        unreviewedBadge.textContent = `${unreviewedCount} unreviewed`;
        unreviewedBadge.style.display = '';
    }

    // Collapse tracker panel on init (avoids flashing open)
    const panel = document.getElementById('followupTrackerPanel');
    if (panel) panel.classList.add('collapsed');

    // Silently pre-fetch tracker count to update badge number
    fetch('/api/detect/followup_tracker')
        .then(r => r.json())
        .then(data => {
            const badge = document.getElementById('trackerCountBadge');
            if (data.success && badge) badge.textContent = (data.tracker || []).length;
        })
        .catch(() => {});

    if (_total > 0) _showCard(0);

    _initBackToTop();
});
