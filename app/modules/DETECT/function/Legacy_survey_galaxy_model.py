"""
galaxy_model.py — LS DR10 Tractor model-based host galaxy identifier.

Query the Legacy Survey DR10 Tractor catalog for extended sources near a
transient, compute ellipse parameters from the Tractor shape model, and
determine whether the transient falls within any galaxy's boundary.

Tractor shape convention:
  shape_r   : geometric-mean half-light radius (R_50) in arcsec
               shape_r = sqrt(a * b)  →  a = shape_r / sqrt(q)
  shape_e1/2: complex ellipticity  e = sqrt(e1²+e2²),  q = (1-e)/(1+e)
  pa        : East of North  = 0.5 * arctan2(e2, e1)  [degrees]

For COMP models:
  shapedev_r/e1/e2 : de Vaucouleurs component
  shapeexp_r/e1/e2 : exponential component
  fracdev          : DEV flux fraction (0–1)

R₂₅ / R₅₀ approximations by profile type (used as host boundary):
  DEV  → × 3.3   (de Vaucouleurs, Sersic n=4)
  EXP  → × 2.5   (exponential, Sersic n=1)
  REX  → × 2.5   (round exponential)
  SER  → × 2.8   (generic Sersic, intermediate)
  COMP → dominant component scale
"""
import io
import csv
import math
import requests
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from astropy.coordinates import SkyCoord
import astropy.units as u
from pathlib import Path
from typing import cast

from function.paths import PROJECT_ROOT, DATA_ROOT  # noqa: F401
GALAXY_MODEL_OUTPUT_DIR = DATA_ROOT / "DESI_img"

# ── LS DR10 endpoints ────────────────────────────────────────────────────────
# NOIRLAB Astro Data Lab TAP (LS DR10 Tractor catalog, public, no auth required)
_TAP_URL    = "https://datalab.noirlab.edu/tap/sync"
_CUTOUT_URL = "https://www.legacysurvey.org/viewer/cutout.jpg"


# ── R₂₅ scale factors per Tractor profile type ──────────────────────────────
# Tractor fixed profile Sersic indices
_FIXED_SERSIC_N = {
    'DEV':  4.0,   # de Vaucouleurs
    'EXP':  1.0,   # exponential
    'REX':  1.0,   # round exponential
    'COMP': 2.5,   # composite DEV+EXP, midpoint
}

def _sersic_r25_scale(n, mu_e=22.0, mu_lim=25.0):
    """
    R₂₅ / R₅₀ for a Sersic profile of index n.
    Derived from Sersic surface brightness profile:
        mu(r) = mu_e + (2.5 * b_n / ln10) * [(r/R_50)^(1/n) - 1]
    Solve for mu(R₂₅) = mu_lim.
    b_n is found via incomplete-gamma inverse: P(2n, b_n) = 0.5.
    Assumes typical effective surface brightness mu_e = 22 mag/arcsec².
    """
    from scipy.special import gammaincinv
    n = max(0.5, min(float(n), 10.0))
    try:
        b_n   = gammaincinv(2.0 * n, 0.5)
        delta = (mu_lim - mu_e) * math.log(10) / (2.5 * b_n)
        if delta <= -1.0:
            return 1.0
        return max(1.0, (1.0 + delta) ** n)
    except Exception:
        return 2.5

def _r25_scale(src_type):
    """Return R₂₅/R₅₀ for a given Tractor profile type using Sersic formula."""
    n = _FIXED_SERSIC_N.get(str(src_type).upper())
    return _sersic_r25_scale(n) if n is not None else _sersic_r25_scale(1.0)

def _r25_scale_src(src):
    """Return R₂₅/R₅₀ using actual Sersic n for SER type, else fixed-n formula."""
    t = str(src.get('type', '')).upper()
    n = src.get('sersic') if t == 'SER' else None
    if n is None or float(n) <= 0:
        n = _FIXED_SERSIC_N.get(t, 1.0)
    return _sersic_r25_scale(n)


# ── helpers ───────────────────────────────────────────────────────────────────
def _flux_to_mag(flux, zp=22.5):
    if not isinstance(flux, (int, float)) or flux <= 0:
        return None
    return round(zp - 2.5 * math.log10(flux), 3)


def _ellip_to_shape(shape_r, e1, e2):
    """
    Tractor shape_r, e1, e2  →  (a, b, pa_deg)
    a, b : semi-major / semi-minor in arcsec  (a = R_50 along major axis)
    pa   : position angle, degrees East of North
    """
    e = math.sqrt(e1 ** 2 + e2 ** 2)
    e = min(e, 0.99)
    q = max((1.0 - e) / (1.0 + e), 0.05)   # b/a axis ratio
    # shape_r = sqrt(a*b) = a*sqrt(q)
    a = shape_r / math.sqrt(q)
    b = a * q
    pa_deg = math.degrees(0.5 * math.atan2(e2, e1))
    return a, b, pa_deg


def _effective_shape(src):
    """Return (shape_r, e1, e2) for the source. Uses shape_r/e1/e2 directly."""
    return src['shape_r'], src['shape_e1'], src['shape_e2']


def _ellipse_frame(t_ra, t_dec, g_ra, g_dec, pa_deg):
    """Transient offset from the galaxy centre in the ellipse frame, arcsec.

    x runs along the semi-major axis, y along the semi-minor (PA East of North).
    """
    cosdec = math.cos(math.radians(g_dec))
    dra  = _wrap_dra(t_ra, g_ra) * 3600.0 * cosdec   # arcsec, +East
    ddec = (t_dec - g_dec) * 3600.0                  # arcsec, +North
    pa_rad = math.radians(pa_deg)
    x =  dra * math.sin(pa_rad) + ddec * math.cos(pa_rad)
    y = -dra * math.cos(pa_rad) + ddec * math.sin(pa_rad)
    return x, y


def _point_in_ellipse(t_ra, t_dec, g_ra, g_dec, a, b, pa_deg):
    """
    Returns (is_inside, normalized_distance).
    normalized_distance = 1.0  →  exactly on the ellipse boundary.
    a, b in arcsec; pa_deg East of North.
    """
    x, y = _ellipse_frame(t_ra, t_dec, g_ra, g_dec, pa_deg)
    norm_d = math.sqrt((x / a) ** 2 + (y / b) ** 2)
    return norm_d <= 1.0, norm_d


def _directional_light_radius(t_ra, t_dec, g_ra, g_dec, a, b, pa_deg):
    """Ellipse radius along the direction from the galaxy centre to the transient.

    DLR (Sullivan+2006, Gupta+2016): the galaxy's "edge" in the transient's
    direction, r(φ) = ab / sqrt((b cos φ)² + (a sin φ)²) with φ measured from
    the major axis. d_DLR = separation / DLR is the standard host-association
    statistic; with the R25-scaled axes it is identical to normalized_dist.
    """
    x, y = _ellipse_frame(t_ra, t_dec, g_ra, g_dec, pa_deg)
    phi = math.atan2(y, x)
    return a * b / math.sqrt((b * math.cos(phi)) ** 2 + (a * math.sin(phi)) ** 2)


def _catalog_shape_source(g):
    """Build a Tractor-like source dict from the candidate's own catalog columns.

    The rebuilt cat.desi carries the LS DR9 shape of every target and, where
    matched, the nearest LS DR10 model (dr10_*). Preferring DR10 keeps the
    result consistent with the live TAP query; DR9 is the fallback. Returns
    None when the candidate has no usable extended-source shape.
    """
    def _f(key):
        try:
            v = g.get(key)
            return None if v is None or v == '' else float(v)
        except (TypeError, ValueError):
            return None

    for prefix, type_key, ra_key, dec_key, origin in (
        ('dr10_', 'dr10_type', 'dr10_ra', 'dr10_dec', 'catalog_dr10'),
        ('', 'morphtype', 'ra', 'dec', 'catalog_dr9'),
    ):
        shape_r = _f(prefix + 'shape_r')
        src_type = str(g.get(type_key) or '').upper()
        if not shape_r or shape_r <= 0 or src_type in ('PSF', 'DUP', ''):
            continue
        ra, dec = _f(ra_key), _f(dec_key)
        if ra is None or dec is None:
            continue
        return {
            'ra': ra, 'dec': dec, 'type': src_type,
            'shape_r': shape_r,
            'shape_e1': _f(prefix + 'shape_e1') or 0.0,
            'shape_e2': _f(prefix + 'shape_e2') or 0.0,
            'sersic': _f(prefix + 'sersic'),
            'mag_r': _flux_to_mag(_f(prefix + 'flux_r')),
            'shape_source': origin,
        }
    return None


def _wrap_dra(ra1, ra2):
    """ra1 - ra2 in degrees, wrapped into [-180, 180)."""
    return (ra1 - ra2 + 180.0) % 360.0 - 180.0


def _approx_sep_arcsec(ra1, dec1, ra2, dec2, cosdec=None):
    """Fast small-angle separation approximation in arcsec (RA wrap-safe)."""
    if cosdec is None:
        cosdec = math.cos(math.radians((dec1 + dec2) / 2.0))
    dra = _wrap_dra(ra1, ra2)
    return math.sqrt(
        (dra * 3600.0 * cosdec) ** 2 +
        ((dec1 - dec2) * 3600.0) ** 2
    )


def _sep_sort_key(src):
    """Sort sources by transient separation, putting missing values last."""
    try:
        sep = float(src.get('sep_arcsec'))
    except (TypeError, ValueError):
        return math.inf
    return sep if math.isfinite(sep) else math.inf


def _adql_cone_box(ra, dec, radius_arcsec):
    """ADQL predicate for an RA/Dec box that fully covers the search cone.

    RA is widened by 1/cos(dec) at the box edge nearest the pole and split
    across the 0/360 wrap; near a pole the RA constraint is dropped entirely.
    """
    r_deg  = radius_arcsec / 3600.0
    dec_lo = max(dec - r_deg, -90.0)
    dec_hi = min(dec + r_deg,  90.0)
    predicate = f"dec BETWEEN {dec_lo} AND {dec_hi}"

    worst_dec = min(max(abs(dec_lo), abs(dec_hi)), 89.999999)
    ra_pad = r_deg / math.cos(math.radians(worst_dec))
    if ra_pad >= 180.0:
        return predicate
    ra_lo, ra_hi = ra - ra_pad, ra + ra_pad
    if ra_lo < 0.0 or ra_hi > 360.0:
        return f"{predicate} AND (ra >= {ra_lo % 360.0} OR ra <= {ra_hi % 360.0})"
    return f"{predicate} AND ra BETWEEN {ra_lo} AND {ra_hi}"


# ── catalog query ─────────────────────────────────────────────────────────────
def query_ls_dr10_models(ra, dec, radius_arcsec=60):
    """
    Query LS DR10 Tractor catalog via NOIRLAB Astro Data Lab TAP service.
    Excludes PSF and DUP (deblend-child) entries.

    Returns list of dicts:
        ra, dec, type, shape_r, shape_e1, shape_e2, mag_r
    """
    adql = (
        f"SELECT ra, dec, type, shape_r, shape_e1, shape_e2, flux_r, sersic "
        f"FROM ls_dr10.tractor "
        f"WHERE {_adql_cone_box(ra, dec, radius_arcsec)} "
        f"AND type NOT IN ('PSF', 'DUP') "
        f"AND shape_r > 0"
    )
    try:
        resp = requests.get(_TAP_URL, params={
            'REQUEST': 'doQuery',
            'LANG':    'ADQL',
            'FORMAT':  'csv',
            'QUERY':   adql,
        }, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[galaxy_model] catalog query failed: {exc}")
        return []

    sources = []
    reader  = csv.DictReader(io.StringIO(resp.text))
    cosdec  = math.cos(math.radians(dec))
    for row in reader:
        try:
            shape_r = float(row.get('shape_r') or 0)
            if shape_r <= 0:
                continue
            # The box over-covers the cone (by design); keep the cone itself.
            if _approx_sep_arcsec(float(row['ra']), float(row['dec']), ra, dec, cosdec) > radius_arcsec:
                continue
            sersic_n = row.get('sersic')
            try:
                sersic_n = float(sersic_n) if sersic_n not in (None, '', 'None') else None
            except (ValueError, TypeError):
                sersic_n = None
            sources.append({
                'ra':       float(row['ra']),
                'dec':      float(row['dec']),
                'type':     row.get('type', '?'),
                'shape_r':  shape_r,
                'shape_e1': float(row.get('shape_e1') or 0),
                'shape_e2': float(row.get('shape_e2') or 0),
                'sersic':   sersic_n,
                'mag_r':    _flux_to_mag(float(row['flux_r']) if row.get('flux_r') else None),
            })
        except (ValueError, KeyError):
            continue

    return sources


# ── host-galaxy check ─────────────────────────────────────────────────────────
def check_host_galaxy(transient_ra, transient_dec,
                      radius_arcsec=60, scale_factor=None):
    """
    Query LS DR10 models and check whether the transient lies inside any
    galaxy's R₂₅ ellipse (approximated per profile type).

    scale_factor : override multiplier for all sources (None = use per-type R₂₅)
                   DEV→3.3, EXP/REX→2.5, SER→computed from actual Sersic n, COMP→3.0

    Returns list of candidate dicts sorted by normalized_dist (nearest first).
    Each dict adds:
        a_arcsec, b_arcsec, pa_deg, sep_arcsec, normalized_dist,
        is_host, eff_scale
    """
    models = query_ls_dr10_models(transient_ra, transient_dec, radius_arcsec)
    candidates = []

    for src in models:
        try:
            r, e1, e2 = _effective_shape(src)
            a, b, pa  = _ellip_to_shape(r, e1, e2)
            eff_scale = scale_factor if scale_factor is not None else _r25_scale_src(src)
            a_scaled  = a * eff_scale
            b_scaled  = b * eff_scale
            is_in, norm_d = _point_in_ellipse(
                transient_ra, transient_dec,
                src['ra'], src['dec'],
                a_scaled, b_scaled, pa
            )
            sep = SkyCoord(ra=transient_ra * u.deg, dec=transient_dec * u.deg
                           ).separation(
                           SkyCoord(ra=src['ra'] * u.deg, dec=src['dec'] * u.deg)
                           ).arcsec
            candidates.append({
                **src,
                'a_arcsec':        round(a, 3),
                'b_arcsec':        round(b, 3),
                'pa_deg':          round(pa, 2),
                'sep_arcsec':      round(sep, 2),
                'normalized_dist': round(norm_d, 4),
                'is_host':         is_in,
                'eff_scale':       eff_scale,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x['normalized_dist'])
    return candidates


# ── visualisation ─────────────────────────────────────────────────────────────
def plot_galaxy_ellipses(transient_ra, transient_dec, candidates,
                          fov_arcsec=120, scale_factor=None,
                          output_path=None, layer='ls-dr10', #-grz
                          force_show_r25=False):
    """
    Download LS DR10 cutout and overlay Tractor model ellipses.

    Parameters
    ----------
    fov_arcsec   : field of view (arcsec); also controls download size
    scale_factor : override multiplier (None = use per-source eff_scale / R₂₅)
                   draws R₅₀ (dashed) and R₂₅ (solid) ellipses
    output_path  : save to file if given; otherwise return PNG bytes
    force_show_r25 : if True, always draw R25 ellipse even when transient is in R50

    Returns
    -------
    output_path (str) or PNG bytes (bytes) or None on failure
    """
    # ---- download image ----
    pixscale   = 0.262                        # arcsec/pixel, LS DR10 native
    pixel_size = max(64, min(512, int(fov_arcsec / pixscale)))
    actual_ps  = fov_arcsec / pixel_size      # actual arcsec/pixel

    url_params = {
        'ra':       transient_ra,
        'dec':      transient_dec,
        'pixscale': actual_ps,
        'layer':    layer,
        'size':     pixel_size,
    }
    try:
        resp = requests.get(_CUTOUT_URL, params=url_params, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert('RGB')
    except Exception as exc:
        print(f"[galaxy_model] image download failed: {exc}")
        return None

    img_arr = np.array(img)
    h, w    = img_arr.shape[:2]
    cx, cy  = w / 2.0, h / 2.0

    # ---- coordinate helpers ----
    cosdec = math.cos(math.radians(transient_dec))

    def sky_to_pix(ra, dec):
        # East → left (RA increases left), North → up
        dx = _wrap_dra(transient_ra, ra) * 3600.0 * cosdec / actual_ps
        dy = (dec - transient_dec) * 3600.0 / actual_ps
        return cx + dx, cy - dy

    # ---- plot ----
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(img_arr, origin='upper')

    # Transient marker
    ax.plot(cx, cy, marker='+', color='cyan', markersize=18, mew=2.5,
            label='Transient', zorder=10)

    HOST_COLORS = ['lime', 'yellow', 'orange', 'tomato', 'deepskyblue',
                   'violet', 'white']

    for i, src in enumerate(sorted(candidates, key=_sep_sort_key)):
        color    = HOST_COLORS[i % len(HOST_COLORS)]
        xg, yg   = sky_to_pix(src['ra'], src['dec'])
        a_pix    = src['a_arcsec'] / actual_ps
        b_pix    = src['b_arcsec'] / actual_ps
        mpl_ang  = -90.0 - src['pa_deg']
        eff_sc   = scale_factor if scale_factor is not None else src.get('eff_scale', _r25_scale_src(src))

        # R₅₀ boundary (dashed)
        ax.add_patch(Ellipse(
            xy=(xg, yg), width=2 * a_pix, height=2 * b_pix,
            angle=mpl_ang, linewidth=1.2,
            edgecolor=color, facecolor='none', linestyle='--', zorder=5,
        ))

        # R₂₅ boundary (solid) — optionally force drawing in debug/main mode
        in_r50 = src['normalized_dist'] * eff_sc <= 1.0
        if force_show_r25 or not in_r50:
            ax.add_patch(Ellipse(
                xy=(xg, yg),
                width=2 * a_pix * eff_sc,
                height=2 * b_pix * eff_sc,
                angle=mpl_ang, linewidth=1.8,
                edgecolor=color, facecolor='none', linestyle='-',
                alpha=0.85, zorder=5,
            ))

        sersic_str = f" n={src['sersic']:.1f}" if src.get('sersic') is not None and str(src.get('type','')).upper() == 'SER' else ""
        status_str = "IN" if (in_r50 or src['is_host']) else ""
        label_str = f"{src['type']}{sersic_str}  sep={src['sep_arcsec']:.1f}\""
        if status_str:
            label_str += f"  {status_str}"
        ax.plot(xg, yg, marker='x', color=color, markersize=7, mew=1.5, zorder=6,
                label=label_str)

    # ---- axes ticks in arcsec offset ----
    n_t = 5
    xt  = np.linspace(0, w, n_t)
    ax.set_xticks(xt)
    ax.set_xticklabels([f"{(cx - x) * actual_ps:.0f}" for x in xt], fontsize=8)
    yt  = np.linspace(0, h, n_t)
    ax.set_yticks(yt)
    ax.set_yticklabels([f"{(cy - y) * actual_ps:.0f}" for y in yt], fontsize=8)
    ax.set_xlabel("← RA offset (arcsec, East +)",  fontsize=9)
    ax.set_ylabel("Dec offset (arcsec, North +)",   fontsize=9)
    ax.set_title(
        f"LS DR10  RA={transient_ra:.5f}  Dec={transient_dec:.5f}\n"
        f"-- = R₅₀   ─ = R₂₅ boundary (Sersic profile, μ_lim=25)",
        fontsize=9,
    )
    ax.legend(fontsize=7, loc='upper right')
    plt.tight_layout()

    # ---- save / return ----
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return output_path
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.read()


R50_FLOOR_ARCSEC = 0.5   # unresolved hosts: below the seeing, d_DLR would explode


def analyze_specz_galaxies(transient_ra, transient_dec, specz_galaxies,
                           scale_factor=None, match_tol_arcsec=3.0,
                           fallback_tol_arcsec=10.0, search_buffer_arcsec=15.0,
                           r50_floor_arcsec=R50_FLOOR_ARCSEC):
    """
    Match cross-match/spec-z candidates to LS DR10 Tractor models and evaluate
    whether the transient falls inside each matched ellipse.

    Returns a list aligned with `specz_galaxies`. Each result includes the raw
    ellipse containment flag in both `ellipse_contains` and `is_host` for
    backwards compatibility with existing plotting code.
    """
    if not specz_galaxies:
        return []

    cosdec = math.cos(math.radians(transient_dec))

    max_sep = 0.0
    for g in specz_galaxies:
        try:
            sep = _approx_sep_arcsec(g['ra'], g['dec'], transient_ra, transient_dec, cosdec)
            if sep > max_sep:
                max_sep = sep
        except Exception:
            continue
    search_r = int(math.ceil(max(max_sep + search_buffer_arcsec, 30.0)))

    models = query_ls_dr10_models(transient_ra, transient_dec, radius_arcsec=search_r)

    matched_sources = []
    for g in specz_galaxies:
        try:
            g_ra = float(g['ra'])
            g_dec = float(g['dec'])
        except (KeyError, TypeError, ValueError):
            continue

        best, best_sep = None, 9999.0
        for src in models:
            sep = _approx_sep_arcsec(src['ra'], src['dec'], g_ra, g_dec, cosdec)
            if sep < best_sep:
                best_sep = sep
                best = src

        sep_transient = _approx_sep_arcsec(g_ra, g_dec, transient_ra, transient_dec, cosdec)
        chosen_src = None
        ls_match_type = None
        if best and best_sep <= match_tol_arcsec:
            chosen_src = dict(best, shape_source='dr10_tap')
            ls_match_type = 'direct'
        elif best and best_sep <= fallback_tol_arcsec:
            chosen_src = dict(best, shape_source='dr10_tap')
            ls_match_type = 'fallback'
        else:
            # TAP down, target outside DR10, or no model within 10": use the
            # shape the catalog row itself carries (DR10 nearest, else DR9).
            chosen_src = _catalog_shape_source(g)
            if chosen_src:
                ls_match_type = 'catalog'
                best_sep = _approx_sep_arcsec(chosen_src['ra'], chosen_src['dec'], g_ra, g_dec, cosdec)

        if chosen_src:
            try:
                chosen_src = cast(dict, chosen_src)
                r, e1, e2 = _effective_shape(chosen_src)
                r = max(float(r), r50_floor_arcsec)          # same floor the DLR calibration used
                a, b, pa = _ellip_to_shape(r, e1, e2)
                eff_sc = scale_factor if scale_factor is not None else _r25_scale_src(chosen_src)
                _, norm_d = _point_in_ellipse(
                    transient_ra, transient_dec,
                    chosen_src['ra'], chosen_src['dec'],
                    a * eff_sc, b * eff_sc, pa
                )
                ellipse_contains = norm_d <= 1.0
                sep_center = _approx_sep_arcsec(
                    chosen_src['ra'], chosen_src['dec'], transient_ra, transient_dec, cosdec
                )
                dlr_r50 = _directional_light_radius(
                    transient_ra, transient_dec, chosen_src['ra'], chosen_src['dec'], a, b, pa
                )
                matched_sources.append({
                    **chosen_src,
                    'a_arcsec':        round(a, 3),
                    'b_arcsec':        round(b, 3),
                    'pa_deg':          round(pa, 2),
                    'sep_arcsec':      round(sep_transient, 2),
                    'center_sep_arcsec': round(sep_center, 2),
                    'normalized_dist': round(norm_d, 4),
                    'dlr_r50_arcsec':  round(dlr_r50, 3),
                    'dlr_r25_arcsec':  round(dlr_r50 * eff_sc, 3),
                    'd_dlr':           round(sep_center / dlr_r50, 4) if dlr_r50 > 0 else None,
                    'ellipse_contains': ellipse_contains,
                    'is_host':         ellipse_contains,
                    'eff_scale':       eff_sc,
                    'specz_name':      g.get('name', ''),
                    'specz_z':         g.get('z', g.get('redshift', None)),
                    'catalog_name':    g.get('catalog_name', ''),
                    'candidate_type':  g.get('type', ''),
                    'crossmatch_uid':  g.get('crossmatch_uid'),
                    'match_label':     g.get('label', ''),
                    'ls_dr10_sep':     round(best_sep, 2),
                    'ls_match_type':   ls_match_type,
                    'shape_source':    chosen_src.get('shape_source'),
                })
                if ls_match_type == 'fallback':
                    print(f"[galaxy_model] fallback match: LS DR10 {chosen_src['type']} at {best_sep:.1f}\" from candidate pos")
                continue
            except Exception:
                pass

        matched_sources.append({
            'ra': g_ra,
            'dec': g_dec,
            'type': '?',
            'shape_r': None,
            'a_arcsec': None,
            'b_arcsec': None,
            'pa_deg': None,
            'sep_arcsec': round(sep_transient, 2),
            'center_sep_arcsec': None,
            'normalized_dist': None,
            'dlr_r50_arcsec': None,
            'dlr_r25_arcsec': None,
            'd_dlr': None,
            'ellipse_contains': False,
            'is_host': False,
            'mag_r': None,
            'specz_name': g.get('name', ''),
            'specz_z': g.get('z', g.get('redshift', None)),
            'catalog_name': g.get('catalog_name', ''),
            'candidate_type': g.get('type', ''),
            'crossmatch_uid': g.get('crossmatch_uid'),
            'match_label': g.get('label', ''),
            'ls_dr10_sep': None,
            'ls_match_type': None,
            'shape_source': None,
        })

    return matched_sources


# ── spec-z galaxy ellipse plot (for pipeline use) ─────────────────────────────
def plot_specz_ellipse(transient_ra, transient_dec, specz_galaxies,
                       fov_arcsec=120, scale_factor=None,
                       match_tol_arcsec=3.0, output_path=None,
                       matched_sources=None, host_uid=None, info_lines=None,
                       title=None, shared_uids=None):
    """
    Download LS DR10 cutout and overlay Tractor ellipses ONLY for galaxies
    that have a spectroscopic match (i.e. from DESI catalog).

    Parameters
    ----------
    transient_ra/dec  : transient coordinates (degrees)
    specz_galaxies    : list of dicts with keys 'ra', 'dec', and optionally 'z', 'name'
                        — these are the DESI-matched galaxy positions
    match_tol_arcsec  : max distance (arcsec) to identify LS DR10 source with spec-z galaxy
    output_path       : save to file if given; else return PNG bytes
    matched_sources   : result of analyze_specz_galaxies() for these galaxies, if the
                        caller already has it — skips a second TAP query and guarantees
                        the plot shows the same containment decision that was stored
    host_uid          : crossmatch_uid of the row the host rule chose; drawn heavier, with
                        the DLR segment from its centre to the transient and d_DLR labelled
    shared_uids       : rows the host rule folded into the host galaxy (a fibre on a spiral
                        arm, a Tractor shred at the same z) — drawn thin and dotted so a
                        piece of the host is not mistaken for a second galaxy
    info_lines        : short strings for the corner box (name, z, M_abs, score, tags …)
    title             : first title line (default: coordinates)

    Returns
    -------
    output_path (str) or PNG bytes (bytes) or None on failure
    """
    if not specz_galaxies:
        return None
    if matched_sources is None:
        matched_sources = analyze_specz_galaxies(
            transient_ra, transient_dec, specz_galaxies,
            scale_factor=scale_factor,
            match_tol_arcsec=match_tol_arcsec,
        )

    cosdec = math.cos(math.radians(transient_dec))

    # ---- download image ----
    pixscale   = 0.262
    pixel_size = max(64, min(512, int(fov_arcsec / pixscale)))
    actual_ps  = fov_arcsec / pixel_size

    url_params = {
        'ra': transient_ra, 'dec': transient_dec,
        'pixscale': actual_ps, 'layer': 'ls-dr10-grz', 'size': pixel_size,
    }
    try:
        resp = requests.get(_CUTOUT_URL, params=url_params, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert('RGB')
    except Exception as exc:
        print(f"[galaxy_model] image download failed: {exc}")
        return None

    img_arr = np.array(img)
    h, w    = img_arr.shape[:2]
    cx, cy  = w / 2.0, h / 2.0

    def sky_to_pix(ra, dec):
        dx = _wrap_dra(transient_ra, ra) * 3600.0 * cosdec / actual_ps
        dy = (dec - transient_dec) * 3600.0 / actual_ps
        return cx + dx, cy - dy

    # ---- plot ----
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(img_arr, origin='upper')

    # Transient marker
    ax.plot(cx, cy, marker='+', color='cyan', markersize=18, mew=2.5,
            label='Transient', zorder=10)

    COLORS = ['lime', 'yellow', 'orange', 'tomato', 'deepskyblue', 'violet', 'white']

    shared_uids = set(shared_uids or ())
    for i, src in enumerate(sorted(matched_sources, key=_sep_sort_key)):
        is_host_row = host_uid is not None and src.get('crossmatch_uid') == host_uid
        is_shred = src.get('crossmatch_uid') in shared_uids
        if is_host_row:
            color, lw_r50, lw_r25, ls_r25 = 'lime', 2.2, 3.0, '-'
        elif is_shred:
            color, lw_r50, lw_r25, ls_r25 = 'lightgrey', 0.9, 0.9, ':'
        else:
            color, lw_r50, lw_r25, ls_r25 = COLORS[(i + 1) % len(COLORS)], 1.2, 1.8, '-'
        xg, yg = sky_to_pix(src['ra'], src['dec'])

        z_str   = f"z={src['specz_z']:.4f}" if src['specz_z'] is not None else ""
        mag_str = f"r={src['mag_r']}" if src['mag_r'] else ""

        if src['a_arcsec'] is not None:
            a_pix   = src['a_arcsec'] / actual_ps
            b_pix   = src['b_arcsec'] / actual_ps
            mpl_ang = -90.0 - src['pa_deg']
            eff_sc  = scale_factor if scale_factor is not None else src.get('eff_scale', _r25_scale_src(src))

            # R₅₀ (dashed) and R₂₅ (solid) — both always drawn, so the reader sees
            # the two scales the numbers refer to
            ax.add_patch(Ellipse(
                xy=(xg, yg), width=2*a_pix, height=2*b_pix,
                angle=mpl_ang, linewidth=lw_r50,
                edgecolor=color, facecolor='none', linestyle='--', zorder=5,
            ))
            ax.add_patch(Ellipse(
                xy=(xg, yg),
                width=2*a_pix*eff_sc, height=2*b_pix*eff_sc,
                angle=mpl_ang, linewidth=lw_r25,
                edgecolor=color, facecolor='none', linestyle=ls_r25, alpha=0.9, zorder=5,
            ))
            in_r50 = src['normalized_dist'] * eff_sc <= 1.0

            # DLR segment: galaxy centre -> transient, labelled with d_DLR (R50)
            if is_host_row and src.get('d_dlr') is not None:
                ax.plot([xg, cx], [yg, cy], color=color, lw=1.4, ls='-', alpha=0.9, zorder=7)
                mx, my = (xg + cx) / 2, (yg + cy) / 2
                ax.annotate(f"d_DLR={src['d_dlr']:.2f}\n{src.get('center_sep_arcsec', 0):.1f}\"",
                            (mx, my), xytext=(8, 8), textcoords='offset points',
                            fontsize=8, color=color, zorder=8,
                            bbox=dict(boxstyle='round,pad=0.25', fc='black', ec='none', alpha=0.55))

            sersic_str = f" n={src['sersic']:.1f}" if src.get('sersic') is not None and str(src.get('type','')).upper() == 'SER' else ""
            status_str = "IN" if (in_r50 or src.get('ellipse_contains', src['is_host'])) else "OUT"
            prefix = "HOST  " if is_host_row else ("part of host  " if is_shred else "")
            parts = [prefix + f"{src['type']}{sersic_str}", f"sep={src['sep_arcsec']:.1f}\""]
            if z_str:
                parts.append(z_str)
            if src.get('d_dlr') is not None:
                parts.append(f"d_DLR={src['d_dlr']:.2f}")
            parts.append(status_str)
            label = "  ".join(parts)
        else:
            # No LS DR10 match — just show a circle at the DESI position
            ax.add_patch(plt.Circle((xg, yg), radius=5, fill=False,
                                    edgecolor=color, linewidth=1.5,
                                    linestyle=':', zorder=5))
            label = f"DESI {z_str}  {mag_str}  (no model)"

        # Galaxy centre marker — label goes to legend
        ax.plot(xg, yg, marker='x', color=color, markersize=11 if is_host_row else 9,
                mew=2.5 if is_host_row else 2, zorder=6, label=label)

    if info_lines:
        ax.text(0.015, 0.985, "\n".join(str(l) for l in info_lines), transform=ax.transAxes,
                fontsize=8.5, color='white', family='monospace', va='top', ha='left', zorder=9,
                bbox=dict(boxstyle='round,pad=0.4', fc='black', ec='none', alpha=0.6))

    # The ellipses may reach past the cutout; never let them stretch the axes.
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)

    # Axis ticks in arcsec offset
    for ticks, get_off, set_fn, set_lbl in [
        (np.linspace(0, w, 5), lambda x: (cx - x)*actual_ps, ax.set_xticks, ax.set_xticklabels),
        (np.linspace(0, h, 5), lambda y: (cy - y)*actual_ps, ax.set_yticks, ax.set_yticklabels),
    ]:
        set_fn(ticks)
        set_lbl([f"{get_off(t):.0f}" for t in ticks], fontsize=8)
    ax.set_xlabel("\u2190 RA offset (arcsec, East +)", fontsize=9)
    ax.set_ylabel("Dec offset (arcsec, North +)", fontsize=9)
    ax.set_title(
        (title or f"LS DR10  RA={transient_ra:.5f}  Dec={transient_dec:.5f}") + "\n"
        f"-- = R₅₀   ─ = R₂₅ (Sérsic-scaled)   line = DLR direction   FOV {fov_arcsec:.0f}\"",
        fontsize=9,
    )
    ax.legend(fontsize=7, loc='lower right')
    fig.tight_layout()

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return output_path
    else:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.read()


# ── full pipeline ─────────────────────────────────────────────────────────────
def run(transient_ra, transient_dec,
        transient_name="Transient",
        radius_arcsec=60,
        scale_factor=None,
        fov_arcsec=120,
    output_path=None,
    force_show_r25=False):
    """
    Full pipeline: query LS DR10 models → check host → plot.

    scale_factor : None = use per-type R₂₅ approximation (recommended)
    force_show_r25 : if True, always draw R25 boundary in output image

    Returns dict:
        candidates      : all extended sources, sorted by proximity
        host_candidates : subset where is_host=True
        image           : output_path (str) or PNG bytes
    """
    print(f"[galaxy_model] {transient_name}  "
          f"RA={transient_ra:.5f}  Dec={transient_dec:.5f}  "
          f"r={radius_arcsec}\"")

    candidates = check_host_galaxy(transient_ra, transient_dec,
                                   radius_arcsec, scale_factor)

    if not candidates:
        print("[galaxy_model] No extended sources found — generating image with transient only.")
    else:
        print(f"[galaxy_model] {len(candidates)} extended source(s):")
        print("[galaxy_model] axis formula: e=sqrt(e1^2+e2^2), q=(1-e)/(1+e), "
              "a50=shape_r/sqrt(q), b50=shape_r*sqrt(q), "
              "a25=a50*scale, b25=b50*scale")
    for i, c in enumerate(candidates):
        flag = "  ← HOST" if c['is_host'] else ""
        a25 = c['a_arcsec'] * c['eff_scale']
        b25 = c['b_arcsec'] * c['eff_scale']
        print(f"  #{i+1:2d}  {c['type']:4s}  "
              f"center=({c['ra']:.6f},{c['dec']:+.6f})  "
              f"R50(a,b)=({c['a_arcsec']:5.2f}\",{c['b_arcsec']:5.2f}\")  "
              f"R25(a,b)=({a25:5.2f}\",{b25:5.2f}\")  "
              f"×{c['eff_scale']:.1f}≈R25  "
              f"sep={c['sep_arcsec']:6.1f}\"  "
              f"norm_d={c['normalized_dist']:.3f}"
              f"{flag}")

    image = plot_galaxy_ellipses(
        transient_ra, transient_dec, candidates,
        fov_arcsec=fov_arcsec,
        scale_factor=scale_factor,
        output_path=output_path,
        force_show_r25=force_show_r25,
    )

    host_candidates = [c for c in candidates if c['is_host']]
    return {
        'candidates':      candidates,
        'host_candidates': host_candidates,
        'image':           image,
    }


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    out_dir = GALAXY_MODEL_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        # (name, ra, dec, note)
        # ("SN2025wny",   109.143750,  38.352253, "SLSN-I z=2.011, DESI sep=1.7\""),
        # ("AT2025absb",   56.437083, -14.879133, "z=1.511, DESI sep=1.6\""),
        # ("AT2025adtl",  143.491987,   0.376886, "z=0.846, DESI sep=0.07\""),
        # ("SN2026gzf",   149.9287, 0.4184, "SN Ia z=0.169"),
        ("AT 2021nto", 161.825507, -4.713785, ""),
        ("AT 2021niu", 206.674106, 46.502936, ""),
        ("AT 2021achu", 339.601706, 6.470346, ""),
        ("AT 2021jhy", 216.835700, -0.120300, ""),
    ]

    for name, ra, dec, note in test_cases:
        print("\n" + "=" * 60)
        print(f"Test: {name}  ({note})")
        result = run(
            transient_ra=ra,
            transient_dec=dec,
            transient_name=name,
            radius_arcsec=60,
            scale_factor=None,
            fov_arcsec=20,
            output_path=str(out_dir / f"galaxy_model_{name}.png"),
            force_show_r25=False,
        )
        hosts = result['host_candidates']
        print(f"  → {len(hosts)} host candidate(s)")
        for h in hosts:
            a25 = h['a_arcsec'] * h['eff_scale']
            b25 = h['b_arcsec'] * h['eff_scale']
            print(f"     type={h['type']}  "
                  f"center=({h['ra']:.6f},{h['dec']:+.6f})  "
                f"R50(a,b)=({h['a_arcsec']:.2f}\",{h['b_arcsec']:.2f}\")  "
                f"R25(a,b)=({a25:.2f}\",{b25:.2f}\")  "
                  f"sep={h['sep_arcsec']:.2f}\"  "
                  f"mag_r={h['mag_r']}  norm_d={h['normalized_dist']:.3f}")
        if result['image']:
            print(f"  → image saved: {result['image']}")
