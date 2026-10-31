"""Astronomy tools — the Exposure Time Calculator's Simple mode: pick hardware, a target and an SNR,
get back how long each frame should be and how many to take.

CASTOR answers "how many frames of t seconds reach this SNR" (solve_time), but t is an input:
someone who only wants an observing plan has no basis for choosing it. This module chooses it.
Everything physical stays CASTOR's — the request is assembled exactly the way its own CLI
assembles one (castorCLI.presets.resolve + castorCLI.main.ASSUMPTIONS), and every row shown
comes from castor.calculator.run_calculation. The only arithmetic done here is finding the
single-frame time that just reaches the target, from the noise budget CASTOR reports, and that
answer is then checked by running CASTOR on it like every other row.
"""
import copy
import math

# Frame lengths a plan is written in: the round numbers an observer would type into the
# telescope's script, so every suggestion is one of them. Not a physical scale.
PREFERRED_EXPOSURES = (15, 30, 45, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600)

# Only for targets that saturate a 15 s frame: then the longest of these that does not.
SHORT_EXPOSURES = (1, 2, 3, 5, 10)

# Every frame also costs a readout and a save, which CASTOR does not model (its total is
# integration time only). The exact figure depends on the camera's readout mode; this is an
# assumption, not a measurement. What matters is that it is not zero: ranking plans by time
# spent rather than time integrating is what makes one 30 s frame beat four 8 s ones.
READOUT_OVERHEAD_S = 10

# A plan longer than this on one target is reported, not hidden: the numbers are right, the
# plan is not one anybody will run.
IMPRACTICAL_TOTAL_S = 4 * 3600

# Probe frame for the noise budget. Its length does not matter (every term is either constant
# or linear in time per frame, plus the flatness term in t^2), only that it is a valid request.
_PROBE_EXP_S = 60.0


class QuickInputError(ValueError):
    """A Simple-mode input that cannot become a request; its message is shown to the user."""


def _set_default(data, dotted, value):
    node = data
    parts = dotted.split('.')
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node.setdefault(parts[-1], value)


def parse_coordinates(ra_text, dec_text):
    """RA/Dec as typed: degrees, or sexagesimal (RA in hours) with ':' or spaces."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    ra_text = str(ra_text or '').strip()
    dec_text = str(dec_text or '').strip()
    if not ra_text or not dec_text:
        raise QuickInputError('Enter the target RA and Dec.')
    sexagesimal = any(c in ra_text for c in ': hms') or any(c in dec_text for c in ': dms')
    try:
        coord = SkyCoord(ra_text, dec_text, unit=(u.hourangle, u.deg) if sexagesimal else (u.deg, u.deg))
    except Exception:
        raise QuickInputError('Could not read the coordinates. Use degrees (e.g. 150.12, 2.21) '
                              'or hh:mm:ss / dd:mm:ss.')
    return float(coord.ra.deg), float(coord.dec.deg)


def _single_frame_time(noise, probe_exp, target_snr):
    """Exposure time at which ONE frame reaches target_snr, or None if no length does.

    From CASTOR's own single-frame budget at the probe length: signal a·t, a per-frame
    variance b·t + r (source, sky and dark grow with t; readout does not) and the flatness
    term c·t². Solving (a·t)² = T²(b·t + r + c·t²) for t.
    """
    t0 = probe_exp
    a = noise['signal'] / t0
    b = (noise['source_variance'] + noise['sky_variance'] + noise['dark_variance']) / t0
    r = noise['readout_variance']
    c = noise['flatness_variance'] / t0 ** 2
    t2 = target_snr ** 2
    qa = a * a - t2 * c
    if qa <= 0:
        return None
    return (t2 * b + math.sqrt((t2 * b) ** 2 + 4 * qa * t2 * r)) / (2 * qa)


def compute_plan(catalogue, *, site, telescope, camera, optic_filter, ra, dec, mag,
                 target_snr, observing_time_utc, fwhm):
    """Run CASTOR over the frame lengths that make sense and pick one. Returns a JSON-ready dict."""
    from castor import schema
    from castor.calculator import run_calculation
    from castorCLI.main import ASSUMPTIONS
    from castorCLI import presets

    if not (target_snr and target_snr > 0):
        raise QuickInputError('Target SNR must be a positive number.')
    if not (fwhm and fwhm > 0):
        raise QuickInputError('Seeing must be a positive number of arcseconds.')

    try:
        fragment = catalogue.resolve(site, telescope, camera, optic_filter)
        labels = catalogue.labels(site, telescope, camera, optic_filter)
        caveats = list(catalogue.caveats(site, telescope, camera, optic_filter).values())
    except presets.PresetError as exc:
        raise QuickInputError(str(exc))

    base = copy.deepcopy(fragment)
    base.setdefault('target', {}).update({'ra': ra, 'dec': dec})
    base['target'].setdefault('brightness', {})['target_mag'] = mag
    base.setdefault('environment', {}).update({'total_fwhm': fwhm, 'observing_time_utc': observing_time_utc})
    for path, value, _why in ASSUMPTIONS:
        _set_default(base, path, value)

    def run(options):
        data = copy.deepcopy(base)
        data['options'] = {**data.get('options', {}), **options}
        return run_calculation(schema.ObservationRequest.model_validate(data))

    probe = run({'type': 'solve_snr', 'num_exposures': 1, 'single_exp_time': _PROBE_EXP_S})
    eph = probe.ephemeris
    t_sat = float(probe.core.saturation_time_limit)

    result = {
        'labels': labels,
        'caveats': caveats,
        'conditions': {
            'target_elevation_deg': eph.target_elevation_deg,
            'airmass': probe.diagnostics.airmass,
            'moon_elevation_deg': eph.moon_elevation_deg,
            'moon_illumination': (1 + math.cos(math.radians(eph.moon_phase_angle_deg))) / 2,
            'moon_separation_deg': eph.moon_separation_deg,
            'fwhm_arcsec': fwhm,
            'saturation_time_s': t_sat,
            'sky_mag_arcsec2': probe.diagnostics.sky_surface_brightness,
        },
        'target_snr': target_snr,
        'readout_overhead_s': READOUT_OVERHEAD_S,
        'single_frame_time_s': None,
        'recommended': None,
        'rows': [],
        'snr_ceiling': probe.core.snr_ceiling,
        'warnings': [w for w in probe.flags.warnings],
    }

    if eph.target_elevation_deg <= 0:
        result['status'] = 'below_horizon'
        return result

    usable = ([t for t in PREFERRED_EXPOSURES if t < t_sat]
              or [t for t in SHORT_EXPOSURES if t < t_sat][-1:])
    if not usable:
        result['status'] = 'saturated'
        return result

    t_one = _single_frame_time(probe.noise.single.model_dump(), _PROBE_EXP_S, target_snr)
    result['single_frame_time_s'] = t_one

    rows = []
    for t in usable:
        resp = run({'type': 'solve_time', 'target_snr': target_snr, 'single_exp_time': float(t)})
        n = resp.core.required_exposures
        if n is None:   # above the background-flatness ceiling: no count of these frames reaches it
            continue
        rows.append({'exp_s': t, 'frames': int(n), 'total_s': t * int(n),
                     'elapsed_s': (t + READOUT_OVERHEAD_S) * int(n), 'snr': resp.core.total_snr})
        if n == 1:      # every longer frame is also one frame, just longer
            break
    if not rows:
        result['status'] = 'unreachable'
        return result

    # Least time at the telescope, and on a tie the fewer frames.
    recommended = min(rows, key=lambda row: (row['elapsed_s'], row['frames']))
    recommended['recommended'] = True
    result['rows'] = rows
    result['recommended'] = recommended
    result['status'] = 'impractical' if recommended['total_s'] > IMPRACTICAL_TOTAL_S else 'ok'
    return result
