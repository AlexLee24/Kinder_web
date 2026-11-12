"""Tools › Spectrum (/spectrum): a DESI DR1 / EDR coadded spectrum by TARGETID, plotted with Plotly.

* GET /spectrum?targetid=…                      the page (spectrum.html + js/spectrum.js); loads at once when a TARGETID is given
* GET /api/spectrum/desi/<targetid>             JSON from app/services/astro/desi_spectrum.py
      ?release=dr1|edr &survey= &program=        pick one coadd when the TARGETID has several
      &ra= &dec=                                 position for a TARGETID that is not in cat.desi
      &refresh=1                                 ignore the disk cache
"""
import logging
import re

from flask import jsonify, render_template, request

from app.services.astro import desi_spectrum

from . import astronomy_tools_bp
from .helpers import _client_ip, _rate_ok_burst

logger = logging.getLogger(__name__)

_WORD = re.compile(r'^[a-z0-9]{1,16}$')


def _word(name):
    v = (request.args.get(name) or '').strip().lower()
    return v if _WORD.match(v) else None


def _coord(name, lo, hi):
    try:
        v = float(request.args.get(name, ''))
    except ValueError:
        return None
    return v if lo <= v <= hi else None


@astronomy_tools_bp.route('/spectrum')
def spectrum():
    tid = (request.args.get('targetid') or '').strip()
    return render_template('spectrum.html', current_path='/spectrum',
                           targetid=tid if tid.isdigit() else '',
                           release=_word('release') or '', survey=_word('survey') or '',
                           program=_word('program') or '')


@astronomy_tools_bp.route('/api/spectrum/desi/<int:targetid>')
def spectrum_desi_api(targetid):
    if not _rate_ok_burst(_client_ip(), 'desi_spectrum', 12, 60.0):
        return jsonify({'error': 'Too many spectrum requests; wait a minute.'}), 429
    try:
        data = desi_spectrum.get_spectrum(
            targetid, release=_word('release'), survey=_word('survey'), program=_word('program'),
            ra=_coord('ra', 0.0, 360.0), dec=_coord('dec', -90.0, 90.0),
            refresh=request.args.get('refresh') == '1')
    except desi_spectrum.SpectrumError as e:
        return jsonify({'error': str(e)}), e.status
    except Exception:
        logger.exception('[SPECTRUM] %s failed', targetid)
        return jsonify({'error': 'Reading the DESI spectrum failed; see the server log.'}), 500
    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'private, no-cache'   # Kinder's disk cache answers in ms
    return resp
