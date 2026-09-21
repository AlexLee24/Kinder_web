"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — helpers (split from astronomy_tools_routes.py)."""
import os
import re
import time
import threading
import matplotlib
from flask import request


matplotlib.use('Agg')

# ── Public API rate limiter ────────────────────────────────────────────────────
_rl_lock  = threading.Lock()

_rl_store = {}   # {(ip, endpoint_key): last_allowed_timestamp}

_RL_INTERVAL = 1.0  # seconds

def _client_ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()

def _rate_ok(ip, key, interval=None):
    """Return True and record the timestamp if the request is allowed.
    interval overrides _RL_INTERVAL for this specific call."""
    limit = interval if interval is not None else _RL_INTERVAL
    now = time.monotonic()
    k = (ip, key)
    with _rl_lock:
        if now - _rl_store.get(k, 0) < limit:
            return False
        _rl_store[k] = now
        if len(_rl_store) > 20000:
            cutoff = now - 120
            for old in [x for x, t in list(_rl_store.items()) if t < cutoff]:
                _rl_store.pop(old, None)
        return True

from app.paths import BLUEPRINTS_DIR, CASTOR_SRC, SHARED_PLOTS_DIR

_SHARE_DIR = str(SHARED_PLOTS_DIR)   # app/data/shared_plots

_SHARE_ID_RE = re.compile(r'^[a-f0-9]{24}$')

_SHARE_TTL_SECS = 60 * 86400  # 60 days

# ===============================================================================
# EXPOSURE TIME CALCULATOR (CASTOR engine)
# ===============================================================================
_CASTOR_ETC_BODY_PATH = os.path.join(
    os.path.dirname(__file__), 'templates', 'castor_etc_body.html'
)

_CASTOR_PRESETS_PATH = str(CASTOR_SRC / 'castorGUI' / 'data' / 'presets.json')

# Absolute path to planners/ov_plot/ (sibling blueprint folder)
_PLANNERS_OV_PLOT_DIR = str(BLUEPRINTS_DIR / 'planners' / 'ov_plot')

# ===============================================================================
# PUBLIC JSON API  (no key required · 1 request / second / IP / endpoint)
# ===============================================================================

_API_DOCS = {
    'api': 'Kinder Astronomy Tools — Public JSON API',
    'rate_limit': '1 request per second per IP per endpoint',
    'cosmology_defaults': {
        'H0': 67.7, 'Om0': 0.309, 'Tcmb0': 2.725,
        'reference': 'Planck 2018 (A&A 641 A6)'
    },
    'endpoints': {
        'GET /api/distance': {
            'description': 'Luminosity distance and/or absolute magnitude from redshift',
            'params': {
                'z':      '(required) redshift',
                'z_err':  '(optional) redshift uncertainty',
                'm':      '(optional) apparent magnitude → enables absolute magnitude output',
                'A':      '(optional) extinction, default 0',
                'H0':     '(optional) Hubble constant km/s/Mpc, default 67.7',
                'Om0':    '(optional) matter density Ω_m, default 0.309',
                'Tcmb0':  '(optional) CMB temperature K, default 2.725',
            },
            'example': '/api/distance?z=0.039&m=15.3&A=0.1',
        },
        'GET /api/coords': {
            'description': 'Convert RA or DEC between HMS/DMS and decimal degrees',
            'params': {
                'ra_hms':  '(optional) RA in hh:mm:ss.s  → returns decimal degrees',
                'ra_deg':  '(optional) RA in decimal °   → returns HMS',
                'dec_dms': '(optional) DEC in ±dd:mm:ss  → returns decimal degrees',
                'dec_deg': '(optional) DEC in decimal °  → returns DMS',
            },
            'note': 'Provide ra_hms OR ra_deg, and/or dec_dms OR dec_deg in one call',
            'example': '/api/coords?ra_hms=12:34:56.78&dec_dms=-23:45:12.34',
        },
        'GET /api/date': {
            'description': 'Convert between MJD, JD and calendar date (UTC)',
            'params': {
                'mjd':  '(optional) Modified Julian Date',
                'jd':   '(optional) Julian Date',
                'date': '(optional) ISO date string, e.g. 2024-06-01T12:00:00',
            },
            'note': 'Provide exactly one of the three parameters',
            'example': '/api/date?mjd=59000.5',
        },
        'GET /api/finding_chart/image': {
            'description': 'Finding chart PNG image returned directly (Content-Type: image/png). Rate limit: 1 req/30s.',
            'params': {
                'ra':         '(required) Right Ascension — HMS or decimal degrees',
                'dec':        '(required) Declination — DMS or decimal degrees',
                'name':       '(optional) Object name label, default "Target"',
                'survey':     '(optional) Image source: DSS2 Red | DESI-color | DESI-r | PS1-color | … (default DESI-color)',
                'fov':        '(optional) Field of view in arcmin, default 10',
                'invert':     '(optional) 1 = white background (single-band surveys only), default 0',
                'mag_limit':  '(optional) Faintest star to annotate (mag), default 15',
                'show_names': '(optional) 0/1 show star names, default 1',
                'show_mag':   '(optional) 0/1 show magnitude labels, default 1',
            },
            'example': '/api/finding_chart/image?ra=12:34:56.78&dec=-23:45:12.34&survey=DESI-color&fov=10',
        },
        'GET /api/objects/<name>': {
            'description': 'Object metadata. Add ?api_key= to also receive photometry and spectroscopy filtered by your access permissions.',
            'auth': 'No key → metadata only (public). Valid api_key → + photometry + spectroscopy.',
            'params': {
                'name':    '(path) Object name: full (AT2025wny, SN2024abc) or year+letters (2025wny)',
                'api_key': '(optional) Your API key — enables photometry and spectroscopy in the response',
            },
            'example': '/api/objects/2025wny',
            'example_auth': '/api/objects/2025wny?api_key=YOUR_KEY',
        },
        'GET /api/visibility/image': {
            'description': 'Nightly visibility (altitude vs time) plot returned as JPEG. Rate limit: 1 req/15s.',
            'params': {
                'date': '(required) Observation date YYYY-MM-DD',
                'ra':   '(required) Target RA — HMS or decimal degrees',
                'dec':  '(required) Target Dec — DMS or decimal degrees',
                'name': '(optional) Target name, default "Target"',
                'lon':  '(optional) Observatory longitude ddd:mm:ss or decimal (default Lulin 120:52:21.5)',
                'lat':  '(optional) Observatory latitude ±dd:mm:ss or decimal (default Lulin 23:28:10.0)',
                'alt':  '(optional) Observatory altitude in metres, default 2800',
                'tz':   '(optional) UTC offset integer, default 8',
            },
            'example': '/api/visibility/image?date=2026-06-07&ra=12:34:56.78&dec=-23:45:12.34',
        },
    },
}

_FINDING_CHART_SURVEYS = [
    {'value': 'DSS2 Red',   'group': 'DSS', 'label': 'DSS2 Red'},
    {'value': 'DSS2 Blue',  'group': 'DSS', 'label': 'DSS2 Blue'},
    {'value': 'DSS2 IR',    'group': 'DSS', 'label': 'DSS2 IR'},
    {'value': 'DSS',        'group': 'DSS', 'label': 'DSS1'},
    {'value': 'DESI-color', 'group': 'DESI Legacy Survey DR10', 'label': 'DESI LS — Color (grz)', 'default': True},
    {'value': 'DESI-g',     'group': 'DESI Legacy Survey DR10', 'label': 'DESI LS — g-band'},
    {'value': 'DESI-r',     'group': 'DESI Legacy Survey DR10', 'label': 'DESI LS — r-band'},
    {'value': 'DESI-z',     'group': 'DESI Legacy Survey DR10', 'label': 'DESI LS — z-band'},
    {'value': 'DESI-i',     'group': 'DESI Legacy Survey DR10', 'label': 'DESI LS — i-band'},
    {'value': 'PS1-color',  'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — Color (gri)'},
    {'value': 'PS1-g',      'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — g-band'},
    {'value': 'PS1-r',      'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — r-band'},
    {'value': 'PS1-i',      'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — i-band'},
    {'value': 'PS1-z',      'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — z-band'},
    {'value': 'PS1-y',      'group': 'Pan-STARRS (PS1)',        'label': 'PS1 — y-band'},
]
