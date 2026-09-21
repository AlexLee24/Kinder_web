"""HEALPix spatial indexing helpers for the local catalog tables.

Catalog rows in ``cat.desi`` / ``cat.lens`` carry a precomputed HEALPix pixel
number (NESTED scheme) in a B-tree indexed column.  A cone search is then a
plain integer lookup:

    pixels = cone_pixels(ra, dec, radius_arcsec)
    SELECT ... WHERE healpix_8192 = ANY(pixels)

``healpy.query_disc(..., inclusive=True)`` over-covers the cone, so the pixel
set is guaranteed to contain every row inside the radius; the exact angular
separation cut still happens afterwards in :mod:`function.database.catalogue`.

The pixel column name encodes NSIDE (``healpix_<nside>``) so that changing
``HEALPIX_NSIDE`` simply means running the migration again for the new
resolution instead of silently reading a stale column.
"""

import os

import healpy as hp
import numpy as np

# NSIDE 8192 -> ~25.8" pixels, a good match for the 15-60" search radii used by
# the pipeline (a 30" cone touches roughly a dozen pixels).
DEFAULT_NSIDE = 8192
HEALPIX_NEST = True

ARCSEC_PER_DEG = 3600.0


def get_nside() -> int:
    """Resolution used for the catalog pixel columns (override: ``HEALPIX_NSIDE``)."""
    raw = os.getenv("HEALPIX_NSIDE")
    if not raw:
        return DEFAULT_NSIDE
    try:
        nside = int(raw)
    except (TypeError, ValueError):
        print(f"[WARNING] Invalid HEALPIX_NSIDE={raw!r}, falling back to {DEFAULT_NSIDE}")
        return DEFAULT_NSIDE
    if not hp.isnsideok(nside, nest=HEALPIX_NEST):
        print(f"[WARNING] HEALPIX_NSIDE={nside} is not a valid NESTED nside, "
              f"falling back to {DEFAULT_NSIDE}")
        return DEFAULT_NSIDE
    return nside


def healpix_column(nside: int | None = None) -> str:
    """Name of the catalog column holding the pixel number for `nside`."""
    return f"healpix_{nside or get_nside()}"


def healpix_index(ra, dec, nside: int | None = None):
    """NESTED pixel number(s) for the given ICRS coordinates in degrees.

    Accepts scalars or array-likes; returns ``int`` or an ``int64`` array.
    """
    nside = nside or get_nside()
    scalar = np.isscalar(ra) and np.isscalar(dec)
    pix = hp.ang2pix(nside, ra, dec, nest=HEALPIX_NEST, lonlat=True)
    return int(pix) if scalar else np.asarray(pix, dtype=np.int64)


def cone_pixels(ra: float, dec: float, radius_arcsec: float,
                nside: int | None = None) -> list[int]:
    """Pixels overlapping the cone of `radius_arcsec` around (ra, dec).

    The cover is inclusive (never misses a row inside the radius) and therefore
    slightly larger than the cone itself.
    """
    nside = nside or get_nside()
    radius_rad = np.radians(max(float(radius_arcsec), 0.0) / ARCSEC_PER_DEG)
    vec = hp.ang2vec(float(ra), float(dec), lonlat=True)
    if radius_rad <= 0:
        return [int(hp.vec2pix(nside, *vec, nest=HEALPIX_NEST))]
    pixels = hp.query_disc(nside, vec, radius_rad, inclusive=True, fact=4,
                           nest=HEALPIX_NEST)
    return [int(p) for p in pixels]


def pixel_resolution_arcsec(nside: int | None = None) -> float:
    """Approximate pixel size in arcseconds, for logging / sanity checks."""
    return float(hp.nside2resol(nside or get_nside(), arcmin=True) * 60.0)
