"""Per-object light-curve download for Kinder (app/services/photometry).

process_single_object_workflow(name) reads the object's coordinates and internal names,
downloads its light curve from public services, bins it to one point per filter, site and
night, and stores it in transient.photometry:

* ZTF  — ALeRCE (alerce.core.Alerce, survey="ztf")
* LSST — ALeRCE (survey="lsst"); fluxes in nJy -> AB mag
* TNS discovery magnitude, only when the object has no survey name we can query

Credentials (TNS bot) come from kinder.env through app.config; nothing is stored here.
The ATLAS and Pan-STARRS (QUB) downloaders live in the git-ignored download_phot_backup.py.
"""
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from alerce.core import Alerce
from astropy.time import Time as astime
from tqdm import tqdm

from app.config import config  # noqa: F401  -- loads kinder.env (single place)
from app.db import get_db_connection
from app.db.transient import TNSObjectDB
from app.paths import PHOT_CACHE_DIR

logger = logging.getLogger(__name__)

TNS_API_URL = "https://www.wis-tns.org/api/get/object"
HTTP_TIMEOUT = 30  # seconds, every outgoing request

# Shared ALeRCE client (lazy singleton) — used for both ZTF and LSST light curves.
_alerce_client = None


def _get_alerce_client() -> Alerce:
    global _alerce_client
    if _alerce_client is None:
        _alerce_client = Alerce()
    return _alerce_client


def _tns_request(object_name: str) -> dict | None:
    """TNS get/object for one name (no photometry / spectra); the reply's ``data`` or None.

    TNS identifies a bot by this User-Agent marker; its id, name and API key come from
    kinder.env (TNS_BOT_ID, TNS_BOT_NAME, TNS_API_KEY).
    """
    import os
    bot_id, bot_name, api_key = os.getenv("TNS_BOT_ID"), os.getenv("TNS_BOT_NAME"), os.getenv("TNS_API_KEY")
    if not (bot_id and bot_name and api_key):
        logger.error('TNS bot settings (TNS_BOT_ID / TNS_BOT_NAME / TNS_API_KEY) missing in kinder.env')
        return None
    headers = {"User-Agent": f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'}
    payload = {"api_key": api_key,
               "data": json.dumps({"objname": object_name, "photometry": "0", "spectra": "0"})}
    try:
        response = requests.post(TNS_API_URL, headers=headers, data=payload, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        logger.error('TNS request for %s failed: %s', object_name, e)
        return None
    if response.status_code != 200:
        logger.error('TNS request for %s: HTTP %d', object_name, response.status_code)
        return None
    try:
        reply = response.json()
    except ValueError:
        logger.error('TNS request for %s: reply is not JSON', object_name)
        return None
    if reply.get("id_code") not in (None, 200):
        logger.error('TNS API error for %s: %s', object_name, reply.get('id_message'))
        return None
    return reply.get("data") or {}


def init_photometry_file(object_name: str, ra: float, dec: float, output_dir: str):
    output_dir = Path(output_dir)
    year = object_name[0:4]
    output_dir_year = output_dir / f"{year}"
    output_dir_year.mkdir(parents=True, exist_ok=True)
    output_file = output_dir_year / f"{object_name}_photometry.txt"

    try:
        if output_file.exists():
            logger.info('Photometry file already exists for %s', object_name)
            return True

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Object: {object_name}\n")
            f.write(f"# RA: {ra}\n")
            f.write(f"# DEC: {dec}\n")
            f.write("# MJD Mag Mag_err Filter Site\n")
        logger.info('Initialized photometry file for %s', object_name)
        return True
    except Exception as e:
        logger.error('Error initializing photometry file for %s: %s', object_name, e)
        return False


def write_photometry_to_txt(object_name: str, lines: list[str], output_dir: str):
    output_dir = Path(output_dir)
    year = object_name[0:4]
    output_dir_year = output_dir / f"{year}"
    output_dir_year.mkdir(parents=True, exist_ok=True)
    output_file = output_dir_year / f"{object_name}_photometry.txt"

    try:
        existing_lines = set()

        if output_file.exists():
            with open(output_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()
                    if not line_stripped.startswith('#'):
                        existing_lines.add(line_stripped)

        new_lines = [line for line in lines if line.strip() and line.strip() not in existing_lines]

        if new_lines:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
        return True
    except Exception as e:
        logger.error('Error writing photometry for %s: %s', object_name, e)
        return False

def get_discover_mag_from_TNS(object_name: str, output_dir: str):
    """Write the TNS discovery magnitude as the object's only point (no survey name to query)."""
    data = _tns_request(object_name)
    if not data:
        logger.warning('No TNS data for %s', object_name)
        return False
    try:
        discovery_mag = data.get('discoverymag')
        discovery_date = data.get('discoverydate')
        discovery_filter_obj = data.get('discmagfilter')

        discovery_filter = "Unknown"
        discovery_site = "TNS_Discovery"

        if isinstance(discovery_filter_obj, dict):
            discovery_filter = discovery_filter_obj.get('name', 'Unknown')
            family = discovery_filter_obj.get('family')
            if family:
                discovery_site = f"{family}(TNS)"
        elif isinstance(discovery_filter_obj, str):
            discovery_filter = discovery_filter_obj

        if discovery_mag is not None and discovery_date:
            discovery_MJD = astime(discovery_date).mjd
            line = [f"{discovery_MJD} {discovery_mag} 0.01 {discovery_filter} {discovery_site}"]
            write_photometry_to_txt(object_name, line, output_dir)
            return True

        logger.warning('Missing discovery info for %s', object_name)
        return False

    except Exception as e:
        logger.error('Error reading the TNS discovery mag of %s: %s', object_name, e)
        return False


def get_ztf_photometry(name_list: list[str], output_dir: str = "./data/photometry"):
    """
    Fetch ZTF photometry via the ALeRCE Python client (alerce.core.Alerce).

        client.query_lightcurve(ztf_oid, survey="ztf")
        -> {"detections": [...], "non_detections": [...]}

    detections carry magpsf/sigmapsf/fid/mjd; non_detections carry diffmaglim/fid/mjd.
    fid mapping: 1=g, 2=r, 3=i
    """
    FID_MAP = {1: "g", 2: "r", 3: "i"}
    client = _get_alerce_client()

    for name_pair in tqdm(name_list, desc="ZTF (ALeRCE): Fetching photometry"):
        parts = name_pair.split()
        object_name = parts[0]
        ztf_name = parts[1]

        logger.info('Fetching ZTF photometry for %s (%s) via ALeRCE...', object_name, ztf_name)

        try:
            lc = client.query_lightcurve(ztf_name, survey="ztf")
            detections = lc.get("detections", []) or []
            non_detections = lc.get("non_detections", []) or []

            photometry_list = []
            det_mjds = []
            for det in detections:
                mjd = det.get("mjd")
                mag = det.get("magpsf")
                dmag = det.get("sigmapsf")
                fid = det.get("fid")
                filt = FID_MAP.get(fid, f"ZTF{fid}")

                if mjd is None or mag is None or dmag is None:
                    continue

                det_mjds.append(mjd)
                photometry_list.append(f"{mjd} {mag} {dmag} {filt} ZTF(alerce)")

            # Fetch non-detections within 5 days of any detection
            if det_mjds:
                det_mjds_arr = np.array(det_mjds)
                for nd in non_detections:
                    mjd = nd.get("mjd")
                    diffmaglim = nd.get("diffmaglim")
                    fid = nd.get("fid")
                    filt = FID_MAP.get(fid, f"ZTF{fid}")

                    if mjd is None or diffmaglim is None:
                        continue

                    # Check if within 5 days of any detection
                    if np.min(np.abs(det_mjds_arr - mjd)) <= 5:
                        # Use 0.0 error to signify limit
                        photometry_list.append(f"{mjd} {diffmaglim} 0.0 {filt} ZTF(alerce)")

            write_photometry_to_txt(object_name, photometry_list, output_dir)
            logger.info('Saved %d ZTF photometry points for %s', len(photometry_list), object_name)

        except Exception as e:
            logger.error('Error fetching ZTF photometry for %s (%s): %s', object_name, ztf_name, e)

    return True, None

def get_lsst_alerce_photometry(name_list: list[str], output_dir: str = "./data/photometry"):
    """
    Fetch LSST/Rubin photometry via the ALeRCE Python client (alerce.core.Alerce).

        client.query_lightcurve(oid, survey="lsst")
        -> {"detections": [...], "non_detections": [...], "forced_photometry": [...]}

    name_list: list of "{iau_name} {lsst_internal_name}" strings
               e.g. "2026nbd LSST-AP-DO-170441931760337135"

    The numeric OID is extracted from the internal name (last hyphen-separated
    segment that is entirely digits).

    Unlike ZTF, LSST returns *fluxes* (psfFlux / psfFluxErr) in nanojansky rather
    than magnitudes, so we convert to AB magnitudes:
        m_AB     = 31.4 − 2.5·log10(flux_nJy)            (31.4 = 2.5·log10(3631 Jy / 1 nJy))
        m_AB_err = (2.5 / ln10) · (psfFluxErr / psfFlux)
    Detections and forced-photometry points with positive flux are kept as
    measurements; non-detections within 5 days become upper limits.
    """
    # Rubin/LSST integer band → filter character (band_name string is preferred when present)
    LSST_BAND_MAP = {1: 'g', 2: 'r', 3: 'i', 4: 'z', 5: 'y', 6: 'u'}  # the API's band_map (u is 6)
    AB_ZP_NJY = 31.4  # AB zero point for fluxes expressed in nanojansky
    client = _get_alerce_client()

    def _extract_oid(lsst_name: str) -> str | None:
        """Return the numeric object ID from an internal name like LSST-AP-DO-170441931760337135."""
        for part in reversed(lsst_name.split('-')):
            if part.isdigit():
                return part
        return None

    def _band_str(item: dict) -> str:
        """Filter character from band_name (preferred) or the integer band."""
        name = item.get('band_name')
        if isinstance(name, str) and name:
            return name
        raw = item.get('band')
        try:
            return LSST_BAND_MAP.get(int(raw), f"lsst{raw}")
        except (TypeError, ValueError):
            return str(raw)

    def _flux_to_mag(flux, flux_err):
        """nJy flux → (AB mag, AB mag err); returns (None, None) for non-positive flux."""
        if flux is None or flux <= 0:
            return None, None
        mag = AB_ZP_NJY - 2.5 * np.log10(flux)
        mag_err = (2.5 / np.log(10)) * (flux_err / flux) if flux_err else 0.0
        return mag, mag_err

    for name_pair in tqdm(name_list, desc="LSST (ALeRCE): Fetching photometry"):
        parts = name_pair.split()
        if len(parts) < 2:
            continue
        object_name = parts[0]
        lsst_name   = parts[1]

        oid = _extract_oid(lsst_name)
        if not oid:
            logger.warning('Cannot extract OID from LSST name: %s', lsst_name)
            continue

        logger.info('Fetching LSST photometry for %s (%s, OID=%s) via ALeRCE…', object_name, lsst_name, oid)
        try:
            lc = client.query_lightcurve(oid, survey="lsst")
            # Alert detections + forced photometry both give measured psfFlux for the object.
            detections = (lc.get('detections') or []) + (lc.get('forced_photometry') or [])
            non_dets   = lc.get('non_detections') or []

            photometry_list = []
            det_mjds        = []
            seen            = set()  # (filter, rounded mjd) to drop detection/forced duplicates

            for det in detections:
                mjd = det.get('mjd')
                if mjd is None:
                    continue
                mag, mag_err = _flux_to_mag(det.get('psfFlux'), det.get('psfFluxErr'))
                if mag is None:
                    continue
                filt = _band_str(det)
                key = (filt, round(mjd, 5))
                if key in seen:
                    continue
                seen.add(key)
                det_mjds.append(mjd)
                photometry_list.append(f"{mjd} {mag:.4f} {mag_err:.4f} {filt} LSST(alerce)")

            # Include non-detections within 5 days of any detection (upper limits)
            if det_mjds:
                det_arr = np.array(det_mjds)
                for nd in non_dets:
                    mjd = nd.get('mjd')
                    if mjd is None:
                        continue
                    lim_mag = nd.get('mag_limit') or nd.get('diffmaglim') or nd.get('limmag')
                    if lim_mag is None:
                        # Fall back to a 5σ limit derived from the flux error, if available.
                        flux_err = nd.get('psfFluxErr')
                        if flux_err and flux_err > 0:
                            lim_mag = AB_ZP_NJY - 2.5 * np.log10(5 * flux_err)
                    if lim_mag is None:
                        continue
                    filt = _band_str(nd)
                    if np.min(np.abs(det_arr - mjd)) <= 5:
                        photometry_list.append(f"{mjd} {float(lim_mag):.4f} 0.0 {filt} LSST(alerce)")

            write_photometry_to_txt(object_name, photometry_list, output_dir)
            logger.info('Saved %d LSST photometry points for %s (OID=%s)', len(photometry_list), object_name, oid)

        except Exception as e:
            logger.error('Error fetching LSST photometry for %s (%s): %s', object_name, lsst_name, e)

    return True, None


def bin_photometry_file(photometry_path: str, bin_window: float = 1.0):
    photometry_path = Path(photometry_path)

    if not photometry_path.exists():
        logger.error('File not found: %s', photometry_path)
        return False

    # Read header
    header_lines = []
    with open(photometry_path, 'r') as f:
        for line in f:
            if line.startswith('#'):
                header_lines.append(line)
            else:
                break

    # Read photometry data
    df = pd.read_csv(photometry_path, sep=r'\s+', comment='#',
                     names=['MJD', 'Mag', 'Mag_err', 'Filter', 'Site'])

    # Remove rows with nan magnitude
    df = df.dropna(subset=['Mag'])

    if len(df) == 0:
        logger.warning('No valid data after removing NaN magnitudes')
        return False

    binned_data = []

    # Group by Filter and Site
    for (filt, site), group in df.groupby(['Filter', 'Site']):
        mjd = group['MJD'].values
        mag = group['Mag'].values
        mag_err = group['Mag_err'].values

        # Separate limits from detections
        is_limit = (np.isnan(mag_err)) | (mag_err == 99.0) | (mag_err <= 0)

        # We will bin limits and detections separately
        # Detections:
        det_mjd = mjd[~is_limit]
        det_mag = mag[~is_limit]
        det_err = mag_err[~is_limit]

        if len(det_mjd) > 0:
            det_err = np.where(det_err == 0, 0.1, det_err) # Just safety

            day_indices = np.floor(det_mjd / bin_window).astype(int)
            unique_days = np.unique(day_indices)

            for day in unique_days:
                day_mask = (day_indices == day)
                mjd_sub = det_mjd[day_mask]
                mag_sub = det_mag[day_mask]
                err_sub = det_err[day_mask]

                if len(mjd_sub) == 1:
                    binned_data.append({
                        'MJD': mjd_sub[0],
                        'Mag': mag_sub[0],
                        'Mag_err': err_sub[0],
                        'Filter': filt,
                        'Site': site
                    })
                    continue

                flux_sub = 10**(-0.4 * mag_sub)
                flux_err_sub = flux_sub * err_sub * 0.4 * np.log(10)

                weights = 1.0 / (flux_err_sub**2)
                w_flux = np.sum(flux_sub * weights) / np.sum(weights)

                avg_mag = -2.5 * np.log10(w_flux)
                avg_mjd = np.mean(mjd_sub)

                err_prop = np.sqrt(1.0 / np.sum(weights))
                err_scatter = np.std(flux_sub, ddof=1) / np.sqrt(len(flux_sub)) if len(flux_sub) > 1 else err_prop
                final_flux_err = max(err_prop, err_scatter)

                final_mag_err = (2.5 / np.log(10)) * (final_flux_err / w_flux)

                binned_data.append({
                    'MJD': avg_mjd,
                    'Mag': avg_mag,
                    'Mag_err': final_mag_err,
                    'Filter': filt,
                    'Site': site
                })

        # Limits:
        lim_mjd = mjd[is_limit]
        lim_mag = mag[is_limit]

        if len(lim_mjd) > 0:
            day_indices = np.floor(lim_mjd / bin_window).astype(int)
            unique_days = np.unique(day_indices)

            for day in unique_days:
                day_mask = (day_indices == day)
                mjd_sub = lim_mjd[day_mask]
                mag_sub = lim_mag[day_mask]

                # For limits, we might just take the median or max limit in that bin
                # Typically taking the shallowest (minimum magnitude) limit is safe, or mean
                binned_data.append({
                    'MJD': np.mean(mjd_sub),
                    'Mag': np.min(mag_sub), # shallowest limit
                    'Mag_err': 0.0, # 0.0 means limit
                    'Filter': filt,
                    'Site': site
                })

    if len(binned_data) == 0:
        logger.warning('No binned data generated')
        return False

    # Sort by MJD
    binned_data.sort(key=lambda x: x['MJD'])

    # Write output
    with open(photometry_path, 'w', encoding='utf-8') as f:
        # Write header
        for line in header_lines:
            f.write(line)

        # Write binned data
        for row in binned_data:
            f.write(f"{row['MJD']:.6f} {row['Mag']:.4f} {row['Mag_err']:.4f} {row['Filter']} {row['Site']}\n")

    logger.info('Binned %d points to %d points: %s', len(df), len(binned_data), photometry_path)
    return True

def get_photometry(big_name_list: list[list[str]], output_dir: str = "./data/photometry"):
    ztf_batch_list = []
    lsst_batch_list = []
    processed_iau_names = []

    for item in big_name_list:
        # Handle list format: [name, ra, dec, internal_names]
        if len(item) == 4:
            iau_name = item[0]
            ra = item[1]
            dec = item[2]
            internal_names_str = item[3]
        else:
            # Fallback to old string format
            raw_str = item[0]
            parts = raw_str.split(',')

            try:
                ra = float(parts[1])
                dec = float(parts[2])
            except (IndexError, ValueError):
                logger.error('Error parsing coordinates for: %s', raw_str)
                ra, dec = None, None

            iau_name = next((x.strip() for x in parts if x.strip().startswith('20') and len(x) > 4), None)
            internal_names_str = ','.join(parts[3:]) if len(parts) > 3 else ''

        if not iau_name:
            logger.warning('Skipping %s due to missing IAU name.', item)
            continue

        # Parse internal names
        if isinstance(internal_names_str, str):
            internal_parts = [x.strip() for x in internal_names_str.split(',')]
        else:
            internal_parts = []

        # ATLAS / Pan-STARRS names are still recognised so that such objects do not fall
        # back to a TNS request every day; their downloaders are in download_phot_backup.py.
        atlas_name = next((x for x in internal_parts if "ATLAS" in x), None)
        ps_name    = next((x for x in internal_parts if x.startswith("PS")), None)
        ztf_name   = next((x for x in internal_parts if x.startswith("ZTF")), None)
        lsst_name  = next((x for x in internal_parts if x.upper().startswith("LSST") or re.match(r"^\d{15,}$", x)), None)

        processed_iau_names.append(iau_name)
        init_photometry_file(iau_name, ra, dec, output_dir)

        # Only fall back to TNS bot if no other source is available
        # to avoid excessive TNS API requests.
        if not atlas_name and not ps_name and not ztf_name and not lsst_name:
            logger.info('No ATLAS/PS/ZTF/LSST name for %s, falling back to TNS discovery mag.', iau_name)
            get_discover_mag_from_TNS(iau_name, output_dir)

        if ztf_name:
            ztf_batch_list.append(f"{iau_name} {ztf_name}")

        if lsst_name:
            lsst_batch_list.append(f"{iau_name} {lsst_name}")

    logger.info('Batch processing: %d ZTF, %d LSST objects.', len(ztf_batch_list), len(lsst_batch_list))

    if ztf_batch_list:
        logger.info('Starting ZTF (ALeRCE) batch fetch...')
        get_ztf_photometry(ztf_batch_list, output_dir)

    if lsst_batch_list:
        logger.info('Starting LSST (ALeRCE) batch fetch...')
        get_lsst_alerce_photometry(lsst_batch_list, output_dir)

    for iau_name in processed_iau_names:
        photometry_path = Path(output_dir) / iau_name[0:4] / f"{iau_name}_photometry.txt"
        bin_photometry_file(photometry_path, bin_window=1.0)

    return True

def get_tns_internal_name(objname):
    """Internal names TNS lists for *objname* ([] when none, None on a TNS error)."""
    data = _tns_request(objname)
    if data is None:
        return None
    internal_names = data.get("internal_names")
    if not internal_names:
        logger.warning('No internal name recorded in TNS for %s', objname)
        return []
    return [name.strip() for name in internal_names.split(',')]


def get_object_coordinates(object_name):
    """Get RA and DEC from database for a given object"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT o.ra, o.dec FROM transient.objects o WHERE o.name = %s", (object_name,))
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
    except Exception as e:
        logger.error('Error getting coordinates for %s: %s', object_name, e)
    return None, None

def update_object_internal_names(object_name, internal_names_str):
    """Update internal names in database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Always update to ensure we have the latest from TNS
            cursor.execute("UPDATE transient.objects SET internal_name = %s WHERE name = %s",
                         (internal_names_str, object_name))
            conn.commit()
            logger.info('Updated internal names for %s: %s', object_name, internal_names_str)
    except Exception as e:
        logger.error('Error updating internal names for %s: %s', object_name, e)

def upload_photometry_to_db(object_name, file_path):
    """Read photometry file and upload to database"""
    try:
        # Get existing photometry to check for duplicates
        existing_photometry = TNSObjectDB.get_photometry(object_name)

        data = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.strip().split()
                if len(parts) >= 5:
                    # Format: MJD Mag Mag_err Filter Site
                    try:
                        mjd = float(parts[0])
                        mag = float(parts[1])
                        mag_err = float(parts[2])
                        filt = parts[3]
                        # Handle site potentially having spaces or being the last part
                        # The original code used parts[4], assuming site is one word or we only take the first word.
                        # If we want to be safer with the existing logic:
                        site = parts[4]
                        if len(parts) > 5:
                            site = " ".join(parts[4:])

                        # Check for duplicates
                        is_duplicate = False
                        for existing in existing_photometry:
                            ex_filter = existing.get('filter')
                            ex_telescope = existing.get('telescope')
                            ex_mjd = existing.get('mjd')
                            ex_mag = existing.get('magnitude')

                            # Check filter and telescope
                            # We use loose comparison for telescope as it might vary slightly or be "Unknown"
                            if ex_filter == filt and ex_telescope == site:
                                # Check MJD and Mag with tolerance
                                # MJD tolerance: 0.001 days (~1.4 mins)
                                # Mag tolerance: 0.001 magnitude
                                if ex_mjd is not None and ex_mag is not None:
                                    if abs(float(ex_mjd) - mjd) < 0.001 and abs(float(ex_mag) - mag) < 0.001:
                                        is_duplicate = True
                                        break

                        if not is_duplicate:
                            # Add to list for bulk insert
                            # (object_name, mjd, magnitude, magnitude_error, filter, telescope)
                            data.append((object_name, mjd, mag, mag_err, filt, site))
                    except ValueError:
                        continue # Skip lines with parsing errors

        if data:
            TNSObjectDB.add_photometry_bulk(data)
            logger.info('Uploaded %d new photometry points to database for %s', len(data), object_name)

            # Update last_photometry_date
            TNSObjectDB.sync_last_photometry_date(object_name)

        else:
            logger.info('No new valid photometry data found in %s', file_path)

    except Exception as e:
        logger.error('Error uploading photometry to DB for %s: %s', object_name, e)

def process_single_object_workflow(object_name):
    run_id = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    started = time.monotonic()
    status = 'ok'
    logger.info('event=phot_object_workflow_start run_id=%s object=%s', run_id, object_name)

    # 1. Get RA, DEC from DB
    ra, dec = get_object_coordinates(object_name)
    if ra is None:
        logger.error('event=phot_object_workflow_missing_object run_id=%s object=%s', run_id, object_name)
        status = 'missing_object'
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            'event=phot_object_workflow_done run_id=%s object=%s status=%s duration_ms=%s',
            run_id,
            object_name,
            status,
            duration_ms,
        )
        return

    logger.info('Found coordinates: RA=%s, DEC=%s', ra, dec)

    # 2. Get Internal Names — skip TNS bot if photometry already exists to avoid rate limits
    internal_names_str = ""
    try:
        existing_phot = TNSObjectDB.get_photometry(object_name)
        has_phot = len(existing_phot) > 0
    except Exception:
        has_phot = False

    if has_phot:
        # Read stored internal names from DB instead of calling TNS bot
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT o.internal_name FROM transient.objects o WHERE o.name = %s", (object_name,))
                result = cursor.fetchone()
                if result and result[0]:
                    internal_names_str = result[0]
        except Exception as e:
            logger.error('Error reading internal names from DB for %s: %s', object_name, e)
        logger.info('Object %s already has photometry, using DB internal names (skip TNS bot): %s', object_name, internal_names_str)
    else:
        # No photometry yet — call TNS bot to get internal names
        internal_names_list = get_tns_internal_name(object_name)
        if internal_names_list:
            internal_names_str = ",".join(internal_names_list)
            logger.info('Found internal names: %s', internal_names_str)
            update_object_internal_names(object_name, internal_names_str)
        else:
            logger.info('No internal names found.')

    # 3. Prepare list for get_photometry
    # [name, ra, dec, internal_names_str]
    input_list = [[object_name, ra, dec, internal_names_str]]

    # 5. Download Photometry
    # Use absolute path for output directory to avoid confusion
    output_dir = str(PHOT_CACHE_DIR)   # app/data/phot_cache
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info('Downloading photometry...')
    get_photometry(input_list, output_dir)

    # 6. Update to Database
    year = object_name[:4]
    phot_file = Path(output_dir) / year / f"{object_name}_photometry.txt"

    if phot_file.exists():
        logger.info('Processing photometry file: %s', phot_file)
        upload_photometry_to_db(object_name, phot_file)

        # 7. Delete local file
        try:
            phot_file.unlink()
            logger.info('Deleted local file: %s', phot_file)
        except Exception as e:
            logger.error('Error deleting file %s: %s', phot_file, e)
            status = 'cleanup_error'
    else:
        logger.warning('No photometry file generated for %s', object_name)
        status = 'no_file'

    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        'event=phot_object_workflow_done run_id=%s object=%s status=%s duration_ms=%s',
        run_id,
        object_name,
        status,
        duration_ms,
    )


if __name__ == "__main__":
    # .venv/bin/python -m app.services.photometry.download_phot 2025zmn [more names]
    import sys
    logging.basicConfig(level=logging.INFO)
    for target_name in sys.argv[1:]:
        process_single_object_workflow(target_name)
