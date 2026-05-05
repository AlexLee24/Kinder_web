import csv
import logging
import os
import pathlib
import requests
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone, timedelta, date as _date

_MJD_EPOCH = _date(1858, 11, 17)


def _to_mjd(s):
    """Convert date string 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD' to MJD float."""
    if s is None:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
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
logger = logging.getLogger("tns_fetch")

# ---- Function to download TNS API data ----
def download_TNS_api_hr(hr, debug=False):
    tns_link = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{hr}.csv.zip"
    
    # Set headers with bot info
    headers = {
        'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'
    }
    
    # Set POST data
    data = {
        'api_key': api_key
    }
    
    if debug:
        logger.debug(f"URL: {tns_link}")
        logger.debug(f"Headers: {headers}")
    
    # Retry logic: 10s, 30s, 60s
    retry_delays = [10, 30, 60]
    attempt = 0
    max_attempts = len(retry_delays) + 1
    
    while attempt < max_attempts:
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            logger.info(f"Waiting {delay} seconds before retry {attempt}/{len(retry_delays)}...")
            time.sleep(delay)
        
        response = requests.post(tns_link, headers=headers, data=data)
        
        if response.status_code == 200:
            output_file = SAVE_DIR / f"tns_public_objects_{hr}.csv.zip"
            with open(output_file, 'wb') as f:
                f.write(response.content)
            if debug:
                logger.debug(f"Data successfully saved to: {output_file}")
            
            # Unzip the file
            with zipfile.ZipFile(output_file, 'r') as zip_ref:
                zip_ref.extractall(SAVE_DIR)
            if debug:
                logger.debug(f"File unzipped to: {SAVE_DIR}")
            
            # Rename the extracted CSV file
            extracted_csv = SAVE_DIR / f"tns_public_objects_{hr}.csv"
            #renamed_csv = SAVE_DIR / f"tns_public_objects_WORK_{hr}_WORK.csv"
            renamed_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
            if extracted_csv.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted_csv.rename(renamed_csv)
                if debug:
                    logger.debug(f"Renamed extracted file to: {renamed_csv}")
            
            # Remove the zip file
            output_file.unlink()
            if debug:
                logger.debug(f"Removed zip file: {output_file}")
            logger.info(f"Download and extraction completed for {hr}")
            return True
        elif response.status_code == 404:
            logger.error(f"File not found (404) for {hr}")
            return False
        else:
            logger.error(f"Request failed with status code: {response.status_code}")
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"Failed after {len(retry_delays)} retries. Stopping.")
                return False

def download_TNS_api(year, month, day, debug=False):
    download_url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{year}{month:02d}{day:02d}.csv.zip"
    
    # Set headers with bot info
    headers = {
        'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'
    }
    
    # Set POST data
    data = {
        'api_key': api_key
    }
    
    if debug:
        logger.debug(f"URL: {download_url}")
        logger.debug(f"Headers: {headers}")
    
    # Retry logic: 10s, 30s, 60s
    retry_delays = [10, 30, 60]
    attempt = 0
    max_attempts = len(retry_delays) + 1
    
    while attempt < max_attempts:
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            logger.info(f"Waiting {delay} seconds before retry {attempt}/{len(retry_delays)}...")
            time.sleep(delay)
        
        response = requests.post(download_url, headers=headers, data=data)
        
        if response.status_code == 200:
            output_file = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv.zip"
            with open(output_file, 'wb') as f:
                f.write(response.content)
            if debug:
                logger.debug(f"Data successfully saved to: {output_file}")
            
            # Unzip the file
            with zipfile.ZipFile(output_file, 'r') as zip_ref:
                zip_ref.extractall(SAVE_DIR)
            if debug:
                logger.debug(f"File unzipped to: {SAVE_DIR}")
            
            # Rename the extracted CSV file
            extracted_csv = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv"
            #renamed_csv = SAVE_DIR / f"tns_public_objects_WORK_{year}{month:02d}{day:02d}_WORK.csv"
            renamed_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
            if extracted_csv.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted_csv.rename(renamed_csv)
                if debug:
                    logger.debug(f"Renamed extracted file to: {renamed_csv}")
            
            # Remove the zip file
            output_file.unlink()
            if debug:
                logger.debug(f"Removed zip file: {output_file}")
            logger.info(f"Download and extraction completed for {year}-{month:02d}-{day:02d}")
            return True
        elif response.status_code == 404:
            logger.error(f"File not found (404) for {year}-{month:02d}-{day:02d}")
            return False
        else:
            logger.error(f"Request failed with status code: {response.status_code}")
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"Failed after {len(retry_delays)} retries. Stopping.")
                return False


def addin_database(filepath, debug=False):
    """Import CSV data into PostgreSQL TNS database with write optimization"""
    
    # Log download attempt at the very beginning
    utc_now = datetime.now(timezone.utc)
    hour_utc = utc_now.strftime('%Y-%m-%d_%H')
    filename = os.path.basename(filepath) if os.path.exists(filepath) else "file_not_found"
    log_id = log_download_attempt(hour_utc, filename=filename)
    
    if not os.path.exists(filepath):
        error_msg = f"File not found: {filepath}"
        logger.error(error_msg)
        update_download_log(log_id, 'failed', records_imported=0, records_updated=0, error_message=error_msg)
        return False
    
    imported_count = 0
    updated_count = 0
    skipped_count = 0
    
    # Collect data in batches for bulk insert
    insert_batch = []
    update_batch = []
    BATCH_SIZE = 1000
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            with open(filepath, 'r', encoding='utf-8') as file:
                # Skip first line (date range info)
                next(file)
                csv_reader = csv.DictReader(file)
                
                for row in csv_reader:
                    # Clean data
                    cleaned_row = {}
                    for key, value in row.items():
                        key = key.strip().strip('"')
                        if value == '' or value == 'NULL' or value is None:
                            cleaned_row[key] = None
                        else:
                            cleaned_row[key] = value.strip().strip('"') if isinstance(value, str) else value
                    
                    # Validate required fields
                    if not cleaned_row.get('objid') or not cleaned_row.get('name'):
                        continue
                    
                    # Check if object exists
                    cursor.execute('SELECT last_modified_date FROM transient.objects WHERE obj_id = %s', (cleaned_row.get('objid'),))
                    existing = cursor.fetchone()

                    if existing:
                        existing_lastmodified = existing[0]  # MJD float or None
                        new_lastmodified_mjd = _to_mjd(cleaned_row.get('lastmodified'))

                        # Compare last_modified_date (MJD), keep newer data
                        if new_lastmodified_mjd is not None and existing_lastmodified is not None:
                            if new_lastmodified_mjd <= existing_lastmodified:
                                if debug:
                                    logger.debug(f"Skipping {cleaned_row.get('name')}: existing data is newer")
                                skipped_count += 1
                                continue
                        
                        # Prepare update data
                        update_batch.append((
                            cleaned_row.get('name_prefix'),
                            cleaned_row.get('name'),
                            cleaned_row.get('ra'),
                            cleaned_row.get('declination'),
                            cleaned_row.get('redshift'),
                            cleaned_row.get('type'),
                            cleaned_row.get('reporting_group'),
                            cleaned_row.get('source_group'),
                            _to_mjd(cleaned_row.get('discoverydate')),
                            cleaned_row.get('discoverymag'),
                            cleaned_row.get('discmagfilter'),
                            _reporters_arr(cleaned_row.get('reporters')),
                            _to_mjd(cleaned_row.get('time_received')),
                            cleaned_row.get('internal_names'),
                            cleaned_row.get('discovery_ads_bibcode'),
                            cleaned_row.get('class_ads_bibcodes'),
                            _to_mjd(cleaned_row.get('creationdate')),
                            _to_mjd(cleaned_row.get('last_photometry_date')),
                            _to_mjd(cleaned_row.get('lastmodified')),
                            cleaned_row.get('objid')
                        ))
                        updated_count += 1
                        
                        # Execute batch update
                        if len(update_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                UPDATE transient.objects SET
                                    name_prefix = %s, name = %s, ra = %s, dec = %s, redshift = %s,
                                    type = %s, report_group = %s, source_group = %s,
                                    discovery_date = %s, discovery_mag = %s, discovery_filter = %s,
                                    reporters = %s, received_date = %s, internal_name = %s,
                                    discovery_ADS = %s, class_ADS = %s,
                                    creation_date = %s, last_phot_date = %s, last_modified_date = %s,
                                    status = CASE WHEN status = 'Snoozed' THEN 'Inbox' ELSE status END
                                WHERE obj_id = %s
                            ''', update_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug(f"Committed {len(update_batch)} updates")
                            update_batch = []
                    else:
                        # Prepare insert data
                        insert_batch.append((
                            cleaned_row.get('objid'),
                            cleaned_row.get('name_prefix'),
                            cleaned_row.get('name'),
                            cleaned_row.get('ra'),
                            cleaned_row.get('declination'),
                            cleaned_row.get('redshift'),
                            cleaned_row.get('type'),
                            cleaned_row.get('reporting_group'),
                            cleaned_row.get('source_group'),
                            _to_mjd(cleaned_row.get('discoverydate')),
                            cleaned_row.get('discoverymag'),
                            cleaned_row.get('discmagfilter'),
                            _reporters_arr(cleaned_row.get('reporters')),
                            _to_mjd(cleaned_row.get('time_received')),
                            cleaned_row.get('internal_names'),
                            cleaned_row.get('discovery_ads_bibcode'),
                            cleaned_row.get('class_ads_bibcodes'),
                            _to_mjd(cleaned_row.get('creationdate')),
                            _to_mjd(cleaned_row.get('last_photometry_date')),
                            _to_mjd(cleaned_row.get('lastmodified'))
                        ))
                        imported_count += 1
                        
                        # Execute batch insert
                        if len(insert_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                INSERT INTO transient.objects (
                                    obj_id, name_prefix, name, ra, dec, redshift, type,
                                    report_group, source_group, discovery_date, discovery_mag,
                                    discovery_filter, reporters, received_date, internal_name,
                                    discovery_ADS, class_ADS, creation_date, last_phot_date,
                                    last_modified_date, status, tag
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Inbox', '{}'::text[])
                                ON CONFLICT DO NOTHING
                            ''', insert_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug(f"Committed {len(insert_batch)} inserts")
                            insert_batch = []
            
            # Execute remaining batches
            if update_batch:
                extras.execute_batch(cursor, '''
                    UPDATE transient.objects SET
                        name_prefix = %s, name = %s, ra = %s, dec = %s, redshift = %s,
                        type = %s, report_group = %s, source_group = %s,
                        discovery_date = %s, discovery_mag = %s, discovery_filter = %s,
                        reporters = %s, received_date = %s, internal_name = %s,
                        discovery_ADS = %s, class_ADS = %s,
                        creation_date = %s, last_phot_date = %s, last_modified_date = %s,
                        status = CASE WHEN status = 'Snoozed' THEN 'Inbox' ELSE status END
                    WHERE obj_id = %s
                ''', update_batch, page_size=BATCH_SIZE)
                if debug:
                    logger.debug(f"Committed final {len(update_batch)} updates")
            
            if insert_batch:
                extras.execute_batch(cursor, '''
                    INSERT INTO transient.objects (
                        obj_id, name_prefix, name, ra, dec, redshift, type,
                        report_group, source_group, discovery_date, discovery_mag,
                        discovery_filter, reporters, received_date, internal_name,
                        discovery_ADS, class_ADS, creation_date, last_phot_date,
                        last_modified_date, status, tag
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Inbox', '{}'::text[])
                    ON CONFLICT DO NOTHING
                ''', insert_batch, page_size=BATCH_SIZE)
                if debug:
                    logger.debug(f"Committed final {len(insert_batch)} inserts")
            
            conn.commit()
            cursor.close()
        
        logger.info(f"Import completed: {imported_count} new, {updated_count} updated, {skipped_count} skipped")
        
        # Update download log with success
        update_download_log(log_id, 'completed', records_imported=imported_count, records_updated=updated_count)
        n = sync_kinder_ids()
        if n:
            logger.info("sync_kinder_ids: assigned %d new kinder_ids", n)
        return True
        
    except Exception as e:
        logger.exception(f"Error importing CSV: {e}")
        
        # Update download log with error
        update_download_log(log_id, 'failed', records_imported=imported_count, records_updated=updated_count, error_message=str(e))
        return False


def auto_snoozed(time_now_utc, debug=False):
    """Auto-snooze objects with no photometry for 15+ days"""
    snoozed_count = 0
    finished_follow_count = 0

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Calculate cutoff as MJD (15 days ago)
            cutoff_mjd = (time_now_utc.date() - _MJD_EPOCH).days - 15

            if debug:
                logger.debug(f"Processing transient.objects with cutoff MJD: {cutoff_mjd}")

            # Find non-snoozed objects with old photometry or old last_modified_date
            cursor.execute('''
                SELECT obj_id, name, last_phot_date, status
                FROM transient.objects
                WHERE status != 'Snoozed'
                AND (
                    (last_phot_date IS NOT NULL AND last_phot_date < %s)
                    OR
                    (last_phot_date IS NULL AND last_modified_date < %s)
                )
            ''', (cutoff_mjd, cutoff_mjd))

            objects_to_snooze = cursor.fetchall()

            for obj in objects_to_snooze:
                obj_id, name, last_phot_date, cur_status = obj

                if cur_status == 'Follow-up':
                    # Was being followed — mark as Finish (auto-completed)
                    cursor.execute('''
                        UPDATE transient.objects
                        SET status = 'Finish'
                        WHERE obj_id = %s
                    ''', (obj_id,))
                    finished_follow_count += 1
                    if debug:
                        logger.debug(f"Snoozed & finished follow: {name} (last_phot: {last_phot_date})")
                else:
                    # Snooze it
                    cursor.execute('''
                        UPDATE transient.objects
                        SET status = 'Snoozed'
                        WHERE obj_id = %s
                    ''', (obj_id,))
                    if debug:
                        logger.debug(f"Snoozed: {name} (last_phot: {last_phot_date})")

                snoozed_count += 1
            
            conn.commit()
            cursor.close()
        
        logger.info(f"Auto-snooze completed: {snoozed_count} objects snoozed ({finished_follow_count} finished follow)")
        return True
        
    except Exception as e:
        logger.exception(f"Error in auto_snoozed: {e}")
        return False



def main():
    logger.info(f"TNS fetcher started at {datetime.now(timezone.utc)}")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # 1. Hourly at XX:15 and XX:45
            if now.minute == 15 or now.minute == 45:
                logger.info(f"Executing hourly task at {now}")
                utc_hr = f"{now.hour:02d}"
                if download_TNS_api_hr(utc_hr, debug=True):
                    work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
                    addin_database(work_csv, debug=True)
                    auto_snoozed(now, debug=True)

                # Extra auto-snooze at 00:15
                if now.hour == 0:
                    logger.info(f"Executing midnight auto-snooze at {now}")
                    auto_snoozed(now, debug=True)

                time.sleep(60)

            # 2. Daily at 01:00
            elif now.hour == 1 and now.minute == 0:
                logger.info(f"Executing daily task at {now}")
                yesterday = now - timedelta(days=1)
                if download_TNS_api(yesterday.year, yesterday.month, yesterday.day, debug=True):
                    work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
                    addin_database(work_csv, debug=True)
                    auto_snoozed(now, debug=True)

                time.sleep(60)

            else:
                time.sleep(10)

        except Exception as e:
            logger.exception(f"Error in main loop: {e}")
            time.sleep(10)


# ---------------------------------------------------------------------------
# Public entry point — called from main.py
# ---------------------------------------------------------------------------
_tns_thread      = None
_tns_thread_lock = threading.Lock()


def start_tns_fetcher(log_dir=None):
    """Start TNS fetcher as a daemon thread. Safe to call multiple times."""
    global _tns_thread
    with _tns_thread_lock:
        if _tns_thread is not None and _tns_thread.is_alive():
            logger.info("TNS fetcher already running.")
            return
        if log_dir and not logger.handlers:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, 'tns_fetch.log'))
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(fh)
            logger.setLevel(logging.INFO)
        _tns_thread = threading.Thread(target=main, daemon=True, name="tns_fetch")
        _tns_thread.start()
        logger.info("TNS fetcher daemon thread started.")


if __name__ == "__main__":
    print("========= START =========")
    try:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        if download_TNS_api(yesterday.year, yesterday.month, yesterday.day, debug=True):
            work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
            addin_database(work_csv, debug=True)
            auto_snoozed(now, debug=True)
    except Exception as e:
        print(f"Error during startup download: {e}")
        import traceback
        traceback.print_exc()
    main()
    # download_TNS_api_hr("12", debug=True)
    # work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
    # addin_database(work_csv, debug=True)