"""DETECT's second review image: a Euclid VIS cutout (DR1, else Q1) of the same field as the LS DR10 finder,
with the transient and DETECT's candidates marked. Used by TNS-DETECT (vendored cross_match.py, stored in
transient.target_images with source 'Euclid') and LSST-DETECT (transient.lsst_target_images.euclid_data).

    build_png(name, ra, dec, fov_arcsec, candidates, host_uid)   PNG bytes, or None where Euclid has no pixels

Most of the sky is outside Euclid: euclid_cutout.near_tile answers that from a cached list of tile centres, so only
positions near a tile ask the ESA archive. Never raises: a slow or down archive just means no Euclid image this run.
"""
import io
import logging
import math

logger = logging.getLogger(__name__)

SOURCE = 'Euclid'          # transient.target_images.source of these images
BAND = 'VIS'
VIS_PIXSCALE = 0.1         # arcsec per pixel of the MER mosaics
FOV_MIN, FOV_MAX = 20, 120


def _fov(fov_arcsec) -> int:
    try:
        f = int(round(float(fov_arcsec)))
    except (TypeError, ValueError):
        f = 60
    return max(FOV_MIN, min(FOV_MAX, f))


def build_png(name: str, ra: float, dec: float, fov_arcsec=60, candidates=None, host_uid=None) -> bytes | None:
    from app.services.astro import euclid_cutout as ec
    try:
        cov = ec.coverage(float(ra), float(dec), wait_for_tiles=True)
        if not cov.get('covered'):
            return None
        fov = _fov(fov_arcsec)
        data, px, py, binning = ec.pixels(float(ra), float(dec), fov, BAND)
    except ec.EuclidError as e:
        if getattr(e, 'status', 0) != 404:
            logger.warning('[DETECT] %s: no Euclid image (%s)', name, e)
        return None
    except Exception:
        logger.exception('[DETECT] %s: Euclid cutout failed', name)
        return None
    try:
        return _render(name, float(ra), float(dec), data, px, py, VIS_PIXSCALE * binning, fov, cov,
                       candidates or [], host_uid)
    except Exception:
        logger.exception('[DETECT] %s: Euclid image render failed', name)
        return None


def _render(name, ra, dec, data, px, py, scale, fov, cov, candidates, host_uid) -> bytes:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    from app.services.special_run import euclid_slsn as es

    img = es._stretch(data)
    h, w = img.shape
    fig, ax = plt.subplots(figsize=(6, 6), facecolor='black')
    ax.imshow(img, origin='lower', cmap='gray', vmin=0, vmax=1, interpolation='nearest')   # FITS rows run south → north
    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(-0.5, h - 0.5)
    ax.set_axis_off()

    # transient: an open cross, like the LS finder
    gap, arm = 1.2 / scale, 3.5 / scale
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ax.plot([px + dx * gap, px + dx * arm], [py + dy * gap, py + dy * arm], color='#00e5ff', lw=2)

    # DETECT candidates (north up, east left on MER tiles)
    cosd = math.cos(math.radians(dec))
    for c in candidates:
        try:
            cra, cdec = float(c['ra']), float(c['dec'])
        except (KeyError, TypeError, ValueError):
            continue
        x = px - ((cra - ra + 180) % 360 - 180) * cosd * 3600 / scale
        y = py + (cdec - dec) * 3600 / scale
        if not (-0.5 <= x <= w - 0.5 and -0.5 <= y <= h - 0.5):
            continue
        is_host = host_uid is not None and c.get('crossmatch_uid') == host_uid
        lens = str(c.get('catalog_name') or '').lower().startswith('lens')
        colour = '#ff4d4d' if is_host else ('#ffd60a' if lens else '#7CFC00')
        ax.add_patch(Circle((x, y), 1.5 / scale, fill=False, ec=colour, lw=2 if is_host else 1.3))

    # 5" scale bar, bottom right
    bar = 5 / scale
    x1, y0 = w * 0.95, h * 0.05
    ax.plot([x1 - bar, x1], [y0, y0], color='white', lw=2)
    ax.text(x1 - bar / 2, y0 + h * 0.015, '5″', color='white', ha='center', va='bottom', fontsize=10)
    ax.text(w * 0.03, h * 0.97, 'N ↑  E ←', color='white', ha='left', va='top', fontsize=9, alpha=0.8)

    rel = str(cov.get('release') or '').upper()
    ax.set_title(f"{name}   Euclid VIS · {rel} tile {cov.get('tile')} · {fov}″",
                 color='white', fontsize=10, loc='left')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='black')
    plt.close(fig)
    return buf.getvalue()
