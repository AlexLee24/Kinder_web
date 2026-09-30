import logging
import os

logger = logging.getLogger(__name__)
import csv
from datetime import datetime, timezone, date as _date

_MJD_EPOCH = _date(1858, 11, 17)


def _to_mjd(s):
    """Convert date string 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD' to MJD float."""
    if s is None:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(s).strip(), fmt)
            return ((_date(dt.year, dt.month, dt.day) - _MJD_EPOCH).days + dt.hour / 24.0
                    + dt.minute / 1440.0 + (dt.second + dt.microsecond / 1e6) / 86400.0)
        except ValueError:
            continue
    return None


def _reporters_arr(s):
    """Convert comma-separated reporters string to TEXT[]."""
    if not s:
        return None
    return [x.strip() for x in str(s).split(',') if x.strip()]
try:
    from app.db import get_db_connection
    from app.db.transient import log_download_attempt, update_download_log, sync_kinder_ids, _tns_name_to_kinder_id
except ImportError:
    from app.db import get_db_connection
    from database.transient import log_download_attempt, update_download_log, sync_kinder_ids, _tns_name_to_kinder_id
from psycopg2 import extras

# ---- User settings ----
from app.paths import ENV_FILE, TNS_WORK_DIR
SAVE_DIR = TNS_WORK_DIR   # app/data/tns_api_download_work
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ---- BOT settings ----
from dotenv import load_dotenv
load_dotenv(ENV_FILE)
env = os.getenv
tns_host     = env("TNS_HOST", "www.wis-tns.org")
api_base_url = env("API_BASE_URL", "https://www.wis-tns.org/api/get")
bot_id       = env("TNS_BOT_ID")      # same names as auto_tns_download / kinder.env
bot_name     = env("TNS_BOT_NAME")
api_key      = env("TNS_API_KEY")

# ---- Function to download TNS API data ----
# Both downloads go through auto_tns_download's helper: request timeout + retries,
# RequestException handling, and unique temp files so concurrent runs never clobber
# each other's zip/CSV. Each returns the CSV path (truthy; default
# tns_public_objects_WORK.csv, or ``dest``) or False.
def download_TNS_api_hr(hr, debug=False, dest=None):
    from app.services.tns.auto_tns_download import download_TNS_api_hr as _dl_hr
    return _dl_hr(hr, debug=debug, dest=dest)


def download_TNS_api(year, month, day, debug=False, dest=None):
    from app.services.tns.auto_tns_download import download_TNS_api as _dl_day
    return _dl_day(year, month, day, debug=debug, dest=dest)


def addin_database(filepath, debug=False):
    """Import a TNS CSV; serialised with the auto importer via tns_import_lock()."""
    from app.services.tns.auto_tns_download import tns_import_lock
    with tns_import_lock():
        return _addin_database_locked(filepath, debug=debug)


def _addin_database_locked(filepath, debug=False):
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
                    
                    # Check if object exists. obj_id is the kinder_id for rows created by
                    # the current importers (not the TNS objid), so match by name like
                    # auto_tns_download.addin_database does.
                    cursor.execute('SELECT obj_id, last_modified_date FROM transient.objects WHERE name = %s',
                                   (cleaned_row.get('name'),))
                    existing = cursor.fetchone()

                    if existing:
                        existing_obj_id = existing[0]
                        existing_lastmodified = existing[1]  # MJD float or None
                        new_lastmodified_mjd = _to_mjd(cleaned_row.get('lastmodified'))

                        # Compare last_modified_date (MJD), keep newer data
                        if new_lastmodified_mjd is not None and existing_lastmodified is not None:
                            if new_lastmodified_mjd <= existing_lastmodified:
                                if debug:
                                    logger.debug('Skipping %s: existing data is newer', cleaned_row.get('name'))
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
                            existing_obj_id
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
                                logger.debug('Committed %d updates', len(update_batch))
                            update_batch = []
                    else:
                        # Prepare insert data (obj_id = kinder_id, as auto_tns_download does)
                        kinder_id = _tns_name_to_kinder_id(cleaned_row.get('name'))
                        insert_batch.append((
                            kinder_id or cleaned_row.get('objid'),
                            kinder_id,
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
                                    obj_id, kinder_id, name_prefix, name, ra, dec, redshift, type,
                                    report_group, source_group, discovery_date, discovery_mag,
                                    discovery_filter, reporters, received_date, internal_name,
                                    discovery_ADS, class_ADS, creation_date, last_phot_date,
                                    last_modified_date, status, tag
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Inbox', '{}'::text[])
                                ON CONFLICT DO NOTHING
                            ''', insert_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                logger.debug('Committed %d inserts', len(insert_batch))
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
                    logger.debug('Committed final %d updates', len(update_batch))
            
            if insert_batch:
                extras.execute_batch(cursor, '''
                    INSERT INTO transient.objects (
                        obj_id, kinder_id, name_prefix, name, ra, dec, redshift, type,
                        report_group, source_group, discovery_date, discovery_mag,
                        discovery_filter, reporters, received_date, internal_name,
                        discovery_ADS, class_ADS, creation_date, last_phot_date,
                        last_modified_date, status, tag
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Inbox', '{}'::text[])
                    ON CONFLICT DO NOTHING
                ''', insert_batch, page_size=BATCH_SIZE)
                if debug:
                    logger.debug('Committed final %d inserts', len(insert_batch))
            
            conn.commit()
            cursor.close()
        
        logger.info('Import completed: %d new, %d updated, %d skipped', imported_count, updated_count, skipped_count)
        
        # Update download log with success
        update_download_log(log_id, 'completed', records_imported=imported_count, records_updated=updated_count)
        n = sync_kinder_ids()
        if n:
            logger.info('sync_kinder_ids: assigned %d new kinder_ids', n)
        return True
        
    except Exception as e:
        logger.error('Error importing CSV: %s', e)
        import traceback
        traceback.print_exc()
        
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
                logger.debug('Processing transient.objects with cutoff MJD: %s', cutoff_mjd)

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
                    # Was being followed — park it as Snoozed ('Finish' no longer exists)
                    cursor.execute('''
                        UPDATE transient.objects
                        SET status = 'Snoozed'
                        WHERE obj_id = %s
                    ''', (obj_id,))
                    finished_follow_count += 1
                    if debug:
                        logger.debug('Snoozed & finished follow: %s (last_phot: %s)', name, last_phot_date)
                else:
                    # Snooze it
                    cursor.execute('''
                        UPDATE transient.objects
                        SET status = 'Snoozed'
                        WHERE obj_id = %s
                    ''', (obj_id,))
                    if debug:
                        logger.debug('Snoozed: %s (last_phot: %s)', name, last_phot_date)

                snoozed_count += 1
            
            conn.commit()
            cursor.close()
        
        logger.info('Auto-snooze completed: %d objects snoozed (%d finished follow)', snoozed_count, finished_follow_count)
        return True
        
    except Exception as e:
        logger.error('Error in auto_snoozed: %s', e)
        import traceback
        traceback.print_exc()
        return False



def main():
    # Download latest hourly data
    # utc_hr = f"{datetime.now(timezone.utc).hour:02d}"
    # download_TNS_api_hr(utc_hr, debug=True)
    # # download_TNS_api(2026, 1, 2, debug=True)
    
    # # Import to database
    # work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
    # addin_database(work_csv, debug=True)
    # Auto-snooze old objects
    auto_snoozed(datetime.now(timezone.utc), debug=True)

if __name__ == "__main__":
    work_csv = SAVE_DIR / "tns_public_objects_WORK.csv"
    
    
    # utc_hr = f"{datetime.now(timezone.utc).hour:02d}"
    
    # download_TNS_api(2026, 1, 2, debug=True)
    
    # addin_database(work_csv, debug=True)
    
    auto_snoozed(datetime.now(timezone.utc), debug=True)