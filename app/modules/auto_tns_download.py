import csv
import logging
import os
import pathlib
import requests
import threading
import time
import zipfile
from datetime import datetime, timezone, timedelta, date as _date

from dotenv import load_dotenv
from psycopg2 import extras

try:
    from modules.database import get_db_connection
    from modules.database.transient import log_download_attempt, update_download_log, sync_kinder_ids, log_tns_update_batch
except ImportError:
    from database import get_db_connection
    from database.transient import log_download_attempt, update_download_log, sync_kinder_ids, log_tns_update_batch

# ---- Paths ----
_module_dir = os.path.dirname(os.path.abspath(__file__))
_app_dir    = os.path.dirname(_module_dir)
_repo_root  = os.path.normpath(os.path.join(_module_dir, '..', '..'))

SAVE_DIR = pathlib.Path(_app_dir) / 'data' / 'tns_api_download_work'
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ---- Env / BOT settings ----
load_dotenv(os.path.join(_repo_root, 'kinder.env'))

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
            return (_date(dt.year, dt.month, dt.day) - _MJD_EPOCH).days + dt.hour / 24.0
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

def _download_and_extract(url, zip_path, renamed_csv, debug=False):
    """POST download → unzip → rename to renamed_csv. Returns True on success."""
    headers = {'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'}
    data    = {'api_key': api_key}

    if debug:
        logger.debug("URL: %s", url)

    retry_delays  = [10, 30, 60]
    max_attempts  = len(retry_delays) + 1

    for attempt in range(max_attempts):
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            logger.info("Waiting %ds before retry %d/%d…", delay, attempt, len(retry_delays))
            time.sleep(delay)

        response = requests.post(url, headers=headers, data=data, timeout=60)

        if response.status_code == 200:
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(SAVE_DIR)
            zip_path.unlink(missing_ok=True)

            # The extracted name equals the zip stem without .zip
            extracted = SAVE_DIR / zip_path.stem   # e.g. tns_public_objects_12.csv
            if extracted.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted.rename(renamed_csv)
            if debug:
                logger.debug("Saved to %s", renamed_csv)
            return True

        elif response.status_code == 404:
            logger.warning("404 — file not found: %s", url)
            return False
        else:
            logger.warning("HTTP %s for %s", response.status_code, url)

    logger.error("Failed after %d retries: %s", len(retry_delays), url)
    return False


def download_TNS_api_hr(hr, debug=False):
    url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{hr}.csv.zip"
    return _download_and_extract(
        url,
        SAVE_DIR / f"tns_public_objects_{hr}.csv.zip",
        SAVE_DIR / "tns_public_objects_WORK.csv",
        debug=debug,
    )


def download_TNS_api(year, month, day, debug=False):
    tag = f"{year}{month:02d}{day:02d}"
    url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{tag}.csv.zip"
    return _download_and_extract(
        url,
        SAVE_DIR / f"tns_public_objects_{tag}.csv.zip",
        SAVE_DIR / "tns_public_objects_WORK.csv",
        debug=debug,
    )


def download_TNS_api_with_fallback(year, month, day, debug=False):
    """Try date-based file only; log reason if unavailable (no hourly fallback)."""
    if download_TNS_api(year, month, day, debug=debug):
        return True

    logger.warning(
        "Date-based TNS file %04d-%02d-%02d not available; "
        "TNS has not yet published this daily file (it may be too recent or delayed).",
        year, month, day,
    )
    return False


def addin_database(filepath, debug=False, fetch_phot_for_new=False):
    """Import CSV into transient.objects + seed transient.photometry with discovery point.

    When ``fetch_phot_for_new`` is True, each newly inserted object triggers an
    immediate light-curve fetch (same workflow as the object-detail "Fetch"
    button) once the import has been committed.
    """

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
                        "discovery_mag, last_phot_date "
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
                            r.get('discmagfilter'),
                            csv_reporters,
                            csv_time_received,
                            csv_internal_names,
                            csv_discovery_ads,
                            csv_class_ads,
                            csv_creationdate,
                            csv_last_phot_date,
                            new_lm_mjd,
                            existing_obj_id,
                        ))
                        if changed_fields:
                            update_audit_batch.append((
                                int(r.get('objid')),
                                r.get('name') or '',
                                changed_fields,
                                'auto_tns_download',
                            ))
                        updated_count += 1

                        if len(update_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                UPDATE transient.objects SET
                                    name_prefix = %s,
                                    name = COALESCE(%s, name),
                                    ra = COALESCE(%s, ra),
                                    dec = COALESCE(%s, dec),
                                    redshift = COALESCE(%s, redshift),
                                    type = %s,
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
                                    last_modified_date = %s,
                                    status = CASE WHEN status = 'Snoozed' THEN 'Inbox' ELSE status END
                                WHERE obj_id = %s
                            ''', update_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug("Committed %d updates", len(update_batch))
                            update_batch = []

                    else:
                        insert_batch.append((
                            r.get('objid'),
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
                            r.get('discmagfilter'),
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
                            extras.execute_batch(cursor, '''
                                INSERT INTO transient.objects (
                                    obj_id, name_prefix, name, ra, dec, redshift,
                                    type, report_group, source_group,
                                    discovery_date, discovery_mag, discovery_filter,
                                    reporters, received_date, internal_name,
                                    discovery_ADS, class_ADS, creation_date,
                                    last_phot_date, last_modified_date, status, tag
                                ) VALUES (
                                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                    %s,%s,%s,%s,%s,%s,%s,%s,'Inbox','{}'::text[]
                                ) ON CONFLICT DO NOTHING
                            ''', insert_batch, page_size=BATCH_SIZE)
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
                extras.execute_batch(cursor, '''
                    UPDATE transient.objects SET
                        name_prefix = %s,
                        name = COALESCE(%s, name),
                        ra = COALESCE(%s, ra),
                        dec = COALESCE(%s, dec),
                        redshift = COALESCE(%s, redshift),
                        type = %s,
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
                        last_modified_date = %s,
                        status = CASE WHEN status = 'Snoozed' THEN 'Inbox' ELSE status END
                    WHERE obj_id = %s
                ''', update_batch, page_size=BATCH_SIZE)

            if insert_batch:
                extras.execute_batch(cursor, '''
                    INSERT INTO transient.objects (
                        obj_id, name_prefix, name, ra, dec, redshift,
                        type, report_group, source_group,
                        discovery_date, discovery_mag, discovery_filter,
                        reporters, received_date, internal_name,
                        discovery_ADS, class_ADS, creation_date,
                        last_phot_date, last_modified_date, status, tag
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,'Inbox','{}'::text[]
                    ) ON CONFLICT DO NOTHING
                ''', insert_batch, page_size=BATCH_SIZE)

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

        logger.info("Import done: %d new, %d updated, %d skipped",
                    imported_count, updated_count, skipped_count)
        update_download_log(log_id, 'completed',
                            records_imported=imported_count,
                            records_updated=updated_count)
        n = sync_kinder_ids()
        if n:
            logger.info("sync_kinder_ids: assigned %d new kinder_ids", n)

        # Immediately fetch a light curve for each newly added object,
        # mirroring the object-detail page "Fetch" button.
        if fetch_phot_for_new and new_object_names:
            _fetch_phot_for_new_objects(new_object_names, debug=debug)

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
        from modules.download_phot import process_single_object_workflow
    except ImportError:
        from download_phot import process_single_object_workflow

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


def main():
    logger.info("Bot started at %s", datetime.now(timezone.utc))

    while True:
        try:
            now = datetime.now(timezone.utc)
            work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"

            if now.minute in (15, 45):
                logger.info("Hourly task at %s", now)
                if download_TNS_api_hr(f"{now.hour:02d}", debug=True):
                    # Newly added hourly objects get an immediate light-curve fetch.
                    addin_database(work_csv, debug=True, fetch_phot_for_new=True)
                    auto_snoozed(now, debug=True)
                if now.hour == 0:
                    auto_snoozed(now, debug=True)
                time.sleep(60)

            elif now.hour in (1, 4, 12) and now.minute == 0:
                # day_offset=0: 今天（補充每小時 CSV 可能缺少的欄位）
                # day_offset=1: 昨天；day_offset=2: 前天
                logger.info("Daily task at %s (UTC %02d:00): processing today, yesterday, and day-before-yesterday", now, now.hour)
                for day_offset in (0, 1, 2):
                    target_day = now - timedelta(days=day_offset)
                    logger.info("Daily task target day: %s", target_day.date())
                    if download_TNS_api_with_fallback(target_day.year, target_day.month, target_day.day, debug=True):
                        addin_database(work_csv, debug=True)
                        auto_snoozed(now, debug=True)
                    else:
                        logger.warning("Daily task download failed for %s", target_day.date())
                time.sleep(60)

            else:
                time.sleep(10)

        except Exception as e:
            logger.exception("Error in main loop: %s", e)
            time.sleep(10)


def diagnose_csv_columns(filepath=None, names=None, max_rows=20):
    """診斷工具：印出 CSV 中 reporters / time_received 欄位的原始值。

    用法（在 Python shell 裡執行）：
        from modules.auto_tns_download import diagnose_csv_columns
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