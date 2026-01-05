from astropy.coordinates import SkyCoord
import astropy.units as u
from dustmaps.sfd import SFDQuery

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

if __name__ == "__main__":
    names = 'Object1'
    ras = 68.50157
    decs = -8.57885
    filters = 'r'
    
    extinction = get_extinction(ras, decs, filters)
    print(f"Extinction for {names} in filter {filters}: {extinction:.3f} mag")