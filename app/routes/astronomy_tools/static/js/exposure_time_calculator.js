/* Exposure Time Calculator (CASTOR engine) — form wiring, API call, results rendering.
 * Form inputs are named with dotted paths matching CASTOR's ObservationRequest schema
 * exactly (e.g. name="instrument.telescope.primary_mirror_diameter"), so the payload
 * is built generically by walking the form — no per-field mapping code to keep in sync. */
(function () {
    'use strict';

    var API_URL = '/api/exposure_time_calculator';
    var PRESETS_URL = '/api/exposure_time_calculator/presets';

    function $(id) { return document.getElementById(id); }

    // ── Generic dotted-path payload builder ─────────────────────────
    function setNestedValue(obj, pathParts, value) {
        var current = obj;
        for (var i = 0; i < pathParts.length - 1; i++) {
            var part = pathParts[i];
            if (!current[part]) current[part] = {};
            current = current[part];
        }
        current[pathParts[pathParts.length - 1]] = value;
    }

    function parseFieldValue(el) {
        if (el.type === 'number') {
            return el.value === '' ? null : parseFloat(el.value);
        }
        if (el.type === 'datetime-local') {
            return el.value === '' ? null : new Date(el.value).toISOString();
        }
        return el.value;
    }

    function buildRequest() {
        var payload = {};
        var elements = $('etc-form').elements;
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            if (!el.name) continue;
            // Skip fields belonging to a currently-hidden dynamic group (e.g. the
            // brightness-type field not selected, or the calc-mode not selected).
            if (el.closest('.etc-dyn[hidden]')) continue;

            var value = parseFieldValue(el);
            if (value === null || value === '') continue;

            setNestedValue(payload, el.name.split('.'), value);
        }
        return payload;
    }

    // ── Hardware presets ─────────────────────────────────────────────
    function applyPreset(presetData) {
        Object.keys(presetData).forEach(function (dottedName) {
            var el = document.querySelector('[name="' + dottedName + '"]');
            if (el) el.value = presetData[dottedName];
        });
    }

    function populatePresetSelect(selectEl, presetCategory) {
        selectEl.innerHTML = '';
        Object.keys(presetCategory).forEach(function (key) {
            var opt = document.createElement('option');
            opt.value = key;
            opt.textContent = key.replace(/_/g, ' ');
            selectEl.appendChild(opt);
        });
        var firstKey = Object.keys(presetCategory)[0];
        if (firstKey) {
            selectEl.value = firstKey;
            applyPreset(presetCategory[firstKey]);
        }
    }

    function loadPresets() {
        fetch(PRESETS_URL).then(function (res) {
            if (!res.ok) throw new Error('Failed to load presets');
            return res.json();
        }).then(function (presets) {
            populatePresetSelect($('preset-telescope'), presets.telescopes || {});
            populatePresetSelect($('preset-camera'), presets.cameras || {});
            populatePresetSelect($('preset-filter'), presets.filters || {});

            $('preset-telescope').addEventListener('change', function (e) {
                applyPreset(presets.telescopes[e.target.value]);
            });
            $('preset-camera').addEventListener('change', function (e) {
                applyPreset(presets.cameras[e.target.value]);
            });
            $('preset-filter').addEventListener('change', function (e) {
                applyPreset(presets.filters[e.target.value]);
            });
        }).catch(function (err) {
            console.warn('Preset load failed:', err);
        });
    }

    // ── Progressive-disclosure toggles ──────────────────────────────
    function toggleBrightnessUI(type) {
        $('grp-target-mag').hidden = !['vega_mag', 'ab_mag'].includes(type);
        $('grp-zero-point').hidden = (type !== 'vega_mag');
        $('grp-flux-value').hidden = !['jansky_flux', 'wavelength_flux'].includes(type);
    }
    $('f-tgt-bright-type').addEventListener('change', function (e) { toggleBrightnessUI(e.target.value); });
    toggleBrightnessUI($('f-tgt-bright-type').value);

    function toggleCalcModeUI(type) {
        $('grp-num-exposures').hidden = (type !== 'solve_snr');
        $('grp-target-snr').hidden = (type !== 'solve_time');
    }
    $('f-opt-mode').addEventListener('change', function (e) { toggleCalcModeUI(e.target.value); });
    toggleCalcModeUI($('f-opt-mode').value);

    // ── Results rendering ────────────────────────────────────────────
    function fmt(v, digits) {
        if (v === null || v === undefined || isNaN(v)) return '--';
        return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 3 : digits });
    }

    function escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function renderResults(data) {
        $('etc-placeholder').hidden = true;
        $('etc-results-body').hidden = false;

        var warnBox = $('etc-warnings');
        var warnings = (data.flags.warnings || []).slice();
        if (data.flags.is_saturated) {
            warnings.unshift('Warning: single exposure time exceeds the saturation limit (full well capacity reached).');
        }
        if (warnings.length) {
            warnBox.hidden = false;
            warnBox.innerHTML = '<strong>Observation Warnings</strong><ul>' +
                warnings.map(function (w) { return '<li>' + escapeHtml(w) + '</li>'; }).join('') +
                '</ul>';
        } else {
            warnBox.hidden = true;
            warnBox.innerHTML = '';
        }

        if (data.core.required_exposures === null || data.core.required_exposures === undefined) {
            $('etc-hero-label').textContent = 'Signal-to-Noise Ratio';
            $('etc-hero-value').textContent = fmt(data.core.total_snr, 2);
            $('etc-hero-desc').textContent = 'Calculated from the given number of exposures.';
        } else {
            $('etc-hero-label').textContent = 'Required Exposures';
            $('etc-hero-value').textContent = data.core.required_exposures + ' frames';
            $('etc-hero-desc').textContent = 'Total SNR achieved: ' + fmt(data.core.total_snr, 2);
        }

        $('res-source-rate').textContent = fmt(data.budget.source_count_rate, 3);
        $('res-sky-rate').textContent = fmt(data.budget.sky_count_rate, 4);
        $('res-peak-rate').textContent = fmt(data.budget.peak_pixel_rate, 4);
        $('res-single-snr').textContent = fmt(data.core.single_snr, 2);

        $('res-total-fwhm').textContent = fmt(data.diagnostics.total_fwhm, 2);
        $('res-pixel-scale').textContent = fmt(data.diagnostics.pixel_scale, 3);
        $('res-eff-area').textContent = fmt(data.diagnostics.effective_area, 3);
        $('res-throughput').textContent = fmt(data.diagnostics.total_throughput * 100, 1);
        $('res-enclosed-flux').textContent = fmt(data.diagnostics.enclosed_flux_fraction * 100, 1);
        $('res-num-pixels').textContent = fmt(data.diagnostics.num_pixels_aperture, 1);

        $('res-sat-time').textContent = fmt(data.core.saturation_time_limit, 2);
    }

    function showFormError(message) {
        var box = $('etc-form-error');
        box.textContent = message;
        box.hidden = false;
    }
    function clearFormError() {
        var box = $('etc-form-error');
        box.hidden = true;
        box.textContent = '';
    }

    // ── Submit handler ───────────────────────────────────────────────
    $('etc-form').addEventListener('submit', function (e) {
        e.preventDefault();
        clearFormError();

        var payload;
        try {
            payload = buildRequest();
        } catch (err) {
            showFormError('Could not build request: ' + err.message);
            return;
        }

        var btn = $('etc-submit-btn');
        btn.disabled = true;
        btn.textContent = 'Calculating…';

        fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    if (!res.ok) throw new Error(data.error || 'Calculation failed');
                    return data;
                });
            })
            .then(renderResults)
            .catch(function (err) {
                showFormError(err.message);
            })
            .finally(function () {
                btn.disabled = false;
                btn.textContent = 'Run Calculation';
            });
    });

    loadPresets();
})();
