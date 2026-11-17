"""PNG previews of the images behind one row of an AutoPhOT photometry table, so the frame itself can be looked at
from Results without downloading FITS.

    preview_png(tid, name, run=None)   PNG bytes: whole frame + a zoom on the target (+ the difference image's zoom
                                       when the image was template-subtracted); NotFound when no FITS is left

The source is the uploaded frame (images/), else AutoPhOT's working copy (<output>/<base>/<base>_APT.fits). The PNG
is cached as <output>/<base>/.preview.png (dot files are not listed), so it stays after the FITS are deleted.
"""
import io
import logging
import os
from pathlib import Path

from . import autophot as ap

logger = logging.getLogger(__name__)

CACHE_NAME = '.preview.png'
ZOOM_ARCSEC = 90           # side of the target zoom
FULL_MAX_PX = 900          # the whole frame is binned down to about this


def _target_coord(cfg):
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    ra, dec = str(cfg.get('ra') or '').strip(), str(cfg.get('dec') or '').strip()
    if not ra or not dec:
        return None
    try:
        return SkyCoord(float(ra), float(dec), unit='deg')
    except ValueError:
        try:
            return SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
        except Exception:
            return None


def _sources(tid, name, run):
    """(folder of this image's output or None, original FITS or None, difference FITS or None)."""
    rp = ap.run_paths(tid, run)
    base_name = ap._ap_base(name)
    out = rp['reduced']
    safe = Path(name).name
    folder = next((p for p in (out / safe, out / base_name) if safe and p.is_dir()), None)
    if folder is None and out.is_dir():
        folder = next((p.parent for p in out.rglob(f'LOG_{base_name}.log')), None)
    original = None
    fits_dir = Path(str(rp['cfg'].get('fits_dir') or ''))
    if fits_dir.is_dir():
        original = next((p for p in ap._fits_in(fits_dir, True) if ap._ap_base(p.name) == base_name), None)
    diff = None
    if folder is not None:
        if original is None:
            original = next((p for p in sorted(folder.glob('*_APT.fit*')) if p.is_file()), None)
        diff = next((p for p in sorted(folder.glob('diff_*.fit*'))
                     if p.is_file() and not p.name.endswith(('_decorr.fits', '_photometry.fits'))), None)
    return folder, original, diff


def _load(path):
    import numpy as np
    from astropy.io import fits
    from astropy.wcs import WCS
    with fits.open(path, memmap=False) as hdul:
        for h in hdul:
            if h.data is not None and getattr(h.data, 'ndim', 0) >= 2:
                data = np.asarray(h.data, dtype=float)
                while data.ndim > 2:
                    data = data[0]
                try:
                    wcs = WCS(h.header, naxis=2)
                    wcs = wcs if wcs.has_celestial else None
                except Exception:
                    wcs = None
                return data, wcs, h.header
    raise ValueError('no image data')


def _scaled(img):
    import numpy as np
    from astropy.visualization import ZScaleInterval
    finite = np.isfinite(img)
    if not finite.any():
        return np.zeros_like(img)
    lo, hi = ZScaleInterval().get_limits(img[finite])
    if not hi > lo:
        hi = lo + 1
    return np.clip((np.where(finite, img, lo) - lo) / (hi - lo), 0, 1)


def _pixscale(wcs):
    import numpy as np
    from astropy.wcs.utils import proj_plane_pixel_scales
    try:
        return float(np.mean(proj_plane_pixel_scales(wcs)) * 3600)
    except Exception:
        return None


def _zoom_panel(ax, data, wcs, coord, title, arcsec=ZOOM_ARCSEC):
    import numpy as np
    from matplotlib.patches import Circle
    ax.set_facecolor('black')
    ax.set_axis_off()
    ax.set_title(title, color='white', fontsize=10, loc='left')
    if wcs is None or coord is None:
        ax.text(0.5, 0.5, 'No WCS', color='#aaa', ha='center', va='center', transform=ax.transAxes)
        return
    x, y = (float(v) for v in wcs.world_to_pixel(coord))
    scale = _pixscale(wcs) or 1.0
    half = int(round(arcsec / 2 / scale))
    h, w = data.shape
    if not (np.isfinite(x) and np.isfinite(y)) or not (-half < x < w + half and -half < y < h + half):
        ax.text(0.5, 0.5, 'Target outside this image', color='#aaa', ha='center', va='center', transform=ax.transAxes)
        return
    x0, y0 = int(round(x)) - half, int(round(y)) - half
    cut = np.full((2 * half + 1, 2 * half + 1), np.nan)
    ys, xs = slice(max(0, y0), min(h, y0 + 2 * half + 1)), slice(max(0, x0), min(w, x0 + 2 * half + 1))
    cut[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0] = data[ys, xs]
    ax.imshow(_scaled(cut), origin='lower', cmap='gray', vmin=0, vmax=1, interpolation='nearest')
    cx, cy = x - x0, y - y0
    ax.add_patch(Circle((cx, cy), 3.0 / scale, fill=False, ec='#00e5ff', lw=1.5))
    bar = 10 / scale
    ax.plot([cut.shape[1] * 0.95 - bar, cut.shape[1] * 0.95], [cut.shape[0] * 0.06] * 2, color='white', lw=2)
    ax.text(cut.shape[1] * 0.95 - bar / 2, cut.shape[0] * 0.08, '10″', color='white', ha='center', va='bottom', fontsize=9)


def _render(original, diff, coord, title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Circle

    data, wcs, hdr = _load(original)
    panels = 3 if diff is not None else 2
    fig, axes = plt.subplots(1, panels, figsize=(5.2 * panels, 5.6), facecolor='black',
                             gridspec_kw={'width_ratios': [1.25] + [1] * (panels - 1)})
    ax = axes[0]
    ax.set_facecolor('black')
    ax.set_axis_off()
    h, w = data.shape
    step = max(1, int(np.ceil(max(h, w) / FULL_MAX_PX)))
    small = data[:h - h % step or h, :w - w % step or w]
    if step > 1:
        small = np.nanmean(small.reshape(small.shape[0] // step, step, small.shape[1] // step, step), axis=(1, 3))
    ax.imshow(_scaled(small), origin='lower', cmap='gray', vmin=0, vmax=1, interpolation='nearest')
    if wcs is not None and coord is not None:
        x, y = (float(v) for v in wcs.world_to_pixel(coord))
        if np.isfinite(x) and np.isfinite(y):
            ax.add_patch(Circle((x / step, y / step), max(h, w) / step * 0.03, fill=False, ec='#00e5ff', lw=1.5))
    bits = [str(hdr['FILTER'])] if hdr.get('FILTER') not in (None, '') else []
    if hdr.get('EXPTIME') not in (None, ''):
        bits.append(f"{hdr['EXPTIME']:g} s" if isinstance(hdr['EXPTIME'], (int, float)) else str(hdr['EXPTIME']))
    ax.set_title(f'{original.name}\n{w}×{h} px' + (f" · {' · '.join(bits)}" if bits else ''),
                 color='white', fontsize=9, loc='left')
    _zoom_panel(axes[1], data, wcs, coord, f'Target · {ZOOM_ARCSEC}″')
    if diff is not None:
        try:
            ddata, dwcs, _ = _load(diff)
            _zoom_panel(axes[2], ddata, dwcs, coord, f'Difference · {ZOOM_ARCSEC}″')
        except Exception:
            logger.exception('preview: could not read %s', diff)
            axes[2].set_axis_off()
    fig.suptitle(title, color='#ddd', fontsize=11, x=0.01, ha='left')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=90, facecolor='black', bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def preview_png(tid, name, run=None):
    folder, original, diff = _sources(tid, name, run)
    cache = folder / CACHE_NAME if folder is not None else None
    newest = max((p.stat().st_mtime for p in (original, diff) if p is not None), default=0)
    if cache is not None and cache.is_file() and cache.stat().st_mtime >= newest:
        return cache.read_bytes()
    if original is None:
        raise ap.NotFound('The FITS of this image are no longer kept.')
    cfg = ap.run_paths(tid, run)['cfg']
    png = _render(original, diff, _target_coord(cfg), ap._ap_base(name))
    if cache is not None:
        try:
            tmp = cache.with_suffix('.tmp')
            tmp.write_bytes(png)
            os.replace(tmp, cache)
        except OSError:
            pass
    return png


def zoom_png(path, coord, arcsec=60, px=240):
    """A square PNG of just the target zoom of one FITS (for the Trigger page's frame thumbnails), or None."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    try:
        data, wcs, _ = _load(path)
    except Exception:
        logger.exception('preview: could not read %s', path)
        return None
    if wcs is None or coord is None:
        return None
    fig = plt.figure(figsize=(px / 100, px / 100), dpi=100, facecolor='black')
    ax = fig.add_axes([0, 0, 1, 1])
    _zoom_panel(ax, data, wcs, coord, '', arcsec)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, facecolor='black')
    plt.close(fig)
    return buf.getvalue()


def field_grid(path, max_px=480):
    """The north-up grid a frame's whole field is drawn on: {'ra', 'dec' (centre, deg), 'w', 'h' (arcsec),
    'nx', 'ny' (px), 'scale' (arcsec/px)}, or None without a WCS. Every filter of a night is drawn on the first
    one's grid, and the survey image is cut to it, so they all show the same piece of sky."""
    import numpy as np
    data, wcs, _ = _load(path)
    if wcs is None:
        return None
    h, w = data.shape
    cx, cy = (w - 1) / 2, (h - 1) / 2
    c = wcs.pixel_to_world(cx, cy)
    ra0, dec0 = float(c.ra.deg), float(c.dec.deg)
    xs, ys = np.array([0, w - 1, 0, w - 1, cx]), np.array([0, 0, h - 1, h - 1, cy])
    corners = wcs.pixel_to_world(xs, ys)
    dx = ((corners.ra.deg - ra0 + 180) % 360 - 180) * np.cos(np.radians(dec0)) * 3600
    dy = (corners.dec.deg - dec0) * 3600
    width, height = 2 * float(np.max(np.abs(dx))), 2 * float(np.max(np.abs(dy)))
    scale = max(width, height) / max_px
    return {'ra': ra0, 'dec': dec0, 'w': round(width, 1), 'h': round(height, 1),
            'nx': int(round(width / scale)), 'ny': int(round(height / scale)), 'scale': scale}


def _out_wcs(grid):
    from astropy.wcs import WCS
    o = WCS(naxis=2)
    o.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    o.wcs.crval = [grid['ra'], grid['dec']]
    o.wcs.crpix = [(grid['nx'] + 1) / 2, (grid['ny'] + 1) / 2]
    o.wcs.cdelt = [-grid['scale'] / 3600, grid['scale'] / 3600]       # east left, north up
    return o


def target_px(grid, coord):
    """(x, y) of the target on the grid's image, y counted from the top; None off the grid."""
    import numpy as np
    x, y = (float(v) for v in _out_wcs(grid).world_to_pixel(coord))
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    return x, grid['ny'] - 1 - y


def field_png(path, coord, grid):
    """The frame's whole field resampled north up onto ``grid`` (field_grid), the target ringed; PNG bytes or None."""
    import numpy as np
    from PIL import Image, ImageDraw
    try:
        data, wcs, _ = _load(path)
    except Exception:
        logger.exception('preview: could not read %s', path)
        return None
    if wcs is None:
        return None
    step = max(1, int(grid['scale'] / (_pixscale(wcs) or grid['scale'])))      # bin first: no aliasing noise
    h, w = data.shape
    if step > 1:
        small = data[:h - h % step, :w - w % step]
        with np.errstate(all='ignore'):
            small = np.nanmean(small.reshape(small.shape[0] // step, step, small.shape[1] // step, step), axis=(1, 3))
    else:
        small = data
    jj, ii = np.mgrid[0:grid['ny'], 0:grid['nx']]
    world = _out_wcs(grid).pixel_to_world(ii.ravel(), jj.ravel())
    fx, fy = wcs.world_to_pixel(world)
    fx, fy = (np.asarray(fx) + 0.5) / step - 0.5, (np.asarray(fy) + 0.5) / step - 0.5
    ix, iy = np.rint(fx).astype(int), np.rint(fy).astype(int)
    ok = (ix >= 0) & (iy >= 0) & (ix < small.shape[1]) & (iy < small.shape[0])
    out = np.full(ix.shape, np.nan)
    out[ok] = small[iy[ok], ix[ok]]
    out = out.reshape(grid['ny'], grid['nx'])
    img = (_scaled(out) * 255).astype(np.uint8)
    img[~np.isfinite(out)] = 0
    im = Image.fromarray(img[::-1], 'L').convert('RGB')
    t = target_px(grid, coord) if coord is not None else None
    if t:
        r = max(6, round(max(grid['nx'], grid['ny']) * 0.025))
        ImageDraw.Draw(im).ellipse([t[0] - r, t[1] - r, t[0] + r, t[1] + r], outline=(0, 229, 255), width=2)
    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
