import os
import pathlib
import requests
import json
import zipfile
import pandas as pd
import time
import csv
from datetime import datetime, timezone
from postgres_database import get_db_connection, log_download_attempt, update_download_log
from psycopg2 import extras

# ---- User settings ----
SAVE_DIR = pathlib.Path("app/data/tns_api_download_work")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ---- BOT settings ----
from dotenv import load_dotenv
project_root = os.path.dirname(os.path.abspath(__file__))
# Use relative path to kinder.env (2 levels up from app/modules/)
dotenv_path = os.path.join(project_root, '..', '..', 'kinder.env')
load_dotenv(dotenv_path)
env = os.getenv
tns_host     = env("TNS_HOST")
api_base_url = env("API_BASE_URL")
bot_id       = env("BOT_ID")
bot_name     = env("BOT_NAME")
api_key      = env("API_KEY") 

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
        print(f"URL: {tns_link}")
        print(f"Headers: {headers}")
    
    # Retry logic: 10s, 30s, 60s
    retry_delays = [10, 30, 60]
    attempt = 0
    max_attempts = len(retry_delays) + 1
    
    while attempt < max_attempts:
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            print(f"Waiting {delay} seconds before retry {attempt}/{len(retry_delays)}...")
            time.sleep(delay)
        
        response = requests.post(tns_link, headers=headers, data=data)
        
        if response.status_code == 200:
            output_file = SAVE_DIR / f"tns_public_objects_{hr}.csv.zip"
            with open(output_file, 'wb') as f:
                f.write(response.content)
            if debug:
                print(f"Data successfully saved to: {output_file}")
            
            # Unzip the file
            with zipfile.ZipFile(output_file, 'r') as zip_ref:
                zip_ref.extractall(SAVE_DIR)
            if debug:
                print(f"File unzipped to: {SAVE_DIR}")
            
            # Rename the extracted CSV file
            extracted_csv = SAVE_DIR / f"tns_public_objects_{hr}.csv"
            #renamed_csv = SAVE_DIR / f"tns_public_objects_WORK_{hr}_WORK.csv"
            renamed_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
            if extracted_csv.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted_csv.rename(renamed_csv)
                if debug:
                    print(f"Renamed extracted file to: {renamed_csv}")
            
            # Remove the zip file
            output_file.unlink()
            if debug:
                print(f"Removed zip file: {output_file}")
            print(f"Download and extraction completed for {hr}")
            return True
        elif response.status_code == 404:
            print(f"Error: File not found (404) for {hr}")
            return False
        else:
            print(f"Error: Request failed with status code: {response.status_code}")
            attempt += 1
            if attempt >= max_attempts:
                print(f"Failed after {len(retry_delays)} retries. Stopping.")
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
        print(f"URL: {download_url}")
        print(f"Headers: {headers}")
    
    # Retry logic: 10s, 30s, 60s
    retry_delays = [10, 30, 60]
    attempt = 0
    max_attempts = len(retry_delays) + 1
    
    while attempt < max_attempts:
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            print(f"Waiting {delay} seconds before retry {attempt}/{len(retry_delays)}...")
            time.sleep(delay)
        
        response = requests.post(download_url, headers=headers, data=data)
        
        if response.status_code == 200:
            output_file = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv.zip"
            with open(output_file, 'wb') as f:
                f.write(response.content)
            if debug:
                print(f"Data successfully saved to: {output_file}")
            
            # Unzip the file
            with zipfile.ZipFile(output_file, 'r') as zip_ref:
                zip_ref.extractall(SAVE_DIR)
            if debug:
                print(f"File unzipped to: {SAVE_DIR}")
            
            # Rename the extracted CSV file
            extracted_csv = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv"
            #renamed_csv = SAVE_DIR / f"tns_public_objects_WORK_{year}{month:02d}{day:02d}_WORK.csv"
            renamed_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
            if extracted_csv.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted_csv.rename(renamed_csv)
                if debug:
                    print(f"Renamed extracted file to: {renamed_csv}")
            
            # Remove the zip file
            output_file.unlink()
            if debug:
                print(f"Removed zip file: {output_file}")
            print(f"Download and extraction completed for {year}-{month:02d}-{day:02d}")
            return True
        elif response.status_code == 404:
            print(f"Error: File not found (404) for {year}-{month:02d}-{day:02d}")
            return False
        else:
            print(f"Error: Request failed with status code: {response.status_code}")
            attempt += 1
            if attempt >= max_attempts:
                print(f"Failed after {len(retry_delays)} retries. Stopping.")
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
        print(f"Error: {error_msg}")
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
                    cursor.execute('SELECT lastmodified FROM tns_objects WHERE objid = %s', (cleaned_row.get('objid'),))
                    existing = cursor.fetchone()
                    
                    if existing:
                        existing_lastmodified = existing[0]
                        new_lastmodified = cleaned_row.get('lastmodified')
                        
                        # Compare lastmodified, keep newer data
                        if new_lastmodified and existing_lastmodified:
                            if new_lastmodified <= existing_lastmodified:
                                if debug:
                                    print(f"Skipping {cleaned_row.get('name')}: existing data is newer")
                                skipped_count += 1
                                continue
                        
                        # Prepare update data
                        update_batch.append((
                            cleaned_row.get('name_prefix'),
                            cleaned_row.get('name'),
                            cleaned_row.get('ra'),
                            cleaned_row.get('declination'),
                            cleaned_row.get('redshift'),
                            cleaned_row.get('typeid'),
                            cleaned_row.get('type'),
                            cleaned_row.get('reporting_groupid'),
                            cleaned_row.get('reporting_group'),
                            cleaned_row.get('source_groupid'),
                            cleaned_row.get('source_group'),
                            cleaned_row.get('discoverydate'),
                            cleaned_row.get('discoverymag'),
                            cleaned_row.get('discmagfilter'),
                            cleaned_row.get('filter'),
                            cleaned_row.get('reporters'),
                            cleaned_row.get('time_received'),
                            cleaned_row.get('internal_names'),
                            cleaned_row.get('discovery_ads_bibcode'),
                            cleaned_row.get('class_ads_bibcodes'),
                            cleaned_row.get('creationdate'),
                            cleaned_row.get('last_photometry_date'),
                            cleaned_row.get('lastmodified'),
                            cleaned_row.get('objid')
                        ))
                        updated_count += 1
                        
                        # Execute batch update
                        if len(update_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                UPDATE tns_objects SET
                                    name_prefix = %s, name = %s, ra = %s, declination = %s, redshift = %s,
                                    typeid = %s, type = %s, reporting_groupid = %s, reporting_group = %s,
                                    source_groupid = %s, source_group = %s, discoverydate = %s,
                                    discoverymag = %s, discmagfilter = %s, filter = %s, reporters = %s,
                                    time_received = %s, internal_names = %s, discovery_ads_bibcode = %s,
                                    class_ads_bibcodes = %s, creationdate = %s, last_photometry_date = %s, lastmodified = %s,
                                    inbox = 1, snoozed = 0
                                WHERE objid = %s
                            ''', update_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                print(f"Committed {len(update_batch)} updates")
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
                            cleaned_row.get('typeid'),
                            cleaned_row.get('type'),
                            cleaned_row.get('reporting_groupid'),
                            cleaned_row.get('reporting_group'),
                            cleaned_row.get('source_groupid'),
                            cleaned_row.get('source_group'),
                            cleaned_row.get('discoverydate'),
                            cleaned_row.get('discoverymag'),
                            cleaned_row.get('discmagfilter'),
                            cleaned_row.get('filter'),
                            cleaned_row.get('reporters'),
                            cleaned_row.get('time_received'),
                            cleaned_row.get('internal_names'),
                            cleaned_row.get('discovery_ads_bibcode'),
                            cleaned_row.get('class_ads_bibcodes'),
                            cleaned_row.get('creationdate'),
                            cleaned_row.get('last_photometry_date'),
                            cleaned_row.get('lastmodified')
                        ))
                        imported_count += 1
                        
                        # Execute batch insert
                        if len(insert_batch) >= BATCH_SIZE:
                            extras.execute_batch(cursor, '''
                                INSERT INTO tns_objects (
                                    objid, name_prefix, name, ra, declination, redshift, typeid, type,
                                    reporting_groupid, reporting_group, source_groupid, source_group,
                                    discoverydate, discoverymag, discmagfilter, filter, reporters,
                                    time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                                    creationdate, last_photometry_date, lastmodified, inbox, snoozed, follow, finish_follow
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0, 0, 0)
                            ''', insert_batch, page_size=BATCH_SIZE)
                            conn.commit()
                            if debug:
                                print(f"Committed {len(insert_batch)} inserts")
                            insert_batch = []
            
            # Execute remaining batches
            if update_batch:
                extras.execute_batch(cursor, '''
                    UPDATE tns_objects SET
                        name_prefix = %s, name = %s, ra = %s, declination = %s, redshift = %s,
                        typeid = %s, type = %s, reporting_groupid = %s, reporting_group = %s,
                        source_groupid = %s, source_group = %s, discoverydate = %s,
                        discoverymag = %s, discmagfilter = %s, filter = %s, reporters = %s,
                        time_received = %s, internal_names = %s, discovery_ads_bibcode = %s,
                        class_ads_bibcodes = %s, creationdate = %s, last_photometry_date = %s, lastmodified = %s,
                        inbox = 1, snoozed = 0
                    WHERE objid = %s
                ''', update_batch, page_size=BATCH_SIZE)
                if debug:
                    print(f"Committed final {len(update_batch)} updates")
            
            if insert_batch:
                extras.execute_batch(cursor, '''
                    INSERT INTO tns_objects (
                        objid, name_prefix, name, ra, declination, redshift, typeid, type,
                        reporting_groupid, reporting_group, source_groupid, source_group,
                        discoverydate, discoverymag, discmagfilter, filter, reporters,
                        time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
                        creationdate, last_photometry_date, lastmodified, inbox, snoozed, follow, finish_follow
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0, 0, 0)
                ''', insert_batch, page_size=BATCH_SIZE)
                if debug:
                    print(f"Committed final {len(insert_batch)} inserts")
            
            conn.commit()
            cursor.close()
        
        print(f"Import completed: {imported_count} new, {updated_count} updated, {skipped_count} skipped")
        
        # Update download log with success
        update_download_log(log_id, 'completed', records_imported=imported_count, records_updated=updated_count)
        return True
        
    except Exception as e:
        print(f"Error importing CSV: {e}")
        import traceback
        traceback.print_exc()
        
        # Update download log with error
        update_download_log(log_id, 'failed', records_imported=imported_count, records_updated=updated_count, error_message=str(e))
        return False


def auto_snoozed(time_now_utc, debug=False):
    """Auto-snooze objects with no photometry for 15+ days"""
    from datetime import timedelta
    
    snoozed_count = 0
    finished_follow_count = 0
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate cutoff date (15 days ago)
            cutoff_date = (time_now_utc - timedelta(days=15)).strftime('%Y-%m-%d')
            
            if debug:
                print(f"Processing tns_objects table with cutoff date: {cutoff_date}")
            
            # Find objects in inbox with old photometry or old lastmodified
            cursor.execute('''
                SELECT objid, name, last_photometry_date, follow
                FROM tns_objects
                WHERE inbox = 1 
                AND (
                    (last_photometry_date IS NOT NULL AND last_photometry_date < %s)
                    OR 
                    (last_photometry_date IS NULL AND lastmodified < %s)
                )
            ''', (cutoff_date, cutoff_date))
            
            objects_to_snooze = cursor.fetchall()
            
            for obj in objects_to_snooze:
                objid, name, last_phot_date, follow = obj
                
                if follow == 1:
                    # Update: inbox=0, snoozed=1, follow=0, finish_follow=1
                    cursor.execute('''
                        UPDATE tns_objects
                        SET inbox = 0, snoozed = 1, follow = 0, finish_follow = 1
                        WHERE objid = %s
                    ''', (objid,))
                    finished_follow_count += 1
                    if debug:
                        print(f"Snoozed & finished follow: {name} (last_phot: {last_phot_date})")
                else:
                    # Update: inbox=0, snoozed=1 (no change to follow/finish_follow)
                    cursor.execute('''
                        UPDATE tns_objects
                        SET inbox = 0, snoozed = 1
                        WHERE objid = %s
                    ''', (objid,))
                    if debug:
                        print(f"Snoozed: {name} (last_phot: {last_phot_date})")
                
                snoozed_count += 1
            
            conn.commit()
            cursor.close()
        
        print(f"Auto-snooze completed: {snoozed_count} objects snoozed ({finished_follow_count} finished follow)")
        return True
        
    except Exception as e:
        print(f"Error in auto_snoozed: {e}")
        import traceback
        traceback.print_exc()
        return False



def main():
    # Download latest hourly data
    utc_hr = f"{datetime.now(timezone.utc).hour:02d}"
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