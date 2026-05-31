// ── Flag toggle ───────────────────────────────────────────────────────────────
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

// ── Date selector ─────────────────────────────────────────────────────────────
function changeDate(selectElement) {
    const date = selectElement.value;
    window.location.href = date ? `/detect?detect_results=${date}` : '/detect';
}

// ── Status badge helpers ──────────────────────────────────────────────────────
const _STATUS_BADGE_HTML = {
    followup:        '<span class="badge-followup">⬤ Follow-up</span>',
    finished_host:   '<span class="badge-checked">✓ Checked</span>',
    finished_nohost: '<span class="badge-nohost">✗ No Host</span>',
    object:          '<span style="color:#555;">—</span>',  // Empty/no decision state
};

function _patchSummaryRow(targetName, statusKey) {
    const cell = document.getElementById('status-cell-' + targetName);
    if (cell) cell.innerHTML = _STATUS_BADGE_HTML[statusKey] || '<span style="color:#555;">—</span>';
    const cardBadge = document.getElementById('card-status-' + targetName);
    if (cardBadge) cardBadge.innerHTML = _STATUS_BADGE_HTML[statusKey] || '';
}

function _patchHostCell(targetName, isHost) {
    const cell = document.getElementById('host-cell-' + targetName);
    if (!cell) return;
    cell.innerHTML = isHost
        ? '<span class="badge-host" title="Host confirmed">✓ HOST</span>'
        : '<span style="color:#555;">—</span>';
}

// ── Host management ───────────────────────────────────────────────────────────
function setHost(matchId, targetName, redshift, source) {
    if (!confirm(`Set this match as host for ${targetName}?\nThis will update the redshift and mark it as Follow-up.`)) return;
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
            // Update card header status badge and buttons
            const badgeEl = document.getElementById(`card-status-${targetName}`);
            if (badgeEl) {
                badgeEl.innerHTML = '<span class="badge-followup">⬭ Follow-up</span>';
            }
            // Hide "No Host" button since we now have a host
            const actionBtns = document.querySelector(`[id^="card-status-${targetName}"]`)?.closest('.card-header-actions')?.querySelector('.card-action-buttons');
            if (actionBtns) {
                actionBtns.innerHTML = '';
            }
            // Disable "Set Host" buttons for all other matches in this card (they should be disabled now)
            const card = document.getElementById(`card-${_currentCard}`);
            if (card) {
                const setHostBtns = card.querySelectorAll('.btn-set-host');
                setHostBtns.forEach(btn => {
                    if (!btn.disabled) {  // Only disable non-host buttons
                        btn.disabled = true;
                        btn.title = 'Another match is already the host';
                    }
                });
            }
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
            // Re-fetch actual status after unset
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

// ── Object status (Not Host / Check) ─────────────────────────────────────────
function _updateCardHeaderButtons(targetName, newStatus) {
    // Determine what buttons to show based on new status
    const buttonContainer = document.querySelector(`[id^="card-status-${targetName}"]`)?.closest('.card-header-actions')?.querySelector('.card-action-buttons');
    if (!buttonContainer) return;

    // Clear existing buttons
    buttonContainer.innerHTML = '';

    if (newStatus === 'finished_nohost') {
        // Marked as no host - show Remove button
        const btn = document.createElement('button');
        btn.className = 'btn-action btn-remove';
        btn.title = 'Undo no-host decision';
        btn.textContent = 'Remove';
        btn.onclick = () => unmarkNoHost(targetName);
        buttonContainer.appendChild(btn);
    } else if (newStatus === 'object') {
        // Back to initial/inbox state - show "No Host" button
        const btn = document.createElement('button');
        btn.className = 'btn-action btn-nohost';
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
            // Update summary table badge
            _patchSummaryRow(targetName, patchKey);
            // Update card header buttons based on new status
            _updateCardHeaderButtons(targetName, patchKey);
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
    if (!confirm(`Mark "${targetName}" as checked (host confirmed, no follow-up needed)?\nThis will set status to Finished.`)) return;
    _setObjectStatus(targetName, 'finished', 'finished_host');
}

function unmarkNoHost(targetName) {
    if (!confirm(`Undo "No Host" decision for "${targetName}"?\nThis will reset status back to Inbox.`)) return;
    _setObjectStatus(targetName, 'object', 'object');
}

// ── Card navigation ───────────────────────────────────────────────────────────
let _currentCard = 0;
const _plotInited = new Set();

function _allCards() {
    return document.querySelectorAll('.target-card');
}

function _totalCards() {
    return _allCards().length;
}

function _initPlotForCard(index) {
    if (_plotInited.has(index)) return;
    _plotInited.add(index);
    const card = document.getElementById('card-' + index);
    if (!card) return;
    const div = card.querySelector('.plotly-chart');
    if (!div) return;
    const raw = div.getAttribute('data-plot');
    if (!raw) return;
    try {
        const plotData = JSON.parse(raw);
        Plotly.newPlot(div.id, plotData.data, plotData.layout, plotData.config || { responsive: true });
    } catch (e) {
        console.error('Plotly init error for card', index, e);
    }
}

function showCard(index) {
    const cards = _allCards();
    const total = cards.length;
    if (total === 0) return;
    index = ((index % total) + total) % total;   // wrap

    cards.forEach(c => c.style.display = 'none');
    const current = document.getElementById('card-' + index);
    if (current) current.style.display = 'block';

    _currentCard = index;
    document.getElementById('cardCurrent').textContent = index + 1;

    // Highlight summary row
    document.querySelectorAll('#summaryTable tr[data-card-index]').forEach(r => {
        r.classList.toggle('summary-row-active', parseInt(r.dataset.cardIndex) === index);
    });

    // Lazy-init Plotly
    _initPlotForCard(index);

    // Scroll to card nav bar
    const bar = document.getElementById('cardNavBar');
    if (bar) bar.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function nextCard() { showCard(_currentCard + 1); }
function prevCard() { showCard(_currentCard - 1); }

function jumpToCard(index) {
    showCard(index);
}

// ── Image lightbox ────────────────────────────────────────────────────────────
function openImgModal(imgEl) {
    const modal = document.getElementById('imgModal');
    const modalImg = document.getElementById('imgModalSrc');
    modalImg.src = imgEl.src;
    modal.style.display = 'flex';
}
function closeImgModal() {
    document.getElementById('imgModal').style.display = 'none';
}

// Keyboard: left/right for cards, ESC for lightbox
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeImgModal(); return; }
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    if (e.key === 'ArrowRight') nextCard();
    else if (e.key === 'ArrowLeft') prevCard();
});

// ── Init on DOMContentLoaded ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const total = _totalCards();
    const totalEl = document.getElementById('cardTotal');
    if (totalEl) totalEl.textContent = total;

    // Init plot only for the first card
    if (total > 0) _initPlotForCard(0);

    // Back to top button
    const backBtn = document.getElementById('backToTopBtn');
    if (backBtn) {
        window.addEventListener('scroll', () => {
            backBtn.style.display = (document.documentElement.scrollTop > 300) ? 'block' : 'none';
        });
        backBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    }
});
