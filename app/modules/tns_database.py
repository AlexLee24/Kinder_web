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
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM tns_objects WHERE 1=1"
    params = []
    
    # Add filters
    if search_term:
        query += " AND (name LIKE ? OR name_prefix LIKE ? OR internal_names LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern, search_pattern])
    
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
        query += " AND tag = ?"
        params.append(tag)
    
    # Add sorting
    sort_column = sort_by if sort_by in ["discoverydate", "name", "type", "redshift", "discoverymag", "time_received"] else "discoverydate"
    sort_direction = "DESC" if sort_order.upper() == "DESC" else "ASC"
    query += f" ORDER BY {sort_column} {sort_direction}"
    
    # Add pagination
    query += " LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)
    
    cursor.execute(query, params)
    columns = [description[0] for description in cursor.description]
    results = []
    
    for row in cursor.fetchall():
        obj_dict = dict(zip(columns, row))
        results.append(obj_dict)
    
    conn.close()
    return results

def get_objects_count(search_term=None, object_type=None, tag=None, date_from=None, date_to=None):
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT COUNT(*) FROM tns_objects WHERE 1=1"
    params = []
    
    # Add the same filters as search_tns_objects
    if search_term:
        query += " AND (name LIKE ? OR name_prefix LIKE ? OR internal_names LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern, search_pattern])
    
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
        query += " AND tag = ?"
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