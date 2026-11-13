"""Checks a spectrum upload (object page › Spectroscopy › Upload) before it is stored.

The browser runs the same rules (object_detail.js › checkSpectrumPoints) so the user sees
the problems before sending; this is the server-side guard for anything that bypasses it.

``check_spectrum_points`` returns (points, errors, warnings):
  errors   — the upload is refused (HTTP 400) and the messages are shown to the user;
  warnings — stored anyway (e.g. the points were not sorted: they are sorted here).
Wavelengths are stored in Ångström, so ranges that look like nm or µm are refused.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

MIN_POINTS = 10
MAX_POINTS = 200_000
# Ångström. 1000 Å (far-UV) to 30 µm (mid-IR) covers every spectrograph Kinder takes data from.
MIN_WAVELENGTH = 1000.0
MAX_WAVELENGTH = 300_000.0
# Observation dates before this, or more than a day in the future, are typos.
EARLIEST_OBSERVATION = datetime(1950, 1, 1, tzinfo=timezone.utc)


def _as_number(value):
    """Finite float, or None (bools and strings are not numbers here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def check_spectrum_points(wavelength, intensity):
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(wavelength, list) or not isinstance(intensity, list):
        return [], ['wavelength and intensity must both be lists of numbers.'], warnings
    if len(wavelength) != len(intensity):
        return [], [f'wavelength has {len(wavelength)} values but intensity has {len(intensity)}; '
                    'every point needs both.'], warnings
    if len(wavelength) > MAX_POINTS:
        return [], [f'{len(wavelength):,} points is more than the {MAX_POINTS:,} allowed; '
                    'bin the spectrum first.'], warnings

    points, bad = [], []
    for i, (wl, fl) in enumerate(zip(wavelength, intensity), start=1):
        wl, fl = _as_number(wl), _as_number(fl)
        if wl is None or fl is None:
            bad.append(i)
            continue
        points.append((wl, fl))
    if bad:
        shown = ', '.join(map(str, bad[:5])) + (f' and {len(bad) - 5} more' if len(bad) > 5 else '')
        errors.append(f'{len(bad)} point(s) are not finite numbers (point {shown}).')

    if len(points) < MIN_POINTS:
        errors.append(f'Only {len(points)} valid point(s); a spectrum needs at least {MIN_POINTS}.')
        return points, errors, warnings

    wls = [p[0] for p in points]
    lo, hi = min(wls), max(wls)
    if lo <= 0:
        errors.append('Wavelengths must be positive.')
    elif hi < 50:
        errors.append(f'Wavelengths {lo:g}–{hi:g} look like micrometres; Kinder stores Ångström '
                      '(multiply by 10000).')
    elif hi < MIN_WAVELENGTH:
        errors.append(f'Wavelengths {lo:g}–{hi:g} look like nanometres; Kinder stores Ångström '
                      '(multiply by 10).')
    elif lo < MIN_WAVELENGTH or hi > MAX_WAVELENGTH:
        errors.append(f'Wavelengths {lo:g}–{hi:g} Å are outside {MIN_WAVELENGTH:g}–{MAX_WAVELENGTH:g} Å. '
                      'Is the first column the wavelength in Ångström?')

    fluxes = [p[1] for p in points]
    if max(fluxes) == min(fluxes):
        errors.append('Every intensity is the same value; is the second column the flux?')

    if any(b[0] < a[0] for a, b in zip(points, points[1:])):
        warnings.append('Wavelengths were not in increasing order; they are sorted on upload.')
        points.sort(key=lambda p: p[0])
    dupes = sum(1 for a, b in zip(points, points[1:]) if a[0] == b[0])
    if dupes:
        warnings.append(f'{dupes} repeated wavelength value(s).')

    return points, errors, warnings


def check_observation_mjd(mjd, now: datetime | None = None) -> str | None:
    """Error message when the resolved observation epoch (MJD) is not believable, else None."""
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=float(mjd))
    except (TypeError, ValueError, OverflowError):
        return 'The observation date could not be read.'
    if dt < EARLIEST_OBSERVATION:
        return f'Observation date {dt:%Y-%m-%d} is before 1950; check the date.'
    if dt > now + timedelta(days=1):
        return f'Observation date {dt:%Y-%m-%d} is in the future.'
    return None
