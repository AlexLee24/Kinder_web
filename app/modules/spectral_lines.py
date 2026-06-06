"""
Fetch and cache NIST atomic spectral line data for the spectrum viewer.

Lines are queried via astroquery.nist, filtered, deduplicated, and cached
as JSON. Cache TTL is 30 days — atomic wavelengths don't change.
"""

import json
import logging
import threading
import time
from pathlib import Path

import astropy.units as u

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / '_spectral_lines_cache.json'
_CACHE_TTL  = 30 * 24 * 3600   # 30 days

_build_lock   = threading.Lock()
_build_thread: threading.Thread | None = None

# Same element grouping as the existing JS _SPEC_LINES / _SPEC_LINE_COLORS
_IONS: list[tuple[str, str]] = [
    ('H I',    'H'),
    ('He I',   'He'), ('He II',  'He'),
    ('Ca I',   'Ca'), ('Ca II',  'Ca'),
    ('Si II',  'Si'), ('Si III', 'Si'),
    ('O I',    'O'),  ('O II',   'O'),  ('O III',  'O'),
    ('Na I',   'Na'),
    ('Fe II',  'Fe'), ('Fe III', 'Fe'),
    ('S II',   'S'),  ('S III',  'S'),
    ('C II',   'C'),  ('C III',  'C'),  ('C IV',   'C'),
    ('Mg I',   'Mg'), ('Mg II',  'Mg'),
    ('N II',   'N'),  ('N III',  'N'),
    ('Ti II',  'Ti'),
    ('Ba II',  'Ba'),
]

WL_MIN = 3000   # Å
WL_MAX = 10000  # Å

# Traditional astronomical labels for well-known transitions.
# Key: (nist_ion_name, round(wavelength_Å))  — ±1 Å tolerance applied at lookup.
_TRAD: dict[tuple[str, int], str] = {
    # Hydrogen Balmer + Paschen
    ('H I',   6563): 'Hα',
    ('H I',   4861): 'Hβ',
    ('H I',   4341): 'Hγ',
    ('H I',   4102): 'Hδ',
    ('H I',   3970): 'Hε',
    ('H I',   3889): 'Hζ',
    ('H I',   3835): 'Hη',
    ('H I',   9229): 'Pa δ',
    ('H I',   9546): 'Pa γ',
    # Calcium
    ('Ca II', 3934): 'Ca II K',
    ('Ca II', 3968): 'Ca II H',
    ('Ca I',  4227): 'Ca I 4227',
    ('Ca II', 8498): 'Ca II 8498',
    ('Ca II', 8542): 'Ca II 8542',
    ('Ca II', 8662): 'Ca II 8662',
    ('Ca II', 7292): '[Ca II] 7292',
    ('Ca II', 7291): '[Ca II] 7292',   # rounding variant
    ('Ca II', 7324): '[Ca II] 7324',
    # Oxygen
    ('O I',   7772): 'O I 7772',
    ('O I',   8446): 'O I 8446',
    ('O I',   6300): '[O I] 6300',
    ('O I',   6364): '[O I] 6364',
    ('O II',  3727): '[O II] 3727',
    ('O III', 4363): '[O III] 4363',
    ('O III', 4959): '[O III] 4959',
    ('O III', 5007): '[O III] 5007',
    # Sodium
    ('Na I',  5890): 'Na I D2',
    ('Na I',  5896): 'Na I D1',
    # Iron
    ('Fe II', 7155): '[Fe II] 7155',
    ('Fe III', 4658): '[Fe III] 4658',
    ('Fe III', 5270): '[Fe III] 5270',
    # Sulfur
    ('S II',  5454): 'S II 5454',
    ('S II',  5640): 'S II 5640',
    ('S II',  6716): '[S II] 6716',
    ('S II',  6731): '[S II] 6731',
    ('S III', 6312): '[S III] 6312',
    ('S III', 9069): '[S III] 9069',
    ('S III', 9531): '[S III] 9531',
    # Nitrogen
    ('N II',  5755): '[N II] 5755',
    ('N II',  6548): '[N II] 6548',
    ('N II',  6584): '[N II] 6584',
    ('N III', 4641): 'N III 4641',
    # Magnesium
    ('Mg I',  4571): 'Mg I] 4571',
    ('Mg I',  5167): 'Mg I b1',
    ('Mg I',  5173): 'Mg I b2',
    ('Mg I',  5184): 'Mg I b3',
    ('Mg II', 4481): 'Mg II 4481',
    # Carbon
    ('C II',  4267): 'C II 4267',
    ('C II',  6578): 'C II 6578',
    ('C II',  7231): 'C II 7231',
    ('C III', 4647): 'C III 4647',
    ('C III', 5696): 'C III 5696',
    ('C IV',  5801): 'C IV 5801',
    ('C IV',  5812): 'C IV 5812',
    # Barium
    ('Ba II', 4554): 'Ba II 4554',
    ('Ba II', 4934): 'Ba II 4934',
    ('Ba II', 6142): 'Ba II 6142',
    ('Ba II', 6497): 'Ba II 6497',
}


def _trad_label(ion_name: str, wl: float) -> str | None:
    """Look up traditional name with ±1 Å rounding tolerance."""
    k = round(wl)
    return (
        _TRAD.get((ion_name, k))
        or _TRAD.get((ion_name, k + 1))
        or _TRAD.get((ion_name, k - 1))
    )


def _parse_float(raw: str) -> float | None:
    s = raw.strip().replace('*', '').replace('?', '')
    if s in ('--', '', 'nan', 'None', 'masked'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_forbidden(type_str: str) -> bool:
    return 'M1' in type_str or 'E2' in type_str


def _query_ion(ion_name: str, group: str) -> list[dict]:
    """Query NIST for one ion over [WL_MIN, WL_MAX] Å (air wavelengths)."""
    from astroquery.nist import Nist

    try:
        table = Nist.query(
            WL_MIN * u.AA,
            WL_MAX * u.AA,
            linename=ion_name,
            wavelength_type='vac+air',
        )
    except Exception as exc:
        logger.warning('NIST %s query failed: %s', ion_name, exc)
        return []

    cols = table.colnames
    raw_lines = []
    for row in table:
        # Wavelength — Ritz preferred over Observed (more precise)
        wl = None
        for col in ('Ritz', 'Observed'):
            if col in cols:
                wl = _parse_float(str(row[col]))
                if wl is not None:
                    break
        if wl is None or not (WL_MIN <= wl <= WL_MAX):
            continue

        rel       = _parse_float(str(row['Rel.']))  if 'Rel.'  in cols else None
        typ       = str(row['Type']).strip()         if 'Type'  in cols else ''
        forbidden = _is_forbidden(typ)
        has_trad  = _trad_label(ion_name, wl) is not None

        # Keep: measurable relative intensity, forbidden transition, OR known traditional line
        if rel is None and not forbidden and not has_trad:
            continue

        raw_lines.append({'wl': wl, 'rel': rel or 0.0, 'forbidden': forbidden})

    if not raw_lines:
        return []

    # Deduplicate: within a 2 Å window, keep the line with the highest Rel.
    raw_lines.sort(key=lambda x: x['wl'])
    deduped = []
    i = 0
    while i < len(raw_lines):
        j = i + 1
        while j < len(raw_lines) and raw_lines[j]['wl'] - raw_lines[i]['wl'] < 2.0:
            j += 1
        best = max(raw_lines[i:j], key=lambda x: x['rel'])
        deduped.append(best)
        i = j

    # Build output
    result = []
    for entry in deduped:
        wl    = entry['wl']
        trad  = _trad_label(ion_name, wl)
        if trad:
            label = trad
        elif entry['forbidden']:
            elem  = ion_name.split()[0]
            label = f'[{elem}] {wl:.1f}'
        else:
            label = f'{ion_name} {wl:.1f}'

        result.append({'w': round(wl, 2), 'label': label, 'ion': ion_name, 'group': group})

    logger.debug('NIST %s: %d lines (raw %d)', ion_name, len(result), len(raw_lines))
    return result


def _build_cache() -> list[dict]:
    """Query all ions and write cache file. Called in background thread."""
    all_lines: list[dict] = []
    for ion_name, group in _IONS:
        lines = _query_ion(ion_name, group)
        all_lines.extend(lines)
        time.sleep(0.5)   # polite rate-limiting for NIST servers

    all_lines.sort(key=lambda l: l['w'])
    payload = {'built_at': time.time(), 'count': len(all_lines), 'lines': all_lines}
    try:
        _CACHE_PATH.write_text(json.dumps(payload, separators=(',', ':')))
        logger.info('Spectral lines cache built: %d lines → %s', len(all_lines), _CACHE_PATH.name)
    except Exception as exc:
        logger.error('Failed to write spectral lines cache: %s', exc)
    return all_lines


def _load_cache() -> list[dict] | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(_CACHE_PATH.read_text())
        age = time.time() - payload.get('built_at', 0)
        if age > _CACHE_TTL:
            logger.info('Spectral lines cache expired (%.0f h old)', age / 3600)
            return None
        return payload.get('lines')
    except Exception as exc:
        logger.warning('Spectral lines cache unreadable: %s', exc)
        return None


def get_spectral_lines() -> list[dict]:
    """Return cached NIST lines. Returns [] and triggers async build if cache is cold."""
    lines = _load_cache()
    if lines is not None:
        return lines
    warm_cache_async()
    return []


def warm_cache_async() -> None:
    """Start background NIST fetch if not already running."""
    global _build_thread
    with _build_lock:
        if _build_thread is not None and _build_thread.is_alive():
            return
        _build_thread = threading.Thread(
            target=_build_cache, name='nist-spec-lines', daemon=True
        )
        _build_thread.start()
        logger.info('NIST spectral lines background build started (%d ions)', len(_IONS))


def rebuild_cache() -> list[dict]:
    """Force-rebuild the cache synchronously. Intended for admin/CLI use."""
    if _CACHE_PATH.exists():
        _CACHE_PATH.unlink()
    return _build_cache()
