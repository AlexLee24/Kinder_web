"""Keep the LSST light curve of every TNS object with an LSST counterpart current.

Runs hourly after the alert watch (app/services/lsst/alerts.py), independent of
DETECT and of the object's status (the daily photometry fetch only covers Inbox).

* Counterparts: the ``LSST-AP-DO-<oid>`` internal name TNS gives, plus objects the
  alert watch linked by position (``transient.lsst_alerts.obj_id``).
* One ALeRCE call per 200 objects tells each one's ``lastmjd``; only objects with a
  newer point than last time (``transient.lsst_lc_state``) get their light curve
  downloaded again.
* Points are written exactly like the photometry download does them
  (download_phot.get_lsst_alerce_photometry + bin_photometry_file): psfFlux > 0 of
  detections and forced photometry -> AB mag, one weighted point per filter and night,
  source ``LSST(alerce)``. A refresh replaces that object's ``LSST(alerce)`` rows, so a
  night that gained points is re-binned instead of duplicated.
"""
import logging
import math
import re
import threading
import time

import numpy as np
from psycopg2 import extras

from app.db import get_db_connection
from app.services.lsst import alerce_api

logger = logging.getLogger(__name__)

SOURCE = "LSST(alerce)"
AB_ZP_NJY = 31.4
MAX_REFRESH_PER_RUN = 300        # ~1 s per light curve; the rest waits for the next hour
_OID_RE = re.compile(r"^(?:LSST-AP-DO-)?(\d{15,})$", re.I)
_lock = threading.Lock()


def oid_from_internal_names(internal_name: str | None) -> int | None:
    for part in (internal_name or "").split(","):
        m = _OID_RE.match(part.strip())
        if m:
            return int(m.group(1))
    return None


def _now_mjd() -> float:
    return time.time() / 86400.0 + 40587.0


def lightcurve_points(lc: dict) -> list[tuple]:
    """ALeRCE light curve -> [(mjd, mag, mag_err, filter)], one point per filter and night."""
    raw = {}
    seen = set()
    for p in (lc.get("detections") or []) + (lc.get("forced_photometry") or []):
        mjd, flux, err = p.get("mjd"), p.get("psfFlux"), p.get("psfFluxErr")
        if mjd is None or flux is None or flux <= 0:
            continue
        filt = alerce_api.band_letter(p)
        key = (filt, round(mjd, 5))
        if key in seen:
            continue
        seen.add(key)
        mag = AB_ZP_NJY - 2.5 * math.log10(flux)
        mag_err = (2.5 / math.log(10)) * (abs(err) / flux) if err else 0.1
        raw.setdefault((filt, int(math.floor(mjd))), []).append((mjd, mag, mag_err or 0.1))

    points = []
    for (filt, _night), pts in raw.items():
        mjd = np.array([p[0] for p in pts])
        mag = np.array([p[1] for p in pts])
        err = np.array([p[2] for p in pts])
        if len(pts) == 1:
            points.append((float(mjd[0]), float(mag[0]), float(err[0]), filt))
            continue
        # Same weighting as download_phot.bin_photometry_file
        flux = 10 ** (-0.4 * mag)
        flux_err = flux * err * 0.4 * np.log(10)
        w = 1.0 / flux_err ** 2
        w_flux = np.sum(flux * w) / np.sum(w)
        err_prop = np.sqrt(1.0 / np.sum(w))
        err_scatter = np.std(flux, ddof=1) / np.sqrt(len(flux))
        final_err = max(err_prop, err_scatter)
        points.append((float(np.mean(mjd)), float(-2.5 * np.log10(w_flux)),
                       float((2.5 / np.log(10)) * final_err / w_flux), filt))
    points.sort()
    return points


def _targets() -> dict:
    """{obj_id: {name, oid, status, stored_max, state_lastmjd}} for every TNS object with an LSST oid."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""
            SELECT o.obj_id, o.name, o.status, o.internal_name, a.oid AS alert_oid,
                   s.alerce_lastmjd AS state_lastmjd,
                   (SELECT MAX(p."MJD") FROM transient.photometry p
                     WHERE p.obj_id = o.obj_id AND p.source = %s) AS stored_max
              FROM transient.objects o
              LEFT JOIN transient.lsst_alerts a ON a.obj_id = o.obj_id
              LEFT JOIN transient.lsst_lc_state s ON s.obj_id = o.obj_id
             WHERE o.internal_name ~* '(LSST-AP-DO-)?[0-9]{15,}' OR a.oid IS NOT NULL
        """, (SOURCE,))
        rows = cur.fetchall()
    out = {}
    for r in rows:
        oid = oid_from_internal_names(r["internal_name"]) or r["alert_oid"]
        if oid and r["obj_id"] not in out:
            out[r["obj_id"]] = {**r, "oid": int(oid)}
    return out


def _needs_refresh(t: dict, alerce_lastmjd: float | None) -> bool:
    if alerce_lastmjd is None:
        return False
    if t["state_lastmjd"] is not None:
        return alerce_lastmjd > t["state_lastmjd"] + 1e-6
    # Never refreshed by this job: the photometry download may already hold the
    # data; its points are nightly means, so allow half a night of slack.
    return t["stored_max"] is None or alerce_lastmjd > t["stored_max"] + 0.5


def _priority(t: dict, lastmjd: float) -> tuple:
    rank = {"Follow-up": 0, "Inbox": 1}.get(t["status"], 2)
    return (rank, -lastmjd)


def refresh_object(obj_id: int, name: str, oid: int, alerce_lastmjd: float | None = None) -> int:
    """Download one object's LSST light curve and replace its LSST(alerce) rows. Returns #points."""
    error = None
    points = []
    try:
        points = lightcurve_points(alerce_api.lightcurve(oid))
    except Exception as e:
        error = str(e)[:500]
    with get_db_connection() as conn:
        cur = conn.cursor()
        if error is None:
            cur.execute("DELETE FROM transient.photometry WHERE obj_id = %s AND source = %s", (obj_id, SOURCE))
            if points:
                extras.execute_values(
                    cur,
                    'INSERT INTO transient.photometry (obj_id, name, "MJD", mag, mag_err, filter, source) '
                    "VALUES %s ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING",
                    [(obj_id, name, m, mag, e, f, SOURCE) for m, mag, e, f in points],
                )
            cur.execute(
                'UPDATE transient.objects SET last_phot_date = '
                '(SELECT MAX("MJD") FROM transient.photometry WHERE obj_id = %s) WHERE obj_id = %s',
                (obj_id, obj_id))
        cur.execute("""
            INSERT INTO transient.lsst_lc_state (obj_id, oid, alerce_lastmjd, n_points, refreshed_at, error)
            VALUES (%s, %s, %s, %s, now(), %s)
            ON CONFLICT (obj_id) DO UPDATE SET
                oid = EXCLUDED.oid,
                alerce_lastmjd = COALESCE(CASE WHEN EXCLUDED.error IS NULL THEN EXCLUDED.alerce_lastmjd END,
                                          transient.lsst_lc_state.alerce_lastmjd),
                n_points = COALESCE(EXCLUDED.n_points, transient.lsst_lc_state.n_points),
                refreshed_at = now(), error = EXCLUDED.error
        """, (obj_id, oid, alerce_lastmjd if error is None else None,
              len(points) if error is None else None, error))
        conn.commit()
    if error:
        raise RuntimeError(error)
    return len(points)


def refresh_lightcurves(max_objects: int = MAX_REFRESH_PER_RUN, progress=None) -> dict:
    """Hourly: refresh the LSST light curve of every linked TNS object that has new points.
    ``progress(msg)`` receives a few human-readable progress lines (the run log)."""
    say = progress or (lambda _m: None)
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already running"}
    started = time.monotonic()
    try:
        targets = _targets()
        by_oid = {t["oid"]: oid for oid, t in targets.items()}
        say(f"{len(targets)} TNS objects have an LSST counterpart; asking ALeRCE for their latest point…")
        latest = alerce_api.objects_by_oid(by_oid.keys())
        due = []
        for oid, row in latest.items():
            obj_id = by_oid.get(oid)
            if obj_id is None:
                continue
            t = targets[obj_id]
            if _needs_refresh(t, row.get("lastmjd")):
                due.append((_priority(t, row["lastmjd"]), obj_id, row["lastmjd"]))
        due.sort()
        done = failed = 0
        todo = due[:max_objects]
        say(f"{len(due)} have new points; refreshing {len(todo)}"
            + (f" (the other {len(due) - len(todo)} next hour)" if len(due) > len(todo) else ""))
        for n, (_p, obj_id, lastmjd) in enumerate(todo, 1):
            t = targets[obj_id]
            try:
                refresh_object(obj_id, t["name"], t["oid"], lastmjd)
                done += 1
            except Exception as e:
                failed += 1
                logger.warning("event=lsst_lc_refresh_failed object=%s oid=%s error=%s", t["name"], t["oid"], e)
            if n % 25 == 0:
                say(f"{n}/{len(todo)} light curves done")
        res = {"linked": len(targets), "in_alerce": len(latest), "due": len(due),
               "refreshed": done, "failed": failed, "seconds": round(time.monotonic() - started, 1)}
        logger.info("event=lsst_lc_refresh_done %s", " ".join(f"{k}={v}" for k, v in res.items()))
        return res
    finally:
        _lock.release()
