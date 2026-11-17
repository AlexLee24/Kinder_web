/* Light curve of a Kinder object (Plotly), shared by the Transient page (object_detail.js) and the Daily Trigger page
   (dt_auto.js): the figure comes from /api/object/<name>/photometry/plot; this file draws it with the same theme,
   axes (MJD, Date, Phase), filter legend (#photLegend) and telescope toggles (#telescopeToggles).
   One light curve per page: the plot div is #phot-plotly-div. */

// Keep default LC view from over-zooming when points are very close in time.
function enforceMinLcXAxisSpan(figData, minSpanDays = 1) {
    if (!figData || !Array.isArray(figData.data) || figData.data.length === 0) return;

    const numericX = [];
    const dateXMs = [];

    figData.data.forEach(trace => {
        if (!trace || !Array.isArray(trace.x)) return;

        trace.x.forEach(value => {
            if (typeof value === 'number' && Number.isFinite(value)) {
                numericX.push(value);
                return;
            }

            if (typeof value !== 'string') return;
            const text = value.trim();
            if (!text) return;

            if (/^-?\d+(\.\d+)?$/.test(text)) {
                const num = Number(text);
                if (Number.isFinite(num)) numericX.push(num);
                return;
            }

            const ms = Date.parse(text);
            if (Number.isFinite(ms)) dateXMs.push(ms);
        });
    });

    figData.layout = figData.layout || {};
    figData.layout.xaxis = figData.layout.xaxis || {};

    if (numericX.length > 0 && dateXMs.length === 0) {
        const minX = Math.min(...numericX);
        const maxX = Math.max(...numericX);
        const span = maxX - minX;
        if (span < minSpanDays) {
            const center = (minX + maxX) / 2;
            const forcedMin = center - minSpanDays / 2;
            const forcedMax = center + minSpanDays / 2;
            figData.layout.xaxis.range = [forcedMin, forcedMax];
            figData.layout.xaxis.autorange = false;
            figData.layout.xaxis.tickmode = 'linear';
            figData.layout.xaxis.dtick = minSpanDays;
            figData.layout.xaxis.tick0 = Math.floor(forcedMin);
        }
        return;
    }

    if (dateXMs.length > 0 && numericX.length === 0) {
        const minSpanMs = minSpanDays * 24 * 60 * 60 * 1000;
        const minX = Math.min(...dateXMs);
        const maxX = Math.max(...dateXMs);
        const span = maxX - minX;
        if (span < minSpanMs) {
            const center = (minX + maxX) / 2;
            const forcedMin = center - minSpanMs / 2;
            const forcedMax = center + minSpanMs / 2;
            const tick0Date = new Date(forcedMin);
            tick0Date.setUTCHours(0, 0, 0, 0);
            figData.layout.xaxis.range = [new Date(forcedMin), new Date(forcedMax)];
            figData.layout.xaxis.autorange = false;
            figData.layout.xaxis.tickmode = 'linear';
            figData.layout.xaxis.dtick = minSpanMs;
            figData.layout.xaxis.tick0 = tick0Date;
        }
    }
}

// ---------------------------------------------------------------------------
// Light-curve x axes: MJD (bottom), Date (top) and Phase (second bottom axis).
// ---------------------------------------------------------------------------
const LC_PHASE_DOMAIN_BOTTOM = 0.17;   // y-domain start: room below the plot for the phase axis

function _mjdFromDateString(text) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?)?/.exec(String(text || '').trim());
    if (!m) return null;
    const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), 0) + parseFloat(m[6] || 0) * 1000;
    return Number.isFinite(ms) ? ms / 86400000 + 40587 : null;
}

function _mjdToDateString(mjd) {
    return new Date((mjd - 40587) * 86400000).toISOString().replace('T', ' ').slice(0, 19);
}

/** The phase axis reference {mjd, custom}: the Transient page's own (_phaseRef, user-settable), else lcPhaseRefDefault. */
let lcPhaseRefDefault = null;
function lcPhaseRef() {
    if (typeof _phaseRef === 'function') return _phaseRef();
    return lcPhaseRefDefault;
}

/** Add the phase axis (xaxis3, days since ref.mjd) to a light-curve figure before it is drawn. */
function lcAddPhaseAxis(figData, ref, title) {
    const layout = figData && figData.layout;
    const range = layout && layout.xaxis && layout.xaxis.range;
    if (!ref || !Array.isArray(range) || range.length !== 2) return;
    const lo = Number(range[0]), hi = Number(range[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return;

    ['yaxis', 'yaxis2'].forEach(ax => {
        if (layout[ax] && !layout[ax].overlaying) layout[ax].domain = [LC_PHASE_DOMAIN_BOTTOM, 1];
    });
    layout.xaxis3 = {
        title: { text: title || 'Phase (days since discovery)', standoff: 4 },
        overlaying: 'x',
        anchor: 'free',
        position: 0,
        side: 'bottom',
        range: [lo - ref.mjd, hi - ref.mjd],
        tickformat: '+~g',    // explicit sign: +12 d / −3 d
        ticksuffix: ' d',
        showgrid: false,
        zeroline: false,
    };
    layout.margin = Object.assign({}, layout.margin || {}, { b: Math.max((layout.margin || {}).b || 0, 52) });
    // An overlaying axis is only drawn when a trace uses it.
    figData.data.push({
        x: [lo - ref.mjd], y: [null], xaxis: 'x3', yaxis: 'y', type: 'scatter', mode: 'markers',
        marker: { opacity: 0 }, showlegend: false, hoverinfo: 'skip',
    });
}

/**
 * Keep the light-curve axes usable while zooming:
 *  - axes drawn with fixed tick spacing (tickmode 'linear', e.g. one tick per day or
 *    per 0.2 mag) show no labels once the view is narrower than that spacing, so a
 *    zoom switches them to automatic ticks and a reset restores the fixed grid;
 *  - the Date (top) and Phase axes follow the MJD axis.
 */
function _wireLcAxes(plotDiv) {
    if (!plotDiv || !plotDiv.layout || typeof plotDiv.on !== 'function') return;
    const fixed = {};
    ['xaxis', 'yaxis', 'yaxis2'].forEach(ax => {
        const a = plotDiv.layout[ax];
        if (a && a.tickmode === 'linear') {
            fixed[ax] = { tickmode: 'linear', dtick: a.dtick, tick0: a.tick0,
                          range: Array.isArray(a.range) ? a.range.slice() : null };
        }
    });
    let busy = false;

    plotDiv.on('plotly_relayout', ev => {
        if (busy || !ev) return;
        const update = {};
        const touched = ax => `${ax}.range[0]` in ev || `${ax}.range` in ev || `${ax}.autorange` in ev;

        Object.keys(fixed).forEach(ax => {
            if (!touched(ax)) return;
            const cur = (plotDiv.layout[ax] || {}).range || [];
            const init = fixed[ax].range;
            const isReset = ev[`${ax}.autorange`] === true || (init && cur.length === 2
                && Math.abs(cur[0] - init[0]) < 1e-9 && Math.abs(cur[1] - init[1]) < 1e-9);
            if (isReset) {
                update[`${ax}.tickmode`] = 'linear';
                update[`${ax}.dtick`] = fixed[ax].dtick;
                update[`${ax}.tick0`] = fixed[ax].tick0;
            } else {
                update[`${ax}.tickmode`] = 'auto';
                update[`${ax}.dtick`] = null;
                update[`${ax}.tick0`] = null;
            }
        });

        if (touched('xaxis')) Object.assign(update, _secondaryXRanges(plotDiv));
        if (!Object.keys(update).length) return;
        busy = true;
        Promise.resolve(Plotly.relayout(plotDiv, update)).finally(() => { busy = false; });
    });
}

/** Date (xaxis2) and Phase (xaxis3) ranges that match the current MJD range. */
function _secondaryXRanges(plotDiv) {
    const r = (plotDiv.layout.xaxis || {}).range;
    if (!Array.isArray(r) || r.length !== 2) return {};
    const lo = Number(r[0]), hi = Number(r[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return {};
    const out = {};
    if (plotDiv.layout.xaxis2) {
        out['xaxis2.range'] = [_mjdToDateString(lo), _mjdToDateString(hi)];
        out['xaxis2.autorange'] = false;
    }
    const ref = lcPhaseRef();
    if (plotDiv.layout.xaxis3 && ref) {
        out['xaxis3.range'] = [lo - ref.mjd, hi - ref.mjd];
        out['xaxis3.autorange'] = false;
        out['xaxis3.title.text'] = typeof _phaseAxisTitle === 'function' ? _phaseAxisTitle(ref) : 'Phase (days since discovery)';
    }
    return out;
}

// ── Shared photometry visibility state ────────────────────────────────────
let _photTelActive   = null;  // Set<string> — active telescopes
let _photTraceActive = null;  // Set<string> — active trace names

// Parse telescope from trace name: "{filter} - {telescope}" or "{filter} - {telescope} - Limit"
function _telFromTraceName(name) {
    if (!name) return null;
    const base = name.endsWith(' - Limit') ? name.slice(0, -8).trimEnd() : name;
    const idx = base.lastIndexOf(' - ');
    return idx >= 0 ? base.slice(idx + 3) : null;
}

function _applyPhotVis() {
    const plotDiv = document.getElementById('phot-plotly-div');
    if (!plotDiv || !plotDiv.data) return;
    const visArr = plotDiv.data.map(tr => {
        if (tr.showlegend === false || !tr.name) return true;
        const tel = _telFromTraceName(tr.name);
        const telOk   = !_photTelActive   || !tel || _photTelActive.has(tel);
        const traceOk = !_photTraceActive || _photTraceActive.has(tr.name);
        return (telOk && traceOk) ? true : 'legendonly';
    });
    Plotly.restyle('phot-plotly-div', 'visible', visArr);

    // Sync filter-legend button visual state
    document.querySelectorAll('.phot-filter-btn').forEach(btn => {
        const name = btn.dataset.traceName;
        const tel = _telFromTraceName(name);
        const traceOn = !_photTraceActive || _photTraceActive.has(name);
        const telOn   = !_photTelActive   || !tel || _photTelActive.has(tel);
        btn.classList.toggle('active',  traceOn && telOn);
        btn.classList.toggle('tel-off', traceOn && !telOn);
    });
}

// Build telescope quick-toggle buttons above photometry plot
function _buildTelescopeToggles(traces) {
    const container = document.getElementById('telescopeToggles');
    if (!container) return;

    const telescopes = [];
    const seen = new Set();
    traces.forEach(t => {
        const tel = _telFromTraceName(t.name);
        if (tel && !seen.has(tel)) { seen.add(tel); telescopes.push(tel); }
    });

    _photTelActive = new Set(telescopes);

    if (telescopes.length <= 1) { container.style.display = 'none'; return; }

    container.innerHTML = '';
    container.style.display = 'flex';

    telescopes.forEach(tel => {
        const btn = document.createElement('button');
        btn.className = 'phot-tel-btn active';
        btn.textContent = tel;
        btn.dataset.telescope = tel;
        btn.addEventListener('click', function () {
            if (_photTelActive.has(tel)) { _photTelActive.delete(tel); btn.classList.remove('active'); }
            else                         { _photTelActive.add(tel);    btn.classList.add('active');    }
            _applyPhotVis();
        });
        container.appendChild(btn);
    });
}

// ── Photometry filter legend (below chart, replaces Plotly built-in legend) ──
function _buildFilterLegend(traces) {
    const container = document.getElementById('photLegend');
    if (!container) return;
    container.innerHTML = '';

    const entries = [];
    const seen = new Set();
    traces.forEach(t => {
        if (t.showlegend === false || !t.name) return;
        if (seen.has(t.name)) return;
        seen.add(t.name);
        const color = (t.marker && t.marker.color) ? t.marker.color : '#888';
        const tel   = _telFromTraceName(t.name) || '';
        const isUp  = t.name.endsWith(' - Limit');
        // filter label = part before the last " - telescope" segment
        const base  = isUp ? t.name.slice(0, -8).trimEnd() : t.name;
        const filterLabel = base.slice(0, base.lastIndexOf(' - ') >= 0 ? base.lastIndexOf(' - ') : base.length);
        entries.push({ name: t.name, color, isUp, tel, filterLabel });
    });

    _photTraceActive = new Set(entries.map(e => e.name));

    if (entries.length === 0) { container.style.display = 'none'; return; }

    // Sort: by telescope name, then detections before limits, then filter name
    entries.sort((a, b) => {
        if (a.tel !== b.tel) return a.tel.localeCompare(b.tel);
        if (a.isUp !== b.isUp) return a.isUp ? 1 : -1;
        return a.filterLabel.localeCompare(b.filterLabel);
    });

    // Group by telescope — build groups with a header label
    let currentTel = null;
    entries.forEach(({ name, color, isUp, tel, filterLabel }) => {
        // Telescope group header
        if (tel !== currentTel) {
            currentTel = tel;
            if (container.childElementCount > 0) {
                // thin divider between groups
                const sep = document.createElement('span');
                sep.className = 'phot-legend-sep';
                container.appendChild(sep);
            }
            const hdr = document.createElement('span');
            hdr.className = 'phot-legend-tel';
            hdr.textContent = tel || '—';
            container.appendChild(hdr);
        }

        const btn = document.createElement('button');
        btn.className = 'phot-filter-btn active';
        btn.dataset.traceName = name;
        btn.style.setProperty('--fc', color);

        const dot = document.createElement('span');
        dot.className = isUp ? 'phot-filter-up' : 'phot-filter-dot';

        const label = document.createElement('span');
        label.textContent = isUp ? filterLabel + ' - Limit' : filterLabel;

        btn.appendChild(dot);
        btn.appendChild(label);

        btn.addEventListener('click', function () {
            if (_photTraceActive.has(name)) _photTraceActive.delete(name);
            else                            _photTraceActive.add(name);
            _applyPhotVis();
        });

        container.appendChild(btn);
    });

    container.style.display = 'flex';
}

/** Draw plotData (the /photometry/plot answer) into container: theme, axes, legend, telescope toggles.
    addPhaseAxis(figData) adds the phase axis (optional); height in px (default 450). Returns the figure. */
function lcDraw(container, plotData, addPhaseAxis, height) {
    container.innerHTML = '<div id="phot-plotly-div" style="width:100%; height:' + (height || 450) + 'px;"></div>';
    const figData = JSON.parse(plotData.plot_json);
    // Override template to match page dark theme
    if (figData.layout) {
        figData.layout.paper_bgcolor = 'rgba(0,0,0,0)';
        figData.layout.plot_bgcolor  = 'rgba(0,0,0,0)';
        figData.layout.font = figData.layout.font || {};
        figData.layout.font.color = '#ccc';
        figData.layout.showlegend = false;
        figData.layout.margin = Object.assign(figData.layout.margin || {}, { t: 45 });
    }
    enforceMinLcXAxisSpan(figData, 1);
    // Phones: desktop margins leave a ~150px wide plot and the mode bar covers the title
    const phone = window.matchMedia('(max-width: 600px)').matches;
    if (phone && figData.layout) {
        const t = figData.layout.title;
        figData.layout.margin = { l: 48, r: 44, t: 36, b: 44, pad: 0 };
        figData.layout.font.size = 10;
        figData.layout.title = Object.assign({}, typeof t === 'string' ? { text: t } : (t || {}), { font: { size: 13 } });
        document.getElementById('phot-plotly-div').style.height = '380px';
    }
    if (addPhaseAxis) addPhaseAxis(figData);
    Plotly.newPlot('phot-plotly-div', figData.data, figData.layout, { responsive: true, displayModeBar: !phone });
    _wireLcAxes(document.getElementById('phot-plotly-div'));
    _buildTelescopeToggles(figData.data);
    _buildFilterLegend(figData.data);
    return figData;
}
