import os
import time
import numpy as np
import matplotlib.pyplot as plt
import requests
import random
from PIL import Image
from astropy.coordinates import SkyCoord
import astropy.units as u
from pathlib import Path
import matplotlib
matplotlib.use('Agg')

def calculate_separation(ra1, dec1, ra2, dec2):
    coord1 = SkyCoord(ra=ra1*u.degree, dec=dec1*u.degree)
    coord2 = SkyCoord(ra=ra2*u.degree, dec=dec2*u.degree)
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
    pixel_size = int(size_arcsec / pixscale)
    jpg_url = (
        f"https://www.legacysurvey.org/viewer/cutout.jpg"
        f"?ra={ra}&dec={dec}"
        f"&pixscale={pixscale}"
        f"&layer={layer}"
        f"&size={pixel_size}"
    )
    
    for retry in range(max_retries):
        try:
            if retry > 0:
                delay = 3 + random.uniform(0, 2)
                print(f"Retry DESI download {retry}/{max_retries}, waiting {delay:.1f} seconds...")
                time.sleep(delay)
            
            response = requests.get(jpg_url, timeout=60)
            response.raise_for_status()
            
            temp_file = f"temp_desi_{ra:.4f}_{dec:.4f}.jpg"
            with open(temp_file, "wb") as fp:
                fp.write(response.content)
            
            file_size = os.path.getsize(temp_file)
            if file_size < 1000:
                print(f"DESI image file too small ({file_size} bytes)")
                if retry < max_retries - 1:
                    continue
                raise RuntimeError("DESI image too small")
            
            print(f"✓ DESI Legacy Survey download successful")
            return temp_file, "DESI Legacy Survey", pixscale
            
        except Exception as e:
            if retry == max_retries - 1:
                raise RuntimeError(f"DESI download failed: {e}")
    
    raise RuntimeError("DESI download failed")



import io

def create_marked_image(obj_name, target_ra, target_dec, coord_list, output_path=None, fov_arcsec=60):
    """
    Create marked image.
    If output_path is provided, saves to file and returns path.
    If output_path is None, returns image bytes.
    """
    jpg_filename, survey_used, pixscale = download_desi_cutout(
        target_ra, target_dec, 
        size_arcsec=fov_arcsec, 
        pixscale=0.1
    )
    
    image = Image.open(jpg_filename)
    img_data = np.array(image)
    img_height, img_width = img_data.shape[0], img_data.shape[1]
    
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(img_data, origin='upper')
    
    x_target, y_target = img_width / 2, img_height / 2
    ax.plot(x_target, y_target, marker='x', color='cyan', 
           markersize=12, mfc='none', mew=3, linewidth=0, 
           label='Target')
    
    colors = ['magenta', 'yellow', 'lime', 'orange', 'red', 'white', 'blue']
    count = 1
    
    # Calculate separation for all coordinates and sort by distance (nearest first)
    for coord in coord_list:
        # Calculate separation if not already present
        if 'sep_arcsec' not in coord:
            coord['sep_arcsec'] = calculate_separation(target_ra, target_dec, coord['ra'], coord['dec'])
            
    # Sort the list in-place
    coord_list.sort(key=lambda x: x.get('sep_arcsec', 9999))
    
    # Mark each coordinate in list
    for i, coord in enumerate(coord_list):
        ra = coord['ra']
        dec = coord['dec']
        redshift = coord.get('redshift', 'N/A')
        name = coord.get('name', f'Obj{i+1}')
        
        
        # Calculate separation
        sep_arcsec = calculate_separation(target_ra, target_dec, ra, dec)
        
        # Convert to pixel coordinates
        x_obj, y_obj = world_to_pixel(
            ra, dec, target_ra, target_dec,
            img_width, img_height, pixscale
        )
        
        # Check if within image bounds
        if 0 <= x_obj < img_width and 0 <= y_obj < img_height:
            color = colors[i % len(colors)]
            ax.plot(x_obj, y_obj, marker='o', color=color, 
                   markersize=15, mfc='none', mew=2.5, linewidth=0,
                   label=f'Galaxy_{count}: z={redshift:.3f}, sep={sep_arcsec:.2f}"')
            count += 1
    
    # Add scale bar (5 arcsec)
    scale_bar_length_arcsec = 5
    scale_bar_length_pixels = scale_bar_length_arcsec / pixscale
    bar_x = 0.1 * img_width
    bar_y = 0.9 * img_height
    ax.plot([bar_x, bar_x + scale_bar_length_pixels],
            [bar_y, bar_y], color='white', linewidth=3)
    ax.text(bar_x + scale_bar_length_pixels / 2,
            bar_y + 20,
            f'{scale_bar_length_arcsec}"', color='white',
            ha='center', fontsize=12, weight='bold')
    
    # Add legend and title
    plt.legend(loc='upper right', fontsize=10, framealpha=0.8)
    plt.title(f"{obj_name} Target: RA={target_ra:.5f}, DEC={target_dec:.5f}\n"
             f"{survey_used} | FOV={fov_arcsec}\" | North Up, East Left",
             fontsize=12)
    
    plt.axis('off')
    
    # Save image
    if output_path:
        plt.savefig(output_path, bbox_inches='tight', dpi=150)
        plt.close(fig)
        result = output_path
    else:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        plt.close(fig)
        buf.seek(0)
        result = buf.read()
    
    # Clean up temporary file
    if jpg_filename and os.path.exists(jpg_filename):
        os.remove(jpg_filename)
    
    return result

if __name__ == "__main__":
    # Example usage
    target_ra = 150.1234
    target_dec = 2.5678
    
    coord_list = [
        {'ra': 150.1245, 'dec': 2.5690, 'redshift': 0.532, 'name': 'Galaxy1'},
        {'ra': 150.1220, 'dec': 2.5665, 'redshift': 0.528, 'name': 'Galaxy2'},
        {'ra': 150.1250, 'dec': 2.5670, 'redshift': 0.540, 'name': 'Galaxy3'},
    ]
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_dir, "data", "desi_image", "marked_desi_image.png")
    
    create_marked_image(
        obj_name="Test Object",
        target_ra=target_ra,
        target_dec=target_dec,
        coord_list=coord_list,
        output_path=output_path,
        fov_arcsec=60
    )
