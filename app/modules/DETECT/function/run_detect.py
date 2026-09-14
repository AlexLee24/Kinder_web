"""Run DETECT on objects that are already in transient.objects.

This is the entry point another program uses (the Kinder web app vendors
``function/`` and calls these after its own TNS import, and from the object
page's Run button). TNS download / scheduling stay in DETECT_pipe.py.

    from function.run_detect import run_detect_for_names, run_detect_followups
    run_detect_for_names(["2026abdm", "2026abnn"])
"""
from __future__ import annotations

from psycopg2 import extras

from function.database import get_db_connection
from function.module.cross_match import run_cross_match_pipeline
from function.module.tns_ingest import bare_name


def _targets_for(sql: str, params: tuple) -> list[tuple]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return [(float(r["ra"]), float(r["dec"]), r["name"]) for r in rows
            if r.get("ra") is not None and r.get("dec") is not None]


def run_detect_for_names(names: list[str], group_name: str = "Web") -> dict:
    """Cross-match + host rule + screening + image + upload for the named objects."""
    wanted = sorted({bare_name(n) for n in names if n})
    if not wanted:
        return {"desi": {}, "lens": {}, "images": {}, "host_summary": {}}
    targets = _targets_for(
        "SELECT name, ra, dec FROM transient.objects WHERE name = ANY(%s)", (wanted,))
    return run_cross_match_pipeline({"targets": targets, "count": len(targets)}, group_name)


def run_detect_single(name: str) -> dict:
    """One object (the marshal's Run / Refresh button). Returns its host_summary entry."""
    res = run_detect_for_names([name], group_name="Web")
    return (res.get("host_summary") or {}).get(bare_name(name), {})


def run_detect_followups(group_name: str = "Follow-up") -> dict:
    """Every object a person put in Follow-up: re-screened so M and the host track the latest data."""
    targets = _targets_for("SELECT name, ra, dec FROM transient.objects WHERE status = 'Follow-up'", ())
    if not targets:
        return {"desi": {}, "lens": {}, "images": {}, "host_summary": {}}
    return run_cross_match_pipeline({"targets": targets, "count": len(targets)}, group_name)


def run_detect_recent(hours: float = 2.0, group_name: str = "Web") -> dict:
    """Objects TNS touched in the last *hours* (by last_modified_date) — what an
    hourly import just wrote, without needing the file it came from."""
    targets = _targets_for(
        "SELECT name, ra, dec FROM transient.objects "
        "WHERE last_modified_date >= (EXTRACT(EPOCH FROM now()) / 86400.0 + 40587.0) - %s / 24.0",
        (float(hours),))
    if not targets:
        return {"desi": {}, "lens": {}, "images": {}, "host_summary": {}}
    return run_cross_match_pipeline({"targets": targets, "count": len(targets)}, group_name)
