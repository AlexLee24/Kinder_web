"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — finding_chart_render (split from astronomy_tools_routes.py)."""
import re
import io
import traceback
import base64
import numpy as np
import requests
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Polygon
from PIL import Image
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.vizier import Vizier


def _derotate_fits(raw, header):
    """Read WCS rotation from FITS header and rotate image to North-up.
    Returns (rotated_array, angle_degrees_applied)."""
    angle_applied = 0.0
    try:
        import warnings
        from astropy.wcs import WCS, FITSFixedWarning
        from scipy.ndimage import rotate as nd_rotate
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FITSFixedWarning)
            wcs = WCS(header, naxis=2)
        ny, nx = raw.shape
        cx, cy = nx / 2.0, ny / 2.0
        # In a numpy array from astropy FITS, row index increases = moving North
        # (FITS pixel y increases = Dec increases for standard WCS)
        c_ra, c_dec = wcs.all_pix2world([[cx, cy]], 0)[0]
        n_ra, n_dec = wcs.all_pix2world([[cx, cy + 1]], 0)[0]
        delta_ra_sky = (n_ra - c_ra) * np.cos(np.radians(c_dec))
        delta_dec    = n_dec - c_dec
        # Angle from "up" to North; positive = image rotated CW on sky
        angle = np.degrees(np.arctan2(delta_ra_sky, delta_dec))
        if abs(angle) > 0.05:
            fill_val = float(np.nanmedian(raw[np.isfinite(raw)]))
            # FLIP_TOP_BOTTOM (applied after) inverts chirality, so negate angle here
            raw = nd_rotate(raw, -angle, reshape=False, cval=fill_val, order=1)
            angle_applied = angle
    except Exception as exc:
        pass  # fallback: no rotation
    return raw, angle_applied

def _fits_to_png(fits_data_2d, fits_header=None, use_zscale=False):
    """Normalize a 2-D float FITS array and return a PIL RGB image (N-up).
    use_zscale=True: ZScale interval + asinh stretch (DESI single-band).
    use_zscale=False: simple percentile linear stretch (DSS).
    If fits_header is provided, de-rotate to North-up before normalization.
    Returns (PIL Image, angle_degrees_applied)."""
    data = fits_data_2d.astype(float)
    angle_applied = 0.0
    if fits_header is not None:
        data, angle_applied = _derotate_fits(data, fits_header)

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        out = np.zeros_like(data, dtype=np.uint8)
    elif use_zscale:
        try:
            from astropy.visualization import ZScaleInterval, AsinhStretch, ImageNormalize
            # contrast=0.35: moderate dynamic range; a=0.5: gentle non-linearity
            norm = ImageNormalize(finite, interval=ZScaleInterval(contrast=0.25),
                                  stretch=AsinhStretch(a=1.0))
            out = np.clip(norm(data) * 255, 0, 255).astype(np.uint8)
        except Exception:
            vmin = np.percentile(finite, 2.0)
            vmax = np.percentile(finite, 98.0)
            if vmax <= vmin:
                vmax = vmin + 1
            out = np.clip((data - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)
    else:
        # Linear stretch for DSS
        vmin = np.percentile(finite, 0.5)
        vmax = np.percentile(finite, 99.5)
        if vmax <= vmin:
            vmax = vmin + 1
        out = np.clip((data - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)

    img_pil = Image.fromarray(out, mode='L').convert('RGB')
    img_pil = img_pil.transpose(Image.FLIP_TOP_BOTTOM)  # FITS is South-up
    return img_pil, angle_applied

def _fetch_survey_image(survey, ra_deg, dec_deg, fov_arcmin):
    """Fetch cutout image bytes from the selected survey.
    Returns (bytes_or_None, list_of_log_strings)."""
    timeout = 45
    logs = []
    try:
        # ------------------------------------------------------------------ DSS
        if survey.startswith('DSS'):
            survey_map = {
                'DSS2 Red':  'poss2ukstu_red',
                'DSS2 Blue': 'poss2ukstu_blue',
                'DSS2 IR':   'poss2ukstu_ir',
                'DSS':       'poss1_red',
                'DSS1':      'poss1_red',
            }
            dss_name = survey_map.get(survey, 'poss2ukstu_red')
            url = (
                f'https://archive.stsci.edu/cgi-bin/dss_search'
                f'?v={dss_name}&r={ra_deg}&d={dec_deg}&e=J2000'
                f'&h={fov_arcmin}&w={fov_arcmin}&f=fits&c=gz&fov=NONE&v3='
            )
            logs.append(f'[DSS] GET {url[:80]}...')
            r = requests.get(url, timeout=timeout)
            logs.append(f'[DSS] HTTP {r.status_code}  size={len(r.content)} bytes')
            if r.status_code == 200:
                import gzip
                from astropy.io import fits as afits
                try:
                    fits_raw = gzip.decompress(r.content)
                except Exception:
                    fits_raw = r.content
                hdu = afits.open(io.BytesIO(fits_raw))
                img_pil, rot_ang = _fits_to_png(hdu[0].data, fits_header=hdu[0].header, use_zscale=False)
                logs.append(f'[DSS] WCS de-rotation applied: {rot_ang:.3f} deg')
                buf = io.BytesIO()
                img_pil.save(buf, format='PNG')
                return buf.getvalue(), logs
            logs.append(f'[DSS] ERROR: non-200 response')
            return None, logs

        # --------------------------------------------------------------- DESI LS
        elif survey.startswith('DESI'):
            layer = 'ls-dr10'
            pixscale = fov_arcmin * 60 / 900  # arcsec/pixel for 900 px
            if 'color' in survey:
                url = (
                    f'https://www.legacysurvey.org/viewer/cutout.jpg'
                    f'?ra={ra_deg}&dec={dec_deg}&size=900&layer={layer}&pixscale={pixscale:.4f}'
                )
                logs.append(f'[DESI] GET color JPG  pixscale={pixscale:.4f}"')
                r = requests.get(url, timeout=timeout)
                logs.append(f'[DESI] HTTP {r.status_code}  size={len(r.content)} bytes')
                return (r.content if r.status_code == 200 else None), logs
            else:
                band = survey.split('-')[-1].lower()
                url = (
                    f'https://www.legacysurvey.org/viewer/cutout.fits'
                    f'?ra={ra_deg}&dec={dec_deg}&size=900&layer={layer}'
                    f'&pixscale={pixscale:.4f}&bands={band}'
                )
                logs.append(f'[DESI] GET {band}-band FITS  pixscale={pixscale:.4f}"')
                r = requests.get(url, timeout=timeout)
                logs.append(f'[DESI] HTTP {r.status_code}  size={len(r.content)} bytes')
                if r.status_code == 200:
                    from astropy.io import fits as afits
                    hdu = afits.open(io.BytesIO(r.content))
                    raw = hdu[0].data
                    if raw.ndim == 3:
                        raw = raw[0]
                    img_pil, rot_ang = _fits_to_png(raw, fits_header=hdu[0].header, use_zscale=True)
                    logs.append(f'[DESI] WCS de-rotation applied: {rot_ang:.3f} deg')
                    buf = io.BytesIO()
                    img_pil.save(buf, format='PNG')
                    return buf.getvalue(), logs
                logs.append('[DESI] ERROR: non-200 response')
                return None, logs

        # ------------------------------------------------------------------ PS1
        elif survey.startswith('PS1'):
            size_px = 900
            # PS1 native resolution is 0.25"/pixel; size param in fitscut.cgi is native pixels
            src_px = max(240, int(fov_arcmin * 60 / 0.25))
            if 'color' in survey:
                filters = 'gri'
            else:
                filters = survey.split('-')[-1].lower()

            # Step 1: resolve actual image filenames
            fn_url = (
                f'https://ps1images.stsci.edu/cgi-bin/ps1filenames.py'
                f'?ra={ra_deg}&dec={dec_deg}&filters={filters}&type=stack'
            )
            logs.append(f'[PS1] Querying filenames: filters={filters}')
            fr = requests.get(fn_url, timeout=timeout)
            logs.append(f'[PS1] Filenames HTTP {fr.status_code}')
            if fr.status_code != 200 or not fr.text.strip():
                logs.append('[PS1] ERROR: filenames query failed')
                return None, logs

            lines = [l for l in fr.text.strip().split('\n') if l.strip()]
            if len(lines) < 2:
                logs.append('[PS1] ERROR: no images found at this position (outside PS1 footprint?)')
                return None, logs

            header = lines[0].split()
            rows = []
            for l in lines[1:]:
                parts = l.split()
                if len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))
            if not rows:
                logs.append('[PS1] ERROR: empty filename table')
                return None, logs

            file_map = {row.get('filter', ''): row.get('filename', '') for row in rows}
            logs.append(f'[PS1] Available bands: {list(file_map.keys())}')

            if 'color' in survey:
                r_f = file_map.get('r', file_map.get('i', ''))
                g_f = file_map.get('i', file_map.get('r', ''))
                b_f = file_map.get('g', '')
                if not all([r_f, g_f, b_f]):
                    logs.append(f'[PS1] ERROR: missing bands for color — {file_map}')
                    return None, logs
                cut_url = (
                    f'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
                    f'?ra={ra_deg}&dec={dec_deg}&size={src_px}&format=jpg'
                    f'&output_size={size_px}&red={r_f}&green={g_f}&blue={b_f}'
                )
                logs.append('[PS1] Fetching color cutout (JPG)')
                cr = requests.get(cut_url, timeout=timeout)
                logs.append(f'[PS1] Cutout HTTP {cr.status_code}  size={len(cr.content)} bytes')
                return (cr.content if cr.status_code == 200 else None), logs
            else:
                fname = file_map.get(filters, '')
                if not fname:
                    logs.append(f'[PS1] ERROR: band {filters} not available')
                    return None, logs
                cut_url = (
                    f'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
                    f'?ra={ra_deg}&dec={dec_deg}&size={src_px}&format=jpg'
                    f'&output_size={size_px}&red={fname}'
                )
                logs.append(f'[PS1] Fetching {filters}-band cutout (JPG, as grayscale red channel)')
                cr = requests.get(cut_url, timeout=timeout)
                logs.append(f'[PS1] Cutout HTTP {cr.status_code}  size={len(cr.content)} bytes')
                return (cr.content if cr.status_code == 200 else None), logs

        logs.append(f'[ERROR] Unknown survey: {survey}')
        return None, logs
    except Exception as e:
        traceback.print_exc()
        logs.append(f'[ERROR] Exception: {e}')
        return None, logs

def _fetch_survey_fits(survey, ra_deg, dec_deg, fov_arcmin):
    """Fetch raw FITS bytes for selected survey/FOV. Returns (bytes_or_None, logs)."""
    timeout = 45
    logs = []
    try:
        if survey.startswith('DSS'):
            survey_map = {
                'DSS2 Red': 'poss2ukstu_red',
                'DSS2 Blue': 'poss2ukstu_blue',
                'DSS2 IR': 'poss2ukstu_ir',
                'DSS': 'poss1_red',
                'DSS1': 'poss1_red',
            }
            dss_name = survey_map.get(survey, 'poss2ukstu_red')
            url = (
                f'https://archive.stsci.edu/cgi-bin/dss_search'
                f'?v={dss_name}&r={ra_deg}&d={dec_deg}&e=J2000'
                f'&h={fov_arcmin}&w={fov_arcmin}&f=fits&c=gz&fov=NONE&v3='
            )
            logs.append(f'[DSS] GET FITS {url[:80]}...')
            r = requests.get(url, timeout=timeout)
            logs.append(f'[DSS] HTTP {r.status_code}  size={len(r.content)} bytes')
            if r.status_code != 200:
                return None, logs
            import gzip
            try:
                return gzip.decompress(r.content), logs
            except Exception:
                return r.content, logs

        if survey.startswith('DESI'):
            layer = 'ls-dr10'
            pixscale = fov_arcmin * 60 / 900
            band = survey.split('-')[-1].lower() if '-' in survey else 'grz'
            bands = 'grz' if band == 'color' else band
            url = (
                f'https://www.legacysurvey.org/viewer/cutout.fits'
                f'?ra={ra_deg}&dec={dec_deg}&size=900&layer={layer}'
                f'&pixscale={pixscale:.4f}&bands={bands}'
            )
            logs.append(f'[DESI] GET FITS bands={bands} pixscale={pixscale:.4f}"')
            r = requests.get(url, timeout=timeout)
            logs.append(f'[DESI] HTTP {r.status_code}  size={len(r.content)} bytes')
            return (r.content if r.status_code == 200 else None), logs

        if survey.startswith('PS1'):
            size_px = 900
            src_px = max(240, int(fov_arcmin * 60 / 0.25))
            req_filter = 'r' if 'color' in survey else survey.split('-')[-1].lower()

            fn_url = (
                f'https://ps1images.stsci.edu/cgi-bin/ps1filenames.py'
                f'?ra={ra_deg}&dec={dec_deg}&filters={req_filter}&type=stack'
            )
            logs.append(f'[PS1] Querying filenames: filters={req_filter}')
            fr = requests.get(fn_url, timeout=timeout)
            logs.append(f'[PS1] Filenames HTTP {fr.status_code}')
            if fr.status_code != 200 or not fr.text.strip():
                return None, logs

            lines = [l for l in fr.text.strip().split('\n') if l.strip()]
            if len(lines) < 2:
                return None, logs
            header = lines[0].split()
            rows = []
            for line in lines[1:]:
                parts = line.split()
                if len(parts) == len(header):
                    rows.append(dict(zip(header, parts)))
            if not rows:
                return None, logs
            file_map = {row.get('filter', ''): row.get('filename', '') for row in rows}
            fname = file_map.get(req_filter, '')
            if not fname:
                return None, logs

            cut_url = (
                f'https://ps1images.stsci.edu/cgi-bin/fitscut.cgi'
                f'?ra={ra_deg}&dec={dec_deg}&size={src_px}&format=fits'
                f'&output_size={size_px}&red={fname}'
            )
            logs.append(f'[PS1] Fetching {req_filter}-band FITS cutout')
            cr = requests.get(cut_url, timeout=timeout)
            logs.append(f'[PS1] Cutout HTTP {cr.status_code}  size={len(cr.content)} bytes')
            return (cr.content if cr.status_code == 200 else None), logs

        logs.append(f'[ERROR] Unknown survey: {survey}')
        return None, logs
    except Exception as e:
        traceback.print_exc()
        logs.append(f'[ERROR] Exception: {e}')
        return None, logs

def _query_nearby_stars(ra_deg, dec_deg, fov_arcmin, mag_limit):
    """Multi-catalog star query: Tycho-2 (bright) + UCAC4 (faint) + SIMBAD names.
    Returns (stars_list, dominant_band_str, logs_list)."""
    logs = []
    stars = {}  # key: (ra4, dec4) for spatial dedup
    coord  = SkyCoord(ra_deg, dec_deg, unit='deg')
    radius = (fov_arcmin / 2) * u.arcmin

    # ── 1. Tycho-2: complete to V~11.5, good for bright/saturated stars ──────
    try:
        tyc_lim = min(mag_limit, 13.0)
        logs.append(f'[Vizier] Querying Tycho-2  mag<{tyc_lim}  r={fov_arcmin/2:.1f}\'')
        v_tyc = Vizier(
            columns=['RAmdeg', 'DEmdeg', 'VTmag', 'BTmag', 'TYC1', 'TYC2', 'TYC3', 'HIP'],
            column_filters={'VTmag': f'<{tyc_lim}'},
            row_limit=400)
        res = v_tyc.query_region(coord, radius=radius, catalog='I/259/tyc2')
        n_tyc = 0
        if res and len(res) > 0:
            tbl  = res[0]
            cols = tbl.colnames
            for row in tbl:
                try:
                    vt = float(row['VTmag']) if 'VTmag' in cols else np.nan
                    bt = float(row['BTmag']) if 'BTmag' in cols else np.nan
                    if not np.isfinite(vt):
                        continue
                    # Standard Tycho → Johnson V: V = VT − 0.090*(BT−VT)
                    if np.isfinite(bt):
                        mag  = round(vt - 0.090 * (bt - vt), 2)
                        band = 'V'
                    else:
                        mag  = round(vt, 2)
                        band = 'VT'
                    if mag >= mag_limit:
                        continue
                    ra_s  = float(row['RAmdeg'])
                    dec_s = float(row['DEmdeg'])
                    try:
                        _hip_raw = row['HIP'] if 'HIP' in cols else None
                        if _hip_raw is None or np.ma.is_masked(_hip_raw):
                            hip_val = np.nan
                        else:
                            hip_val = float(_hip_raw)
                        hip = str(int(hip_val)) if np.isfinite(hip_val) else ''
                    except Exception:
                        hip = ''
                    tyc_id = (f"TYC {row['TYC1']}-{row['TYC2']}-{row['TYC3']}"
                              if 'TYC1' in cols else '')
                    star_id = f'HIP {hip}' if hip else tyc_id
                    key = (round(ra_s, 4), round(dec_s, 4))
                    stars[key] = {'ra': ra_s, 'dec': dec_s, 'mag': mag,
                                  'band': band, 'id': star_id, 'name': ''}
                    n_tyc += 1
                except Exception:
                    continue
        logs.append(f'[Vizier] Tycho-2 found {n_tyc} stars')
    except Exception as e:
        logs.append(f'[Vizier] Tycho-2 ERROR: {e}')

    # ── 2. UCAC4: adds faint stars not covered by Tycho-2 ───────────────────
    PRIORITY   = [('V', 'Vmag'), ('r', 'rmag'), ('R', 'f.mag')]
    tycho_snap = list(stars.values())   # snapshot before UCAC4 loop
    n_ucac     = 0
    try:
        logs.append(f'[Vizier] Querying UCAC4  mag<{mag_limit}  r={fov_arcmin/2:.1f}\'')
        v_uc = Vizier(columns=['RAJ2000', 'DEJ2000', 'Vmag', 'rmag', 'f.mag', 'UCAC4'],
                      row_limit=500)
        res_uc = v_uc.query_region(coord, radius=radius, catalog='I/322A')
        if res_uc and len(res_uc) > 0:
            tbl   = res_uc[0]
            acols = tbl.colnames
            for row in tbl:
                try:
                    chosen_mag, chosen_label = None, None
                    for label, col in PRIORITY:
                        if col in acols:
                            try:
                                raw = row[col]
                                # Skip masked / None values before float()
                                if hasattr(raw, '_fill_value') or raw is None:
                                    continue
                                val = float(raw)
                                if np.isfinite(val) and val < mag_limit:
                                    chosen_mag = round(val, 2)
                                    chosen_label = label
                                    break
                            except (ValueError, TypeError):
                                continue
                    if chosen_mag is None:
                        continue
                    ra_s  = float(row['RAJ2000'])
                    dec_s = float(row['DEJ2000'])
                    cos_d = np.cos(np.radians(dec_s))
                    # Skip if within 3" of any Tycho-2 star (already covered)
                    matched = any(
                        ((ra_s - ev['ra']) * cos_d)**2 + (dec_s - ev['dec'])**2 < (3/3600)**2
                        for ev in tycho_snap
                    )
                    if not matched:
                        key = (round(ra_s, 4), round(dec_s, 4))
                        stars[key] = {
                            'ra': ra_s, 'dec': dec_s,
                            'mag': chosen_mag, 'band': chosen_label,
                            'id': str(row['UCAC4']) if 'UCAC4' in acols else '',
                            'name': '',
                        }
                        n_ucac += 1
                except Exception:
                    continue
        logs.append(f'[Vizier] UCAC4 added {n_ucac}  total={len(stars)}')
    except Exception as e:
        logs.append(f'[Vizier] UCAC4 ERROR: {e}')

    # ── 3. SIMBAD: fetch common names for matched stars ──────────────────────
    try:
        from astroquery.simbad import Simbad
        sim = Simbad()
        sim.TIMEOUT = 25
        logs.append(f'[SIMBAD] Querying names  r={fov_arcmin/2:.1f}\'')
        sim_res = sim.query_region(coord, radius=radius)
        if sim_res is not None and len(sim_res) > 0:
            n_named = 0
            star_list_snap = list(stars.items())
            for row in sim_res:
                try:
                    sc = SkyCoord(ra=str(row['RA']), dec=str(row['DEC']),
                                  unit=(u.hourangle, u.deg))
                    s_ra, s_dec = sc.ra.deg, sc.dec.deg
                except Exception:
                    continue
                main_id = str(row['MAIN_ID']).strip()
                # Clean prefixes: "* ", "V* ", "** " → Bayer/Flamsteed/proper name
                clean = re.sub(r'^(V\*|\*\*|\*)\s*', '', main_id).strip()
                if not clean:
                    clean = main_id
                cos_d = np.cos(np.radians(s_dec))
                best_key, best_d2 = None, (5 / 3600) ** 2   # 5" threshold
                for k, sv in star_list_snap:
                    d2 = ((sv['ra'] - s_ra) * cos_d)**2 + (sv['dec'] - s_dec)**2
                    if d2 < best_d2:
                        best_d2, best_key = d2, k
                if best_key is not None:
                    stars[best_key]['name'] = clean
                    n_named += 1
            logs.append(f'[SIMBAD] Named {n_named} stars')
    except Exception as e:
        logs.append(f'[SIMBAD] WARN: {e}')

    star_list   = list(stars.values())
    band_counts = {}
    for s in star_list:
        band_counts[s['band']] = band_counts.get(s['band'], 0) + 1
    dominant = max(band_counts, key=band_counts.get) if band_counts else 'V'
    logs.append(f'[Stars] Total {len(star_list)}  bands={band_counts}')
    return star_list, dominant, logs

def _render_finding_chart(img, ra_deg, dec_deg, fov_arcmin, target_name,
                          star_data, mag_band, mag_limit, name_limit, invert, survey,
                          show_mag=True, show_names=True, max_stars=None,
                          show_slit=False, slit_length=20.0, slit_width=1.5, slit_pa=0.0):
    """Render the finding chart with matplotlib and return base64 PNG."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=120)

    # Determine color scheme based on invert
    is_single_filter = survey not in ['DESI-color', 'PS1-color']
    if invert and is_single_filter:
        marker_color = 'red'
        text_color = 'black'
        star_color = 'blue'
        crosshair_color = 'red'
        compass_color = 'black'
    else:
        marker_color = '#00FF00'
        text_color = 'white'
        star_color = '#FFD700'
        crosshair_color = '#00FF00'
        compass_color = 'white'

    # cos(dec) correction: on sky, 1 arcmin in RA = 1/cos(dec) degrees
    cos_dec = np.cos(np.radians(dec_deg))
    cos_dec = max(cos_dec, 1e-6)  # guard near poles

    # Display image
    # The survey returns a square image (fov_arcmin x fov_arcmin on sky).
    # In RA/Dec degree space, the RA width = fov / cos(dec) because
    # 1 sky-arcmin in RA = (1/cos(dec)) degree of RA.
    half_fov_dec = fov_arcmin / 2.0 / 60.0          # degrees in Dec
    half_fov_ra  = half_fov_dec / cos_dec            # degrees in RA
    extent = [ra_deg + half_fov_ra, ra_deg - half_fov_ra,
              dec_deg - half_fov_dec, dec_deg + half_fov_dec]
    ax.imshow(img, extent=extent, aspect='auto', origin='upper')
    # Set aspect so the sky image appears square on screen
    ax.set_aspect(1.0 / cos_dec)

    # Helper: sky_arcfrac -> RA-degree offset and Dec-degree offset
    # e.g. sky_frac(0.06) = 6% of fov in sky angular units
    def ra_off(sky_frac):
        return fov_arcmin / 60.0 * sky_frac / cos_dec

    def dec_off(sky_frac):
        return fov_arcmin / 60.0 * sky_frac

    # Crosshair on target
    ch_len = dec_off(0.06)
    ch_gap = dec_off(0.015)
    ra_ch_len = ra_off(0.06)
    ra_ch_gap = ra_off(0.015)
    ax.plot([ra_deg - ra_ch_gap, ra_deg - ra_ch_len], [dec_deg, dec_deg], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg + ra_ch_gap, ra_deg + ra_ch_len], [dec_deg, dec_deg], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg, ra_deg], [dec_deg - ch_gap, dec_deg - ch_len], '-', color=crosshair_color, lw=1.5)
    ax.plot([ra_deg, ra_deg], [dec_deg + ch_gap, dec_deg + ch_len], '-', color=crosshair_color, lw=1.5)

    # Circle around target (Ellipse because RA/Dec axes have different scales)
    circle_sky = dec_off(0.035)  # radius in sky degrees
    ell = Ellipse((ra_deg, dec_deg),
                  width=circle_sky / cos_dec * 2,
                  height=circle_sky * 2,
                  fill=False, edgecolor=crosshair_color, lw=1.5, ls='--')
    ax.add_patch(ell)

    # Target name label
    offset_dec = dec_off(0.05)
    ax.text(ra_deg, dec_deg + offset_dec, target_name,
            color=marker_color, fontsize=11, fontweight='bold',
            ha='center', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='black' if not invert else 'white',
                      alpha=0.6, edgecolor='none'))

    # Plot nearby stars
    # --- Slit overlay ---
    if show_slit:
        slit_color = '#FF6600' if not (invert and is_single_filter) else '#CC4400'
        pa_rad = np.radians(slit_pa)
        # Half dimensions in sky angular degrees
        hl = slit_length / 2.0 / 3600.0    # half-length
        hw = slit_width  / 2.0 / 3600.0    # half-width
        # Slit long-axis unit vector in (East_sky, North_sky):
        #   East = sin(PA), North = cos(PA)
        # Slit perp unit vector: (cos(PA), -sin(PA))
        sin_pa, cos_pa = np.sin(pa_rad), np.cos(pa_rad)
        # 4 corners in (East_sky_deg, North_sky_deg)
        corners_sky = [
            ( hl*sin_pa + hw*cos_pa,  hl*cos_pa - hw*sin_pa),
            ( hl*sin_pa - hw*cos_pa,  hl*cos_pa + hw*sin_pa),
            (-hl*sin_pa - hw*cos_pa, -hl*cos_pa + hw*sin_pa),
            (-hl*sin_pa + hw*cos_pa, -hl*cos_pa - hw*sin_pa),
        ]
        # Convert to RA/Dec: East offset / cos_dec = RA offset
        corners_radec = np.array(
            [(ra_deg + e / cos_dec, dec_deg + n) for e, n in corners_sky]
        )
        slit_poly = Polygon(corners_radec, closed=True, linewidth=2.0,
                            edgecolor=slit_color, facecolor=slit_color,
                            alpha=0.18, transform=ax.transData)
        ax.add_patch(slit_poly)
        slit_border = Polygon(corners_radec, closed=True, linewidth=2.0,
                              edgecolor=slit_color, facecolor='none',
                              transform=ax.transData)
        ax.add_patch(slit_border)
        # Center line along slit long axis
        ax.plot(
            [ra_deg - hl*sin_pa/cos_dec, ra_deg + hl*sin_pa/cos_dec],
            [dec_deg - hl*cos_pa,        dec_deg + hl*cos_pa],
            '-', color=slit_color, lw=0.8, alpha=0.7
        )
        # PA label near top of slit
        label_ra  = ra_deg + (hl + dec_off(0.04)) * sin_pa / cos_dec
        label_dec = dec_deg + (hl + dec_off(0.04)) * cos_pa
        ax.text(label_ra, label_dec,
                f'PA={slit_pa:.1f}°\n{slit_width}"×{slit_length}"',
                color=slit_color, fontsize=8, fontweight='bold',
                ha='center', va='bottom',
                bbox=dict(boxstyle='round,pad=0.18',
                          facecolor='black' if not (invert and is_single_filter) else 'white',
                          alpha=0.55, edgecolor='none'))

    visible_stars = sorted(star_data, key=lambda s: s['mag'])
    if max_stars is not None:
        visible_stars = visible_stars[:max_stars]

    for star in visible_stars:
        s_ra, s_dec, s_mag = star['ra'], star['dec'], star['mag']
        # Skip if too close to target (< 3 arcsec on sky)
        sep = np.sqrt(((s_ra - ra_deg) * cos_dec)**2 + (s_dec - dec_deg)**2) * 3600
        if sep < 3:
            continue

        # Star marker — skip if no annotation is shown at all
        if show_mag or show_names:
            msize = max(2, min(8, (mag_limit - s_mag) * 0.8))
            ax.plot(s_ra, s_dec, 'o', color=star_color, markersize=msize,
                    markerfacecolor='none', markeredgewidth=0.8)

        label_offset_ra  = ra_off(0.014)
        label_offset_dec = dec_off(0.014)
        band_label = star.get('band', '')

        # Magnitude label
        if show_mag:
            ax.text(s_ra + label_offset_ra, s_dec + label_offset_dec,
                    f"{s_mag:.1f}({band_label})",
                    color=star_color, fontsize=9, fontweight='semibold', alpha=0.95,
                    ha='left', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.12',
                              facecolor='black' if not (invert and is_single_filter) else 'white',
                              alpha=0.4, edgecolor='none'))

        # Name label for bright stars — prefer SIMBAD name, fall back to catalog id
        if show_names and s_mag < name_limit:
            display_name = star.get('name') or star.get('id', '')
            if display_name:
                ax.text(s_ra + label_offset_ra, s_dec - label_offset_dec,
                        display_name, color=text_color, fontsize=7.5, alpha=0.8,
                        ha='left', va='top')

    # Compass (N/E arrows) in top-left corner
    cx = extent[0] - ra_off(0.08)
    cy = extent[3] - dec_off(0.08)
    arrow_len_dec = dec_off(0.08)
    arrow_len_ra  = ra_off(0.08)
    # N arrow (up in Dec)
    ax.annotate('', xy=(cx, cy + arrow_len_dec), xytext=(cx, cy),
                arrowprops=dict(arrowstyle='->', color=compass_color, lw=1.5))
    ax.text(cx, cy + arrow_len_dec * 1.15, 'N', color=compass_color, fontsize=9,
            fontweight='bold', ha='center', va='bottom')
    # E arrow (increasing RA to the right visually since extent is RA-decreasing left)
    ax.annotate('', xy=(cx + arrow_len_ra, cy), xytext=(cx, cy),
                arrowprops=dict(arrowstyle='->', color=compass_color, lw=1.5))
    ax.text(cx + arrow_len_ra * 1.15, cy, 'E', color=compass_color, fontsize=9,
            fontweight='bold', ha='left', va='center')

    # Scale bar in bottom-left (angular scale, shown in Dec-direction length)
    scale_len_arcmin = _nice_scale_bar(fov_arcmin)
    scale_len_deg = scale_len_arcmin / 60.0 / cos_dec  # RA-direction length
    bar_x = extent[1] + ra_off(0.08)
    bar_y = extent[2] + dec_off(0.06)
    tick_h = dec_off(0.008)
    ax.plot([bar_x, bar_x + scale_len_deg], [bar_y, bar_y], '-', color=compass_color, lw=2)
    ax.plot([bar_x, bar_x], [bar_y - tick_h, bar_y + tick_h], '-', color=compass_color, lw=1.5)
    ax.plot([bar_x + scale_len_deg, bar_x + scale_len_deg], [bar_y - tick_h, bar_y + tick_h],
            '-', color=compass_color, lw=1.5)
    scale_text = f"{scale_len_arcmin:.0f}'" if scale_len_arcmin >= 1 else f'{scale_len_arcmin * 60:.0f}"'
    ax.text(bar_x + scale_len_deg / 2, bar_y + dec_off(0.015),
            scale_text, color=compass_color, fontsize=8, ha='center', va='bottom')

    # Info text in top-right
    coord_sc = SkyCoord(ra_deg, dec_deg, unit='deg')
    ra_hms = coord_sc.ra.to_string(u.hour, sep=':', precision=2)
    dec_dms = coord_sc.dec.to_string(u.deg, sep=':', precision=1, alwayssign=True)
    info_lines = [
        f'RA: {ra_hms}  Dec: {dec_dms}',
        f"FOV: {fov_arcmin:.1f}'  Survey: {survey}",
    ]
    info_x = extent[1] + ra_off(0.03)
    info_y = extent[3] - dec_off(0.03)
    for i, line in enumerate(info_lines):
        ax.text(info_x, info_y - i * fov_arcmin / 60.0 * 0.035, line,
                color=text_color, fontsize=7.5,
                ha='left', va='top', family='monospace',
                bbox=dict(boxstyle='round,pad=0.15',
                          facecolor='black' if not invert else 'white',
                          alpha=0.5, edgecolor='none'))

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel('RA [deg]', fontsize=9, color='gray')
    ax.set_ylabel('Dec [deg]', fontsize=9, color='gray')
    ax.tick_params(labelsize=7, colors='gray')

    # Suppress scientific notation; auto decimal places based on axis range
    import math
    from matplotlib.ticker import FuncFormatter
    def _adaptive_fmt(rng):
        # e.g. rng=0.5° → 4 dp, rng=5° → 3 dp, rng=0.05° → 5 dp
        n = max(1, int(math.ceil(-math.log10(max(rng, 1e-9)))) + 2)
        return FuncFormatter(lambda v, _: f'{v:.{n}f}')
    ax.xaxis.set_major_formatter(_adaptive_fmt(abs(extent[1] - extent[0])))
    ax.yaxis.set_major_formatter(_adaptive_fmt(abs(extent[3] - extent[2])))

    fig.patch.set_facecolor('black' if not (invert and is_single_filter) else '#f5f5f5')
    ax.set_facecolor('black' if not (invert and is_single_filter) else '#f5f5f5')
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

def _nice_scale_bar(fov_arcmin):
    """Pick a nice round scale bar length."""
    target = fov_arcmin * 0.2
    nice_values = [0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 15, 20, 30, 60]
    for v in nice_values:
        if v >= target * 0.5:
            return v
    return nice_values[-1]
