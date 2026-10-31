"""Small client for the ALeRCE LSST API (https://api-lsst.alerce.online).

Behaviour measured on 2026-10-30/31:

* ``list_objects`` returns one row per (object, classifier) unless ``classifier`` is
  given, so every query here pins ``CLASSIFIER`` to get one row per oid.
* ``firstmjd`` / ``lastmjd`` take ``[from, to]``; a single value means ">= value".
* ``page_size`` is capped at 200 (it was unlimited until 2026-10-30).
* A query that matches nothing is slow (40-55 s) and sometimes answers 504
  "Query timed out", so every call retries.
* The ALeRCE oid is the Rubin diaObjectId, the number in TNS internal names
  ``LSST-AP-DO-<oid>``.
* Fluxes (psfFlux, scienceFlux) are in nJy: m_AB = 31.4 - 2.5 log10(flux).
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api-lsst.alerce.online"
CLASSIFIER = "stamp_classifier_rubin_beta_20260421"
PAGE_SIZE = 200
OID_BATCH = 200          # list_objects accepts at most 200 oids per call
TIMEOUT = 120
RETRIES = 4

# LSST integer band -> filter letter (the API's own band_map; u is 6, not 0)
BAND_MAP = {1: "g", 2: "r", 3: "i", 4: "z", 5: "y", 6: "u"}

_session = requests.Session()
_session.headers["User-Agent"] = "Kinder-LSST-watch"


def _get(path: str, params: dict):
    """GET with retries on 5xx / timeouts; returns parsed JSON or raises."""
    last = None
    for attempt in range(RETRIES):
        try:
            r = _session.get(BASE_URL + path, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After") or 5 * (attempt + 1))
                last = f"HTTP {r.status_code}: {r.text[:120]}"
                logger.warning("ALeRCE %s %s, retry in %.0fs", path, last, wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"ALeRCE {path} HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            last = str(e)
            logger.warning("ALeRCE %s %s, retry", path, e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"ALeRCE {path} failed after {RETRIES} tries: {last}")


def iter_new_objects(firstmjd_from: float, firstmjd_to: float, class_name: str):
    """Every LSST object of one class whose first detection is in the window,
    oldest first (new arrivals land on the last page, so paging stays stable)."""
    page = 1
    while True:
        data = _get("/object_api/list_objects", {
            "survey": "lsst",
            "classifier": CLASSIFIER,
            "class_name": class_name,
            "firstmjd": [firstmjd_from, firstmjd_to],
            "order_by": "firstmjd",
            "order_mode": "ASC",
            "page": page,
            "page_size": PAGE_SIZE,
        })
        yield from data.get("items") or []
        if not data.get("has_next"):
            return
        page += 1


def objects_by_oid(oids) -> dict:
    """{oid: list_objects row} for the given oids (batched 200 per call)."""
    oids = [str(o) for o in oids]
    out = {}
    for i in range(0, len(oids), OID_BATCH):
        chunk = oids[i:i + OID_BATCH]
        data = _get("/object_api/list_objects", {
            "survey": "lsst",
            "classifier": CLASSIFIER,
            "oid": chunk,
            "page_size": PAGE_SIZE,
        })
        for item in data.get("items") or []:
            out[int(item["oid"])] = item
    return out


def lightcurve(oid) -> dict:
    """{"detections": [...], "non_detections": [...], "forced_photometry": [...]}"""
    return _get("/lightcurve_api/lightcurve", {"oid": str(oid), "survey_id": "lsst"})


def band_letter(point: dict) -> str:
    raw = point.get("band")
    bmap = point.get("band_map") or {}
    if str(raw) in bmap:
        return bmap[str(raw)]
    try:
        return BAND_MAP.get(int(raw), f"lsst{raw}")
    except (TypeError, ValueError):
        return str(raw)


def explorer_url(oid) -> str:
    return f"https://lsst.alerce.online/object/{oid}?survey=lsst"
