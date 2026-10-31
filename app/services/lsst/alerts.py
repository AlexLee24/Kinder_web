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
4. Upsert matched objects into ``transient.lsst_alerts`` (shown on /detect/lsst), keep their
   magnitudes current, run DETECT on them (app/services/lsst/detect.py, reviewed on
   /detect/lsst/review), then refresh the LSST light curves of linked TNS objects
   (app/services/lsst/lightcurve.py).

Scheduled hourly at :25 UTC (app/services/jobs/scheduler.py); disable with LSST_WATCH=0.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import healpy as hp
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from psycopg2 import extras

try:
    import fcntl
except ImportError:  # non-POSIX: only the per-process lock
    fcntl = None

from app.db import get_db_connection
from app.db.auth import get_setting, set_setting
from app.paths import DATA_DIR
from app.services.lsst import alerce_api
from app.services.lsst.lightcurve import lightcurve_points, oid_from_internal_names, refresh_lightcurves

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
STATUS_KEY = "lsst_watch_status"          # current / last run: state, phase, log (shown on /detect/lsst)
LOG_LINES = 200
HEALPIX_NSIDE = 8192                      # cat.desi.healpix_8192 (NESTED)

_lock = threading.Lock()
_LOCK_FILE = str(DATA_DIR / "lsst_watch.lock")   # flock: one run per host (scheduler + gunicorn workers)
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


def match_lens(ra: np.ndarray, dec: np.ndarray, radius_arcsec: float = LENS_RADIUS_ARCSEC) -> dict:
    """{alert index: [lens match, ...]} nearest first."""
    rows, lcoords = _lens_catalog()
    if not rows or not len(ra):
        return {}
    acoords = SkyCoord(ra * u.deg, dec * u.deg)
    i_lens, i_alert, sep, _ = acoords.search_around_sky(lcoords, radius_arcsec * u.arcsec)
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


def match_desi(ra: np.ndarray, dec: np.ndarray, radius_arcsec: float = DESI_RADIUS_ARCSEC,
               max_sep_re: float | None = DESI_MAX_SEP_RE, include_zwarn: bool = False) -> dict:
    """{alert index: [DESI match, ...]} nearest first, one HEALPix join for all alerts.
    ``max_sep_re`` None keeps every galaxy in the cone; galaxies with ZWARN != 0 (unreliable
    redshift) are left out unless ``include_zwarn``."""
    if not len(ra):
        return {}
    radius = np.radians(radius_arcsec / 3600.0)
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
        if s > radius_arcsec or (max_sep_re is not None and sep_re > max_sep_re):
            continue
        if not include_zwarn and r[6]:
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

def process_objects(items: list[dict], desi_classes=DESI_CLASSES) -> dict:
    """Cross-match + TNS-link a batch of ALeRCE list_objects rows and store the matched ones.
    ``desi_classes`` None matches every class with DESI (a manual cross-match)."""
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
    desi_idx = np.array([k for k, i in enumerate(items)
                         if desi_classes is None or i.get("class_name") in desi_classes], dtype=int)
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


class _RunLog:
    """Progress of one watch run, kept in auth.system_settings (``STATUS_KEY``) so every
    gunicorn worker (and the page polling /api/detect/lsst/status) sees the same thing."""

    def __init__(self, trigger: str, params: dict):
        self.status = {"state": "running", "trigger": trigger, "params": params, "pid": os.getpid(),
                       "started_at": time.time(), "updated_at": time.time(), "finished_at": None,
                       "phase": "starting", "log": []}
        self._last_write = 0.0
        self.line(f"Started ({trigger}): " + ", ".join(f"{k}={v}" for k, v in params.items()))

    def line(self, msg: str, phase: str | None = None, force: bool = True) -> None:
        logger.info("event=lsst_watch_log %s", msg)
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.status["log"] = (self.status["log"] + [f"{stamp}  {msg}"])[-LOG_LINES:]
        if phase:
            self.status["phase"] = phase
        self._save(force)

    def _save(self, force: bool) -> None:
        now = time.time()
        if force or now - self._last_write > 3:      # progress lines: at most one write per 3 s
            self.status["updated_at"] = now
            set_setting(STATUS_KEY, json.dumps(self.status, default=str))
            self._last_write = now

    def finish(self, state: str, result: dict | None = None) -> None:
        self.status.update(state=state, finished_at=time.time(), phase=state, result=result)
        self._save(True)


def _file_lock():
    """Non-blocking flock shared by every process on this host; None when another run holds it."""
    if fcntl is None:
        return open(os.devnull)
    fh = open(_LOCK_FILE, "a")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def run_watch(lookback_days: float | None = None, refresh_lc: bool = True, trigger: str = "hourly") -> dict:
    """Hourly job. ``lookback_days`` re-reads that much history instead of using the cursor
    (the daily sweep, and manual runs that want more than "since the last run")."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already running"}
    fh = _file_lock()
    if fh is None:
        _lock.release()
        return {"skipped": True, "reason": "already running in another process"}
    started = time.monotonic()
    log = _RunLog(trigger, {"lookback_days": lookback_days if lookback_days is not None else "since last run",
                            "light_curves": refresh_lc})
    try:
        now = _now_mjd()
        if lookback_days is not None:
            mjd_from = now - lookback_days
            cursor = None
        else:
            cursor = _f(get_setting(CURSOR_KEY))
            mjd_from = (cursor - OVERLAP_DAYS) if cursor else now - FIRST_RUN_DAYS
        log.line(f"Reading ALeRCE LSST objects first detected {_mjd_to_utc(mjd_from)} – now (UTC)", phase="fetching")
        items = []
        for cls in FETCH_CLASSES:
            n0, t0 = len(items), time.monotonic()
            for k, it in enumerate(alerce_api.iter_new_objects(mjd_from, now + 0.1, cls), 1):
                items.append(it)
                if k % (alerce_api.PAGE_SIZE * 10) == 0:
                    log.line(f"  {cls}: {k} objects so far…", force=False)
            log.line(f"  {cls}: {len(items) - n0} objects ({time.monotonic() - t0:.0f} s)")
        pruned = prune_zwarn_matches()
        if pruned:
            log.line(f"Removed ZWARN DESI matches from {pruned} stored alert(s)")
        log.line(f"Cross-matching {len(items)} objects with Lens and DESI, linking to TNS…", phase="matching")
        res = process_objects(items)
        log.line(f"  {res.get('lens', 0)} near a lens, {res.get('desi', 0)} near a DESI galaxy; "
                 f"{res.get('stored', 0)} stored, {res.get('linked', 0)} in TNS, {res.get('relinked', 0)} older ones newly linked")
        if lookback_days is None and items:
            newest = max(float(i["firstmjd"]) for i in items)
            set_setting(CURSOR_KEY, f"{max(newest, cursor or 0):.6f}")
        try:
            res["trigger_renamed"] = sync_trigger_targets()
            if res["trigger_renamed"]:
                log.line(f"  {res['trigger_renamed']} Daily Trigger target(s) renamed to their TNS name")
        except Exception as e:
            logger.error("event=lsst_trigger_sync_error error=%s", e)
            log.line(f"  Daily Trigger rename failed: {e}")
        log.line("Latest / brightest absolute magnitudes of recent alerts…", phase="magnitudes")
        try:
            res["mags"] = refresh_mags(progress=lambda m: log.line("  " + m, force=False))
            log.line(f"  {res['mags']['computed']} computed, {res['mags']['failed']} failed")
        except Exception as e:
            logger.error("event=lsst_mags_error error=%s", e)
            log.line(f"  Magnitudes failed: {e}")
        log.line("DETECT: host rule, score, tags and images…", phase="DETECT")
        try:
            from app.services.lsst import detect
            res["detect"] = detect.screen_alerts(progress=lambda m: log.line("  " + m, force=False))
            d = res["detect"]
            log.line(f"  {d['screened']} screened, {d['images']} image(s), {d['failed']} failed")
        except Exception as e:
            logger.error("event=lsst_detect_error error=%s", e)
            log.line(f"  DETECT failed: {e}")
        res.update(window=[round(mjd_from, 4), round(now, 4)], seconds=round(time.monotonic() - started, 1))
        logger.info("event=lsst_watch_done %s", " ".join(f"{k}={v}" for k, v in res.items()))
        if refresh_lc:
            log.line("Refreshing LSST light curves of TNS objects…", phase="light curves")
            try:
                res["lightcurves"] = refresh_lightcurves(progress=lambda m: log.line("  " + m, force=False))
                lc = res["lightcurves"]
                log.line(f"  {lc.get('refreshed', 0)} refreshed, {lc.get('failed', 0)} failed "
                         f"({lc.get('due', 0)} had new points, {lc.get('linked', 0)} linked objects)")
            except Exception as e:
                logger.error("event=lsst_lc_refresh_error error=%s", e)
                res["lightcurves"] = {"error": str(e)}
                log.line(f"  Light-curve refresh failed: {e}")
        set_setting(LAST_RUN_KEY, json.dumps({"at": time.time(), "trigger": trigger,
                                              **{k: v for k, v in res.items() if k != "lightcurves"},
                                              "lc": res.get("lightcurves")}, default=str))
        log.line(f"Done in {time.monotonic() - started:.0f} s")
        log.finish("done", {k: v for k, v in res.items() if k != "lightcurves"})
        return res
    except Exception as e:
        logger.exception("event=lsst_watch_error")
        log.line(f"FAILED: {e}")
        log.finish("error")
        raise
    finally:
        fh.close()
        _lock.release()


def run_daily_sweep() -> dict:
    """Once a day after the Chilean night: re-read the last 1.5 days."""
    return run_watch(lookback_days=1.5, refresh_lc=False, trigger="daily sweep")


def is_running() -> bool:
    if _lock.locked():
        return True
    fh = _file_lock()
    if fh is None:
        return True
    fh.close()
    return False


def run_status() -> dict:
    """The current / last run as the page shows it (state, phase, log lines)."""
    try:
        st = json.loads(get_setting(STATUS_KEY) or "null") or {}
    except ValueError:
        st = {}
    running = is_running()
    if st.get("state") == "running" and not running:
        st["state"] = "interrupted"      # the process died mid-run (restart / deploy)
    st["running"] = running
    return st


def start_manual_run(lookback_days: float | None) -> bool:
    """Start a watch run in a background thread; False when one is already running."""
    if is_running():
        return False
    threading.Thread(target=_run_quietly, args=(lookback_days,), name="lsst-watch-manual", daemon=True).start()
    return True


def _run_quietly(lookback_days):
    try:
        run_watch(lookback_days=lookback_days, refresh_lc=True, trigger="manual")
    except Exception:
        pass   # already logged and written to the run status


# --------------------------------------------------------------------------- magnitudes

MAGS_DAYS = 60.0               # keep magnitudes current for alerts first seen this recently
MAGS_PER_RUN = 300             # light curves downloaded per run for magnitudes (~1 s each)


def _redshift_for(alert: dict) -> tuple[float | None, str | None]:
    """DETECT's order: the DESI host's redshift (nearest in half-light radii, ZWARN == 0),
    else the TNS redshift of the linked object."""
    for m in alert.get("desi_matches") or []:
        z = _f(m.get("z"))
        if z and z > 0 and not m.get("zwarn"):
            return z, "DESI"
    z = _f(alert.get("tns_redshift"))
    if z and z > 0:
        return z, "TNS"
    return None, None


def compute_mags(alert: dict, points: list[tuple]) -> dict:
    """Latest and brightest LSST point (binned psfFlux > 0) and their absolute magnitudes,
    with DETECT's absolute_magnitude (cosmology, K = 2.5 log(1+z), SFD extinction)."""
    from function.module.screening import absolute_magnitude  # DETECT, on sys.path via app.paths
    out = {"n_points": len(points), "latest_mag": None, "latest_filter": None, "latest_mjd": None,
           "peak_mag": None, "peak_filter": None, "peak_mjd": None, "abs_latest": None, "abs_peak": None}
    z, z_source = _redshift_for(alert)
    out["z_used"], out["z_source"] = z, z_source
    if not points:
        return out
    latest = max(points, key=lambda p: p[0])
    peak = min(points, key=lambda p: p[1])
    out.update(latest_mjd=latest[0], latest_mag=round(latest[1], 3), latest_filter=latest[3],
               peak_mjd=peak[0], peak_mag=round(peak[1], 3), peak_filter=peak[3])
    if z:
        out["abs_latest"] = absolute_magnitude(latest[1], z, alert["ra"], alert["dec"], latest[3]).get("abs_mag")
        out["abs_peak"] = absolute_magnitude(peak[1], z, alert["ra"], alert["dec"], peak[3]).get("abs_mag")
    return out


def save_mags(oid: int, mags: dict, lastmjd: float | None = None, points: list[tuple] | None = None) -> None:
    """Store the magnitudes, and the binned light curve itself (DETECT's screen reads it)."""
    cols = ("latest_mag", "latest_filter", "latest_mjd", "peak_mag", "peak_filter", "peak_mjd",
            "abs_latest", "abs_peak", "z_used", "z_source", "n_points")
    lc = None if points is None else json.dumps([[round(m, 6), round(mag, 4), round(e, 4), f]
                                                 for m, mag, e, f in points])
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE transient.lsst_alerts SET {', '.join(c + ' = %s' for c in cols)}, "
                    "lc_points = COALESCE(%s::jsonb, lc_points), "
                    "mags_lastmjd = COALESCE(%s, mags_lastmjd), mags_at = now() WHERE oid = %s",
                    [mags.get(c) for c in cols] + [lc, lastmjd, int(oid)])
        conn.commit()


def _alerts_for_mags(oids=None) -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        where, params = ("a.oid = ANY(%s)", [list(oids)]) if oids is not None else \
                        ("a.firstmjd >= %s AND (a.n_lens > 0 OR a.n_desi > 0)", [_now_mjd() - MAGS_DAYS])
        cur.execute(f"""
            SELECT a.oid, a.ra, a.dec, a.desi_matches, a.lastmjd, a.mags_lastmjd, a.mags_at,
                   o.redshift AS tns_redshift
              FROM transient.lsst_alerts a LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
             WHERE {where}
        """, params)
        return cur.fetchall()


def refresh_mags(progress=None, max_objects: int = MAGS_PER_RUN) -> dict:
    """Recompute magnitudes of recent alerts that have a newer ALeRCE point than last time
    (or none yet). New watch hits come first."""
    say = progress or (lambda _m: None)
    rows = {int(r["oid"]): r for r in _alerts_for_mags()}
    latest = alerce_api.objects_by_oid(rows.keys()) if rows else {}
    due = []
    for oid, r in rows.items():
        lastmjd = _f((latest.get(oid) or {}).get("lastmjd")) or _f(r["lastmjd"])
        if r["mags_at"] is None or (lastmjd and (r["mags_lastmjd"] is None or lastmjd > r["mags_lastmjd"] + 1e-6)):
            due.append((r["mags_at"] is not None, -(lastmjd or 0), oid, lastmjd))
    due.sort()
    todo = due[:max_objects]
    say(f"{len(rows)} recent alerts; {len(due)} need magnitudes; computing {len(todo)}"
        + (f" (the other {len(due) - len(todo)} next run)" if len(due) > len(todo) else ""))
    done = failed = 0
    for n, (_new, _neg, oid, lastmjd) in enumerate(todo, 1):
        try:
            points = lightcurve_points(alerce_api.lightcurve(oid))
            save_mags(oid, compute_mags(rows[oid], points), lastmjd, points)
            done += 1
        except Exception as e:
            failed += 1
            logger.warning("event=lsst_mags_failed oid=%s error=%s", oid, e)
        if n % 50 == 0:
            say(f"{n}/{len(todo)} magnitudes done")
    return {"recent": len(rows), "due": len(due), "computed": done, "failed": failed}


def prune_zwarn_matches() -> int:
    """Drop DESI matches with ZWARN != 0 from stored alerts (they are no longer matched).
    Returns how many alerts changed; an alert left with no match drops out of the lists."""
    changed = 0
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""SELECT oid, lens_matches, desi_matches FROM transient.lsst_alerts
                        WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(desi_matches) m
                                       WHERE COALESCE((m->>'zwarn')::bigint, 0) <> 0)""")
        for r in cur.fetchall():
            desi = [m for m in r["desi_matches"] if not m.get("zwarn")]
            best = (r["lens_matches"] or desi or [None])[0]
            cur.execute("""UPDATE transient.lsst_alerts SET desi_matches = %s, n_desi = %s, best_sep = %s,
                                  best_z = %s, mags_at = NULL, updated_at = now() WHERE oid = %s""",
                        (json.dumps(desi), len(desi), best and best["sep"],
                         best and (best.get("z") if "z" in best else best.get("z_lens")), r["oid"]))
            changed += 1
        conn.commit()
    return changed


# --------------------------------------------------------------------------- Daily Trigger

TRIGGER_PREFIX = "LSST-"          # obs.targets name of an LSST object without a TNS name: LSST-<oid>
_TRIGGER_NAME_RE = re.compile(r"^LSST-(?:AP-DO-)?(\d{6,})$", re.I)


def oid_from_target_name(name: str | None) -> int | None:
    m = _TRIGGER_NAME_RE.match((name or "").strip())
    return int(m.group(1)) if m else None


def tns_name_for_oid(cur, oid: int) -> str | None:
    """'AT2026xyz' / 'SN2026xyz' when the oid has a TNS object (linked alert or internal name)."""
    cur.execute("""
        SELECT COALESCE(o.name_prefix, '') || o.name
          FROM transient.objects o
         WHERE o.obj_id = (SELECT obj_id FROM transient.lsst_alerts WHERE oid = %s)
            OR o.internal_name ~ %s
         LIMIT 1
    """, (oid, rf"(^|[ ,])(LSST-AP-DO-)?{oid}([ ,]|$)"))
    row = cur.fetchone()
    return row[0] if row else None


def sync_trigger_targets() -> int:
    """Rename Daily Trigger targets (obs.targets, obs.logs) called LSST-<oid> once TNS has
    the object, so a target follows its object to the TNS name. Returns #targets renamed."""
    renamed = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT target_id, name, telescope FROM obs.targets WHERE name ILIKE 'LSST-%%'")
        for target_id, name, telescope in cur.fetchall():
            oid = oid_from_target_name(name)
            new = tns_name_for_oid(cur, oid) if oid else None
            if not new:
                continue
            cur.execute("SELECT 1 FROM obs.targets WHERE name = %s AND telescope = %s", (new, telescope))
            if cur.fetchone():          # already queued under its TNS name on this telescope
                logger.info("event=lsst_trigger_rename_skipped target=%s tns=%s telescope=%s", name, new, telescope)
                continue
            cur.execute("UPDATE obs.targets SET name = %s WHERE target_id = %s", (new, target_id))
            cur.execute("UPDATE obs.logs SET name = %s WHERE name = %s", (new, name))
            renamed += 1
            logger.info("event=lsst_trigger_renamed old=%s new=%s telescope=%s", name, new, telescope)
        conn.commit()
    return renamed


def search_alerts(q: str, limit: int = 15) -> list[dict]:
    """Daily Trigger autocomplete: watched LSST objects whose oid starts with the digits in q."""
    digits = re.sub(r"\D", "", q or "")
    if len(digits) < 4:
        return []
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""
            SELECT a.oid, a.ra, a.dec, a.class_name, a.probability, a.n_lens, a.n_desi, a.firstmjd,
                   o.name AS obj_name, o.name_prefix, o.type AS obj_type
              FROM transient.lsst_alerts a
              LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
             WHERE a.oid::text LIKE %s AND (a.n_lens > 0 OR a.n_desi > 0)
             ORDER BY a.firstmjd DESC
             LIMIT %s
        """, (digits + "%", limit))
        return cur.fetchall()


def get_alert(oid: int) -> dict | None:
    rows = list_alerts(oid=oid, limit=1)
    return rows[0] if rows else None


# --------------------------------------------------------------------------- manual cross-match

def crossmatch_oid(oid: int) -> dict:
    """Cross-match one LSST object on request (any class with DESI). A match is stored like a
    watch hit, so it shows on DETECT › LSST and can go to Daily Trigger."""
    item = alerce_api.objects_by_oid([oid]).get(int(oid))
    if not item:
        return {"found": False, "oid": oid}
    res = process_objects([item], desi_classes=None)
    if res.get("stored"):
        try:
            row = _alerts_for_mags([oid])[0]
            points = lightcurve_points(alerce_api.lightcurve(oid))
            save_mags(oid, compute_mags(row, points), _f(item.get("lastmjd")), points)
        except Exception as e:
            logger.warning("event=lsst_mags_failed oid=%s error=%s", oid, e)
        try:
            from app.services.lsst import detect
            detect.screen_alerts(oids=[oid])
        except Exception as e:
            logger.warning("event=lsst_detect_failed oid=%s error=%s", oid, e)
    return {"found": True, "oid": oid, "stored": bool(res.get("stored")), "item": item}


def parse_coords(ra_text: str, dec_text: str) -> tuple[float, float]:
    """RA / Dec in degrees or sexagesimal (hh:mm:ss / dd:mm:ss, or with spaces) -> degrees."""
    ra_text, dec_text = (ra_text or "").strip(), (dec_text or "").strip()
    if not ra_text or not dec_text:
        raise ValueError("RA and Dec are required")
    sexa = any(c in ra_text for c in ": hms")
    c = SkyCoord(ra_text, dec_text, unit=(u.hourangle if sexa else u.deg, u.deg))
    return float(c.ra.deg), float(c.dec.deg)


def cone_search(ra: float, dec: float, *, lens_radius: float = LENS_RADIUS_ARCSEC,
                desi_radius: float = DESI_RADIUS_ARCSEC, desi_max_sep_re: float | None = DESI_MAX_SEP_RE,
                include_zwarn: bool = False, tns_radius: float = 10.0, alerce_radius: float | None = 10.0,
                max_rows: int = 50) -> dict:
    """Everything Kinder knows around one position, for /detect/crossmatch. Nothing is stored.
    A radius of 0 / None skips that source."""
    ra_a, dec_a = np.array([ra]), np.array([dec])
    out = {"ra": ra, "dec": dec, "errors": {}}
    out["lens"] = match_lens(ra_a, dec_a, lens_radius).get(0, [])[:max_rows] if lens_radius else None
    out["desi"] = (match_desi(ra_a, dec_a, desi_radius, desi_max_sep_re, include_zwarn).get(0, [])[:max_rows]
                   if desi_radius else None)
    out["tns"] = _near_tns(ra, dec, tns_radius, max_rows) if tns_radius else None
    out["lsst_watch"] = _near_watch(ra, dec, max(tns_radius or 0, 5.0), max_rows)
    if alerce_radius:
        try:
            here = SkyCoord(ra * u.deg, dec * u.deg)
            rows = alerce_api.cone(ra, dec, alerce_radius, neighbors=max_rows)
            for r in rows:
                r["sep"] = round(float(here.separation(SkyCoord(r["ra"] * u.deg, r["dec"] * u.deg)).arcsec), 2)
            out["alerce"] = sorted(rows, key=lambda r: r["sep"])
        except Exception as e:
            out["alerce"], out["errors"]["alerce"] = [], str(e)
    else:
        out["alerce"] = None
    return out


def _box(ra: float, dec: float, radius_arcsec: float) -> tuple[float, float, float, float]:
    d = radius_arcsec / 3600.0
    dra = d / max(float(np.cos(np.radians(dec))), 1e-3)
    return float(dec - d), float(dec + d), float(ra - dra), float(ra + dra)


def _near_tns(ra: float, dec: float, radius: float, limit: int) -> list[dict]:
    dmin, dmax, rmin, rmax = _box(ra, dec, radius)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""
            SELECT name, name_prefix, ra, dec, type, redshift, status, internal_name,
                   discovery_date, discovery_mag
              FROM transient.objects
             WHERE dec BETWEEN %s AND %s
               AND (ra BETWEEN %s AND %s OR ra BETWEEN %s AND %s OR ra BETWEEN %s AND %s)
        """, (dmin, dmax, rmin, rmax, rmin + 360, rmax + 360, rmin - 360, rmax - 360))
        rows = cur.fetchall()
    return _within(ra, dec, rows, radius, limit, extra=lambda r: {"discovery_utc": _mjd_to_utc(r["discovery_date"])})


def _near_watch(ra: float, dec: float, radius: float, limit: int) -> list[dict]:
    dmin, dmax, rmin, rmax = _box(ra, dec, radius)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("SELECT oid, ra, dec, class_name, n_lens, n_desi, tns_name, firstmjd FROM transient.lsst_alerts "
                    "WHERE dec BETWEEN %s AND %s AND ra BETWEEN %s AND %s", (dmin, dmax, rmin, rmax))
        rows = cur.fetchall()
    return _within(ra, dec, rows, radius, limit)


def _within(ra, dec, rows, radius, limit, extra=None) -> list[dict]:
    if not rows:
        return []
    here = SkyCoord(ra * u.deg, dec * u.deg)
    sep = here.separation(SkyCoord(np.array([float(r["ra"]) for r in rows]) * u.deg,
                                   np.array([float(r["dec"]) for r in rows]) * u.deg)).arcsec
    out = []
    for r, s in zip(rows, sep):
        if s <= radius:
            out.append({**r, "sep": round(float(s), 2), **(extra(r) if extra else {})})
    return sorted(out, key=lambda r: r["sep"])[:limit]


# --------------------------------------------------------------------------- page data

def list_alerts(view: str = "pre_tns", catalog: str = "all", days: float = 14.0, limit: int = 500,
                oid: int | None = None) -> list[dict]:
    """Rows for /detect/lsst; with ``oid`` just that object, whatever the filters."""
    clauses = ["a.firstmjd >= %s", "(a.n_lens > 0 OR a.n_desi > 0)"]
    params = [_now_mjd() - days]
    if oid is not None:
        clauses, params = ["a.oid = %s"], [int(oid)]
    elif view == "pre_tns":
        clauses.append("a.obj_id IS NULL")
    elif view == "in_tns":
        clauses.append("a.obj_id IS NOT NULL")
    if oid is None and catalog == "lens":
        clauses.append("a.n_lens > 0")
    elif oid is None and catalog == "desi":
        clauses.append("a.n_desi > 0")
    params.append(limit)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"""
            SELECT a.*, o.name AS obj_name, o.name_prefix, o.status AS obj_status, o.type AS obj_type,
                   s.refreshed_at AS lc_refreshed_at, s.n_points AS lc_n_points,
                   d.score AS detect_score, d.tags AS detect_tags, d.host_status AS detect_host_status
              FROM transient.lsst_alerts a
              LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
              LEFT JOIN transient.lsst_lc_state s ON s.obj_id = a.obj_id
              LEFT JOIN transient.lsst_detect_screen d ON d.oid = a.oid
             WHERE {' AND '.join(clauses)}
             ORDER BY (a.n_lens > 0) DESC, a.firstmjd DESC
             LIMIT %s
        """, params)
        rows = cur.fetchall()
    for r in rows:
        r.pop("lc_points", None)
        r["detect_tags"] = [t for t in (r["detect_tags"] or []) if not t.startswith("Host-")]
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
              FROM transient.lsst_alerts WHERE firstmjd >= %s AND (n_lens > 0 OR n_desi > 0)
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
