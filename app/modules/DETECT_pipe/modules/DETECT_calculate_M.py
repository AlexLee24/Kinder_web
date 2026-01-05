import math
from datetime import datetime
from astropy.cosmology import FlatLambdaCDM
import astropy.units as u

cosmo = FlatLambdaCDM(H0=67.4 * u.km / u.s / u.Mpc, Om0=0.315, Tcmb0=2.7255 * u.K)

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