import math
from pathlib import Path

import pandas as pd

from function.Legacy_survey_galaxy_model import analyze_specz_galaxies, plot_specz_ellipse
from function.Legacy_survey_img import create_marked_image
from function.module.DESI_cross_match import desi_cross_match
from function.module.Lens_cross_match import lens_cross_match
from function.module.tns_ingest import ingest_tns_csv, load_object_meta, load_user_host_decisions
from function.module.screening import screen_target
from function.database.upload_data import DataUploader
from function.database import get_db_connection, CatalogueService

from function.paths import PROJECT_ROOT, DATA_ROOT
CROSSMATCH_IMAGE_OUTPUT_DIR = DATA_ROOT / "crossmatch_images"
CROSSMATCH_IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CROSSMATCH_IMAGE_SOURCE = "DESI"


def _upload_tns_objects_directly(csv_path: Path | str) -> int:
    """Upsert the TNS CSV into transient.objects (see function/module/tns_ingest.py)."""
    result = ingest_tns_csv(csv_path)
    return result["inserted"] + result["updated"]


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sanitize_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(name))
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "target"


def _build_target_lookup(data_group: dict) -> dict[str, dict[str, float]]:
    lookup: dict[str, dict[str, float]] = {}
    for target in data_group.get('targets', []):
        if not isinstance(target, (tuple, list)) or len(target) < 3:
            continue
        ra = _safe_float(target[0])
        dec = _safe_float(target[1])
        name = str(target[2]).strip()
        if ra is None or dec is None or not name:
            continue
        lookup[name] = {'ra': ra, 'dec': dec}
    return lookup


def _build_upload_catalog_name(catalog_name: str, match: dict) -> str:
    if catalog_name != "Lens":
        return catalog_name
    origin = str(match.get('origin_catalog_name') or '').strip()
    if origin and origin.lower() != 'lens':
        return f"Lens_{origin}"
    return catalog_name


def _extract_redshift(match: dict):
    for key in ('z', 'redshift', 'z_source', 'z_lens', 'Z', 'zph', 'z(s)'):
        value = _safe_float(match.get(key))
        if value is not None:
            return value
    return None


def _build_candidate_name(catalog_name: str, match: dict, index: int) -> str:
    if catalog_name == 'DESI' and match.get('TARGETID') is not None:
        return f"DESI_{match.get('TARGETID')}"
    for key in ('name', 'obj_name', 'origin_catalog_name', 'TARGETID'):
        value = match.get(key)
        if value not in (None, ''):
            return str(value)
    return f"{catalog_name}_{index + 1}"


def _build_candidate_identity_key(match: dict, ra: float, dec: float) -> str:
    """Stable key for one catalog candidate; do not include result ordering."""
    for key in (
        'TARGETID',
        'targetid',
        'desi_target_id',
        'source_id',
        'obj_id',
        'objid',
        'object_id',
        'id',
        'name',
        'obj_name',
    ):
        value = match.get(key)
        if value not in (None, ''):
            clean_value = str(value).strip().replace('|', '_')
            return f"{key.lower()}:{clean_value}"
    return f"coord:{ra:.7f},{dec:.7f}"


def _prepare_target_upload_rows(target_name: str, catalog_name: str, matches: list[dict]) -> list[dict]:
    upload_rows = []
    seen_candidates = set()
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            continue
        ra = _safe_float(match.get('ra'))
        dec = _safe_float(match.get('dec'))
        if ra is None or dec is None:
            continue
        db_catalog_name = _build_upload_catalog_name(catalog_name, match)
        candidate_key = _build_candidate_identity_key(match, ra, dec)
        dedupe_key = (db_catalog_name, candidate_key)
        if dedupe_key in seen_candidates:
            continue
        seen_candidates.add(dedupe_key)
        crossmatch_uid = f"{target_name}|{db_catalog_name}|{candidate_key}"
        # NaN/inf are not JSON; a single one would make the JSONB upsert fail.
        match_data = {
            k: (None if isinstance(v, float) and not math.isfinite(v) else v)
            for k, v in match.items()
        }
        match_data['crossmatch_uid'] = crossmatch_uid
        upload_rows.append({
            'target_name': target_name,
            'catalog_name': db_catalog_name,
            'separation_arcsec': match.get('separation_arcsec'),
            'match_data': match_data,
            'updated_date': None,
            'status': 'Success',
            'is_host': False,
            'crossmatch_uid': crossmatch_uid,
            'candidate_ra': ra,
            'candidate_dec': dec,
            'candidate_name': _build_candidate_name(catalog_name, match, index),
            'candidate_redshift': _extract_redshift(match),
            'candidate_type': catalog_name,
        })
    return upload_rows


# Catalog columns the host rule can fall back on when LS DR10 TAP has no model.
_CANDIDATE_SHAPE_KEYS = (
    'morphtype', 'sersic', 'shape_r', 'shape_e1', 'shape_e2', 'flux_r',
    'dr10_ra', 'dr10_dec', 'dr10_type', 'dr10_sersic',
    'dr10_shape_r', 'dr10_shape_e1', 'dr10_shape_e2', 'dr10_flux_r', 'dr10_sep',
)


def _build_image_candidates(upload_rows: list[dict]) -> list[dict]:
    candidates = []
    for row in upload_rows:
        md = row.get('match_data') or {}
        candidate = {
            'ra': row['candidate_ra'],
            'dec': row['candidate_dec'],
            'z': row.get('candidate_redshift'),
            'redshift': row.get('candidate_redshift'),
            'name': row.get('candidate_name'),
            'label': row.get('candidate_name'),
            'catalog_name': row.get('catalog_name'),
            'type': row.get('candidate_type'),
            'crossmatch_uid': row.get('crossmatch_uid'),
        }
        for key in _CANDIDATE_SHAPE_KEYS:
            if md.get(key) is not None:
                candidate[key] = md[key]
        candidates.append(candidate)
    return candidates


# Legacy Surveys AB → Vega offsets (m_AB = m_Vega + offset) for the WISE bands.
_WISE_AB_MINUS_VEGA = {'w1': 2.699, 'w2': 3.339, 'w3': 5.174, 'w4': 6.620}


def _nanomaggy_to_mag(flux, transmission=None) -> float | None:
    """AB magnitude from LS nanomaggies, dereddened when a MW transmission is given."""
    f = _safe_float(flux)
    if f is None or f <= 0:
        return None
    t = _safe_float(transmission)
    if t and t > 0:
        f = f / t
    return round(22.5 - 2.5 * math.log10(f), 3)


def _photometry_mags(md: dict) -> dict:
    """Dereddened AB grz + WISE mags (AB and Vega) and the W1−W2 Vega colour."""
    out = {}
    for band in ('g', 'r', 'z'):
        out[f'mag_{band}'] = _nanomaggy_to_mag(md.get(f'flux_{band}'), md.get(f'mw_transmission_{band}'))
    for band, offset in _WISE_AB_MINUS_VEGA.items():
        ab = _nanomaggy_to_mag(md.get(f'flux_{band}'), md.get(f'mw_transmission_{band}'))
        out[f'{band}_mag_ab'] = ab
        out[f'{band}_mag_vega'] = round(ab - offset, 3) if ab is not None else None
    return out


def _wise_color(md: dict) -> tuple[float | None, bool | None]:
    """(W1−W2 in Vega mag, Stern+2012 AGN flag) from LS AB nanomaggy fluxes."""
    w1, w2 = _safe_float(md.get('flux_w1')), _safe_float(md.get('flux_w2'))
    if not w1 or not w2 or w1 <= 0 or w2 <= 0:
        return None, None
    w1_w2_vega = 2.5 * math.log10(w2 / w1) + (_WISE_AB_MINUS_VEGA['w2'] - _WISE_AB_MINUS_VEGA['w1'])
    return round(w1_w2_vega, 3), w1_w2_vega >= 0.8


def _estimate_fov_arcsec(target_ra: float, target_dec: float, candidates: list[dict],
                         analyzed: list[dict] | None = None) -> int:
    """Field of view that shows every candidate and the whole ellipse of any galaxy
    that contains the transient (a nearby spiral's R25 can be 30" across)."""
    if not candidates:
        return 60
    cosdec = math.cos(math.radians(target_dec))
    need = 0.0
    for candidate in candidates:
        dra = (candidate['ra'] - target_ra + 180.0) % 360.0 - 180.0
        sep = math.sqrt(
            (dra * 3600.0 * cosdec) ** 2 +
            ((candidate['dec'] - target_dec) * 3600.0) ** 2
        )
        need = max(need, 2.0 * sep + 20.0)
    for a in analyzed or []:
        if a.get('ellipse_contains') and _safe_float(a.get('a_arcsec')):
            a25 = float(a['a_arcsec']) * float(_safe_float(a.get('eff_scale')) or 2.5)
            sep = _safe_float(a.get('center_sep_arcsec')) or 0.0
            need = max(need, 2.0 * (a25 + sep) + 10.0)
    return int(max(30.0, min(180.0, need)))


HOST_Z_TOLERANCE = 0.001          # candidates closer than this in z are one galaxy
_GALAXY_KEY_DECIMALS = 5          # 1e-5 deg = 0.036"; rows on the same Tractor model share ra/dec exactly


def _galaxy_key(analysis: dict) -> tuple[float, float]:
    """Identity of the galaxy a candidate resolved to (its Tractor model centre)."""
    return (round(float(analysis['ra']), _GALAXY_KEY_DECIMALS),
            round(float(analysis['dec']), _GALAXY_KEY_DECIMALS))


def _projected_offset_kpc(sep_arcsec, redshift) -> float | None:
    """Projected transient-nucleus offset in kpc for a spectroscopic redshift."""
    sep = _safe_float(sep_arcsec)
    z = _safe_float(redshift)
    if sep is None or z is None or z <= 0:
        return None
    from function.module.calculator import cosmo          # same cosmology as the absolute magnitudes
    kpc_per_arcsec = float(cosmo.kpc_proper_per_arcmin(z).value) / 60.0
    return round(float(sep * kpc_per_arcsec), 3)


# ── host rule v1 (DLR) ───────────────────────────────────────────────────
# Calibrated on 4,474 TNS-classified SNe with a DESI host (function/analysis/
# calibrate_dlr.py, 2026-09-14): SER/DEV hosts reach 95 % completeness near
# d_DLR ≈ 5, EXP/REX (small galaxies) near 10–18; a runner-up within 1.5× of
# the best d_DLR is where "smallest d_DLR wins" fails 6.5 % of the time
# instead of 0.9 %.
D_MAX_BY_TYPE = {'SER': 4.0, 'DEV': 4.0, 'COMP': 4.0, 'EXP': 8.0, 'REX': 8.0}
D_MAX_DEFAULT = 4.0
D_MAX_QSO = 1.0                   # a QSO spectrum only "hosts" a nuclear transient; no tentative band
LENS_SEARCH_RADIUS_ARCSEC = 5.0   # cat.lens cone; lensed images lie within an Einstein radius
TENTATIVE_FACTOR = 2.0            # D_max < d_DLR <= 2·D_max -> "Host-z?", not a host
AMBIGUOUS_RATIO = 1.5             # second-best d_DLR within this factor of the best


def _d_max_for(tractor_type) -> float:
    return D_MAX_BY_TYPE.get(str(tractor_type or '').upper(), D_MAX_DEFAULT)


def _centre_inside_r25(inner: dict, outer: dict) -> bool:
    """Is galaxy `inner`'s centre inside galaxy `outer`'s R25 ellipse? (a shred, an
    HII region, a fibre on a spiral arm — as opposed to a companion at the same z)"""
    try:
        from function.Legacy_survey_galaxy_model import _point_in_ellipse
        a = float(outer['a_arcsec']) * float(outer.get('eff_scale') or 2.5)
        b = float(outer['b_arcsec']) * float(outer.get('eff_scale') or 2.5)
        inside, _ = _point_in_ellipse(float(inner['ra']), float(inner['dec']),
                                      float(outer['ra']), float(outer['dec']), a, b, float(outer['pa_deg']))
        return bool(inside)
    except (KeyError, TypeError, ValueError):
        return False


def _apply_host_rule(target_ra: float, target_dec: float, upload_rows: list[dict]) -> tuple[list[dict], int]:
    """Decide is_host for each upload row. Returns (analyzed rows, member galaxies).

    Rule v1 (DLR):
      * every candidate resolves to a Tractor model; rows on one model are one galaxy
      * a galaxy is a *member* if d_DLR(R50) <= D_max for its morphology
        (SER/DEV/COMP 4, EXP/REX 8); D_max < d_DLR <= 2·D_max is *tentative*
      * z-consistent members whose centre lies inside another member's R25 ellipse
        are shreds of it and are merged into it
      * host = the member galaxy with the smallest d_DLR; its host *row* is chosen by
        the preference order (DESI > Lens, GALAXY > QSO, direct > fallback, primary
        target with LS photometry > bare fibre, then nearest)
      * a second member within AMBIGUOUS_RATIO of the best d_DLR -> ambiguous_host
        (host still assigned, status 'review'); a tentative-only case -> host_tentative
    """
    candidates = _build_image_candidates(upload_rows)
    analyzed = analyze_specz_galaxies(target_ra, target_dec, candidates) if candidates else []

    rows_by_uid = {r['crossmatch_uid']: r for r in upload_rows if r.get('crossmatch_uid')}
    analyzed_by_uid = {a['crossmatch_uid']: a for a in analyzed if a.get('crossmatch_uid')}

    def _row_z(uid):
        return _safe_float(rows_by_uid[uid].get('candidate_redshift'))

    # ── galaxies: one entry per Tractor model that has a d_DLR ────────────
    galaxies: dict[tuple, dict] = {}
    for analysis in analyzed:
        uid = analysis.get('crossmatch_uid')
        d = _safe_float(analysis.get('d_dlr'))
        if uid not in rows_by_uid or d is None:
            continue
        g = galaxies.setdefault(_galaxy_key(analysis), {'uids': [], 'd_dlr': d, 'analysis': analysis})
        g['uids'].append(uid)

    def _spectype(uid):
        return str((rows_by_uid[uid].get('match_data') or {}).get('spectype') or '').upper()

    for g in galaxies.values():
        # A model whose only spectra are QSOs is a quasar, not a galaxy with an
        # outskirt: it can host a nuclear transient (d_DLR <= 1) and nothing else.
        g['qso_only'] = bool(g['uids']) and all(_spectype(u) == 'QSO' for u in g['uids'])
        g['d_max'] = D_MAX_QSO if g['qso_only'] else _d_max_for(g['analysis'].get('type'))
        g['member'] = g['d_dlr'] <= g['d_max']
        g['tentative'] = (not g['member']) and not g['qso_only'] and g['d_dlr'] <= TENTATIVE_FACTOR * g['d_max']
        g['z'] = next((_row_z(u) for u in g['uids'] if _row_z(u) is not None), None)

    # ── merge shreds: same z AND centre inside the bigger galaxy's R25 ────
    members = sorted((g for g in galaxies.values() if g['member']), key=lambda g: g['d_dlr'])
    merged_into: dict[int, int] = {}
    for i, gi in enumerate(members):
        for j, gj in enumerate(members):
            if i == j or id(gj) in merged_into or id(gi) in merged_into:
                continue
            same_z = gi['z'] is not None and gj['z'] is not None and abs(gi['z'] - gj['z']) <= HOST_Z_TOLERANCE
            if same_z and _centre_inside_r25(gj['analysis'], gi['analysis']):
                a_i = float(gi['analysis'].get('a_arcsec') or 0); a_j = float(gj['analysis'].get('a_arcsec') or 0)
                big, small = (gi, gj) if a_i >= a_j else (gj, gi)
                big['uids'] = big['uids'] + small['uids']
                big['d_dlr'] = min(big['d_dlr'], small['d_dlr'])
                merged_into[id(small)] = id(big)
    members = [g for g in members if id(g) not in merged_into]
    members.sort(key=lambda g: g['d_dlr'])

    def _preferred_uid(uids: list[str]) -> str:
        """Which row of one galaxy is *the* host row (see docstring)."""
        def key(u):
            row = rows_by_uid[u]
            md = row.get('match_data') or {}
            analysis = analyzed_by_uid.get(u, {})
            return (
                row.get('catalog_name') != 'DESI',
                str(md.get('spectype') or 'GALAXY') != 'GALAXY',
                analysis.get('ls_match_type') != 'direct',
                md.get('morphtype') is None,
                _safe_float(row.get('separation_arcsec')) or float('inf'),
            )
        return min(uids, key=key)

    def _group_z_conflict(uids: list[str]) -> bool:
        # Two spectra on one Tractor model with different z: a blend (foreground
        # galaxy + background QSO, or a ToO fibre on the transient itself).
        zs = [_row_z(u) for u in uids if _row_z(u) is not None]
        return len(zs) >= 2 and (max(zs) - min(zs)) > HOST_Z_TOLERANCE

    unique_host_uid = None
    host_group: list[str] = []
    ambiguous = False
    tentative_uids: set[str] = set()
    if members:
        best = members[0]
        host_group = best['uids']
        unique_host_uid = _preferred_uid(host_group)
        if len(members) > 1 and members[1]['d_dlr'] <= AMBIGUOUS_RATIO * max(best['d_dlr'], 1e-6):
            ambiguous = True
            names = ", ".join(f"{rows_by_uid[g['uids'][0]].get('candidate_name')} d_DLR={g['d_dlr']:.2f} z={g['z']}"
                              for g in members[:2])
            print(f"[INFO] ambiguous host — runner-up within {AMBIGUOUS_RATIO}x: {names}; best kept, flagged for review")
    else:
        for g in galaxies.values():
            if g['tentative']:
                tentative_uids.update(g['uids'])

    conflict_uids: set[str] = set()
    for g in galaxies.values():
        if _group_z_conflict(g['uids']):
            conflict_uids.update(g['uids'])
            names = ", ".join(f"{rows_by_uid[u].get('candidate_name')} z={_row_z(u)}" for u in g['uids'])
            print(f"[WARNING] blended spectra on one galaxy model: {names} — host kept, flagged host_z_conflict")

    member_uids = {u for g in members for u in g['uids']}
    rank_by_uid = {u: i + 1 for i, g in enumerate(members) for u in g['uids']}

    for upload_row in upload_rows:
        uid = upload_row.get('crossmatch_uid')
        analysis = analyzed_by_uid.get(uid, {})
        md = upload_row['match_data']
        final_is_host = uid == unique_host_uid
        upload_row['is_host'] = final_is_host
        md['host_rule'] = 'dlr_v1'
        md['ellipse_contains'] = bool(analysis.get('ellipse_contains', False))   # R25 containment, diagnostic
        md['is_Host'] = final_is_host
        md['host_candidate_count'] = len(members)
        md['host_member'] = uid in member_uids
        md['host_tentative'] = uid in tentative_uids
        md['host_rank'] = rank_by_uid.get(uid)
        md['d_dlr_max'] = (next((g['d_max'] for g in galaxies.values() if uid in g['uids']), None)
                           if analysis else None)
        md['ambiguous_host'] = bool(ambiguous and uid in host_group)
        md['shares_host_galaxy'] = bool(uid in host_group and not final_is_host)
        md['host_z_conflict'] = uid in conflict_uids
        # No LS photometry = not a primary target on a Tractor source: a secondary
        # or ToO fibre, possibly on the transient itself (separation ~ 0).
        md['ls_photometry'] = md.get('morphtype') is not None
        md.update(_photometry_mags(md))
        md['w1_w2_vega'], md['wise_agn_stern12'] = _wise_color(md)
        if analysis:
            md['ls_dr10_sep'] = analysis.get('ls_dr10_sep')
            md['ls_match_type'] = analysis.get('ls_match_type')
            md['normalized_dist'] = analysis.get('normalized_dist')
            md['tractor_type'] = analysis.get('type')
            md['center_sep_arcsec'] = analysis.get('center_sep_arcsec')
            md['dlr_r50_arcsec'] = analysis.get('dlr_r50_arcsec')
            md['dlr_r25_arcsec'] = analysis.get('dlr_r25_arcsec')
            md['d_dlr'] = analysis.get('d_dlr')
            md['shape_source'] = analysis.get('shape_source')
            md['host_a_arcsec'] = analysis.get('a_arcsec')
            md['host_b_arcsec'] = analysis.get('b_arcsec')
            md['host_pa_deg'] = analysis.get('pa_deg')
            md['offset_kpc'] = _projected_offset_kpc(
                analysis.get('center_sep_arcsec'), upload_row.get('candidate_redshift')
            )

    return analyzed, len(members)


def _desi_stars_near(target_lookup: dict[str, dict[str, float]], radius_arcsec: float = 1.5) -> dict[str, list[dict]]:
    """DESI STAR spectra within `radius_arcsec` of each target: a stellar object at the position."""
    if not target_lookup:
        return {}
    from psycopg2.extras import RealDictCursor
    hits: dict[str, list[dict]] = {}
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if CatalogueService.desi_layout(cur) != 'v2':
                    return {}
                for name, coords in target_lookup.items():
                    hits[name] = CatalogueService.fetch_desi_stars(cur, coords['ra'], coords['dec'], radius_arcsec)
    except Exception as e:
        print(f"[WARNING] DESI star check skipped ({type(e).__name__}): {e}")
    return hits


def _build_marked_coords(candidates: list[dict]) -> list[dict]:
    marked_coords = []
    for candidate in candidates:
        marked_coords.append({
            'ra': candidate['ra'],
            'dec': candidate['dec'],
            'redshift': candidate.get('redshift'),
            'name': candidate.get('name'),
            'type': candidate.get('type', 'DESI'),
        })
    return marked_coords


def _make_fallback_image_bytes(target_name: str, target_ra: float, target_dec: float,
                               upload_rows: list[dict]) -> bytes:
    """Pure-matplotlib fallback — no network required, always succeeds."""
    import io as _io
    import matplotlib.pyplot as _plt
    import matplotlib
    matplotlib.use('Agg')

    fig, ax = _plt.subplots(figsize=(8, 6))
    ax.set_facecolor('#111111')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    lines = [
        f"{target_name}",
        f"RA = {target_ra:.6f}   Dec = {target_dec:.6f}",
        "",
        "Sky image unavailable",
        f"{len(upload_rows)} cross-match candidate(s):",
    ]
    for row in upload_rows:
        cname = row.get('candidate_name', '?')
        cat   = row.get('catalog_name', '?')
        sep   = row.get('separation_arcsec')
        z     = row.get('candidate_redshift')
        sep_s = f"sep={sep:.1f}\"" if sep is not None else ""
        z_s   = f"z={z:.4f}" if z is not None else ""
        host_s = " [HOST]" if row.get('is_host') else ""
        lines.append(f"  {cat}: {cname}  {sep_s}  {z_s}{host_s}")

    y = 0.93
    for i, line in enumerate(lines):
        color  = 'white' if i > 0 else 'cyan'
        size   = 14 if i == 0 else 9
        weight = 'bold' if i == 0 else 'normal'
        ax.text(0.05, y, line, color=color, fontsize=size, fontweight=weight,
                transform=ax.transAxes, va='top', family='monospace')
        y -= 0.055 if i == 0 else 0.045

    buf = _io.BytesIO()
    _plt.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                 facecolor='#111111')
    _plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fetch_dss_image_bytes(target_name: str, target_ra: float, target_dec: float,
                           candidates: list[dict], fov_arcsec: float = 60) -> bytes | None:
    """
    Download DSS2 Red sky image from NASA SkyView (all-sky coverage) and overlay
    candidate positions.  Returns PNG bytes, or None if unavailable.
    """
    import io as _io
    import requests
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')
    from PIL import Image as _PILImage

    size_deg = max(fov_arcsec / 3600.0, 0.008)
    pixels = 512
    url = (
        "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl"
        f"?Survey=DSS2+Red&position={target_ra},{target_dec}"
        f"&Size={size_deg}&Pixels={pixels}&Return=PNG&Coordinates=J2000"
    )

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) < 2000:
            return None

        img = _PILImage.open(_io.BytesIO(resp.content))
        img_data = np.array(img)
        img_h, img_w = img_data.shape[:2]
        pixscale = fov_arcsec / pixels            # arcsec/pixel

        fig, ax = plt.subplots(figsize=(8, 8))
        ax.imshow(img_data, origin='upper',
                  cmap='gray' if img_data.ndim == 2 else None)

        # Mark transient position (image centre)
        ax.plot(img_w / 2, img_h / 2, 'c+', markersize=16, mew=3,
                zorder=5, label='Target')

        # Mark Lens candidates
        lens_colors = ['cyan', 'lime', 'yellow', 'orange', 'magenta', 'red', 'white']
        cosdec = math.cos(math.radians(target_dec))
        for i, cand in enumerate(candidates):
            cra  = cand.get('ra')
            cdec = cand.get('dec')
            if cra is None or cdec is None:
                continue
            dx    = (target_ra - cra) * 3600.0 * cosdec / pixscale
            dy    = (cdec - target_dec) * 3600.0 / pixscale
            xpix  = img_w / 2 + dx
            ypix  = img_h / 2 - dy
            color = lens_colors[i % len(lens_colors)]
            name  = cand.get('name', f'Lens_{i + 1}')
            z     = cand.get('redshift')
            z_s   = f" z={z:.3f}" if z is not None else ""
            ax.plot(xpix, ypix, 'D', color=color, markersize=12,
                    mfc='none', mew=2, zorder=4,
                    label=f'Lens: {name}{z_s}')

        ax.legend(loc='upper right', fontsize=9, framealpha=0.75)
        ax.set_title(
            f"{target_name}  RA={target_ra:.5f} Dec={target_dec:.5f}\n"
            f"DSS2 Red | FOV={fov_arcsec}\"",
            fontsize=10,
        )
        ax.axis('off')

        buf = _io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                    facecolor='black')
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        print(f"[WARNING] {target_name}: DSS2 fetch failed: {type(e).__name__} - {e}")
        return None


def _image_info_lines(target_name: str, screen: dict | None, host_row: dict | None) -> tuple[list[str], str]:
    """Corner-box text and title for the overlay image, from the screen result."""
    f = (screen or {}).get('flags') or {}
    lines = [target_name]
    if host_row is not None:
        z = f.get('z')
        lines.append(f"host {host_row.get('candidate_name')}  z={z:.4f}" if z is not None
                     else f"host {host_row.get('candidate_name')}")
    if f.get('abs_mag') is not None:
        band = f.get('abs_mag_band') or '?'
        band_s = f"M_{band}" if band != 'unknown' else "M(filter?)"
        lines.append(f"{band_s} = {f['abs_mag']:.2f}  (m={f.get('app_mag')}, A={f.get('a_mw')})")
    if f.get('offset_kpc') is not None:
        lines.append(f"offset {f.get('center_sep_arcsec')}\" = {f['offset_kpc']:.1f} kpc   d_DLR={f.get('d_dlr')}")
    if screen is not None:
        lines.append(f"score {screen.get('score')}   {' '.join(screen.get('tags') or [])}")
    return lines, f"{target_name}   LS DR10 grz"


def _generate_and_upload_target_image(target_name: str, target_ra: float, target_dec: float,
                                      upload_rows: list[dict],
                                      has_desi: bool = True,
                                      analyzed: list[dict] | None = None,
                                      screen: dict | None = None) -> tuple[str | None, bool]:
    image_candidates = _build_image_candidates(upload_rows)
    host_row = next((r for r in upload_rows if r.get('is_host')), None)
    shared_uids = {r['crossmatch_uid'] for r in upload_rows
                   if (r.get('match_data') or {}).get('shares_host_galaxy')}
    info_lines, title = _image_info_lines(target_name, screen, host_row)
    fov_arcsec = _estimate_fov_arcsec(target_ra, target_dec, image_candidates, analyzed)
    image_bytes = None

    if has_desi:
        # ── DESI / mixed path ─────────────────────────────────────────
        # 1st try: LS DR10 ellipse overlay
        if image_candidates:
            try:
                image_bytes = plot_specz_ellipse(
                    transient_ra=target_ra,
                    transient_dec=target_dec,
                    specz_galaxies=image_candidates,
                    fov_arcsec=fov_arcsec,
                    output_path=None,
                    matched_sources=analyzed,
                    host_uid=host_row.get('crossmatch_uid') if host_row else None,
                    shared_uids=shared_uids,
                    info_lines=info_lines,
                    title=title,
                )
            except Exception as e:
                print(f"[WARNING] {target_name}: plot_specz_ellipse failed: {type(e).__name__} - {e}")

        # 2nd try: Legacy Survey marked image
        if not isinstance(image_bytes, (bytes, bytearray)):
            try:
                image_bytes = create_marked_image(
                    obj_name=target_name,
                    obj_ra=target_ra,
                    obj_dec=target_dec,
                    matched_coords=_build_marked_coords(image_candidates),
                    output_path=None,
                    fov_arcsec=fov_arcsec,
                    max_retries=2,
                    save_to_data_dir=False,
                )
            except Exception as e:
                print(f"[WARNING] {target_name}: create_marked_image failed: {type(e).__name__} - {e}")
    else:
        # ── Lens-only path ────────────────────────────────────────────
        # 1st try: DSS2 Red via SkyView (full-sky coverage)
        print(f"[INFO] {target_name}: Lens-only — trying DSS2 sky image...")
        image_bytes = _fetch_dss_image_bytes(target_name, target_ra, target_dec,
                                             image_candidates, fov_arcsec)

        # 2nd try: Legacy Survey marked image (has built-in placeholder)
        if not isinstance(image_bytes, (bytes, bytearray)):
            print(f"[INFO] {target_name}: DSS2 unavailable — trying Legacy Survey cutout...")
            try:
                image_bytes = create_marked_image(
                    obj_name=target_name,
                    obj_ra=target_ra,
                    obj_dec=target_dec,
                    matched_coords=_build_marked_coords(image_candidates),
                    output_path=None,
                    fov_arcsec=fov_arcsec,
                    max_retries=2,
                    save_to_data_dir=False,
                )
            except Exception as e:
                print(f"[WARNING] {target_name}: create_marked_image failed: {type(e).__name__} - {e}")

    # ── Final fallback: pure-matplotlib text summary (no network) ─────
    if not isinstance(image_bytes, (bytes, bytearray)):
        print(f"[WARNING] {target_name}: using text-only fallback image (no sky cutout available)")
        try:
            image_bytes = _make_fallback_image_bytes(target_name, target_ra, target_dec, upload_rows)
        except Exception as e:
            print(f"[ERROR] {target_name}: fallback image also failed: {type(e).__name__} - {e}")
            return None, False

    image_bytes = bytes(image_bytes)
    output_path = CROSSMATCH_IMAGE_OUTPUT_DIR / f"{_sanitize_filename(target_name)}.png"
    output_path.write_bytes(image_bytes)
    uploaded = DataUploader.save_target_image(target_name, image_bytes, source=CROSSMATCH_IMAGE_SOURCE)
    return str(output_path), uploaded


def _apply_user_host_decision(upload_rows: list[dict], decision: dict | None) -> bool:
    """A person's host choice on the marshal overrides rule v1 (Follow-up objects are
    re-run daily, so the rule would otherwise flip it back). The rule's own verdict
    stays in match_data (host_member / host_rank / ...) for reference.

    Returns True when the decision was applied."""
    if not decision:
        return False
    if decision.get("decision") == "host":
        uid = decision.get("uid")
        if not any(r.get("crossmatch_uid") == uid for r in upload_rows):
            print(f"[WARNING] user-chosen host {uid} is no longer among the candidates — rule v1 result kept")
            return False
        for r in upload_rows:
            chosen = r.get("crossmatch_uid") == uid
            r["is_host"] = chosen
            r["match_data"]["is_Host"] = chosen
            r["match_data"]["host_user"] = chosen
            if chosen:
                r["match_data"]["host_user_by"] = decision.get("by")
        return True
    if decision.get("decision") == "none":
        for r in upload_rows:
            r["is_host"] = False
            r["match_data"]["is_Host"] = False
            r["match_data"]["host_user"] = False
        return True
    return False


def run_cross_match_pipeline(data_group: dict | None, group_name: str) -> dict:
    """
    Run cross-match pipeline and upload results to database.

    Args:
        data_group: Dataset with 'count' and 'targets' keys
        group_name: Name of the data group (e.g., 'TNS', 'Follow-up')

    Returns:
        Dictionary with 'desi' and 'lens' cross-match results
    """
    results = {'desi': {}, 'lens': {}, 'images': {}, 'host_summary': {}}

    if not data_group or not isinstance(data_group, dict):
        print(f"[WARNING] No {group_name} data available")
        return results

    count = data_group.get('count', 0)
    targets = data_group.get('targets', [])
    target_lookup = _build_target_lookup(data_group)

    if str(group_name).strip().upper() == 'TNS' and data_group.get('path'):
        _upload_tns_objects_directly(data_group['path'])

    print(f"\n[INFO] Running DESI cross-match on {count} {group_name} targets...")
    desi_results = desi_cross_match(targets)
    results['desi'] = desi_results
    desi_match_count = sum(len(v) for v in desi_results.values())
    print(f"[SUCCESS] {group_name} DESI results: {desi_match_count} matches found\n")

    print(f"[INFO] Running Lens cross-match on {count} {group_name} targets...")
    lens_results = lens_cross_match(targets, search_radius=LENS_SEARCH_RADIUS_ARCSEC)
    results['lens'] = lens_results
    lens_match_count = sum(len(v) for v in lens_results.values())
    print(f"[SUCCESS] {group_name} Lens results: {lens_match_count} matches found\n")

    all_upload_rows = []
    screen_rows = []
    image_upload_count = 0
    all_target_names = list(dict.fromkeys(
        list(target_lookup.keys()) + list(desi_results.keys()) + list(lens_results.keys())
    ))
    object_meta = load_object_meta(all_target_names)
    user_decisions = load_user_host_decisions(all_target_names)
    star_hits = _desi_stars_near(target_lookup)

    for target_name in all_target_names:
        target_coords = target_lookup.get(target_name)
        if not target_coords:
            print(f"[WARNING] Missing coordinates for {target_name}, skipping host analysis and image generation")
            continue

        target_upload_rows = []
        target_upload_rows.extend(_prepare_target_upload_rows(target_name, "DESI", desi_results.get(target_name, [])))
        target_upload_rows.extend(_prepare_target_upload_rows(target_name, "Lens", lens_results.get(target_name, [])))

        if not target_upload_rows:
            print(f"[INFO] {target_name}: no DESI/Lens match — skipping image")
            screen = screen_target(
                name=target_name, ra=target_coords['ra'], dec=target_coords['dec'],
                obj_meta=object_meta.get(target_name), host_row=None, upload_rows=[],
                star_hits=star_hits.get(target_name, []), inside_galaxies=0,
            )
            screen_rows.append({'target_name': target_name, **screen})
            results['host_summary'][target_name] = {
                'inside_count': 0, 'host_count': 0, 'host_candidates': [], 'analyzed_count': 0,
                'score': screen['score'], 'tags': screen['tags'], 'abs_mag': screen['flags'].get('abs_mag'),
                'host_status': 'none',
            }
            continue

        analyzed, inside_count = _apply_host_rule(
            target_coords['ra'],
            target_coords['dec'],
            target_upload_rows,
        )
        if _apply_user_host_decision(target_upload_rows, user_decisions.get(target_name)):
            d = user_decisions[target_name]
            print(f"[INFO] {target_name}: host decision by {d.get('by') or 'a user'} on the marshal "
                  f"({d['decision']}) overrides rule v1")
        all_upload_rows.extend(target_upload_rows)

        host_rows = [row for row in target_upload_rows if row.get('is_host')]
        screen = screen_target(
            name=target_name, ra=target_coords['ra'], dec=target_coords['dec'],
            obj_meta=object_meta.get(target_name), host_row=host_rows[0] if host_rows else None,
            upload_rows=target_upload_rows, star_hits=star_hits.get(target_name, []),
            inside_galaxies=inside_count,
        )
        screen_rows.append({'target_name': target_name, **screen})

        # Lens-only targets may lie outside Legacy Survey footprint — use DSS fallback
        has_desi = any(row.get('catalog_name', '').upper() == 'DESI' for row in target_upload_rows)
        image_path, uploaded = _generate_and_upload_target_image(
            target_name,
            target_coords['ra'],
            target_coords['dec'],
            target_upload_rows,
            has_desi=has_desi,
            analyzed=analyzed,
            screen=screen,
        )
        results['images'][target_name] = image_path
        image_upload_count += int(uploaded)
        results['host_summary'][target_name] = {
            'inside_count': inside_count,
            'host_count': len(host_rows),
            'host_candidates': [row.get('candidate_name') for row in host_rows],
            'analyzed_count': len(analyzed),
            'score': screen['score'],
            'tags': screen['tags'],
            'abs_mag': screen['flags'].get('abs_mag'),
            'host_status': screen['flags'].get('host_status'),
        }

        # ── host rule log ──────────────────────────────────────────────
        if host_rows:
            note = f" (chosen among {inside_count} z-consistent models)" if inside_count > 1 else ""
            print(f"[INFO] {target_name}: unique host = {host_rows[0].get('candidate_name')}{note}")
        elif inside_count > 1:
            print(f"[INFO] {target_name}: {inside_count} distinct galaxies contain the transient -> ambiguous, all is_host=False")
        else:
            print(f"[INFO] {target_name}: no cross-match candidate is inside ellipse")

        # ── confirm ALL rows (host + non-host) are queued ─────────────
        n_host     = len(host_rows)
        n_non_host = len(target_upload_rows) - n_host
        print(f"[INFO] {target_name}: queued {len(target_upload_rows)} row(s) for upload "
              f"(is_host=True: {n_host}, is_host=False: {n_non_host})")

    print(f"[INFO] Uploading {group_name} cross-match results and images to database...")
    try:
        if all_upload_rows:
            DataUploader.save_cross_match_results(all_upload_rows)
            print(f"[INFO] Uploaded {len(all_upload_rows)} {group_name} cross-match entries "
                  f"(all matches, regardless of is_host)")
        if screen_rows:
            n_screen = DataUploader.save_screen_results(screen_rows)
            print(f"[INFO] Uploaded {n_screen}/{len(screen_rows)} {group_name} screening rows (score + tags)")
        print(f"[INFO] Uploaded {image_upload_count} {group_name} image(s) to database")
        print(f"[SUCCESS] Uploaded {group_name} cross-match results to database\n")
    except Exception as e:
        print(f"[ERROR] Failed to upload {group_name} cross-match results: {type(e).__name__} - {e}\n")

    return results



if __name__ == "__main__":
    from function.data_source import daily_run_data

    print("=" * 60)
    print("Testing Cross-Match Pipeline with Daily Data")
    print("=" * 60)

    # Get daily data
    print("\n[INFO] Fetching daily data...")
    daily_data = daily_run_data(debug=True)

    # Run cross-match on TNS data
    if daily_data.get('tns'):
        print("\n" + "=" * 60)
        print("TNS Data Cross-Match")
        print("=" * 60)

        # Upload TNS objects to database first
        tns_csv_path = daily_data['tns']['path']
        objs_uploaded = _upload_tns_objects_directly(tns_csv_path)
        print()

        tns_results = run_cross_match_pipeline(daily_data['tns'], "TNS")
        print(f"TNS Cross-Match Results:")
        print(f"  - DESI matches: {sum(len(v) for v in tns_results['desi'].values())}")
        print(f"  - Lens matches: {sum(len(v) for v in tns_results['lens'].values())}")

    # Run cross-match on Follow-up data
    if daily_data.get('followup'):
        print("\n" + "=" * 60)
        print("Follow-up Data Cross-Match")
        print("=" * 60)
        fu_results = run_cross_match_pipeline(daily_data['followup'], "Follow-up")
        print(f"Follow-up Cross-Match Results:")
        print(f"  - DESI matches: {sum(len(v) for v in fu_results['desi'].values())}")
        print(f"  - Lens matches: {sum(len(v) for v in fu_results['lens'].values())}")

    print("\n" + "=" * 60)
    print("Cross-Match Pipeline Test Completed")
    print("=" * 60)
