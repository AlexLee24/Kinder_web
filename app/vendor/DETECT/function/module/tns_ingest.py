"""TNS CSV -> transient.objects (+ discovery photometry point).

DETECT owns the TNS download; the marshal (kinder_web) reads what is written
here. The column set and update semantics mirror the marshal's own importer so
the two can coexist, with one deliberate difference: ``discovery_filter`` gets
the TNS filter *name* (``r``, ``orange``, ``L`` …), which is what the
absolute-magnitude calculator understands, not the numeric TNS filter id.

obj_id policy: a new object gets ``kinder_id`` (year·10⁶ + name rank — the
scheme documented for the marshal). An object that already exists under its
name keeps whatever obj_id it has; only its TNS fields are refreshed.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2 import extras

from function.database import get_db_connection

_MJD_EPOCH = datetime(1858, 11, 17)
_NAME_RE = re.compile(r"^(?:AT|SN)?(\d{4})([a-z]+)$", re.I)

OBJECT_COLUMNS = (
    "obj_id", "kinder_id", "name_prefix", "name", "ra", "dec", "redshift", "type",
    "report_group", "source_group", "discovery_date", "discovery_mag", "discovery_filter",
    "reporters", "received_date", "internal_name", "discovery_ads", "class_ads",
    "creation_date", "last_phot_date", "last_modified_date",
)

UPSERT_SQL = f"""
INSERT INTO transient.objects ({", ".join(OBJECT_COLUMNS)}, status, tag)
VALUES ({", ".join("%s" for _ in OBJECT_COLUMNS)}, 'Inbox', '{{}}'::text[])
ON CONFLICT (name) DO UPDATE SET
    kinder_id          = COALESCE(transient.objects.kinder_id, EXCLUDED.kinder_id),
    name_prefix        = COALESCE(EXCLUDED.name_prefix, transient.objects.name_prefix),
    ra                 = COALESCE(EXCLUDED.ra, transient.objects.ra),
    dec                = COALESCE(EXCLUDED.dec, transient.objects.dec),
    redshift           = COALESCE(EXCLUDED.redshift, transient.objects.redshift),
    type               = COALESCE(EXCLUDED.type, transient.objects.type),
    report_group       = COALESCE(EXCLUDED.report_group, transient.objects.report_group),
    source_group       = COALESCE(EXCLUDED.source_group, transient.objects.source_group),
    discovery_date     = COALESCE(EXCLUDED.discovery_date, transient.objects.discovery_date),
    discovery_mag      = COALESCE(EXCLUDED.discovery_mag, transient.objects.discovery_mag),
    discovery_filter   = COALESCE(EXCLUDED.discovery_filter, transient.objects.discovery_filter),
    reporters          = CASE WHEN cardinality(EXCLUDED.reporters) > 0 THEN EXCLUDED.reporters
                              ELSE transient.objects.reporters END,
    received_date      = COALESCE(EXCLUDED.received_date, transient.objects.received_date),
    internal_name      = COALESCE(EXCLUDED.internal_name, transient.objects.internal_name),
    discovery_ads      = COALESCE(EXCLUDED.discovery_ads, transient.objects.discovery_ads),
    class_ads          = COALESCE(EXCLUDED.class_ads, transient.objects.class_ads),
    creation_date      = COALESCE(EXCLUDED.creation_date, transient.objects.creation_date),
    last_phot_date     = COALESCE(EXCLUDED.last_phot_date, transient.objects.last_phot_date),
    last_modified_date = GREATEST(COALESCE(EXCLUDED.last_modified_date, 0), COALESCE(transient.objects.last_modified_date, 0)),
    status             = CASE WHEN transient.objects.status = 'Snoozed'
                               AND EXCLUDED.last_modified_date > COALESCE(transient.objects.last_modified_date, 0)
                              THEN 'Inbox' ELSE transient.objects.status END
RETURNING obj_id, (xmax = 0) AS inserted
"""

# Objects a TNS update is about to wake (Snoozed -> Inbox): recorded in the
# marshal's audit table so the review page can say why they are back.
WAKE_AUDIT_SQL = """
INSERT INTO transient.tns_update_audit (obj_id, name, changed_fields, source)
SELECT o.obj_id, o.name,
       ARRAY['woke: Snoozed -> Inbox'] || ARRAY_REMOVE(ARRAY[
           CASE WHEN t.type IS DISTINCT FROM o.type AND t.type IS NOT NULL THEN 'type' END,
           CASE WHEN t.redshift IS DISTINCT FROM o.redshift AND t.redshift IS NOT NULL THEN 'redshift' END,
           CASE WHEN t.class_ads IS DISTINCT FROM o.class_ads AND t.class_ads IS NOT NULL THEN 'class_ads' END,
           CASE WHEN t.internal_name IS DISTINCT FROM o.internal_name AND t.internal_name IS NOT NULL THEN 'internal_names' END
       ], NULL),
       'DETECT'
FROM tns_in t JOIN transient.objects o ON o.name = t.name
WHERE o.status = 'Snoozed' AND t.last_modified_date > COALESCE(o.last_modified_date, 0)
"""


def _audit_wakeups(cur) -> int:
    """Run WAKE_AUDIT_SQL against the ``tns_in`` temp table; tolerate a DB without the audit table."""
    try:
        cur.execute("SAVEPOINT wake_audit")
        cur.execute(WAKE_AUDIT_SQL)
        n = cur.rowcount
        cur.execute("RELEASE SAVEPOINT wake_audit")
        return n
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT wake_audit")
        print(f"[WARNING] wake-up audit skipped: {str(e).strip().splitlines()[0]}")
        return 0

PHOT_SQL = """
INSERT INTO transient.photometry (obj_id, name, "MJD", mag, mag_err, filter, source)
VALUES (%s, %s, %s, %s, NULL, %s, %s)
ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING
"""


# ---- parsing ---------------------------------------------------------------

def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip().strip('"')
    return None if s == "" or s.upper() in ("NULL", "NAN") else s


def _float(v):
    s = _clean(v)
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def to_mjd(value) -> float | None:
    s = _clean(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return (dt - _MJD_EPOCH).total_seconds() / 86400.0
    return None


def kinder_id_for(name: str) -> int | None:
    m = _NAME_RE.match(str(name or "").strip())
    if not m:
        return None
    year, suffix = int(m.group(1)), m.group(2).lower()
    rank = sum((ord(c) - 96) * (26 ** i) for i, c in enumerate(reversed(suffix)))
    return year * 1_000_000 + rank


def _reporters(v) -> list[str]:
    s = _clean(v)
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def parse_tns_row(row) -> dict | None:
    """One TNS public-objects CSV row -> column dict for the upsert, or None."""
    name = _clean(row.get("name"))
    ra, dec = _float(row.get("ra")), _float(row.get("declination"))
    if not name or ra is None or dec is None:
        return None
    kid = kinder_id_for(name)
    if kid is None:
        return None
    return {
        "obj_id": kid,
        "kinder_id": kid,
        "name_prefix": (_clean(row.get("name_prefix")) or "AT").upper(),
        "name": name,
        "ra": ra,
        "dec": dec,
        "redshift": _float(row.get("redshift")),
        "type": _clean(row.get("type")),
        "report_group": _clean(row.get("reporting_group")),
        "source_group": _clean(row.get("source_group")),
        "discovery_date": to_mjd(row.get("discoverydate")),
        "discovery_mag": _float(row.get("discoverymag")),
        "discovery_filter": _clean(row.get("filter")),          # name, not discmagfilter (id)
        "reporters": _reporters(row.get("reporters")),
        "received_date": to_mjd(row.get("time_received")),
        "internal_name": _clean(row.get("internal_names")),
        "discovery_ads": _clean(row.get("Discovery_ADS_bibcode") or row.get("discovery_ads_bibcode")),
        "class_ads": _clean(row.get("Class_ADS_bibcodes") or row.get("class_ads_bibcodes")),
        "creation_date": to_mjd(row.get("creationdate")),
        "last_phot_date": to_mjd(row.get("last_photometry_date")),
        "last_modified_date": to_mjd(row.get("lastmodified")),
    }


def read_tns_csv(csv_path: Path | str) -> list[dict]:
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, skiprows=1, dtype=str, keep_default_na=False)   # row 1 is the date range
    df.columns = df.columns.str.strip().str.replace('"', "")
    parsed = []
    for _, row in df.iterrows():
        try:
            rec = parse_tns_row(row)
        except (ValueError, TypeError):
            rec = None
        if rec is not None:
            parsed.append(rec)
    return parsed


# ---- writing ---------------------------------------------------------------

def _seed_discovery_photometry(cur, phot_rows, result: dict) -> None:
    """Seed the discovery point unless an equivalent one exists. The marshal's
    importer stored discovery MJDs truncated to the hour, so "equivalent" is
    same object, same magnitude, within 0.05 d — decided in SQL so a full
    backfill does not pull the whole photometry table into memory."""
    if not phot_rows:
        return
    cur.execute("SAVEPOINT tns_phot")
    try:
        cur.execute(
            "CREATE TEMP TABLE tns_disc (obj_id BIGINT, name TEXT, mjd DOUBLE PRECISION, "
            "mag DOUBLE PRECISION, filter TEXT, source TEXT) ON COMMIT DROP"
        )
        extras.execute_values(cur, "INSERT INTO tns_disc VALUES %s", phot_rows, page_size=2000)
        cur.execute(
            """
            INSERT INTO transient.photometry (obj_id, name, "MJD", mag, mag_err, filter, source)
            SELECT t.obj_id, t.name, t.mjd, t.mag, NULL, t.filter, t.source
            FROM tns_disc t
            WHERE NOT EXISTS (
                SELECT 1 FROM transient.photometry p
                WHERE p.obj_id = t.obj_id
                  AND p.mag IS NOT NULL AND abs(p.mag - t.mag) < 1e-3
                  AND abs(p."MJD" - t.mjd) < 0.05
            )
            ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING
            """
        )
        result["photometry_added"] = cur.rowcount
        cur.execute("RELEASE SAVEPOINT tns_phot")
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT tns_phot")
        print(f"[WARNING] discovery photometry not written: {str(e).strip()[:120]}")


BULK_THRESHOLD = 5000      # files larger than this take the set-based path


def ingest_tns_csv(csv_path: Path | str) -> dict:
    """Upsert every object in a TNS CSV; seed its discovery photometry point.

    Each row runs inside its own SAVEPOINT so one bad row (e.g. a primary-key
    clash from an older importer's obj_id policy) is reported and skipped
    instead of aborting the transaction and silently losing the whole file.
    """
    csv_path = Path(csv_path)
    result = {"inserted": 0, "updated": 0, "failed": [], "names": [], "photometry_added": 0, "woke": 0}
    if not csv_path.exists():
        print(f"[WARNING] TNS CSV not found: {csv_path}")
        return result
    try:
        records = read_tns_csv(csv_path)
    except (pd.errors.ParserError, OSError) as e:
        print(f"[WARNING] Failed to read TNS CSV ({type(e).__name__}): {e}")
        return result
    if not records:
        return result

    conn = get_db_connection()
    if len(records) >= BULK_THRESHOLD:
        try:
            ingest_tns_records_bulk(conn, records, result)
        except psycopg2.Error as e:
            conn.rollback()
            print(f"[ERROR] TNS bulk ingest aborted ({type(e).__name__}): {e}")
            return result
        finally:
            conn.close()
        print(f"[INFO] TNS ingest (bulk): {result['inserted']} new, {result['updated']} updated, "
              f"{result['photometry_added']} discovery points added"
              f"{', ' + str(len(result['failed'])) + ' skipped' if result['failed'] else ''}")
        for name, reason in result["failed"][:20]:
            print(f"[WARNING] TNS object {name} not written: {reason}")
        return result

    try:
        with conn.cursor() as cur:
            _copy_records(cur, records)
            result["woke"] = _audit_wakeups(cur)
            phot_rows = []
            for i, rec in enumerate(records, 1):
                if i % 10000 == 0:
                    conn.commit()                       # a long backfill should not be one giant transaction
                    print(f"  ... {i:,}/{len(records):,} objects")
                cur.execute("SAVEPOINT tns_row")
                try:
                    cur.execute(UPSERT_SQL, tuple(rec[c] for c in OBJECT_COLUMNS))
                    obj_id, inserted = cur.fetchone()
                    cur.execute("RELEASE SAVEPOINT tns_row")
                except psycopg2.Error as e:
                    cur.execute("ROLLBACK TO SAVEPOINT tns_row")
                    reason = (e.pgerror or type(e).__name__).strip().splitlines()[0]
                    result["failed"].append((rec["name"], reason))
                    continue
                result["inserted" if inserted else "updated"] += 1
                result["names"].append(rec["name"])
                if rec["discovery_date"] is not None and rec["discovery_mag"] is not None:
                    phot_rows.append((obj_id, rec["name"], rec["discovery_date"], rec["discovery_mag"],
                                      rec["discovery_filter"], rec["source_group"] or "TNS"))
            _seed_discovery_photometry(cur, phot_rows, result)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] TNS ingest aborted ({type(e).__name__}): {e}")
        return result
    finally:
        conn.close()

    print(f"[INFO] TNS ingest: {result['inserted']} new, {result['updated']} updated, "
          f"{result['photometry_added']} discovery points added"
          f"{', ' + str(len(result['failed'])) + ' failed' if result['failed'] else ''}")
    for name, reason in result["failed"]:
        print(f"[WARNING] TNS object {name} not written: {reason}")
    return result


def bare_name(name: str) -> str:
    """'AT 2021nto' / 'SN2021nto' / '2021nto' -> '2021nto' (the DB key)."""
    s = str(name or "").strip()
    m = re.match(r"^(?:AT|SN|TDE|FRB|EP)\s*(\d{4}[a-zA-Z]+)$", s, re.I)
    return m.group(1) if m else s


_UPDATE_COLS = [c for c in OBJECT_COLUMNS if c not in ("obj_id", "kinder_id", "name", "reporters")]

BULK_UPDATE_SQL = (
    "UPDATE transient.objects AS o SET "
    + ", ".join(f"{c} = COALESCE(t.{c}, o.{c})" for c in _UPDATE_COLS)
    + ", kinder_id = COALESCE(o.kinder_id, t.kinder_id)"
    + ", reporters = CASE WHEN cardinality(t.reporters) > 0 THEN t.reporters ELSE o.reporters END"
    + ", status = CASE WHEN o.status = 'Snoozed' AND t.last_modified_date > COALESCE(o.last_modified_date, 0)"
    + "                THEN 'Inbox' ELSE o.status END "
    "FROM tns_in t WHERE o.name = t.name"
)

BULK_INSERT_SQL = (
    f"INSERT INTO transient.objects ({', '.join(OBJECT_COLUMNS)}, status, tag) "
    f"SELECT {', '.join('t.' + c for c in OBJECT_COLUMNS)}, 'Inbox', '{{}}'::text[] "
    "FROM tns_in t "
    "WHERE NOT EXISTS (SELECT 1 FROM transient.objects o WHERE o.name = t.name) "
    "  AND NOT EXISTS (SELECT 1 FROM transient.objects o WHERE o.obj_id = t.obj_id)"
)

BULK_COLLISION_SQL = (
    "SELECT t.name, o.name FROM tns_in t JOIN transient.objects o ON o.obj_id = t.obj_id "
    "WHERE o.name <> t.name AND NOT EXISTS (SELECT 1 FROM transient.objects x WHERE x.name = t.name)"
)


def _copy_records(cur, records: list[dict]) -> None:
    """COPY the parsed rows into a temp table tns_in (dropped at commit)."""
    import csv
    import io
    cols = list(OBJECT_COLUMNS)
    cur.execute(
        "CREATE TEMP TABLE tns_in ("
        "obj_id BIGINT, kinder_id BIGINT, name_prefix TEXT, name TEXT, ra DOUBLE PRECISION, "
        "dec DOUBLE PRECISION, redshift DOUBLE PRECISION, type TEXT, report_group TEXT, source_group TEXT, "
        "discovery_date DOUBLE PRECISION, discovery_mag DOUBLE PRECISION, discovery_filter TEXT, "
        "reporters TEXT[], received_date DOUBLE PRECISION, internal_name TEXT, discovery_ads TEXT, "
        "class_ads TEXT, creation_date DOUBLE PRECISION, last_phot_date DOUBLE PRECISION, "
        "last_modified_date DOUBLE PRECISION) ON COMMIT DROP"
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in records:
        row = []
        for c in cols:
            v = r[c]
            if c == "reporters":
                v = "{" + ",".join('"' + x.replace('"', '\\"') + '"' for x in v) + "}"
            row.append("" if v is None else v)
        w.writerow(row)
    buf.seek(0)
    cur.copy_expert(f"COPY tns_in ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
    cur.execute("CREATE INDEX ON tns_in (name)")
    cur.execute("ANALYZE tns_in")


def ingest_tns_records_bulk(conn, records: list[dict], result: dict) -> None:
    """Set-based upsert: one UPDATE for known names, one INSERT for new ones.

    Rows whose kinder_id is already an obj_id under a different name (a prefix
    variant left by an older importer) are reported and skipped, not inserted.
    """
    with conn.cursor() as cur:
        _copy_records(cur, records)
        cur.execute(BULK_COLLISION_SQL)
        for new_name, holder in cur.fetchall():
            result["failed"].append((new_name, f"obj_id already used by {holder}"))
        result["woke"] = _audit_wakeups(cur)
        cur.execute(BULK_UPDATE_SQL)
        result["updated"] = cur.rowcount
        cur.execute(BULK_INSERT_SQL)
        result["inserted"] = cur.rowcount
        cur.execute(
            "SELECT o.obj_id, t.name, t.discovery_date, t.discovery_mag, t.discovery_filter, "
            "COALESCE(t.source_group, 'TNS') FROM tns_in t JOIN transient.objects o ON o.name = t.name "
            "WHERE t.discovery_date IS NOT NULL AND t.discovery_mag IS NOT NULL"
        )
        phot_rows = cur.fetchall()
        result["names"] = [r[1] for r in phot_rows]
        _seed_discovery_photometry(cur, phot_rows, result)
    conn.commit()


def load_user_host_decisions(names: list[str]) -> dict[str, dict]:
    """Host decisions people made on the marshal, keyed by the caller's name.

    The marshal stores them in transient.cross_matches.match_data:
    ``host_user = true`` on the row a person chose as host, ``false`` on rows
    they rejected (``false`` on every row = "no host"). Absent key = the pipeline
    decides. Returns ``{name: {'decision': 'host', 'uid': ..., 'by': ...}}`` or
    ``{name: {'decision': 'none', 'by': ...}}``.
    """
    if not names:
        return {}
    wanted = {n: bare_name(n) for n in names}
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT o.name, c.match_id, c.match_data->>'crossmatch_uid' AS uid,
                       (c.match_data->>'host_user')::boolean AS host_user,
                       c.match_data->>'host_user_by' AS by
                FROM transient.cross_matches c
                JOIN transient.objects o ON o.obj_id = c.obj_id
                WHERE o.name = ANY(%s) AND c.match_data ? 'host_user'
                ORDER BY c.match_id
                """,
                (list(set(wanted.values())),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    by_bare: dict[str, dict] = {}
    for r in rows:
        cur_d = by_bare.get(r["name"])
        if r["host_user"]:
            by_bare[r["name"]] = {"decision": "host", "uid": r["uid"], "match_id": r["match_id"], "by": r["by"]}
        elif cur_d is None:
            by_bare[r["name"]] = {"decision": "none", "by": r["by"]}
    return {n: by_bare[b] for n, b in wanted.items() if b in by_bare}


def load_object_meta(names: list[str]) -> dict[str, dict]:
    """transient.objects fields the screen needs, keyed by the caller's name."""
    if not names:
        return {}
    wanted = {n: bare_name(n) for n in names}
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT o.obj_id, o.name, o.ra, o.dec, o.redshift, o.type, o.discovery_mag,
                       o.discovery_filter, o.discovery_date, o.report_group, o.tag, o.status,
                       p.mag AS peak_mag, p.filter AS peak_filter, p."MJD" AS peak_mjd,
                       p.source AS peak_source, p.n_phot
                FROM transient.objects o
                LEFT JOIN LATERAL (
                    -- brightest real detection: limits carry mag_err = 0, junk carries mag 99
                    SELECT mag, filter, "MJD", source, count(*) OVER () AS n_phot
                    FROM transient.photometry
                    WHERE obj_id = o.obj_id AND mag BETWEEN 5 AND 30
                      AND (mag_err IS NULL OR mag_err > 0)
                    ORDER BY mag ASC LIMIT 1
                ) p ON true
                WHERE o.name = ANY(%s)
                """,
                (list(set(wanted.values())),),
            )
            by_bare = {r["name"]: dict(r) for r in cur.fetchall()}
            # The measured light curve (no limits, no mag-99 junk) for the decline-rate test.
            by_obj = {r["obj_id"]: r for r in by_bare.values() if r.get("obj_id") is not None}
            for r in by_obj.values():
                r["photometry"] = []
            if by_obj:
                cur.execute(
                    """
                    SELECT obj_id, "MJD" AS mjd, mag, mag_err, filter
                    FROM transient.photometry
                    WHERE obj_id = ANY(%s) AND mag BETWEEN 5 AND 30 AND (mag_err IS NULL OR mag_err > 0)
                    ORDER BY obj_id, "MJD"
                    """,
                    (list(by_obj),),
                )
                for r in cur.fetchall():
                    by_obj[r["obj_id"]]["photometry"].append(
                        {"mjd": r["mjd"], "mag": r["mag"], "mag_err": r["mag_err"], "filter": r["filter"]})
    finally:
        conn.close()
    return {n: by_bare[b] for n, b in wanted.items() if b in by_bare}
