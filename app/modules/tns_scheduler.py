import schedule
import time
import threading
from datetime import datetime, timezone
import requests
import os
from pathlib import Path
from dotenv import load_dotenv
import zipfile
import csv
from .tns_database import (
    init_tns_database, import_csv_to_database, 
    log_download_attempt, update_download_log,
    get_tns_db_connection, insert_tns_object, update_tns_object
)
from .tns_hourly_download import download_tns_data

class TNSScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        load_dotenv()
        
        init_tns_database()
        
        self.tns_data_dir = Path(os.path.dirname(os.path.dirname(__file__))) / "tns_data"
        self.tns_data_dir.mkdir(exist_ok=True)
        
        self.tns_bot_id = os.getenv('TNS_BOT_ID')
        self.tns_bot_name = os.getenv('TNS_BOT_NAME')
        self.headers = {
            'User-Agent': f'tns_marker{{"tns_id":"{self.tns_bot_id}","type":"bot","name":"{self.tns_bot_name}"}}'
        }
    
    def download_and_import_tns_data(self):
        current_utc = datetime.now(timezone.utc)
        prev_hour = (current_utc.hour - 1) % 24
        utc_hr = f"{prev_hour:02d}"
        
        print(f"Starting TNS download for hour {utc_hr}")
        
        log_id = log_download_attempt(prev_hour)
        
        try:
            download_tns_data()
            
            result = self.find_and_process_csv(utc_hr, log_id)
            return result
                
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            print(error_msg)
            update_download_log(log_id, 'failed', error_message=error_msg)
            raise e
    
    def start_scheduler(self):
        if self.running:
            return False
        
        schedule.every().hour.at(":01").do(self.download_and_import_tns_data)
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        print("TNS scheduler started - will download at 1 minute past every hour")
        return True
    
    def stop_scheduler(self):
        self.running = False
        schedule.clear()
        if self.thread:
            self.thread.join(timeout=1)
        print("TNS scheduler stopped")
    
    def _run_scheduler(self):
        while self.running:
            schedule.run_pending()
            time.sleep(1)
    
    def manual_download(self, hour_offset=0):
        hour_utc = (datetime.now(timezone.utc).hour - hour_offset) % 24
        utc_hr = f"{hour_utc:02d}"
        
        print(f"Starting manual TNS download for hour {utc_hr}")
        
        log_id = log_download_attempt(hour_utc, "manual_download")
        
        try:
            download_tns_data()
            
            result = self.find_and_process_csv(utc_hr, log_id)
            return result
                
        except Exception as e:
            print(f"Manual download failed: {e}")
            update_download_log(log_id, 'failed', error_message=str(e))
            raise e

    def find_and_process_csv(self, utc_hr, log_id):
        possible_names = [
            f"tns_public_objects_{utc_hr}.csv",
            f"tns_public_objects_{int(utc_hr):02d}.csv",
            f"tns_{utc_hr}.csv",
            f"public_objects_{utc_hr}.csv"
        ]
        
        csv_path = None
        
        for name in possible_names:
            potential_path = self.tns_data_dir / name
            if potential_path.exists():
                csv_path = potential_path
                break
        
        if not csv_path:
            csv_files = list(self.tns_data_dir.glob("*.csv"))
            if csv_files:
                csv_path = csv_files[0]
                print(f"Using found CSV file: {csv_path.name}")
            else:
                raise FileNotFoundError(f"No CSV files found for hour {utc_hr}")
        
        print(f"Processing CSV file: {csv_path}")
        
        result = self.import_csv_to_database_with_tracking(str(csv_path))
        
        print(f"Import completed: {result['imported']} new, {result['updated']} updated, {result['errors']} errors")
        
        update_download_log(
            log_id, 
            'completed', 
            records_imported=result['imported'],
            records_updated=result['updated'],
            error_message=f"{result['errors']} errors" if result['errors'] > 0 else None
        )
        
        # Keep CSV file for future reference (max 24 files, one per UTC hour)
        print(f"Keeping CSV file: {csv_path}")
        return result

    def import_csv_to_database_with_tracking(self, csv_file_path):
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        imported_count = 0
        updated_count = 0
        error_count = 0
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Skip lines until we find the header
                line = file.readline()
                line_count = 1
                
                while line and not line.strip().startswith('"objid"'):
                    print(f"Skipping line {line_count}: {line.strip()[:50]}...")
                    line = file.readline()
                    line_count += 1
                
                if not line:
                    raise ValueError("Could not find CSV header line starting with 'objid'")
                
                print(f"Found header at line {line_count}: {line.strip()}")
                
                # Reset file position to start of header line
                file.seek(0)
                for _ in range(line_count - 1):
                    file.readline()
                
                # Now read with CSV reader
                csv_reader = csv.DictReader(file)
                
                print(f"CSV columns: {csv_reader.fieldnames}")
                
                batch_size = 1000
                batch_count = 0
                
                for row_num, row in enumerate(csv_reader, 1):
                    try:
                        cleaned_row = {}
                        for key, value in row.items():
                            if value == '' or value == 'NULL' or value is None:
                                cleaned_row[key] = None
                            else:
                                cleaned_row[key] = value
                        
                        if not cleaned_row.get('objid'):
                            print(f"Row {row_num}: Missing objid")
                            error_count += 1
                            continue
                        
                        cursor.execute('SELECT id FROM tns_objects WHERE objid = ?', (cleaned_row.get('objid'),))
                        existing = cursor.fetchone()
                        
                        if existing:
                            update_tns_object(cursor, cleaned_row)
                            updated_count += 1
                            if updated_count <= 5:
                                print(f"Updated: {cleaned_row.get('name_prefix', '')}{cleaned_row.get('name', '')}")
                        else:
                            insert_tns_object(cursor, cleaned_row)
                            imported_count += 1
                            if imported_count <= 5:
                                print(f"Imported: {cleaned_row.get('name_prefix', '')}{cleaned_row.get('name', '')}")
                        
                        batch_count += 1
                        if batch_count >= batch_size:
                            conn.commit()
                            batch_count = 0
                            print(f"Processed {row_num} rows... ({imported_count} new, {updated_count} updated)")
                            
                    except Exception as row_error:
                        error_count += 1
                        print(f"Error processing row {row_num}: {row_error}")
                        continue
            
            conn.commit()
            
            print(f"Import completed: {imported_count} new, {updated_count} updated, {error_count} errors")
            
            return {
                'imported': imported_count,
                'updated': updated_count,
                'errors': error_count,
                'total_processed': imported_count + updated_count
            }
            
        except Exception as e:
            conn.rollback()
            print(f"Database error: {e}")
            raise e
        finally:
            conn.close()

    def cleanup_old_csv_files(self, days_to_keep=7):
        """Clean up CSV files older than specified days (optional maintenance)"""
        try:
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            
            csv_files = list(self.tns_data_dir.glob("*.csv"))
            cleaned_count = 0
            
            for csv_file in csv_files:
                if csv_file.stat().st_mtime < cutoff_time.timestamp():
                    csv_file.unlink()
                    cleaned_count += 1
                    print(f"Removed old CSV file: {csv_file.name}")
            
            if cleaned_count > 0:
                print(f"Cleaned up {cleaned_count} old CSV files")
            
        except Exception as e:
            print(f"Error during CSV cleanup: {e}")

tns_scheduler = TNSScheduler()