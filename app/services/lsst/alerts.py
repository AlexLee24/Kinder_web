"""Hourly LSST alert watch: new ALeRCE LSST objects near a Lens or DESI galaxy.

1. Fetch every object first detected since the last run (cursor in
   auth.system_settings ``lsst_watch_cursor_mjd``, re-reading ``OVERLAP_DAYS`` before it
   for objects ALeRCE ingests late), classes ``FETCH_CLASSES`` of the stamp classifier.
2. Cross-match: ``cat.lens`` within DETECT's lens radius for every class; ``cat.desi``
   within ``DESI_RADIUS_ARCSEC`` for ``DESI_CLASSES`` only (AGN / VS mostly sit on their
   own galaxy and would bury the transients).
3. Link to TNS: oid inside a ``LSST-AP-DO-<oid>`` internal name, else a TNS object within
   ``TNS_RADIUS_ARCSEC``. Unlinked rows are re-tried every run, so an alert moves to
   "in TNS" as soon as the hourly TNS import brings it in.
4. Upsert matched objects into ``transient.lsst_alerts`` (shown on /detect/lsst), then
   refresh the LSST light curves of linked TNS objects (app/services/lsst/lightcurve.py).

Scheduled hourly at :25 UTC (app/services/jobs/scheduler.py); disable with LSST_WATCH=0.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import healpy as hp
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from psycopg2 import extras

from app.db import get_db_connection
from app.db.auth import get_setting, set_setting
from app.services.lsst import alerce_api
from app.services.lsst.lightcurve import oid_from_internal_names, refresh_lightcurves

logger = logging.getLogger(__name__)

ENABLED = os.getenv("LSST_WATCH", "1").strip().lower() not in ("0", "false", "no", "off")
FETCH_CLASSES = ("SN", "AGN", "VS")      # bogus / asteroid are never fetched
DESI_CLASSES = ("SN",)
DESI_RADIUS_ARCSEC = 30.0                 # same cone as DETECT's DESI cross-match
DESI_MAX_SEP_RE = 3.0                     # ...but keep only galaxies within 3 half-light radii (0.5" floor)
LENS_RADIUS_ARCSEC = 10.0                 # DETECT's LENS_SEARCH_RADIUS_ARCSEC
TNS_RADIUS_ARCSEC = 1.5
MAX_MATCHES_KEPT = 5
OVERLAP_DAYS = 2.0 / 24.0
FIRST_RUN_DAYS = 2.0
RELINK_DAYS = 120.0                       # how long an unlinked alert keeps looking for TNS
CURSOR_KEY = "lsst_watch_cursor_mjd"
LAST_RUN_KEY = "lsst_watch_last_run"
HEALPIX_NSIDE = 8192                      # cat.desi.healpix_8192 (NESTED)

_lock = threading.Lock()
_lens_cache = {"at": 0.0, "rows": None, "coords": None}


def _now_mjd() -> float:
    return time.time() / 86400.0 + 40587.0


def _f(v):
    try:
        v = float(v)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- catalogs

def _lens_catalog():
    """cat.lens (~10k rows) in memory, reloaded every 6 h."""
    if _lens_cache["rows"] is None or time.time() - _lens_cache["at"] > 6 * 3600:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute("SELECT lens_id, ra, dec, z_lens, z_source, lens_grade, known, reference "
                        "FROM cat.lens WHERE ra IS NOT NULL AND dec IS NOT NULL")
            rows = cur.fetchall()
        _lens_cache.update(at=time.time(), rows=rows, coords=SkyCoord(
            np.array([r["ra"] for r in rows]) * u.deg, np.array([r["dec"] for r in rows]) * u.deg))
    return _lens_cache["rows"], _lens_cache["coords"]


def match_lens(ra: np.ndarray, dec: np.ndarray) -> dict:
    """{alert index: [lens match, ...]} nearest first."""
    rows, lcoords = _lens_catalog()
    if not rows or not len(ra):
        return {}
    acoords = SkyCoord(ra * u.deg, dec * u.deg)
    i_lens, i_alert, sep, _ = acoords.search_around_sky(lcoords, LENS_RADIUS_ARCSEC * u.arcsec)
    out = {}
    for il, ia, s in zip(i_lens, i_alert, sep.arcsec):
        r = rows[il]
        out.setdefault(int(ia), []).append({
            "lens_id": r["lens_id"], "ra": r["ra"], "dec": r["dec"], "sep": round(float(s), 2),
            "z_lens": _f(r["z_lens"]), "z_source": _f(r["z_source"]),
            "grade": r["lens_grade"], "known": r["known"], "reference": r["reference"],
        })
    for v in out.values():
        v.sort(key=lambda m: m["sep"])
    return out


def match_desi(ra: np.ndarray, dec: np.ndarray) -> dict:
    """{alert index: [DESI match, ...]} nearest first, one HEALPix join for all alerts."""
    if not len(ra):
        return {}
    radius = np.radians(DESI_RADIUS_ARCSEC / 3600.0)
    keys, pixels = [], []
    for k in range(len(ra)):
        vec = hp.ang2vec(float(ra[k]), float(dec[k]), lonlat=True)
        pix = hp.query_disc(HEALPIX_NSIDE, vec, radius, inclusive=True, fact=4, nest=True)
        keys.extend([k] * len(pix))
        pixels.extend(int(p) for p in pix)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            WITH t AS (SELECT * FROM unnest(%s::int[], %s::bigint[]) AS t(k, pix))
            SELECT t.k, d.targetid, d.ra, d.dec, d.z, d.zerr, d.zwarn, d.spectype,
                   d.shape_r, d.mag_r
              FROM t JOIN cat.desi d ON d.healpix_8192 = t.pix
        """, (keys, pixels))
        rows = cur.fetchall()
    if not rows:
        return {}
    k = np.array([r[0] for r in rows])
    sep = SkyCoord(ra[k] * u.deg, dec[k] * u.deg).separation(
        SkyCoord(np.array([r[2] for r in rows]) * u.deg, np.array([r[3] for r in rows]) * u.deg)).arcsec
    out = {}
    for r, s in zip(rows, sep):
        shape_r = _f(r[8])
        sep_re = float(s) / max(shape_r or 0.0, 0.5)
        if s > DESI_RADIUS_ARCSEC or sep_re > DESI_MAX_SEP_RE:
            continue
        out.setdefault(int(r[0]), []).append({
            "targetid": int(r[1]), "ra": r[2], "dec": r[3], "sep": round(float(s), 2),
            "z": _f(r[4]), "zerr": _f(r[5]), "zwarn": r[6], "spectype": r[7],
            "shape_r": shape_r, "mag_r": _f(r[9]),
            "sep_re": round(sep_re, 2),     # separation in half-light radii
        })
    for v in out.values():
        v.sort(key=lambda m: (m["sep_re"], m["sep"]))
    return out


# --------------------------------------------------------------------------- TNS link

def _tns_index(min_discovery_mjd: float):
    """(oid -> (obj_id, name), SkyCoord, [(obj_id, name)]) for TNS objects since min_discovery_mjd."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT obj_id, name, ra, dec, internal_name FROM transient.objects
             WHERE ra IS NOT NULL AND dec IS NOT NULL
               AND (discovery_date >= %s OR internal_name ~* 'LSST')
        """, (min_discovery_mjd,))
        rows = cur.fetchall()
    by_oid = {}
    for obj_id, name, _ra, _dec, internal in rows:
        oid = oid_from_internal_names(internal)
        if oid:
            by_oid[oid] = (obj_id, name)
    coords = SkyCoord(np.array([r[2] for r in rows]) * u.deg, np.array([r[3] for r in rows]) * u.deg) if rows else None
    return by_oid, coords, [(r[0], r[1]) for r in rows]


def link_tns(oids, ra, dec, index) -> dict:
    """{alert index: (obj_id, name, 'oid' | 'position')}."""
    by_oid, coords, objs = index
    out = {}
    for k, oid in enumerate(oids):
        if int(oid) in by_oid:
            out[k] = (*by_oid[int(oid)], "oid")
    if coords is not None and len(ra):
        acoords = SkyCoord(np.asarray(ra) * u.deg, np.asarray(dec) * u.deg)
        i_obj, i_alert, sep, _ = acoords.search_around_sky(coords, TNS_RADIUS_ARCSEC * u.arcsec)
        best = {}
        for io, ia, s in zip(i_obj, i_alert, sep.arcsec):
            if int(ia) not in out and (int(ia) not in best or s < best[int(ia)][0]):
                best[int(ia)] = (s, io)
        for ia, (_s, io) in best.items():
            out[ia] = (*objs[io], "position")
    return out


# --------------------------------------------------------------------------- store

def _upsert(rows: list[dict]) -> None:
    if not rows:
        return
    with get_db_connection() as conn:
        cur = conn.cursor()
        extras.execute_values(cur, """
            INSERT INTO transient.lsst_alerts
                (oid, ra, dec, firstmjd, lastmjd, n_det, class_name, probability,
                 lens_matches, desi_matches, n_lens, n_desi, best_sep, best_z,
                 obj_id, tns_name, tns_link)
            VALUES %s
            ON CONFLICT (oid) DO UPDATE SET
                ra = EXCLUDED.ra, dec = EXCLUDED.dec, lastmjd = EXCLUDED.lastmjd,
                n_det = EXCLUDED.n_det, class_name = EXCLUDED.class_name,
                probability = EXCLUDED.probability,
                lens_matches = EXCLUDED.lens_matches, desi_matches = EXCLUDED.desi_matches,
                n_lens = EXCLUDED.n_lens, n_desi = EXCLUDED.n_desi,
                best_sep = EXCLUDED.best_sep, best_z = EXCLUDED.best_z,
                obj_id = COALESCE(EXCLUDED.obj_id, transient.lsst_alerts.obj_id),
                tns_name = COALESCE(EXCLUDED.tns_name, transient.lsst_alerts.tns_name),
                tns_link = COALESCE(EXCLUDED.tns_link, transient.lsst_alerts.tns_link),
                updated_at = now()
        """, [(r["oid"], r["ra"], r["dec"], r["firstmjd"], r["lastmjd"], r["n_det"],
               r["class_name"], r["probability"],
               json.dumps(r["lens_matches"]), json.dumps(r["desi_matches"]),
               len(r["lens_matches"]), len(r["desi_matches"]), r["best_sep"], r["best_z"],
               r["obj_id"], r["tns_name"], r["tns_link"]) for r in rows])
        conn.commit()


def _relink_unlinked(index) -> int:
    """Give every still-unlinked recent alert another chance to find its TNS object."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT oid, ra, dec FROM transient.lsst_alerts "
                    "WHERE obj_id IS NULL AND firstmjd >= %s", (_now_mjd() - RELINK_DAYS,))
        rows = cur.fetchall()
        if not rows:
            return 0
        links = link_tns([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], index)
        if links:
            extras.execute_batch(cur,
                "UPDATE transient.lsst_alerts SET obj_id = %s, tns_name = %s, tns_link = %s, "
                "updated_at = now() WHERE oid = %s",
                [(obj_id, name, how, rows[k][0]) for k, (obj_id, name, how) in links.items()])
            conn.commit()
        return len(links)


# --------------------------------------------------------------------------- run

def process_objects(items: list[dict]) -> dict:
    """Cross-match + TNS-link a batch of ALeRCE list_objects rows and store the matched ones."""
    uniq = {}
    for it in items:
        uniq[int(it["oid"])] = it
    items = list(uniq.values())
    if not items:
        return {"fetched": 0, "lens": 0, "desi": 0, "stored": 0, "linked": 0}
    oids = np.array([int(i["oid"]) for i in items], dtype=np.int64)
    ra = np.array([float(i["meanra"]) for i in items])
    dec = np.array([float(i["meandec"]) for i in items])
    lens = match_lens(ra, dec)
    desi_idx = np.array([k for k, i in enumerate(items) if i.get("class_name") in DESI_CLASSES], dtype=int)
    desi = {int(desi_idx[k]): v for k, v in match_desi(ra[desi_idx], dec[desi_idx]).items()} if len(desi_idx) else {}
    hits = sorted(set(lens) | set(desi))
    index = _tns_index(float(min(i["firstmjd"] for i in items)) - 30.0)
    links = link_tns(oids[hits], ra[hits], dec[hits], index) if hits else {}
    rows = []
    for n, k in enumerate(hits):
        it = items[k]
        lm = lens.get(k, [])[:MAX_MATCHES_KEPT]
        dm = desi.get(k, [])[:MAX_MATCHES_KEPT]
        best = (lm or dm)[0]
        obj_id, name, how = links.get(n, (None, None, None))
        rows.append({
            "oid": int(it["oid"]), "ra": float(it["meanra"]), "dec": float(it["meandec"]),
            "firstmjd": _f(it.get("firstmjd")), "lastmjd": _f(it.get("lastmjd")),
            "n_det": it.get("n_det"), "class_name": it.get("class_name"),
            "probability": _f(it.get("probability")),
            "lens_matches": lm, "desi_matches": dm,
            "best_sep": best["sep"], "best_z": best.get("z") if "z" in best else best.get("z_lens"),
            "obj_id": obj_id, "tns_name": name, "tns_link": how,
        })
    _upsert(rows)
    relinked = _relink_unlinked(index)
    return {"fetched": len(items), "lens": len(lens), "desi": len(desi), "stored": len(rows),
            "linked": sum(1 for r in rows if r["obj_id"]), "relinked": relinked}


def run_watch(lookback_days: float | None = None, refresh_lc: bool = True) -> dict:
    """Hourly job. ``lookback_days`` re-reads that much history instead of using the cursor
    (the daily sweep, for objects ALeRCE ingested late)."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already running"}
    started = time.monotonic()
    try:
        now = _now_mjd()
        if lookback_days is not None:
            mjd_from = now - lookback_days
            cursor = None
        else:
            cursor = _f(get_setting(CURSOR_KEY))
            mjd_from = (cursor - OVERLAP_DAYS) if cursor else now - FIRST_RUN_DAYS
        items = []
        for cls in FETCH_CLASSES:
            items.extend(alerce_api.iter_new_objects(mjd_from, now + 0.1, cls))
        res = process_objects(items)
        if lookback_days is None and items:
            newest = max(float(i["firstmjd"]) for i in items)
            set_setting(CURSOR_KEY, f"{max(newest, cursor or 0):.6f}")
        res.update(window=[round(mjd_from, 4), round(now, 4)], seconds=round(time.monotonic() - started, 1))
        logger.info("event=lsst_watch_done %s", " ".join(f"{k}={v}" for k, v in res.items()))
        if refresh_lc:
            try:
                res["lightcurves"] = refresh_lightcurves()
            except Exception as e:
                logger.error("event=lsst_lc_refresh_error error=%s", e)
                res["lightcurves"] = {"error": str(e)}
        set_setting(LAST_RUN_KEY, json.dumps({"at": time.time(), **{k: v for k, v in res.items() if k != "lightcurves"},
                                              "lc": res.get("lightcurves")}, default=str))
        return res
    finally:
        _lock.release()


def run_daily_sweep() -> dict:
    """Once a day after the Chilean night: re-read the last 1.5 days."""
    return run_watch(lookback_days=1.5, refresh_lc=False)


def is_running() -> bool:
    return _lock.locked()


# --------------------------------------------------------------------------- page data

def list_alerts(view: str = "pre_tns", catalog: str = "all", days: float = 14.0, limit: int = 500) -> list[dict]:
    clauses = ["a.firstmjd >= %s"]
    params = [_now_mjd() - days]
    if view == "pre_tns":
        clauses.append("a.obj_id IS NULL")
    elif view == "in_tns":
        clauses.append("a.obj_id IS NOT NULL")
    if catalog == "lens":
        clauses.append("a.n_lens > 0")
    elif catalog == "desi":
        clauses.append("a.n_desi > 0")
    params.append(limit)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"""
            SELECT a.*, o.name AS obj_name, o.name_prefix, o.status AS obj_status, o.type AS obj_type,
                   s.refreshed_at AS lc_refreshed_at, s.n_points AS lc_points
              FROM transient.lsst_alerts a
              LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
              LEFT JOIN transient.lsst_lc_state s ON s.obj_id = a.obj_id
             WHERE {' AND '.join(clauses)}
             ORDER BY (a.n_lens > 0) DESC, a.firstmjd DESC
             LIMIT %s
        """, params)
        rows = cur.fetchall()
    for r in rows:
        r["alerce_url"] = alerce_api.explorer_url(r["oid"])
        r["first_utc"] = _mjd_to_utc(r["firstmjd"])
        r["last_utc"] = _mjd_to_utc(r["lastmjd"])
    return rows


def _mjd_to_utc(mjd) -> str:
    if mjd is None:
        return "—"
    return datetime.fromtimestamp((float(mjd) - 40587.0) * 86400.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def summary(days: float = 14.0) -> dict:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT count(*) FILTER (WHERE obj_id IS NULL),
                   count(*) FILTER (WHERE obj_id IS NOT NULL),
                   count(*) FILTER (WHERE n_lens > 0),
                   count(*) FILTER (WHERE n_desi > 0)
              FROM transient.lsst_alerts WHERE firstmjd >= %s
        """, (_now_mjd() - days,))
        pre, linked, n_lens, n_desi = cur.fetchone()
        cur.execute("SELECT count(*), max(refreshed_at), count(*) FILTER (WHERE error IS NOT NULL) "
                    "FROM transient.lsst_lc_state")
        lc_n, lc_last, lc_err = cur.fetchone()
    last = get_setting(LAST_RUN_KEY)
    try:
        last = json.loads(last) if last else None
    except ValueError:
        last = None
    return {"pre_tns": pre, "in_tns": linked, "lens": n_lens, "desi": n_desi,
            "lc_tracked": lc_n, "lc_last": lc_last, "lc_errors": lc_err,
            "last_run": last, "cursor": _f(get_setting(CURSOR_KEY)), "running": is_running()}
