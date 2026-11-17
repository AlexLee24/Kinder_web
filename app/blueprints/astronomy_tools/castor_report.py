"""CASTOR check (/castor/snr_check): measured S/N of Lulin photometry against CASTOR's prediction for the same frame.

Not linked from any page and not indexed: reached only by its address, and only with the password. The report and
the password live in one file outside git, app/data/castor_report/snr_check.json (the repository is public):

    {"password_hash": "<werkzeug generate_password_hash(...)>",
     "title": "...", "generated": "2026-11-18", "intro": "...",
     "notes": [{"title": "...", "items": ["...", ...]}, ...],
     "rows": [{"tel": "LOT", "cam": "Sophia", "band": "r", "target": "SN2025wny", "image": "2026-09-12T194159",
               "date": "2026-09-12T19:41", "exp": "1x300s", "X": 1.69, "fwhm": 2.38, "ts": "w/o TS",
               "mag": 19.475, "err": 0.035, "snr_meas": 37.4, "chi2": 1.46, "snr_noise": 45.1,
               "snr_castor": 42.7, "ratio": 0.87, "ratio_noise": 1.06, "kinder": ""}, ...]}

No file: 404. Changing password_hash signs everyone out (the session keeps a fingerprint of the hash).
"""
import hashlib
import json
import logging
import statistics

from flask import abort, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.core import rate_limit
from app.paths import DATA_DIR

from . import astronomy_tools_bp
from .helpers import _client_ip

logger = logging.getLogger(__name__)

REPORT_FILE = DATA_DIR / 'castor_report' / 'snr_check.json'
SESSION_KEY = 'castor_snr_check'
LOGIN_BURST, LOGIN_WINDOW_S = 8, 600          # password tries per IP
BAND_ORDER = {b: i for i, b in enumerate('ugrizy')}
CAMERAS = {'Sophia': 'Sophia 2048B', 'SLT_DZ936': 'Andor iKon-L DZ936', 'SLT_DU934P': 'Andor iKon-M DU934P'}
CAMERA_ORDER = {'Sophia': 0, 'SLT_DZ936': 1, 'SLT_DU934P': 2}


def load_report():
    try:
        return json.loads(REPORT_FILE.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.error('castor report: cannot read %s: %s', REPORT_FILE, e)
        return None


def _fingerprint(report):
    return hashlib.sha256((report.get('password_hash') or '').encode()).hexdigest()[:16]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def groups(rows):
    """Rows by telescope, camera and band (LOT first, then SLT's cameras; u→z), each with its medians."""
    by = {}
    for r in rows:
        by.setdefault((r.get('tel', ''), r.get('cam', ''), r.get('band', '')), []).append(r)
    out = []
    for (tel, cam, band) in sorted(by, key=lambda k: (k[0], CAMERA_ORDER.get(k[1], 9), BAND_ORDER.get(k[2], 9), k[2])):
        items = sorted(by[(tel, cam, band)], key=lambda r: (r.get('target', ''), r.get('date', '')))
        ratio = [x for x in (_num(r.get('ratio')) for r in items) if x is not None]
        noise = [x for x in (_num(r.get('ratio_noise')) for r in items) if x is not None]
        out.append({'tel': tel, 'cam': cam, 'camera': CAMERAS.get(cam, cam), 'band': band, 'rows': items,
                    'n': len(items),
                    'ratio': (statistics.median(ratio), min(ratio), max(ratio)) if ratio else None,
                    'ratio_noise': (statistics.median(noise), min(noise), max(noise)) if noise else None})
    return out


def _no_index(resp):
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@astronomy_tools_bp.route('/castor/snr_check', methods=['GET', 'POST'])
def castor_snr_check():
    report = load_report()
    if not report or not report.get('password_hash'):
        abort(404)
    error = None
    if request.method == 'POST':
        if not rate_limit.allow(f'castor_report:{_client_ip()}', LOGIN_BURST, LOGIN_WINDOW_S):
            error = 'Too many tries. Wait a few minutes.'
        elif check_password_hash(report['password_hash'], (request.form.get('password') or '')[:256]):
            session[SESSION_KEY] = _fingerprint(report)
            return _no_index(redirect(url_for('astronomy_tools.castor_snr_check'), 303))
        else:
            error = 'Wrong password.'
    if session.get(SESSION_KEY) != _fingerprint(report):
        return _no_index(make_response(render_template('castor_report.html', locked=True, error=error,
                                                       current_path='/castor/snr_check'), 401 if error else 200))
    rows = report.get('rows') or []
    return _no_index(make_response(render_template(
        'castor_report.html', locked=False, report=report, groups=groups(rows), n_rows=len(rows),
        n_targets=len({r.get('target') for r in rows}), current_path='/castor/snr_check')))


@astronomy_tools_bp.route('/castor/snr_check/lock', methods=['POST'])
def castor_snr_check_lock():
    session.pop(SESSION_KEY, None)
    return _no_index(redirect(url_for('astronomy_tools.castor_snr_check'), 303))
