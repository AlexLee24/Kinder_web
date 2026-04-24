"""tns_gap_filler.py
Runs hourly after auto_tns_download. Finds kinder_id gaps in the current year
and fills them one-by-one via the TNS object API (60 s delay to avoid rate limits).

Kinder_id scheme: year * 1_000_000 + bijective-base-26 rank of lowercase suffix.
  'a'=1, 'z'=26, 'aa'=27, ... → 2026a = 2026000001, 2026aa = 2026000027
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, date as _date, timezone

import requests
from dotenv import load_dotenv
from psycopg2 import extras

try:
    from modules.database import get_db_connection
    from modules.database.transient import sync_kinder_ids
except ImportError:
    from database import get_db_connection
    from database.transient import sync_kinder_ids

# ---- Paths & env ----
_module_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root  = os.path.normpath(os.path.join(_module_dir, '..', '..'))
load_dotenv(os.path.join(_repo_root, 'kinder.env'))

bot_id   = os.getenv("TNS_BOT_ID")
bot_name = os.getenv("TNS_BOT_NAME")
api_key  = os.getenv("TNS_API_KEY")

# ---- Logger ----
logger = logging.getLogger("tns_gap_filler")

# ---- Thread state ----
_gap_filler_thread: threading.Thread | None = None
_gap_filler_lock = threading.Lock()
_stop_event = threading.Event()

# ---- MJD helper ----
_MJD_EPOCH = _date(1858, 11, 17)


def _to_mjd(s) -> float | None:
    if s is None:
        return None
    from datetime import datetime as _dt
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = _dt.strptime(str(s).strip(), fmt)
            return (_date(dt.year, dt.month, dt.day) - _MJD_EPOCH).days + dt.hour / 24.0
        except ValueError:
            continue
    return None


def _parse_ra(s) -> float | None:
    """Accept decimal degrees or HH:MM:SS.sss → decimal degrees."""
    if s is None:
        return None
    s = str(s).strip()
    if ':' in s:
        parts = s.split(':')
        try:
            h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
            return (h + m / 60.0 + sec / 3600.0) * 15.0
        except (IndexError, ValueError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_dec(s) -> float | None:
    """Accept decimal degrees or ±DD:MM:SS.sss → decimal degrees."""
    if s is None:
        return None
    s = str(s).strip()
    if ':' in s:
        neg = s.startswith('-')
        parts = s.lstrip('+-').split(':')
        try:
            d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
            val = d + m / 60.0 + sec / 3600.0
            return -val if neg else val
        except (IndexError, ValueError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


# ---- Kinder_id ↔ name conversion ----

def _kinder_id_to_name(kid: int) -> str:
    """2026000027 → '2026aa', 2026000003 → '2026C' (single letter = uppercase per TNS)"""
    year = kid // 1_000_000
    rank = kid % 1_000_000
    letters = []
    r = rank
    while r > 0:
        r, rem = divmod(r - 1, 26)
        letters.append(chr(rem + ord('a')))
    suffix = ''.join(reversed(letters))
    if len(suffix) == 1:
        suffix = suffix.upper()
    return str(year) + suffix


def _name_to_kinder_id(name: str) -> int | None:
    """'2026aa' → 2026000027, '2026C' → 2026000003 (accepts upper/lowercase)"""
    import re
    m = re.match(r'^(\d{4})([a-zA-Z]+)$', name)
    if not m:
        return None
    year   = int(m.group(1))
    suffix = m.group(2).lower()  # normalise before rank calculation
    rank   = sum((ord(c) - 96) * (26 ** i) for i, c in enumerate(reversed(suffix)))
    return year * 1_000_000 + rank


# ---- Gap detection ----

def _find_gaps(year: int) -> list[int]:
    """Return sorted list of kinder_ids present in [min..max] for year but absent in DB.
    Considers both objects that have kinder_id set AND objects whose name maps to a
    kinder_id in range (e.g. uppercase single-letter '2026A' that has kinder_id=NULL).
    """
    lo = year * 1_000_000 + 1
    hi = (year + 1) * 1_000_000
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Objects with kinder_id already filled
            cur.execute(
                "SELECT kinder_id FROM transient.objects "
                "WHERE kinder_id >= %s AND kinder_id < %s",
                (lo, hi),
            )
            existing = {row[0] for row in cur.fetchall()}

            # Objects whose name maps to this year but kinder_id not yet set
            cur.execute(
                "SELECT name FROM transient.objects "
                "WHERE kinder_id IS NULL AND name ~ %s",
                (f'^{year}[a-zA-Z]+$',),
            )
            for (name,) in cur.fetchall():
                kid = _name_to_kinder_id(name)
                if kid and lo <= kid < hi:
                    existing.add(kid)
    except Exception as e:
        logger.error("_find_gaps DB error: %s", e)
        return []

    if not existing:
        return []

    max_kid = max(existing)
    return sorted(set(range(lo, max_kid + 1)) - existing)


# ---- TNS API helpers ----

def _tns_headers() -> dict:
    return {
        'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'
    }


def _search_tns_exists(name: str) -> bool:
    """Use Search API to cheaply check if a name exists on TNS.
    Returns True only when at least one matching object is found."""
    url = "https://www.wis-tns.org/api/get/search"
    payload = json.dumps({"objname": name})
    try:
        resp = requests.post(
            url,
            headers=_tns_headers(),
            data={"api_key": api_key, "data": payload},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("TNS Search HTTP %s for %s", resp.status_code, name)
            return False
        j = resp.json()
        if j.get("id_code") != 200:
            return False
        data = j.get("data", [])
        # Search API returns data as a list directly, or {"reply": [...]}
        if isinstance(data, list):
            results = data
        elif isinstance(data, dict):
            results = data.get("reply", [])
        else:
            results = []
        return len(results) > 0
    except Exception as e:
        logger.error("_search_tns_exists(%s): %s", name, e)
        return False


def _get_tns_object(name: str) -> dict | None:
    """Call Get Object API; return the data dict or None if not found / error.
    Response layout: json['data'] contains the object fields directly."""
    url = "https://www.wis-tns.org/api/get/object"
    payload = json.dumps({
        "objname": name,
        "photometry": "0",
        "spectra": "0",
    })
    try:
        resp = requests.post(
            url,
            headers=_tns_headers(),
            data={"api_key": api_key, "data": payload},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("TNS Get HTTP %s for %s", resp.status_code, name)
            return None
        j = resp.json()
        if j.get("id_code") != 200:
            logger.debug("TNS Get no result for %s: %s", name, j.get("id_message"))
            return None
        data = j.get("data") or {}
        return data if data else None
    except Exception as e:
        logger.error("_get_tns_object(%s): %s", name, e)
        return None


def _str_from(val) -> str | None:
    """Extract name string from TNS dict-or-string field."""
    if isinstance(val, dict):
        return val.get("name") or None
    return val or None


def _reporters_list(val) -> list | None:
    if not val:
        return None
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("name") or str(item))
            else:
                parts.append(str(item))
        return parts or None
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()] or None
    return None


def _insert_tns_object(reply: dict) -> bool:
    """
    Insert a TNS object-API reply into transient.objects.
    Uses kinder_id (computed from objname) as obj_id for consistency with
    the migrated DB scheme.
    Returns True if a row was actually inserted (rowcount > 0).
    """
    bare_name = reply.get("objname") or reply.get("name")
    if not bare_name:
        return False

    kid = _name_to_kinder_id(bare_name)
    if kid is None:
        logger.warning("Cannot compute kinder_id for name=%r, skipping", bare_name)
        return False

    # TNS Get Object API returns fields directly under json['data']
    # Try both 'declination' (CSV / older API) and 'dec' (newer API response)
    ra  = _parse_ra(reply.get("ra"))
    dec = _parse_dec(reply.get("declination") or reply.get("dec"))

    if ra is None or dec is None:
        logger.warning("Skipping %s: missing coordinates (ra=%s, dec=%s)",
                       bare_name, reply.get("ra"), reply.get("declination") or reply.get("dec"))
        return False

    row = (
        kid,                                             # obj_id = kinder_id
        reply.get("name_prefix"),                        # name_prefix
        bare_name,                                       # name
        ra,                                              # ra  (decimal degrees)
        dec,                                             # dec (decimal degrees)
        reply.get("redshift"),                           # redshift
        _str_from(reply.get("object_type")),             # type  (dict → name)
        _str_from(reply.get("reporting_group")),         # report_group
        _str_from(reply.get("source_group")),            # source_group
        _to_mjd(reply.get("discoverydate")),             # discovery_date
        reply.get("discoverymag"),                       # discovery_mag
        _str_from(reply.get("discmagfilter")),           # discovery_filter (dict → name)
        _reporters_list(reply.get("reporters")) or [],   # reporters (TEXT[] NOT NULL)
        _to_mjd(reply.get("time_received")),             # received_date
        reply.get("internal_names"),                     # internal_name
        reply.get("discovery_ads_bibcode"),              # discovery_ADS
        reply.get("class_ads_bibcodes"),                 # class_ADS
        _to_mjd(reply.get("creationdate")),              # creation_date
        _to_mjd(reply.get("last_photometry_date")),      # last_phot_date
        _to_mjd(reply.get("lastmodified")),              # last_modified_date
    )

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO transient.objects (
                    obj_id, name_prefix, name, ra, dec, redshift,
                    type, report_group, source_group,
                    discovery_date, discovery_mag, discovery_filter,
                    reporters, received_date, internal_name,
                    discovery_ADS, class_ADS, creation_date,
                    last_phot_date, last_modified_date,
                    kinder_id, status
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,'Inbox'
                )
                ON CONFLICT DO NOTHING
                """,
                row + (kid,),   # kinder_id column = same value
            )
            inserted = cur.rowcount > 0
            conn.commit()
        return inserted
    except Exception as e:
        logger.error("_insert_tns_object(%s): %s", bare_name, e)
        return False


# ---- Core fill function ----

def fill_year_gaps(year: int, delay: float = 60.0) -> int:
    """
    1. sync_kinder_ids() to flush any recently-imported objects
    2. Find gaps in kinder_ids for `year`
    3. For each gap: fetch from TNS, insert if found (60 s between calls)
    4. sync_kinder_ids() again after filling
    Returns number of objects actually inserted.
    """
    # Ensure kinder_id column is current before gap detection
    n_sync = sync_kinder_ids()
    if n_sync:
        logger.info("pre-scan sync: assigned %d kinder_ids", n_sync)

    gaps = _find_gaps(year)
    if not gaps:
        logger.info("No kinder_id gaps for year %d", year)
        return 0

    logger.info("Found %d gaps for year %d (range: %s…%s)",
                len(gaps), year,
                _kinder_id_to_name(gaps[0]),
                _kinder_id_to_name(gaps[-1]))

    filled = 0
    for i, kid in enumerate(gaps):
        if _stop_event.is_set():
            logger.info("Gap filler stop requested, aborting at %d/%d",
                        i, len(gaps))
            break

        name = _kinder_id_to_name(kid)
        logger.debug("Checking gap %d/%d: %s (kinder_id=%d)",
                     i + 1, len(gaps), name, kid)

        # Step 1: cheap Search API check — skip Get Object if not on TNS
        exists = _search_tns_exists(name)
        if not exists:
            logger.debug("Not found on TNS (search): %s", name)
            if i < len(gaps) - 1 and not _stop_event.is_set():
                time.sleep(delay)
            continue

        # Step 2: full Get Object API
        if i > 0:   # small extra gap between search and get for the same object
            time.sleep(5)
        data = _get_tns_object(name)
        if data:
            ok = _insert_tns_object(data)
            if ok:
                logger.info("Filled: %s", name)
                filled += 1
            else:
                logger.debug("Insert skipped (likely already exists): %s", name)
        else:
            logger.debug("Get Object returned nothing for %s", name)

        # Respect rate limit between objects
        if i < len(gaps) - 1 and not _stop_event.is_set():
            time.sleep(delay)

    n_sync2 = sync_kinder_ids()
    if n_sync2:
        logger.info("post-fill sync: assigned %d kinder_ids", n_sync2)

    logger.info("Gap fill done — year %d: filled %d / %d gaps",
                year, filled, len(gaps))
    return filled


# ---- Daemon loop ----

def _main_loop(delay: float = 60.0):
    # Initial delay: let bulk downloads (at :15 and :45) settle
    logger.info("Gap filler waiting 10 min before first scan…")
    _stop_event.wait(600)  # 10-minute grace period

    while not _stop_event.is_set():
        year = datetime.now(timezone.utc).year
        try:
            fill_year_gaps(year, delay=delay)
        except Exception:
            logger.exception("Unexpected error in gap filler loop")
        # Wait up to 1 hour, but wake immediately if stop is requested
        _stop_event.wait(3600)

    logger.info("Gap filler loop exited.")


def start_gap_filler(log_dir=None, delay: float = 60.0):
    """Start gap filler as a daemon thread. Safe to call multiple times."""
    global _gap_filler_thread
    with _gap_filler_lock:
        if _gap_filler_thread is not None and _gap_filler_thread.is_alive():
            logger.info("Gap filler already running.")
            return
        _stop_event.clear()
        if log_dir and not logger.handlers:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, "tns_gap_filler.log"))
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(fh)
            logger.setLevel(logging.INFO)
        _gap_filler_thread = threading.Thread(
            target=_main_loop,
            args=(delay,),
            daemon=True,
            name="tns_gap_filler",
        )
        _gap_filler_thread.start()
        logger.info("Gap filler daemon thread started.")


def stop_gap_filler():
    """Signal the daemon thread to stop after the current object."""
    _stop_event.set()


# ---- Standalone / one-shot test ----

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    year = datetime.now(timezone.utc).year
    # Allow overriding year via CLI: python tns_gap_filler.py 2025
    if len(sys.argv) > 1:
        try:
            year = int(sys.argv[1])
        except ValueError:
            pass

    logger.info("========= GAP FILLER START  year=%d =========", year)
    n = fill_year_gaps(year, delay=60.0)
    logger.info("========= GAP FILLER DONE   filled=%d =========", n)
