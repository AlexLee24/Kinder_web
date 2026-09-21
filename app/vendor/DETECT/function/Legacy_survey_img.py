import io
import time
import numpy as np
import matplotlib.pyplot as plt
import requests
import random
from PIL import Image
from astropy.coordinates import SkyCoord
import astropy.units as u
import matplotlib
from pathlib import Path
from datetime import datetime

matplotlib.use('Agg')

# 定義數據目錄
from function.paths import PROJECT_ROOT, DATA_ROOT  # noqa: F401
IMAGE_OUTPUT_DIR = DATA_ROOT / "marked_images"
IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def calculate_separation(ra1, dec1, ra2, dec2):
    coord1 = SkyCoord(ra=ra1 * u.degree, dec=dec1 * u.degree)
    coord2 = SkyCoord(ra=ra2 * u.degree, dec=dec2 * u.degree)
    return coord1.separation(coord2).arcsec


def world_to_pixel(ra_deg, dec_deg, center_ra_deg, center_dec_deg, img_width, img_height, pixscale):
    cosdec = np.cos(np.deg2rad(center_dec_deg))
    ra_diff_arcsec = (center_ra_deg - ra_deg) * 3600 * cosdec
    dec_diff_arcsec = (dec_deg - center_dec_deg) * 3600

    center_x, center_y = img_width / 2, img_height / 2
    x_pix = center_x + ra_diff_arcsec / pixscale
    y_pix = center_y - dec_diff_arcsec / pixscale

    return x_pix, y_pix


def download_desi_cutout(ra, dec, size_arcsec=90, pixscale=0.1, layer="ls-dr10-grz", max_retries=3):
    """Fetch a Legacy Survey JPEG cutout. Returns (jpeg_bytes, survey_name, pixscale)."""
    pixel_size = int(size_arcsec / pixscale)
    jpg_url = (
        f"https://www.legacysurvey.org/viewer/cutout.jpg"
        f"?ra={ra}&dec={dec}"
        f"&pixscale={pixscale}"
        f"&layer={layer}"
        f"&size={pixel_size}"
    )

    last_error = None
    for retry in range(max_retries):
        if retry > 0:
            delay = 3 + random.uniform(0, 2)
            print(f"Retry DESI download {retry}/{max_retries}, waiting {delay:.1f} seconds...")
            time.sleep(delay)
        try:
            response = requests.get(jpg_url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            last_error = e
            continue

        if len(response.content) < 1000:
            last_error = RuntimeError(f"DESI image too small ({len(response.content)} bytes)")
            print(f"DESI image file too small ({len(response.content)} bytes)")
            continue

        print("✓ DESI Legacy Survey download successful")
        return response.content, "DESI Legacy Survey", pixscale

    raise RuntimeError(f"DESI download failed: {last_error}")


def create_marked_image(obj_name, obj_ra, obj_dec, matched_coords, output_path=None, fov_arcsec=60, max_retries=3, save_to_data_dir=True):
    """
    Create marked image from Legacy Survey cutout.

    Args:
        obj_name: Object name for title
        obj_ra: Target RA in degrees
        obj_dec: Target Dec in degrees
        matched_coords: List of dicts with 'ra', 'dec', 'type', 'redshift', 'name'
        output_path: Path to save image. If None and save_to_data_dir=True, saves to DATA_ROOT/marked_images
        fov_arcsec: Field of view in arcseconds
        max_retries: Number of retries if image generation fails
        save_to_data_dir: If True and output_path is None, auto-save to data directory

    Returns:
        Path to saved image file
    """
    fig = None

    # 如果沒有指定輸出路徑且 save_to_data_dir=True，自動生成路徑
    if output_path is None and save_to_data_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = obj_name.replace("/", "_").replace(" ", "_")
        output_path = IMAGE_OUTPUT_DIR / f"{safe_name}_{timestamp}.png"
        print(f"[INFO] Auto-saving image to: {output_path}")

    for attempt in range(max_retries):
        try:
            # Download DESI cutout
            print(f"[INFO] Downloading Legacy Survey cutout for {obj_name}...")
            jpg_bytes, survey_used, pixscale = download_desi_cutout(
                obj_ra, obj_dec,
                size_arcsec=fov_arcsec,
                pixscale=0.1,
                max_retries=3
            )

            # Load image
            image = Image.open(io.BytesIO(jpg_bytes))
            img_data = np.array(image)
            img_height, img_width = img_data.shape[0], img_data.shape[1]

            # Create figure
            fig, ax = plt.subplots(figsize=(10, 10))
            ax.imshow(img_data, origin='upper')

            # Mark target
            x_target, y_target = img_width / 2, img_height / 2
            ax.plot(x_target, y_target, marker='x', color='cyan',
                    markersize=12, mfc='none', mew=3, linewidth=0,
                    label='Target')

            # Marker styles per source type
            type_style = {
                'DESI': {'marker': 'o', 'colors': ['magenta', 'yellow', 'lime', 'orange', 'red', 'white', 'blue']},
                'Lens': {'marker': 'D', 'colors': ['cyan', 'deepskyblue', 'aquamarine']},
                'VizieR': {'marker': '^', 'colors': ['tomato', 'coral', 'orangered']},
            }
            type_counters = {'DESI': 0, 'Lens': 0, 'VizieR': 0}

            # Calculate separation for all coordinates
            for coord in matched_coords:
                if 'sep_arcsec' not in coord:
                    coord['sep_arcsec'] = calculate_separation(obj_ra, obj_dec, coord['ra'], coord['dec'])

            # Sort by distance (nearest first)
            matched_coords.sort(key=lambda x: x.get('sep_arcsec', 9999))

            # Mark each matched object
            for i, coord in enumerate(matched_coords):
                match_ra = coord['ra']
                match_dec = coord['dec']
                redshift = coord.get('redshift', 'N/A')
                name = coord.get('name', f'Obj{i + 1}')
                src_type = coord.get('type', 'DESI')

                if src_type not in type_style:
                    src_type = 'DESI'

                # Calculate separation
                sep_arcsec = calculate_separation(obj_ra, obj_dec, match_ra, match_dec)

                # Convert to pixel coordinates
                x_obj, y_obj = world_to_pixel(
                    match_ra, match_dec, obj_ra, obj_dec,
                    img_width, img_height, pixscale
                )

                # Mark if within image bounds
                if 0 <= x_obj < img_width and 0 <= y_obj < img_height:
                    style = type_style[src_type]
                    cidx = type_counters[src_type] % len(style['colors'])
                    color = style['colors'][cidx]
                    type_counters[src_type] += 1
                    z_str = f"{redshift:.3f}" if isinstance(redshift, (int, float)) else str(redshift)
                    ax.plot(x_obj, y_obj,
                            marker=style['marker'], color=color,
                            markersize=15, mfc='none', mew=2.5, linewidth=0,
                            label=f'[{src_type}] {name}: z={z_str}, sep={sep_arcsec:.2f}"')

            # Add scale bar (5 arcsec)
            scale_bar_arcsec = 5
            scale_bar_pixels = scale_bar_arcsec / pixscale
            bar_x = 0.1 * img_width
            bar_y = 0.9 * img_height
            ax.plot([bar_x, bar_x + scale_bar_pixels],
                    [bar_y, bar_y], color='white', linewidth=3)
            ax.text(bar_x + scale_bar_pixels / 2,
                    bar_y + 20,
                    f'{scale_bar_arcsec}"', color='white',
                    ha='center', fontsize=12, weight='bold')

            # Add legend and title
            ax.legend(loc='upper right', fontsize=10, framealpha=0.8)
            ax.set_title(f"{obj_name} Target: RA={obj_ra:.5f}, DEC={obj_dec:.5f}\n"
                         f"{survey_used} | FOV={fov_arcsec}\" | North Up, East Left",
                         fontsize=12)
            ax.axis('off')

            print(f"[SUCCESS] Image generated successfully for {obj_name}")
            break

        except Exception as e:
            print(f"[WARNING] Image generation failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__} - {e}")
            # Never leave a half-built figure behind: the next attempt makes its own.
            if fig is not None:
                plt.close(fig)
                fig = None
            if attempt == max_retries - 1:
                print(f"[ERROR] Failed to generate image after {max_retries} attempts, creating placeholder")
                fig, ax = plt.subplots(figsize=(10, 10))
                ax.set_facecolor('black')
                ax.text(0.5, 0.5, "Image unavailable", color='white',
                        ha='center', va='center', fontsize=30, transform=ax.transAxes)
                ax.set_title(f"{obj_name} Target: RA={obj_ra:.5f}, DEC={obj_dec:.5f}\n"
                             f"Image Unavailable", fontsize=12)
                ax.axis('off')

    # Save image
    result = None
    try:
        if fig is None:
            raise RuntimeError("no figure was produced")
        if output_path:
            # 確保輸出目錄存在
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            fig.savefig(str(output_path), bbox_inches='tight', dpi=150)
            print(f"[SUCCESS] Image saved to {output_path}")
            result = str(output_path)
        else:
            # 若沒有輸出路徑，回傳字節數據
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            buf.seek(0)
            result = buf.read()
            print(f"[INFO] Image returned as bytes ({len(result)} bytes)")
    except Exception as e:
        print(f"[ERROR] Failed to save image: {type(e).__name__} - {e}")
        result = None
    finally:
        if fig is not None:
            plt.close(fig)

    return result


if __name__ == "__main__":
    # Example usage
    test_obj_ra = 206.8982039
    test_obj_dec = -22.2355124

    test_matched_coords = [
        # {'ra': 150.1245, 'dec': 2.5690, 'redshift': 0.532, 'name': 'Galaxy1', 'type': 'DESI'},
        # {'ra': 150.1220, 'dec': 2.5665, 'redshift': 0.528, 'name': 'Galaxy2', 'type': 'DESI'},
        # {'ra': 150.1250, 'dec': 2.5670, 'redshift': 0.540, 'name': 'Galaxy3', 'type': 'Lens'},
    ]

    print(f"[INFO] Image output directory: {IMAGE_OUTPUT_DIR}")

    result = create_marked_image(
        obj_name="Test_Object",
        obj_ra=test_obj_ra,
        obj_dec=test_obj_dec,
        matched_coords=test_matched_coords,
        fov_arcsec=60,
        max_retries=3,
        save_to_data_dir=True
    )

    if result:
        print(f"[SUCCESS] Test completed. Image path: {result}")
    else:
        print(f"[ERROR] Test failed - image not generated")
