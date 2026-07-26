/* Exposure Time Calculator (CASTOR engine) — ported from CASTOR's own
 * src/castorGUI/frontend/js/script.js, adapted to call this site's routes.
 * Form inputs are named with dotted paths matching CASTOR's ObservationRequest
 * schema exactly (e.g. name="instrument.telescope.primary_mirror_diameter"),
 * so the payload is built generically by walking the form. */

var API_URL = '/api/exposure_time_calculator';
var PRESETS_URL = '/api/exposure_time_calculator/presets';

// ==========================================
// 1. UI State Controller
// ==========================================
class UIController {
    constructor() {
        this.presets = null;
        this.bindEvents();
        this.initUI();
    }

    async loadPresets() {
        try {
            const response = await fetch(PRESETS_URL);
            if (!response.ok) throw new Error('HTTP ' + response.status);
            this.presets = await response.json();

            this.populateSelect('telescope-template', this.presets.telescopes, 'telescopes');
            this.populateSelect('camera-template', this.presets.cameras, 'cameras');
            this.populateSelect('filter-template', this.presets.filters, 'filters');
        } catch (error) {
            console.error('Preset load failed:', error);
            this.showPresetLoadError();
        }
    }

    // Presets are a convenience, not a requirement — every field already carries a
    // sensible default value, so on failure we just surface a clear message and
    // reveal the editable fields instead of leaving the dropdown stuck on "Loading…".
    showPresetLoadError() {
        ['telescope-template', 'camera-template', 'filter-template'].forEach((id) => {
            const select = document.getElementById(id);
            select.innerHTML = '';
            const opt = document.createElement('option');
            opt.value = 'CUSTOM';
            opt.textContent = 'Presets unavailable — using defaults below';
            select.appendChild(opt);
            select.disabled = true;
            select.classList.add('preset-error');
            this.toggleCustomDetails(select);
        });
    }

    populateSelect(elementId, presetCategory, categoryName) {
        const select = document.getElementById(elementId);
        select.innerHTML = '';

        for (const key in presetCategory) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = key.replace(/_/g, ' ');
            select.appendChild(option);
        }

        const customOption = document.createElement('option');
        customOption.value = 'CUSTOM';
        customOption.textContent = 'Custom Parameters';
        select.appendChild(customOption);

        if (Object.keys(presetCategory).length > 0) {
            const firstKey = Object.keys(presetCategory)[0];
            select.value = firstKey;
            this.applyPreset(categoryName, firstKey);
        }

        this.toggleCustomDetails(select);
    }

    bindEvents() {
        document.getElementById('telescope-template').addEventListener('change', (e) => {
            this.applyPreset('telescopes', e.target.value);
            this.toggleCustomDetails(e.target);
        });
        document.getElementById('camera-template').addEventListener('change', (e) => {
            this.applyPreset('cameras', e.target.value);
            this.toggleCustomDetails(e.target);
        });
        document.getElementById('filter-template').addEventListener('change', (e) => {
            this.applyPreset('filters', e.target.value);
            this.toggleCustomDetails(e.target);
        });

        document.getElementById('target-brightness-type').addEventListener('change', (e) => this.toggleBrightnessUI(e.target.value));
        document.getElementById('sed-type').addEventListener('change', (e) => this.toggleSedUI(e.target.value));
        document.getElementById('calc-mode-type').addEventListener('change', (e) => this.toggleCalcStrategyUI(e.target.value));
    }

    initUI() {
        this.toggleBrightnessUI(document.getElementById('target-brightness-type').value);
        this.toggleSedUI(document.getElementById('sed-type').value);
        this.toggleCalcStrategyUI(document.getElementById('calc-mode-type').value);
    }

    applyPreset(category, templateName) {
        if (templateName === 'CUSTOM') return;
        if (!this.presets || !this.presets[category]) return;

        const presetData = this.presets[category][templateName];
        if (!presetData) return;

        for (const [inputName, value] of Object.entries(presetData)) {
            const inputElement = document.querySelector(`input[name="${inputName}"]`);
            if (inputElement && value !== null) {
                inputElement.value = value;
                inputElement.style.transition = 'background-color 0.3s';
                inputElement.style.backgroundColor = 'rgba(197, 160, 89, 0.3)';
                setTimeout(() => inputElement.style.backgroundColor = '', 400);
            }
        }
    }

    toggleCustomDetails(selectElement) {
        const customDetailsDiv = selectElement.closest('.instrument-group').querySelector('.custom-details');
        if (selectElement.value === 'CUSTOM') {
            customDetailsDiv.classList.remove('hidden-detail');
        } else {
            customDetailsDiv.classList.add('hidden-detail');
        }
    }

    toggleBrightnessUI(type) {
        document.getElementById('group-target-mag').hidden = !['vega_mag', 'ab_mag'].includes(type);
        document.getElementById('group-zero-point-flux').hidden = (type !== 'vega_mag');
        document.getElementById('group-flux-value').hidden = !['jansky_flux', 'wavelength_flux'].includes(type);
    }

    toggleSedUI(type) {
        document.getElementById('group-temperature').hidden = (type !== 'Temp');
    }

    toggleCalcStrategyUI(type) {
        document.getElementById('group-solve-snr').hidden = (type !== 'solve_snr');
        document.getElementById('group-solve-time').hidden = (type !== 'solve_time');
    }

    setLoadingState(isLoading) {
        const btn = document.getElementById('btn-submit');
        if (isLoading) {
            btn.disabled = true;
            btn.textContent = 'Calculating...';
            btn.style.opacity = '0.7';
            btn.style.cursor = 'not-allowed';
        } else {
            btn.disabled = false;
            btn.textContent = 'Run Simulation';
            btn.style.opacity = '1';
            btn.style.cursor = 'pointer';
        }
    }
}

// ==========================================
// 2. Payload Builder — generic dotted-path walker
// ==========================================
class PayloadBuilder {
    static build() {
        const payload = {};
        const formElements = document.getElementById('castor-form').elements;

        for (let el of formElements) {
            if (!el.name) continue;

            // Skip fields belonging to a currently-hidden dynamic group (e.g. the
            // brightness-type field not selected, or the calc-mode not selected).
            if (el.closest('.dynamic-group[hidden]')) continue;

            const value = this._parseValue(el);
            if (value === null || value === '') continue;

            this._setNestedValue(payload, el.name.split('.'), value);
        }

        // Convert the local wall-clock datetime-local input to standard UTC ISO 8601.
        if (payload.environment && payload.environment.observing_time_utc) {
            const localTimeString = payload.environment.observing_time_utc;
            const dateObj = new Date(localTimeString);
            payload.environment.observing_time_utc = dateObj.toISOString();
        }

        return payload;
    }

    static _parseValue(el) {
        if (el.type === 'number') {
            return el.value === '' ? null : parseFloat(el.value);
        }
        return el.value;
    }

    static _setNestedValue(obj, pathArray, value) {
        let current = obj;
        for (let i = 0; i < pathArray.length - 1; i++) {
            const part = pathArray[i];
            if (!current[part]) current[part] = {};
            current = current[part];
        }
        current[pathArray[pathArray.length - 1]] = value;
    }
}

// ==========================================
// 3. API Client
// ==========================================
class CastorAPI {
    static async calculate(payload) {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Calculation failed');
        }
        return data;
    }
}

// ==========================================
// 4. Result Renderer
// ==========================================
class ResultRenderer {
    static render(data, isArrayMode) {
        document.getElementById('results-placeholder').hidden = true;
        document.getElementById('results-container').hidden = false;

        this._renderWarnings(data.flags.warnings, data.flags.is_saturated);
        document.getElementById('plot-area').hidden = !isArrayMode;

        document.getElementById('res-source-rate').textContent = this._fmt(data.budget.source_count_rate, 3);
        document.getElementById('res-sky-rate').textContent = this._fmt(data.budget.sky_count_rate, 4);
        document.getElementById('res-peak-rate').textContent = this._fmt(data.budget.peak_pixel_rate, 4);
        document.getElementById('res-single-snr').textContent = this._fmt(data.core.single_snr, 2);

        document.getElementById('res-total-fwhm').textContent = this._fmt(data.diagnostics.total_fwhm, 2);
        document.getElementById('res-pixel-scale').textContent = this._fmt(data.diagnostics.pixel_scale, 3);
        document.getElementById('res-eff-area').textContent = this._fmt(data.diagnostics.effective_area, 3);
        document.getElementById('res-throughput').textContent = this._fmt(data.diagnostics.total_throughput * 100, 1);
        document.getElementById('res-enclosed-flux').textContent = this._fmt(data.diagnostics.enclosed_flux_fraction * 100, 1);
        document.getElementById('res-num-pixels').textContent = this._fmt(data.diagnostics.num_pixels_aperture, 1);

        document.getElementById('res-sat-time').textContent = this._fmt(data.core.saturation_time_limit, 2);

        this._renderPrimary(data);
    }

    static _fmt(v, digits) {
        if (v === null || v === undefined || isNaN(v)) return '--';
        return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 3 : digits });
    }

    static _renderPrimary(data) {
        const labelEl = document.getElementById('primary-result-label');
        const valueEl = document.getElementById('primary-result-value');
        const descEl = document.getElementById('primary-result-desc');

        if (data.core.required_exposures === null || data.core.required_exposures === undefined) {
            labelEl.textContent = 'Signal-to-Noise Ratio (SNR)';
            valueEl.textContent = this._fmt(data.core.total_snr, 2);
            descEl.textContent = 'Calculated from the given number of exposures.';
        } else {
            labelEl.textContent = 'Required Exposures';
            valueEl.textContent = `${data.core.required_exposures} frames`;
            descEl.textContent = `Total SNR achieved: ${this._fmt(data.core.total_snr, 2)}`;
        }
    }

    static _renderWarnings(warnings, isSaturated) {
        const alertContainer = document.getElementById('alert-container');
        const warningList = document.getElementById('warning-list');
        warningList.innerHTML = '';

        let hasWarning = false;

        if (isSaturated) {
            hasWarning = true;
            const li = document.createElement('li');
            li.textContent = 'Warning: single exposure time exceeds the saturation limit (full well capacity reached).';
            warningList.appendChild(li);
        }

        if (warnings && warnings.length > 0) {
            hasWarning = true;
            warnings.forEach(w => {
                const li = document.createElement('li');
                li.textContent = w;
                warningList.appendChild(li);
            });
        }

        alertContainer.hidden = !hasWarning;
    }
}

// ==========================================
// 5. Stepper Controller
// ==========================================
class StepperController {
    constructor() {
        this.currentStep = 0;
        this.steps = Array.from(document.querySelectorAll('.step-content'));
        this.indicators = document.querySelectorAll('.stepper-indicator .step');

        this.btnNext = document.getElementById('btn-next');
        this.btnPrev = document.getElementById('btn-prev');
        this.btnSubmit = document.getElementById('btn-submit');

        this.bindEvents();
        this.updateUI();
    }

    bindEvents() {
        this.btnNext.addEventListener('click', () => this.nextStep());
        this.btnPrev.addEventListener('click', () => this.prevStep());
    }

    nextStep() {
        const currentSection = this.steps[this.currentStep];
        const inputs = currentSection.querySelectorAll('input, select');

        let isValid = true;
        for (let input of inputs) {
            if (input.closest('.dynamic-group[hidden]') || input.closest('.hidden-detail')) {
                continue;
            }
            if (!input.checkValidity()) {
                input.reportValidity();
                isValid = false;
                break;
            }
        }

        if (!isValid) return;

        if (this.currentStep < this.steps.length - 1) {
            this.currentStep++;
            this.updateUI();
        }
    }

    prevStep() {
        if (this.currentStep > 0) {
            this.currentStep--;
            this.updateUI();
        }
    }

    updateUI() {
        this.steps.forEach((step, index) => {
            step.hidden = (index !== this.currentStep);
        });

        this.indicators.forEach((ind, index) => {
            if (index === this.currentStep) {
                ind.classList.add('active');
                ind.classList.remove('completed');
            } else if (index < this.currentStep) {
                ind.classList.remove('active');
                ind.classList.add('completed');
            } else {
                ind.classList.remove('active', 'completed');
            }
        });

        this.btnPrev.hidden = (this.currentStep === 0);

        if (this.currentStep === this.steps.length - 1) {
            this.btnNext.hidden = true;
            this.btnSubmit.hidden = false;
        } else {
            this.btnNext.hidden = false;
            this.btnSubmit.hidden = true;
        }
    }
}

// ==========================================
// Main entry point
// ==========================================
function showFormError(message) {
    const box = document.getElementById('etc-form-error');
    box.textContent = message;
    box.hidden = false;
}
function clearFormError() {
    const box = document.getElementById('etc-form-error');
    box.hidden = true;
    box.textContent = '';
}

document.addEventListener('DOMContentLoaded', async () => {
    const ui = new UIController();
    await ui.loadPresets();

    const stepper = new StepperController();

    document.getElementById('castor-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        clearFormError();
        ui.setLoadingState(true);

        try {
            const payload = PayloadBuilder.build();
            const resultData = await CastorAPI.calculate(payload);
            const isArrayMode = document.getElementById('toggle-array-mode').checked;
            ResultRenderer.render(resultData, isArrayMode);
        } catch (error) {
            showFormError(error.message);
        } finally {
            ui.setLoadingState(false);
        }
    });
});
