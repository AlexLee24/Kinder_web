import schedule
import time
import threading
from datetime import datetime, timedelta
import pytz
from modules.tns_database import get_tns_db_connection

class AutoSnoozeScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        self.days_threshold = 45  # Default threshold
        self.timezone = pytz.timezone('Asia/Taipei')  # UTC+8
        
    def start_scheduler(self):
        """Start the auto-snooze scheduler"""
        if self.running:
            print("Auto-snooze scheduler is already running")
            return
            
        self.running = True
        
        # Schedule daily auto-snooze check at 00:20 UTC+8
        schedule.every().day.at("00:20").do(self.run_auto_snooze_check)
        
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        print("Auto-snooze scheduler started - will run daily at 00:20 UTC+8")
        self._log_startup_status()
    
    def _log_startup_status(self):
        """Log startup status without running auto-snooze immediately"""
        try:
            stats = self.get_auto_snooze_stats()
            print(f"Auto-snooze scheduler initialized with {self.days_threshold} days threshold")
            print(f"Current auto-snooze stats: {stats}")
        except Exception as e:
            print(f"Error getting auto-snooze stats: {e}")
    
    def stop_scheduler(self):
        """Stop the auto-snooze scheduler"""
        self.running = False
        schedule.clear()
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            
        print("Auto-snooze scheduler stopped")
    
    def _run_scheduler(self):
        """Internal method to run the scheduler loop"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                print(f"Auto-snooze scheduler error: {e}")
                time.sleep(300)  # Wait 5 minutes on error
    
    def run_auto_snooze_check(self):
        """Execute auto-snooze operation based on updated_at timestamps"""
        try:
            # Get current time in UTC+8
            now_utc8 = datetime.now(self.timezone)
            print(f"Running auto-snooze check at {now_utc8.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            
            # Calculate cutoff date (45 days ago)
            cutoff_date = now_utc8 - timedelta(days=self.days_threshold)
            cutoff_date_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
            
            print(f"Cutoff date for auto-snooze: {cutoff_date_str}")
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Ensure necessary columns exist
            self._ensure_columns_exist(cursor, conn)
            
            # 1. Find objects to snooze (updated_at > 45 days ago and not already snoozed)
            snoozed_count = self._snooze_old_objects(cursor, cutoff_date_str)
            
            # 2. Find objects to unsnooze (updated_at < 45 days ago and currently snoozed)
            unsnoozed_count = self._unsnooze_recent_objects(cursor, cutoff_date_str)
            
            conn.commit()
            conn.close()
            
            print(f"Auto-snooze completed: {snoozed_count} objects snoozed, {unsnoozed_count} objects moved back to inbox")
            
            # Log the activity
            self._log_auto_snooze_activity(snoozed_count, unsnoozed_count)
            
            return {
                'snoozed_count': snoozed_count,
                'unsnoozed_count': unsnoozed_count,
                'total_processed': snoozed_count + unsnoozed_count
            }
            
        except Exception as e:
            print(f"Error during auto-snooze: {e}")
            import traceback
            traceback.print_exc()
            return {'snoozed_count': 0, 'unsnoozed_count': 0, 'total_processed': 0}
    
    def _ensure_columns_exist(self, cursor, conn):
        """Ensure required columns exist in the database"""
        try:
            cursor.execute("PRAGMA table_info(tns_objects)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'tag' not in column_names:
                print("Adding tag column...")
                cursor.execute("ALTER TABLE tns_objects ADD COLUMN tag TEXT DEFAULT 'object'")
                conn.commit()
                
            if 'last_activity' not in column_names:
                print("Adding last_activity column...")
                cursor.execute("ALTER TABLE tns_objects ADD COLUMN last_activity TEXT")
                conn.commit()
                
                # Initialize last_activity with updated_at or imported_at
                cursor.execute("""
                    UPDATE tns_objects 
                    SET last_activity = COALESCE(updated_at, imported_at, CURRENT_TIMESTAMP)
                    WHERE last_activity IS NULL
                """)
                conn.commit()
                
        except Exception as e:
            print(f"Error ensuring columns exist: {e}")
    
    def _snooze_old_objects(self, cursor, cutoff_date_str):
        """Snooze objects that haven't been updated for 45+ days"""
        try:
            # Find objects to snooze
            cursor.execute("""
                SELECT objid, name_prefix, name, updated_at, tag
                FROM tns_objects 
                WHERE (tag IS NULL OR tag = '' OR tag = 'object')
                AND (updated_at IS NULL OR updated_at < ?)
                AND discoverydate IS NOT NULL
            """, (cutoff_date_str,))
            
            candidates = cursor.fetchall()
            
            if not candidates:
                print("No objects found for auto-snoozing")
                return 0
            
            print(f"Found {len(candidates)} objects eligible for auto-snoozing")
            
            # Update these objects to snoozed status
            snooze_count = 0
            for obj in candidates:
                objid, name_prefix, name, updated_at, current_tag = obj
                full_name = (name_prefix or '') + (name or '')
                
                try:
                    cursor.execute("""
                        UPDATE tns_objects 
                        SET tag = 'snoozed', 
                            last_activity = CURRENT_TIMESTAMP,
                            auto_snoozed_at = CURRENT_TIMESTAMP
                        WHERE objid = ?
                    """, (objid,))
                    
                    if cursor.rowcount > 0:
                        snooze_count += 1
                        print(f"Auto-snoozed: {full_name} (last updated: {updated_at})")
                    
                except Exception as e:
                    print(f"Error auto-snoozing {full_name}: {e}")
                    continue
            
            return snooze_count
            
        except Exception as e:
            print(f"Error in _snooze_old_objects: {e}")
            return 0
    
    def _unsnooze_recent_objects(self, cursor, cutoff_date_str):
        """Move recently updated objects back to inbox if they're currently snoozed"""
        try:
            # Find snoozed objects that have been updated recently
            cursor.execute("""
                SELECT objid, name_prefix, name, updated_at, tag
                FROM tns_objects 
                WHERE tag = 'snoozed'
                AND updated_at IS NOT NULL 
                AND updated_at >= ?
            """, (cutoff_date_str,))
            
            candidates = cursor.fetchall()
            
            if not candidates:
                print("No snoozed objects found for reactivation")
                return 0
            
            print(f"Found {len(candidates)} snoozed objects with recent updates")
            
            # Update these objects back to inbox (object status)
            unsnooze_count = 0
            for obj in candidates:
                objid, name_prefix, name, updated_at, current_tag = obj
                full_name = (name_prefix or '') + (name or '')
                
                try:
                    cursor.execute("""
                        UPDATE tns_objects 
                        SET tag = 'object', 
                            last_activity = CURRENT_TIMESTAMP,
                            auto_unsnoozed_at = CURRENT_TIMESTAMP
                        WHERE objid = ?
                    """, (objid,))
                    
                    if cursor.rowcount > 0:
                        unsnooze_count += 1
                        print(f"Moved back to inbox: {full_name} (recently updated: {updated_at})")
                    
                except Exception as e:
                    print(f"Error moving {full_name} back to inbox: {e}")
                    continue
            
            return unsnooze_count
            
        except Exception as e:
            print(f"Error in _unsnooze_recent_objects: {e}")
            return 0
    
    def _log_auto_snooze_activity(self, snoozed_count, unsnoozed_count):
        """Log auto-snooze activity to the download log"""
        try:
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            # Add tracking columns if they don't exist
            try:
                cursor.execute("ALTER TABLE tns_objects ADD COLUMN auto_snoozed_at TEXT")
            except:
                pass
            
            try:
                cursor.execute("ALTER TABLE tns_objects ADD COLUMN auto_unsnoozed_at TEXT")
            except:
                pass
            
            # Log to download log table
            cursor.execute("""
                INSERT INTO tns_download_log (
                    download_time, hour_utc, filename, status, 
                    records_imported, records_updated, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(), 
                datetime.now().hour,
                'auto_snooze_system',
                'completed',
                unsnoozed_count,  # Objects moved back to inbox
                snoozed_count,    # Objects moved to snoozed
                f'Auto-processed {snoozed_count + unsnoozed_count} objects: {snoozed_count} snoozed, {unsnoozed_count} reactivated'
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Warning: Could not log auto-snooze activity: {e}")
    
    def manual_auto_snooze(self, days_threshold=None):
        """Manually trigger auto-snooze with optional custom threshold"""
        if days_threshold:
            old_threshold = self.days_threshold
            self.days_threshold = days_threshold
            
        try:
            result = self.run_auto_snooze_check()
            return result['snoozed_count'] + result['unsnoozed_count']
        finally:
            if days_threshold:
                self.days_threshold = old_threshold
    
    def get_status(self):
        """Get scheduler status and statistics"""
        stats = self.get_auto_snooze_stats()
        
        return {
            'running': self.running,
            'days_threshold': self.days_threshold,
            'timezone': str(self.timezone),
            'next_run': self._get_next_run_time(),
            'stats': stats
        }
    
    def get_auto_snooze_stats(self):
        """Get statistics about auto-snoozed objects"""
        try:
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            stats = {}
            
            # Check if columns exist
            cursor.execute("PRAGMA table_info(tns_objects)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'auto_snoozed_at' in column_names:
                # Count auto-snoozed objects
                cursor.execute("SELECT COUNT(*) FROM tns_objects WHERE auto_snoozed_at IS NOT NULL")
                stats['auto_snoozed_count'] = cursor.fetchone()[0]
                
                # Recent auto-snooze activity (last 7 days)
                cursor.execute("""
                    SELECT COUNT(*) FROM tns_objects 
                    WHERE auto_snoozed_at > datetime('now', '-7 days')
                """)
                stats['auto_snoozed_last_week'] = cursor.fetchone()[0]
            else:
                stats['auto_snoozed_count'] = 0
                stats['auto_snoozed_last_week'] = 0
            
            if 'auto_unsnoozed_at' in column_names:
                # Count auto-unsnoozed objects
                cursor.execute("SELECT COUNT(*) FROM tns_objects WHERE auto_unsnoozed_at IS NOT NULL")
                stats['auto_unsnoozed_count'] = cursor.fetchone()[0]
                
                # Recent auto-unsnooze activity (last 7 days)
                cursor.execute("""
                    SELECT COUNT(*) FROM tns_objects 
                    WHERE auto_unsnoozed_at > datetime('now', '-7 days')
                """)
                stats['auto_unsnoozed_last_week'] = cursor.fetchone()[0]
            else:
                stats['auto_unsnoozed_count'] = 0
                stats['auto_unsnoozed_last_week'] = 0
            
            # Objects that could be auto-snoozed soon (35-44 days inactive)
            cutoff_warning = (datetime.now() - timedelta(days=35)).isoformat()
            cutoff_snooze = (datetime.now() - timedelta(days=45)).isoformat()
            
            cursor.execute("""
                SELECT COUNT(*) FROM tns_objects 
                WHERE (tag IS NULL OR tag = '' OR tag = 'object')
                AND updated_at < ? AND updated_at >= ?
            """, (cutoff_warning, cutoff_snooze))
            stats['objects_at_risk'] = cursor.fetchone()[0]
            
            conn.close()
            return stats
            
        except Exception as e:
            print(f"Error getting auto-snooze stats: {e}")
            return {
                'auto_snoozed_count': 0,
                'auto_snoozed_last_week': 0,
                'auto_unsnoozed_count': 0,
                'auto_unsnoozed_last_week': 0,
                'objects_at_risk': 0
            }
    
    def _get_next_run_time(self):
        """Get next scheduled run time"""
        if not self.running:
            return None
            
        jobs = schedule.get_jobs()
        if jobs:
            # Convert to UTC+8 timezone
            next_run_utc = jobs[0].next_run
            next_run_utc8 = next_run_utc.replace(tzinfo=pytz.UTC).astimezone(self.timezone)
            return next_run_utc8.strftime('%Y-%m-%d %H:%M:%S %Z')
        return None

# Global scheduler instance
auto_snooze_scheduler = AutoSnoozeScheduler()