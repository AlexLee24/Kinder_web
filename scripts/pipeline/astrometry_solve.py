"""Astrometry for the Pipeline: solve-field per FITS, after EAU_Web (app/modules/media/platesolve.py).

Used by reduction_web_run.py (calibrated frames) and autophot_web_run.py (every frame, before AutoPhOT runs);
needs only astropy, so it works in the reduction Python and in AutoPhOT's.

Hints come from the header: the position from RA / DEC (or OBJCTRA / OBJCTDEC), the pixel scale from FOCALLEN and
XPIXSZ × XBINNING, as the reduction pipeline estimates it. Attempts, each until one solves:
  narrow   scale × 0.85–1.18, within max(field × 1.5, 1°) of the header position     CPU 60 s
  wide     scale × 0.5–2.0, within 5°                                                CPU 120 s
  blind    0.1–10″/px, anywhere (the pipeline's own range)                           CPU 300 s
Each attempt also has a wall-clock limit (CPU × 1.5 + 30 s); past it the whole process group is killed, so the
astrometry-engine child goes too. ASTROMETRY_CONFIG points solve-field at another astrometry.cfg (index files).
"""
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

NARROW = ('narrow', 0.85, 1.18, None, 60)        # radius None: max(field × 1.5, 1°)
WIDE = ('wide', 0.5, 2.0, 5.0, 120)              # also covers a binning the header does not tell
BLIND = ('blind', None, None, None, 300)
DOWNSAMPLE_ABOVE = 2500                          # px on the long side: solve a 2× downsampled image
MARK = 'KWASTROM'                                # header card: 'solved' / 'failed' by this module


def find_solve_field():
    return shutil.which('solve-field') or next(
        (p for p in ('/opt/homebrew/bin/solve-field', '/usr/local/bin/solve-field', '/usr/bin/solve-field')
         if os.path.isfile(p)), None)


def _coord(ra, dec):
    """Header RA / Dec: degrees, or sexagesimal with spaces or colons → (ra°, dec°) or (None, None)."""
    ra, dec = str(ra or '').strip(), str(dec or '').strip()
    if not ra or not dec:
        return None, None
    try:
        r, d = float(ra), float(dec)
    except ValueError:
        try:
            from astropy import units as u
            from astropy.coordinates import SkyCoord
            c = SkyCoord(ra.replace(' ', ':'), dec.replace(' ', ':'), unit=(u.hourangle, u.deg))
            r, d = float(c.ra.deg), float(c.dec.deg)
        except Exception:
            return None, None
    if (r == 0 and d == 0) or not (0 <= r < 360 and -90 <= d <= 90):
        return None, None
    return r, d


def hints(header):
    """{'ra', 'dec', 'scale' (″/px), 'long_px', 'field' (°)}; unknown values are None."""
    ra, dec = _coord(header.get('RA'), header.get('DEC'))
    if ra is None:
        ra, dec = _coord(header.get('OBJCTRA'), header.get('OBJCTDEC'))
    nx, ny = int(header.get('NAXIS1') or 0), int(header.get('NAXIS2') or 0)
    scale = None
    try:
        import math
        fl, pix = float(header['FOCALLEN']), float(header['XPIXSZ'])
        b = int(header.get('XBINNING') or 1)
        scale = 3600 * 180 * 2 * math.atan(1e-3 * 0.5 * pix / fl) / math.pi * b
        if not 0.05 <= scale <= 50:
            scale = None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return {'ra': ra, 'dec': dec, 'scale': scale, 'long_px': max(nx, ny),
            'field': scale * max(nx, ny) / 3600 if scale else None}


def attempts(h):
    if h['scale']:
        return [NARROW, WIDE, BLIND]
    if h['ra'] is not None:
        return [('wide', None, None, 5.0, 120), BLIND]
    return [BLIND]


def _killpg(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _run(solve_field, src, dest, tmp, h, how, children):
    label, flo, fhi, radius, cpu = how
    lo, hi = (h['scale'] * flo, h['scale'] * fhi) if flo and h['scale'] else (0.1, 10.0)
    cmd = [solve_field, str(src), '--dir', str(tmp), '--no-plots', '--overwrite', '--no-verify', '--crpix-center',
           '--fits-image', '--cpulimit', str(cpu), '--scale-units', 'arcsecperpix',
           '--scale-low', f'{lo:.4f}', '--scale-high', f'{hi:.4f}', '--new-fits', str(dest),
           '--corr', 'none', '--rdls', 'none', '--match', 'none', '--index-xyls', 'none', '--solved', 'none',
           '--temp-axy']
    if h['ra'] is not None and label != 'blind':
        r = radius if radius else max((h['field'] or 0) * 1.5, 1.0)
        cmd += ['--ra', f"{h['ra']:.6f}", '--dec', f"{h['dec']:.6f}", '--radius', f'{r:.2f}']
    if h['long_px'] > DOWNSAMPLE_ABOVE:
        cmd += ['--downsample', '2']
    cfg = os.environ.get('ASTROMETRY_CONFIG', '').strip()
    if cfg:
        cmd += ['--config', cfg]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, errors='replace', start_new_session=True)
    children.add(proc.pid)
    killed = []
    timer = threading.Timer(cpu * 1.5 + 30, lambda: (killed.append(1), _killpg(proc.pid)))
    timer.daemon = True
    timer.start()
    try:
        out = proc.communicate()[0] or ''
    finally:
        timer.cancel()
        children.discard(proc.pid)
    if os.path.isfile(dest):
        return 'solved'
    if killed:
        return 'timeout'
    return 'cpu_limit' if 'CPU time limit' in out else 'no_solution'


def wcs_summary(path):
    import warnings

    from astropy.io import fits
    from astropy.wcs import WCS
    from astropy.wcs.utils import proj_plane_pixel_scales

    with fits.open(path) as hdul, warnings.catch_warnings():
        warnings.simplefilter('ignore')                # old MaxIm DL / PinPoint cards (EPOCH, RADECSYS)
        h = hdul[0].header
        w = WCS(h).celestial
        nx, ny = h.get('NAXIS1', 0), h.get('NAXIS2', 0)
    c = w.pixel_to_world_values((nx - 1) / 2, (ny - 1) / 2)
    return {'ra': round(float(c[0]), 5), 'dec': round(float(c[1]), 5),
            'pixscale': round(float(sum(proj_plane_pixel_scales(w))) / 2 * 3600, 4)}


def solve(src, dest, solve_field, log=print, children=None, workdir=None):
    """Solve src; on success the image with its new WCS is written to dest (may be src itself).
    Returns {'status': 'solved'|'failed', 'how', 'reason', 'ra', 'dec', 'pixscale', 'seconds', 'hint_scale'}."""
    from astropy.io import fits

    t0 = time.time()
    children = children if children is not None else set()
    name = os.path.basename(str(src))
    rec = {'status': 'failed'}
    try:
        h = hints(fits.getheader(str(src)))
    except Exception as e:
        rec.update(reason=f'header not readable: {e}', seconds=round(time.time() - t0, 1))
        return rec
    rec['hint_scale'] = round(h['scale'], 4) if h['scale'] else None
    tmp = tempfile.mkdtemp(prefix='solve_', dir=workdir)
    out = os.path.join(tmp, 'solved.fits')
    try:
        reason = 'no_solution'
        for how in attempts(h):
            log(f'{name}: solve-field {how[0]} (CPU limit {how[4]} s)')
            reason = _run(solve_field, src, out, tmp, h, how, children)
            if reason == 'solved':
                with fits.open(out, mode='update') as hdul:
                    hdul[0].header[MARK] = ('solved', f'WCS by Kinder solve-field ({how[0]})')
                shutil.move(out, str(dest))
                rec.update(status='solved', how=how[0], **wcs_summary(str(dest)))
                log(f"{name}: solved ({how[0]}), {rec['pixscale']}″/px at RA {rec['ra']} Dec {rec['dec']}")
                break
            log(f'{name}: {how[0]} gave {reason}')
        else:
            rec['reason'] = reason
    except Exception as e:
        rec['reason'] = f'error: {e}'
        log(f'{name}: astrometry error {e}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rec['seconds'] = round(time.time() - t0, 1)
    return rec
