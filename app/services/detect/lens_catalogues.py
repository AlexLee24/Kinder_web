"""What the DETECT pages say about a cat.lens match: which catalogue(s), its grade or probability, and links.

cat.lens merges every lens catalogue into one table; ``reference`` lists each catalogue a lens is in (space
separated, rows within 2" merged) and ``catalogue_ids`` keeps a catalogue's own name / page id for the lens
({"<reference>": {"name": ..., "id": ...}}, scripts/add_lens_csv.py). ``describe()`` turns one row (a cat.lens row,
or a match's stored match_data) into

    {'measure': 'Grade A' | 'P(lens) 0.93' | ..., 'catalogues': [{'ref', 'name', 'site', 'url', 'id'}], 'photo_url'}

``site`` is the catalogue's home page; ``url`` opens this lens there (the Euclid lens page, the SuGOHI search
around it with HSC cutouts, the VizieR row); ``photo_url`` is the Legacy Survey viewer at the lens, for every
catalogue. A reference not in CATALOGUES shows its name with only the photo link. Add a catalogue below.
"""
from urllib.parse import quote, urlencode

SUGOHI_SITE = 'https://www-utap.phys.s.u-tokyo.ac.jp/~oguri/sugohi/'
SUGOHI_SEARCH = SUGOHI_SITE + 'cand.php'
SUGOHI_RADIUS_ARCMIN = 0.05            # 3": the SuGOHI list merges objects within 3"
VIZIER = 'https://vizier.cds.unistra.fr/viz-bin/VizieR-3'
LS_VIEWER = 'https://www.legacysurvey.org/viewer'

_ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']

CATALOGUES = {
    'Euclid-DR1-26Nov12': {'name': 'Euclid DR1 strong lenses (ECLIPSE)', 'site': 'https://euclid-eclipse-lenses.org/',
                           'page': 'euclid', 'scale': 'Grade A / B (lens finding)'},
    'HOLISMOKES2': {'name': 'HOLISMOKES II (Cañameras+2020)', 'site': f'{VIZIER}?-source={quote("J/A+A/644/A163")}',
                    'page': 'vizier', 'vizier': 'J/A+A/644/A163', 'scale': 'Grade 0–3 (mean of inspectors), P(CNN)'},
    # The SuGOHI list (and its search, with HSC cutouts) also carries these HOLISMOKES papers.
    'HOLISMOKES6+13': {'name': 'HOLISMOKES VI + XIII', 'site': SUGOHI_SITE, 'page': 'sugohi'},
    'HOLISMOKES8': {'name': 'HOLISMOKES VIII', 'site': SUGOHI_SITE, 'page': 'sugohi'},
    'HOLISMOKES13': {'name': 'HOLISMOKES XIII', 'site': SUGOHI_SITE, 'page': 'sugohi'},
    'HOLISMOKES16': {'name': 'HOLISMOKES XVI', 'site': SUGOHI_SITE, 'page': 'sugohi'},
    **{f'SuGOHI{n}': {'name': f'SuGOHI {_ROMAN[n - 1]}', 'site': SUGOHI_SITE, 'page': 'sugohi'} for n in range(1, 11)},
}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def sugohi_search_fields(ra, dec) -> dict:
    """The SuGOHI query form (POST only), as a radial search around (ra, dec) with every grade / type."""
    fields = {k: 'ok' for k in ('gradea', 'gradeb', 'gradec', 'galaxy', 'group', 'gsource', 'qsource', 'ylspecz',
                                'nlspecz', 'ysspecz', 'nsspecz', 'showname', 'showimg', 'showra', 'showdec', 'showzl',
                                'showzs', 'showrein', 'showtype', 'showdisc', 'showgrade', 'showref')}
    fields.update(outfmt='html', position='radial', ra0=f'{float(ra):.6f}', dec0=f'{float(dec):.6f}',
                  radius=f'{SUGOHI_RADIUS_ARCMIN:g}', sort='ra', order='asc')
    return fields


def photo_url(ra, dec) -> str:
    return f'{LS_VIEWER}?' + urlencode({'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}', 'layer': 'ls-dr10', 'zoom': 16,
                                        'mark': f'{ra:.6f},{dec:.6f}'})


def _page_url(info, ids, ra, dec):
    page = info.get('page')
    if page == 'euclid' and ids.get('id'):
        return 'https://euclid-eclipse-lenses.org/lens.html?' + urlencode({'lens': ids['id']})
    if ra is None or dec is None:
        return None
    if page == 'sugohi':
        return '/detect/lens/sugohi?' + urlencode({'ra': f'{ra:.6f}', 'dec': f'{dec:.6f}'})
    if page == 'vizier':
        return f'{VIZIER}?' + urlencode({'-source': info['vizier'], '-c': f'{ra:.6f} {dec:+.6f}', '-c.rs': 3})
    return None


def measure(row: dict) -> str | None:
    """'Grade A', 'Grade 2.5 / 3', 'P(lens) 0.93' or both: whatever the catalogue gives."""
    parts = []
    grade = row.get('lens_grade', row.get('grade'))
    grade = None if grade is None else str(grade).strip()
    if grade:
        parts.append(f'Grade {grade} / 3' if _f(grade) is not None else f'Grade {grade}')
    prob = _f(row.get('lens_probability'))
    if prob is not None:
        parts.append(f'P(lens) {prob:.2f}')
    return ' · '.join(parts) or None


def describe(row: dict | None) -> dict | None:
    """Catalogues, grade / probability and links for one cat.lens row (or a lens match's match_data)."""
    if not row:
        return None
    ra, dec = _f(row.get('ra')), _f(row.get('dec'))
    all_ids = row.get('catalogue_ids') or {}
    cats = []
    for ref in str(row.get('reference') or '').split():
        info = CATALOGUES.get(ref, {})
        ids = all_ids.get(ref) or {}
        cats.append({'ref': ref, 'name': info.get('name') or ref, 'site': info.get('site'),
                     'url': _page_url(info, ids, ra, dec), 'id': ids.get('name'), 'scale': info.get('scale')})
    return {'measure': measure(row), 'catalogues': cats,
            'photo_url': photo_url(ra, dec) if ra is not None and dec is not None else None}


def lookup(lens_ids) -> dict:
    """{lens_id: cat.lens row} for these ids, so a stored match shows today's catalogues and ids."""
    ids = sorted({int(i) for i in lens_ids if _f(i) is not None})
    if not ids:
        return {}
    from psycopg2 import extras

    from app.db import get_db_connection
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'cat' AND table_name = 'lens' AND column_name = 'catalogue_ids'")
        extra = ', catalogue_ids' if cur.fetchone() else ''
        cur.execute(f"SELECT lens_id, ra, dec, lens_grade, lens_probability, reference{extra} "
                    "FROM cat.lens WHERE lens_id = ANY(%s)", (ids,))
        return {r['lens_id']: dict(r) for r in cur.fetchall()}


def describe_matches(match_datas) -> list:
    """describe() for each lens match_data (same order), refreshed from cat.lens by lens_id when it can be."""
    match_datas = list(match_datas)
    try:
        fresh = lookup(md.get('lens_id') for md in match_datas if md)
    except Exception:
        fresh = {}
    out = []
    for md in match_datas:
        lid = _f((md or {}).get('lens_id'))
        out.append(describe({**(md or {}), **fresh.get(int(lid), {})} if lid is not None else md))
    return out
