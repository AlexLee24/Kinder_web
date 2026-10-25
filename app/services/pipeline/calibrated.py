"""Calibrated frames written by the reduction pipeline on this server, read only.

  <calibrated_dir>/<folder>/[<subfolder>/…]*.fits      (default /Users/greatlab/reduction_pipeline/Calibrated_Science)

The Pipeline page searches the folders, lists a folder's FITS with their headers, and copies the
frames the user ticks into a workspace (autophot.add_files); nothing here is ever written or moved.
"""
import os
import time
from pathlib import Path

from . import config
from . import filters as bands
from .autophot import FITS_EXT, MAX_SCAN, TELESCOPE_YML, NotConfigured, NotFound, PipelineError, _telescope_file

MAX_FOLDERS = 400
MAX_DEPTH = 4
HEADER_KEYS = ('OBJECT', 'TELESCOP', 'INSTRUME', 'FILTER', 'DATE-OBS', 'EXPTIME', 'RA', 'DEC', 'OBJCTRA', 'OBJCTDEC')


def root():
    p = config.paths().get('calibrated_dir')
    if not p or not p.is_dir():
        raise NotConfigured(f'The calibrated science folder {p} is not on this server (Admin → Operations → Pipeline).')
    return p


def status():
    """For the page: {'ok', 'path'}."""
    p = config.paths().get('calibrated_dir')
    return {'ok': bool(p and p.is_dir()), 'path': str(p or '')}


def _inside(rel):
    base = root().resolve()
    p = (base / (rel or '')).resolve()
    if p != base and base not in p.parents:
        raise NotFound('No such folder.')
    return base, p


def _is_fits(name):
    return name.lower().endswith(FITS_EXT) and not name.startswith('.')


def folders(q=''):
    """Folders (any depth up to MAX_DEPTH) that hold FITS, newest first; q filters on the folder path."""
    base = root().resolve()
    q = str(q or '').strip().lower()
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).relative_to(base).parts)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        if depth == 0:
            continue
        rel = str(Path(dirpath).relative_to(base))
        fits = [f for f in filenames if _is_fits(f)]
        if not fits or (q and q not in rel.lower()):
            continue
        try:
            mtime = max(os.stat(os.path.join(dirpath, f)).st_mtime for f in fits)
        except OSError:
            mtime = 0
        out.append({'path': rel, 'n': len(fits), 'mtime': mtime})
    out.sort(key=lambda x: -x['mtime'])
    return {'root': str(base), 'folders': out[:MAX_FOLDERS], 'more': max(0, len(out) - MAX_FOLDERS)}


def folder(rel):
    """The FITS directly in one folder with a header summary and standard filter."""
    from astropy.io import fits as afits
    base, d = _inside(rel)
    if not d.is_dir() or d == base:
        raise NotFound('No such folder.')
    db = bands.telescope_db(_telescope_file() if _telescope_file().is_file() else TELESCOPE_YML)
    names = sorted(f for f in os.listdir(d) if _is_fits(f) and (d / f).is_file())
    files = []
    for name in names[:MAX_SCAN]:
        p = d / name
        info = {'name': name, 'path': str(p.relative_to(base)), 'size': p.stat().st_size}
        try:
            with afits.open(p) as hdul:
                h = dict(hdul[0].header)
                for ext in hdul[1:2]:
                    h = {**dict(ext.header), **h}
            info['header'] = {k: str(h[k]) for k in HEADER_KEYS if h.get(k) not in (None, '')}
            if 'FILTER' not in info['header']:
                f = ' / '.join(str(h[k]) for k in ('FILTER1', 'FILTER2', 'FILTNAME') if h.get(k))
                if f:
                    info['header']['FILTER'] = f
            band, _how, raw = bands.band_of(h, db, name)
            info.update(band=band or '', raw=raw)
            typ = str(h.get('IMAGETYP') or h.get('OBSTYPE') or '').strip()
            if typ:
                info['imagetyp'] = typ
        except Exception as e:
            info['error'] = f'{type(e).__name__}: {e}'
        files.append(info)
    return {'path': str(d.relative_to(base)), 'files': files, 'more': max(0, len(names) - MAX_SCAN),
            'scanned': time.time()}


def file_path(rel):
    """Absolute path of one FITS under the folder (checked to be inside it)."""
    _, p = _inside(rel)
    if not p.is_file() or not _is_fits(p.name):
        raise PipelineError(f'{rel} is no longer in the calibrated science folder.')
    return p
