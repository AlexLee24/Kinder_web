/* ============================================================================
   CASTOR ETC — controller for etc_body.html.

   Host-agnostic: every route it talks to comes from window.CASTOR_ETC_CONFIG,
   which the host page sets before loading this file (see frontend/README.md).
   Kinder points it at its own Flask blueprint; the standalone server.py points
   it at the identical paths it serves itself.

   Interaction model: four freely switchable tabs, no submit button, every edit
   recalculates. Recalculating over the network is what makes that last part
   delicate — a slow earlier response can land after a fast later one and
   overwrite it, so each request family keeps a single AbortController and
   cancels its own predecessor.
============================================================================ */
(function () {
    'use strict';

    var CONFIG = Object.assign({
        apiUrl: '/api/exposure_time_calculator',
        batchUrl: '/api/exposure_time_calculator/batch',
        presetsUrl: '/api/exposure_time_calculator/presets'
    }, window.CASTOR_ETC_CONFIG || {});

    // Single-point is cheap; batch runs astropy ephemeris over the whole window,
    // so it waits longer before firing (same split as app.py's BATCH_DEBOUNCE).
    var SINGLE_DEBOUNCE_MS = 250;
    var BATCH_DEBOUNCE_MS = 500;

    var root = document.getElementById('castor-etc');
    var form = document.getElementById('castor-form');
    if (!root || !form) { return; }

    var el = function (id) { return document.getElementById(id); };

    // ========================================================================
    // Formatting helpers
    // ========================================================================

    function fmt(value, digits) {
        if (value === null || value === undefined || isNaN(value)) { return '—'; }
        return Number(value).toLocaleString(undefined, {
            maximumFractionDigits: digits === undefined ? 3 : digits
        });
    }

    /* Percentage inputs hold 0-100 while castor.schema wants the 0-1 fraction.
       Rounding before display matters: 0.804 * 100 is 80.39999999999999 in IEEE
       754, and showing that in a field the user is about to edit is worse than
       useless. Mirrors LeftPanel._format_percent. */
    function fractionToPercentText(fraction) {
        return String(Math.round(fraction * 100 * 1e6) / 1e6);
    }

    function toLocalInputValue(date) {
        var pad = function (n) { return String(n).padStart(2, '0'); };
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
            'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }

    function isoToLocalInputValue(iso) {
        var d = new Date(iso);
        return isNaN(d.getTime()) ? '' : toLocalInputValue(d);
    }

    // ========================================================================
    // Payload building
    // ========================================================================

    var PayloadBuilder = {
        /* prune=true drops inputs inside a hidden .dynamic-group, because
           castor.schema is strict: sending zero_point_flux while the brightness
           discriminator says ab_mag is a validation error, not a harmless extra.
           prune=false is for SAVE, which keeps every branch's value — see
           buildSaveObject for why. */
        build: function (prune) {
            var payload = {};
            var elements = form.elements;

            for (var i = 0; i < elements.length; i++) {
                var input = elements[i];
                if (!input.name) { continue; }
                if (prune !== false && input.closest('.dynamic-group[hidden]')) { continue; }

                var value = this._read(input);
                if (value === null || value === '') { continue; }
                this._set(payload, input.name.split('.'), value);
            }
            return payload;
        },

        _read: function (input) {
            if (input.type === 'checkbox') { return input.checked; }
            if (input.type === 'datetime-local') {
                if (!input.value) { return null; }
                var d = new Date(input.value);   // parsed as local wall-clock time
                return isNaN(d.getTime()) ? null : d.toISOString();
            }
            if (input.type === 'number') {
                if (input.value === '') { return null; }
                var n = parseFloat(input.value);
                if (isNaN(n)) { return null; }
                return input.hasAttribute('data-percent') ? n / 100 : n;
            }
            return input.value;
        },

        _set: function (obj, path, value) {
            var node = obj;
            for (var i = 0; i < path.length - 1; i++) {
                if (!node[path[i]]) { node[path[i]] = {}; }
                node = node[path[i]];
            }
            node[path[path.length - 1]] = value;
        }
    };

    function buildSingleRequest() {
        var base = PayloadBuilder.build(true);
        delete base.batch;      // batch.* are UI-only fields, not part of ObservationRequest
        return base;
    }

    /* TimeSeriesEnvironment shares location / mu_dark / extinction / FWHM with the
       single-point environment and swaps the instant for a start/end/step range.
       It has no auto_calc_background: the batch path always layers the dynamic
       moon contribution. */
    function buildBatchRequest() {
        var base = PayloadBuilder.build(true);
        var env = base.environment || {};
        var batch = base.batch || {};

        return {
            instrument: base.instrument,
            target: base.target,
            environment: {
                location: env.location,
                start_time_utc: batch.start_time_utc,
                end_time_utc: batch.end_time_utc,
                time_step_minutes: batch.time_step_minutes,
                mu_dark: env.mu_dark,
                zodiacal_share: env.zodiacal_share,
                extinction_coeff: env.extinction_coeff,
                seeing_fwhm: env.seeing_fwhm,
                diffraction_fwhm: env.diffraction_fwhm,
                optical_fwhm: env.optical_fwhm,
                tracking_fwhm: env.tracking_fwhm
            },
            options: base.options
        };
    }

    // ========================================================================
    // API
    // ========================================================================

    function postJSON(url, body, signal) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: signal
        }).then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) { throw new Error(data.error || ('HTTP ' + response.status)); }
                return data;
            });
        });
    }

    // ========================================================================
    // Results rendering
    // ========================================================================

    /* Single-point and batch warnings share one box but arrive from two
       independent requests that finish at different times — tracked separately
       so whichever lands second doesn't wipe out the other's lines. Same split
       as RightPanel._single_warn_lines / _batch_warn_lines. */
    var singleWarnings = [];
    var batchWarnings = [];

    function refreshWarnings() {
        var lines = singleWarnings.concat(batchWarnings);
        el('warning-text').textContent = lines.join('\n');
        el('warning-box').hidden = lines.length === 0;
    }

    var METRIC_IDS = [
        'res-source-rate', 'res-sky-rate', 'res-peak-rate', 'res-single-snr',
        'res-total-fwhm', 'res-pixel-scale', 'res-eff-area', 'res-throughput',
        'res-enclosed-flux', 'res-num-pixels', 'res-sat-time', 'res-optimal-time'
    ];

    var resultsScroll = root.querySelector('.etc-results-scroll');

    // What the single-point run last computed for the hero. Held rather than painted so
    // the sweep can own the headline, and hand it back if the sweep has no answer.
    var lastSingleHero = null;

    function restoreHero() {
        if (!lastSingleHero) { return; }
        el('hero-label').textContent = lastSingleHero.label;
        el('hero-value').textContent = lastSingleHero.value;
        el('hero-desc').textContent = lastSingleHero.desc;
    }

    function renderSingle(data, error) {
        if (error) {
            el('error-text').textContent = error;
            el('error-box').hidden = false;
            singleWarnings = [];
            refreshWarnings();
            el('hero-label').textContent = 'Primary Result';
            el('hero-value').textContent = '—';
            el('hero-desc').textContent = 'Invalid input, please check the fields on the left';
            // Blank the cards rather than leaving the last good run's numbers sitting
            // next to an error message, where they read as current results.
            METRIC_IDS.forEach(function (id) { el(id).textContent = '—'; });
            return;
        }

        el('error-box').hidden = true;

        var core = data.core, budget = data.budget, diag = data.diagnostics, flags = data.flags;

        lastSingleHero = (core.required_exposures === null || core.required_exposures === undefined)
            ? { label: 'Signal-to-Noise Ratio (SNR)',
                value: fmt(core.total_snr, 2),
                desc:  'Calculated based on the given exposure time.' }
            : { label: 'Required Exposures',
                value: core.required_exposures + ' frames',
                desc:  'Target SNR achieved: ' + fmt(core.total_snr, 2) };

        /* Computed either way, written only when it is the answer on show. While
           sweeping the headline belongs to renderBatch, and painting an instant's
           figure here would race the sweep for the same three elements — the two run
           on separate debounces, so whichever landed last would win the hero. */
        if (!el('toggle-batch').checked) { restoreHero(); }

        singleWarnings = (flags.warnings || []).slice();
        if (flags.is_saturated) {
            singleWarnings.unshift('⚠️ Single exposure time exceeds the saturation limit (Full Well Capacity reached).');
        }
        refreshWarnings();

        el('res-source-rate').textContent = fmt(budget.source_count_rate, 2);
        el('res-sky-rate').textContent = fmt(budget.sky_count_rate, 2);
        el('res-peak-rate').textContent = fmt(budget.peak_pixel_rate, 2);
        el('res-single-snr').textContent = fmt(core.single_snr, 2);

        el('res-total-fwhm').textContent = fmt(diag.total_fwhm, 2);
        el('res-pixel-scale').textContent = fmt(diag.pixel_scale, 3);
        el('res-eff-area').textContent = fmt(diag.effective_area, 3);
        el('res-throughput').textContent = fmt(diag.total_throughput * 100, 1);
        el('res-enclosed-flux').textContent = fmt(diag.enclosed_flux_fraction * 100, 1);
        el('res-num-pixels').textContent = fmt(diag.num_pixels_aperture, 1);
        el('res-num-pixels-sky').textContent = fmt(diag.num_pixels_sky_estimate, 1);

        el('res-sat-time').textContent = fmt(core.saturation_time_limit, 2);
        el('res-optimal-time').textContent = fmt(core.optimal_exposure_time, 2);
    }

    // ========================================================================
    // Observing Window chart (Plotly)
    // ========================================================================

    /* Returns [[startIdx, endIdx], ...] for each contiguous run where test() holds,
       end inclusive — a night can contain more than one below-horizon or
       saturation-risk window. Port of chart.py's _contiguous_runs. */
    function contiguousRuns(values, test) {
        var runs = [], start = null;
        for (var i = 0; i < values.length; i++) {
            if (test(values[i], i)) {
                if (start === null) { start = i; }
            } else if (start !== null) {
                runs.push([start, i - 1]);
                start = null;
            }
        }
        if (start !== null) { runs.push([start, values.length - 1]); }
        return runs;
    }

    /* "...T20:00:00" is UTC despite carrying no Z; adding one is what makes Date read
       it as the instant it is rather than as local time. Emitted space-separated,
       which Plotly accepts and which reads as a wall clock rather than a stamp. */
    function toLocalPlotTime(iso) {
        var d = new Date(iso + 'Z');
        if (isNaN(d.getTime())) { return iso; }
        var p = function (n) { return String(n).padStart(2, '0'); };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
               ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }

    /* Shared by the chart and the sweep headline so the two cannot disagree about
       which hours count. -18 deg is astronomical twilight: the Sun far enough down
       that its scattered light no longer sets the background. */
    var ASTRONOMICAL_TWILIGHT_DEG = -18;

    function observableMask(data) {
        var target = data.ephemeris.target_elevation_deg;
        var sun = data.ephemeris.sun_elevation_deg || [];
        var hasSun = sun.length === target.length;
        return target.map(function (v, i) {
            return v > 0 && (!hasSun || sun[i] < ASTRONOMICAL_TWILIGHT_DEG);
        });
    }

    function toLocalClock(iso) {
        var d = new Date(iso + 'Z');
        if (isNaN(d.getTime())) { return iso; }
        var p = function (n) { return String(n).padStart(2, '0'); };
        return p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function themeColor(name, fallback) {
        var value = getComputedStyle(root).getPropertyValue(name).trim();
        return value || fallback;
    }

    function setChartStatus(message) {
        var status = el('chart-status');
        status.textContent = message || '';
        status.hidden = !message;
    }

    /* Three stacked panels on one shared time axis, in reading order:
         1. Target & Moon elevation — is this window even above the horizon?
         2. Single-exposure SNR — how good is one frame right now?
         3. Saturation limit vs. the chosen exposure — will one frame saturate?
       Deliberately not total_snr (that tracks the chosen exposure count, not the
       sky) and deliberately not one dual-axis panel (SNR and seconds don't share
       a scale). Same reasoning as chart.py, which this replaces. */
    function renderChart(data, singleExpTime) {
        if (typeof window.Plotly === 'undefined') {
            setChartStatus('Plotly is not loaded on this page, so the chart cannot be drawn.');
            return;
        }

        var accent = themeColor('--etc-accent', '#C5A059');
        var moon = themeColor('--etc-moon', '#6FA8DC');
        var warning = themeColor('--etc-warning', '#fbbf24');
        var sun = themeColor('--etc-sun', '#8f8fa8');
        /* Deliberately a flat neutral, not the warning colour the below-horizon band
           used to borrow. Panel 3 shades saturation risk in warning amber, and two
           bands in one amber on one time axis read as the same hazard. Unobservable
           is not a hazard, it is just when the sky is closed. */
        var shadeUnobservable = 'rgba(148, 163, 184, 0.10)';
        var muted = themeColor('--etc-text-muted', '#9ca3af');
        var textMain = themeColor('--etc-text-main', '#e5e7eb');
        var gridColor = 'rgba(255, 255, 255, 0.08)';

        /* Every time field on the form is labelled "(local)" and is typed in local
           wall-clock, but the response stamps its series in UTC with no offset suffix
           (see _expand_time_series), so Plotly parsed them as naive and drew a UTC
           axis under a form that had promised local. Same instants, clock shifted —
           you typed 04:00 and the chart said 20:00. Convert once, here, and label the
           axis for the clock actually drawn. */
        var times = data.core.timestamps_iso.map(toLocalPlotTime);
        var targetEl = data.ephemeris.target_elevation_deg;
        var moonEl = data.ephemeris.moon_elevation_deg;
        var sunEl = data.ephemeris.sun_elevation_deg || [];
        var singleSnr = data.core.single_snr;
        var tSat = data.core.saturation_time_limit;

        /* Changing the goal used to leave the chart untouched, and correctly so: both
           of the plotted series describe the sky and the detector, not the question.
           The one array that does answer the question — how many frames this moment
           costs you — was computed per timestamp and then dropped on the floor before
           the response was assembled. With it returned, panel 2 can show the goal's
           own answer instead of a quantity that ignores it. */
        var requiredExp = data.core.required_exposures || null;
        var solvingForTime = Array.isArray(requiredExp) && requiredExp.length === times.length;
        var panel2Series = solvingForTime ? requiredExp : singleSnr;
        // Kept short deliberately: a y-axis title is rotated, so its length is vertical,
        // and this panel is only ~26% of the height. "Exposures to Reach Target SNR"
        // overran its own domain and collided with the titles above and below it.
        var panel2Title = solvingForTime ? 'Exposures Needed' : 'Single-Exposure SNR';
        // Fewest frames is the good end when solving for time; highest SNR is the good
        // end otherwise. The callout should point at whichever that is.
        var panel2Better = solvingForTime
            ? function (a, b) { return a < b; }
            : function (a, b) { return a > b; };

        /* "Observable" is the whole point of the top panel, so say it once here and
           let the other two panels inherit it: the target has to be up, and the sky
           has to be dark. -18 deg is astronomical twilight — the Sun far enough down
           that its scattered light no longer dominates the background.

           Outside that window the engine still returns numbers, and they are the
           reason this chart was unreadable: below the horizon the airmass clamp
           makes the target almost infinitely extinguished, so the saturation limit
           runs to millions of seconds and flattens every real value against zero.
           They are not wrong, they are answers to a question nobody asked. Mask them
           and each panel autoscales to the hours you could actually use. */
        var hasSun = sunEl.length === times.length;
        var observable = observableMask(data);
        var anyObservable = observable.some(Boolean);
        // With nothing observable there is nothing to autoscale to, so show the raw
        // curves rather than three empty panels.
        function maskUnobservable(values) {
            if (!anyObservable) { return values; }
            return values.map(function (v, i) { return observable[i] ? v : null; });
        }
        var snrPlot = maskUnobservable(panel2Series);
        var tSatPlot = maskUnobservable(tSat);

        var traces = [
            { x: times, y: targetEl, name: 'Target', type: 'scatter', mode: 'lines',
              line: { color: accent, width: 2 }, xaxis: 'x', yaxis: 'y',
              hovertemplate: '%{y:.1f}°<extra>Target</extra>' },
            { x: times, y: moonEl, name: 'Moon', type: 'scatter', mode: 'lines',
              line: { color: moon, width: 2 }, xaxis: 'x', yaxis: 'y',
              hovertemplate: '%{y:.1f}°<extra>Moon</extra>' },
            { x: times, y: snrPlot, name: panel2Title, type: 'scatter', mode: 'lines',
              line: { color: accent, width: 2 }, showlegend: false, xaxis: 'x2', yaxis: 'y2',
              hovertemplate: solvingForTime
                  ? '%{y:,.0f}<extra>frames needed</extra>'
                  : '%{y:.1f}<extra>SNR / frame</extra>' },
            { x: times, y: tSatPlot, name: 'Saturation Limit', type: 'scatter', mode: 'lines',
              line: { color: accent, width: 2 }, showlegend: false, xaxis: 'x3', yaxis: 'y3',
              hovertemplate: '%{y:,.0f} s<extra>saturates after</extra>' }
        ];

        /* The Sun answers "when is this actually night" directly, which the shading
           alone only implies — and it is the one curve a reader can check against
           their own sense of the date. Dimmer than Target and Moon on purpose: it is
           context for the other two, not a third thing to compare them against. */
        if (hasSun) {
            traces.splice(2, 0, {
                x: times, y: sunEl, name: 'Sun', type: 'scatter', mode: 'lines',
                line: { color: sun, width: 1.5, dash: 'dot' }, xaxis: 'x', yaxis: 'y',
                hovertemplate: '%{y:.1f}°<extra>Sun</extra>'
            });
        }

        var shapes = [];
        var annotations = [];

        /* Anchor a callout away from whichever edge it sits against, or Plotly centres
           it on the last tick and half the label lands outside the plot — which is what
           pushed the saturation figure into the axis, and what sent the band's own label
           off the right-hand side once the band drifted late in the window. */
        function edgeAnchor(index) {
            var frac = index / Math.max(1, times.length - 1);
            return frac > 0.85 ? 'right' : (frac < 0.15 ? 'left' : 'center');
        }

        /* Shade every stretch you could NOT observe, on all three panels rather than
           just the first. It used to be panel 1 only, in warning amber, at opacity
           0.06 and with nothing anywhere naming it — a faint yellow slab that looked
           like a rendering fault. Carrying it down the stack is what ties the empty
           stretches in panels 2 and 3 to their cause. */
        var unobservableRuns = contiguousRuns(observable, function (v) { return !v; });
        if (anyObservable) {
            unobservableRuns.forEach(function (run) {
                ['x', 'x2', 'x3'].forEach(function (ax, panel) {
                    shapes.push({
                        type: 'rect', xref: ax,
                        yref: (panel === 0 ? 'y' : 'y' + (panel + 1)) + ' domain',
                        x0: times[run[0]], x1: times[run[1]], y0: 0, y1: 1,
                        fillcolor: shadeUnobservable, line: { width: 0 }, layer: 'below'
                    });
                });
            });
        }
        /* Name the band in place rather than in the legend. A fourth legend entry has
           to be long enough to be meaningful, and at this panel's width that wrapped
           the strip onto four lines and squeezed the three plots. Labelling the widest
           run directly also puts the words on the thing they describe, which is what
           panel 3 already does for its saturation window. */
        var widestRun = null;
        unobservableRuns.forEach(function (run) {
            if (!widestRun || (run[1] - run[0]) > (widestRun[1] - widestRun[0])) { widestRun = run; }
        });
        if (anyObservable && widestRun) {
            var bandMid = Math.floor((widestRun[0] + widestRun[1]) / 2);
            annotations.push({
                x: times[bandMid], y: 1,
                xref: 'x', yref: 'y domain',
                text: 'target down / sky not dark', showarrow: false,
                xanchor: edgeAnchor(bandMid), yanchor: 'top', yshift: -4,
                font: { color: muted, size: 10, family: 'inherit' }
            });
        } else if (!anyObservable) {
            annotations.push({
                x: times[Math.floor(times.length / 2)], y: 1, xref: 'x', yref: 'y domain',
                text: 'not observable at any point in this window', showarrow: false,
                xanchor: 'center', yanchor: 'top', yshift: -4,
                font: { color: warning, size: 10, family: 'inherit' }
            });
        }
        shapes.push({
            type: 'line', xref: 'x', yref: 'y',
            x0: times[0], x1: times[times.length - 1], y0: 0, y1: 0,
            line: { color: muted, width: 1, dash: 'solid' }, opacity: 0.4, layer: 'below'
        });


        /* Every callout below reads the masked series, not the raw one. Labelling the
           best SNR or the tightest saturation limit at an hour the target is under
           the horizon is worse than not labelling it at all. */
        function extremeIndex(values, better) {
            var best = null;
            for (var i = 0; i < values.length; i++) {
                if (values[i] === null || !isFinite(values[i])) { continue; }
                if (best === null || better(values[i], values[best])) { best = i; }
            }
            return best;
        }

        // Panel 2: direct-label the peak only — never every point.
        var peak = extremeIndex(snrPlot, panel2Better);
        if (peak !== null) {
            annotations.push({
                x: times[peak], y: snrPlot[peak], xref: 'x2', yref: 'y2',
                text: solvingForTime ? fmt(snrPlot[peak], 0) + ' frames' : fmt(snrPlot[peak], 0),
                showarrow: false, yshift: 14,
                xanchor: edgeAnchor(peak),
                font: { color: textMain, size: 11, family: 'inherit' }
            });
        }

        // Panel 3: saturation-risk windows + the chosen exposure as a threshold.
        var riskRuns = contiguousRuns(tSatPlot, function (v) {
            return v !== null && v < singleExpTime;
        });
        riskRuns.forEach(function (run) {
            shapes.push({
                type: 'rect', xref: 'x3', yref: 'y3 domain',
                x0: times[run[0]], x1: times[run[1]], y0: 0, y1: 1,
                fillcolor: warning, opacity: 0.08, line: { width: 0 }, layer: 'below'
            });
        });
        shapes.push({
            type: 'line', xref: 'x3', yref: 'y3',
            x0: times[0], x1: times[times.length - 1], y0: singleExpTime, y1: singleExpTime,
            line: { color: muted, width: 1.5, dash: 'dash' }
        });
        annotations.push({
            x: times[times.length - 1], y: singleExpTime, xref: 'x3', yref: 'y3',
            text: 'your exposure: ' + fmt(singleExpTime, 0) + 's', showarrow: false,
            xanchor: 'right', yanchor: 'bottom', yshift: 4,
            font: { color: muted, size: 10, family: 'inherit' }
        });
        if (riskRuns.length) {
            annotations.push({
                x: times[riskRuns[0][0]], y: 1, xref: 'x3', yref: 'y3 domain',
                text: '⚠ saturation risk window', showarrow: false,
                xanchor: 'left', yanchor: 'top',
                font: { color: warning, size: 10, family: 'inherit' }
            });
        }
        var trough = extremeIndex(tSatPlot, function (a, b) { return a < b; });
        if (trough !== null) {
            annotations.push({
                x: times[trough], y: tSatPlot[trough], xref: 'x3', yref: 'y3',
                text: fmt(tSatPlot[trough], 0) + 's', showarrow: false, yshift: -14,
                xanchor: edgeAnchor(trough),
                font: { color: textMain, size: 11, family: 'inherit' }
            });
        }

        /* Log, not linear-from-zero. The limit and the exposure it is compared against
           are routinely three or four orders of magnitude apart — 120 s against tens
           of thousands here — and on a linear axis anchored at zero the threshold line
           lies flat on the baseline, exactly where "you are about to saturate" and
           "you have all the headroom in the world" look identical. The range is opened
           past both ends so the dashed threshold is always on screen even when nothing
           comes near it. */
        function saturationRange() {
            var vals = tSatPlot.filter(function (v) { return v !== null && isFinite(v) && v > 0; });
            vals.push(singleExpTime);
            var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
            if (!(lo > 0) || !isFinite(hi)) { return undefined; }
            return [Math.log10(lo / 2), Math.log10(hi * 2)];
        }
        var satRange = saturationRange();

        var axisBase = {
            gridcolor: gridColor, zeroline: false, linecolor: gridColor,
            tickfont: { color: muted, size: 10 }, automargin: true
        };
        var titleFont = { color: muted, size: 11 };

        // matches:'x3' keeps all three panels on one time axis (pan/zoom stays in
        // sync) while only the bottom one carries tick labels.
        var layout = {
            // No title and no warning banner drawn in here: the section heading and
            // the shared warning box above already say all of that.
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { family: 'inherit', color: muted },
            margin: { l: 62, r: 16, t: 30, b: 44 },
            height: 460,
            showlegend: true,
            legend: { orientation: 'h', x: 0, xanchor: 'left', y: 1.06, yanchor: 'bottom',
                      font: { color: textMain, size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
            hovermode: 'x unified',
            /* Plotly's default hover box is near-white and inherits layout.font, which
               here is the muted grey meant for axis ticks — grey on white, illegible,
               which is exactly how it was shipping. Theme it like the panels it sits
               over and give the text the main foreground colour. */
            hoverlabel: {
                bgcolor: themeColor('--etc-surface-1', '#14141E'),
                bordercolor: themeColor('--etc-border-color', 'rgba(255,255,255,0.10)'),
                font: { color: textMain, size: 11, family: 'inherit' }
            },
            shapes: shapes,
            annotations: annotations,
            xaxis:  Object.assign({}, axisBase, { domain: [0, 1], anchor: 'y',  matches: 'x3', showticklabels: false }),
            xaxis2: Object.assign({}, axisBase, { domain: [0, 1], anchor: 'y2', matches: 'x3', showticklabels: false }),
            xaxis3: Object.assign({}, axisBase, { domain: [0, 1], anchor: 'y3', title: { text: 'Time (local)', font: titleFont } }),
            yaxis:  Object.assign({}, axisBase, { domain: [0.72, 1],    anchor: 'x',  title: { text: 'Elevation (°)', font: titleFont } }),
            yaxis2: Object.assign({}, axisBase, { domain: [0.38, 0.64], anchor: 'x2', title: { text: panel2Title, font: titleFont } }),
            yaxis3: Object.assign({}, axisBase, { domain: [0, 0.26],    anchor: 'x3', title: { text: 'Saturation Limit (s)', font: titleFont },
                                                  type: 'log', range: satRange })
        };

        window.Plotly.react(el('etc-chart'), traces, layout, {
            responsive: true, displaylogo: false,
            modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d']
        });
        setChartStatus('');
    }

    /* Sweeping, the honest headline is not one instant but the best the window has and
       when it falls — the question a time range is opened to answer. Read off the same
       observable hours the chart draws, so the number always has a point on the curve
       behind it. */
    function renderSweepHero(data) {
        var times = data.core.timestamps_iso;
        var mask = observableMask(data);
        var anyObservable = mask.some(Boolean);
        var required = data.core.required_exposures;
        var solvingForTime = Array.isArray(required) && required.length === times.length;
        var series = solvingForTime ? required : data.core.total_snr;
        var better = solvingForTime
            ? function (a, b) { return a < b; }
            : function (a, b) { return a > b; };

        var best = null;
        for (var i = 0; i < series.length; i++) {
            if (anyObservable && !mask[i]) { continue; }
            if (!isFinite(series[i])) { continue; }
            if (best === null || better(series[i], series[best])) { best = i; }
        }
        if (best === null) { restoreHero(); return; }

        el('hero-label').textContent = solvingForTime
            ? 'Fewest Exposures in Window' : 'Best SNR in Window';
        el('hero-value').textContent = solvingForTime
            ? fmt(series[best], 0) + ' frames' : fmt(series[best], 2);
        el('hero-desc').textContent = anyObservable
            ? 'At ' + toLocalClock(times[best]) + ' local, the best of the observable hours.'
            : 'Nothing in this window is observable — this is the best of it regardless.';
    }

    function renderBatch(data, error) {
        if (error) {
            batchWarnings = [];
            refreshWarnings();
            setChartStatus(error);
            // The sweep is what the headline was showing, so put back the figure that
            // is still true rather than leaving a stale window summary standing.
            restoreHero();
            return;
        }
        batchWarnings = (data.flags.warnings || []).slice();
        if (data.flags.is_saturated) {
            batchWarnings.unshift('⚠️ At least one point in the time series exceeds the saturation limit — see the shaded window(s) below.');
        }
        refreshWarnings();

        renderSweepHero(data);

        var expInput = form.elements['options.single_exp_time'];
        renderChart(data, parseFloat(expInput && expInput.value) || 0);
    }

    // ========================================================================
    // Scheduling — debounce + cancel-the-predecessor
    // ========================================================================

    function makeRunner(delay, buildBody, url, onResult) {
        var timer = null;
        var controller = null;

        return function schedule() {
            clearTimeout(timer);
            timer = setTimeout(function () {
                if (controller) { controller.abort(); }
                controller = new AbortController();
                var mine = controller;

                var body;
                try {
                    body = buildBody();
                } catch (err) {
                    onResult(null, err.message);
                    return;
                }

                postJSON(url, body, mine.signal).then(function (data) {
                    if (mine.signal.aborted) { return; }
                    onResult(data, null);
                }).catch(function (err) {
                    if (err.name === 'AbortError') { return; }
                    onResult(null, err.message);
                });
            }, delay);
        };
    }

    var scheduleSingle = makeRunner(SINGLE_DEBOUNCE_MS, buildSingleRequest, CONFIG.apiUrl, renderSingle);
    var scheduleBatch = makeRunner(BATCH_DEBOUNCE_MS, buildBatchRequest, CONFIG.batchUrl, renderBatch);

    function recalculate() {
        // The single-point result is always computed — the sweep is an addition on
        // top of it, not an alternate mode.
        scheduleSingle();

        if (!el('toggle-batch').checked) {
            el('observing-window').hidden = true;
            resultsScroll.classList.remove('is-sweep');
            // The hero is showing a window that is no longer on screen.
            restoreHero();
            batchWarnings = [];
            refreshWarnings();
            return;
        }
        // Reveal the section immediately so flipping the switch has a visible
        // effect, rather than nothing happening until the request comes back.
        el('observing-window').hidden = false;
        // Promotes the chart to the top of the results panel — see etc.css.
        resultsScroll.classList.add('is-sweep');
        setChartStatus('Calculating…');
        scheduleBatch();
    }

    // ========================================================================
    // Tabs & conditional field groups
    // ========================================================================

    function initTabs() {
        var tabs = root.querySelectorAll('.etc-tab');
        Array.prototype.forEach.call(tabs, function (tab) {
            tab.addEventListener('click', function () {
                Array.prototype.forEach.call(tabs, function (other) {
                    var active = other === tab;
                    other.classList.toggle('is-active', active);
                    other.setAttribute('aria-selected', String(active));
                });
                Array.prototype.forEach.call(root.querySelectorAll('.etc-tabpanel'), function (panel) {
                    panel.hidden = panel.dataset.panel !== tab.dataset.tab;
                });
            });
        });
    }

    function syncGroups(attribute, selected) {
        Array.prototype.forEach.call(root.querySelectorAll('[data-' + attribute + ']'), function (group) {
            group.hidden = group.dataset[attribute].split(' ').indexOf(selected) === -1;
        });
    }

    /* Jansky and wavelength flux are one input wearing two units, because
       castor.schema calls both fields flux_value. Swapping only the unit label
       left the number behind, so switching system silently restated the target
       twelve orders of magnitude away and the SNR moved with it. Convert instead:
       the discriminator picks the units, it does not redefine the source.

       Only this pair converts. Vega and AB share target_mag and differ by a
       band-dependent offset (~0.16 mag at r'), which is a real astronomical
       distinction rather than a change of units — quietly shifting the number
       there would be inventing a photometric transform the engine never applied. */
    var C_ANGSTROM_PER_S = 2.99792458e18;      // physics.SPEED_OF_LIGHT_CGS * 1e8
    var JY_IN_CGS = 1e-23;                     // erg/s/cm^2/Hz per Jansky

    function fluxNuToLambdaFactor() {
        var nm = parseFloat(form.elements['instrument.optic_filter.central_wavelength'].value);
        if (!isFinite(nm) || nm <= 0) { return null; }
        var angstrom = nm * 10.0;
        return C_ANGSTROM_PER_S / (angstrom * angstrom);
    }

    function convertFluxValue(from, to) {
        var input = form.elements['target.brightness.flux_value'];
        var value = parseFloat(input.value);
        var factor = fluxNuToLambdaFactor();
        if (!isFinite(value) || factor === null) { return; }
        // toExponential, not toPrecision: these values straddle 1e-17 and 1e-5, and
        // toPrecision spells the latter 0.00005249, which reads as a different kind of
        // number from the 5.248e-5 the field ships with.
        if (from === 'jansky_flux' && to === 'wavelength_flux') {
            input.value = (value * JY_IN_CGS * factor).toExponential(3);
        } else if (from === 'wavelength_flux' && to === 'jansky_flux') {
            input.value = (value / factor / JY_IN_CGS).toExponential(3);
        }
    }

    /* The unit the flux input is currently holding, which is NOT the same thing as
       the selected brightness type: picking Vega or AB hides the field but leaves
       whatever was in it. Tracking the selection instead meant a detour through a
       magnitude system lost the conversion — wavelength -> AB -> Jansky relabelled
       erg/s/cm2/A as Jy without touching the number. Seeded to the unit the shipped
       default is written in. */
    var fluxValueUnit = 'jansky_flux';

    function syncFluxValueUnit(brightness) {
        if (brightness !== 'jansky_flux' && brightness !== 'wavelength_flux') { return; }
        if (fluxValueUnit !== brightness) {
            convertFluxValue(fluxValueUnit, brightness);
            fluxValueUnit = brightness;
        }
    }

    function syncConditionalFields() {
        var brightness = form.elements['target.brightness.type'].value;
        syncFluxValueUnit(brightness);
        syncGroups('brightness', brightness);
        el('label-target-mag').textContent =
            brightness === 'ab_mag' ? 'Apparent Magnitude (AB)' : 'Apparent Magnitude';
        el('unit-flux-value').innerHTML =
            brightness === 'jansky_flux' ? 'Jy' : 'erg/s/cm&sup2;/&Aring;';

        syncGroups('sed', form.elements['target.sed.type'].value);
        syncGroups('options', form.elements['options.type'].value);
        syncGroups('when', el('toggle-batch').checked ? 'batch' : 'single');
    }

    // ========================================================================
    // Presets — an observing profile (site + its rigs) cascading into a rig, plus
    // an independent filter. The same rules are implemented for Python callers in
    // castorCLI/presets.py; both read the same data/presets.json.
    // ========================================================================

    var presets = {};

    function profiles() { return presets.profiles || {}; }

    /* Telescope and camera lists are scoped to the selected site — that scoping is
       why the site selector sits above them. */
    function catalogue(kind) {
        return (profiles()[el('select-profile').value] || {})[kind] || {};
    }

    /* Presets are stored shaped like castor.schema itself, so applying one means
       walking the fragment down to its leaves and writing each into the matching
       input. */
    function flattenFragment(prefix, fragment, out) {
        Object.keys(fragment).forEach(function (key) {
            var path = prefix + '.' + key;
            var value = fragment[key];
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                flattenFragment(path, value, out);
            } else {
                out[path] = value;
            }
        });
        return out;
    }

    function applyFragment(section, fragment) {
        var flat = flattenFragment(section, fragment || {}, {});
        Object.keys(flat).forEach(function (path) {
            var input = form.elements[path];
            if (!input) { return; }
            input.value = input.hasAttribute('data-percent')
                ? fractionToPercentText(flat[path])
                : String(flat[path]);
        });
    }

    var SELECTOR_IDS = ['select-profile', 'select-telescope', 'select-camera', 'select-filter'];

    /* Choosing "Custom" means the numbers have no preset behind them, so the raw fields
       stop being a detail to check on demand and become the only way to say anything —
       reveal them. Only on an actual selection, not on first paint: everything starts on
       Custom before any choice has been made, and opening it there would just be the
       uncollapsed form again.

       Picking a preset again closes the panel back up, but only one this code opened:
       autoOpened records that, so a panel the reader opened for themselves is never
       shut on their behalf. (Each panel belongs to exactly one selector, which is what
       makes closing well-defined — while a single shared panel served all four
       selectors, no correct rule existed.) */
    var autoOpened = Object.create(null);

    function panelFor(name) {
        return root.querySelector('.etc-details[data-details="' + name + '"]');
    }

    function revealDetails(name) {
        var details = panelFor(name);
        if (!details || details.open) { return; }
        details.open = true;
        autoOpened[name] = true;
    }

    function collapseDetails(name) {
        var details = panelFor(name);
        if (!details || !autoOpened[name]) { return; }
        details.open = false;
        delete autoOpened[name];
    }

    function watchPanels() {
        Array.prototype.forEach.call(root.querySelectorAll('.etc-details'), function (details) {
            details.addEventListener('toggle', function () {
                // Closing it by hand takes ownership back. Opening it by hand was never
                // ours to close, so it never enters autoOpened in the first place.
                if (!details.open) { delete autoOpened[details.dataset.details]; }
            });
        });
    }

    function fillSelect(select, entries, placeholder) {
        select.innerHTML = '';
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = placeholder;
        select.appendChild(blank);
        entries.forEach(function (entry) {
            var option = document.createElement('option');
            option.value = entry[0];
            option.textContent = entry[1];
            select.appendChild(option);
        });
    }

    function named(source) {
        return Object.keys(source).map(function (key) {
            return [key, source[key].name || key];
        });
    }

    /* Live-derived from the form rather than from the preset, so it keeps telling the
       truth after a field is edited by hand. */
    function renderSpecs() {
        var value = function (name) { return parseFloat(form.elements[name].value); };
        var aperture = value('instrument.telescope.primary_mirror_diameter');
        var focal = value('instrument.telescope.focal_length');
        var num = function (v) { return String(Math.round(v * 1e6) / 1e6); };

        var lines = [
            num(aperture) + ' m aperture · ' + num(focal) + ' m focal length · ' +
                (aperture ? 'f/' + (focal / aperture).toFixed(1) : 'f/—'),
            num(value('instrument.camera.pixel_pitch')) + ' µm pixels · QE ' +
                value('instrument.camera.quantum_efficiency').toFixed(0) + '% · read noise ' +
                num(value('instrument.camera.readout_noise')) + ' e-'
        ];

        // Shown, never applied: seeing describes the night being planned, not the site,
        // and it is the field an observer is most likely to have set on purpose.
        var seeing = (profiles()[el('select-profile').value] || {}).median_seeing_fwhm;
        if (seeing !== undefined) {
            lines.push('Site median seeing ' + seeing + '" — reference only, not applied');
        }
        el('specs-card').textContent = lines.join('\n');
    }

    /* The three catalogues a site owns, each with the select it fills, the part of the
       request it writes, and the disclosure it reveals. */
    var CATALOGUES = [
        { kind: 'telescopes', select: 'select-telescope', section: 'instrument.telescope', key: 'telescope', panel: 'telescope' },
        { kind: 'cameras', select: 'select-camera', section: 'instrument.camera', key: 'camera', panel: 'camera' },
        { kind: 'filters', select: 'select-filter', section: 'instrument.optic_filter', key: 'optic_filter', panel: 'filter' }
    ];

    /* A filter may also speak for the sky it looks through and for the efficiency of
       everything in front of it, because both depend on the band while the request has
       one number for each. Mirrors _overlay in castorCLI/presets.py.

       The base is re-applied first, which the Python side gets for free by building a
       fresh fragment every time and this side does not: without it, moving from a band
       that carries a correction to one that does not would leave the previous band's
       numbers sitting in the form, looking like the new filter's. Bands with no
       measurement must fall back to the site and the rig, not to whatever was chosen
       before them.

       A catalogue sitting on Custom is left alone in both steps. Those numbers are the
       reader's own, and a filter has no business overwriting them. */
    function applyBand(entry) {
        var profile = profiles()[el('select-profile').value];
        if (!profile) { return; }

        if (profile.environment) {
            applyFragment('environment', profile.environment);
            if (entry && entry.environment) { applyFragment('environment', entry.environment); }
        }

        var telescopeId = el('select-telescope').value;
        var rig = (profile.telescopes || {})[telescopeId];
        if (rig) {
            applyFragment('instrument.telescope', rig.telescope);
            /* The filter's telescope fragment is keyed by telescope, because a band's
               throughput is measured on one rig and says nothing about the other. Reading
               it as a flat fragment names no field that exists, so it applies silently as
               nothing and the rig's own default stands in for a measurement. */
            var measured = ((entry && entry.telescope) || {})[telescopeId];
            if (measured) { applyFragment('instrument.telescope', measured); }
        }
    }

    function showCaveat(profile) {
        var box = el('profile-caveat');
        if (!box) { return; }
        var caveat = profile && profile.caveat;
        box.textContent = caveat || '';
        box.hidden = !caveat;
    }

    function applyProfile(profileId) {
        var profile = profiles()[profileId];
        showCaveat(profile);

        if (!profile) {
            // Nothing to choose from and nothing chosen: every catalogue empties to
            // Custom, and each one's fields become the only way to describe it.
            CATALOGUES.forEach(function (cat) {
                fillSelect(el(cat.select), [], 'Custom');
                revealDetails(cat.panel);
            });
            renderSpecs();
            return;
        }
        // A profile with an environment block is a real site; one without is a hardware
        // family and must not invent a location. See data/presets.json.
        if (profile.environment) { applyFragment('environment', profile.environment); }

        CATALOGUES.forEach(function (cat) {
            var entries = profile[cat.kind] || {};
            var select = el(cat.select);
            fillSelect(select, named(entries), 'Custom');

            // First listed is the default — see the note on ordering in presets.json.
            var first = Object.keys(entries)[0];
            if (first) {
                select.value = first;
                applyFragment(cat.section, entries[first][cat.key]);
                if (cat.kind === 'filters') { applyBand(entries[first]); }
                collapseDetails(cat.panel);
            } else {
                // A real profile can still leave one catalogue empty — "other" has
                // no filters yet. fillSelect above already fell that select back to
                // Custom, but setting .value in JS fires no change event, so
                // bindSlice's own reveal-on-Custom never runs. Do here what that
                // handler would have done: there is no data behind the selection,
                // so show the fields that are now the only way to describe it.
                revealDetails(cat.panel);
            }
        });
        renderSpecs();
    }

    function initPresets() {
        var profileSelect = el('select-profile');

        /* Each of the three hardware selectors writes only its own slice. Picking a
           different camera at the same site is no reason to re-apply that site's sky
           over an mu_dark the observer tuned, nor to reset the telescope. */
        function bindSlice(select, kind, section, key, panel) {
            select.addEventListener('change', function () {
                var preset = catalogue(kind)[select.value];
                if (preset) {
                    applyFragment(section, preset[key]);
                    if (kind === 'filters') { applyBand(preset); }
                    collapseDetails(panel);
                } else {
                    revealDetails(panel);
                }
                renderSpecs();
                recalculate();
            });
            bindCustomReselect(select, panel);
        }

        /* Re-picking the value a select already holds fires no change event, and every
           selector starts on Custom — so on a fresh page, opening the menu and choosing
           Custom would do nothing at all, which reads as the reveal being broken rather
           than as nothing having changed. Opening the menu while already on Custom is
           reason enough to show the fields. */
        function bindCustomReselect(select, panel) {
            select.addEventListener('click', function () {
                if (!select.value) { revealDetails(panel); }
            });
        }

        fetch(CONFIG.presetsUrl).then(function (response) {
            if (!response.ok) { throw new Error('HTTP ' + response.status); }
            return response.json();
        }).then(function (data) {
            presets = data || {};
            fillSelect(profileSelect, named(profiles()), 'Custom');
            CATALOGUES.forEach(function (cat) { fillSelect(el(cat.select), [], 'Custom'); });

            profileSelect.addEventListener('change', function () {
                applyProfile(profileSelect.value);
                recalculate();
            });
            profileSelect.addEventListener('click', function () {
                if (!profileSelect.value) { CATALOGUES.forEach(function (c) { revealDetails(c.panel); }); }
            });
            CATALOGUES.forEach(function (cat) {
                bindSlice(el(cat.select), cat.kind, cat.section, cat.key, cat.panel);
            });

            /* Open on the first profile rather than on Custom. The HTML defaults are
               real, usable numbers but they come from nowhere in particular, so booting
               on Custom meant every selector claimed the values were hand-entered while
               the panels holding those values stayed shut — the label and the behaviour
               disagreed. Starting from a named configuration removes the contradiction
               instead of special-casing first paint out of the reveal rule. */
            var firstProfile = Object.keys(profiles())[0];
            if (firstProfile) {
                profileSelect.value = firstProfile;
                applyProfile(firstProfile);
                recalculate();
            } else {
                renderSpecs();
            }
        }).catch(function (err) {
            // Presets are a convenience, not a requirement — every field already
            // carries a usable default, so say so plainly and leave them editable
            // instead of stranding the dropdown on "Loading…".
            console.error('Preset load failed:', err);
            [profileSelect].concat(CATALOGUES.map(function (c) { return el(c.select); })).forEach(function (select) {
                select.innerHTML = '<option>Presets unavailable — using defaults below</option>';
                select.disabled = true;
                select.classList.add('is-error');
            });
        });
    }

    // ========================================================================
    // SAVE / LOAD — a saved file is castor.schema's own request shape, so it stays
    // readable by anything else that speaks the contract rather than only by this form.
    // ========================================================================

    var dialog = el('json-dialog');

    function openJsonDialog(options) {
        el('json-dialog-title').textContent = options.title;
        el('json-dialog-hint').textContent = options.hint;
        var text = el('json-dialog-text');
        text.value = options.text || '';
        text.readOnly = Boolean(options.readOnly);
        setDialogError('');

        var actions = el('json-dialog-actions');
        actions.innerHTML = '';
        options.actions.forEach(function (spec) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'etc-action' + (spec.variant ? ' etc-action-' + spec.variant : '');
            button.textContent = spec.label;
            button.addEventListener('click', spec.onClick);
            actions.appendChild(button);
        });

        dialog.showModal();
        text.focus();
        if (options.readOnly) {
            // Selecting scrolls to the end of the selection; the reader wants the start.
            text.select();
            text.scrollTop = 0;
        }
    }

    function setDialogError(message) {
        el('json-dialog-error-text').textContent = message;
        el('json-dialog-error').hidden = !message;
    }

    /* Every branch's value is kept, not just the ones the current discriminators
       select. That makes it a superset of a valid request — deliberately, so switching
       brightness type after a load doesn't find the fields blank — which is why it is
       read back through applyLoaded rather than posted. */
    function buildSaveObject() {
        var all = PayloadBuilder.build(false);
        var batch = all.batch || {};
        delete all.batch;
        all.batch_time = {
            start_time_utc: batch.start_time_utc,
            end_time_utc: batch.end_time_utc,
            time_step_minutes: batch.time_step_minutes
        };
        all.batch_enabled = el('toggle-batch').checked;
        return all;
    }

    function importFromDialog() {
        var raw = el('json-dialog-text').value.trim();
        if (!raw) {
            setDialogError('Nothing to import — paste the JSON above first.');
            return;
        }
        var data;
        try {
            data = JSON.parse(raw);
        } catch (err) {
            setDialogError('That is not valid JSON: ' + err.message);
            return;
        }
        if (data === null || typeof data !== 'object' || Array.isArray(data)) {
            setDialogError('Expected a JSON object like the one SAVE produces.');
            return;
        }
        applyLoaded(data);
        dialog.close();
    }

    function initSaveLoad() {
        el('btn-save').addEventListener('click', function () {
            openJsonDialog({
                title: 'Save request',
                hint: 'Copy this and keep it wherever you like — a file, a script, a message. LOAD takes it back.',
                text: JSON.stringify(buildSaveObject(), null, 2),
                readOnly: true,
                // Dismiss on the left, the action that commits on the right, the way
                // this platform puts them. The row is right-aligned, so the last
                // entry here is the one nearest the corner and under the cursor.
                actions: [
                    { label: 'Close', variant: 'ghost', onClick: function () { dialog.close(); } },
                    { label: 'Download', onClick: downloadDialogText },
                    { label: 'Copy', variant: 'primary', onClick: copyDialogText }
                ]
            });
        });

        el('btn-load').addEventListener('click', function () {
            openJsonDialog({
                title: 'Load request',
                hint: 'Paste a saved request below, or pick a file to read one in — either way you see it before it is applied.',
                text: '',
                actions: [
                    { label: 'Cancel', variant: 'ghost', onClick: function () { dialog.close(); } },
                    { label: 'Choose file…', onClick: function () { el('load-file-input').click(); } },
                    { label: 'Import', variant: 'primary', onClick: importFromDialog }
                ]
            });
        });

        // Fills the box rather than applying straight away, so a file gets the same
        // look-before-you-leap as a paste.
        el('load-file-input').addEventListener('change', function (event) {
            var file = event.target.files && event.target.files[0];
            event.target.value = '';   // so re-picking the same file fires change again
            if (!file) { return; }
            file.text().then(function (text) {
                el('json-dialog-text').value = text;
                setDialogError('');
            }).catch(function (err) {
                setDialogError('Could not read that file: ' + err.message);
            });
        });
    }

    function copyDialogText() {
        var text = el('json-dialog-text');
        text.select();
        // The Clipboard API needs a secure context, which a plain-http deployment is not.
        // Falling back to selecting the text means the worst case is still one Ctrl+C.
        if (!navigator.clipboard) {
            setDialogError('Clipboard unavailable here — the text is selected, copy it with Ctrl/Cmd+C.');
            return;
        }
        navigator.clipboard.writeText(text.value).then(function () {
            setDialogError('');
        }).catch(function () {
            setDialogError('Could not reach the clipboard — the text is selected, copy it with Ctrl/Cmd+C.');
        });
    }

    function downloadDialogText() {
        var blob = new Blob([el('json-dialog-text').value], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = 'castor_request.json';
        link.click();
        URL.revokeObjectURL(url);
    }

    function lookup(source, path) {
        var node = source;
        var parts = path.split('.');
        for (var i = 0; i < parts.length; i++) {
            if (node === null || typeof node !== 'object' || !(parts[i] in node)) { return undefined; }
            node = node[parts[i]];
        }
        return node;
    }

    function applyLoaded(data) {
        // Field-by-field rather than wholesale: a save file predating a newer field
        // leaves that field at its current value instead of blanking it.
        var elements = form.elements;
        for (var i = 0; i < elements.length; i++) {
            var input = elements[i];
            if (!input.name) { continue; }

            var path = input.name.indexOf('batch.') === 0
                ? input.name.replace('batch.', 'batch_time.')
                : input.name;
            var value = lookup(data, path);
            if (value === undefined || value === null) { continue; }

            if (input.type === 'checkbox') {
                input.checked = Boolean(value);
            } else if (input.type === 'datetime-local') {
                input.value = isoToLocalInputValue(value);
            } else if (input.hasAttribute('data-percent')) {
                input.value = fractionToPercentText(value);
            } else {
                input.value = String(value);
            }
        }

        if (typeof data.batch_enabled === 'boolean') {
            el('toggle-batch').checked = data.batch_enabled;
        }
        // The file's own discriminator says what unit its flux_value is in. Adopt it
        // rather than letting syncConditionalFields convert a value already correct.
        var loadedBrightness = form.elements['target.brightness.type'].value;
        if (loadedBrightness === 'jansky_flux' || loadedBrightness === 'wavelength_flux') {
            fluxValueUnit = loadedBrightness;
        }
        // Leaving the selectors on their previous choice would claim a provenance
        // these numbers no longer have.
        SELECTOR_IDS.forEach(function (id) { el(id).value = ''; });
        // Loaded numbers match no preset, and the reader has every reason to want to see
        // what they just opened.
        CATALOGUES.forEach(function (cat) { revealDetails(cat.panel); });
        renderSpecs();
        syncConditionalFields();
        recalculate();
    }

    // ========================================================================
    // Init
    // ========================================================================

    /* The night LOT observed SN 2025wny, not "now".

       The rest of the form boots on a real measurement - LOT 1 m, Sloan r', image A
       at AB 19.6 - and an observing time of "now" would quietly break it: the target
       is a pre-dawn winter object, so for most of the year "now" puts it under the
       horizon and the first thing a new user sees is an airmass warning against
       numbers that are otherwise exactly right. Pinning the epoch keeps the whole
       default self-consistent, at the cost of opening on a past date, which is the
       honest trade: this is a worked example first and a blank form second.

       These are fixed UTC instants rendered into the browser's own wall clock, not
       fixed local strings - a hard-coded "04:00" would mean a different instant, and
       a different airmass, for every timezone the page is opened in. 20:00Z is 04:00
       the next morning at Lulin, near the target's transit and clear of airmass 2.
       The sweep brackets it across the observable window, 02:00 to 06:00 local, so
       the batch chart opens on the target actually climbing out of the murk. */
    var LOT_EPOCH_UTC = '2025-09-28T20:00:00Z';
    var LOT_SWEEP_START_UTC = '2025-09-28T18:00:00Z';
    var LOT_SWEEP_END_UTC = '2025-09-28T22:00:00Z';

    function initDefaultTimes() {
        form.elements['environment.observing_time_utc'].value = isoToLocalInputValue(LOT_EPOCH_UTC);
        form.elements['batch.start_time_utc'].value = isoToLocalInputValue(LOT_SWEEP_START_UTC);
        form.elements['batch.end_time_utc'].value = isoToLocalInputValue(LOT_SWEEP_END_UTC);
    }

    initTabs();
    watchPanels();
    initDefaultTimes();
    initPresets();
    initSaveLoad();
    syncConditionalFields();

    form.addEventListener('input', function () {
        syncConditionalFields();
        renderSpecs();
        recalculate();
    });
    form.addEventListener('change', function () {
        syncConditionalFields();
        recalculate();
    });

    // One calculation up front so the results panel isn't empty on first paint.
    recalculate();
})();
