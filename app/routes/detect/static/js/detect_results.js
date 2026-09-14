'use strict';
/* ═══════════════════════════════════════════════════════════════
   detect_results.js — DETECT review page
   — card navigation, DETECT verdict → action bar, one-key decisions
     (F follow-up / D done / N no host / R reopen), candidate table
     actions, interactive Plotly LC, follow-up tracker, lightbox.

   State lives on each card's data-* attributes:
     status        object | followup | snoozed | finished
     host-status   confirmed | review | none        (DETECT's verdict)
     host-match-id cross_matches.match_id of the current host row ('' = none)
     host-z        that row's redshift
     host-pinned   'true' when a person chose the host (survives re-runs)
     host-rejected 'true' when a person said "no host"
   ═══════════════════════════════════════════════════════════════ */

const CAN_EDIT = document.body.dataset.canEdit === 'true';

// ── In-memory LC cache ────────────────────────────────────────────────────
const _lcCache = new Map(); // target_name → plot_json string

// ── Card navigation ───────────────────────────────────────────────────────
let _cur   = 0;
let _total = 0;

function _showCard(idx) {
    if (idx < 0 || idx >= _total) return;

    const oldCard = document.getElementById(`card-${_cur}`);
    if (oldCard && _cur !== idx) {
        oldCard.style.display = 'none';
        const pd = document.getElementById(`plotly-card-${_cur}`);
        if (pd && pd._fullLayout) { try { Plotly.purge(pd); } catch (_) {} }
    }

    const newCard = document.getElementById(`card-${idx}`);
    if (newCard) newCard.style.display = '';
    _cur = idx;

    const el = document.getElementById('cardCurrent');
    if (el) el.textContent = idx + 1;

    const nameEl = document.getElementById('cardNavObjName');
    if (nameEl) nameEl.textContent = newCard ? (newCard.dataset.name || '') : '';

    document.querySelectorAll('.summary-row-active').forEach(r => r.classList.remove('summary-row-active'));
    const row = document.querySelector(`[data-card-index="${idx}"]`);
    if (row) row.classList.add('summary-row-active');

    const prevBtn = document.getElementById('prevCardBtn');
    const nextBtn = document.getElementById('nextCardBtn');
    if (prevBtn) prevBtn.disabled = idx === 0;
    if (nextBtn) nextBtn.disabled = idx === _total - 1;

    if (newCard) {
        const img = newCard.querySelector('img.lazy-img');
        if (img) _loadCardImage(img);
    }
    _autoFetchLC(idx);
}

function _loadCardImage(img) {
    if (!img) return;
    if (!img.dataset.src && img.complete && img.naturalWidth > 0) return;
    const container = img.parentElement;
    if (!container || container.querySelector('.card-img-loading')) return;

    const spinner = document.createElement('div');
    spinner.className = 'card-img-loading';
    spinner.innerHTML = '<span class="tracker-spinner"></span>';
    container.insertBefore(spinner, img);
    img.style.opacity = '0';
    img.style.transition = 'opacity 0.25s';
    const cleanup = () => { spinner.remove(); img.style.opacity = ''; img.style.transition = ''; };
    img.addEventListener('load',  cleanup, { once: true });
    img.addEventListener('error', () => spinner.remove(), { once: true });
    if (img.dataset.src) { img.src = img.dataset.src; img.removeAttribute('data-src'); }
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
    for (let i = 0; i < _cur; i++) {
        const c = document.getElementById(`card-${i}`);
        if (c && c.dataset.status === 'object') { jumpToCard(i); return; }
    }
    _toast('No pending objects left on this day.');
}

function _currentCard() { return document.getElementById(`card-${_cur}`); }

document.addEventListener('keydown', e => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const card = _currentCard();
    const name = card ? card.dataset.name : null;
    switch (e.key) {
        case 'ArrowRight': nextCard(); break;
        case 'ArrowLeft':  prevCard(); break;
        case 'Escape':     closeImgModal(); break;
        case '?':          toggleGuide(); break;
        case 'u': case 'U': nextUnreviewed(); break;
        case 'f': case 'F': if (CAN_EDIT && name) decideFollowup(name); break;
        case 'd': case 'D': if (CAN_EDIT && name) decideDone(name); break;
        case 'n': case 'N': if (CAN_EDIT && name) decideNoHost(name); break;
        case 'r': case 'R': if (CAN_EDIT && name) decideReopen(name); break;
        default: return;
    }
});

// ── Guide ─────────────────────────────────────────────────────────────────
function toggleGuide(force) {
    const g = document.getElementById('reviewGuide');
    if (!g) return;
    const open = force !== undefined ? force : g.classList.contains('collapsed');
    g.classList.toggle('collapsed', !open);
    const btn = document.getElementById('helpToggleBtn');
    if (btn) btn.classList.toggle('active', open);
    try { localStorage.setItem('detect.guide', open ? 'open' : 'closed'); } catch (_) {}
}

// ── Toast ─────────────────────────────────────────────────────────────────
let _toastTmo = null;
function _toast(msg, kind) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast' + (kind ? ' toast-' + kind : '');
    t.hidden = false;
    if (_toastTmo) clearTimeout(_toastTmo);
    _toastTmo = setTimeout(() => { t.hidden = true; }, 2600);
}

// ── Photometry: interactive Plotly ────────────────────────────────────────
function _autoFetchLC(cardIdx) {
    const plotDiv = document.getElementById(`plotly-card-${cardIdx}`);
    if (!plotDiv) return;
    const target = plotDiv.dataset.targetName;
    if (!target) return;
    if (_lcCache.has(target)) { _renderPlotly(plotDiv, _lcCache.get(target), target); return; }
    if (plotDiv.children.length > 0 && !plotDiv.querySelector('.card-lc-loading')) return;
    _fetchLC(target, cardIdx, false);
}

function fetchCardLightcurve(targetName, cardIdx) {
    const plotDiv  = document.getElementById(`plotly-card-${cardIdx}`);
    const statusEl = document.getElementById(`lc-status-${cardIdx}`);
    const fetchBtn = document.querySelector(`#card-${cardIdx} .card-lc-actions button:first-child`);
    if (!plotDiv) return;

    if (plotDiv._fullLayout) { try { Plotly.purge(plotDiv); } catch (_) {} }
    plotDiv.innerHTML = '<div class="card-lc-loading"><span class="tracker-spinner"></span>&nbsp;Fetching from TNS…</div>';
    if (statusEl) { statusEl.textContent = ''; statusEl.className = 'card-lc-status'; }
    if (fetchBtn) {
        fetchBtn.disabled = true;
        fetchBtn._origText = fetchBtn.innerHTML;
        fetchBtn.innerHTML = '<span class="tracker-spinner"></span>&nbsp;Fetching…';
    }
    _lcCache.delete(targetName);

    fetch(`/api/object/${encodeURIComponent(targetName)}/fetch_photometry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }
    })
    .then(r => r.json())
    .then(data => {
        if (fetchBtn) { fetchBtn.disabled = false; fetchBtn.innerHTML = fetchBtn._origText || 'Fetch LC'; }
        if (data.success) _fetchLC(targetName, cardIdx, true);
        else {
            plotDiv.innerHTML = `<div class="card-no-data">Fetch failed: ${data.error || 'Unknown error'}</div>`;
            if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'card-lc-status error'; }
        }
    })
    .catch(() => {
        if (fetchBtn) { fetchBtn.disabled = false; fetchBtn.innerHTML = fetchBtn._origText || 'Fetch LC'; }
        plotDiv.innerHTML = '<div class="card-no-data">Failed to fetch photometry</div>';
        if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'card-lc-status error'; }
    });
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

    if (!forceRefresh && _lcCache.has(targetName)) { _renderPlotly(plotDiv, _lcCache.get(targetName), targetName); return; }

    if (plotDiv._fullLayout) { try { Plotly.purge(plotDiv); } catch (_) {} }
    plotDiv.innerHTML = '<div class="card-lc-loading"><span class="tracker-spinner"></span>&nbsp;Loading photometry…</div>';
    if (statusEl) { statusEl.textContent = ''; statusEl.className = 'card-lc-status'; }

    if (typeof Plotly === 'undefined') { setTimeout(() => _fetchLC(targetName, cardIdx, forceRefresh), 200); return; }

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
        Plotly.newPlot(plotDiv, plotData.data, plotData.layout,
            Object.assign({ responsive: true, displayModeBar: true }, plotData.config || {}));
    } catch (err) {
        console.error('[detect] plot render error for', targetName, err);
        plotDiv.innerHTML = '<div class="card-no-data">Plot render failed</div>';
    }
}

function _formatAbsMag(value, sep) {
    const am = Number(value);
    if (!Number.isFinite(am)) return '<span class="absmag-none">—</span>';
    const label = am.toFixed(2);
    const sepValue = Number(sep);
    const dimStyle = Number.isFinite(sepValue) && sepValue >= 10 ? ' style="opacity:0.7"' : '';
    if (am <= -20) return `<span class="absmag-chip absmag-verybright"${dimStyle}>${label}</span>`;
    if (am <= -18) return `<span class="absmag-chip absmag-peak">${label}</span>`;
    if (am <= -15) return label;
    return `<span class="absmag-chip absmag-dim">${label}</span>`;
}

const _TAG_CLASS = {
    'Luminous': 'tag-hot', 'SLSN?': 'tag-hot', 'Too-bright': 'tag-hot', 'glSN?': 'tag-hot',
    'Nuclear': 'tag-cool', 'TDE?': 'tag-cool', 'Lens': 'tag-cool', 'Passive-host': 'tag-cool', 'Host-z': 'tag-cool',
    'Galactic': 'tag-veto', 'AGN': 'tag-veto', 'Classified': 'tag-veto', 'Star?': 'tag-veto',
};
function _tagChips(tags) {
    return (tags || []).filter(t => !String(t).startsWith('Host-') || t === 'Host-z')
        .map(t => `<span class="tag-chip ${_TAG_CLASS[t] || 'tag-warn'}">${t}</span>`).join('');
}
function _hostBadge(hs) {
    if (hs === 'confirmed') return '<span class="hs-badge hs-confirmed">● Confirmed host</span>';
    if (hs === 'review')    return '<span class="hs-badge hs-review">? Needs judgement</span>';
    return '<span class="hs-badge hs-none">○ No host</span>';
}
function _scoreChip(score) {
    const s = Number(score) || 0;
    const cls = s >= 7 ? 'hi' : s >= 3 ? 'mid' : s >= 0 ? 'lo' : 'neg';
    return `<span class="score-chip score-${cls}">${s}</span>`;
}

// ── Filter summary table ──────────────────────────────────────────────────
function filterSummary(btn, filter) {
    document.querySelectorAll('.tbl-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('#summaryTable tbody tr').forEach(row => {
        const status = row.dataset.status || '';
        const hs     = row.dataset.hostStatus || '';
        let show = false;
        switch (filter) {
            case 'all':       show = true; break;
            case 'pending':   show = status === 'object'; break;
            case 'review':    show = hs === 'review'; break;
            case 'confirmed': show = hs === 'confirmed'; break;
            case 'nohost':    show = hs === 'none'; break;
            case 'followup':  show = status === 'followup'; break;
            case 'done':      show = status === 'snoozed' || status === 'finished'; break;
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
            if (!data.success) { body.innerHTML = '<div class="tracker-empty">Failed to load tracker.</div>'; return; }
            const tracker = data.tracker || [];
            if (data.building && tracker.length === 0) {
                body.innerHTML = '<div class="tracker-loading"><span class="tracker-spinner"></span> Building tracker…</div>';
                if (_trackerRetryTmo) clearTimeout(_trackerRetryTmo);
                _trackerRetryTmo = setTimeout(() => loadTracker(false), 3000);
                return;
            }
            _trackerLoaded = true;
            const subtitle = document.getElementById('trackerSubtitle');
            const badge    = document.getElementById('trackerCountBadge');
            if (subtitle) subtitle.textContent = `${tracker.length} follow-up objects · re-screened by DETECT every day`;
            if (badge)    badge.textContent    = tracker.length;
            if (tracker.length === 0) { body.innerHTML = '<div class="tracker-empty">No follow-up objects yet.</div>'; return; }

            let html = '<div class="tracker-table-wrap"><table class="tracker-table"><thead><tr>'
                + '<th>Object</th><th>Score</th><th>Host</th><th>Tags</th>'
                + '<th class="th-absmag">M</th><th>z</th><th>Catalog</th><th>Sep (")</th>'
                + '<th class="td-date">Discovery</th><th class="td-date">DETECT run</th>'
                + '</tr></thead><tbody>';
            tracker.forEach(item => {
                const src = item.abs_mag_source === 'peak' ? `peak (${item.abs_mag_band || ''})` : item.abs_mag_source === 'discovery' ? 'discovery mag' : '';
                html += `<tr>
                    <td><a href="/object/${item.name}" class="tracker-obj-link" target="_blank" rel="noopener noreferrer">${item.name}</a></td>
                    <td style="text-align:center;">${item.score != null ? _scoreChip(item.score) : '—'}</td>
                    <td>${item.host_status ? _hostBadge(item.host_status) : '—'}</td>
                    <td class="td-tags">${_tagChips(item.tags)}</td>
                    <td class="td-absmag" title="${src}">${_formatAbsMag(item.abs_mag, item.separation_arcsec)}</td>
                    <td>${item.z != null ? item.z.toFixed(4) : '—'}</td>
                    <td class="td-catalog">${item.catalog_name}</td>
                    <td>${item.separation_arcsec != null ? item.separation_arcsec.toFixed(2) : '—'}</td>
                    <td class="td-date">${item.discoverydate}</td>
                    <td class="td-date">${item.detect_run_date || '—'}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
            body.innerHTML = html;
        })
        .catch(() => { body.innerHTML = '<div class="tracker-empty">Network error loading tracker.</div>'; });
}

// ── Flag toggle ───────────────────────────────────────────────────────────
function toggleFlag(id, element) {
    event.stopPropagation();
    const newFlag = !element.classList.contains('active');
    element.style.opacity = '0.5';
    fetch('/api/toggle_flag', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, flag: newFlag })
    })
    .then(r => r.json())
    .then(data => {
        element.style.opacity = '1';
        if (data.success) element.classList.toggle('active', newFlag);
        else _toast('Failed to update flag', 'error');
    })
    .catch(() => { element.style.opacity = '1'; _toast('An error occurred', 'error'); });
}

function changeDate(sel) {
    const date = sel.value;
    window.location.href = date ? `/detect?detect_results=${date}` : '/detect';
}
function refreshPage() { location.reload(); }

// ═══════════════════════════════════════════════════════════════════════════
//  Decisions
// ═══════════════════════════════════════════════════════════════════════════
function _cardByName(name) { return document.querySelector(`.target-card[data-name="${CSS.escape(name)}"]`); }
function _rowByName(name)  { return document.getElementById(`summary-row-${name}`); }

function _post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => r.json());
}

function _setCardBusy(card, busy, message = 'Saving…') {
    if (!card) return;
    let overlay = card.querySelector('.card-busy-overlay');
    if (busy) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'card-busy-overlay';
            overlay.setAttribute('role', 'status');
            card.appendChild(overlay);
        }
        overlay.innerHTML = `<div class="card-busy-box"><span class="tracker-spinner card-busy-spinner"></span><span>${message}</span></div>`;
        card.classList.add('card-busy');
        return;
    }
    card.classList.remove('card-busy');
    if (overlay) overlay.remove();
}

/** Follow-up: accept the current host (pinning it if a person has not yet), status → Follow-up. */
function decideFollowup(name) { _decide(name, 'followup'); }
/** Done: same as Follow-up but the object is closed (status → Snoozed). */
function decideDone(name)     { _decide(name, 'snoozed'); }

function _decide(name, status) {
    const card = _cardByName(name);
    if (!card) return;
    if (card.dataset.status === status) { _toast(`${name} is already ${status === 'followup' ? 'Follow-up' : 'Done'}.`); return; }
    const hostId  = card.dataset.hostMatchId;
    const pinned  = card.dataset.hostPinned === 'true';
    _setCardBusy(card, true);
    const req = (hostId && !pinned)
        ? _post('/api/set_host', { match_id: hostId, target_name: name, redshift: card.dataset.hostZ || null, status })
        : _post('/api/set_object_status', { target_name: name, status });
    req.then(d => {
        if (!d.success) { _toast('Failed: ' + (d.message || 'unknown'), 'error'); return; }
        if (hostId) { card.dataset.hostPinned = 'true'; _markPinnedRow(card, hostId); }
        _applyStatus(card, status);
        _toast(`${name} → ${status === 'followup' ? 'Follow-up' : 'Done'}${hostId ? ' · host accepted' : ''}`, 'ok');
        if (status === 'snoozed') setTimeout(nextUnreviewed, 350);
    })
    .catch(() => _toast('An error occurred', 'error'))
    .finally(() => _setCardBusy(card, false));
}

/** No host: every candidate rejected (DETECT keeps that), status → Snoozed. */
function decideNoHost(name) {
    const card = _cardByName(name);
    if (!card) return;
    _setCardBusy(card, true);
    _post('/api/mark_no_host', { target_name: name })
        .then(d => {
            if (!d.success) { _toast('Failed: ' + (d.message || 'unknown'), 'error'); return; }
            card.dataset.hostMatchId = '';
            card.dataset.hostZ = '';
            card.dataset.hostPinned = 'false';
            card.dataset.hostRejected = 'true';
            card.querySelectorAll('.match-detail-table tbody tr').forEach(r => {
                r.dataset.isHost = 'false'; r.dataset.hostUser = 'false';
                if (r.dataset.ruleKind === 'host') r.dataset.ruleKind = 'member';
            });
            _applyStatus(card, 'snoozed');
            _toast(`${name} → No host`, 'ok');
            setTimeout(nextUnreviewed, 350);
        })
        .catch(() => _toast('An error occurred', 'error'))
        .finally(() => _setCardBusy(card, false));
}

/** Reopen: back to Pending; the host question returns to the pipeline. */
function decideReopen(name) {
    const card = _cardByName(name);
    if (!card) return;
    if (card.dataset.status === 'object' && card.dataset.hostPinned !== 'true' && card.dataset.hostRejected !== 'true') {
        _toast(`${name} is already pending.`); return;
    }
    _setCardBusy(card, true);
    _post('/api/unset_host', { target_name: name })
        .then(d => {
            if (!d.success) { _toast('Failed: ' + (d.message || 'unknown'), 'error'); return; }
            // the decision is withdrawn; whatever row is host right now stays the host
            card.dataset.hostPinned = 'false';
            card.dataset.hostRejected = 'false';
            card.querySelectorAll('.match-detail-table tbody tr').forEach(r => { r.dataset.hostUser = ''; });
            _applyStatus(card, 'object');
            _toast(card.dataset.hostMatchId
                ? `${name} reopened — pending again`
                : `${name} reopened — DETECT re-derives the host on its next run`, 'ok');
        })
        .catch(() => _toast('An error occurred', 'error'))
        .finally(() => _setCardBusy(card, false));
}

/** Set host on a candidate row. Status is untouched unless the object is pending. */
function pickHost(name, matchId, z) {
    const card = _cardByName(name);
    if (!card) return;
    _setCardBusy(card, true, 'Setting host…');
    _post('/api/set_host', { match_id: matchId, target_name: name, redshift: z || null, status: 'keep' })
        .then(d => {
            if (!d.success) { _toast('Failed: ' + (d.message || 'unknown'), 'error'); return; }
            card.dataset.hostMatchId = String(matchId);
            card.dataset.hostZ = z || '';
            card.dataset.hostPinned = 'true';
            card.dataset.hostRejected = 'false';
            card.querySelectorAll('.match-detail-table tbody tr').forEach(r => {
                const mine = String(r.dataset.matchId) === String(matchId);
                r.dataset.isHost = mine ? 'true' : 'false';
                r.dataset.hostUser = mine ? 'true' : 'false';
                if (mine) r.dataset.ruleKind = 'host';
                else if (r.dataset.ruleKind === 'host') r.dataset.ruleKind = 'member';
            });
            _markPinnedRow(card, matchId);
            _renderCard(card);
            const hint = document.getElementById(`verdict-hint-${name}`);
            if (hint) hint.textContent = 'Host chosen by you. Now Follow-up (F) or Done (D).';
            _toast(`${name}: host set${z ? ' · z = ' + Number(z).toFixed(4) : ''}. Now F or D.`, 'ok');
        })
        .catch(() => _toast('An error occurred', 'error'))
        .finally(() => _setCardBusy(card, false));
}

function _markPinnedRow(card, matchId) {
    card.querySelectorAll('.match-detail-table tbody tr').forEach(r => {
        const mine = String(r.dataset.matchId) === String(matchId);
        r.dataset.hostUser = mine ? 'true' : 'false';
        if (mine) r.dataset.isHost = 'true';
    });
}

/** Push a new object status into the card, its summary row and the counters. */
function _applyStatus(card, status) {
    const prev = card.dataset.status;
    card.dataset.status = status;
    card.classList.toggle('card-unreviewed', status === 'object');
    const row = _rowByName(card.dataset.name);
    if (row) {
        row.dataset.status = status;
        row.dataset.hasHost = card.dataset.hostMatchId ? 'true' : 'false';
        row.classList.toggle('row-unreviewed', status === 'object');
        const cell = document.getElementById(`status-cell-${card.dataset.name}`);
        if (cell) cell.innerHTML = _statusBadge(status, !!card.dataset.hostMatchId);
    }
    _renderCard(card);
    _bumpStat(prev, -1); _bumpStat(status, +1);
}

function _bumpStat(status, delta) {
    const id = status === 'object' ? 'statPending' : status === 'followup' ? 'statFollowup'
             : (status === 'snoozed' || status === 'finished') ? 'statDone' : null;
    if (!id) return;
    const el = document.getElementById(id);
    if (el) el.textContent = Math.max(0, (parseInt(el.textContent, 10) || 0) + delta);
}

function _statusBadge(status, hasHost) {
    if (status === 'snoozed' || status === 'finished')
        return hasHost ? '<span class="badge-checked">✓ Done</span>' : '<span class="badge-nohost">✗ No host</span>';
    if (status === 'followup') return '<span class="badge-followup">⬤ Follow-up</span>';
    return '<span class="badge-unreviewed">Pending</span>';
}

// ── Render the "what to do" bar and the candidate actions from card state ──
function _renderCard(card) {
    const name    = card.dataset.name;
    const status  = card.dataset.status;
    const hostId  = card.dataset.hostMatchId;
    const pinned  = card.dataset.hostPinned === 'true';
    const rejected = card.dataset.hostRejected === 'true';
    const hs      = card.dataset.hostStatus;
    const done    = status === 'snoozed' || status === 'finished';

    const badge = document.getElementById(`card-status-${name}`);
    if (badge) badge.innerHTML = _statusBadge(status, !!hostId);

    const bar = document.getElementById(`actions-${name}`);
    if (bar) {
        if (!CAN_EDIT) {
            bar.innerHTML = '<span class="action-note">Sign in as an admin to review.</span>';
        } else if (done) {
            bar.innerHTML = `
                <span class="action-lead">${hostId ? 'Closed with host accepted' : 'Closed as no host'}${pinned || rejected ? ' — your decision' : ''}.</span>
                <button class="btn-decide btn-reopen" onclick="decideReopen('${name}')" title="Back to pending (R)">↺ Reopen <kbd>R</kbd></button>`;
        } else if (status === 'followup') {
            bar.innerHTML = `
                <span class="action-lead">In follow-up${hostId ? ' with host ' + (pinned ? 'chosen by a reviewer' : 'from the rule') : ' without a host'}. DETECT re-screens it daily.</span>
                <button class="btn-decide btn-done" onclick="decideDone('${name}')" title="Close it (D)">✓ Done <kbd>D</kbd></button>
                <button class="btn-decide btn-reopen" onclick="decideReopen('${name}')" title="Back to pending (R)">↺ Reopen <kbd>R</kbd></button>`;
        } else {
            let lead;
            if (pinned)            lead = 'Host chosen by you — now decide:';
            else if (hostId && hs === 'confirmed') lead = 'Accept the host and decide:';
            else if (hostId)       lead = 'Accept the rule\'s pick (#1) and decide, or set another row as host:';
            else if (hs === 'review') lead = 'Set host on a candidate row if the image supports it, otherwise:';
            else                   lead = 'No galaxy contains it. Close it, or set host on a row if the image disagrees:';
            const nohostLabel = hostId ? '✗ No host' : '✗ No host · close';
            bar.innerHTML = `
                <span class="action-lead">${lead}</span>
                <button class="btn-decide btn-followup" onclick="decideFollowup('${name}')" title="Follow-up (F)${hostId ? ' — accepts the host' : ''}">★ Follow-up <kbd>F</kbd></button>
                <button class="btn-decide btn-done ${hostId ? '' : 'btn-quiet'}" onclick="decideDone('${name}')" title="Done (D)${hostId ? ' — accepts the host, no follow-up' : ''}">✓ Done <kbd>D</kbd></button>
                <button class="btn-decide btn-nohost ${hostId ? 'btn-quiet' : ''}" onclick="decideNoHost('${name}')" title="None of the candidates is the host (N)">${nohostLabel} <kbd>N</kbd></button>`;
        }
    }

    // candidate table actions
    card.querySelectorAll('.match-detail-table tbody tr').forEach(r => {
        const cell = r.querySelector('.td-match-action');
        if (!cell) return;
        const isHost = r.dataset.isHost === 'true';
        const mine   = r.dataset.hostUser === 'true';
        const by     = r.dataset.hostUserBy;
        r.classList.toggle('row-is-host', isHost);
        let html = '';
        if (isHost) {
            html += `<span class="badge-host" title="${mine ? 'Chosen by ' + (by || 'a reviewer') : 'DETECT rule v1'}">✓ HOST${mine ? ' · you' : ''}</span>`;
        } else if (CAN_EDIT && !done) {
            const z = r.dataset.matchZ || '';
            const kind = r.dataset.ruleKind;
            const prominent = (!hostId && (kind === 'tentative' || kind === 'member')) || (kind === 'member' && r.dataset.ruleRank === '2');
            html += `<button class="btn-action btn-set-host ${prominent ? 'btn-prominent' : ''}" onclick="pickHost('${name}', '${r.dataset.matchId}', '${z}')" title="Make this row the host">Set host</button>`;
        } else {
            html += '<span style="color:#444;">—</span>';
        }
        cell.innerHTML = html;
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
    window.addEventListener('scroll', () => { btn.style.display = window.scrollY > 300 ? 'block' : 'none'; }, { passive: true });
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.target-card');
    _total = cards.length;
    const totalEl = document.getElementById('cardTotal');
    if (totalEl) totalEl.textContent = _total;

    cards.forEach(_renderCard);

    // guide: open until the reviewer closes it once
    let guidePref = null;
    try { guidePref = localStorage.getItem('detect.guide'); } catch (_) {}
    toggleGuide(guidePref !== 'closed');

    const panel = document.getElementById('followupTrackerPanel');
    if (panel) panel.classList.add('collapsed');
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
