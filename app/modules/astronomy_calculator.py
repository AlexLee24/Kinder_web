import math
from datetime import datetime

def calculate_redshift_distance(redshift, redshift_error=None):
    """Calculate distance from redshift using cosmological models"""
    try:
        from astropy.cosmology import FlatLambdaCDM
        import astropy.units as u
        
        cosmo = FlatLambdaCDM(H0=67.7 * u.km / u.s / u.Mpc, Om0=0.309, Tcmb0=2.725 * u.K)
        
        distance = cosmo.luminosity_distance(redshift)
        distance_mpc = distance.to(u.Mpc).value
        distance_pc = distance.to(u.pc).value
        distance_km = distance.to(u.km).value
        distance_ly = (distance_pc * 3.26156)
        distance_gpc = distance_mpc / 1000
        
        result = {
            'distance_km': round(distance_km, 2),
            'distance_ly': round(distance_ly, 2),
            'distance_pc': round(distance_pc, 2),
            'distance_mpc': round(distance_mpc, 2),
            'distance_gpc': round(distance_gpc, 4),
            'redshift': redshift
        }
        
        if redshift_error:
            dz = 0.001
            z_plus = redshift + dz
            z_minus = max(0, redshift - dz)
            
            dist_plus = cosmo.luminosity_distance(z_plus).to(u.Mpc).value
            dist_minus = cosmo.luminosity_distance(z_minus).to(u.Mpc).value
            
            dd_dz = (dist_plus - dist_minus) / (2 * dz)
            distance_error_mpc = abs(dd_dz * redshift_error)
            
            result.update({
                'distance_error_km': round(distance_error_mpc * 3.086e19, 2),
                'distance_error_ly': round(distance_error_mpc * 1e6 * 3.26156, 2),
                'distance_error_pc': round(distance_error_mpc * 1e6, 2),
                'distance_error_mpc': round(distance_error_mpc, 2),
                'distance_error_gpc': round(distance_error_mpc / 1000, 4)
            })
        
        return result
        
    except ImportError:
        # Fallback to simple Hubble law
        H0 = 70
        c = 299792.458
        
        distance_mpc = (c * redshift) / H0
        distance_pc = distance_mpc * 1e6
        distance_km = distance_mpc * 3.086e19
        distance_ly = distance_pc * 3.26156
        distance_gpc = distance_mpc / 1000
        
        result = {
            'distance_km': round(distance_km, 2),
            'distance_ly': round(distance_ly, 2),
            'distance_pc': round(distance_pc, 2),
            'distance_mpc': round(distance_mpc, 2),
            'distance_gpc': round(distance_gpc, 4),
            'redshift': redshift
        }
        
        if redshift_error:
            distance_error_mpc = (c * redshift_error) / H0
            result.update({
                'distance_error_km': round(distance_error_mpc * 3.086e19, 2),
                'distance_error_ly': round(distance_error_mpc * 1e6 * 3.26156, 2),
                'distance_error_pc': round(distance_error_mpc * 1e6, 2),
                'distance_error_mpc': round(distance_error_mpc, 2),
                'distance_error_gpc': round(distance_error_mpc / 1000, 4)
            })
        
        return result

def calculate_absolute_magnitude(apparent_magnitude, redshift, extinction=0):
    """Calculate absolute magnitude from apparent magnitude and redshift"""
    try:
        from astropy.cosmology import FlatLambdaCDM
        import astropy.units as u
        
        cosmo = FlatLambdaCDM(H0=67.7 * u.km / u.s / u.Mpc, Om0=0.309, Tcmb0=2.725 * u.K)
        distance = cosmo.luminosity_distance(redshift)
        distance_pc = distance.to(u.pc).value
        
    except ImportError:
        H0 = 70
        c = 299792.458
        distance_mpc = (c * redshift) / H0
        distance_pc = distance_mpc * 1e6
    
    distance_modulus = 5 * math.log10(distance_pc) - 5
    k_correction = 2.5 * math.log10(1 + redshift)
    absolute_magnitude = apparent_magnitude - distance_modulus - k_correction - extinction
    
    return {
        'absolute_magnitude': round(absolute_magnitude, 2),
        'distance_modulus': round(distance_modulus, 2),
        'k_correction': round(k_correction, 2),
        'distance_mpc': round(distance_pc / 1e6, 2),
        'extinction': extinction
    }