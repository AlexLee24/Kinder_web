"""Legacy Survey Tractor catalogues straight from the public brick files (no Data Lab TAP).

Used when NOIRLab Data Lab's TAP service is down or times out, which otherwise
looks like "catalog 'legacy' returned 0 sources", and to read the local depth
(PSFDEPTH) for Legacy Survey templates.

    bricks(ra, dec, half_w, half_h, layer)        brick names overlapping a box
    sources(ra, dec, radius_deg, release)         DataFrame like the TAP query
    psfdepth(ra, dec, half_deg, band, release)    (median PSFDEPTH_<band>, n) or None

A brick's Tractor file is 25-40 MB; only the columns used here are kept, as a
small .npz per brick in the cache folder (LEGACY_TRACTOR_CACHE, default
~/.cache/autophot/legacy_tractor), so a field is downloaded once.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

BRICKS_URL = "https://www.legacysurvey.org/viewer/bricks/"
DATA_URL = "https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/{release}"
BANDS = ("g", "r", "i", "z")
MAX_BRICKS = 16          # 0.25 deg bricks: a 0.4 deg radius field at most
TIMEOUT = 120
USER_AGENT = "autophot-legacy-tractor/1.0"


def cache_dir() -> Path:
    d = Path(os.environ.get("LEGACY_TRACTOR_CACHE") or Path.home() / ".cache" / "autophot" / "legacy_tractor")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str, timeout: int = TIMEOUT) -> tuple[str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.headers.get_content_type(), resp.read()


def _box(ra, dec, half_h):
    cosd = max(abs(math.cos(math.radians(dec))), 1e-6)
    return half_h / cosd


def bricks(ra: float, dec: float, half_w: float, half_h: float, layer: str = "ls-dr10") -> list[str]:
    q = urllib.parse.urlencode({
        "ralo": max(0.0, ra - half_w), "rahi": min(360.0, ra + half_w),
        "declo": max(-90.0, dec - half_h), "dechi": min(90.0, dec + half_h), "layer": layer,
    })
    ctype, payload = _get(f"{BRICKS_URL}?{q}", timeout=60)
    if ctype == "text/html":
        raise RuntimeError("brick lookup returned HTML")
    return sorted({p["name"] for p in json.loads(payload).get("polys", [])})


def _brick_sep(name, ra, dec):
    """Rough distance (deg) to a brick centre from its name: RRRR[pm]DDD = ra*10, dec*10."""
    try:
        bra, bdec = int(name[:4]) / 10.0, int(name[5:8]) / 10.0 * (-1 if name[4] == "m" else 1)
    except ValueError:
        return 999.0
    return math.hypot(((bra - ra + 180) % 360 - 180) * math.cos(math.radians(dec)), bdec - dec)


def _brick_table(brick: str, release: str):
    """{column: array} for one brick (cached); None when the brick has no Tractor file in this release."""
    cache = cache_dir() / f"{release}_{brick}.npz"
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as z:
            return {k: z[k] for k in z.files} if z.files else None
    from astropy.io import fits

    for region in ("south", "north"):
        url = f"{DATA_URL.format(release=release)}/{region}/tractor/{brick[:3]}/tractor-{brick}.fits"
        try:
            ctype, data = _get(url)
        except Exception as e:                      # 404: brick not in this region
            logger.debug("Tractor %s %s: %s", region, brick, e)
            continue
        if ctype == "text/html" or not data.startswith(b"SIMPLE"):
            continue
        with tempfile.NamedTemporaryFile(suffix=".fits") as tmp:
            tmp.write(data)
            tmp.flush()
            with fits.open(tmp.name, memmap=False) as hdul:
                t = hdul[1].data
                names = {n.lower(): n for n in t.names}
                out = {"ra": np.asarray(t[names["ra"]], float), "dec": np.asarray(t[names["dec"]], float),
                       "type": np.asarray(t[names["type"]]).astype(str)}
                if "brick_primary" in names:
                    out["brick_primary"] = np.asarray(t[names["brick_primary"]], bool)
                for b in BANDS:
                    for col in (f"flux_{b}", f"flux_ivar_{b}", f"psfdepth_{b}"):
                        if col in names:
                            out[col] = np.asarray(t[names[col]], float)
        np.savez_compressed(cache, **out)
        return out
    np.savez_compressed(cache)                      # remember "no file" too
    return None


def _tables(ra, dec, half_h, release):
    half_w = _box(ra, dec, half_h)
    names = bricks(ra, dec, half_w, half_h, layer=f"ls-{release}")
    if not names:
        return []
    if len(names) > MAX_BRICKS:
        names = sorted(names, key=lambda n: _brick_sep(n, ra, dec))
        logger.warning("Legacy Tractor: %d bricks overlap the field; using the %d nearest", len(names), MAX_BRICKS)
        names = names[:MAX_BRICKS]
    logger.info("Legacy Tractor (%s): reading %d brick(s): %s", release, len(names), ", ".join(names))
    out = []
    for n in names:
        t = _brick_table(n, release)
        if t:
            out.append(t)
    return out


def sources(ra: float, dec: float, radius_deg: float, release: str = "dr10"):
    """Rows like the Data Lab query: ra, dec, type, mag_<b>, flux_ivar_<b>, angular_distance; None if no bricks."""
    import pandas as pd

    tabs = _tables(ra, dec, radius_deg, release)
    if not tabs:
        return None
    cat = {k: np.concatenate([t[k] for t in tabs if k in t]) for k in tabs[0]}
    keep = np.ones(len(cat["ra"]), bool)
    if "brick_primary" in cat:
        keep &= cat["brick_primary"]
    dra = ((cat["ra"] - ra + 180.0) % 360.0 - 180.0) * math.cos(math.radians(dec))
    dist = np.hypot(dra, cat["dec"] - dec)
    keep &= dist <= radius_deg
    df = pd.DataFrame({"ra": cat["ra"][keep], "dec": cat["dec"][keep], "type": cat["type"][keep]})
    for b in BANDS:
        f = cat.get(f"flux_{b}")
        if f is None:
            df[f"mag_{b}"] = np.nan
            df[f"flux_ivar_{b}"] = np.nan
            continue
        f = f[keep]
        with np.errstate(divide="ignore", invalid="ignore"):
            df[f"mag_{b}"] = np.where(f > 0, 22.5 - 2.5 * np.log10(f), np.nan)
        df[f"flux_ivar_{b}"] = cat[f"flux_ivar_{b}"][keep]
    df["angular_distance"] = dist[keep]
    return df.sort_values("angular_distance").reset_index(drop=True)


def psfdepth(ra: float, dec: float, half_deg: float, band: str, release: str = "dr10"):
    """(median PSFDEPTH_<band> in nanomaggy^-2, number of sources) inside the box, or None."""
    try:
        tabs = _tables(ra, dec, half_deg, release)
    except Exception as e:
        logger.info("Legacy Tractor depth: %s", e)
        return None
    vals = []
    half_w = _box(ra, dec, half_deg)
    for t in tabs:
        d = t.get(f"psfdepth_{band}")
        if d is None:
            continue
        dra = (t["ra"] - ra + 180.0) % 360.0 - 180.0
        ok = np.isfinite(d) & (d > 0) & (np.abs(dra) <= half_w) & (np.abs(t["dec"] - dec) <= half_deg)
        if "brick_primary" in t:
            ok &= t["brick_primary"]
        vals.extend(d[ok].tolist())
    return (float(np.median(vals)), len(vals)) if vals else None
