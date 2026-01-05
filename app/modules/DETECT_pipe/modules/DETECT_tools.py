import os
import json
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.time import Time
import numpy as np
import pathlib
from matplotlib import pyplot as plt
from matplotlib.ticker import ScalarFormatter

from DETECT_calculate_extinction import get_extinction
from DETECT_calculate_M import apm_to_abm

def get_internal_name(name, csv_file):
    df = pd.read_csv(csv_file, skiprows=1)
    df.columns = df.columns.str.strip().str.replace('"', '')
    
    result = df[df['name'] == name]
    
    if result.empty:
        return None
    
    internal_names = result['internal_names'].values[0]
    internal_names = internal_names.strip().split(', ')
    
    return internal_names

def calculate_pannel(ra, dec, search_radius=45):
    radius_deg = search_radius / 3600.0
    ra_offset = radius_deg / np.cos(np.radians(dec))
    dec_offset = radius_deg
    
    # Calculate corner coordinates
    corners = [
        (ra - ra_offset, dec + dec_offset),  # top_left
        (ra + ra_offset, dec + dec_offset),  # top_right
        (ra - ra_offset, dec - dec_offset),  # bottom_left
        (ra + ra_offset, dec - dec_offset),  # bottom_right
        (ra, dec)                             # center
    ]
    
    # Generate panel names and remove duplicates
    unique_panels = set()
    for r, d in corners:
        r_int = int(r)
        d_int = int(d)
        name = f"RA_{r_int}_DEC_{d_int}"
        unique_panels.add(name)

    pannel = list(unique_panels)
    return pannel

def generate_light_curve_and_M(object_name, redshift, data_dir, output_dir):
    year = object_name[:4]
    data_dir = pathlib.Path(data_dir)
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir_year = output_dir / year
    output_dir_year.mkdir(parents=True, exist_ok=True)
    output_path = output_dir_year / f"{object_name}_{redshift:.3f}_light_curve.png"
    
    # Read photometry file
    photometry_file = data_dir / year / f"{object_name}_photometry.txt"
    
    if not photometry_file.exists():
        print(f"Photometry file not found: {photometry_file}")
        return None
    
    # Parse header to get RA and DEC
    ra, dec = None, None
    with open(photometry_file, 'r') as f:
        for line in f:
            if line.startswith('# RA:'):
                ra = float(line.split(':')[1].strip())
            elif line.startswith('# DEC:'):
                dec = float(line.split(':')[1].strip())
            elif not line.startswith('#'):
                break
    
    if ra is None or dec is None:
        print(f"Could not find RA/DEC in header")
        return None
    
    # Read photometry data
    df = pd.read_csv(photometry_file, sep=r'\s+', comment='#', 
                     names=['MJD', 'Mag', 'Mag_err', 'Filter', 'Site'],
                     na_values=['None', 'nan', 'NaN'])
    
    # Remove rows with missing magnitude values
    df = df.dropna(subset=['Mag'])
    
    if len(df) == 0:
        print(f"No valid photometry data found in {photometry_file}")
        return None, None, None
    
    # Calculate absolute magnitude for each row
    abs_mags = []
    for _, row in df.iterrows():
        filt = row['Filter']
        mag = row['Mag']
        
        # Get extinction for this filter
        extinction = get_extinction(ra, dec, filt)
        
        # Calculate absolute magnitude
        abs_mag = apm_to_abm(mag, redshift, extinction)
        abs_mags.append(abs_mag)
    
    df['Abs_Mag'] = abs_mags
    
    # Create figure with dual y-axes
    fig, ax1 = plt.subplots(figsize=(12, 8))
    ax2 = ax1.twinx()
    
    # Load filter colors from JSON
    filter_color_file = pathlib.Path(__file__).parent / 'filter_color.json'
    try:
        with open(filter_color_file, 'r') as f:
            filter_data = json.load(f)
        filter_colors = {k: v['color'] for k, v in filter_data['filters'].items()}
    except Exception as e:
        print(f"Warning: Could not load filter colors from JSON: {e}")
        filter_colors = {}
    
    # Plot data for each filter
    for filt in df['Filter'].unique():
        mask = df['Filter'] == filt
        color = filter_colors.get(filt, 'black')
        
        ax1.errorbar(df[mask]['MJD'], df[mask]['Mag'], 
                    yerr=df[mask]['Mag_err'],
                    fmt='o', color=color, label=filt, alpha=0.7,
                    markersize=5, capsize=3)
    
    # Find and mark brightest magnitude
    brightest_mag = df['Mag'].min()
    brightest_idx = df['Mag'].idxmin()
    brightest_filter = df.loc[brightest_idx, 'Filter']
    brightest_extinction = get_extinction(ra, dec, brightest_filter)
    brightest_abs_mag = apm_to_abm(brightest_mag, redshift, brightest_extinction)
    
    # Draw horizontal line at brightest magnitude
    ax1.axhline(y=brightest_mag, color='gray', linestyle='--', linewidth=1, alpha=0.3)
    
    # Set labels and formatting
    ax1.set_xlabel('MJD', fontsize=14)
    ax1.set_ylabel('Apparent Magnitude', fontsize=14)
    ax1.invert_yaxis()
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left', fontsize=10)
    
    # Force MJD to display in plain format (no scientific notation)
    ax1.ticklabel_format(style='plain', axis='x', useOffset=False)
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)
    ax1.xaxis.set_major_formatter(formatter)
    
    # Add date axis on top
    ax_top = ax1.twiny()
    ax_top.set_xlim(ax1.get_xlim())
    
    # Convert MJD to dates for tick labels
    mjd_ticks = ax1.get_xticks()
    date_labels = []
    for mjd in mjd_ticks:
        try:
            t = Time(mjd, format='mjd')
            dt = t.datetime
            date_labels.append(f"{dt.month}/{dt.day}/{dt.year % 100:02d}")
        except:
            date_labels.append('')
    
    ax_top.set_xticks(mjd_ticks)
    ax_top.set_xticklabels(date_labels, fontsize=10)
    ax_top.set_xlabel('Date (MM/DD/YY)', fontsize=12)
    
    # Set up right y-axis for absolute magnitude
    mag_min, mag_max = ax1.get_ylim()
    abs_mag_min = apm_to_abm(mag_min, redshift, 0)
    abs_mag_max = apm_to_abm(mag_max, redshift, 0)
    ax2.set_ylim(abs_mag_min, abs_mag_max)
    ax2.set_ylabel('Absolute Magnitude', fontsize=14)
    
    plt.title(f'{object_name} Light Curve (z={redshift:.3f}, M={brightest_abs_mag:.3f})', fontsize=16)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"Light curve saved to {output_path}")
    print(f"Brightest magnitude: {brightest_mag:.3f} (apparent), {brightest_abs_mag:.3f} (absolute)")
    
    return output_path, brightest_mag, brightest_abs_mag

if __name__ == "__main__":
    name = "2025zmn"
    redshift = 0.012
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, "data", "photometry")
    output_dir = os.path.join(current_dir, "data", "light_curves")
    path, brightest_mag, brightest_abs_mag = generate_light_curve_and_M(name, redshift, data_dir, output_dir)
    print(brightest_mag, brightest_abs_mag)