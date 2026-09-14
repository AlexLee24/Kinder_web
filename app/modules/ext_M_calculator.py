"""Absolute magnitude, extinction and luminosity distance for the web app.

A shim over DETECT's ``function.module.calculator`` (app/modules/DETECT), so the
marshal, the DETECT pages and the DETECT pipeline all use one cosmology
(Planck 2018, ``cosmo``), one SFD98 x SF11 extinction table and one filter map.
The SFD dust maps are fetched on first use into DETECT_DATA_DIR.
"""
from function.module.calculator import (  # noqa: F401
    cosmo,
    setup_filter_mapping,
    sf11_extinction,
    get_extinction,
    z_to_lmd,
    apm_to_abm,
    normalize_filter_name,
    TNS_FILTER_IDS,
)
