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
    from modules.database.transient import log_download_attempt, update_download_log, sync_kinder_ids
except ImportError:
    from database import get_db_connection
    from database.transient import log_download_attempt, update_download_log, sync_kinder_ids

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


def _to_mjd(s):
    """Convert date string to MJD float."""
    if s is None:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(s).strip(), fmt)
            return (_date(dt.year, dt.month, dt.day) - _MJD_EPOCH).days + dt.hour / 24.0
        except ValueError:
            continue
    return None


def _reporters_arr(s):
    """Convert comma-separated reporters string to TEXT[]."""
    if not s:
        return None
    return [x.strip() for x in str(s).split(',') if x.strip()]


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


def addin_database(filepath, debug=False):
    """Import CSV into transient.objects + seed transient.photometry with discovery point."""

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
    phot_batch   = []   # (name, mjd, mag, filter, source_group)

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

                    new_lm_mjd = _to_mjd(r.get('lastmodified'))

                    cursor.execute(
                        "SELECT last_modified_date FROM transient.objects WHERE obj_id = %s",
                        (r.get('objid'),)
                    )
                    existing = cursor.fetchone()

                    if existing:
                        existing_lm = existing[0]
                        if new_lm_mjd and existing_lm and new_lm_mjd <= existing_lm:
                            if debug:
                                logger.debug("Skipping %s: existing data is newer", r.get('name'))
                            skipped_count += 1
                            continue

                        update_batch.append((
                            r.get('name_prefix'),
                            r.get('name'),
                            r.get('ra'),
                            r.get('declination'),    # CSV column name unchanged
                            r.get('redshift'),
                            r.get('type'),
                            r.get('reporting_group'),
                            r.get('source_group'),
                            _to_mjd(r.get('discoverydate')),
                            r.get('discoverymag'),
                            r.get('discmagfilter'),
                            _reporters_arr(r.get('reporters')),
                            _to_mjd(r.get('time_received')),
                            r.get('internal_names'),
                            r.get('discovery_ads_bibcode'),
                            r.get('class_ads_bibcodes'),
                            _to_mjd(r.get('creationdate')),
                            _to_mjd(r.get('last_photometry_date')),
                            new_lm_mjd,
                            r.get('objid'),
                        ))
                        updated_count += 1

                        if len(update_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                UPDATE transient.objects SET
                                    name_prefix = %s, name = %s, ra = %s, dec = %s,
                                    redshift = %s, type = %s, report_group = %s,
                                    source_group = %s, discovery_date = %s,
                                    discovery_mag = %s, discovery_filter = %s,
                                    reporters = %s, received_date = %s,
                                    internal_name = %s, discovery_ADS = %s,
                                    class_ADS = %s, creation_date = %s,
                                    last_phot_date = %s, last_modified_date = %s,
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
                            r.get('reporting_group'),
                            r.get('source_group'),
                            _to_mjd(r.get('discoverydate')),
                            r.get('discoverymag'),
                            r.get('discmagfilter'),
                            _reporters_arr(r.get('reporters')),
                            _to_mjd(r.get('time_received')),
                            r.get('internal_names'),
                            r.get('discovery_ads_bibcode'),
                            r.get('class_ads_bibcodes'),
                            _to_mjd(r.get('creationdate')),
                            _to_mjd(r.get('last_photometry_date')),
                            new_lm_mjd,
                        ))
                        imported_count += 1

                        if len(insert_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                INSERT INTO transient.objects (
                                    obj_id, name_prefix, name, ra, dec, redshift,
                                    type, report_group, source_group,
                                    discovery_date, discovery_mag, discovery_filter,
                                    reporters, received_date, internal_name,
                                    discovery_ADS, class_ADS, creation_date,
                                    last_phot_date, last_modified_date, status
                                ) VALUES (
                                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                    %s,%s,%s,%s,%s,%s,%s,%s,'Inbox'
                                ) ON CONFLICT DO NOTHING
                            ''', insert_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug("Committed %d inserts", len(insert_batch))
                            insert_batch = []

                    # Collect discovery photometry point
                    phot_mjd = _to_mjd(r.get('discoverydate'))
                    phot_mag = r.get('discoverymag')
                    if r.get('name') and phot_mjd is not None and phot_mag is not None:
                        try:
                            phot_batch.append((
                                r.get('name'),
                                phot_mjd,
                                float(phot_mag),
                                r.get('discmagfilter'),
                                r.get('source_group'),
                            ))
                        except (ValueError, TypeError):
                            pass

            # ---- Flush remaining objects ----
            if update_batch:
                extras.execute_batch(cursor, '''
                    UPDATE transient.objects SET
                        name_prefix = %s, name = %s, ra = %s, dec = %s,
                        redshift = %s, type = %s, report_group = %s,
                        source_group = %s, discovery_date = %s,
                        discovery_mag = %s, discovery_filter = %s,
                        reporters = %s, received_date = %s,
                        internal_name = %s, discovery_ADS = %s,
                        class_ADS = %s, creation_date = %s,
                        last_phot_date = %s, last_modified_date = %s,
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
                        last_phot_date, last_modified_date, status
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,'Inbox'
                    ) ON CONFLICT DO NOTHING
                ''', insert_batch, page_size=BATCH_SIZE)

            conn.commit()

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
                        phot_rows.append((oid, name, mjd, mag, None, filt, src or 'TNS'))

                if phot_rows:
                    extras.execute_batch(cursor, '''
                        INSERT INTO transient.photometry
                            (obj_id, name, "MJD", mag, mag_err, filter, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING
                    ''', phot_rows, page_size=BATCH_SIZE)
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
        return True

    except Exception as e:
        logger.exception("Error importing CSV: %s", e)
        update_download_log(log_id, 'failed',
                            records_imported=imported_count,
                            records_updated=updated_count,
                            error_message=str(e))
        return False


def auto_snoozed(time_now_utc, debug=False):
    """Auto-snooze objects with no photometry for 15+ days."""
    snoozed_count         = 0
    finished_follow_count = 0

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cutoff_mjd = (_date.fromisoformat(time_now_utc.strftime('%Y-%m-%d')) - _MJD_EPOCH).days - 15

            if debug:
                logger.debug("Auto-snooze cutoff MJD: %d", cutoff_mjd)

            cursor.execute('''
                SELECT obj_id, name, last_phot_date, status
                FROM transient.objects
                WHERE status NOT IN ('Snoozed', 'Finish')
                AND (
                    (last_phot_date IS NOT NULL AND last_phot_date < %s)
                    OR (last_phot_date IS NULL AND last_modified_date < %s)
                )
            ''', (cutoff_mjd, cutoff_mjd))

            for obj_id, name, last_phot, status in cursor.fetchall():
                if status == 'Follow-up':
                    cursor.execute(
                        "UPDATE transient.objects SET status = 'Finish' WHERE obj_id = %s",
                        (obj_id,)
                    )
                    finished_follow_count += 1
                    if debug:
                        logger.debug("Finished follow: %s (last_phot MJD: %s)", name, last_phot)
                else:
                    cursor.execute(
                        "UPDATE transient.objects SET status = 'Snoozed' WHERE obj_id = %s",
                        (obj_id,)
                    )
                    if debug:
                        logger.debug("Snoozed: %s (last_phot MJD: %s)", name, last_phot)
                snoozed_count += 1

            conn.commit()
            cursor.close()

        logger.info("Auto-snooze: %d snoozed (%d finished follow)",
                    snoozed_count, finished_follow_count)
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
                    addin_database(work_csv, debug=True)
                    auto_snoozed(now, debug=True)
                if now.hour == 0:
                    auto_snoozed(now, debug=True)
                time.sleep(60)

            elif now.hour == 1 and now.minute == 0:
                logger.info("Daily task at %s", now)
                yesterday = now - timedelta(days=1)
                if download_TNS_api(yesterday.year, yesterday.month, yesterday.day, debug=True):
                    addin_database(work_csv, debug=True)
                    auto_snoozed(now, debug=True)
                time.sleep(60)

            else:
                time.sleep(10)

        except Exception as e:
            logger.exception("Error in main loop: %s", e)
            time.sleep(10)


def start_auto_tns_downloader(log_dir=None):
    """Start auto TNS downloader as a daemon thread. Safe to call multiple times."""
    global _auto_tns_thread
    with _auto_tns_thread_lock:
        if _auto_tns_thread is not None and _auto_tns_thread.is_alive():
            logger.info("Auto TNS downloader already running.")
            return
        if log_dir and not logger.handlers:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, 'auto_tns_download.log'))
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(fh)
            logger.setLevel(logging.INFO)
        _auto_tns_thread = threading.Thread(target=main, daemon=True, name="auto_tns_download")
        _auto_tns_thread.start()
        logger.info("Auto TNS downloader daemon thread started.")


if __name__ == "__main__":
    """Quick one-shot test: download yesterday → import → auto-snooze."""
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    logger.info("========= TEST START =========")
    now       = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    work_csv  = SAVE_DIR / "tns_public_objects_WORK.csv"

    logger.info("Step 1: Download yesterday (%s-%02d-%02d)",
                yesterday.year, yesterday.month, yesterday.day)
    ok = download_TNS_api(yesterday.year, yesterday.month, yesterday.day, debug=True)

    if ok:
        logger.info("Step 2: Import into DB")
        addin_database(work_csv, debug=True)
        logger.info("Step 3: Auto-snooze")
        auto_snoozed(now, debug=True)
    else:
        logger.warning("Download failed, skipping import.")

    logger.info("========= TEST DONE =========")
