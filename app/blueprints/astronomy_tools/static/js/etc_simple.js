/* ============================================================================
   CASTOR ETC — Simple mode (etc_simple_body.html), and the Simple / Advanced switch.

   Written for Kinder and moved here so both hosts serve one copy. The Advanced
   mode is etc.js; this file never reaches into it. Simple mode asks for hardware,
   a target and one of Advanced mode's two goals, posts them to the quick route
   (castorCLI/plan.py), and shows either the frame length and frame count it
   recommends for an SNR (solve_time), or the SNR given frames reach (solve_snr),
   each with the alternatives beside it.

   Hardware lists come from the same presets route the Advanced form reads, so
   both modes always offer the same telescopes, cameras and filters.

   The localStorage keys keep their Kinder names so a viewer's remembered mode
   and form survive Kinder switching to this copy.
   ============================================================================ */
(function () {
    'use strict';

    var MODE_KEY = 'kinder.etc.mode';
    var FORM_KEY = 'kinder.etc.simple';

    function el(id) { return document.getElementById(id); }

    // Per-viewer conveniences only; private windows and blocked storage just forget.
    function store(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ } }
    function recall(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; } }

    // ── Fit the viewport ────────────────────────────────────────────────────
    // Both modes size their panels to the height left under the mode bar (--etc-top,
    // read by etc_simple.css and the page's CASTOR overrides). The bar wraps on narrow
    // windows, so where the panels start is measured rather than assumed.
    var page = document.querySelector('.etc-page');

    function measureTop() {
        var panel = document.querySelector('[data-etc-mode-panel]:not([hidden])');
        if (!page || !panel) { return; }
        page.style.setProperty('--etc-top', Math.round(panel.getBoundingClientRect().top + window.scrollY) + 'px');
    }
    window.addEventListener('resize', measureTop);
    window.addEventListener('load', measureTop);

    // ── Mode switch ─────────────────────────────────────────────────────────
    var tabs = document.querySelectorAll('[data-etc-mode]');

    function setMode(mode) {
        tabs.forEach(function (tab) {
            var on = tab.getAttribute('data-etc-mode') === mode;
            tab.classList.toggle('is-on', on);
            tab.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('[data-etc-mode-panel]').forEach(function (panel) {
            panel.hidden = panel.getAttribute('data-etc-mode-panel') !== mode;
        });
        document.querySelectorAll('[data-etc-mode-hint]').forEach(function (hint) {
            hint.hidden = hint.getAttribute('data-etc-mode-hint') !== mode;
        });
        measureTop();
        // Plotly sizes its chart from the container, which had no width while hidden.
        if (mode === 'advanced') { window.dispatchEvent(new Event('resize')); }
        store(MODE_KEY, mode);
    }

    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () { setMode(tab.getAttribute('data-etc-mode')); });
    });
    var urlMode = new URLSearchParams(location.search).get('mode');
    setMode(urlMode === 'advanced' || urlMode === 'simple' ? urlMode : (recall(MODE_KEY) === 'advanced' ? 'advanced' : 'simple'));

    // ── Simple form ─────────────────────────────────────────────────────────
    var form = el('etc-simple-form');
    var result = el('qs-result');
    var body = el('qs-body');
    var goBtn = el('qs-go');
    var CONFIG = window.CASTOR_ETC_CONFIG || {};
    // quickUrl is the fourth key of the host contract; KINDER_ETC_QUICK_URL is what
    // Kinder's template set before this file moved here, still honoured so that
    // template keeps working unchanged.
    var QUICK_URL = CONFIG.quickUrl || window.KINDER_ETC_QUICK_URL;
    var profiles = {};

    function entries(obj) {
        return Object.keys(obj || {}).map(function (key) { return { key: key, name: (obj[key] && obj[key].name) || key }; });
    }

    function fill(select, list, wanted) {
        select.innerHTML = '';
        list.forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = item.key;
            opt.textContent = item.name;
            select.appendChild(opt);
        });
        if (wanted && list.some(function (item) { return item.key === wanted; })) { select.value = wanted; }
    }

    /* The presets do not say which camera sits on which telescope. Camera keys that
       belong to one telescope are prefixed with it (SLT_DU934P), so: a camera named
       after this telescope, else the first camera not named after another one. */
    function defaultCamera(profile, telescopeKey) {
        var cams = Object.keys(profile.cameras || {});
        var tels = Object.keys(profile.telescopes || {});
        var own = cams.filter(function (c) { return c.indexOf(telescopeKey + '_') === 0; });
        if (own.length) { return own[0]; }
        var free = cams.filter(function (c) {
            return !tels.some(function (t) { return t !== telescopeKey && c.indexOf(t + '_') === 0; });
        });
        return free[0] || cams[0];
    }

    function currentProfile() { return profiles[el('qs-site').value] || {}; }

    function syncHardware(saved) {
        var profile = currentProfile();
        fill(el('qs-telescope'), entries(profile.telescopes), saved && saved.telescope);
        fill(el('qs-filter'), entries(profile.filters), saved && saved.filter);
        fill(el('qs-camera'), entries(profile.cameras), (saved && saved.camera) || defaultCamera(profile, el('qs-telescope').value));
        syncSiteNotes();
    }

    function syncSiteNotes() {
        var profile = currentProfile();
        var caveat = el('qs-caveat');
        caveat.textContent = profile.caveat || '';
        caveat.hidden = !profile.caveat;
        var median = profile.median_seeing_fwhm;
        el('qs-fwhm-note').textContent = median
            ? 'Site median ' + median + '″ — use tonight’s seeing if you know it.'
            : 'Typical seeing for this site is not recorded; enter your best estimate.';
        if (!el('qs-fwhm').value) { el('qs-fwhm').value = median || 1.5; }
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function toLocalInput(d) {
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    // Daytime opens on tonight at 22:00; at night, on now.
    function defaultTime() {
        var now = new Date();
        if (now.getHours() >= 6 && now.getHours() < 18) {
            now.setHours(22, 0, 0, 0);
        } else {
            now.setSeconds(0, 0);
        }
        return toLocalInput(now);
    }

    /* The time is read in this browser's time zone, which is not necessarily the
       observatory's — so the label names the zone and the UTC it becomes is shown. */
    function syncTimeNote() {
        var when = new Date(el('qs-time').value);
        var valid = !isNaN(when.getTime());
        el('qs-time-utc').textContent = valid ? '= ' + when.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '';
        try {
            // The offset of the chosen date, not today's: daylight saving may differ.
            var offset = -(valid ? when : new Date()).getTimezoneOffset() / 60;
            el('qs-tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone +
                ', UTC' + (offset >= 0 ? '+' : '') + offset;
        } catch (e) { /* keep "your local time" */ }
    }
    el('qs-time').addEventListener('input', syncTimeNote);

    // ── Calculation Goal ────────────────────────────────────────────────────
    // Advanced mode's choice and names: solve_snr takes the frames, solve_time the SNR.
    function currentGoal() {
        var on = form.querySelector('input[name="goal"]:checked');
        return on ? on.value : 'solve_time';
    }
    function setGoal(goal) {
        form.querySelectorAll('input[name="goal"]').forEach(function (radio) { radio.checked = radio.value === goal; });
        syncGoal();
    }
    function syncGoal() {
        var goal = currentGoal();
        form.querySelectorAll('[data-qs-goal]').forEach(function (group) {
            group.hidden = group.getAttribute('data-qs-goal') !== goal;
        });
    }
    form.querySelectorAll('input[name="goal"]').forEach(function (radio) { radio.addEventListener('change', syncGoal); });

    function formValues() {
        return {
            site: el('qs-site').value, telescope: el('qs-telescope').value,
            camera: el('qs-camera').value, filter: el('qs-filter').value,
            ra: el('qs-ra').value.trim(), dec: el('qs-dec').value.trim(),
            mag: el('qs-mag').value, goal: currentGoal(), target_snr: el('qs-snr').value,
            single_exp_time: el('qs-exp').value, num_exposures: el('qs-num').value,
            time: el('qs-time').value, fwhm: el('qs-fwhm').value
        };
    }

    // ── Rendering ───────────────────────────────────────────────────────────
    function esc(text) {
        return String(text).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function fmtSeconds(s) {
        return (s < 10 && s % 1 ? s.toFixed(1) : Math.round(s)) + ' s';
    }
    function fmtDuration(s) {
        s = Math.round(s);
        if (s < 60) { return s + ' s'; }
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        if (h) { return h + ' h' + (m ? ' ' + m + ' min' : ''); }
        return m + ' min' + (sec ? ' ' + sec + ' s' : '');
    }
    function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

    function kpi(label, value, note, alert) {
        return '<div class="kw-kpi' + (alert ? ' is-alert' : '') + '"><span class="kw-kpi-label">' + esc(label) +
            '</span><b>' + esc(value) + '</b><small>' + esc(note) + '</small></div>';
    }

    function conditionsHtml(data) {
        var c = data.conditions;
        var alt = c.target_elevation_deg;
        var moonUp = c.moon_elevation_deg > 0;
        var lit = Math.round(c.moon_illumination * 100);
        return '<div class="kw-kpis">' +
            kpi('Target altitude', Math.round(alt) + '°', alt > 0 ? 'airmass ' + c.airmass.toFixed(2) : 'below the horizon', alt < 30) +
            kpi('Moon', lit + '% lit', moonUp ? Math.round(c.moon_separation_deg) + '° from target' : 'below the horizon', moonUp && lit > 50 && c.moon_separation_deg < 45) +
            kpi('Sky', c.sky_mag_arcsec2.toFixed(2), 'mag/arcsec² with moon') +
            kpi('Saturates after', c.saturation_time_s >= 3600 ? '> 1 h' : fmtSeconds(c.saturation_time_s), 'per frame', c.saturation_time_s < 10) +
            '</div>';
    }

    function tableHtml(data) {
        var rows = data.rows;
        var fastest = Math.min.apply(null, rows.map(function (r) { return r.elapsed_s; }));
        // The rows a person might actually pick; the rest (short frames that spend most of
        // the time reading out) stay one click away.
        var shown = rows.filter(function (r) { return r.recommended || r.elapsed_s <= 2 * fastest; });
        function rowHtml(r) {
            return '<tr class="' + (r.recommended ? 'is-rec' : '') + '">' +
                '<td>' + fmtSeconds(r.exp_s) + (r.recommended ? ' <span class="kw-chip kw-chip-gold">Suggested</span>' : '') + '</td>' +
                '<td>' + r.frames + '</td>' +
                '<td>' + fmtDuration(r.total_s) + '</td>' +
                '<td>' + r.snr.toFixed(1) + '</td></tr>';
        }
        var hidden = rows.length - shown.length;
        return '<h3 class="etc-simple-section">Other ways to reach SNR ' + esc(+data.target_snr) + '</h3>' +
            '<div class="kw-table-wrap"><table class="kw-table etc-simple-table">' +
            '<thead><tr><th>Each frame</th><th>Frames</th><th>Total</th><th>SNR</th></tr></thead>' +
            '<tbody>' + shown.map(rowHtml).join('') + '</tbody>' +
            (hidden ? '<tbody hidden id="qs-more-rows">' + rows.filter(function (r) { return shown.indexOf(r) < 0; }).map(rowHtml).join('') + '</tbody>' : '') +
            '</table></div>' +
            (hidden ? '<button type="button" class="kw-btn kw-btn-sm etc-simple-more" id="qs-more">Show ' + plural(hidden, 'slower option') + '</button>' : '');
    }

    /* solve_snr: the same total integration cut into other frame counts. Fewer, longer
       frames pay less read noise; more, shorter ones survive a cosmic ray or a satellite. */
    function splitTableHtml(data) {
        function rowHtml(r) {
            return '<tr class="' + (r.chosen ? 'is-rec' : '') + '">' +
                '<td>' + fmtSeconds(r.exp_s) +
                (r.chosen ? ' <span class="kw-chip kw-chip-gold">Yours</span>' : '') +
                (r.saturates ? ' <span class="kw-chip">Saturates</span>' : '') + '</td>' +
                '<td>' + r.frames + '</td>' +
                '<td>' + fmtDuration(r.elapsed_s) + '</td>' +
                '<td>' + r.snr.toFixed(1) + '</td></tr>';
        }
        return '<h3 class="etc-simple-section">The same ' + esc(fmtDuration(data.chosen.total_s)) + ', split differently</h3>' +
            '<div class="kw-table-wrap"><table class="kw-table etc-simple-table">' +
            '<thead><tr><th>Each frame</th><th>Frames</th><th>With readout</th><th>SNR</th></tr></thead>' +
            '<tbody>' + data.rows.map(rowHtml).join('') + '</tbody></table></div>';
    }

    function hero(eyebrow, planHtml, sub, why, problem) {
        return '<div class="etc-simple-hero"><div class="kw-eyebrow">' + esc(eyebrow) + '</div>' +
            '<div class="etc-simple-plan' + (problem ? ' is-problem' : '') + '">' + planHtml + '</div>' +
            (sub ? '<div class="etc-simple-sub">' + sub + '</div>' : '') +
            (why ? '<p class="etc-simple-why">' + why + '</p>' : '') + '</div>';
    }

    function render(data) {
        var alerts = (data.warnings || []).slice();
        var html = '';
        var c = data.conditions;
        var labels = data.labels || {};
        var setup = [labels.telescope, labels.camera, labels.optic_filter].filter(Boolean).join(' · ');

        if (data.goal === 'solve_snr' && data.status !== 'below_horizon') {
            var mine = data.chosen;
            var ceiling = data.snr_ceiling;
            html += hero('Expected SNR', esc(mine.snr.toFixed(1)),
                esc(fmtSeconds(mine.exp_s)) + ' × ' + esc(plural(mine.frames, 'frame')) + ' · ' +
                    fmtDuration(mine.total_s) + ' on target (about ' + fmtDuration(mine.elapsed_s) + ' with readout)' +
                    (mine.frames > 1 ? ' · SNR ' + mine.single_snr.toFixed(1) + ' per frame' : ''),
                ceiling && mine.snr > 0.8 * ceiling
                    ? 'Close to the ' + ceiling.toFixed(1) + ' that flat-field residuals allow: more frames will barely raise it.'
                    : '',
                false);
            if (data.status === 'saturated') {
                alerts.unshift('Each frame saturates after ' + fmtSeconds(c.saturation_time_s) + ', so a ' + fmtSeconds(mine.exp_s) +
                    ' frame overfills the brightest pixel and this SNR overstates what you would measure. Use shorter frames.');
            }
        } else if (data.status === 'below_horizon') {
            alerts = [];    // airmass caveats about a target nobody can point at
            html += hero('Not observable', 'The target is below the horizon',
                'Altitude ' + Math.round(c.target_elevation_deg) + '° at this time.',
                'Try another time, or check the coordinates.', true);
        } else if (data.status === 'saturated') {
            html += hero('Too bright', 'Saturates in under 1 s',
                'The brightest pixel fills in ' + c.saturation_time_s.toFixed(2) + ' s with ' + esc(setup) + '.',
                'Use a smaller telescope, a narrower filter, or defocus. The Advanced mode accepts sub-second frames.', true);
        } else if (data.status === 'unreachable') {
            html += hero('Not reachable', 'SNR ' + esc(+data.target_snr) + ' can’t be reached',
                data.snr_ceiling ? 'Flat-field residuals cap the stacked SNR at ' + data.snr_ceiling.toFixed(1) + ', however many frames you take.' : '',
                'Lower the target SNR, or pick a setup with less background.', true);
        } else {
            var rec = data.recommended;
            html += hero('Suggested exposure',
                esc(fmtSeconds(rec.exp_s)) + '<span class="etc-simple-x">×</span>' + esc(plural(rec.frames, 'frame')),
                fmtDuration(rec.total_s) + ' on target (about ' + fmtDuration(rec.elapsed_s) + ' with readout) · reaches SNR ' + rec.snr.toFixed(1),
                rec.frames === 1
                    ? 'One frame of ' + fmtSeconds(rec.exp_s) + ' already reaches the target (exactly ' + fmtSeconds(data.single_frame_time_s) + ' would). Take a few more frames if you want to reject cosmic rays.'
                    : 'The least time at the telescope, counting about ' + data.readout_overhead_s + ' s of readout per frame — so as few frames as that allows. Frames are 15, 30 or 45 s or whole minutes, and never longer than the saturation limit.',
                false);
            if (data.status === 'impractical') {
                alerts.unshift('This needs ' + fmtDuration(rec.total_s) + ' on one target. Consider a lower SNR or a larger telescope.');
            }
        }

        (data.caveats || []).forEach(function (text) { alerts.push(text); });
        if (alerts.length) {
            html += '<div class="etc-simple-alerts">' + alerts.map(function (a) {
                return '<div class="etc-simple-alert">' + esc(a) + '</div>';
            }).join('') + '</div>';
        }
        html += conditionsHtml(data);
        // Wide panels lay the plan and the other options side by side (etc_simple.css).
        var detail = data.rows && data.rows.length;
        html = '<div class="etc-simple-main">' + html + '</div><div class="etc-simple-detail">' +
            (detail ? (data.goal === 'solve_snr' ? splitTableHtml(data) : tableHtml(data)) : '');
        html += '<p class="etc-simple-foot">' + esc(setup) + ', seeing ' + c.fwhm_arcsec + '″. Total is integration only; ' +
            (data.goal === 'solve_snr' ? 'the time with readout assumes' : 'the suggestion assumes') +
            ' about ' + data.readout_overhead_s + ' s of readout per frame (not measured), and slewing is extra. ' +
            'Switch to <b>Advanced</b> for the full noise budget and how it changes over the night.</p></div>';

        body.innerHTML = html;
        body.classList.toggle('has-detail', !!detail);
        result.scrollTop = 0;
        var more = el('qs-more');
        if (more) {
            more.addEventListener('click', function () {
                el('qs-more-rows').hidden = false;
                more.remove();
            });
        }
    }

    function renderError(message) {
        body.classList.remove('has-detail');
        body.innerHTML = '<div class="etc-simple-alerts"><div class="etc-simple-alert is-error">' + esc(message) + '</div></div>';
    }

    function setState(state) {
        result.classList.remove('is-idle', 'is-busy', 'is-stale');
        if (state) { result.classList.add(state); }
    }

    // ── Run ─────────────────────────────────────────────────────────────────
    var inflight = null;

    form.addEventListener('submit', function (event) {
        event.preventDefault();
        var v = formValues();
        store(FORM_KEY, v);
        if (!v.ra || !v.dec || v.mag === '') {
            setState('');
            renderError('Enter the target’s RA, Dec and magnitude.');
            return;
        }
        if (v.goal === 'solve_snr' && (v.single_exp_time === '' || v.num_exposures === '')) {
            setState('');
            renderError('Enter the exposure time and the number of exposures.');
            return;
        }
        var when = v.time ? new Date(v.time) : new Date();
        if (isNaN(when.getTime())) { when = new Date(); }

        if (inflight) { inflight.abort(); }
        inflight = new AbortController();
        setState('is-busy');
        el('qs-empty-text').textContent = 'Calculating…';
        goBtn.disabled = true;

        fetch(QUICK_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: inflight.signal,
            body: JSON.stringify(Object.assign({
                goal: v.goal,
                site: v.site, telescope: v.telescope, camera: v.camera, filter: v.filter,
                ra: v.ra, dec: v.dec, mag: parseFloat(v.mag),
                fwhm: parseFloat(v.fwhm), observing_time_utc: when.toISOString().replace(/\.\d{3}Z$/, 'Z')
            }, v.goal === 'solve_snr'
                ? { single_exp_time: parseFloat(v.single_exp_time), num_exposures: parseFloat(v.num_exposures) }
                : { target_snr: parseFloat(v.target_snr) }))
        }).then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) { throw new Error(data.error || ('HTTP ' + response.status)); }
                return data;
            });
        }).then(function (data) {
            setState('');
            render(data);
        }).catch(function (err) {
            if (err.name === 'AbortError') { return; }
            setState('');
            renderError(err.message);
        }).then(function () {
            goBtn.disabled = false;
            // One column (phones): the answer is below the form, out of sight of the
            // button. Scrolled once it is drawn, when the page is tall enough to reach it.
            if (window.matchMedia('(max-width: 960px)').matches) {
                result.scrollIntoView({ block: 'start' });
            }
        });
    });

    // An edit after a result fades it, so an old answer is never read as the new one.
    form.addEventListener('input', function () {
        if (!result.classList.contains('is-idle') && !result.classList.contains('is-busy')) { setState('is-stale'); }
    });

    el('qs-site').addEventListener('change', function () { el('qs-fwhm').value = ''; syncHardware(null); });
    el('qs-telescope').addEventListener('change', function () {
        el('qs-camera').value = defaultCamera(currentProfile(), el('qs-telescope').value);
    });

    // ── Boot ────────────────────────────────────────────────────────────────
    fetch(CONFIG.presetsUrl).then(function (r) { return r.json(); }).then(function (doc) {
        profiles = doc.profiles || {};
        var saved = recall(FORM_KEY) || {};
        // Only real sites can place a target in the sky; hardware families have no location.
        var sites = entries(profiles).filter(function (p) { return profiles[p.key].environment; });
        fill(el('qs-site'), sites, saved.site);
        if (saved.site === el('qs-site').value && saved.fwhm) { el('qs-fwhm').value = saved.fwhm; }
        syncHardware(saved.site === el('qs-site').value ? saved : null);
        ['ra', 'dec', 'mag'].forEach(function (k) { if (saved[k]) { el('qs-' + k).value = saved[k]; } });
        if (saved.target_snr) { el('qs-snr').value = saved.target_snr; }
        if (saved.single_exp_time) { el('qs-exp').value = saved.single_exp_time; }
        if (saved.num_exposures) { el('qs-num').value = saved.num_exposures; }
        setGoal(saved.goal === 'solve_snr' ? 'solve_snr' : 'solve_time');
        el('qs-time').value = defaultTime();
        syncTimeNote();
    }).catch(function () {
        renderError('Could not load the telescope list.');
        setState('');
    });
})();
