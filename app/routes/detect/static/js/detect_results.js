// ── Tracker: lazy load via API ────────────────────────────────────
const TRACKER_KEY      = 'detect_tracker_open';
const CARD_RESTORE_KEY = 'detect_card_restore';

function _absMagChip(am) {
    if (am === null || am === undefined) return '<span class="absmag-none">—</span>';
    am = parseFloat(am);
    let cls = am < -20 ? 'absmag-verybright'
            : am <= -18 ? 'absmag-peak'
            : am <= -15 ? 'absmag-fading'
            : 'absmag-dim';
    return `<span class="absmag-chip ${cls}">${am.toFixed(2)}</span>`;
}

function _statusBadge(status) {
    if (status === 'followup') return '<span class="badge-followup">⬤ FU</span>';
    if (status === 'finished') return '<span class="badge-checked">✓ Done</span>';
    return '<span style="color:#555;">—</span>';
}

function loadTracker(force = false) {
    const panel = document.getElementById('followupTrackerPanel');
    if (!panel) return;
    // Don't re-fetch if already loaded (unless forced)
    if (!force && panel.dataset.loaded === '1') return;

    const body     = document.getElementById('trackerBody');
    const subtitle = document.getElementById('trackerSubtitle');
    const badge    = document.getElementById('trackerCountBadge');
    body.innerHTML = '<div class="tracker-loading"><span class="tracker-spinner"></span> Loading…</div>';

    fetch('/api/detect/followup_tracker')
        .then(r => r.json())
        .then(data => {
            if (!data.success) { body.innerHTML = '<div class="tracker-empty">Failed to load tracker.</div>'; return; }
            const items = data.tracker || [];
            badge.textContent = items.length;
            if (subtitle) subtitle.textContent = `${items.length} objects · latest photometry`;
            panel.dataset.loaded = '1';

            if (!items.length) {
                body.innerHTML = '<div class="tracker-empty">No objects currently in follow-up.</div>';
                return;
            }

            const rows = items.map(fu => `
                <tr>
                    <td><a href="/object/${fu.name}" class="tracker-obj-link" target="_blank">${fu.name}</a></td>
                    <td class="td-catalog">${fu.catalog_name}</td>
                    <td>${fu.separation_arcsec != null ? fu.separation_arcsec.toFixed(2) : '—'}</td>
                    <td>${fu.z != null ? fu.z.toFixed(4) : '—'}</td>
                    <td class="td-absmag">${_absMagChip(fu.abs_mag)}</td>
                    <td>${_statusBadge(fu.obj_status)}</td>
                    <td class="td-date">${fu.discoverydate}</td>
                </tr>`).join('');

            body.innerHTML = `
                <div class="tracker-table-wrap">
                    <table class="tracker-table">
                        <thead><tr>
                            <th>Object</th><th>Host (Catalog)</th><th>Sep (")</th>
                            <th>Z</th><th class="th-absmag">Abs Mag</th>
                            <th>Status</th><th>Discovery</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
        })
        .catch(() => { body.innerHTML = '<div class="tracker-empty">Network error loading tracker.</div>'; });
}

// ── Tracker toggle ────────────────────────────────────────────────
function toggleTracker() {
    const panel = document.getElementById('followupTrackerPanel');
    const btn   = document.getElementById('trackerToggleBtn');
    if (!panel) return;
    const collapsed = panel.classList.toggle('collapsed');
    btn?.classList.toggle('active', !collapsed);
    localStorage.setItem(TRACKER_KEY, collapsed ? '0' : '1');
    // Lazy-load when opening for the first time
    if (!collapsed) loadTracker();
}

// ── Page refresh (preserves card position) ────────────────────────
function refreshPage() {
    sessionStorage.setItem(CARD_RESTORE_KEY, String(_currentCard));
    window.location.reload();
}

// ── Table filter ──────────────────────────────────────────────────
function filterSummary(btn, filter) {
    document.querySelectorAll('.tbl-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('#summaryTable tbody tr').forEach(tr => {
        const status  = tr.dataset.status  || '';
        const hasHost = tr.dataset.hasHost === 'true';
        let show = true;
        if      (filter === 'unreviewed') show = status === 'object';
        else if (filter === 'followup')   show = status === 'followup';
        else if (filter === 'host')       show = hasHost;
        else if (filter === 'nohost')     show = status === 'finished' && !hasHost;
        tr.style.display = show ? '' : 'none';
    });
}

// ── Flag toggle ───────────────────────────────────────────────────
function toggleFlag(id, element) {
    const isActive = element.classList.contains('active');
    element.style.opacity = '0.5';
    fetch('/api/toggle_flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, flag: !isActive })
    })
    .then(r => r.json())
    .then(data => {
        element.style.opacity = '1';
        if (data.success) element.classList.toggle('active', !isActive);
        else alert('Failed to update flag');
    })
    .catch(() => { element.style.opacity = '1'; alert('An error occurred'); });
}

// ── Date selector ─────────────────────────────────────────────────
function changeDate(selectElement) {
    const date = selectElement.value;
    window.location.href = date ? `/detect?detect_results=${date}` : '/detect';
}

// ── Status badge helpers ──────────────────────────────────────────
const _STATUS_BADGE_HTML = {
    followup:        '<span class="badge-followup">⬤ Follow-up</span>',
    finished_host:   '<span class="badge-checked">✓ Checked</span>',
    finished_nohost: '<span class="badge-nohost">✗ No Host</span>',
    object:          '<span class="badge-unreviewed">! Needs Review</span>',
};

function _patchSummaryRow(targetName, statusKey) {
    const cell = document.getElementById('status-cell-' + targetName);
    if (cell) cell.innerHTML = _STATUS_BADGE_HTML[statusKey] || '<span style="color:#444;">—</span>';
    const cardBadge = document.getElementById('card-status-' + targetName);
    if (cardBadge) cardBadge.innerHTML = _STATUS_BADGE_HTML[statusKey] || '';
}

function _patchHostCell(targetName, isHost) {
    const cell = document.getElementById('host-cell-' + targetName);
    if (!cell) return;
    cell.innerHTML = isHost
        ? '<span class="badge-host" title="Host confirmed">✓ HOST</span>'
        : '<span style="color:#444;">—</span>';
}

// ── Host management ───────────────────────────────────────────────
function setHost(matchId, targetName, redshift, source) {
    if (!confirm(`Set this match as host for ${targetName}?\nThis will update the redshift and mark as Follow-up.`)) return;
    fetch('/api/set_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: matchId, target_name: targetName, redshift, source })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _patchHostCell(targetName, true);
            _patchSummaryRow(targetName, 'followup');
            _patchCardDataStatus(targetName, 'followup');
            const badgeEl = document.getElementById(`card-status-${targetName}`);
            if (badgeEl) badgeEl.innerHTML = '<span class="badge-followup">⬤ Follow-up</span>';
            const card = document.getElementById(`card-${_currentCard}`);
            if (card) {
                card.querySelectorAll('.btn-set-host').forEach(btn => {
                    if (!btn.disabled) { btn.disabled = true; btn.title = 'Another match is already the host'; }
                });
            }
            const actionBtns = document.querySelector(`[id^="card-status-${targetName}"]`)
                ?.closest('.card-header-actions')?.querySelector('.card-action-buttons');
            if (actionBtns) actionBtns.innerHTML = '';
        } else {
            alert('Failed to set host: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(() => alert('An error occurred'));
}

function unsetHost(targetName) {
    if (!confirm(`Clear the host for ${targetName}?`)) return;
    fetch('/api/unset_host', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _patchHostCell(targetName, false);
            fetch('/api/get_object_status?name=' + encodeURIComponent(targetName))
                .then(r => r.json())
                .then(d => {
                    if (d.success) _patchSummaryRow(targetName, d.obj_status === 'followup' ? 'followup' : '');
                });
        } else {
            alert('Failed to clear host: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(() => alert('An error occurred'));
}

// ── Object status ─────────────────────────────────────────────────
function _patchCardDataStatus(targetName, newStatus) {
    const row = document.getElementById('summary-row-' + targetName);
    if (row) {
        row.dataset.status = newStatus;
        row.classList.toggle('row-unreviewed', newStatus === 'object');
    }
    document.querySelectorAll('.target-card').forEach(c => {
        const link = c.querySelector('.card-obj-title a');
        if (link && link.textContent.includes(targetName)) {
            c.dataset.status = newStatus;
            c.classList.toggle('card-unreviewed', newStatus === 'object');
        }
    });
    _updateUnreviewedCount();
}

function _updateCardHeaderButtons(targetName, newStatus) {
    const buttonContainer = document.querySelector(`[id^="card-status-${targetName}"]`)
        ?.closest('.card-header-actions')?.querySelector('.card-action-buttons');
    if (!buttonContainer) return;
    buttonContainer.innerHTML = '';
    if (newStatus === 'finished_nohost') {
        const btn = document.createElement('button');
        btn.className = 'btn-action btn-remove';
        btn.title = 'Undo no-host decision';
        btn.textContent = 'Remove';
        btn.onclick = () => unmarkNoHost(targetName);
        buttonContainer.appendChild(btn);
    } else if (newStatus === 'object') {
        const btn = document.createElement('button');
        btn.className = 'btn-action btn-nohost btn-prominent';
        btn.title = 'Mark target as having no host';
        btn.textContent = 'No Host';
        btn.onclick = () => markNoHost(targetName);
        buttonContainer.appendChild(btn);
    }
}

function _setObjectStatus(targetName, status, patchKey) {
    fetch('/api/set_object_status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_name: targetName, status })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _patchSummaryRow(targetName, patchKey);
            _updateCardHeaderButtons(targetName, patchKey);
            const dsStatus = patchKey.startsWith('finished') ? 'finished'
                           : patchKey === 'followup' ? 'followup' : 'object';
            _patchCardDataStatus(targetName, dsStatus);
        } else {
            alert('Failed: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(err => { console.error(err); alert('An error occurred'); });
}

function markNoHost(targetName) {
    if (!confirm(`Mark "${targetName}" as having no host?\nThis will set status to Finished.`)) return;
    _setObjectStatus(targetName, 'finished', 'finished_nohost');
}
function markChecked(targetName) {
    if (!confirm(`Mark "${targetName}" as checked (host confirmed)?\nThis will set status to Finished.`)) return;
    _setObjectStatus(targetName, 'finished', 'finished_host');
}
function unmarkNoHost(targetName) {
    if (!confirm(`Undo "No Host" for "${targetName}"? This will reset status to Inbox.`)) return;
    _setObjectStatus(targetName, 'object', 'object');
}

// ── Unreviewed helpers ────────────────────────────────────────────
function _updateUnreviewedCount() {
    const n = Array.from(_allCards()).filter(c => c.dataset.status === 'object').length;
    const badge = document.getElementById('unreviewedCountBadge');
    if (badge) {
        badge.textContent = n + ' unreviewed';
        badge.style.display = n > 0 ? '' : 'none';
    }
    _updateNextUnreviewedBtn();
}

function _updateNextUnreviewedBtn() {
    const btn = document.getElementById('nextUnreviewedBtn');
    if (!btn) return;
    const hasUnreviewed = Array.from(_allCards()).some(c => c.dataset.status === 'object');
    btn.textContent = hasUnreviewed ? 'Next Unreviewed →' : 'All reviewed ✓';
    btn.disabled    = !hasUnreviewed;
}

function nextUnreviewed() {
    const cards = Array.from(_allCards());
    const total = cards.length;
    for (let i = 1; i <= total; i++) {
        const idx  = (_currentCard + i) % total;
        if (cards[idx]?.dataset.status === 'object') { showCard(idx); return; }
    }
}

// ── Card navigation ───────────────────────────────────────────────
let _currentCard = 0;
const _plotInited = new Set();
const _plotCache = new Map();
const _plotRequests = new Map();

function _allCards()  { return document.querySelectorAll('.target-card'); }
function _totalCards(){ return _allCards().length; }

function _setCardLcStatus(index, message, isError = false) {
    const el = document.getElementById(`lc-status-${index}`);
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('error', !!isError);
}

function _renderCardPlaceholder(div, message, isError = false) {
    if (!div) return;
    div.innerHTML = `<div class="card-no-data" style="height:360px;${isError ? 'color:#ff7f7f;' : ''}">${message}</div>`;
}

function _renderCardPlot(div, rawPlot, index) {
    if (!div || !rawPlot) return false;
    try {
        const plotData = typeof rawPlot === 'string' ? JSON.parse(rawPlot) : rawPlot;
        Plotly.newPlot(div.id, plotData.data, plotData.layout, plotData.config || { responsive: true });
        _setCardLcStatus(index, '');
        return true;
    } catch (e) {
        console.error('Plotly init error for card', index, e);
        _renderCardPlaceholder(div, 'Failed to render lightcurve', true);
        _setCardLcStatus(index, 'Plot render failed', true);
        return false;
    }
}

function _fetchCardPlotPayload(targetName, force = false) {
    if (!targetName) return Promise.resolve({ success: false, message: 'Missing target name' });
    if (!force && _plotCache.has(targetName)) return Promise.resolve(_plotCache.get(targetName));
    if (!force && _plotRequests.has(targetName)) return _plotRequests.get(targetName);

    const url = `/api/detect/lightcurve/${encodeURIComponent(targetName)}${force ? '?refresh=1' : ''}`;
    const req = fetch(url)
        .then(r => r.json())
        .then(payload => {
            if (payload && payload.success) {
                _plotCache.set(targetName, payload);
            }
            return payload;
        })
        .finally(() => {
            _plotRequests.delete(targetName);
        });

    _plotRequests.set(targetName, req);
    return req;
}

function _initPlotForCard(index, force = false) {
    if (!force && _plotInited.has(index)) return;

    const card = document.getElementById('card-' + index);
    if (!card) return;
    const div = card.querySelector('.plotly-chart');
    if (!div) return;

    const targetName = div.dataset.targetName || '';
    if (force && targetName) {
        _plotCache.delete(targetName);
        _plotInited.delete(index);
    }

    const embedded = !force ? div.getAttribute('data-plot') : null;
    if (embedded && _renderCardPlot(div, embedded, index)) {
        _plotInited.add(index);
        if (targetName && !_plotCache.has(targetName)) {
            _plotCache.set(targetName, { success: true, plot_json: embedded });
        }
        div.removeAttribute('data-plot');
        return;
    }

    _renderCardPlaceholder(div, 'Loading lightcurve...');
    _setCardLcStatus(index, 'Loading...');

    _fetchCardPlotPayload(targetName, force)
        .then(payload => {
            if (!payload || !payload.success) {
                _renderCardPlaceholder(div, (payload && payload.message) || 'Failed to load lightcurve', true);
                _setCardLcStatus(index, 'Load failed', true);
                return;
            }

            if (!payload.plot_json) {
                _renderCardPlaceholder(div, payload.message || 'No photometry data available');
                _setCardLcStatus(index, payload.cached ? 'Cached' : 'No LC data');
                _plotInited.add(index);
                return;
            }

            if (_renderCardPlot(div, payload.plot_json, index)) {
                _plotInited.add(index);
                _setCardLcStatus(index, payload.cached ? 'Cached' : 'Loaded');
            }
        })
        .catch(err => {
            console.error('LC load error', targetName, err);
            _renderCardPlaceholder(div, 'Network error loading lightcurve', true);
            _setCardLcStatus(index, 'Network error', true);
        });
}

function fetchCardLightcurve(targetName, index) {
    if (!targetName) return;
    if (!confirm(`Fetch photometry for ${targetName} from TNS? This may take a moment.`)) return;

    _setCardLcStatus(index, 'Fetching latest LC...');
    fetch(`/api/object/${encodeURIComponent(targetName)}/fetch_photometry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                alert('Failed to fetch LC: ' + (data.error || data.message || 'Unknown error'));
                _setCardLcStatus(index, 'Fetch failed', true);
                return;
            }
            _plotCache.delete(targetName);
            _plotInited.delete(index);
            _setCardLcStatus(index, 'Fetched. Refreshing plot...');
            _initPlotForCard(index, true);
        })
        .catch(() => {
            alert('An error occurred while fetching LC');
            _setCardLcStatus(index, 'Fetch failed', true);
        });
}

function refreshCardLightcurve(targetName, index) {
    if (!targetName) return;
    _setCardLcStatus(index, 'Refreshing...');
    _initPlotForCard(index, true);
}

function showCard(index) {
    const cards = _allCards();
    const total = cards.length;
    if (total === 0) return;
    index = ((index % total) + total) % total;
    cards.forEach(c => c.style.display = 'none');
    const current = document.getElementById('card-' + index);
    if (current) current.style.display = 'block';
    _currentCard = index;
    document.getElementById('cardCurrent').textContent = index + 1;

    // Show object name in nav bar
    const nameEl = document.getElementById('cardNavObjName');
    if (nameEl && current) {
        const titleLink = current.querySelector('.card-obj-title a');
        nameEl.textContent = titleLink
            ? titleLink.textContent.trim().replace(/↗\s*$/, '').trim()
            : '';
    }

    // Highlight summary row
    document.querySelectorAll('#summaryTable tr[data-card-index]').forEach(r => {
        r.classList.toggle('summary-row-active', parseInt(r.dataset.cardIndex) === index);
    });

    _updateNextUnreviewedBtn();
    _initPlotForCard(index);
    document.getElementById('cardNavBar')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function nextCard() { showCard(_currentCard + 1); }
function prevCard() { showCard(_currentCard - 1); }
function jumpToCard(index) { showCard(index); }

// ── Image lightbox ────────────────────────────────────────────────
function openImgModal(imgEl) {
    document.getElementById('imgModalSrc').src = imgEl.src;
    document.getElementById('imgModal').style.display = 'flex';
}
function closeImgModal() {
    document.getElementById('imgModal').style.display = 'none';
}

// Keyboard shortcuts
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeImgModal(); return; }
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    if (e.key === 'ArrowRight') nextCard();
    else if (e.key === 'ArrowLeft')  prevCard();
});

// ── Init ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Restore tracker open/closed state (default: open)
    const panel = document.getElementById('followupTrackerPanel');
    const btn   = document.getElementById('trackerToggleBtn');
    const trackerOpen = localStorage.getItem(TRACKER_KEY) !== '0';
    if (!trackerOpen && panel) {
        panel.classList.add('collapsed');
        btn?.classList.remove('active');
    } else {
        btn?.classList.add('active');
        loadTracker();   // lazy-load immediately if open
    }

    // Card count
    const total = _totalCards();
    const totalEl = document.getElementById('cardTotal');
    if (totalEl) totalEl.textContent = total;

    // Restore card position after a page refresh
    const savedCard = sessionStorage.getItem(CARD_RESTORE_KEY);
    if (savedCard !== null) {
        sessionStorage.removeItem(CARD_RESTORE_KEY);
        const idx = parseInt(savedCard, 10);
        if (!isNaN(idx) && idx > 0 && idx < total) {
            // Wait a tick for DOM to settle then jump
            requestAnimationFrame(() => showCard(idx));
        } else {
            if (total > 0) _initPlotForCard(0);
        }
    } else {
        if (total > 0) _initPlotForCard(0);
    }

    // Show first card name
    const firstCard = document.getElementById('card-0');
    const nameEl    = document.getElementById('cardNavObjName');
    if (nameEl && firstCard) {
        const titleLink = firstCard.querySelector('.card-obj-title a');
        nameEl.textContent = titleLink
            ? titleLink.textContent.trim().replace(/↗\s*$/, '').trim()
            : '';
    }

    // Unreviewed count (read from rendered data-status attrs)
    _updateUnreviewedCount();

    // Back to top
    const backBtn = document.getElementById('backToTopBtn');
    if (backBtn) {
        window.addEventListener('scroll', () => {
            backBtn.style.display = document.documentElement.scrollTop > 300 ? 'block' : 'none';
        });
        backBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    }
});
