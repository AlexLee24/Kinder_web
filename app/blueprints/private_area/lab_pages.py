"""The Lab section: every page in it, in sidebar order, and who may open it.

LAB_NAV is the one list of Lab pages. The sidebar (_shell.html via the `lab_nav` template global), Admin ›
Permissions and the access gate all read it, so a page added here is listed and guarded everywhere at once.

Who opens what (Admin › Permissions › Lab access):
  * 'lab' — the Lab as a whole. Nobody but admins opens any Lab page unless the Lab rule lets them in.
  * every page — its own rule, or 'lab' (= the same people as the Lab rule).
A rule is a level plus added groups: 'signed_in' (any account that is not a guest), 'member' (GREAT Lab
members), 'admin' (admins only); the groups added to it open it as well. Admins always open everything.
Settings live in auth.system_settings: page_level:<key> and page_perm:<key> (JSON list of group names).
"""
import json

from flask import g, has_request_context, request, session

# (group key, icon, label, [(href, label, page key), …]) — icons are _shell.html icon names.
LAB_NAV = [
    ('pipeline', 'stack', 'Pipeline', [('/pipeline', 'Pipeline', 'pipeline')]),
    ('detect', 'shield-check', 'DETECT', [
        ('/detect', 'TNS-DETECT', 'detect_tns'),
        ('/detect/lsst', 'LSST-DETECT', 'detect_lsst'),
        ('/detect/crossmatch', 'Cross-match', 'detect_crossmatch'),
        ('/detect/archives', 'Archives', 'detect_archives'),
    ]),
    ('triggers', 'send', 'Triggers', [
        ('/daily_trigger', 'Daily Trigger', 'daily_trigger'),
        ('/direct_trigger', 'Direct Trigger', 'direct_trigger'),
        ('/bots', 'Alerts', 'bots'),
    ]),
    ('calendar', 'calendar', 'Calendar', [('/lab_calendar', 'Calendar', 'lab_calendar')]),
    ('specialrun', 'bolt', 'Special Run', [
        ('/special_run/euclid_slsn', 'Euclid-SLSN', 'special_run_euclid_slsn'),
        ('/special_run/lens_sim', 'Lens Simulator', 'special_run_lens_sim'),
    ]),
    ('epessto', 'users', 'ePessto++', [('/epessto_support', 'ePessto++ Support Team', 'epessto_support')]),
    ('labinfo', 'building', 'Lab Info', [
        ('/documents', 'Docs', 'documents'),
        ('/greatlab_info', 'Links', 'greatlab_info'),
    ]),
]

LAB_KEY = 'lab'
PAGES = [key for _g, _i, _l, views in LAB_NAV for _h, _vl, key in views]
PAGE_HREFS = {key: href for _g, _i, _l, views in LAB_NAV for href, _vl, key in views}
PAGE_LABELS = {key: (glabel if len(views) == 1 else f'{glabel} › {vlabel}')
               for _g, _i, glabel, views in LAB_NAV for _h, vlabel, key in views}

LEVELS = {'signed_in': 'Signed-in users', 'member': 'GREAT Lab members', 'admin': 'Admins only'}
PAGE_LEVELS = {'lab': 'Same as Lab', **LEVELS}

# Pages that predate the Lab rule keep their old default ('member'); pages added since follow the Lab.
_DEFAULT_LEVEL = {'special_run_lens_sim': 'admin', LAB_KEY: 'member'}
_LEGACY_MEMBER_PAGES = {'daily_trigger', 'direct_trigger', 'pipeline', 'greatlab_info', 'epessto_support',
                        'documents', 'bots', 'lab_calendar', 'special_run_euclid_slsn'}
# Euclid-SLSN keeps the groups of the old single 'special_run' key until it is set on its own.
_GROUP_FALLBACK = {'special_run_euclid_slsn': 'special_run'}


def _setting(key):
    """auth.system_settings value, read once per request."""
    from app.db import auth
    if not has_request_context():
        return auth.get_setting(key)
    cache = g.setdefault('_lab_settings', {})
    if key not in cache:
        cache[key] = auth.get_setting(key)
    return cache[key]


def forget_cached():
    if has_request_context():
        g.pop('_lab_settings', None)


def _json_list(raw):
    try:
        v = json.loads(raw) if raw else []
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def level(key: str) -> str:
    v = _setting(f'page_level:{key}')
    allowed = LEVELS if key == LAB_KEY else PAGE_LEVELS
    if v in allowed:
        return v
    if key in _DEFAULT_LEVEL:
        return _DEFAULT_LEVEL[key]
    return 'member' if key in _LEGACY_MEMBER_PAGES else 'lab'


def groups(key: str) -> list:
    """Groups added to a page (or to the Lab rule)."""
    raw = _setting(f'page_perm:{key}')
    if raw is None and key in _GROUP_FALLBACK:
        raw = _setting(f'page_perm:{_GROUP_FALLBACK[key]}')
    if raw is None and key == LAB_KEY:
        # Never set: everyone a page was shared with keeps reaching that page.
        out = []
        for p in PAGES:
            for name in groups(p):
                if name not in out:
                    out.append(name)
        return out
    return _json_list(raw)


def _passes(user: dict, key: str) -> tuple[bool, str]:
    lvl = level(key)
    if lvl == 'lab':
        return _passes(user, LAB_KEY)
    user_groups = set(user.get('groups') or [])
    if lvl == 'signed_in' and user.get('role', 'guest') != 'guest':
        return True, 'signed-in user'
    if lvl in ('signed_in', 'member') and ('GREAT_Lab' in user_groups or user.get('is_great_lab_member')):
        return True, 'GREAT Lab member'
    hit = sorted(user_groups & set(groups(key)))
    if hit:
        return True, f'group {hit[0]}'
    return False, {'signed_in': 'guest account', 'member': 'not GREAT Lab, no added group',
                   'admin': 'admins only, no added group'}[lvl]


def explain(user: dict, key: str) -> tuple[bool, str]:
    """(may open, why) for a Lab page key or 'lab'."""
    if not user:
        return False, 'not signed in'
    if user.get('is_admin'):
        return True, 'admin'
    if key != LAB_KEY:
        ok, why = _passes(user, LAB_KEY)
        if not ok:
            return False, f'Lab closed ({why})'
        if level(key) == 'lab':
            return True, why
    return _passes(user, key)


def user_can_open(user: dict, key: str) -> bool:
    return explain(user, key)[0]


def can_open(key: str) -> bool:
    return user_can_open(session.get('user') or {}, key)


def visible_nav(user: dict | None = None) -> list:
    """LAB_NAV for the sidebar: only the pages this viewer may open, as _shell.html groups."""
    user = session.get('user') if user is None else user
    if not user or not user_can_open(user, LAB_KEY):
        return []
    out = []
    for gkey, icon, label, views in LAB_NAV:
        vs = [(href, vlabel) for href, vlabel, key in views if user_can_open(user, key)]
        if vs:
            out.append((gkey, icon, label, '', vs))
    return out


# Pages whose sub-URLs are not theirs: /detect/lens/… and the like serve the Transient pages too.
_EXACT_ONLY = {'detect_tns'}


def page_for_path(path: str) -> str | None:
    """Lab page key a URL belongs to (longest matching href, sub-pages included), or None."""
    best = None
    for key, href in PAGE_HREFS.items():
        if (path == href or (key not in _EXACT_ONLY and path.startswith(href + '/'))) and (best is None or len(href) > len(PAGE_HREFS[best])):
            best = key
    return best


def gate():
    """before_app_request: a Lab page the viewer may not open sends them to sign in or home."""
    if request.method not in ('GET', 'HEAD'):
        return None
    key = page_for_path(request.path)
    if not key:
        return None
    from flask import flash, redirect, url_for
    if 'user' not in session:
        flash('Please log in to open this page.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_open(key):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    return None
