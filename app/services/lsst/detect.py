"""DETECT on LSST alerts: the same host rule, screen (score + tags) and review image as
DETECT's TNS pipeline (app/vendor/DETECT/function/module/cross_match.py), fed from
ALeRCE instead of TNS. Results live in LSST tables, never in transient.objects:

* ``transient.lsst_detect_matches``  DESI / Lens candidates, match_data as cross_matches
* ``transient.lsst_detect_screen``   score, host status, tags, M (one row per oid)
* ``transient.lsst_target_images``   the LS DR10 host-model image
* ``transient.lsst_alerts.review_status``  the reviewer's Inbox / Follow-up / Snoozed / Finish

An alert is screened once when it arrives and again whenever its LSST light curve gains a
point (within ``RESCREEN_DAYS`` of the first detection) or a reviewer changes its host. The
light curve is the binned LSST one (alerts.save_mags keeps it in ``lsst_alerts.lc_points``);
type and TNS redshift come from the linked TNS object, if any. DESI candidates with
ZWARN != 0 are dropped before the host rule, as in the watch.

Pages: DETECT › LSST-DETECT (app/blueprints/detect/lsst_review.py): the overview at /detect/lsst and
one review day per UTC date of the first LSST detection (/detect/lsst?day=). Only alerts with
DETECT candidates (``_MATCHED``) are shown; the others stay screened but hidden.
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2 import extras

from app.db import get_db_connection
from app.services.lsst import alerce_api
from app.services.lsst.lightcurve import SOURCE, lightcurve_points

logger = logging.getLogger(__name__)

NAME_PREFIX = "LSST-"
RESCREEN_DAYS = 30.0          # new LSST points re-screen an alert this long after its first detection
MAX_PER_RUN = 150             # alerts screened per scheduled run; the rest waits for the next hour
MAX_PER_MANUAL_RUN = 1000     # a run started from the page screens everything it read
LENS_RADIUS_ARCSEC = 10.0     # DETECT's LENS_SEARCH_RADIUS_ARCSEC
REVIEW_STATUSES = {"object": "Inbox", "followup": "Follow-up", "snoozed": "Snoozed", "finished": "Finish"}
_NAME_RE = re.compile(r"^LSST-(\d{6,})$")


def target_name(oid) -> str:
    return f"{NAME_PREFIX}{int(oid)}"


def oid_from_name(name: str | None) -> int | None:
    m = _NAME_RE.match((name or "").strip())
    return int(m.group(1)) if m else None


def _now_mjd() -> float:
    return time.time() / 86400.0 + 40587.0


def _mjd_day(mjd) -> str | None:
    if mjd is None:
        return None
    return datetime.fromtimestamp((float(mjd) - 40587.0) * 86400.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _zwarn(m: dict) -> int:
    try:
        return int(float(m.get("zwarn") if m.get("zwarn") is not None else m.get("ZWARN") or 0))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- screening

def _alerts_to_screen(oids=None, limit: int = MAX_PER_RUN) -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        if oids is not None:
            where, params = "a.oid = ANY(%s)", [list(int(o) for o in oids)]
        else:
            where = """(a.n_lens > 0 OR a.n_desi > 0) AND (
                           s.oid IS NULL OR s.screened_lastmjd IS NULL
                        OR (a.firstmjd >= %s AND COALESCE(a.mags_lastmjd, a.lastmjd) > s.screened_lastmjd + 1e-6))"""
            params = [_now_mjd() - RESCREEN_DAYS]
        cur.execute(f"""
            SELECT a.oid, a.ra, a.dec, a.firstmjd, a.lastmjd, a.mags_lastmjd, a.lc_points, a.desi_matches,
                   o.type AS tns_type, o.redshift AS tns_redshift, s.oid IS NOT NULL AS screened,
                   s.image_key, (i.oid IS NOT NULL) AS has_image
              FROM transient.lsst_alerts a
              LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
              LEFT JOIN transient.lsst_detect_screen s ON s.oid = a.oid
              LEFT JOIN transient.lsst_target_images i ON i.oid = a.oid
             WHERE {where}
             ORDER BY (s.oid IS NULL) DESC, a.firstmjd DESC
             LIMIT %s
        """, params + [limit])
        return cur.fetchall()


def _points(alert: dict) -> list[tuple]:
    """The stored binned light curve, downloading it (and saving the magnitudes) when missing."""
    if alert.get("lc_points") is not None:
        return [tuple(p) for p in alert["lc_points"]]
    from app.services.lsst import alerts as lsst_alerts
    points = lightcurve_points(alerce_api.lightcurve(alert["oid"]))
    lsst_alerts.save_mags(alert["oid"], lsst_alerts.compute_mags(alert, points),
                          max((p[0] for p in points), default=None), points)
    return points


def _object_meta(alert: dict, points: list[tuple]) -> dict:
    """What screen_target reads from transient.objects, built from the LSST light curve."""
    meta = {"type": alert.get("tns_type"), "redshift": alert.get("tns_redshift"),
            "discovery_mag": None, "discovery_filter": None, "peak_mag": None,
            "photometry": [{"mjd": m, "mag": mag, "mag_err": e, "filter": f} for m, mag, e, f in points]}
    if points:
        first = min(points, key=lambda p: p[0])
        peak = min(points, key=lambda p: p[1])
        meta.update(discovery_mag=first[1], discovery_filter=first[3],
                    peak_mag=peak[1], peak_filter=peak[3], peak_mjd=peak[0],
                    peak_source=SOURCE, n_phot=len(points))
    return meta


def _user_decisions(oids: list[int]) -> dict[int, dict]:
    """Reviewers' host choices, the shape DETECT's load_user_host_decisions returns."""
    if not oids:
        return {}
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""
            SELECT oid, match_id, crossmatch_uid AS uid, (match_data->>'host_user')::boolean AS host_user,
                   match_data->>'host_user_by' AS by
              FROM transient.lsst_detect_matches
             WHERE oid = ANY(%s) AND match_data ? 'host_user'
             ORDER BY match_id
        """, (list(oids),))
        rows = cur.fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        if r["host_user"]:
            out[r["oid"]] = {"decision": "host", "uid": r["uid"], "match_id": r["match_id"], "by": r["by"]}
        elif r["oid"] not in out:
            out[r["oid"]] = {"decision": "none", "by": r["by"]}
    return out


def _image_key(rows: list[dict], screen: dict) -> str:
    f = screen.get("flags") or {}
    key = {"host": next((r["crossmatch_uid"] for r in rows if r.get("is_host")), None),
           "uids": sorted(r["crossmatch_uid"] for r in rows),
           "score": screen.get("score"), "tags": screen.get("tags"),
           "M": round(f["abs_mag"], 2) if f.get("abs_mag") is not None else None}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def _save(alert: dict, name: str, rows: list[dict], screen: dict, image: bytes | None, image_key: str,
          screened_lastmjd) -> None:
    from function.database import CatalogueService
    from function.module.screening import _plain  # numpy scalars -> Python (psycopg2 / JSON)
    rows, screen = _plain(rows), _plain(screen)
    for r in rows:      # DETECT's own upload names the catalogue this way: Lens_Lens_UNKNOWN -> Lens_UNKNOWN
        r["catalog_name"] = CatalogueService.build_catalog_name(r["catalog_name"], None)
    f = screen.get("flags") or {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        uids = [r["crossmatch_uid"] for r in rows]
        cur.execute("DELETE FROM transient.lsst_detect_matches WHERE oid = %s AND NOT (crossmatch_uid = ANY(%s))",
                    (alert["oid"], uids or [""]))
        for r in rows:
            md = r["match_data"]
            cur.execute("""
                INSERT INTO transient.lsst_detect_matches
                    (oid, crossmatch_uid, catalog, separation, is_host, redshift, match_ra, match_dec, match_data, updated_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (oid, crossmatch_uid) DO UPDATE SET
                    catalog = EXCLUDED.catalog, separation = EXCLUDED.separation, is_host = EXCLUDED.is_host,
                    redshift = EXCLUDED.redshift, match_ra = EXCLUDED.match_ra, match_dec = EXCLUDED.match_dec,
                    match_data = EXCLUDED.match_data, updated_date = now()
            """, (alert["oid"], r["crossmatch_uid"], r["catalog_name"], r.get("separation_arcsec"),
                  bool(r.get("is_host")), r.get("candidate_redshift"), r.get("candidate_ra"),
                  r.get("candidate_dec"), extras.Json(md)))
        cur.execute("""
            INSERT INTO transient.lsst_detect_screen
                (oid, name, score, host_status, tags, flags, host_targetid, z, z_source, abs_mag, abs_mag_band,
                 abs_mag_source, abs_mag_discovery, peak_mag, peak_filter, peak_mjd, center_sep_arcsec, d_dlr,
                 offset_kpc, review_day, screened_lastmjd, image_key, run_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (oid) DO UPDATE SET
                name = EXCLUDED.name, score = EXCLUDED.score, host_status = EXCLUDED.host_status,
                tags = EXCLUDED.tags, flags = EXCLUDED.flags, host_targetid = EXCLUDED.host_targetid,
                z = EXCLUDED.z, z_source = EXCLUDED.z_source, abs_mag = EXCLUDED.abs_mag,
                abs_mag_band = EXCLUDED.abs_mag_band, abs_mag_source = EXCLUDED.abs_mag_source,
                abs_mag_discovery = EXCLUDED.abs_mag_discovery, peak_mag = EXCLUDED.peak_mag,
                peak_filter = EXCLUDED.peak_filter, peak_mjd = EXCLUDED.peak_mjd,
                center_sep_arcsec = EXCLUDED.center_sep_arcsec, d_dlr = EXCLUDED.d_dlr,
                offset_kpc = EXCLUDED.offset_kpc, review_day = EXCLUDED.review_day,
                screened_lastmjd = EXCLUDED.screened_lastmjd,
                image_key = COALESCE(EXCLUDED.image_key, transient.lsst_detect_screen.image_key), run_date = now()
        """, (alert["oid"], name, int(screen.get("score") or 0), f.get("host_status"), list(screen.get("tags") or []),
              extras.Json(f), f.get("host_targetid"), f.get("z"), f.get("z_source"), f.get("abs_mag"),
              f.get("abs_mag_band"), f.get("abs_mag_source"), f.get("abs_mag_discovery"), f.get("peak_mag"),
              f.get("peak_filter"), f.get("peak_mjd"), f.get("center_sep_arcsec"), f.get("d_dlr"),
              f.get("offset_kpc"), _mjd_day(alert["firstmjd"]), screened_lastmjd,
              image_key if image is not None else None))
        if image is not None:
            cur.execute("""
                INSERT INTO transient.lsst_target_images (oid, image_data, created_at) VALUES (%s, %s, now())
                ON CONFLICT (oid) DO UPDATE SET image_data = EXCLUDED.image_data, created_at = now()
            """, (alert["oid"], psycopg2.Binary(image)))
        conn.commit()


def screen_alerts(oids=None, progress=None, max_objects: int = MAX_PER_RUN) -> dict:
    """Run DETECT on LSST alerts that are new, have new LSST points, or a new host decision
    (``oids``: exactly those). ``progress(msg)`` gets a few run-log lines."""
    from function.module.cross_match import (  # DETECT, on sys.path via app.paths
        _apply_host_rule,
        _apply_user_host_decision,
        _desi_stars_near,
        _prepare_target_upload_rows,
        build_target_image_bytes,
    )
    from function.module.DESI_cross_match import desi_cross_match
    from function.module.Lens_cross_match import lens_cross_match
    from function.module.screening import screen_target

    from app.services.detect.detect_pipeline import _pin_db_env

    say = progress or (lambda _m: None)
    started = time.monotonic()
    todo = _alerts_to_screen(oids, max_objects)
    if not todo:
        return {"screened": 0, "images": 0, "failed": 0, "seconds": 0.0}
    names = {a["oid"]: target_name(a["oid"]) for a in todo}
    targets = [(float(a["ra"]), float(a["dec"]), names[a["oid"]]) for a in todo]
    say(f"{len(todo)} alert(s) to screen; DETECT's DESI and Lens cross-match…")
    _pin_db_env()          # DETECT reads PG_DATABASE; the app's database is app.db.DB_NAME
    desi = desi_cross_match(targets)
    lens = lens_cross_match(targets, search_radius=LENS_RADIUS_ARCSEC)
    # both return {} on any error (printed, not raised) but a key per target on success:
    # never save a failed cross-match as "no candidates"
    for label, got in (("DESI", desi), ("Lens", lens)):
        if any(t[2] not in got for t in targets):
            raise RuntimeError(f"DETECT's {label} cross-match failed (see the server log); nothing saved")
    decisions = _user_decisions([a["oid"] for a in todo])
    stars = _desi_stars_near({names[a["oid"]]: {"ra": float(a["ra"]), "dec": float(a["dec"])} for a in todo})

    screened = images = failed = 0
    for n, a in enumerate(todo, 1):
        name, ra, dec = names[a["oid"]], float(a["ra"]), float(a["dec"])
        try:
            points = _points(a)
            desi_rows = [m for m in desi.get(name, []) if not _zwarn(m)]
            rows = (_prepare_target_upload_rows(name, "DESI", desi_rows)
                    + _prepare_target_upload_rows(name, "Lens", lens.get(name, [])))
            analyzed, inside = (_apply_host_rule(ra, dec, rows) if rows else ([], 0))
            _apply_user_host_decision(rows, decisions.get(a["oid"]))
            host = next((r for r in rows if r.get("is_host")), None)
            screen = screen_target(name=name, ra=ra, dec=dec, obj_meta=_object_meta(a, points),
                                   host_row=host, upload_rows=rows, star_hits=stars.get(name, []),
                                   inside_galaxies=inside)
            key = _image_key(rows, screen)
            image = None
            if rows and (key != a.get("image_key") or not a.get("has_image")):
                has_desi = any(r.get("catalog_name", "").upper() == "DESI" for r in rows)
                image = build_target_image_bytes(name, ra, dec, rows, has_desi=has_desi,
                                                 analyzed=analyzed, screen=screen)
            _save(a, name, rows, screen, image, key, a.get("mags_lastmjd") or a.get("lastmjd"))
            screened += 1
            images += image is not None
        except Exception as e:
            failed += 1
            logger.warning("event=lsst_detect_failed oid=%s error=%s", a["oid"], e)
        if n % 10 == 0:
            say(f"{n}/{len(todo)} screened")
    res = {"screened": screened, "images": images, "failed": failed,
           "seconds": round(time.monotonic() - started, 1)}
    logger.info("event=lsst_detect_done %s", " ".join(f"{k}={v}" for k, v in res.items()))
    return res


# --------------------------------------------------------------------------- review page data

# an alert DETECT found DESI / Lens candidates for; the pages show only these
_MATCHED = "EXISTS (SELECT 1 FROM transient.lsst_detect_matches m WHERE m.oid = s.oid)"
# ... on a lens-catalogue object: marked and pinned to the top
_ON_LENS = ("EXISTS (SELECT 1 FROM transient.lsst_detect_matches m"
            " WHERE m.oid = s.oid AND left(lower(m.catalog), 4) = 'lens')")      # no %: used with and without params

_SCREEN_SELECT = """
    SELECT s.oid, s.name, s.score, s.host_status, s.tags, s.flags, s.host_targetid,
           s.z, s.z_source, s.abs_mag, s.abs_mag_band, s.abs_mag_source, s.abs_mag_discovery,
           s.peak_mag, s.peak_filter, s.peak_mjd, s.center_sep_arcsec, s.d_dlr, s.offset_kpc,
           s.run_date, o.type AS tns_type, a.review_status AS obj_status, a.ra, a.dec, o.redshift AS tns_z,
           to_char(TIMESTAMP '1858-11-17' + a.firstmjd * INTERVAL '1 day', 'YYYY-MM-DD') AS discoverydate,
           a.tns_name, o.name AS obj_name, to_char(s.review_day, 'YYYY-MM-DD') AS review_day,
           {on_lens} AS has_lens
      FROM transient.lsst_detect_screen s
      JOIN transient.lsst_alerts a ON a.oid = s.oid
      LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
""".replace("{on_lens}", _ON_LENS)


def _screen_row(r) -> dict:
    d = dict(r)
    d["flags"] = d.get("flags") or {}
    d["tags"] = list(d.get("tags") or [])
    if d.get("run_date") is not None:
        d["run_date"] = d["run_date"].strftime("%Y-%m-%d %H:%M")
    return d


def review_metadata() -> dict:
    """available_dates / daily_counts / screen_counts in the shape of get_detect_metadata(),
    over the alerts with DETECT candidates."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"""
            SELECT s.review_day AS d, s.host_status, count(*) AS n, max(s.run_date) AS last_run,
                   bool_or({_ON_LENS}) AS has_lens,
                   count(*) FILTER (WHERE 'glSN?' = ANY(s.tags) AND NOT {_ON_LENS}) AS lens_cand,
                   count(*) FILTER (WHERE 'SLSN?' = ANY(s.tags)) AS slsn
              FROM transient.lsst_detect_screen s
             WHERE s.review_day IS NOT NULL AND {_MATCHED}
             GROUP BY 1, 2
        """)
        screen_counts: dict = {}
        for r in cur.fetchall():
            day = r["d"].strftime("%Y-%m-%d")
            e = screen_counts.setdefault(day, {"confirmed": 0, "review": 0, "none": 0, "total": 0,
                                               "has_lens": False, "lens_cand": 0, "slsn": 0, "last_run": None})
            e[r["host_status"] or "none"] = r["n"]
            e["total"] += r["n"]
            e["lens_cand"] += r["lens_cand"]
            e["slsn"] += r["slsn"]
            e["has_lens"] = e["has_lens"] or bool(r["has_lens"])
            if e["last_run"] is None or r["last_run"] > e["last_run"]:
                e["last_run"] = r["last_run"]
    for e in screen_counts.values():
        if e["last_run"] is not None:
            e["last_run"] = e["last_run"].strftime("%Y-%m-%d %H:%M %Z")
    days = sorted(screen_counts, reverse=True)
    return {"available_dates": days,
            "daily_counts": [{"date": d, "count": screen_counts[d]["total"], "has_lens": screen_counts[d]["has_lens"],
                              "lens_cand": screen_counts[d]["lens_cand"], "slsn": screen_counts[d]["slsn"],
                              "screen": screen_counts[d]} for d in days],
            "screen_counts": screen_counts}


def review_overview() -> dict:
    """get_detect_overview() for LSST: the latest run, how the alerts it screened split by host
    status, what is still waiting for a person, and the highest-scoring alerts — after every
    lens-catalogue alert still in Inbox or Follow-up, from any day."""
    result = {"last_run": None, "run_day": None, "counts": {}, "pending": 0, "top": []}
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"SELECT max(s.run_date) AS last_run FROM transient.lsst_detect_screen s WHERE {_MATCHED}")
        last_run = (cur.fetchone() or {}).get("last_run")
        if last_run is None:
            return result
        result["last_run"] = last_run.strftime("%Y-%m-%d %H:%M %Z")
        result["run_day"] = last_run.strftime("%Y-%m-%d")
        cur.execute(f"""
            SELECT s.host_status, count(*) AS n, count(*) FILTER (WHERE a.review_status = 'Inbox') AS pending
              FROM transient.lsst_detect_screen s JOIN transient.lsst_alerts a ON a.oid = s.oid
             WHERE s.run_date::date = %s::date AND {_MATCHED}
             GROUP BY 1
        """, (last_run,))
        for r in cur.fetchall():
            result["counts"][r["host_status"] or "none"] = r["n"]
            if (r["host_status"] or "none") != "none":
                result["pending"] += r["pending"]
        result["counts"]["total"] = sum(result["counts"].values())
        cur.execute(_SCREEN_SELECT + f"""
             WHERE {_ON_LENS} AND a.review_status IN ('Inbox', 'Follow-up')
             ORDER BY s.score DESC, s.abs_mag ASC NULLS LAST, s.name
        """)
        lens = [_screen_row(r) for r in cur.fetchall()]
        cur.execute(_SCREEN_SELECT + f"""
             WHERE s.run_date::date = %s::date AND s.host_status <> 'none' AND {_MATCHED} AND NOT {_ON_LENS}
             ORDER BY s.score DESC, s.abs_mag ASC NULLS LAST, s.name LIMIT 8
        """, (last_run,))
        result["top"] = lens + [_screen_row(r) for r in cur.fetchall()]
    return result


def review_page_data(day: str) -> dict:
    """get_detect_page_data(date) for LSST: candidates, details, latest point and screen
    rows of the alerts with DETECT candidates first detected on ``day`` (UTC)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""
            SELECT m.match_id AS id, s.name AS target_name, m.catalog AS catalog_name,
                   m.separation AS separation_arcsec, m.is_host, m.updated_date AS created_at,
                   'Success' AS status, m.flag, m.redshift AS z, m.match_data, m.match_ra, m.match_dec
              FROM transient.lsst_detect_matches m
              JOIN transient.lsst_detect_screen s ON s.oid = m.oid
             WHERE s.review_day = %s
        """, (day,))
        results = cur.fetchall()
        cur.execute(f"""
            SELECT s.name, a.oid, a.ra, a.dec AS declination,
                   to_char(TIMESTAMP '1858-11-17' + a.firstmjd * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS')
                       AS discoverydate,
                   a.tns_name, a.obj_id, o.name AS obj_name, o.type, o.redshift, a.review_status AS status,
                   a.latest_mag, a.latest_filter, a.latest_mjd, a.lc_points
              FROM transient.lsst_detect_screen s
              JOIN transient.lsst_alerts a ON a.oid = s.oid
              LEFT JOIN transient.objects o ON o.obj_id = a.obj_id
             WHERE s.review_day = %s AND {_MATCHED}
        """, (day,))
        details_batch, latest_phot = {}, {}
        for r in cur.fetchall():
            pts = r.pop("lc_points") or []
            first = min(pts, key=lambda p: p[0]) if pts else None
            internal = [f"LSST {r['oid']}"] + ([r["tns_name"]] if r["tns_name"] else [])
            details_batch[r["name"]] = {**r, "internal_names": ", ".join(internal),
                                        "discoverymag": first[1] if first else None,
                                        "filter": first[3] if first else None}
            if r["latest_mag"] is not None:
                latest_phot[r["name"]] = {"magnitude": r["latest_mag"], "filter": r["latest_filter"],
                                          "mjd": r["latest_mjd"]}
        cur.execute(_SCREEN_SELECT + f" WHERE s.review_day = %s AND {_MATCHED}", (day,))
        screen_batch = {r["name"]: _screen_row(r) for r in cur.fetchall()}
    return {
        "results": results,
        "details_batch": details_batch,
        "latest_phot": latest_phot,
        "screen_batch": screen_batch,
        "screen_only": [],
        "wake_notes": {},
    }


def object_href(detail: dict | None, oid: int) -> str:
    """Where the object name links: its marshal page once in TNS, else ALeRCE's explorer."""
    if detail and detail.get("obj_name"):
        return "/object/" + detail["obj_name"]
    return alerce_api.explorer_url(oid)


def review_day_for(oid: int) -> str | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT review_day FROM transient.lsst_detect_screen s WHERE s.oid = %s AND {_MATCHED}",
                    (int(oid),))
        row = cur.fetchone()
    return row[0].strftime("%Y-%m-%d") if row and row[0] else None


def get_image(oid: int) -> bytes | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT image_data FROM transient.lsst_target_images WHERE oid = %s", (int(oid),))
        row = cur.fetchone()
    return bytes(row[0]) if row else None


def lightcurve_rows(oid: int) -> tuple[list[dict], dict]:
    """Stored LSST points as photometry rows for DataVisualization, plus z / ra / dec."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("""SELECT a.ra, a.dec, a.lc_points, s.z FROM transient.lsst_alerts a
                       LEFT JOIN transient.lsst_detect_screen s ON s.oid = a.oid WHERE a.oid = %s""", (int(oid),))
        row = cur.fetchone()
    if not row:
        return [], {}
    phot = [{"id": i, "mjd": m, "magnitude": mag, "magnitude_error": e, "filter": f, "telescope": SOURCE}
            for i, (m, mag, e, f) in enumerate(row["lc_points"] or [])]
    return phot, {"z": row["z"], "ra": row["ra"], "dec": row["dec"]}


def refetch_lightcurve(oid: int) -> int:
    """Download the light curve from ALeRCE again (the card's Fetch LC). Returns #points."""
    from app.services.lsst import alerts as lsst_alerts
    rows = lsst_alerts._alerts_for_mags([oid])
    if not rows:
        raise LookupError(f"LSST {oid} is not a watched alert")
    points = lightcurve_points(alerce_api.lightcurve(oid))
    lsst_alerts.save_mags(oid, lsst_alerts.compute_mags(rows[0], points),
                          max((p[0] for p in points), default=None), points)
    return len(points)


def followup_tracker() -> list[dict]:
    """LSST alerts a reviewer put in Follow-up, in the shape of DETECT's tracker rows."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(_SCREEN_SELECT.replace("SELECT s.oid,", """SELECT
               (SELECT regexp_replace(m.catalog, '^(Lens_)+', 'Lens_')        -- rows saved before build_catalog_name
                  FROM transient.lsst_detect_matches m WHERE m.oid = s.oid
                 ORDER BY m.is_host DESC, m.separation LIMIT 1) AS catalog_name,
               (SELECT m.separation FROM transient.lsst_detect_matches m WHERE m.oid = s.oid
                 ORDER BY m.is_host DESC, m.separation LIMIT 1) AS separation_arcsec,
               s.oid,""") + " WHERE a.review_status = 'Follow-up'")
        rows = cur.fetchall()
    out = [{
        "name": r["name"], "oid": r["oid"], "z": r["z"], "abs_mag": r["abs_mag"],
        "abs_mag_source": r["abs_mag_source"], "abs_mag_band": r["abs_mag_band"],
        "catalog_name": r["catalog_name"] or "—", "separation_arcsec": r["separation_arcsec"],
        "discoverydate": r["discoverydate"] or "—", "obj_status": "followup", "score": r["score"],
        "host_status": r["host_status"],
        "tags": [t for t in (r["tags"] or []) if not str(t).startswith("Host-")],
        "detect_run_date": r["run_date"].strftime("%Y-%m-%d %H:%M") if r["run_date"] else None,
    } for r in rows]
    out.sort(key=lambda x: (-(x["score"] or 0), x["abs_mag"] is None, x["abs_mag"] or 0))
    return out


# --------------------------------------------------------------------------- review decisions

def _decision_json(value: bool, by: str | None) -> str:
    return json.dumps({"host_user": value, "host_user_by": by,
                       "host_user_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def _rescreen_soon(cur, oid: int, host_status: str | None = None) -> None:
    """The next run re-screens the alert with the decision applied (z, M, tags, image), as
    DETECT's daily Follow-up re-run does; until then the page shows the decision as is."""
    if host_status:
        cur.execute("UPDATE transient.lsst_detect_screen SET host_status = %s, screened_lastmjd = NULL "
                    "WHERE oid = %s", (host_status, oid))
    else:
        cur.execute("UPDATE transient.lsst_detect_screen SET screened_lastmjd = NULL WHERE oid = %s", (oid,))


def set_review_status(oid: int, status: str, by: str | None = None) -> bool:
    """status: object | followup | snoozed | finished (the page's names)."""
    value = REVIEW_STATUSES.get(status)
    if value is None:
        return False
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transient.lsst_alerts SET review_status = %s, review_by = %s, review_at = now() "
                    "WHERE oid = %s", (value, by, int(oid)))
        ok = cur.rowcount > 0
        conn.commit()
    return ok


def set_host(oid: int, match_id: int, by: str | None) -> bool:
    """A person picks ``match_id`` as the host; False (nothing changed) when it is not a candidate of oid."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transient.lsst_detect_matches SET is_host = TRUE, "
                    "match_data = COALESCE(match_data, '{}'::jsonb) || %s::jsonb "
                    "WHERE match_id = %s AND oid = %s", (_decision_json(True, by), int(match_id), int(oid)))
        if cur.rowcount == 0:
            conn.rollback()
            return False
        cur.execute("UPDATE transient.lsst_detect_matches SET is_host = FALSE, "
                    "match_data = COALESCE(match_data, '{}'::jsonb) || %s::jsonb "
                    "WHERE oid = %s AND match_id <> %s", (_decision_json(False, by), int(oid), int(match_id)))
        _rescreen_soon(cur, int(oid), "confirmed")
        conn.commit()
    return True


def release_host(oid: int) -> bool:
    """Reopen: drop the person's decision, leave is_host as it stands until the re-screen."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transient.lsst_detect_matches SET "
                    "match_data = match_data - 'host_user' - 'host_user_by' - 'host_user_at' "
                    "WHERE oid = %s AND match_data ? 'host_user'", (int(oid),))
        _rescreen_soon(cur, int(oid))
        conn.commit()
    return True


def reject_hosts(oid: int, by: str | None) -> bool:
    """A person decided none of the candidates is the host."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transient.lsst_detect_matches SET is_host = FALSE, "
                    "match_data = COALESCE(match_data, '{}'::jsonb) || %s::jsonb WHERE oid = %s",
                    (_decision_json(False, by), int(oid)))
        _rescreen_soon(cur, int(oid), "none")
        conn.commit()
    return True


def set_flag(match_id: int, flag: bool) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transient.lsst_detect_matches SET flag = %s WHERE match_id = %s", (flag, int(match_id)))
        ok = cur.rowcount > 0
        conn.commit()
    return ok

