"""Run the embedded DETECT pipeline from the web app.

Thin wrapper over ``function.run_detect`` (app/modules/DETECT) with one lock, so an
hourly import, a daily Follow-up re-screen and an object-page Run button never
run on top of each other. Everything DETECT writes (cross_matches, detect_screen,
target_images, objects.tag / brightest_*) is identical to the daemon's output.

Disable with DETECT_IN_WEB=0 when a stand-alone DETECT daemon already serves this DB.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
ENABLED = os.getenv("DETECT_IN_WEB", "1").strip().lower() not in ("0", "false", "no", "off")
DETECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DETECT")

# What this process is running / ran last (the admin panel reads it; completed runs
# are also persisted through modules.job_status so every gunicorn worker sees them).
_state = {"running": None, "last": None}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_id(label: str) -> str:
    return "detect_" + label.lower().replace(" ", "_").replace("-", "_")


class _Run:
    """Context manager: marks a run in the local state and in job_status."""
    def __init__(self, label, n=None):
        self.label, self.n, self.t0 = label, n, time.time()

    def __enter__(self):
        _state["running"] = {"label": self.label, "objects": self.n, "started_at": _now()}
        try:
            from modules import job_status
            job_status.record_start(_job_id(self.label))
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        ok = exc is None
        run = _state["running"] or {}
        counts = run.get("counts") or {}
        _state["last"] = {"label": self.label, "objects": run.get("objects", self.n), "counts": counts,
                          "started_at": run.get("started_at"), "finished_at": _now(),
                          "seconds": round(time.time() - self.t0, 1),
                          "status": "success" if ok else "error", "message": "" if ok else str(exc)[:200]}
        _state["running"] = None
        try:
            from modules import job_status
            msg = ("" if ok else str(exc)[:200]) or ", ".join(f"{k} {v}" for k, v in counts.items())
            job_status.record_finish(_job_id(self.label), ok, msg)
        except Exception:
            pass
        return False


def _pin_db_env() -> None:
    """DETECT connects with PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE. The web
    app hard-codes its database name (modules.database.DB_NAME) and several modules
    re-load kinder.env with override=True, so pin the name right before each run."""
    from modules.database import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
    os.environ.update({"PG_HOST": str(DB_HOST), "PG_PORT": str(DB_PORT), "PG_USER": str(DB_USER),
                       "PG_PASSWORD": str(DB_PASSWORD), "PG_DATABASE": str(DB_NAME)})


def _summary(res: dict, label: str) -> dict:
    hs = res.get("host_summary") or {}
    counts = {"objects": len(hs), "confirmed": 0, "review": 0, "none": 0}
    for v in hs.values():
        counts[v.get("host_status") or "none"] = counts.get(v.get("host_status") or "none", 0) + 1
    logger.info("[DETECT-WEB] %s: %s", label, counts)
    return counts


def run_for_names(names, label="Web") -> dict:
    """Cross-match + host rule + screening + finder for objects already in transient.objects."""
    names = [n for n in (names or []) if n]
    if not ENABLED or not names:
        return {}
    from function.run_detect import run_detect_for_names
    with _LOCK, _Run(label, len(names)):
        _pin_db_env()
        res = run_detect_for_names(names, group_name=label)
        counts = _summary(res, f"{label} ({len(names)} objects)")
        _state["running"]["counts"] = counts
    return counts


def run_single(name: str) -> dict:
    """The object page's Run / Refresh: returns DETECT's host_summary entry for the object."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_single
    with _LOCK, _Run(f"object {name}", 1):
        _pin_db_env()
        out = run_detect_single(name)
        _state["running"]["counts"] = {"objects": 1, (out.get("host_status") or "none"): 1}
    logger.info("[DETECT-WEB] %s: host_status=%s score=%s", name, out.get("host_status"), out.get("score"))
    return out


def run_followups() -> dict:
    """Daily: every Follow-up object re-screened (light curve, M, host with the latest catalogue)."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_followups
    with _LOCK, _Run("Follow-up"):
        _pin_db_env()
        res = run_detect_followups()
        counts = _summary(res, "Follow-up")
        _state["running"]["objects"] = counts["objects"]
        _state["running"]["counts"] = counts
    return counts


def run_recent(hours: float = 2.0) -> dict:
    """Objects TNS touched in the last *hours* — a catch-up when an import's name list is lost."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_recent
    with _LOCK, _Run(f"recent {hours:g}h"):
        _pin_db_env()
        res = run_detect_recent(hours)
        counts = _summary(res, f"recent {hours}h")
        _state["running"]["objects"] = counts["objects"]
        _state["running"]["counts"] = counts
    return counts


def is_running() -> bool:
    return _state["running"] is not None or _LOCK.locked()


def status() -> dict:
    """Everything the admin panel shows about the embedded DETECT: whether it is on,
    which copy of the code, where its data lives, what is running, what ran last
    (this process), and what the database says about the latest run overall."""
    version = {}
    try:
        for line in open(os.path.join(DETECT_DIR, "VERSION")).read().splitlines():
            k, _, v = line.partition(":")
            version[k.strip()] = v.strip()
    except OSError:
        pass
    data_dir = os.getenv("DETECT_DATA_DIR") or os.path.join(DETECT_DIR, "data")
    sfd_dir = os.path.join(data_dir, "dustmaps", "sfd")
    sfd_ok = all(os.path.exists(os.path.join(sfd_dir, f)) for f in ("SFD_dust_4096_ngp.fits", "SFD_dust_4096_sgp.fits"))
    out = {
        "enabled": ENABLED,
        "code_present": os.path.isdir(os.path.join(DETECT_DIR, "function")),
        "version": version,
        "data_dir": data_dir,
        "sfd_maps": sfd_ok,
        "running": _state["running"],
        "last": _state["last"],
        "db": {},
    }
    try:
        from modules.database import get_db_connection
        from psycopg2 import extras
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute("""
                SELECT MAX(run_date) AS last_run,
                       COUNT(*) FILTER (WHERE run_date > now() - interval '24 hours') AS screened_24h,
                       COUNT(*) FILTER (WHERE run_date > now() - interval '24 hours' AND host_status = 'confirmed') AS confirmed_24h,
                       COUNT(*) FILTER (WHERE run_date > now() - interval '24 hours' AND host_status = 'review') AS review_24h,
                       COUNT(*) FILTER (WHERE run_date > now() - interval '24 hours' AND host_status = 'none') AS none_24h
                FROM transient.detect_screen
            """)
            r = dict(cur.fetchone() or {})
            cur.execute("""
                SELECT COUNT(*) AS pending
                FROM transient.detect_screen s JOIN transient.objects o ON o.obj_id = s.obj_id
                WHERE o.status = 'Inbox' AND s.host_status IN ('confirmed', 'review')
                  AND s.run_date > now() - interval '7 days'
            """)
            r["pending_review"] = (cur.fetchone() or {}).get("pending", 0)
            cur.execute("SELECT COUNT(*) AS n FROM transient.objects WHERE status = 'Follow-up'")
            r["followups"] = (cur.fetchone() or {}).get("n", 0)
            cur.execute("""
                SELECT MAX(updated_date) AS last_xm,
                       COUNT(*) FILTER (WHERE updated_date > now() - interval '24 hours'
                                          AND NOT (match_data ? 'host_rule')) AS legacy_rows_24h
                FROM transient.cross_matches
            """)
            r.update(dict(cur.fetchone() or {}))
            try:
                cur.execute("SELECT COUNT(*) AS n FROM transient.detect_screen_history WHERE run_date > now() - interval '24 hours'")
                r["history_rows_24h"] = (cur.fetchone() or {}).get("n", 0)
            except Exception:
                conn.rollback()
                r["history_rows_24h"] = None
            for k in ("last_run", "last_xm"):
                if r.get(k) is not None:
                    r[k] = r[k].isoformat(timespec="seconds")
            out["db"] = r
    except Exception as e:
        out["db"] = {"error": str(e)[:200]}
    return out
