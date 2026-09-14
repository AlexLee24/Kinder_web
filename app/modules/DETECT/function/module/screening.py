"""Per-transient screening: absolute magnitude, vetoes, and a priority score.

The pipeline's purpose is a fast first look at every new TNS source:

* does it sit in a galaxy with a spectroscopic redshift?           -> host rule
* if so, how luminous is it?                                        -> absolute magnitude
* is it something we already know is not a target?                  -> known Galactic / known AGN / classified
* is it unusual enough for a large-telescope spectrum?              -> luminous, TDE-like, too bright for its z
* could it be a lensed SN?                                          -> Lens catalogue + "too bright" + passive host

Everything here is a *flag with a reason*; nothing is dropped. The score just
orders the queue for a human. Thresholds live at the top of the file.
"""

from __future__ import annotations

import math

from function.module.calculator import apm_to_abm, get_extinction, cosmo, normalize_filter_name

# ---- thresholds ------------------------------------------------------------

NUCLEAR_SEP_ARCSEC = 1.0          # transient within this of the model centre -> "nuclear"
STAR_COINCIDENT_ARCSEC = 1.5      # a DESI STAR spectrum this close -> flag
LUMINOUS_ABS_MAG = -20.0          # brighter than this -> Luminous
SLSN_ABS_MAG = -21.0              # extra weight
IA_PEAK_ABS_MAG = -19.3           # SN Ia peak, B-ish; used for the "too bright" test
TOO_BRIGHT_MARGIN = 1.0           # mag brighter than Ia peak
TOO_BRIGHT_MIN_Z = 0.15           # below this, "too bright" is just a luminous SN, not lensing
PASSIVE_SSFR = 1e-11              # sfr_cg / mass_cg below this -> passive host (lens-like)

# TNS classification strings that end the discussion (case-insensitive substrings).
GALACTIC_TYPES = ("cv", "varstar", "nova", "m dwarf", "yso", "wr", "microlensing")
AGN_TYPES = ("agn", "qso", "blazar", "nls1")

# Tags DETECT owns in transient.objects.tag; re-derived every run, never touching other tags.
DETECT_TAG_VOCAB = [
    "Host-confirmed", "Host-review", "Host-none", "Host-z?", "Ambiguous",
    "Host-z", "Nuclear", "Luminous", "SLSN?", "TDE?", "glSN?", "Too-bright",
    "Lens", "Passive-host", "Galactic", "AGN", "Star?", "Classified", "z-conflict",
]

# Host association outcome, one of three, written to detect_screen.host_status
# and as a tag — this is what the marshal shows next to each object.
HOST_STATUSES = ("confirmed", "review", "none")


def host_status_for(host_row, inside_galaxies: int, upload_rows=()) -> str:
    """confirmed: one host chosen and nothing to argue about
       review:    a human should look — the runner-up galaxy is almost as close in
                  d_DLR (ambiguous_host), two spectra on the host model disagree
                  (host_z_conflict), or the only candidate sits in the tentative
                  band D_max < d_DLR <= 2·D_max (host_tentative, no host assigned)
       none:      no spectroscopic galaxy is a member or tentative"""
    if host_row is not None:
        md = host_row.get("match_data") or {}
        if md.get("host_user"):                       # a person chose it on the marshal
            return "confirmed"
        return "review" if (md.get("host_z_conflict") or md.get("ambiguous_host")) else "confirmed"
    if any((r.get("match_data") or {}).get("host_user") is False for r in upload_rows or ()):
        return "none"                                  # a person said "no host"
    if inside_galaxies >= 2:
        return "review"
    if any((r.get("match_data") or {}).get("host_tentative") for r in upload_rows or ()):
        return "review"
    return "none"

# ---- helpers ---------------------------------------------------------------


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _type_matches(tns_type, needles) -> bool:
    t = str(tns_type or "").strip().lower()
    return bool(t) and any(n in t for n in needles)


def _filter_name(raw) -> str:
    """A TNS filter name ('r', 'orange', 'L', 'BG-q') or numeric TNS id ('111' -> 'r').
    Radio / JWST / IRAC bands have no optical extinction coefficient -> 'unknown'."""
    s = normalize_filter_name(raw)
    if s.startswith("F") and s[1:4].isdigit() or s.endswith(("Band", "MHz")) or s in ("3.4", "4.6", "3.6", "BPSR", "AFB"):
        return "unknown"
    return s


def absolute_magnitude(app_mag, z, ra, dec, filter_raw) -> dict:
    """Discovery-magnitude absolute magnitude with the project cosmology and SFD extinction.

    M = m − μ(z) − 2.5 log10(1+z) − A_λ   (calculator.apm_to_abm)
    Returns the pieces too, so the number can be audited.
    """
    m, z = _f(app_mag), _f(z)
    if m is None or z is None or z <= 0:
        return {"abs_mag": None}
    band = _filter_name(filter_raw)
    try:
        a_mw = float(get_extinction(float(ra), float(dec), band))
    except Exception:
        a_mw = 0.0
    abs_mag = apm_to_abm(m, z, a_mw)
    if isinstance(abs_mag, dict):            # calculator reports errors as dicts
        return {"abs_mag": None, "abs_mag_error": abs_mag.get("error")}
    distmod = float(cosmo.distmod(z).value)
    return {
        "abs_mag": round(float(abs_mag), 3),
        "abs_mag_band": band,
        "abs_mag_filter_known": band != "unknown",
        "app_mag": m,
        "distmod": round(distmod, 3),
        "k_corr": round(2.5 * math.log10(1 + z), 3),
        "a_mw": round(a_mw, 3),
    }


# ---- the screen ------------------------------------------------------------


def screen_target(*, name, ra, dec, obj_meta, host_row, upload_rows, star_hits,
                  inside_galaxies: int = 0) -> dict:
    """Flags, score and tags for one transient.

    obj_meta        : transient.objects row (discovery_mag, discovery_filter, type, redshift)
    host_row        : the upload row with is_host=True, or None
    upload_rows     : all cross-match rows for this target (DESI + Lens)
    star_hits       : DESI STAR rows within STAR_COINCIDENT_ARCSEC
    inside_galaxies : distinct galaxies whose ellipse contains the transient
    """
    md = (host_row or {}).get("match_data") or {}
    flags: dict = {}
    score = 0
    tags: list[str] = []

    status = host_status_for(host_row, inside_galaxies, upload_rows)
    flags["host_status"] = status
    flags["host_user"] = md.get("host_user") if host_row is not None else (
        False if any((r.get("match_data") or {}).get("host_user") is False for r in upload_rows) else None)
    flags["host_user_by"] = md.get("host_user_by") if host_row is not None else None
    flags["inside_galaxies"] = inside_galaxies
    tags.append({"confirmed": "Host-confirmed", "review": "Host-review", "none": "Host-none"}[status])
    tentative_rows = [r for r in upload_rows if (r.get("match_data") or {}).get("host_tentative")]
    flags["host_tentative"] = bool(host_row is None and tentative_rows)
    if flags["host_tentative"]:
        tags.append("Host-z?")
        t = min(tentative_rows, key=lambda r: (r.get("match_data") or {}).get("d_dlr") or 99)
        flags["tentative_host"] = t.get("candidate_name")
        flags["tentative_d_dlr"] = (t.get("match_data") or {}).get("d_dlr")
        flags["tentative_z"] = _f(t.get("candidate_redshift"))
        score += 1
    if host_row is not None and md.get("ambiguous_host"):
        tags.append("Ambiguous")

    tns_type = (obj_meta or {}).get("type")
    lens_rows = [r for r in upload_rows if str(r.get("catalog_name", "")).lower().startswith("lens")]

    # -- redshift: DESI host first, TNS classification redshift as a fallback ---------------
    z, z_source = None, None
    if host_row is not None and _f(host_row.get("candidate_redshift")) is not None:
        z, z_source = _f(host_row["candidate_redshift"]), "desi_host"
    elif _f((obj_meta or {}).get("redshift")) is not None:
        z, z_source = _f(obj_meta["redshift"]), "tns"
    flags["z"], flags["z_source"] = z, z_source

    # -- host ------------------------------------------------------------------------------
    if host_row is not None:
        score += 3
        tags.append("Host-z")
        flags["host"] = host_row.get("candidate_name")
        flags["host_targetid"] = md.get("TARGETID")
        for k in ("center_sep_arcsec", "d_dlr", "offset_kpc", "host_z_conflict", "shares_host_galaxy",
                  "mass_cg", "sfr_cg", "spectype", "morphtype", "agn_maskbits", "wise_agn_stern12"):
            flags[k] = md.get(k)
        if md.get("host_z_conflict"):
            tags.append("z-conflict")

    nuclear = host_row is not None and (_f(md.get("center_sep_arcsec")) or 99.0) <= NUCLEAR_SEP_ARCSEC
    flags["nuclear"] = nuclear
    if nuclear:
        tags.append("Nuclear")

    # -- absolute magnitude: brightest light-curve point first, discovery mag as fallback --
    meta = obj_meta or {}
    disc = absolute_magnitude(meta.get("discovery_mag"), z, ra, dec, meta.get("discovery_filter"))
    flags["abs_mag_discovery"] = disc.get("abs_mag")
    peak = absolute_magnitude(meta.get("peak_mag"), z, ra, dec, meta.get("peak_filter")) \
        if meta.get("peak_mag") is not None else {"abs_mag": None}
    if peak.get("abs_mag") is not None:
        flags.update(peak)
        flags["abs_mag_source"] = "peak"
        flags["peak_mag"], flags["peak_filter"] = meta.get("peak_mag"), _filter_name(meta.get("peak_filter"))
        flags["peak_mjd"], flags["peak_source"] = meta.get("peak_mjd"), meta.get("peak_source")
        flags["n_phot"] = meta.get("n_phot")
    else:
        flags.update(disc)
        flags["abs_mag_source"] = "discovery" if disc.get("abs_mag") is not None else None
    abs_mag = flags.get("abs_mag")

    # -- vetoes (known things) --------------------------------------------------------------
    galactic = _type_matches(tns_type, GALACTIC_TYPES)
    flags["known_galactic"] = galactic
    if galactic:
        score -= 10
        tags.append("Galactic")

    host_agn = bool(md.get("agn_maskbits")) or str(md.get("spectype") or "") == "QSO"
    known_agn = _type_matches(tns_type, AGN_TYPES) or (nuclear and host_agn)
    flags["known_agn"] = known_agn
    flags["host_is_agn"] = host_agn
    if known_agn:
        score -= 10
        tags.append("AGN")

    classified = bool(str(tns_type or "").strip())
    flags["tns_type"] = tns_type or None
    if classified and not (galactic or known_agn):
        score -= 6                                # already has a spectrum: low priority, still listed
        tags.append("Classified")

    flags["desi_star_within_arcsec"] = min((_f(s.get("separation_arcsec")) or 99 for s in star_hits), default=None)
    if star_hits:
        score -= 3                                # a spectroscopic star at the position: probably stellar
        tags.append("Star?")

    # -- interesting things -----------------------------------------------------------------
    if host_row is not None and not classified:
        score += 2                                # spec-z host and nobody has classified it yet

    if abs_mag is not None and abs_mag <= LUMINOUS_ABS_MAG:
        score += 3
        tags.append("Luminous")
        if abs_mag <= SLSN_ABS_MAG:
            score += 1
            tags.append("SLSN?")

    tde_like = nuclear and not host_agn and not galactic
    flags["tde_candidate"] = tde_like
    if tde_like:
        score += 2
        tags.append("TDE?")

    too_bright = (abs_mag is not None and z is not None and z >= TOO_BRIGHT_MIN_Z
                  and abs_mag <= IA_PEAK_ABS_MAG - TOO_BRIGHT_MARGIN)
    flags["too_bright_for_z"] = too_bright
    if too_bright:
        score += 3
        tags.append("Too-bright")

    mass, sfr = _f(md.get("mass_cg")), _f(md.get("sfr_cg"))
    passive = (mass is not None and mass > 0 and sfr is not None and sfr / mass < PASSIVE_SSFR) \
        or str(md.get("morphtype") or "") == "DEV"
    flags["passive_host"] = bool(host_row is not None and passive)
    if flags["passive_host"]:
        tags.append("Passive-host")

    flags["lens_match"] = len(lens_rows)
    if lens_rows:
        score += 2
        tags.append("Lens")

    glsn = too_bright and (bool(lens_rows) or flags["passive_host"])
    flags["glsn_candidate"] = glsn
    if glsn:
        score += 3
        tags.append("glSN?")
        if flags["passive_host"]:
            score += 2

    flags["score"] = score
    return {"score": score, "flags": _plain(flags), "tags": tags}


def _plain(obj):
    """numpy scalars -> Python scalars, recursively; psycopg2 and JSON cannot take np.float64."""
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            return obj.item()
        except (ValueError, TypeError):
            return obj
    return obj
