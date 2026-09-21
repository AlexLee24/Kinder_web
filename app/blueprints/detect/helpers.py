"""DETECT host screening pages and review APIs — helpers (split from detect_routes.py)."""
import os
from collections import OrderedDict
import threading


# Lightweight in-memory cache for DETECT card lightcurves.
_DETECT_LC_CACHE = OrderedDict()

_DETECT_LC_CACHE_MAX_SIZE = int(os.getenv('DETECT_LC_CACHE_MAX_SIZE', '300'))

# In-memory page cache for DETECT results by date.
_DETECT_PAGE_CACHE = OrderedDict()

_DETECT_PAGE_BUILDING = set()

_DETECT_PAGE_CACHE_LOCK = threading.Lock()

_DETECT_PAGE_CACHE_TTL_SEC = int(os.getenv('DETECT_PAGE_CACHE_TTL_SEC', '600'))

_DETECT_PAGE_CACHE_MAX_SIZE = int(os.getenv('DETECT_PAGE_CACHE_MAX_SIZE', '8'))

_DETECT_PAGE_PREWARM_DAYS = int(os.getenv('DETECT_PAGE_PREWARM_DAYS', '3'))

_DETECT_PAGE_CACHE_STATS = {'hits': 0, 'misses': 0, 'evictions': 0}

_DETECT_LC_CACHE_STATS = {'hits': 0, 'misses': 0, 'evictions': 0}

_HOST_STATUS_ORDER = {'review': 0, 'confirmed': 1, 'none': 2, 'unscreened': 3}

UNMATCHED_RECENT_DAYS = 60      # older unmatched objects are TNS edits of old reports, listed apart

_STATUS_NORM = {'Follow-up': 'followup', 'Finish': 'finished', 'Inbox': 'object', 'Snoozed': 'snoozed'}

_SCREEN_KEYS = ('score', 'host_status', 'tags', 'abs_mag', 'abs_mag_band', 'abs_mag_source', 'abs_mag_discovery',
                'peak_mag', 'peak_filter', 'peak_mjd', 'peak_source', 'n_phot', 'z', 'z_source', 'd_dlr',
                'center_sep_arcsec', 'offset_kpc', 'host', 'host_user', 'host_user_by', 'morph', 'mass_cg',
                'sfr_cg', 'known_galactic', 'known_agn', 'tns_type', 'lens_match', 'star_sep',
                'decline_rate', 'decline_filter', 'decline_days', 'kn_model_in', 'kn_model_n', 'run_date')

# ── Follow-up tracker: SWR cache (expensive abs_mag computation) ──────────
_TRACKER_CACHE: dict = {'expires_at': 0.0, 'value': None}

_TRACKER_CACHE_TTL = int(os.getenv('DETECT_TRACKER_CACHE_TTL', '300'))  # 5 min default
