"""Which HiPS server Kinder's Aladin sky views load their survey tiles from (Admin › Site).

Every Aladin view (object page + its NED view, ePESSTO++ NED view, Telescope Simulator) goes through one browser
module, static/js/hips_fallback.js (KinderHips). It knows each survey's address on three servers — CDS (alasky,
Strasbourg), ESA (ESASky, Madrid) and NASA IRSA (Caltech) — checks which of them answer, and loads a survey from
the admin's preferred server, falling back to the next one in SERVERS order that has it.

Only the preferred server is stored here (auth.system_settings ``site:aladin_server``); the browser reads it from
GET /api/aladin/config. The survey list and the per-server addresses live in hips_fallback.js.
"""
import time

SETTING_KEY = 'site:aladin_server'
# (key, short label, full name) — also the fallback order after the preferred one
SERVERS = [
    ('cds', 'CDS', 'CDS alasky — Strasbourg'),
    ('esa', 'ESA', 'ESASky — ESA, Madrid'),
    ('irsa', 'IRSA', 'NASA IRSA — Caltech'),
]
SERVER_KEYS = tuple(k for k, _, _ in SERVERS)
DEFAULT = 'cds'
_CACHE_S = 30
_cache = {'at': 0.0, 'value': None}


def get_preferred() -> str:
    """The admin's preferred server key, cached for _CACHE_S seconds per process."""
    now = time.monotonic()
    if _cache['value'] is not None and now - _cache['at'] < _CACHE_S:
        return _cache['value']
    from app.db.auth import get_setting
    value = (get_setting(SETTING_KEY) or '').strip().lower()
    if value not in SERVER_KEYS:
        value = DEFAULT
    _cache.update(at=now, value=value)
    return value


def set_preferred(key: str) -> bool:
    key = (key or '').strip().lower()
    if key not in SERVER_KEYS:
        raise ValueError(f'Unknown server {key!r}')
    from app.db.auth import set_setting
    ok = set_setting(SETTING_KEY, key)
    if ok:
        _cache.update(at=time.monotonic(), value=key)
    return ok


def order(preferred: str):
    """Server keys to try: the preferred one first, then the rest in SERVERS order."""
    return [preferred] + [k for k in SERVER_KEYS if k != preferred]


def config() -> dict:
    preferred = get_preferred()
    return {'preferred': preferred, 'order': order(preferred),
            'servers': [{'key': k, 'label': label, 'name': name} for k, label, name in SERVERS]}
