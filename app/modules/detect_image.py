"""
detect_image.py — Generate marked finder-chart images for DETECT cross-match results.

Usage:
    from modules.detect_image import create_marked_image

    image_bytes = create_marked_image(
        obj_name="SN 2024abc",
        target_ra=150.1234,
        target_dec=2.5678,
        coord_list=[
            {'ra': 150.124, 'dec': 2.568, 'redshift': 0.53, 'name': 'HOLISMOKES_II', 'type': 'Lens'},
            {'ra': 150.122, 'dec': 2.566, 'redshift': 0.21, 'name': 'DESI-12345',    'type': 'DESI'},
        ],
        fov_arcsec=90,
    )
"""
import io
import os
import time
import random
import logging

import numpy as np
import requests
from PIL import Image
from astropy.coordinates import SkyCoord
import astropy.units as u
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Marker styles per source type  (matches reference code exactly)
# ---------------------------------------------------------------------------
_TYPE_STYLE = {
    'DESI':   {'marker': 'o', 'colors': ['magenta', 'yellow', 'lime', 'orange', 'red', 'white', 'blue']},
    'Lens':   {'marker': 'D', 'colors': ['cyan', 'deepskyblue', 'aquamarine']},
    'VizieR': {'marker': '^', 'colors': ['tomato', 'coral', 'orangered']},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calculate_separation(ra1, dec1, ra2, dec2):
    c1 = SkyCoord(ra=ra1 * u.degree, dec=dec1 * u.degree)
    c2 = SkyCoord(ra=ra2 * u.degree, dec=dec2 * u.degree)
    return float(c1.separation(c2).arcsec)


def _world_to_pixel(ra_deg, dec_deg, center_ra_deg, center_dec_deg,
                    img_width, img_height, pixscale):
    """Convert sky coordinates to image pixel position (North up, East left)."""
    cosdec = np.cos(np.deg2rad(center_dec_deg))
    ra_diff_arcsec  = (center_ra_deg - ra_deg) * 3600.0 * cosdec
    dec_diff_arcsec = (dec_deg - center_dec_deg) * 3600.0
    center_x, center_y = img_width / 2.0, img_height / 2.0
    x_pix = center_x + ra_diff_arcsec  / pixscale
    y_pix = center_y - dec_diff_arcsec / pixscale
    return x_pix, y_pix


def _download_desi_cutout(ra, dec, size_arcsec=90, pixscale=0.1,
                          layer="ls-dr10-grz", max_retries=3):
    """Download DESI Legacy Survey JPEG cutout; returns (bytes, pixscale)."""
    pixel_size = int(size_arcsec / pixscale)
    jpg_url = (
        f"https://www.legacysurvey.org/viewer/cutout.jpg"
        f"?ra={ra}&dec={dec}"
        f"&pixscale={pixscale}"
        f"&layer={layer}"
        f"&size={pixel_size}"
    )
    for retry in range(max_retries):
        if retry > 0:
            delay = 3.0 + random.uniform(0, 2)
            logger.info("Retry DESI download %d/%d, waiting %.1fs", retry, max_retries, delay)
            time.sleep(delay)
        try:
            response = requests.get(jpg_url, timeout=60)
            response.raise_for_status()
            if len(response.content) < 1000:
                raise RuntimeError(f"DESI image too small ({len(response.content)} bytes)")
            logger.info("DESI cutout downloaded: %d bytes", len(response.content))
            return response.content, pixscale
        except Exception as exc:
            if retry == max_retries - 1:
                raise RuntimeError(f"DESI download failed: {exc}") from exc
    raise RuntimeError("DESI download failed")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_marked_image(obj_name, target_ra, target_dec, coord_list,
                        output_path=None, fov_arcsec=90):
    """
    Generate a finder chart with cross-match markers overlaid.

    Parameters
    ----------
    obj_name     : str   — display name for title
    target_ra    : float — degrees
    target_dec   : float — degrees
    coord_list   : list of dicts with keys:
                     ra, dec, type ('DESI'|'Lens'|'VizieR'),
                     name (label), redshift (optional)
    output_path  : str | None — if given, save PNG to disk; otherwise return bytes
    fov_arcsec   : float — image FOV width in arcsec (default 90)

    Returns
    -------
    bytes (PNG) if output_path is None, else output_path string.
    """
    pixscale = 0.1
    fig = None
    survey_used = "DESI Legacy Survey"

    try:
        jpg_bytes, pixscale = _download_desi_cutout(
            target_ra, target_dec,
            size_arcsec=fov_arcsec,
            pixscale=pixscale
        )

        image = Image.open(io.BytesIO(jpg_bytes))
        img_data = np.array(image)
        img_height, img_width = img_data.shape[0], img_data.shape[1]

        fig, ax = plt.subplots(figsize=(10, 10))
        ax.imshow(img_data, origin='upper')

        # Mark the target
        x_target, y_target = img_width / 2, img_height / 2
        ax.plot(x_target, y_target, marker='x', color='cyan',
                markersize=12, mfc='none', mew=3, linewidth=0,
                label='Target')

        # Pre-compute separations and sort nearest first
        for coord in coord_list:
            if 'sep_arcsec' not in coord:
                coord['sep_arcsec'] = _calculate_separation(
                    target_ra, target_dec, coord['ra'], coord['dec']
                )
        coord_list = sorted(coord_list, key=lambda x: x.get('sep_arcsec', 9999))

        _type_counters = {'DESI': 0, 'Lens': 0, 'VizieR': 0}

        for i, coord in enumerate(coord_list):
            ra       = coord['ra']
            dec      = coord['dec']
            redshift = coord.get('redshift', 'N/A')
            name     = coord.get('name', f'Obj{i+1}')
            src_type = coord.get('type', 'DESI')
            if src_type not in _TYPE_STYLE:
                src_type = 'DESI'

            sep_arcsec = _calculate_separation(target_ra, target_dec, ra, dec)

            x_obj, y_obj = _world_to_pixel(
                ra, dec, target_ra, target_dec,
                img_width, img_height, pixscale
            )

            if not (0 <= x_obj < img_width and 0 <= y_obj < img_height):
                logger.debug("coord out of image bounds: %s (%.4f, %.4f) → px(%.1f, %.1f)",
                             name, ra, dec, x_obj, y_obj)
                continue

            style = _TYPE_STYLE[src_type]
            cidx  = _type_counters[src_type] % len(style['colors'])
            color = style['colors'][cidx]
            _type_counters[src_type] += 1

            z_str = f"{redshift:.3f}" if isinstance(redshift, (int, float)) else str(redshift)
            ax.plot(x_obj, y_obj,
                    marker=style['marker'], color=color,
                    markersize=15, mfc='none', mew=2.5, linewidth=0,
                    label=f'[{src_type}] {name}: z={z_str}, sep={sep_arcsec:.2f}"')

        # 5-arcsec scale bar
        scale_bar_length_arcsec  = 5
        scale_bar_length_pixels  = scale_bar_length_arcsec / pixscale
        bar_x = 0.1 * img_width
        bar_y = 0.9 * img_height
        ax.plot([bar_x, bar_x + scale_bar_length_pixels], [bar_y, bar_y],
                color='white', linewidth=3)
        ax.text(bar_x + scale_bar_length_pixels / 2, bar_y + 20,
                f'{scale_bar_length_arcsec}"',
                color='white', ha='center', fontsize=12, weight='bold')

        plt.legend(loc='upper right', fontsize=10, framealpha=0.8)
        plt.title(
            f"{obj_name} Target: RA={target_ra:.5f}, DEC={target_dec:.5f}\n"
            f"{survey_used} | FOV={fov_arcsec}\" | North Up, East Left",
            fontsize=12
        )
        plt.axis('off')

    except Exception as e:
        logger.warning("create_marked_image: failed to download/draw for %s: %s", obj_name, e)
        if fig is not None:
            plt.close(fig)
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.set_facecolor('black')
        ax.text(0.5, 0.5, "Image unavailable", color='white',
                ha='center', va='center', fontsize=30, transform=ax.transAxes)
        plt.title(
            f"{obj_name} Target: RA={target_ra:.5f}, DEC={target_dec:.5f}\n"
            f"Image Unavailable",
            fontsize=12
        )
        plt.axis('off')

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, bbox_inches='tight', dpi=150)
        plt.close(fig)
        return output_path
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

