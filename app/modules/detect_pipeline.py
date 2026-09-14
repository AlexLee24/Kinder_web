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

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
ENABLED = os.getenv("DETECT_IN_WEB", "1").strip().lower() not in ("0", "false", "no", "off")


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
    with _LOCK:
        _pin_db_env()
        res = run_detect_for_names(names, group_name=label)
    return _summary(res, f"{label} ({len(names)} objects)")


def run_single(name: str) -> dict:
    """The object page's Run / Refresh: returns DETECT's host_summary entry for the object."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_single
    with _LOCK:
        _pin_db_env()
        out = run_detect_single(name)
    logger.info("[DETECT-WEB] %s: host_status=%s score=%s", name, out.get("host_status"), out.get("score"))
    return out


def run_followups() -> dict:
    """Daily: every Follow-up object re-screened (light curve, M, host with the latest catalogue)."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_followups
    with _LOCK:
        _pin_db_env()
        res = run_detect_followups()
    return _summary(res, "Follow-up")


def run_recent(hours: float = 2.0) -> dict:
    """Objects TNS touched in the last *hours* — a catch-up when an import's name list is lost."""
    if not ENABLED:
        return {}
    from function.run_detect import run_detect_recent
    with _LOCK:
        _pin_db_env()
        res = run_detect_recent(hours)
    return _summary(res, f"recent {hours}h")
