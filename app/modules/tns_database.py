import sqlite3
import csv
import os
from datetime import datetime
from pathlib import Path

def get_tns_db_connection():
    """Get connection to TNS database"""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'tns_data.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)

def init_tns_database():
    """Initialize TNS database with required tables"""
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    # Create TNS objects table with version tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tns_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            objid INTEGER UNIQUE NOT NULL,
            name_prefix TEXT,
            name TEXT NOT NULL,
            ra REAL NOT NULL,
            declination REAL NOT NULL,
            redshift TEXT,
            typeid TEXT,
            type TEXT,
            reporting_groupid TEXT,
            reporting_group TEXT,
            source_groupid TEXT,
            source_group TEXT,
            discoverydate TEXT,
            discoverymag TEXT,
            discmagfilter TEXT,
            filter TEXT,
            reporters TEXT,
            time_received TEXT,
            internal_names TEXT,
            discovery_ads_bibcode TEXT,
            class_ads_bibcodes TEXT,
            creationdate TEXT,
            lastmodified TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            update_count INTEGER DEFAULT 0
        )
    ''')
    
    # Create download log table with enhanced tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tns_download_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            download_time TEXT NOT NULL,
            hour_utc INTEGER NOT NULL,
            filename TEXT,
            records_imported INTEGER DEFAULT 0,
            records_updated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE tns_download_log ADD COLUMN records_imported INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE tns_download_log ADD COLUMN records_updated INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE tns_download_log ADD COLUMN error_message TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE tns_download_log ADD COLUMN completed_at TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Create indexes for better performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_objid ON tns_objects(objid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_name ON tns_objects(name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_coordinates ON tns_objects(ra, declination)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_discovery ON tns_objects(discoverydate)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_type ON tns_objects(type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_updated ON tns_objects(updated_at)')
    
    conn.commit()
    conn.close()

def insert_tns_object(cursor, row):
    """Insert new TNS object"""
    cursor.execute('''
        INSERT INTO tns_objects (
            objid, name_prefix, name, ra, declination, redshift, typeid, type,
            reporting_groupid, reporting_group, source_groupid, source_group,
            discoverydate, discoverymag, discmagfilter, filter, reporters,
            time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
            creationdate, lastmodified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        row.get('objid'),
        row.get('name_prefix'),
        row.get('name'),
        row.get('ra'),
        row.get('declination'),
        row.get('redshift'),
        row.get('typeid'),
        row.get('type'),
        row.get('reporting_groupid'),
        row.get('reporting_group'),
        row.get('source_groupid'),
        row.get('source_group'),
        row.get('discoverydate'),
        row.get('discoverymag'),
        row.get('discmagfilter'),
        row.get('filter'),
        row.get('reporters'),
        row.get('time_received'),
        row.get('internal_names'),
        row.get('discovery_ads_bibcode'),
        row.get('class_ads_bibcodes'),
        row.get('creationdate'),
        row.get('lastmodified')
    ))

def update_tns_object(cursor, row):
    """Update existing TNS object with version tracking"""
    cursor.execute('''
        UPDATE tns_objects SET
            name_prefix = ?, name = ?, ra = ?, declination = ?, redshift = ?,
            typeid = ?, type = ?, reporting_groupid = ?, reporting_group = ?,
            source_groupid = ?, source_group = ?, discoverydate = ?,
            discoverymag = ?, discmagfilter = ?, filter = ?, reporters = ?,
            time_received = ?, internal_names = ?, discovery_ads_bibcode = ?,
            class_ads_bibcodes = ?, creationdate = ?, lastmodified = ?,
            updated_at = CURRENT_TIMESTAMP,
            update_count = update_count + 1
        WHERE objid = ?
    ''', (
        row.get('name_prefix'),
        row.get('name'),
        row.get('ra'),
        row.get('declination'),
        row.get('redshift'),
        row.get('typeid'),
        row.get('type'),
        row.get('reporting_groupid'),
        row.get('reporting_group'),
        row.get('source_groupid'),
        row.get('source_group'),
        row.get('discoverydate'),
        row.get('discoverymag'),
        row.get('discmagfilter'),
        row.get('filter'),
        row.get('reporters'),
        row.get('time_received'),
        row.get('internal_names'),
        row.get('discovery_ads_bibcode'),
        row.get('class_ads_bibcodes'),
        row.get('creationdate'),
        row.get('lastmodified'),
        row.get('objid')  # WHERE clause
    ))

def log_download_attempt(hour_utc, filename=None):
    """Log a TNS download attempt with enhanced tracking"""
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO tns_download_log (download_time, hour_utc, filename, status, records_imported, records_updated)
            VALUES (?, ?, ?, 'started', 0, 0)
        ''', (datetime.now().isoformat(), hour_utc, filename))
    except sqlite3.OperationalError as e:
        cursor.execute('''
            INSERT INTO tns_download_log (download_time, hour_utc, filename, status)
            VALUES (?, ?, ?, 'started')
        ''', (datetime.now().isoformat(), hour_utc, filename))
    
    log_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return log_id

def update_download_log(log_id, status, records_imported=0, records_updated=0, error_message=None):
    """Update download log with results"""
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE tns_download_log SET
                status = ?,
                records_imported = ?,
                records_updated = ?,
                error_message = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, records_imported, records_updated, error_message, log_id))
    except sqlite3.OperationalError:
        cursor.execute('''
            UPDATE tns_download_log SET
                status = ?
            WHERE id = ?
        ''', (status, log_id))
    
    conn.commit()
    conn.close()

def import_csv_to_database(csv_file_path):
    """Import CSV data to TNS database with upsert logic"""
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    imported_count = 0
    updated_count = 0
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            
            for row in csv_reader:
                # Clean and prepare data
                cleaned_row = {}
                for key, value in row.items():
                    # Handle empty strings and NULL values
                    if value == '' or value == 'NULL' or value is None:
                        cleaned_row[key] = None
                    else:
                        cleaned_row[key] = value
                
                # Validate required fields
                if not cleaned_row.get('objid'):
                    continue
                
                # Check if object already exists by objid
                cursor.execute('SELECT id FROM tns_objects WHERE objid = ?', (cleaned_row.get('objid'),))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing record
                    update_tns_object(cursor, cleaned_row)
                    updated_count += 1
                else:
                    # Insert new record
                    insert_tns_object(cursor, cleaned_row)
                    imported_count += 1
        
        conn.commit()
        print(f"Import completed: {imported_count} new objects, {updated_count} updated objects")
        return imported_count + updated_count
        
    except Exception as e:
        conn.rollback()
        print(f"Error importing CSV: {e}")
        raise e
    finally:
        conn.close()

def search_tns_objects(search_term=None, object_type=None, limit=100, offset=0, sort_by="discoverydate", sort_order="desc", date_from=None, date_to=None, tag=None):
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        query = """
        SELECT objid, name_prefix, name, ra, declination, redshift, typeid, type,
               reporting_groupid, reporting_group, source_groupid, source_group,
               discoverydate, discoverymag, discmagfilter, filter, reporters,
               time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
               creationdate, lastmodified, imported_at, updated_at, update_count,
               COALESCE(tag, 'object') as tag
        FROM tns_objects 
        WHERE 1=1
        """
        
        params = []
        
        if search_term:
            search_term = search_term.strip()
            print(f"Searching for: '{search_term}'")
            
            query += """ AND (
                name LIKE ? OR 
                (COALESCE(name_prefix, '') || COALESCE(name, '')) LIKE ?
            )"""
            search_pattern = f"%{search_term}%"
            params.extend([search_pattern, search_pattern])
            
            print(f"Search pattern: '{search_pattern}'")
        
        if object_type:
            if object_type.upper() == 'AT':
                query += " AND (type IS NULL OR type = '' OR type = 'AT')"
            else:
                query += " AND type = ?"
                params.append(object_type)
        
        if date_from:
            query += " AND discoverydate >= ?"
            params.append(date_from)
            
        if date_to:
            query += " AND discoverydate <= ?"
            params.append(date_to)
        
        if tag:
            query += " AND COALESCE(tag, 'object') = ?"
            params.append(tag)
            print(f"Tag filter applied: {tag}")
        
        sort_column = sort_by if sort_by in ["discoverydate", "name", "type", "redshift", "discoverymag", "time_received"] else "discoverydate"
        sort_direction = "DESC" if sort_order.upper() == "DESC" else "ASC"
        query += f" ORDER BY {sort_column} {sort_direction}"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
            
        if offset:
            query += " OFFSET ?"
            params.append(offset)
        
        print(f"Final query: {query}")
        print(f"Final params: {params}")
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if results:
            columns = [desc[0] for desc in cursor.description]
            objects = []
            for row in results:
                obj_dict = dict(zip(columns, row))
                if 'tag' not in obj_dict or obj_dict['tag'] is None:
                    obj_dict['tag'] = 'object'
                objects.append(obj_dict)
            
            print(f"Found {len(objects)} objects")
            return objects
        else:
            print("No objects found")
            return []
        
    except Exception as e:
        print(f"Database search error: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def get_objects_count(search_term=None, object_type=None, tag=None, date_from=None, date_to=None):
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT COUNT(*) FROM tns_objects WHERE 1=1"
    params = []
    
    if search_term:
        query += " AND (name LIKE ? OR (COALESCE(name_prefix, '') || COALESCE(name, '')) LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern])
    
    if object_type:
        if object_type.upper() == 'AT':
            query += " AND (type IS NULL OR type = '' OR type = 'AT')"
        else:
            query += " AND type = ?"
            params.append(object_type)
            
    if date_from:
        query += " AND discoverydate >= ?"
        params.append(date_from)
        
    if date_to:
        query += " AND discoverydate <= ?"
        params.append(date_to)
    
    if tag:
        query += " AND COALESCE(tag, 'object') = ?"
        params.append(tag)
    
    cursor.execute(query, params)
    count = cursor.fetchone()[0]
    
    conn.close()
    return count

def get_filtered_stats(search_term=None, object_type=None, tag=None, date_from=None, date_to=None):
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    stats = {
        'at_count': 0,
        'classified_count': 0,
        'inbox_count': 0,
        'followup_count': 0,
        'finished_count': 0,
        'snoozed_count': 0
    }
    
    # Base query parts
    base_where = "WHERE 1=1"
    params = []
    
    # Add filters
    if search_term:
        base_where += " AND (name LIKE ? OR name_prefix LIKE ? OR internal_names LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern, search_pattern])
    
    if date_from:
        base_where += " AND discoverydate >= ?"
        params.append(date_from)
        
    if date_to:
        base_where += " AND discoverydate <= ?"
        params.append(date_to)
    
    # AT vs Classified count
    cursor.execute(
        f"SELECT COUNT(*) FROM tns_objects {base_where} AND (type IS NULL OR type = '' OR type = 'AT')", 
        params
    )
    stats['at_count'] = cursor.fetchone()[0]
    
    cursor.execute(
        f"SELECT COUNT(*) FROM tns_objects {base_where} AND type IS NOT NULL AND type != '' AND type != 'AT'", 
        params
    )
    stats['classified_count'] = cursor.fetchone()[0]
    
    stats['inbox_count'] = stats['at_count'] + stats['classified_count']
    
    conn.close()
    return stats

def get_tns_statistics():
    """Get comprehensive TNS database statistics"""
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    try:
        # Total objects
        cursor.execute('SELECT COUNT(*) FROM tns_objects')
        stats['total_objects'] = cursor.fetchone()[0]
        
        # Objects by type
        cursor.execute('''
            SELECT type, COUNT(*) 
            FROM tns_objects 
            WHERE type IS NOT NULL AND type != ''
            GROUP BY type 
            ORDER BY COUNT(*) DESC
        ''')
        stats['objects_by_type'] = dict(cursor.fetchall())
        
        # Recent downloads with update info
        try:
            cursor.execute('''
                SELECT download_time, hour_utc, status, records_imported, records_updated, error_message
                FROM tns_download_log 
                ORDER BY download_time DESC 
                LIMIT 10
            ''')
            stats['recent_downloads'] = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            cursor.execute('''
                SELECT download_time, hour_utc, status
                FROM tns_download_log 
                ORDER BY download_time DESC 
                LIMIT 10
            ''')
            basic_downloads = cursor.fetchall()
            stats['recent_downloads'] = [
                {
                    'download_time': row[0],
                    'hour_utc': row[1],
                    'status': row[2],
                    'records_imported': 0,
                    'records_updated': 0,
                    'error_message': None
                } for row in basic_downloads
            ]
        
        # Update statistics
        try:
            cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE update_count > 0')
            stats['updated_objects'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(update_count) FROM tns_objects WHERE update_count > 0')
            avg_updates = cursor.fetchone()[0]
            stats['avg_updates_per_object'] = round(avg_updates, 2) if avg_updates else 0
        except sqlite3.OperationalError:
            stats['updated_objects'] = 0
            stats['avg_updates_per_object'] = 0
        
    except Exception as e:
        print(f"Error getting TNS statistics: {e}")
        stats = {
            'total_objects': 0,
            'objects_by_type': {},
            'recent_downloads': [],
            'updated_objects': 0,
            'avg_updates_per_object': 0
        }
    
    conn.close()
    return stats

def get_distinct_classifications():
    """Get all unique object classifications from the database"""
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT type 
            FROM tns_objects 
            WHERE type IS NOT NULL AND type != '' AND type != 'null'
            ORDER BY 
                CASE WHEN type = 'AT' THEN 0 ELSE 1 END,
                type
        """)
        
        results = cursor.fetchall()
        classifications = [row[0] for row in results if row[0] and row[0].strip()]
        
        # Ensure AT is always included and first
        if 'AT' not in classifications:
            classifications.insert(0, 'AT')
        
        # Remove duplicates while preserving order
        seen = set()
        unique_classifications = []
        for classification in classifications:
            if classification not in seen:
                seen.add(classification)
                unique_classifications.append(classification)
        
        return unique_classifications
        
    except Exception as e:
        print(f"Error getting distinct classifications: {e}")
        return ['AT', 'SN Ia', 'SN II', 'SN Ib/c']  # Default classifications
    finally:
        if 'conn' in locals():
            conn.close()

def update_object_status(object_name, new_status):
    """Update object status/tag in database with enhanced debugging and activity tracking"""
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        print(f"=== UPDATE STATUS DEBUG ===")
        print(f"Object name: '{object_name}'")
        print(f"New status: '{new_status}'")
        
        # Check columns and add missing ones
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
        
        # Find the object
        search_queries = [
            "SELECT name_prefix, name, tag FROM tns_objects WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?",
            "SELECT name_prefix, name, tag FROM tns_objects WHERE name = ?",
            "SELECT name_prefix, name, tag FROM tns_objects WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) LIKE ?"
        ]
        
        search_patterns = [object_name, object_name, f"%{object_name}%"]
        
        found_object = None
        for i, (query, pattern) in enumerate(zip(search_queries, search_patterns)):
            print(f"Search {i+1}: {query} with '{pattern}'")
            cursor.execute(query, (pattern,))
            result = cursor.fetchone()
            if result:
                found_object = result
                print(f"Found object: name_prefix='{result[0]}', name='{result[1]}', current_tag='{result[2]}'")
                break
        
        if not found_object:
            print("Object not found in database!")
            conn.close()
            return False
        
        # Update status and activity timestamp
        update_queries = [
            """UPDATE tns_objects 
               SET tag = ?, last_activity = CURRENT_TIMESTAMP 
               WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?""",
            """UPDATE tns_objects 
               SET tag = ?, last_activity = CURRENT_TIMESTAMP 
               WHERE name = ?"""
        ]
        
        update_patterns = [object_name, object_name]
        
        for i, (query, pattern) in enumerate(zip(update_queries, update_patterns)):
            print(f"Update attempt {i+1}: {query} with '{pattern}'")
            cursor.execute(query, (new_status, pattern))
            rows_affected = cursor.rowcount
            print(f"Rows affected: {rows_affected}")
            
            if rows_affected > 0:
                conn.commit()
                
                # Verification
                cursor.execute(
                    "SELECT tag, last_activity FROM tns_objects WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?",
                    (object_name,)
                )
                verification = cursor.fetchone()
                if verification:
                    print(f"Verification: new tag = '{verification[0]}', last_activity = '{verification[1]}'")
                
                conn.close()
                return True
        
        print("All update attempts failed!")
        conn.close()
        return False
        
    except Exception as e:
        print(f"Database error in update_object_status: {e}")
        import traceback
        traceback.print_exc()
        return False

def debug_search_objects(search_term):
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM tns_objects")
        total_count = cursor.fetchone()[0]
        print(f"Total objects in database: {total_count}")
        
        cursor.execute("PRAGMA table_info(tns_objects)")
        columns = cursor.fetchall()
        print(f"Database columns: {[col[1] for col in columns]}")
        
        cursor.execute("SELECT name_prefix, name, objid FROM tns_objects LIMIT 5")
        sample_objects = cursor.fetchall()
        print(f"Sample objects: {sample_objects}")
        
        search_queries = [
            ("Exact match (name_prefix + name)", "(name_prefix || name) = ?", [search_term]),
            ("Name only", "name = ?", [search_term]),
            ("objid match", "objid = ?", [search_term]),
            ("Partial match", "(name_prefix || name) LIKE ?", [f"%{search_term}%"]),
        ]
        
        for desc, query, params in search_queries:
            full_query = f"SELECT name_prefix, name, objid FROM tns_objects WHERE {query}"
            print(f"\n{desc}:")
            print(f"Query: {full_query}")
            print(f"Params: {params}")
            
            cursor.execute(full_query, params)
            results = cursor.fetchall()
            print(f"Results: {results}")
        
        conn.close()
        
    except Exception as e:
        print(f"Debug search error: {e}")
        import traceback
        traceback.print_exc()

def update_object_activity(object_name, activity_type="manual_update"):
    """
    Update the last_activity timestamp for an object
    
    Args:
        object_name (str): Name of the object to update
        activity_type (str): Type of activity (e.g., 'status_change', 'data_upload', 'manual_update')
    """
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        # Ensure last_activity column exists
        cursor.execute("PRAGMA table_info(tns_objects)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'last_activity' not in column_names:
            cursor.execute("ALTER TABLE tns_objects ADD COLUMN last_activity TEXT")
            conn.commit()
        
        # Update last_activity timestamp
        cursor.execute("""
            UPDATE tns_objects 
            SET last_activity = CURRENT_TIMESTAMP 
            WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = ?
        """, (object_name,))
        
        if cursor.rowcount > 0:
            conn.commit()
            print(f"Updated activity timestamp for {object_name} ({activity_type})")
            return True
        else:
            print(f"Object {object_name} not found for activity update")
            return False
        
        conn.close()
        
    except Exception as e:
        print(f"Error updating object activity: {e}")
        return False

def get_auto_snooze_stats():
    """Get statistics about auto-snoozed objects"""
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Check if auto_snoozed_at column exists
        cursor.execute("PRAGMA table_info(tns_objects)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'auto_snoozed_at' in column_names:
            # Count auto-snoozed objects
            cursor.execute("SELECT COUNT(*) FROM tns_objects WHERE auto_snoozed_at IS NOT NULL")
            stats['auto_snoozed_count'] = cursor.fetchone()[0]
            
            # Recent auto-snooze activity
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
            
            # Recent auto-unsnooze activity
            cursor.execute("""
                SELECT COUNT(*) FROM tns_objects 
                WHERE auto_unsnoozed_at > datetime('now', '-7 days')
            """)
            stats['auto_unsnoozed_last_week'] = cursor.fetchone()[0]
        else:
            stats['auto_unsnoozed_count'] = 0
            stats['auto_unsnoozed_last_week'] = 0
        
        # Objects that could be auto-snoozed soon (35-44 days inactive)
        from datetime import datetime, timedelta
        warning_date = (datetime.now() - timedelta(days=35)).isoformat()
        snooze_date = (datetime.now() - timedelta(days=45)).isoformat()
        
        cursor.execute("""
            SELECT COUNT(*) FROM tns_objects 
            WHERE (tag IS NULL OR tag = '' OR tag = 'object')
            AND updated_at < ? AND updated_at >= ?
        """, (warning_date, snooze_date))
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

def get_tag_statistics():
    """Get count of objects by tag/status"""
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COALESCE(tag, 'object') as tag_status,
                COUNT(*) as count
            FROM tns_objects 
            GROUP BY COALESCE(tag, 'object')
        ''')
        
        results = cursor.fetchall()
        conn.close()
        
        tag_counts = {}
        for tag, count in results:
            tag_counts[tag] = count
        
        for tag in ['object', 'followup', 'finished', 'snoozed']:
            if tag not in tag_counts:
                tag_counts[tag] = 0
        
        return tag_counts
        
    except Exception as e:
        print(f"Error getting tag statistics: {e}")
        return {
            'object': 0,
            'followup': 0,
            'finished': 0,
            'snoozed': 0
        }

def debug_object_tag(object_name):
    try:
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT name, name_prefix, tag, type, discoverydate 
            FROM tns_objects 
            WHERE name LIKE ? OR (name_prefix || name) = ?
        ''', (f'%{object_name}%', object_name))
        
        results = cursor.fetchall()
        conn.close()
        
        print(f"=== Debug object tag for '{object_name}' ===")
        for row in results:
            name, name_prefix, tag, obj_type, discovery_date = row
            full_name = (name_prefix or '') + name
            print(f"Full name: {full_name}")
            print(f"Name: {name}, Prefix: {name_prefix}")
            print(f"Tag: {tag}")
            print(f"Type: {obj_type}")
            print(f"Discovery date: {discovery_date}")
            print("---")
        
        return results
        
    except Exception as e:
        print(f"Error debugging object tag: {e}")
        return []