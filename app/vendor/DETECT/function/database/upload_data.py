import logging
import re as _re
import time as _time
from datetime import datetime

import psycopg2
from psycopg2 import extras

from . import get_db_connection
from .catalogue import CatalogueService

logger = logging.getLogger(__name__)


def _record_db_change(obj_name: str, description: str, action: str):
    """Forward a DB change event to RunLogger if it is active this run."""
    try:
        from function.run_logger import RunLogger
        RunLogger.record_db_change(obj_name, description, action)
    except Exception:
        pass

_MJD_EPOCH = datetime(1858, 11, 17)
_KINDER_NAME_RE = _re.compile(r"^(\d{4})([a-z]+)$")


def _resolve_obj_id_with_prefix(cur, name: str) -> int | None:
    if not name:
        return None
    name = str(name).strip()
    cur.execute(
        "SELECT obj_id FROM transient.objects WHERE name = %s OR name ILIKE %s LIMIT 1",
        (name, name),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    m = _re.match(r"^(?:AT|SN|FRB|TDE|EP)(.+)$", name, _re.IGNORECASE)
    if m:
        bare = m.group(1)
        cur.execute("SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1", (bare,))
        row = cur.fetchone()
        if row:
            return row[0]
    for prefix in ("AT", "SN"):
        cur.execute("SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1", (prefix + name,))
        row = cur.fetchone()
        if row:
            return row[0]
    return None


def _to_mjd(date_str) -> float | None:
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            d = datetime.strptime(s[:n], fmt)
            delta = d - _MJD_EPOCH
            return delta.days + delta.seconds / 86400.0
        except Exception:
            pass
    return None


def _tns_name_to_kinder_id(name: str) -> int | None:
    m = _KINDER_NAME_RE.match(name)
    if not m:
        return None
    year = int(m.group(1))
    suffix = m.group(2)
    rank = sum((ord(c) - 96) * (26 ** i) for i, c in enumerate(reversed(suffix)))
    return year * 1_000_000 + rank


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class DataUploader:
    @staticmethod
    def add_photometry_bulk(photometry_data):
        if not photometry_data:
            return
        with get_db_connection() as conn:
            cur = conn.cursor()
            names = list({row[0] for row in photometry_data})
            cur.execute("SELECT name, obj_id FROM transient.objects WHERE name = ANY(%s)", (names,))
            name_map = {r[0]: r[1] for r in cur.fetchall()}
            rows = []
            for row in photometry_data:
                oid = name_map.get(row[0])
                if oid:
                    rows.append((oid, row[0], row[1], row[2], row[3], row[4], row[5]))
            if rows:
                extras.execute_batch(
                    cur,
                    "INSERT INTO transient.photometry "
                    "(obj_id, name, \"MJD\", mag, mag_err, filter, source) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING",
                    rows,
                    page_size=1000,
                )
            conn.commit()

    @staticmethod
    def sync_last_photometry_date(object_name: str):
        with get_db_connection() as conn:
            cur = conn.cursor()
            obj_id = _resolve_obj_id_with_prefix(cur, object_name)
            if obj_id is None:
                return
            cur.execute("SELECT MAX(\"MJD\") FROM transient.photometry WHERE obj_id = %s", (obj_id,))
            max_mjd = cur.fetchone()[0]
            cur.execute("UPDATE transient.objects SET last_phot_date = %s WHERE obj_id = %s", (max_mjd, obj_id))
            conn.commit()

    @staticmethod
    def save_flag_objects(flag_list: list):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "ALTER TABLE transient.cross_matches "
                    "ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE"
                )
                for item in flag_list:
                    if len(item) < 2:
                        continue
                    name = item[1]
                    cur.execute("SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1", (name,))
                    row = cur.fetchone()
                    if not row:
                        continue
                    obj_id = row[0]
                    cur.execute("SELECT match_id FROM transient.cross_matches WHERE obj_id = %s LIMIT 1", (obj_id,))
                    if cur.fetchone():
                        cur.execute("UPDATE transient.cross_matches SET flag = TRUE WHERE obj_id = %s", (obj_id,))
                    else:
                        cur.execute(
                            "INSERT INTO transient.cross_matches "
                            "(obj_id, name, catalog, separation, is_host, flag) "
                            "VALUES (%s,%s,'FLAGGED_LIST',0,FALSE,TRUE)",
                            (obj_id, name),
                        )
                conn.commit()
        except Exception as e:
            logger.error("save_flag_objects: %s", e)

    @staticmethod
    def save_target_image(target_name: str, image_data: bytes, source: str = "DESI") -> bool:
        if not image_data:
            return False
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                obj_id = _resolve_obj_id_with_prefix(cur, target_name)
                if obj_id is None:
                    return False
                cur.execute(
                    "SELECT image_id FROM transient.target_images "
                    "WHERE obj_id = %s AND source = %s LIMIT 1",
                    (obj_id, source),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE transient.target_images "
                        "SET image_data = %s, name = %s WHERE image_id = %s",
                        (psycopg2.Binary(image_data), target_name, row[0]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO transient.target_images (obj_id, name, image_data, source) "
                        "VALUES (%s,%s,%s,%s)",
                        (obj_id, target_name, psycopg2.Binary(image_data), source),
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error("save_target_image %s: %s", target_name, e)
            return False

    SCREEN_DDL = """
        CREATE TABLE IF NOT EXISTS transient.detect_screen (
            obj_id        BIGINT PRIMARY KEY REFERENCES transient.objects(obj_id) ON DELETE CASCADE,
            name          TEXT,
            score         INTEGER NOT NULL DEFAULT 0,
            host_status   TEXT,          -- confirmed | review | none
            tags          TEXT[] NOT NULL DEFAULT '{}',
            flags         JSONB,
            host_targetid BIGINT,
            z             DOUBLE PRECISION,
            z_source      TEXT,
            abs_mag       REAL,
            abs_mag_band  TEXT,
            center_sep_arcsec REAL,
            d_dlr         REAL,
            offset_kpc    REAL,
            run_date      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """

    SCREEN_HISTORY_DDL = """
        CREATE TABLE IF NOT EXISTS transient.detect_screen_history (
            hist_id       BIGSERIAL PRIMARY KEY,
            obj_id        BIGINT NOT NULL,
            name          TEXT,
            run_date      TIMESTAMPTZ NOT NULL DEFAULT now(),
            score         INTEGER,
            host_status   TEXT,
            tags          TEXT[],
            host_targetid BIGINT,
            z             DOUBLE PRECISION,
            abs_mag       REAL,
            abs_mag_source TEXT,
            d_dlr         REAL,
            flags         JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_detect_screen_history_obj ON transient.detect_screen_history (obj_id, run_date DESC);
        CREATE INDEX IF NOT EXISTS idx_detect_screen_history_run ON transient.detect_screen_history (run_date DESC);
    """

    @staticmethod
    def save_screen_results(screen_rows: list[dict]) -> int:
        """DETECT-owned screening table + DETECT's tags on transient.objects.

        Tags in screening.DETECT_TAG_VOCAB are replaced wholesale on every run;
        any other tag on the object (human-added) is left untouched.
        """
        from function.module.screening import DETECT_TAG_VOCAB
        if not screen_rows:
            return 0
        written = 0
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(DataUploader.SCREEN_DDL)
                cur.execute(DataUploader.SCREEN_HISTORY_DDL)
                cur.execute("ALTER TABLE transient.detect_screen ADD COLUMN IF NOT EXISTS host_status TEXT")
                cur.execute("ALTER TABLE transient.detect_screen "
                            "ADD COLUMN IF NOT EXISTS abs_mag_source TEXT, "
                            "ADD COLUMN IF NOT EXISTS abs_mag_discovery REAL, "
                            "ADD COLUMN IF NOT EXISTS peak_mag REAL, "
                            "ADD COLUMN IF NOT EXISTS peak_filter TEXT, "
                            "ADD COLUMN IF NOT EXISTS peak_mjd DOUBLE PRECISION")
                for row in screen_rows:
                    obj_id = _resolve_obj_id_with_prefix(cur, row["target_name"])
                    if obj_id is None:
                        continue
                    f = row.get("flags") or {}
                    cur.execute(
                        """
                        INSERT INTO transient.detect_screen
                            (obj_id, name, score, host_status, tags, flags, host_targetid, z, z_source,
                             abs_mag, abs_mag_band, center_sep_arcsec, d_dlr, offset_kpc, run_date,
                             abs_mag_source, abs_mag_discovery, peak_mag, peak_filter, peak_mjd)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s)
                        ON CONFLICT (obj_id) DO UPDATE SET
                            name = EXCLUDED.name, score = EXCLUDED.score, host_status = EXCLUDED.host_status,
                            tags = EXCLUDED.tags,
                            flags = EXCLUDED.flags, host_targetid = EXCLUDED.host_targetid,
                            z = EXCLUDED.z, z_source = EXCLUDED.z_source,
                            abs_mag = EXCLUDED.abs_mag, abs_mag_band = EXCLUDED.abs_mag_band,
                            center_sep_arcsec = EXCLUDED.center_sep_arcsec, d_dlr = EXCLUDED.d_dlr,
                            offset_kpc = EXCLUDED.offset_kpc, run_date = now(),
                            abs_mag_source = EXCLUDED.abs_mag_source, abs_mag_discovery = EXCLUDED.abs_mag_discovery,
                            peak_mag = EXCLUDED.peak_mag, peak_filter = EXCLUDED.peak_filter, peak_mjd = EXCLUDED.peak_mjd
                        """,
                        (obj_id, row["target_name"], int(row.get("score", 0)), f.get("host_status"),
                         list(row.get("tags") or []),
                         extras.Json(f), f.get("host_targetid"), f.get("z"), f.get("z_source"),
                         f.get("abs_mag"), f.get("abs_mag_band"), f.get("center_sep_arcsec"),
                         f.get("d_dlr"), f.get("offset_kpc"),
                         f.get("abs_mag_source"), f.get("abs_mag_discovery"), f.get("peak_mag"),
                         f.get("peak_filter"), f.get("peak_mjd")),
                    )
                    # detect_screen keeps only the latest verdict; the history is append-only.
                    cur.execute(
                        """
                        INSERT INTO transient.detect_screen_history
                            (obj_id, name, score, host_status, tags, host_targetid, z, abs_mag, abs_mag_source, d_dlr, flags)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (obj_id, row["target_name"], int(row.get("score", 0)), f.get("host_status"),
                         list(row.get("tags") or []), f.get("host_targetid"), f.get("z"), f.get("abs_mag"),
                         f.get("abs_mag_source"), f.get("d_dlr"), extras.Json(f)),
                    )
                    # The marshal filters on these two object columns and nothing else fills them.
                    if f.get("abs_mag") is not None:
                        cur.execute(
                            "UPDATE transient.objects SET brightest_mag = %s, brightest_abs_mag = %s WHERE obj_id = %s",
                            (f.get("peak_mag") if f.get("abs_mag_source") == "peak" else f.get("app_mag"),
                             f.get("abs_mag"), obj_id),
                        )
                    cur.execute(
                        """
                        UPDATE transient.objects
                        SET tag = COALESCE((SELECT array_agg(t) FROM unnest(tag) AS t WHERE t <> ALL(%s)), '{}')
                                  || %s::text[]
                        WHERE obj_id = %s
                        """,
                        (DETECT_TAG_VOCAB, list(row.get("tags") or []), obj_id),
                    )
                    written += 1
                conn.commit()
        except Exception as e:
            logger.error("save_screen_results: %s", e)
            print(f"[ERROR] save_screen_results failed: {type(e).__name__}: {e}")
        return written

    @staticmethod
    def save_cross_match_results(results_list: list):
        if not results_list:
            return

        def _extract_redshift(md: dict | None):
            if not isinstance(md, dict):
                return None
            for key in ("z", "redshift", "z_source", "z_lens", "Z", "zph", "z(s)"):
                if key in md:
                    z = _safe_float(md.get(key))
                    if z is not None:
                        return z
            return None

        def _build_note(catalog_name: str, md: dict | None):
            if not isinstance(md, dict):
                return ""
            note_parts = []
            if CatalogueService.is_lens_catalog(catalog_name):
                for key, label in (
                    ("z_lens", "z_lens"),
                    ("z_source", "z_source"),
                    ("grade", "grade"),
                    ("lens_probability", "lens_probability"),
                    ("origin_catalog_name", "catalog"),
                ):
                    val = md.get(key)
                    if val is not None and str(val).strip() != "":
                        note_parts.append(f"{label}={val}")
            else:
                for key, label in (
                    ("spectype", "spectype"), ("survey", "survey"), ("program", "program"),
                    ("redshift_err", "redshift_err"), ("zwarn", "zwarn"), ("delta_chi_2", "delta_chi_2"),
                    ("morphtype", "morph"), ("shape_source", "shape"), ("d_dlr", "d_dlr"),
                    ("offset_kpc", "offset_kpc"), ("mass_cg", "mass_cg"), ("w1_w2_vega", "W1-W2"),
                ):
                    val = md.get(key)
                    if val is not None and str(val).strip() != "":
                        note_parts.append(f"{label}={val}")
            return "; ".join(note_parts)

        candidate_id_keys = (
            "TARGETID",
            "targetid",
            "desi_target_id",
            "source_id",
            "obj_id",
            "objid",
            "object_id",
            "id",
            "name",
            "obj_name",
        )
        numeric_re = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"

        def _truthy_bool(value) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            if isinstance(value, (int, float)):
                return value != 0
            return str(value).strip().lower() in {"true", "t", "yes", "y", "1"}

        def _candidate_identity_pairs(md: dict | None) -> list[tuple[str, str]]:
            if not isinstance(md, dict):
                return []
            pairs = []
            for key in candidate_id_keys:
                value = md.get(key)
                if value not in (None, ""):
                    pairs.append((key, str(value).strip()))
            return pairs

        def _fetch_existing_cross_match(cur, obj_id: int, catalog_name: str, md: dict | None, sep: float | None):
            select_sql = (
                "SELECT match_id, is_host, match_data "
                "FROM transient.cross_matches "
                "WHERE obj_id = %s AND catalog = %s "
            )
            order_sql = "ORDER BY is_host DESC NULLS LAST, updated_date DESC NULLS LAST, match_id DESC LIMIT 1"

            uid = md.get("crossmatch_uid") if isinstance(md, dict) else None
            if uid:
                cur.execute(
                    select_sql + "AND match_data->>'crossmatch_uid' = %s " + order_sql,
                    (obj_id, catalog_name, str(uid)),
                )
                existing = cur.fetchone()
                if existing:
                    return existing

            for key, value in _candidate_identity_pairs(md):
                cur.execute(
                    select_sql + "AND match_data->>%s = %s " + order_sql,
                    (obj_id, catalog_name, key, value),
                )
                existing = cur.fetchone()
                if existing:
                    return existing

            ra = _safe_float(md.get("ra")) if isinstance(md, dict) else None
            dec = _safe_float(md.get("dec")) if isinstance(md, dict) else None
            if ra is not None and dec is not None:
                cur.execute(
                    select_sql
                    + """
                    AND (match_data->>'ra') ~ %s
                    AND (match_data->>'dec') ~ %s
                    AND ROUND((match_data->>'ra')::numeric, 7) = ROUND(%s::numeric, 7)
                    AND ROUND((match_data->>'dec')::numeric, 7) = ROUND(%s::numeric, 7)
                    """
                    + order_sql,
                    (obj_id, catalog_name, numeric_re, numeric_re, ra, dec),
                )
                existing = cur.fetchone()
                if existing:
                    return existing

            # Last-resort compatibility for old rows that only had separation.
            if sep is not None:
                cur.execute(
                    select_sql
                    + """
                    AND separation IS NOT NULL
                    AND ROUND(separation::numeric, 2) = ROUND(%s::numeric, 2)
                    """
                    + order_sql,
                    (obj_id, catalog_name, sep),
                )
                existing = cur.fetchone()
                if existing:
                    return existing

            return None

        def _merge_match_data_preserving_host(md: dict, existing_is_host, existing_md) -> tuple[dict, bool]:
            existing_md = existing_md if isinstance(existing_md, dict) else {}
            preserved_is_host = _truthy_bool(existing_is_host) or _truthy_bool(existing_md.get("is_Host"))
            merged_md = dict(existing_md)
            merged_md.update(md)
            merged_md["is_Host"] = preserved_is_host
            return merged_md, preserved_is_host

        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                normalized = []
                for r in results_list:
                    target_name = r.get("target_name") or r.get("tns_name")
                    if not target_name:
                        continue
                    catalog_name = CatalogueService.build_catalog_name(
                        catalog_name=r.get("catalog_name"),
                        lens_catalog=r.get("lens_catalog"),
                    )
                    if catalog_name == "DETECT_STATUS_RUN":
                        continue
                    separation = r.get("separation_arcsec")
                    if separation is None:
                        separation = 0
                    if "match_data" in r and isinstance(r.get("match_data"), dict):
                        match_data = r.get("match_data")
                    else:
                        match_data = dict(r)
                        for k in ("tns_name_prefix", "tns_name", "tns_ra", "tns_dec", "tns_discoverydate", "tns_internal_names", "lens_catalog"):
                            match_data.pop(k, None)
                    normalized.append(
                        {
                            "target_name": target_name,
                            "catalog_name": catalog_name,
                            "separation_arcsec": separation,
                            "is_host": bool(r.get("is_host", r.get("is_Host", False))),
                            "match_data": match_data,
                            "run_date": r.get("run_date"),
                            "updated_date": r.get("updated_date"),
                            "status": r.get("status") or "Success",
                            "error_message": r.get("error_message"),
                        }
                    )
                if not normalized:
                    return

                object_rows = {}
                for item in results_list:
                    tname = item.get("tns_name") or item.get("target_name")
                    if not tname or tname in object_rows:
                        continue
                    kid = _tns_name_to_kinder_id(tname) or _tns_name_to_kinder_id(tname.lower())
                    if kid is None:
                        continue
                    ra = _safe_float(item.get("tns_ra"))
                    dec = _safe_float(item.get("tns_dec"))
                    # Skip if coordinates are missing — object was already inserted
                    # by _upload_tns_objects_directly with proper RA/Dec; inserting
                    # here with NULL ra/dec would violate the NOT NULL constraint.
                    if ra is None or dec is None:
                        continue
                    mjd = _to_mjd(item.get("tns_discoverydate"))
                    int_name = str(item.get("tns_internal_names", "") or "").strip() or None
                    prefix = item.get("tns_name_prefix") or "AT"
                    object_rows[tname] = (kid, prefix, tname, ra, dec, mjd, int_name, kid)

                if object_rows:
                    now_mjd = (_time.time() / 86400.0) + 40587.0
                    extras.execute_batch(
                        cur,
                        """
                        INSERT INTO transient.objects
                            (obj_id, name_prefix, name, ra, dec, discovery_date,
                             internal_name, kinder_id, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Inbox')
                        ON CONFLICT (name) DO UPDATE SET
                            kinder_id = EXCLUDED.kinder_id,
                            last_modified_date = %s
                        """,
                        [row + (now_mjd,) for row in object_rows.values()],
                        page_size=500,
                    )
                    conn.commit()

                # Build name→obj_id map using prefix-aware resolution
                # (handles AT2026xxx vs 2026xxx mismatch)
                unique_names = list({r["target_name"] for r in normalized})
                name_to_obj_id: dict[str, int] = {}
                for uname in unique_names:
                    oid = _resolve_obj_id_with_prefix(cur, uname)
                    if oid is not None:
                        name_to_obj_id[uname] = oid
                    else:
                        logger.warning(
                            "save_cross_match_results: obj_id not found for '%s' – "
                            "ensure object is inserted into transient.objects first",
                            uname,
                        )

                # Query existing cross_match counts before this run (for status protection logic)
                existing_match_counts: dict[int, int] = {}
                if name_to_obj_id:
                    cur.execute(
                        "SELECT obj_id, COUNT(*) FROM transient.cross_matches "
                        "WHERE obj_id = ANY(%s) GROUP BY obj_id",
                        (list(set(name_to_obj_id.values())),)
                    )
                    for _crow in cur.fetchall():
                        existing_match_counts[int(_crow[0])] = int(_crow[1])

                persisted_rows = []
                for r in normalized:
                    obj_id = name_to_obj_id.get(r["target_name"])
                    if obj_id is None:
                        continue
                    md = dict(r.get("match_data") or {})
                    z = _extract_redshift(md)
                    note = _build_note(r.get("catalog_name", ""), md)
                    sep = _safe_float(r.get("separation_arcsec"))
                    catalog_name = r.get("catalog_name", "")
                    is_host = bool(r.get("is_host", False))
                    md.setdefault("is_Host", is_host)

                    existing = _fetch_existing_cross_match(cur, obj_id, catalog_name, md, sep)

                    if existing:
                        match_id, existing_is_host, existing_md = existing
                        # The pipeline owns is_host: a re-run under a newer catalog or rule may
                        # raise or lower it. People express their judgement through the
                        # object's status / tags, not by pinning this flag. The previous value
                        # is kept in match_data so a change is visible.
                        effective_is_host = bool(is_host)
                        existing_md = existing_md if isinstance(existing_md, dict) else {}
                        if "host_user" not in md and existing_md.get("host_user") is not None:
                            # a person's decision on the marshal outlives any single run
                            effective_is_host = bool(existing_md["host_user"])

                        merged_md = dict(existing_md)
                        merged_md.update(md)
                        merged_md["is_Host"] = effective_is_host
                        if bool(existing_is_host) != effective_is_host:
                            merged_md["is_host_previous"] = bool(existing_is_host)
                            _record_db_change(
                                r["target_name"],
                                f"is_host {bool(existing_is_host)} -> {effective_is_host} ({catalog_name})",
                                "cross_matches updated",
                            )

                        cur.execute(
                            "UPDATE transient.cross_matches SET "
                            "updated_date = now(), "
                            "is_host = %s, "
                            "redshift = COALESCE(%s, redshift), "
                            "note = CASE WHEN %s != '' THEN %s ELSE note END, "
                            "status = %s, "
                            "error_message = %s, "
                            "match_data = %s "
                            "WHERE match_id = %s",
                            (
                                effective_is_host,
                                z,
                                note or "",
                                note,
                                r.get("status", "Success"),
                                r.get("error_message"),
                                extras.Json(merged_md) if merged_md else None,
                                match_id,
                            ),
                        )
                        persisted_rows.append(
                            {
                                "target_name": r["target_name"],
                                "obj_id": obj_id,
                                "is_host": effective_is_host,
                                "match_data": merged_md,
                            }
                        )
                        continue

                    cur.execute(
                        "INSERT INTO transient.cross_matches "
                        "(obj_id, name, catalog, separation, redshift, is_host, "
                        "updated_date, note, run_date, status, error_message, match_data) "
                        "VALUES (%s,%s,%s,%s,%s,%s,COALESCE(%s,now()),%s,COALESCE(%s,now()),%s,%s,%s)",
                        (
                            obj_id,
                            r["target_name"],
                            catalog_name,
                            sep,
                            z,
                            is_host,
                            r.get("updated_date"),
                            note,
                            r.get("run_date"),
                            r.get("status", "Success"),
                            r.get("error_message"),
                            extras.Json(md) if md else None,
                        ),
                    )
                    persisted_rows.append(
                        {
                            "target_name": r["target_name"],
                            "obj_id": obj_id,
                            "is_host": is_host,
                            "match_data": md,
                        }
                    )

                # ── commit cross_matches (must not be blocked by status update) ──
                conn.commit()

                # ── object status is human-owned (since 2026-09-14) ─────────────
                # DETECT never sets Follow-up / Inbox / Finish. The only object field
                # it touches is `redshift`, and only to fill an empty one from the host.
                host_obj_z: dict[int, float | None] = {}
                for r in persisted_rows:
                    if not r.get("is_host") or r.get("obj_id") is None:
                        continue
                    z = _extract_redshift(r.get("match_data") or {})
                    if z is not None and host_obj_z.get(r["obj_id"]) is None:
                        host_obj_z[r["obj_id"]] = z
                if host_obj_z:
                    try:
                        extras.execute_batch(
                            cur,
                            "UPDATE transient.objects SET redshift = %s WHERE obj_id = %s AND redshift IS NULL",
                            [(z, oid) for oid, z in host_obj_z.items()],
                            page_size=500,
                        )
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        logger.error("save_cross_match_results: redshift fill failed: %s", e)
                for r in persisted_rows:
                    if r.get("is_host"):
                        z = _extract_redshift(r.get("match_data") or {})
                        _record_db_change(
                            r["target_name"],
                            f"host found{', z=' + format(z, '.5f') if z is not None else ''}",
                            "No Change (status is set by people)",
                        )

        except Exception as e:
            logger.error("save_cross_match_results: %s", e)
            print(f"[ERROR] save_cross_match_results failed: {type(e).__name__}: {e}")
