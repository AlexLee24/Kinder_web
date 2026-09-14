"""
1. Galactic Extinction: Calculates E(B-V) dust extinction using SFD maps and SF11 ratios.
2. Distance Calculations: Converts cosmological redshift (z) to luminosity distance (Mpc).
3. Absolute Magnitude Calculations: Converts apparent magnitude to absolute magnitude, accounting for distance modulus, K-correction, and extinction.
"""

import math
from datetime import datetime

from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
from dustmaps.config import config as _dustmaps_config

# SFD maps live with the project (data/dustmaps/sfd/SFD_dust_4096_{ngp,sgp}.fits)
# so every machine that checks out DETECT finds them without a per-user ~/.dustmapsrc.
# When DETECT is embedded elsewhere (DETECT_DATA_DIR) they are fetched on first use.
from function.paths import DATA_ROOT as _DATA_ROOT  # noqa: E402
_DUSTMAPS_DIR = _DATA_ROOT / "dustmaps"
_SFD_FILES = ("SFD_dust_4096_ngp.fits", "SFD_dust_4096_sgp.fits")
_SFD_URL = "https://github.com/kbarbary/sfddata/raw/master/"


def _ensure_sfd_maps() -> None:
    sfd_dir = _DUSTMAPS_DIR / "sfd"
    if all((sfd_dir / f).exists() for f in _SFD_FILES):
        return
    import urllib.request
    sfd_dir.mkdir(parents=True, exist_ok=True)
    for f in _SFD_FILES:
        if not (sfd_dir / f).exists():
            print(f"[INFO] fetching SFD dust map {f} -> {sfd_dir}")
            urllib.request.urlretrieve(_SFD_URL + f, sfd_dir / f)


_dustmaps_config["data_dir"] = str(_DUSTMAPS_DIR)

from dustmaps.sfd import SFDQuery  # noqa: E402  (after the config)

# Planck 2018 (TT,TE,EE+lowE+lensing) flat ΛCDM — the single cosmology used for
# absolute magnitudes AND projected host offsets across the pipeline.
cosmo = FlatLambdaCDM(H0=67.4 * u.km / u.s / u.Mpc, Om0=0.315, Tcmb0=2.7255 * u.K, name="DETECT-Planck18")


# TNS numeric filter ids (the `discmagfilter` column, and what an older importer
# stored in transient.photometry.filter) -> the TNS filter *name*. Derived from the
# full public object list, 2026-09-14.
TNS_FILTER_IDS = {
    '0': 'Other', '1': 'Clear', '10': 'U', '11': 'B', '12': 'V', '13': 'R', '14': 'I', '15': 'J',
    '17': 'K', '18': 'L', '20': 'u', '21': 'g', '22': 'r', '23': 'i', '24': 'z', '25': 'y', '26': 'w',
    '32': 'U', '40': '3.6', '45': '3.4', '46': '4.6', '50': 'R', '51': 'g', '52': 'I', '55': 'V-crts',
    '56': 'g', '57': 'r', '58': 'i', '59': 'z', '60': 'g-SM', '61': 'r-SM', '62': 'i-SM', '70': 'gr',
    '71': 'cyan', '72': 'orange', '73': 'wide', '75': 'G', '80': 'VR', '81': 'Y', '90': 'Ha',
    '91': 'g', '92': 'r2', '93': 'i2', '94': 'z', '100': 'F200W', '101': 'F444W', '102': 'F115W',
    '103': 'F150W', '104': 'F277W', '105': 'F356W', '106': 'F335M', '109': 'F210M', '110': 'g',
    '111': 'r', '112': 'i', '113': 'BG-u', '116': 'BG-i', '118': 'BG-q', '120': 'L', '124': '800MHz',
    '125': 'S-Band', '126': 'AFB', '127': 'BPSR', '129': 'L-Band', '151': 'u', '152': 'g', '153': 'r',
    '160': 'u', '161': 'g', '162': 'r', '163': 'i', '164': 'z', '172': 'TESS',
}


def normalize_filter_name(raw) -> str:
    """A filter as TNS/the marshal may store it -> the name the extinction table uses."""
    s = str(raw or "").strip()
    if not s:
        return "unknown"
    if s.isdigit():
        return TNS_FILTER_IDS.get(s, "unknown")
    return s


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

        # Names TNS actually delivers (full public list, 2026-09) that were missing above.
        'wide': 'V',        # ATLAS wide, treated like Pan-STARRS w
        'Other': 'V',
        'BG-q': 'gr_avg',   # BlackGEM / MeerLICHT q (440-720 nm)
        'BG-i': 'i',
        'BG-u': 'u',
        'V-crts': 'V',
        'r-SM': 'r', 'g-SM': 'g', 'i-SM': 'i',   # SkyMapper
        'gr': 'gr_avg',     # LSQ
        'r2': 'r', 'i2': 'i',                    # HSC
        'VR': 'gr_avg',     # DECam VR
        'Ha': 'R',
        'TESS': 'I',
    }
    return filter_mapping


def sf11_extinction(ebv, filter_name):
    """Schlafly & Finkbeiner (2011)"""
    extinction_ratios = {
        'U': 4.107, 'B': 3.641, 'V': 2.682, 'R': 2.119, 'I': 1.516,
        'J': 0.709, 'H': 0.449, 'K': 0.302,
        'u': 4.239,
        'g': 3.303,
        'r': 2.285,
        'i': 1.698,
        'z': 1.263,
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


_sfd_query = None


def _get_sfd() -> SFDQuery:
    """SFDQuery loads the full-sky dust maps from disk; build it once per process."""
    global _sfd_query
    if _sfd_query is None:
        _ensure_sfd_maps()
        _sfd_query = SFDQuery()
    return _sfd_query


def get_extinction(ra, dec, filter_name):
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame='icrs')
    ebv = float(_get_sfd()(coord))
    filter_mapping = setup_filter_mapping()
    mapped_filter = filter_mapping.get(filter_name, filter_name)
    extinction_value = sf11_extinction(ebv, mapped_filter)

    return extinction_value


def z_to_lmd(redshift, redshift_error=None):
    try:
        if not isinstance(redshift, (int, float)) or redshift < 0:
            raise ValueError("Redshift must be a non-negative number.")
        if redshift_error is not None and (not isinstance(redshift_error, (int, float)) or redshift_error < 0):
            raise ValueError("Redshift error must be a non-negative number.")

        distance = cosmo.luminosity_distance(redshift)
        distance_mpc = distance.to(u.Mpc).value

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
        if isinstance(distance_mpc, dict):
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

    target_extinction = get_extinction(ras, decs, filters)
    print(f"Extinction for {names} in filter {filters}: {target_extinction:.3f} mag")