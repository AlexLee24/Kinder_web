import csv
import logging
import os
import requests
import shutil
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta, date as _date
from pathlib import Path

try:
    import fcntl
except ImportError:  # non-POSIX: imports are then only serialised per process
    fcntl = None

from dotenv import load_dotenv
from psycopg2 import extras

try:
    from app.db import get_db_connection
    from app.db.transient import (log_download_attempt, update_download_log, sync_kinder_ids,
                                            log_tns_update_batch, _tns_name_to_kinder_id)
except ImportError:
    from app.db import get_db_connection
    from database.transient import (log_download_attempt, update_download_log, sync_kinder_ids,
                                    log_tns_update_batch, _tns_name_to_kinder_id)

# ---- Paths ----
from app.paths import ENV_FILE, TNS_WORK_DIR

SAVE_DIR = TNS_WORK_DIR   # app/data/tns_api_download_work
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ---- Env / BOT settings ----
load_dotenv(ENV_FILE)

bot_id   = os.getenv("TNS_BOT_ID")
bot_name = os.getenv("TNS_BOT_NAME")
api_key  = os.getenv("TNS_API_KEY")

# ---- Logger ----
logger = logging.getLogger("auto_tns_download")

# ---- Thread state ----
_auto_tns_thread: threading.Thread | None = None
_auto_tns_thread_lock = threading.Lock()

# ---- Helpers ----
_MJD_EPOCH = _date(1858, 11, 17)


def _to_mjd(s, _field_hint=''):
    """Convert date string to MJD float."""
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    for fmt in (
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d',
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d',
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return ((_date(dt.year, dt.month, dt.day) - _MJD_EPOCH).days + dt.hour / 24.0
                    + dt.minute / 1440.0 + (dt.second + dt.microsecond / 1e6) / 86400.0)
        except ValueError:
            continue
    logger.warning("_to_mjd: unrecognised date format%s: %r",
                   f' ({_field_hint})' if _field_hint else '', raw)
    return None


def _reporters_arr(s):
    """Convert comma-separated reporters string to TEXT[]."""
    if not s:
        return None
    return [x.strip() for x in str(s).split(',') if x.strip()]


def _norm_text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _norm_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---- Download helpers ----

# The fixed CSV name older callers (admin / web_api blueprints) still read after a
# download. New code passes its own ``dest`` (see new_work_csv_path) so concurrent runs
# never share a file.
WORK_CSV = SAVE_DIR / "tns_public_objects_WORK.csv"
_IMPORT_LOCK_FILE = SAVE_DIR / ".tns_import.lock"


def new_work_csv_path(tag=""):
    """A unique, empty CSV path in SAVE_DIR for one download+import run.

    The caller owns the file and should delete it when done."""
    fd, path = tempfile.mkstemp(prefix=f"tns_public_objects_{tag}_" if tag else "tns_public_objects_",
                                suffix=".csv", dir=SAVE_DIR)
    os.close(fd)
    return Path(path)


@contextmanager
def tns_import_lock():
    """Cross-process lock (flock) serialising TNS CSV imports into transient.objects.

    Shared by auto_tns_download, manual_tns_download and the admin/web triggers, so the
    hourly daemon and a manual import never write the same rows at the same time."""
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_IMPORT_LOCK_FILE, "a+") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _download_and_extract(url, renamed_csv, debug=False):
    """POST download → unzip → write the CSV to *renamed_csv* (atomically).

    Returns the CSV path (truthy) on success, False otherwise. The zip and the extracted
    CSV go through unique temp files, so concurrent downloads never clobber each other."""
    headers = {'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'}
    data    = {'api_key': api_key}
    renamed_csv = Path(renamed_csv)

    if debug:
        logger.debug("URL: %s", url)

    retry_delays  = [10, 30, 60]
    max_attempts  = len(retry_delays) + 1

    for attempt in range(max_attempts):
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            logger.info("Waiting %ds before retry %d/%d…", delay, attempt, len(retry_delays))
            time.sleep(delay)

        try:
            response = requests.post(url, headers=headers, data=data, timeout=60)
        except requests.RequestException as exc:
            logger.warning("Request error for %s: %s", url, exc)
            continue

        if response.status_code == 200:
            zfd, tmp_zip = tempfile.mkstemp(prefix=".tns_dl_", suffix=".zip", dir=SAVE_DIR)
            cfd, tmp_csv = tempfile.mkstemp(prefix=".tns_dl_", suffix=".csv", dir=SAVE_DIR)
            os.close(cfd)
            try:
                with os.fdopen(zfd, 'wb') as f:
                    f.write(response.content)
                with zipfile.ZipFile(tmp_zip, 'r') as zf:
                    names = zf.namelist()
                    members = [n for n in names if n.lower().endswith('.csv')] or names
                    if not members:
                        logger.error("Empty zip from %s", url)
                        return False
                    with zf.open(members[0]) as src, open(tmp_csv, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                os.replace(tmp_csv, renamed_csv)
            except (OSError, zipfile.BadZipFile) as exc:
                logger.error("Could not unpack %s: %s", url, exc)
                return False
            finally:
                for tmp in (tmp_zip, tmp_csv):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
            if debug:
                logger.debug("Saved to %s", renamed_csv)
            return renamed_csv

        elif response.status_code == 404:
            logger.warning("404 — file not found: %s", url)
            return False
        else:
            logger.warning("HTTP %s for %s", response.status_code, url)

    logger.error("Failed after %d retries: %s", len(retry_delays), url)
    return False


def download_TNS_api_hr(hr, debug=False, dest=None):
    """Download the hourly file; returns the CSV path (default: WORK_CSV) or False."""
    url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{hr}.csv.zip"
    return _download_and_extract(url, dest or WORK_CSV, debug=debug)


def download_TNS_api(year, month, day, debug=False, dest=None):
    """Download the daily file; returns the CSV path (default: WORK_CSV) or False."""
    tag = f"{year}{month:02d}{day:02d}"
    url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{tag}.csv.zip"
    return _download_and_extract(url, dest or WORK_CSV, debug=debug)


def download_TNS_api_with_fallback(year, month, day, debug=False, dest=None):
    """Try date-based file only; log reason if unavailable (no hourly fallback)."""
    path = download_TNS_api(year, month, day, debug=debug, dest=dest)
    if path:
        return path

    logger.warning(
        "Date-based TNS file %04d-%02d-%02d not available; "
        "TNS has not yet published this daily file (it may be too recent or delayed).",
        year, month, day,
    )
    return False


_UPDATE_SQL = '''
    UPDATE transient.objects SET
        name_prefix = COALESCE(%s, name_prefix),
        name = COALESCE(%s, name),
        ra = COALESCE(%s, ra),
        dec = COALESCE(%s, dec),
        redshift = COALESCE(%s, redshift),
        type = COALESCE(%s, type),
        report_group = COALESCE(%s, report_group),
        source_group = COALESCE(%s, source_group),
        discovery_date = COALESCE(%s, discovery_date),
        discovery_mag = COALESCE(%s, discovery_mag),
        discovery_filter = COALESCE(%s, discovery_filter),
        reporters = COALESCE(%s, reporters),
        received_date = COALESCE(%s, received_date),
        internal_name = COALESCE(%s, internal_name),
        discovery_ADS = COALESCE(%s, discovery_ADS),
        class_ADS = COALESCE(%s, class_ADS),
        creation_date = COALESCE(%s, creation_date),
        last_phot_date = COALESCE(%s, last_phot_date),
        status = CASE WHEN status = 'Snoozed' AND %s > COALESCE(last_modified_date, 0) THEN 'Inbox' ELSE status END,
        last_modified_date = GREATEST(COALESCE(%s, 0), COALESCE(last_modified_date, 0))
    WHERE obj_id = %s
'''

_INSERT_SQL = '''
    INSERT INTO transient.objects (
        obj_id, kinder_id, name_prefix, name, ra, dec, redshift,
        type, report_group, source_group,
        discovery_date, discovery_mag, discovery_filter,
        reporters, received_date, internal_name,
        discovery_ADS, class_ADS, creation_date,
        last_phot_date, last_modified_date, status, tag
    ) VALUES (
        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s,'Inbox','{}'::text[]
    ) ON CONFLICT DO NOTHING
'''

# Names touched by the most recent addin_database() call, for the DETECT run that follows it.
_last_import = {'new': [], 'updated': [], 'woke': []}


def last_import_names(new_only=False) -> list:
    return list(_last_import['new'] if new_only else (_last_import['new'] + _last_import['updated']))


def addin_database(filepath, debug=False, fetch_phot_for_new=False):
    """Import CSV into transient.objects + seed transient.photometry with discovery point.

    Imports are serialised across processes with tns_import_lock().

    When ``fetch_phot_for_new`` is True, each newly inserted object triggers an
    immediate light-curve fetch (same workflow as the object-detail "Fetch"
    button) once the import has been committed (outside the import lock).
    """
    with tns_import_lock():
        ok = _addin_database_locked(filepath, debug=debug)
        new_names = list(_last_import['new']) if ok else []

    # Immediately fetch a light curve for each newly added object,
    # mirroring the object-detail page "Fetch" button.
    if ok and fetch_phot_for_new and new_names:
        _fetch_phot_for_new_objects(new_names, debug=debug)
    return ok


def _addin_database_locked(filepath, debug=False):
    """addin_database() body; the caller holds tns_import_lock()."""

    filename = os.path.basename(filepath) if os.path.exists(filepath) else "file_not_found"
    log_id   = log_download_attempt(filename=filename)

    if not os.path.exists(filepath):
        update_download_log(log_id, 'failed', error_message=f"File not found: {filepath}")
        return False

    imported_count = 0
    updated_count  = 0
    skipped_count  = 0
    BATCH_SIZE     = 1000

    insert_batch = []
    update_batch = []
    update_audit_batch = []
    phot_batch   = []   # (name, mjd, mag, filter, source_group)
    new_object_names = []   # names of objects newly inserted this run
    updated_names = []      # names of existing objects touched by this file
    woke_names = []         # Snoozed objects a newer TNS lastmodified put back in Inbox

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            with open(filepath, 'r', encoding='utf-8') as f:
                next(f)   # skip the date-range header line
                for row in csv.DictReader(f):
                    # Normalise keys / empty strings
                    r = {}
                    for k, v in row.items():
                        k = k.strip().strip('"')
                        r[k] = None if (v == '' or v == 'NULL' or v is None) \
                               else (v.strip().strip('"') if isinstance(v, str) else v)

                    if not r.get('objid') or not r.get('name'):
                        continue

                    obj_name = r.get('name', '')
                    new_lm_mjd = _to_mjd(r.get('lastmodified'), 'lastmodified')

                    csv_reporting_group = r.get('reporting_group')
                    csv_source_group = r.get('source_group')
                    csv_reporters = _reporters_arr(r.get('reporters'))
                    csv_internal_names = r.get('internal_names')
                    csv_discovery_ads = r.get('discovery_ads_bibcode') or r.get('Discovery_ADS_bibcode')
                    csv_class_ads = r.get('class_ads_bibcodes') or r.get('Class_ADS_bibcodes')

                    csv_time_received = _to_mjd(r.get('time_received'), f'{obj_name}/time_received')
                    csv_discoverydate = _to_mjd(r.get('discoverydate'), f'{obj_name}/discoverydate')
                    csv_creationdate  = _to_mjd(r.get('creationdate'),  f'{obj_name}/creationdate')
                    csv_last_phot_date = _to_mjd(r.get('last_photometry_date'), f'{obj_name}/last_photometry_date')

                    # 診斷：reporters 有值但 time_received 為 None（可能是欄位錯位）
                    # 或兩者同時為 None（TNS 本身沒有這筆資料）
                    _raw_reporters     = r.get('reporters')
                    _raw_time_received = r.get('time_received')
                    if debug and csv_time_received is None and _raw_time_received is None:
                        logger.debug(
                            "time_received 欄位在 CSV 中為空 for %s | reporters=%r | "
                            "欄位清單(前30)=%s",
                            obj_name, _raw_reporters, list(r.keys())[:30]
                        )

                    # Query by name only
                    cursor.execute(
                        "SELECT obj_id, last_modified_date, type, redshift, report_group, source_group, internal_name, "
                        "discovery_mag, last_phot_date, status "
                        "FROM transient.objects WHERE name = %s",
                        (r.get('name'),)
                    )
                    existing = cursor.fetchone()
                    existing_obj_id = None
                    if existing:
                        existing_obj_id = existing[0]

                    if existing:
                        (
                            _,  # obj_id already in existing_obj_id
                            existing_lm,
                            old_type,
                            old_redshift,
                            old_report_group,
                            old_source_group,
                            old_internal_name,
                            old_discovery_mag,
                            old_last_phot_date,
                            existing_status,
                        ) = existing

                        changed_fields = []
                        if _norm_text(old_type) != _norm_text(r.get('type')) and _norm_text(r.get('type')) is not None:
                            changed_fields.append('type')
                        if _norm_float(old_redshift) != _norm_float(r.get('redshift')) and _norm_float(r.get('redshift')) is not None:
                            changed_fields.append('redshift')
                        if _norm_text(old_report_group) != _norm_text(csv_reporting_group) and _norm_text(csv_reporting_group) is not None:
                            changed_fields.append('reporting_group')
                        if _norm_text(old_source_group) != _norm_text(csv_source_group) and _norm_text(csv_source_group) is not None:
                            changed_fields.append('source_group')
                        if _norm_text(old_internal_name) != _norm_text(csv_internal_names) and _norm_text(csv_internal_names) is not None:
                            changed_fields.append('internal_names')
                        if _norm_float(old_discovery_mag) != _norm_float(r.get('discoverymag')) and _norm_float(r.get('discoverymag')) is not None:
                            changed_fields.append('discovery_mag')
                        if _norm_float(old_last_phot_date) != _norm_float(csv_last_phot_date) and csv_last_phot_date is not None:
                            changed_fields.append('last_photometry_date')

                        update_batch.append((
                            r.get('name_prefix'),
                            r.get('name'),
                            r.get('ra'),
                            r.get('declination'),    # CSV column name unchanged
                            r.get('redshift'),
                            r.get('type'),
                            csv_reporting_group,
                            csv_source_group,
                            csv_discoverydate,
                            r.get('discoverymag'),
                            r.get('filter') or r.get('discmagfilter'),   # the filter *name*, as DETECT stores it
                            csv_reporters,
                            csv_time_received,
                            csv_internal_names,
                            csv_discovery_ads,
                            csv_class_ads,
                            csv_creationdate,
                            csv_last_phot_date,
                            new_lm_mjd,
                            new_lm_mjd,
                            existing_obj_id,
                        ))
                        updated_names.append(obj_name)
                        if existing_status == 'Snoozed' and new_lm_mjd is not None and new_lm_mjd > (existing_lm or 0):
                            changed_fields = ['woke: Snoozed -> Inbox'] + changed_fields
                            woke_names.append(obj_name)
                        if changed_fields:
                            update_audit_batch.append((
                                int(r.get('objid')),
                                r.get('name') or '',
                                changed_fields,
                                'auto_tns_download',
                            ))
                        updated_count += 1

                        if len(update_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, _UPDATE_SQL, update_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug("Committed %d updates", len(update_batch))
                            update_batch = []

                    else:
                        kinder_id = _tns_name_to_kinder_id(obj_name)
                        insert_batch.append((
                            kinder_id or r.get('objid'),
                            kinder_id,
                            r.get('name_prefix'),
                            r.get('name'),
                            r.get('ra'),
                            r.get('declination'),
                            r.get('redshift'),
                            r.get('type'),
                            csv_reporting_group,
                            csv_source_group,
                            csv_discoverydate,
                            r.get('discoverymag'),
                            r.get('filter') or r.get('discmagfilter'),
                            csv_reporters,
                            csv_time_received,
                            csv_internal_names,
                            csv_discovery_ads,
                            csv_class_ads,
                            csv_creationdate,
                            csv_last_phot_date,
                            new_lm_mjd,
                        ))
                        imported_count += 1
                        if obj_name:
                            new_object_names.append(obj_name)
                        # Log new object to audit for "Recent TNS Updates" widget
                        update_audit_batch.append((
                            int(r.get('objid')),
                            r.get('name') or '',
                            ['new_add'],
                            'auto_tns_download',
                        ))

                        if len(insert_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, _INSERT_SQL, insert_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug("Committed %d inserts", len(insert_batch))
                            insert_batch = []

                    # Collect discovery photometry point
                    phot_mjd = csv_discoverydate
                    phot_mag = r.get('discoverymag')
                    if r.get('name') and phot_mjd is not None and phot_mag is not None:
                        try:
                            phot_batch.append((
                                r.get('name'),
                                phot_mjd,
                                float(phot_mag),
                                r.get('filter'),
                                r.get('source_group'),
                            ))
                        except (ValueError, TypeError):
                            pass

            # ---- Flush remaining objects ----
            if update_batch:
                extras.execute_batch(cursor, _UPDATE_SQL, update_batch, page_size=BATCH_SIZE)

            if insert_batch:
                extras.execute_batch(cursor, _INSERT_SQL, insert_batch, page_size=BATCH_SIZE)

            conn.commit()

            if update_audit_batch:
                log_tns_update_batch(update_audit_batch)

            # ---- Bulk insert discovery photometry ----
            # Resolve name → obj_id in one query then bulk-insert
            if phot_batch:
                names = list({p[0] for p in phot_batch})
                cursor.execute(
                    "SELECT name, obj_id FROM transient.objects WHERE name = ANY(%s)",
                    (names,)
                )
                name_map = {row[0]: row[1] for row in cursor.fetchall()}

                phot_rows = []
                for (name, mjd, mag, filt, src) in phot_batch:
                    oid = name_map.get(name)
                    if oid:
                        phot_rows.append((oid, name, mjd, mag, 0.01, filt, f"{src} (TNS)" if src else "(TNS)"))

                if phot_rows:
                    extras.execute_batch(cursor, '''
                        INSERT INTO transient.photometry
                            (obj_id, name, "MJD", mag, mag_err, filter, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING
                    ''', phot_rows, page_size=BATCH_SIZE)

                    # Update last_phot_date and un-snooze for each affected object
                    max_mjd_by_oid: dict = {}
                    for oid, _, mjd, *__ in phot_rows:
                        if oid not in max_mjd_by_oid or mjd > max_mjd_by_oid[oid]:
                            max_mjd_by_oid[oid] = mjd
                    for oid, max_mjd in max_mjd_by_oid.items():
                        # New photometry re-activates dormant objects:
                        # Snoozed → Inbox (needs re-evaluation), Finish → Follow-up (new data warrants follow-up)
                        cursor.execute(
                            "UPDATE transient.objects "
                            "SET last_phot_date = %s, "
                            "    status = CASE "
                            "        WHEN status = 'Snoozed' THEN 'Inbox' "
                            "        WHEN status = 'Finish' THEN 'Follow-up' "
                            "        ELSE status "
                            "    END "
                            "WHERE obj_id = %s AND (last_phot_date IS NULL OR last_phot_date < %s)",
                            (max_mjd, oid, max_mjd)
                        )
                    conn.commit()
                    if debug:
                        logger.debug("Inserted %d photometry points", len(phot_rows))

            cursor.close()

        logger.info("Import done: %d new, %d updated, %d skipped, %d woke from Snoozed",
                    imported_count, updated_count, skipped_count, len(woke_names))
        _last_import['new'], _last_import['updated'], _last_import['woke'] = new_object_names, updated_names, woke_names
        update_download_log(log_id, 'completed',
                            records_imported=imported_count,
                            records_updated=updated_count)
        n = sync_kinder_ids()
        if n:
            logger.info("sync_kinder_ids: assigned %d new kinder_ids", n)

        return True

    except Exception as e:
        logger.exception("Error importing CSV: %s", e)
        update_download_log(log_id, 'failed',
                            records_imported=imported_count,
                            records_updated=updated_count,
                            error_message=str(e))
        return False


def _fetch_phot_for_new_objects(names, debug=False):
    """Run the photometry-fetch workflow for each newly added object name.

    Each object is processed independently; a failure on one does not abort the
    rest.  Uses the same workflow as the object-detail "Fetch" button.
    """
    try:
        from app.services.photometry.download_phot import process_single_object_workflow
    except ImportError:
        try:
            from download_phot import process_single_object_workflow
        except ImportError as exc:
            # download_phot is a private module and may be absent from this deployment.
            logger.warning("Fetch LC skipped for %d new object(s): download_phot unavailable (%s)",
                           len(names), exc)
            return

    total = len(names)
    success = 0
    failed = 0
    logger.info("Fetch LC for %d new object(s) after import", total)
    for name in names:
        try:
            process_single_object_workflow(name)
            success += 1
        except Exception as e:
            failed += 1
            logger.error("Fetch LC failed for new object %s: %s", name, e)
    logger.info("Fetch LC for new objects done: %d ok, %d failed", success, failed)


def auto_snoozed(time_now_utc, debug=False):
    """Auto-snooze objects with no photometry for 15+ days."""
    snoozed_count = 0

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cutoff_mjd = (_date.fromisoformat(time_now_utc.strftime('%Y-%m-%d')) - _MJD_EPOCH).days - 15

            if debug:
                logger.debug("Auto-snooze cutoff MJD: %d", cutoff_mjd)

            # Only Inbox objects are candidates for snoozing — never touch Follow-up or Finish
            cursor.execute('''
                SELECT obj_id, name, last_phot_date
                FROM transient.objects
                WHERE status = 'Inbox'
                AND (
                    (last_phot_date IS NOT NULL AND last_phot_date < %s)
                    OR (last_phot_date IS NULL AND last_modified_date < %s)
                )
            ''', (cutoff_mjd, cutoff_mjd))

            for obj_id, name, last_phot in cursor.fetchall():
                cursor.execute(
                    "UPDATE transient.objects SET status = 'Snoozed' WHERE obj_id = %s",
                    (obj_id,)
                )
                snoozed_count += 1
                if debug:
                    logger.debug("Snoozed: %s (last_phot MJD: %s)", name, last_phot)

            conn.commit()
            cursor.close()

        logger.info("Auto-snooze: %d snoozed", snoozed_count)
        return True

    except Exception as e:
        logger.exception("Error in auto_snoozed: %s", e)
        return False


def _run_detect_after_import(new_only: bool, label: str) -> None:
    """The embedded DETECT pipeline on what the import just wrote (see modules/detect_pipeline)."""
    try:
        from app.services.detect import detect_pipeline
    except ImportError:
        import detect_pipeline
    names = last_import_names(new_only=new_only)
    if not detect_pipeline.ENABLED or not names:
        return
    try:
        logger.info("DETECT after %s import: %d objects", label, len(names))
        detect_pipeline.run_for_names(names, label=label)
        try:
            from app.blueprints.detect.cache import _soft_invalidate_page_cache
            _soft_invalidate_page_cache()
        except Exception:
            pass
    except Exception as e:
        logger.exception("DETECT after %s import failed: %s", label, e)


# Schedule (UTC): hourly import at :15 and :45, daily import at 01:00, 04:00 and 12:00.
_HOURLY_MINUTES = (15, 45)
_DAILY_HOURS = (1, 4, 12)
# On (re)start, a slot this recent is still run; older ones count as already done so a
# restart does not immediately re-run the previous import.
_STARTUP_GRACE = timedelta(minutes=10)


def _latest_hourly_slot(now):
    """Most recent hourly slot (UTC datetime at :15 or :45) that is <= now."""
    base = now.replace(second=0, microsecond=0)
    for m in sorted(_HOURLY_MINUTES, reverse=True):
        if now.minute >= m:
            return base.replace(minute=m)
    return (base - timedelta(hours=1)).replace(minute=max(_HOURLY_MINUTES))


def _latest_daily_slot(now):
    """Most recent daily slot (UTC datetime at hh:00, hh in _DAILY_HOURS) that is <= now."""
    base = now.replace(minute=0, second=0, microsecond=0)
    for h in sorted(_DAILY_HOURS, reverse=True):
        if now.hour >= h:
            return base.replace(hour=h)
    return (base - timedelta(days=1)).replace(hour=max(_DAILY_HOURS))


def _run_hourly(slot, now):
    logger.info("Hourly task for slot %s (now %s)", slot, now)
    work_csv = new_work_csv_path(f"hr{slot.hour:02d}")
    try:
        if download_TNS_api_hr(f"{slot.hour:02d}", debug=True, dest=work_csv):
            # Newly added hourly objects get an immediate light-curve fetch.
            if addin_database(work_csv, debug=True, fetch_phot_for_new=True):
                # cross-match + host rule + screening for everything this hour touched
                _run_detect_after_import(new_only=False, label="TNS-hourly")
            auto_snoozed(now, debug=True)
    finally:
        work_csv.unlink(missing_ok=True)
    if slot.hour == 0:
        auto_snoozed(now, debug=True)


def _run_daily(slot, now):
    # day_offset=0: 今天（補充每小時 CSV 可能缺少的欄位）
    # day_offset=1: 昨天；day_offset=2: 前天
    logger.info("Daily task for slot %s (now %s): processing today, yesterday, and day-before-yesterday",
                slot, now)
    for day_offset in (0, 1, 2):
        target_day = slot - timedelta(days=day_offset)
        logger.info("Daily task target day: %s", target_day.date())
        work_csv = new_work_csv_path(f"{target_day:%Y%m%d}")
        try:
            if download_TNS_api_with_fallback(target_day.year, target_day.month, target_day.day,
                                              debug=True, dest=work_csv):
                if addin_database(work_csv, debug=True):
                    # the daily file mostly repeats the hourly ones: only objects
                    # the hourly imports missed need a DETECT run here
                    _run_detect_after_import(new_only=True, label="TNS-daily")
                auto_snoozed(now, debug=True)
            else:
                logger.warning("Daily task download failed for %s", target_day.date())
        finally:
            work_csv.unlink(missing_ok=True)


def main():
    """Daemon loop. Each job remembers the last slot it ran for and runs once as soon as
    a newer slot is due, so a slot is not lost when the loop was busy (a daily import
    can take longer than a minute) and a backlog is caught up only once."""
    logger.info("Bot started at %s", datetime.now(timezone.utc))

    now = datetime.now(timezone.utc)
    last_hourly = _latest_hourly_slot(now)
    last_daily = _latest_daily_slot(now)
    if now - last_hourly <= _STARTUP_GRACE:
        last_hourly = None
    if now - last_daily <= _STARTUP_GRACE:
        last_daily = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            daily_slot = _latest_daily_slot(now)
            if last_daily is None or daily_slot > last_daily:
                last_daily = daily_slot   # mark first: a failing run is not retried in a tight loop
                _run_daily(daily_slot, now)
                continue   # re-read the clock; the hourly slot may have come due meanwhile

            hourly_slot = _latest_hourly_slot(now)
            if last_hourly is None or hourly_slot > last_hourly:
                last_hourly = hourly_slot
                _run_hourly(hourly_slot, now)
                continue

            time.sleep(10)

        except Exception as e:
            logger.exception("Error in main loop: %s", e)
            time.sleep(10)


def diagnose_csv_columns(filepath=None, names=None, max_rows=20):
    """診斷工具：印出 CSV 中 reporters / time_received 欄位的原始值。

    用法（在 Python shell 裡執行）：
        from app.services.tns.auto_tns_download import diagnose_csv_columns
        diagnose_csv_columns(names=['2026ocm', '2026abc'])
    """
    if filepath is None:
        filepath = str(SAVE_DIR / "tns_public_objects_WORK.csv")

    print(f"[診斷] 讀取 {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline().rstrip('\n')
            print(f"[第1行（跳過）] {first_line[:120]}")
            reader = csv.DictReader(f)
            print(f"[欄位列表] {reader.fieldnames}")

            found = 0
            for row in reader:
                r = {}
                for k, v in row.items():
                    k2 = k.strip().strip('"') if k else k
                    r[k2] = None if (v == '' or v == 'NULL' or v is None) \
                             else (v.strip().strip('"') if isinstance(v, str) else v)

                obj_name = r.get('name', '')
                if names and obj_name not in names:
                    continue

                print(
                    f"  [{obj_name}] "
                    f"reporters={r.get('reporters')!r:40s} "
                    f"time_received={r.get('time_received')!r:25s} "
                    f"discmagfilter={r.get('discmagfilter')!r}"
                )
                found += 1
                if found >= max_rows:
                    break

        if found == 0:
            print("[診斷] 在 CSV 中找不到指定的目標名稱，請確認 CSV 是否是最新的。")
    except FileNotFoundError:
        print(f"[診斷] 找不到檔案 {filepath}，請先執行下載。")
    except Exception as e:
        print(f"[診斷] 錯誤：{e}")


def start_auto_tns_downloader(log_dir=None):
    """Start auto TNS downloader as a daemon thread. Safe to call multiple times."""
    global _auto_tns_thread
    with _auto_tns_thread_lock:
        if _auto_tns_thread is not None and _auto_tns_thread.is_alive():
            logger.info("Auto TNS downloader already running.")
            return
        # Rely on the root logger (setup_logging daily handler) for output.
        # Only set level if not already configured so propagation works correctly.
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)
        _auto_tns_thread = threading.Thread(target=main, daemon=True, name="auto_tns_download")
        _auto_tns_thread.start()
        logger.info("Auto TNS downloader daemon thread started.")


if __name__ == "__main__":
    """Quick one-shot test: download yesterday → import → auto-snooze."""
    # logging.basicConfig(level=logging.DEBUG,
    #                     format='%(asctime)s [%(levelname)s] %(message)s')
    # logger.info("========= TEST START =========")
    # now       = datetime.now(timezone.utc)
    # yesterday = now - timedelta(days=1)
    # work_csv  = SAVE_DIR / "tns_public_objects_WORK.csv"
    #
    # logger.info("Step 1: Download yesterday (%s-%02d-%02d)",
    #             yesterday.year, yesterday.month, yesterday.day)
    # # ok = download_TNS_api_with_fallback(yesterday.year, yesterday.month, yesterday.day, debug=True)
    # ok = download_TNS_api_with_fallback(2026, 5, 5, debug=True)
    #
    # if ok:
    #     logger.info("Step 2: Import into DB")
    #     addin_database(work_csv, debug=True)
    #     logger.info("Step 3: Auto-snooze")
    #     auto_snoozed(now, debug=True)
    # else:
    #     logger.warning("Download failed, skipping import.")
    #
    # logger.info("========= TEST DONE =========")
    # download_TNS_api_hr(17)
    download_TNS_api(2026,5,31)