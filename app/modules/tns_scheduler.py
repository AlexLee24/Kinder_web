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
        self.max_retries = 3
        self.retry_delay = 60  # seconds
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
        
        # Retry mechanism for downloads
        for attempt in range(self.max_retries):
            try:
                print(f"Download attempt {attempt + 1}/{self.max_retries}")
                download_tns_data()
                
                result = self.find_and_process_csv(utc_hr, log_id)
                return result
                
            except requests.exceptions.ReadTimeout as e:
                error_msg = f"Download timeout on attempt {attempt + 1}: {e}"
                print(error_msg)
                
                if attempt < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    print("Max retries reached, marking as failed")
                    update_download_log(log_id, 'failed', error_message=f"Timeout after {self.max_retries} attempts")
                    raise e
                    
            except requests.exceptions.ConnectionError as e:
                error_msg = f"Connection error on attempt {attempt + 1}: {e}"
                print(error_msg)
                
                if attempt < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    print("Max retries reached, marking as failed")
                    update_download_log(log_id, 'failed', error_message=f"Connection error after {self.max_retries} attempts")
                    raise e
                    
            except Exception as e:
                error_msg = f"Unexpected error on attempt {attempt + 1}: {e}"
                print(error_msg)
                
                # For unexpected errors, don't retry
                update_download_log(log_id, 'failed', error_message=error_msg)
                raise e
    
    def start_scheduler(self):
        if self.running:
            return False
        
        # Schedule downloads at 01 and 31 minutes past every hour
        schedule.every().hour.at(":01").do(self._safe_download_wrapper)
        schedule.every().hour.at(":31").do(self._safe_download_wrapper)
        
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        print("TNS scheduler started - will download at 01 and 31 minutes past every hour")
        return True
    
    def _safe_download_wrapper(self):
        """Wrapper to catch and log exceptions from scheduled downloads"""
        try:
            current_time = datetime.now(timezone.utc)
            print(f"Scheduled download triggered at {current_time.strftime('%H:%M')} UTC")
            self.download_and_import_tns_data()
        except Exception as e:
            print(f"Scheduled download failed: {e}")
            # Continue running scheduler even if one download fails
    
    def stop_scheduler(self):
        self.running = False
        schedule.clear()
        if self.thread:
            self.thread.join(timeout=5)  # Increased timeout
        print("TNS scheduler stopped")
    
    def _run_scheduler(self):
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                print(f"Scheduler error: {e}")
                # Continue running even if there's an error
                time.sleep(5)
    
    def manual_download(self, hour_offset=0):
        hour_utc = (datetime.now(timezone.utc).hour - hour_offset) % 24
        utc_hr = f"{hour_utc:02d}"
        
        print(f"Starting manual TNS download for hour {utc_hr}")
        
        log_id = log_download_attempt(hour_utc, "manual_download")
        
        # Retry mechanism for manual downloads
        for attempt in range(self.max_retries):
            try:
                print(f"Manual download attempt {attempt + 1}/{self.max_retries}")
                download_tns_data()
                
                result = self.find_and_process_csv(utc_hr, log_id)
                return result
                
            except requests.exceptions.ReadTimeout as e:
                error_msg = f"Manual download timeout on attempt {attempt + 1}: {e}"
                print(error_msg)
                
                if attempt < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    print("Max retries reached for manual download")
                    update_download_log(log_id, 'failed', error_message=f"Manual download timeout after {self.max_retries} attempts")
                    raise e
                    
            except requests.exceptions.ConnectionError as e:
                error_msg = f"Manual download connection error on attempt {attempt + 1}: {e}"
                print(error_msg)
                
                if attempt < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    print("Max retries reached for manual download")
                    update_download_log(log_id, 'failed', error_message=f"Manual download connection error after {self.max_retries} attempts")
                    raise e
                    
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
        
        # First try exact hour matches
        for name in possible_names:
            potential_path = self.tns_data_dir / name
            if potential_path.exists():
                csv_path = potential_path
                break
        
        # If no exact match, look for any CSV files
        if not csv_path:
            csv_files = list(self.tns_data_dir.glob("*.csv"))
            if csv_files:
                # Use the most recent CSV file
                csv_path = max(csv_files, key=os.path.getctime)
                print(f"Using most recent CSV file: {csv_path.name}")
            else:
                raise FileNotFoundError(f"No CSV files found for hour {utc_hr}")
        
        print(f"Processing CSV file: {csv_path}")
        
        try:
            result = self.import_csv_to_database_with_tracking(str(csv_path))
            
            print(f"Import completed: {result['imported']} new, {result['updated']} updated, {result['errors']} errors")
            
            update_download_log(
                log_id, 
                'completed', 
                records_imported=result['imported'],
                records_updated=result['updated'],
                error_message=f"{result['errors']} errors" if result['errors'] > 0 else None
            )
            
            return result
            
        except Exception as e:
            print(f"Error processing CSV file: {e}")
            update_download_log(log_id, 'failed', error_message=f"CSV processing error: {str(e)}")
            raise e

    def import_csv_to_database_with_tracking(self, csv_file_path):
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        imported_count = 0
        updated_count = 0
        error_count = 0
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                
                # Check if file has enough lines
                if len(lines) < 3:
                    print(f"CSV file has insufficient data: {len(lines)} lines")
                    return {
                        'imported': 0,
                        'updated': 0,
                        'errors': 0,
                        'total_processed': 0
                    }
                
                # Skip first line (time range) and use second line as header
                header_line = lines[1].strip()
                data_lines = lines[2:]
                
                print(f"Time range: {lines[0].strip()}")
                print(f"Header: {header_line[:100]}...")
                print(f"Data lines: {len(data_lines)}")
                
                # Parse header to get field names
                import csv
                from io import StringIO
                
                header_reader = csv.reader(StringIO(header_line))
                fieldnames = next(header_reader)
                
                print(f"CSV columns: {fieldnames}")
                
                # Validate required columns
                if 'objid' not in fieldnames:
                    raise ValueError(f"Missing required 'objid' column in header")
                
                batch_size = 500
                batch_count = 0
                
                # Process data lines
                for row_num, line in enumerate(data_lines, 1):
                    try:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Parse CSV line
                        csv_reader = csv.reader(StringIO(line))
                        values = next(csv_reader)
                        
                        # Create row dictionary
                        row = {}
                        for i, fieldname in enumerate(fieldnames):
                            if i < len(values):
                                value = values[i].strip()
                                row[fieldname] = None if value in ('', 'NULL') else value
                            else:
                                row[fieldname] = None
                        
                        if not row.get('objid'):
                            print(f"Row {row_num}: Missing objid")
                            error_count += 1
                            continue
                        
                        # Check if object exists
                        cursor.execute('SELECT id FROM tns_objects WHERE objid = ?', (row.get('objid'),))
                        existing = cursor.fetchone()
                        
                        if existing:
                            update_tns_object(cursor, row)
                            updated_count += 1
                            if updated_count <= 5:
                                print(f"Updated: {row.get('name_prefix', '')}{row.get('name', '')}")
                        else:
                            insert_tns_object(cursor, row)
                            imported_count += 1
                            if imported_count <= 5:
                                print(f"Imported: {row.get('name_prefix', '')}{row.get('name', '')}")
                        
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
        """Clean up CSV files older than specified days"""
        try:
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            
            csv_files = list(self.tns_data_dir.glob("*.csv"))
            cleaned_count = 0
            
            for csv_file in csv_files:
                try:
                    if csv_file.stat().st_mtime < cutoff_time.timestamp():
                        csv_file.unlink()
                        cleaned_count += 1
                        print(f"Removed old CSV file: {csv_file.name}")
                except OSError as e:
                    print(f"Could not delete {csv_file}: {e}")
            
            if cleaned_count > 0:
                print(f"Cleaned up {cleaned_count} old CSV files")
            
        except Exception as e:
            print(f"Error during CSV cleanup: {e}")

    def get_download_status(self):
        """Get current download status for monitoring"""
        return {
            'running': self.running,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'data_directory': str(self.tns_data_dir)
        }

tns_scheduler = TNSScheduler()