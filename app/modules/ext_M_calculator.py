from dustmaps.sfd import SFDQuery

import math
from datetime import datetime

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM

cosmo = FlatLambdaCDM(H0=67.4 * u.km / u.s / u.Mpc, Om0=0.315, Tcmb0=2.7255 * u.K)


def setup_filter_mapping():
    filter_mapping = {
        'U': 'U', 'B': 'B', 'V': 'V', 'R': 'R', 'I': 'I',
        'g': 'g', 'r': 'r', 'i': 'i', 'z': 'z',
        'J': 'J', 'H': 'H', 'K': 'K', 'Y': 'Y',
        'W1': 'W1', 'W2': 'W2',
        
        'y': 'Y',              
        'w': 'V',              
        'L': 'BVR_avg',        
        'cyan': 'B',           
        'orange': 'gr_avg',    
        'o': 'gr_avg',              
        'c': 'B',              
        'gaia_g': 'g',         
        'G': 'g',              
        'Clear': 'BVR_avg',          
        'unfiltered': 'V',     
        'unknown': 'V',        
    }
    return filter_mapping

def sf11_extinction(ebv, filter_name):
    """Schlafly & Finkbeiner (2011)"""
    extinction_ratios = {
    'U': 4.107, 'B': 3.641, 'V': 2.682, 'R': 2.119, 'I': 1.516,
    'J': 0.709, 'H': 0.449, 'K': 0.302,
    'u': 4.239,  # SDSS u-band (SF11)
    'g': 3.303,  # SDSS g-band (SF11)
    'r': 2.285,  # SDSS r-band (SF11)
    'i': 1.698,  # SDSS i-band (SF11)
    'z': 1.263,  # SDSS z-band (SF11)
    'Y': 1.087, 
    'W1': 0.184, 'W2': 0.113,
    }

    if filter_name == 'BVR_avg':
        b_ext = ebv * extinction_ratios['B']
        v_ext = ebv * extinction_ratios['V'] 
        r_ext = ebv * extinction_ratios['R']
        return (b_ext + v_ext + r_ext) / 3.0
    
    elif filter_name == 'gr_avg':
        g_ext = ebv * extinction_ratios['g']
        r_ext = ebv * extinction_ratios['r']
        return (g_ext + r_ext) / 2.0
    
    ratio = extinction_ratios.get(filter_name)
    if ratio is None:
        print(f"Warning: Filter '{filter_name}' not supported, using V band")
        ratio = extinction_ratios['V']
    
    return ebv * ratio

def get_extinction(ra, dec, filter_name):
    coord = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs')
    sfd = SFDQuery()
    ebv = sfd(coord)
    filter_mapping = setup_filter_mapping()
    mapped_filter = filter_mapping.get(filter_name, filter_name)
    extinction = sf11_extinction(ebv, mapped_filter)
    
    return extinction


def z_to_lmd(redshift, redshift_error=None):
    try:
        if not isinstance(redshift, (int, float)) or redshift < 0:
            raise ValueError("Redshift must be a non-negative number.")
        if redshift_error is not None and (not isinstance(redshift_error, (int, float)) or redshift_error < 0):
            raise ValueError("Redshift error must be a non-negative number.")
        
        distance = cosmo.luminosity_distance(redshift)
        distance_mpc = distance.to(u.Mpc).value
        distance_pc = distance.to(u.pc).value
        distance_km = distance.to(u.km).value
        distance_ly = (distance_pc * 3.26156)
        distance_gpc = distance_mpc / 1000
        # You can also change to other units if needed
        # result = round(float(distance_ly), 3)
        result = round(float(distance_mpc), 3)
        
        if redshift_error:
            dz = 0.001
            z_plus = redshift + dz
            z_minus = max(0, redshift - dz)
            
            dist_plus = cosmo.luminosity_distance(z_plus).to(u.Mpc).value
            dist_minus = cosmo.luminosity_distance(z_minus).to(u.Mpc).value
            
            dd_dz = (dist_plus - dist_minus) / (2 * dz)
            distance_error_mpc = abs(dd_dz * redshift_error)
            error = round(float(distance_error_mpc), 3)
            return result, error
        else:
            return result, None
    except Exception as e:
        return {'error': str(e), 'timestamp': datetime.now().isoformat()}

def apm_to_abm(apparent_mag, redshift, extinction=0):
    try:
        if not isinstance(apparent_mag, (int, float)):
            raise ValueError("Apparent magnitude must be a number.")
        if not isinstance(redshift, (int, float)) or redshift < 0:
            raise ValueError("Redshift must be a non-negative number.")
        if not isinstance(extinction, (int, float)) or extinction < 0:
            raise ValueError("Extinction must be a non-negative number.")
        
        distance_mpc, _ = z_to_lmd(redshift)
        if isinstance(distance_mpc, dict):  # Check if error occurred
            return distance_mpc
        distance_pc = distance_mpc * 1e6
        distance_modulus = 5 * math.log10(distance_pc) - 5
        k_correction = 2.5 * math.log10(1 + redshift)
        absolute_magnitude = apparent_mag - distance_modulus - k_correction - extinction
        return round(float(absolute_magnitude), 3)
    except Exception as e:
        return {'error': str(e), 'timestamp': datetime.now().isoformat()}

if __name__ == "__main__":
    names = 'Object1'
    ras = 68.50157
    decs = -8.57885
    filters = 'r'
    
    extinction = get_extinction(ras, decs, filters)
    print(f"Extinction for {names} in filter {filters}: {extinction:.3f} mag")