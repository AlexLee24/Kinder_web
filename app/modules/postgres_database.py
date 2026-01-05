import psycopg2
from psycopg2 import pool, extras
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

# Load PostgreSQL connection settings from .env
from dotenv import load_dotenv
# Use relative path to kinder.env (2 levels up from app/modules/)
basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '..', '..', 'kinder.env')
# Force reload of environment variables
load_dotenv(dotenv_path, override=True)

DB_HOST = os.getenv("PG_HOST", "localhost")
DB_PORT = os.getenv("PG_PORT", "5432")
DB_NAME = os.getenv("PG_DATABASE", "tns_data")
DB_USER = os.getenv("PG_USER", "postgres")
DB_PASSWORD = os.getenv("PG_PASSWORD", "")

print(f"DEBUG: Loaded DB Config - Host: {DB_HOST}, Port: {DB_PORT}, DB: {DB_NAME}")

# Connection pool for write optimization
connection_pool = None

def check_db_connection():
    """Check connection to PostgreSQL database and print status"""
    try:
        print(f"Attempting to connect to PostgreSQL at {DB_HOST}:{DB_PORT} (DB: {DB_NAME})...")
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        conn.close()
        print(f"[SUCCESS] Successfully connected to PostgreSQL database '{DB_NAME}' at {DB_HOST}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to connect to PostgreSQL database: {e}")
        return False

def init_connection_pool(minconn=2, maxconn=10):
    """Initialize PostgreSQL connection pool for write optimization"""
    global connection_pool
    if connection_pool is None:
        connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn,
            maxconn,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
    return connection_pool

@contextmanager
def get_db_connection():
    """Get connection from pool with context manager for auto-cleanup"""
    pool = init_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

# Compatibility alias for old code
def get_tns_db_connection():
    """Legacy function name - redirects to PostgreSQL connection pool
    Note: This returns a raw connection, not a context manager.
    Caller is responsible for closing the connection.
    """
    pool = init_connection_pool()
    return pool.getconn()

def get_tns_db_connection():
    """Compatibility wrapper for old SQLite-style connection calls (returns raw connection)"""
    pool = init_connection_pool()
    return pool.getconn()

def init_tns_database():
    """Initialize PostgreSQL database with all tables (TNS + object data)"""
    
    # First, create database if not exists
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database='postgres'
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'")
        if not cursor.fetchone():
            cursor.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"Created database: {DB_NAME}")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Database creation check: {e}")
    
    # Connect to target database and create tables
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # TNS Objects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tns_objects (
                objid INTEGER PRIMARY KEY,
                name_prefix TEXT,
                name TEXT NOT NULL UNIQUE,
                ra DOUBLE PRECISION,
                declination DOUBLE PRECISION,
                redshift DOUBLE PRECISION,
                typeid INTEGER,
                type TEXT,
                reporting_groupid INTEGER,
                reporting_group TEXT,
                source_groupid INTEGER,
                source_group TEXT,
                discoverydate TEXT,
                discoverymag DOUBLE PRECISION,
                discmagfilter TEXT,
                filter TEXT,
                reporters TEXT,
                time_received TEXT,
                internal_names TEXT,
                discovery_ads_bibcode TEXT,
                class_ads_bibcodes TEXT,
                creationdate TEXT,
                last_photometry_date TEXT,
                lastmodified TEXT,
                inbox INTEGER DEFAULT 1,
                snoozed INTEGER DEFAULT 0,
                follow INTEGER DEFAULT 0,
                finish_follow INTEGER DEFAULT 0,
                brightest_mag DOUBLE PRECISION,
                brightest_abs_mag DOUBLE PRECISION
            )
        ''')
        
        # Migration: Add columns if they don't exist (for existing tables)
        try:
            cursor.execute("ALTER TABLE tns_objects ADD COLUMN IF NOT EXISTS brightest_mag DOUBLE PRECISION")
            cursor.execute("ALTER TABLE tns_objects ADD COLUMN IF NOT EXISTS brightest_abs_mag DOUBLE PRECISION")
        except Exception as e:
            print(f"Migration note: {e}")
        
        # Photometry table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photometry (
                id SERIAL PRIMARY KEY,
                object_name TEXT NOT NULL,
                mjd DOUBLE PRECISION NOT NULL,
                magnitude DOUBLE PRECISION,
                magnitude_error DOUBLE PRECISION,
                filter TEXT,
                telescope TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_name) REFERENCES tns_objects(name) ON DELETE CASCADE
            )
        ''')
        
        # Spectroscopy table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spectroscopy (
                id SERIAL PRIMARY KEY,
                object_name TEXT NOT NULL,
                wavelength DOUBLE PRECISION NOT NULL,
                intensity DOUBLE PRECISION NOT NULL,
                phase DOUBLE PRECISION,
                telescope TEXT,
                spectrum_id TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_name) REFERENCES tns_objects(name) ON DELETE CASCADE
            )
        ''')
        
        # Comments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                object_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                user_name TEXT NOT NULL,
                user_picture TEXT,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_name) REFERENCES tns_objects(name) ON DELETE CASCADE
            )
        ''')
        
        # Download log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tns_download_log (
                id SERIAL PRIMARY KEY,
                download_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                hour_utc TEXT,
                filename TEXT,
                records_imported INTEGER DEFAULT 0,
                records_updated INTEGER DEFAULT 0,
                status TEXT,
                error_message TEXT,
                completed_at TIMESTAMP WITH TIME ZONE
            )
        ''')

        # Custom Targets table (User defined targets)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_targets (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                ra TEXT NOT NULL,
                declination TEXT NOT NULL,
                mag TEXT,
                priority TEXT DEFAULT 'Normal',
                note TEXT,
                is_auto_exposure BOOLEAN DEFAULT TRUE,
                filters TEXT,
                exposures TEXT,
                counts TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migration: Add columns if they don't exist (for existing tables)
        try:
            cursor.execute("ALTER TABLE custom_targets ADD COLUMN IF NOT EXISTS is_auto_exposure BOOLEAN DEFAULT TRUE")
            cursor.execute("ALTER TABLE custom_targets ADD COLUMN IF NOT EXISTS filters TEXT")
            cursor.execute("ALTER TABLE custom_targets ADD COLUMN IF NOT EXISTS exposures TEXT")
            cursor.execute("ALTER TABLE custom_targets ADD COLUMN IF NOT EXISTS counts TEXT")
        except Exception as e:
            print(f"Migration note: {e}")
        
        # Create indexes for TNS objects
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_objid ON tns_objects(objid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_name ON tns_objects(name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_discoverydate ON tns_objects(discoverydate)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_type ON tns_objects(type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_inbox ON tns_objects(inbox)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_snoozed ON tns_objects(snoozed)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tns_last_photometry ON tns_objects(last_photometry_date)')
        
        # Create indexes for photometry
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photometry_object ON photometry(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photometry_mjd ON photometry(mjd)')
        
        # Create indexes for spectroscopy
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spectroscopy_object ON spectroscopy(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spectroscopy_spectrum_id ON spectroscopy(spectrum_id)')
        
        # Create indexes for comments
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_object ON comments(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(created_at)')
        
        # Cross Match Results table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cross_match_results (
                id SERIAL PRIMARY KEY,
                target_name TEXT NOT NULL,
                catalog_name TEXT NOT NULL,
                match_data TEXT,
                separation_arcsec DOUBLE PRECISION,
                is_host BOOLEAN DEFAULT FALSE,
                flag BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (target_name) REFERENCES tns_objects(name) ON DELETE CASCADE
            )
        ''')
        
        # Check if is_host column exists, if not add it
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='cross_match_results' AND column_name='is_host'
        """)
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE cross_match_results ADD COLUMN is_host BOOLEAN DEFAULT FALSE')

        # Check if updated_at column exists, if not add it
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='cross_match_results' AND column_name='updated_at'
        """)
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE cross_match_results ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP')
            
        # Target Images table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS target_images (
                id SERIAL PRIMARY KEY,
                target_name TEXT NOT NULL UNIQUE,
                image_data BYTEA NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (target_name) REFERENCES tns_objects(name) ON DELETE CASCADE
            )
        ''')
        
        # Create indexes for cross match results
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cm_target ON cross_match_results(target_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cm_created ON cross_match_results(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cm_flag ON cross_match_results(flag)')
        
        conn.commit()
        cursor.close()
        
    print("PostgreSQL database initialized with all tables")

def log_download_attempt(hour_utc, filename=""):
    """Log a download attempt to database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tns_download_log (hour_utc, filename, status)
            VALUES (%s, %s, %s)
            RETURNING id
        ''', (hour_utc, filename, 'in_progress'))
        
        log_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        
    return log_id

def update_download_log(log_id, status, records_imported=0, records_updated=0, error_message=None):
    """Update download log with completion status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE tns_download_log
            SET status = %s, 
                records_imported = %s, 
                records_updated = %s, 
                error_message = %s,
                completed_at = %s
            WHERE id = %s
        ''', (status, records_imported, records_updated, error_message, 
              datetime.now(timezone.utc), log_id))
        
        conn.commit()
        cursor.close()

# Object Data functions
class TNSObjectDB:
    """Unified database class for TNS objects and associated data"""
    
    @staticmethod
    def add_photometry_point(object_name, mjd, magnitude=None, magnitude_error=None, 
                           filter_name=None, telescope=None):
        """Add single photometry point"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO photometry (object_name, mjd, magnitude, magnitude_error, filter, telescope)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (object_name, mjd, magnitude, magnitude_error, filter_name, telescope))
            
            point_id = cursor.fetchone()[0]
            
            # Update object's last_photometry_date if this point is newer
            # MJD 40587 is 1970-01-01. Convert MJD to Unix timestamp (seconds)
            cursor.execute('''
                UPDATE tns_objects 
                SET last_photometry_date = to_timestamp((%s - 40587) * 86400)
                WHERE ((COALESCE(name_prefix, '') || COALESCE(name, '')) = %s OR name = %s)
                AND (last_photometry_date IS NULL OR last_photometry_date::timestamp < to_timestamp((%s - 40587) * 86400))
            ''', (mjd, object_name, object_name, mjd))
            
            conn.commit()
            cursor.close()
            
        return point_id
    
    @staticmethod
    def sync_last_photometry_date(object_name):
        """Recalculate and update last_photometry_date based on photometry data"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get max MJD
            cursor.execute('SELECT MAX(mjd) FROM photometry WHERE object_name = %s', (object_name,))
            result = cursor.fetchone()
            max_mjd = result[0] if result and result[0] is not None else None
            
            if max_mjd:
                # Update with max MJD
                cursor.execute('''
                    UPDATE tns_objects 
                    SET last_photometry_date = to_timestamp((%s - 40587) * 86400)
                    WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
                       OR name = %s
                ''', (max_mjd, object_name, object_name))
            else:
                # No photometry, set to NULL
                cursor.execute('''
                    UPDATE tns_objects 
                    SET last_photometry_date = NULL
                    WHERE (COALESCE(name_prefix, '') || COALESCE(name, '')) = %s
                       OR name = %s
                ''', (object_name, object_name))
                
            conn.commit()
            cursor.close()

    @staticmethod
    def add_photometry_bulk(photometry_data):
        """Bulk insert photometry data for write optimization"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Use execute_batch for optimized bulk insert
            extras.execute_batch(cursor, '''
                INSERT INTO photometry (object_name, mjd, magnitude, magnitude_error, filter, telescope)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', photometry_data, page_size=1000)
            
            conn.commit()
            cursor.close()
    
    @staticmethod
    def add_spectrum_data(object_name, wavelength_data, intensity_data, 
                         phase=None, telescope=None, spectrum_id=None):
        """Add spectrum data"""
        if spectrum_id is None:
            spectrum_id = f"{object_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Prepare bulk data
        spectrum_points = [
            (object_name, wavelength, intensity, phase, telescope, spectrum_id)
            for wavelength, intensity in zip(wavelength_data, intensity_data)
        ]
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Bulk insert with execute_batch
            extras.execute_batch(cursor, '''
                INSERT INTO spectroscopy (object_name, wavelength, intensity, phase, telescope, spectrum_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', spectrum_points, page_size=1000)
            
            conn.commit()
            cursor.close()
            
        return spectrum_id
    
    @staticmethod
    def get_photometry(object_name):
        """Get all photometry for an object"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT * FROM photometry 
                WHERE object_name = %s 
                ORDER BY mjd ASC
            ''', (object_name,))
            
            results = cursor.fetchall()
            cursor.close()
            
        return [dict(row) for row in results]
    
    @staticmethod
    def get_spectroscopy(object_name):
        """Get all spectroscopy for an object"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT * FROM spectroscopy 
                WHERE object_name = %s 
                ORDER BY spectrum_id, wavelength ASC
            ''', (object_name,))
            
            results = cursor.fetchall()
            cursor.close()
            
        return [dict(row) for row in results]
    
    @staticmethod
    def get_spectrum_list(object_name):
        """Get list of available spectra for an object"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT DISTINCT spectrum_id, telescope, phase, 
                       MIN(wavelength) as min_wavelength, MAX(wavelength) as max_wavelength,
                       COUNT(*) as point_count, MIN(created_at) as observation_date
                FROM spectroscopy 
                WHERE object_name = %s 
                GROUP BY spectrum_id, telescope, phase
                ORDER BY observation_date DESC
            ''', (object_name,))
            
            results = cursor.fetchall()
            cursor.close()
            
        return [dict(row) for row in results]
    
    @staticmethod
    def get_object_details(object_name):
        """Get details for a TNS object"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT name, ra, declination, discoverydate, internal_names, type, redshift
                FROM tns_objects 
                WHERE name = %s
            ''', (object_name,))
            
            result = cursor.fetchone()
            cursor.close()
            
        if result:
            return dict(result)
        return None

    @staticmethod
    def delete_photometry_point(point_id):
        """Delete photometry point"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM photometry WHERE id = %s', (point_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            cursor.close()
            
        return deleted
    
    @staticmethod
    def delete_spectrum(spectrum_id):
        """Delete spectrum"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM spectroscopy WHERE spectrum_id = %s', (spectrum_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            cursor.close()
            
        return deleted
    
    @staticmethod
    def add_comment(object_name, user_email, user_name, user_picture, content):
        """Add comment"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO comments (object_name, user_email, user_name, user_picture, content)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (object_name, user_email, user_name, user_picture, content))
            
            comment_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
        return comment_id
    
    @staticmethod
    def get_comments(object_name):
        """Get all comments for an object"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT id, object_name, user_email, user_name, user_picture, content, created_at
                FROM comments 
                WHERE object_name = %s 
                ORDER BY created_at ASC
            ''', (object_name,))
            
            results = cursor.fetchall()
            cursor.close()
            
        # Convert datetime to ISO string
        comments = []
        for row in results:
            comment = dict(row)
            if comment.get('created_at'):
                comment['created_at'] = comment['created_at'].isoformat()
            comments.append(comment)
            
        return comments
    
    @staticmethod
    def delete_comment(comment_id):
        """Delete comment"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM comments WHERE id = %s', (comment_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            cursor.close()
            
        return deleted
    
    @staticmethod
    def get_comment_by_id(comment_id):
        """Get specific comment by ID"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            
            cursor.execute('''
                SELECT id, object_name, user_email, user_name, user_picture, content, created_at
                FROM comments 
                WHERE id = %s
            ''', (comment_id,))
            
            result = cursor.fetchone()
            cursor.close()
            
        if result:
            comment = dict(result)
            if comment.get('created_at'):
                comment['created_at'] = comment['created_at'].isoformat()
            return comment
        return None

# Global instance
tns_object_db = TNSObjectDB()

# TNS Query Functions for Marshal
def get_objects_count(object_type=None, search_term='', tag=None, date_from=None, date_to=None,
                     app_mag_min=None, app_mag_max=None, redshift_min=None, redshift_max=None, discoverer=None,
                     brightest_mag_min=None, brightest_mag_max=None,
                     brightest_abs_mag_min=None, brightest_abs_mag_max=None):
    """Get count of objects matching filters"""
    
    query = 'SELECT COUNT(*) FROM tns_objects WHERE 1=1'
    params = []
    
    # Search term filter
    if search_term:
        query += ' AND (name ILIKE %s OR name_prefix || name ILIKE %s)'
        search_pattern = f'%{search_term}%'
        params.extend([search_pattern, search_pattern])
    
    # Object type filter
    if object_type:
        if object_type == 'AT':
            query += " AND name_prefix = 'AT'"
        elif object_type == 'Classified':
            query += " AND name_prefix != 'AT'"
        else:
            query += ' AND type = %s'
            params.append(object_type)
    
    # Tag filter
    if tag:
        if tag == 'object':
            query += ' AND inbox = 1 AND snoozed = 0'
        elif tag == 'followup':
            query += ' AND follow = 1 AND finish_follow = 0'
        elif tag == 'finished':
            query += ' AND finish_follow = 1'
        elif tag == 'snoozed':
            query += ' AND snoozed = 1'
    
    # Date range filter
    if date_from:
        query += ' AND discoverydate >= %s'
        params.append(date_from)
    if date_to:
        query += ' AND discoverydate <= %s'
        params.append(date_to)
    
    # Magnitude range filter
    if app_mag_min is not None:
        query += ' AND discoverymag >= %s'
        params.append(app_mag_min)
    if app_mag_max is not None:
        query += ' AND discoverymag <= %s'
        params.append(app_mag_max)
    
    # Redshift range filter
    if redshift_min is not None:
        query += ' AND redshift >= %s'
        params.append(redshift_min)
    if redshift_max is not None:
        query += ' AND redshift <= %s'
        params.append(redshift_max)
    
    # Discoverer filter
    if discoverer:
        query += ' AND (source_group ILIKE %s OR reporting_group ILIKE %s OR reporters ILIKE %s)'
        discoverer_pattern = f'%{discoverer}%'
        params.extend([discoverer_pattern, discoverer_pattern, discoverer_pattern])

    # Brightest Mag filter
    if brightest_mag_min is not None:
        query += ' AND brightest_mag >= %s'
        params.append(brightest_mag_min)
    if brightest_mag_max is not None:
        query += ' AND brightest_mag <= %s'
        params.append(brightest_mag_max)

    # Brightest Abs Mag filter
    if brightest_abs_mag_min is not None:
        query += ' AND brightest_abs_mag >= %s'
        params.append(brightest_abs_mag_min)
    if brightest_abs_mag_max is not None:
        query += ' AND brightest_abs_mag <= %s'
        params.append(brightest_abs_mag_max)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        cursor.close()
        
    return count

def get_tag_statistics():
    """Get statistics for each tag"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        stats = {
            'object': 0,     # inbox=1, snoozed=0
            'followup': 0,   # follow=1, finish_follow=0
            'finished': 0,   # finish_follow=1
            'snoozed': 0     # snoozed=1
        }
        
        # Inbox count
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE inbox = 1 AND snoozed = 0')
        stats['object'] = cursor.fetchone()[0]
        
        # Follow-up count
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE follow = 1 AND finish_follow = 0')
        stats['followup'] = cursor.fetchone()[0]
        
        # Finished count
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE finish_follow = 1')
        stats['finished'] = cursor.fetchone()[0]
        
        # Snoozed count
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE snoozed = 1')
        stats['snoozed'] = cursor.fetchone()[0]
        
        cursor.close()
        
    return stats

def get_tns_statistics():
    """Get TNS download and import statistics"""
    stats = {
        'recent_downloads': [],
        'total_imports': 0,
        'total_updates': 0
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=extras.DictCursor)
        
        # Get recent downloads
        cursor.execute('''
            SELECT 
                download_time::text as download_time,
                hour_utc,
                filename,
                records_imported as imported_count,
                records_updated as updated_count,
                status,
                error_message
            FROM tns_download_log
            ORDER BY download_time DESC
            LIMIT 10
        ''')
        
        stats['recent_downloads'] = [dict(row) for row in cursor.fetchall()]
        
        # Get totals
        cursor.execute('SELECT COALESCE(SUM(records_imported), 0), COALESCE(SUM(records_updated), 0) FROM tns_download_log')
        row = cursor.fetchone()
        stats['total_imports'] = row[0]
        stats['total_updates'] = row[1]
        
        cursor.close()
        
    return stats

def search_tns_objects(search_term='', object_type='', limit=100, offset=0, sort_by='discoverydate', sort_order='desc', 
                       date_from=None, date_to=None, mag_min=None, mag_max=None, 
                       app_mag_min=None, app_mag_max=None,
                       redshift_min=None, redshift_max=None, discoverer=None, tag=None,
                       brightest_mag_min=None, brightest_mag_max=None,
                       brightest_abs_mag_min=None, brightest_abs_mag_max=None):
    """Search TNS objects with various filters"""
    
    query = '''
        SELECT 
            objid, name_prefix, name, ra, declination, redshift, typeid, type,
            reporting_groupid, reporting_group, source_groupid, source_group,
            discoverydate, discoverymag, discmagfilter, filter, reporters,
            time_received, internal_names, discovery_ads_bibcode, class_ads_bibcodes,
            creationdate, last_photometry_date, lastmodified, brightest_mag, brightest_abs_mag,
            CASE 
                WHEN finish_follow = 1 THEN 'finished'
                WHEN follow = 1 THEN 'followup'
                WHEN snoozed = 1 THEN 'snoozed'
                ELSE 'object'
            END as tag
        FROM tns_objects
        WHERE 1=1
    '''
    
    params = []
    
    # Search term filter
    if search_term:
        query += ' AND (name ILIKE %s OR name_prefix || name ILIKE %s)'
        search_pattern = f'%{search_term}%'
        params.extend([search_pattern, search_pattern])
    
    # Object type filter
    if object_type:
        if object_type == 'AT':
            query += " AND name_prefix = 'AT'"
        elif object_type == 'Classified':
            query += " AND name_prefix != 'AT'"
        else:
            query += ' AND type = %s'
            params.append(object_type)
    
    # Date range filter
    if date_from:
        query += ' AND discoverydate >= %s'
        params.append(date_from)
    if date_to:
        query += ' AND discoverydate <= %s'
        params.append(date_to)
    
    # Magnitude range filter (support both mag_min/mag_max and app_mag_min/app_mag_max)
    mag_min_val = app_mag_min if app_mag_min is not None else mag_min
    mag_max_val = app_mag_max if app_mag_max is not None else mag_max
    
    if mag_min_val is not None:
        query += ' AND discoverymag >= %s'
        params.append(mag_min_val)
    if mag_max_val is not None:
        query += ' AND discoverymag <= %s'
        params.append(mag_max_val)
    
    # Redshift range filter
    if redshift_min is not None:
        query += ' AND redshift >= %s'
        params.append(redshift_min)
    if redshift_max is not None:
        query += ' AND redshift <= %s'
        params.append(redshift_max)
    
    # Discoverer filter
    if discoverer:
        query += ' AND (source_group ILIKE %s OR reporting_group ILIKE %s OR reporters ILIKE %s)'
        discoverer_pattern = f'%{discoverer}%'
        params.extend([discoverer_pattern, discoverer_pattern, discoverer_pattern])
    
    # Brightest Mag filter
    if brightest_mag_min is not None:
        query += ' AND brightest_mag >= %s'
        params.append(brightest_mag_min)
    if brightest_mag_max is not None:
        query += ' AND brightest_mag <= %s'
        params.append(brightest_mag_max)

    # Brightest Abs Mag filter
    if brightest_abs_mag_min is not None:
        query += ' AND brightest_abs_mag >= %s'
        params.append(brightest_abs_mag_min)
    if brightest_abs_mag_max is not None:
        query += ' AND brightest_abs_mag <= %s'
        params.append(brightest_abs_mag_max)
    
    # Tag filter
    if tag:
        if tag == 'object':
            query += ' AND inbox = 1 AND snoozed = 0'
        elif tag == 'followup':
            query += ' AND follow = 1 AND finish_follow = 0'
        elif tag == 'finished':
            query += ' AND finish_follow = 1'
        elif tag == 'snoozed':
            query += ' AND snoozed = 1'
    
    # Sorting
    valid_sort_columns = ['discoverydate', 'lastmodified', 'discoverymag', 'name', 'time_received', 'last_photometry_date', 'brightest_mag', 'brightest_abs_mag']
    
    if sort_by == 'last_photometry_date':
        sort_direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
        query += f' ORDER BY COALESCE(last_photometry_date, lastmodified) {sort_direction} NULLS LAST'
    elif sort_by in valid_sort_columns:
        sort_direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
        query += f' ORDER BY {sort_by} {sort_direction} NULLS LAST'
    else:
        query += ' ORDER BY discoverydate DESC NULLS LAST'
    
    # Limit and Offset
    query += ' LIMIT %s OFFSET %s'
    params.append(limit)
    params.append(offset)
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=extras.DictCursor)
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        
    return results

def get_filtered_stats(search_term='', object_type='', tag=None, date_from=None, date_to=None,
                      app_mag_min=None, app_mag_max=None, redshift_min=None, redshift_max=None, discoverer=None):
    """Get statistics based on filters"""
    
    # Build base query with filters
    base_query = 'SELECT COUNT(*) FROM tns_objects WHERE 1=1'
    base_params = []
    
    # Apply same filters as search_tns_objects
    if search_term:
        base_query += ' AND (name ILIKE %s OR name_prefix || name ILIKE %s)'
        search_pattern = f'%{search_term}%'
        base_params.extend([search_pattern, search_pattern])
    
    if object_type:
        if object_type == 'AT':
            base_query += " AND name_prefix = 'AT'"
        elif object_type == 'Classified':
            base_query += " AND name_prefix != 'AT'"
        else:
            base_query += ' AND type = %s'
            base_params.append(object_type)
    
    if date_from:
        base_query += ' AND discoverydate >= %s'
        base_params.append(date_from)
    if date_to:
        base_query += ' AND discoverydate <= %s'
        base_params.append(date_to)
    
    if app_mag_min is not None:
        base_query += ' AND discoverymag >= %s'
        base_params.append(app_mag_min)
    if app_mag_max is not None:
        base_query += ' AND discoverymag <= %s'
        base_params.append(app_mag_max)
    
    if redshift_min is not None:
        base_query += ' AND redshift >= %s'
        base_params.append(redshift_min)
    if redshift_max is not None:
        base_query += ' AND redshift <= %s'
        base_params.append(redshift_max)
    
    if discoverer:
        base_query += ' AND (source_group ILIKE %s OR reporting_group ILIKE %s OR reporters ILIKE %s)'
        discoverer_pattern = f'%{discoverer}%'
        base_params.extend([discoverer_pattern, discoverer_pattern, discoverer_pattern])
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        stats = {
            'inbox_count': 0,
            'followup_count': 0,
            'finished_count': 0,
            'snoozed_count': 0
        }
        
        # If no tag filter, get counts for all tags
        if not tag:
            # Inbox count
            query = base_query + ' AND inbox = 1 AND snoozed = 0'
            cursor.execute(query, base_params)
            stats['inbox_count'] = cursor.fetchone()[0]
            
            # Follow-up count
            query = base_query + ' AND follow = 1 AND finish_follow = 0'
            cursor.execute(query, base_params)
            stats['followup_count'] = cursor.fetchone()[0]
            
            # Finished count
            query = base_query + ' AND finish_follow = 1'
            cursor.execute(query, base_params)
            stats['finished_count'] = cursor.fetchone()[0]
            
            # Snoozed count
            query = base_query + ' AND snoozed = 1'
            cursor.execute(query, base_params)
            stats['snoozed_count'] = cursor.fetchone()[0]
        else:
            # Get count for specific tag
            if tag == 'object':
                query = base_query + ' AND inbox = 1 AND snoozed = 0'
                cursor.execute(query, base_params)
                stats['inbox_count'] = cursor.fetchone()[0]
            elif tag == 'followup':
                query = base_query + ' AND follow = 1 AND finish_follow = 0'
                cursor.execute(query, base_params)
                stats['followup_count'] = cursor.fetchone()[0]
            elif tag == 'finished':
                query = base_query + ' AND finish_follow = 1'
                cursor.execute(query, base_params)
                stats['finished_count'] = cursor.fetchone()[0]
            elif tag == 'snoozed':
                query = base_query + ' AND snoozed = 1'
                cursor.execute(query, base_params)
                stats['snoozed_count'] = cursor.fetchone()[0]
        
        cursor.close()
        
    return stats

def get_distinct_classifications():
    """Get list of distinct object classifications"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT type 
            FROM tns_objects 
            WHERE type IS NOT NULL AND type != ''
            ORDER BY type
        ''')
        
        classifications = [row[0] for row in cursor.fetchall()]
        cursor.close()
        
    return classifications

def update_object_status(object_name, status):
    """
    Update object status flags based on the status string.
    
    Logic:
    - 'snoozed': snoozed=1, inbox=0, follow=0. If follow was 1, finish_follow=1.
    - 'finished': finish_follow=1, follow=0.
    - 'followup': follow=1, snoozed=0, finish_follow=0, inbox=1.
    - 'object' (Inbox): inbox=1, snoozed=0.
    """
    query = None
    
    if status == 'snoozed':
        query = """
            UPDATE tns_objects 
            SET 
                finish_follow = CASE WHEN follow = 1 THEN 1 ELSE finish_follow END,
                snoozed = 1,
                inbox = 0,
                follow = 0
            WHERE name = %s
        """
    elif status == 'finished':
        query = """
            UPDATE tns_objects 
            SET 
                finish_follow = 1,
                follow = 0
            WHERE name = %s
        """
    elif status == 'followup':
        query = """
            UPDATE tns_objects 
            SET 
                follow = 1,
                snoozed = 0,
                finish_follow = 0,
                inbox = 1
            WHERE name = %s
        """
    elif status == 'object': # Inbox
        query = """
            UPDATE tns_objects 
            SET 
                inbox = 1,
                snoozed = 0
            WHERE name = %s
        """
    elif status == 'clear':
        query = """
            UPDATE tns_objects 
            SET 
                follow = 0,
                finish_follow = 0
            WHERE name = %s
        """
    
    if not query:
        return False
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            print(f"DEBUG: Updating status for object '{object_name}' to '{status}'") # Debug print
            cursor.execute(query, (object_name,))
            row_count = cursor.rowcount
            conn.commit()
            cursor.close()
            
            if row_count == 0:
                print(f"DEBUG: No rows updated for object '{object_name}'. Trying case-insensitive match.")
                # Fallback 1: Try case-insensitive match on name
                query_insensitive = query.replace("WHERE name = %s", "WHERE name ILIKE %s")
                with get_db_connection() as conn2:
                    cursor2 = conn2.cursor()
                    cursor2.execute(query_insensitive, (object_name,))
                    row_count = cursor2.rowcount
                    conn2.commit()
                    cursor2.close()
            
            if row_count == 0:
                print(f"DEBUG: Still no rows updated. Trying full name match (prefix + name).")
                # Fallback 2: Try matching concatenation of name_prefix and name
                query_fullname = query.replace("WHERE name = %s", "WHERE (COALESCE(name_prefix, '') || name) ILIKE %s")
                with get_db_connection() as conn3:
                    cursor3 = conn3.cursor()
                    cursor3.execute(query_fullname, (object_name,))
                    row_count = cursor3.rowcount
                    conn3.commit()
                    cursor3.close()
            
            print(f"DEBUG: Rows updated: {row_count}")
            return row_count > 0
    except Exception as e:
        print(f"Error updating status: {e}")
        return False

def update_object_activity(objid, activity_type=None):
    """Update object activity timestamp (compatibility function)"""
    # PostgreSQL automatically updates timestamps if configured
    return True

def get_auto_snooze_stats():
    """Get auto-snooze statistics"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        stats = {
            'snoozed_count': 0,
            'finished_count': 0
        }
        
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE snoozed = 1')
        stats['snoozed_count'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM tns_objects WHERE finish_follow = 1')
        stats['finished_count'] = cursor.fetchone()[0]
        
        cursor.close()
        
    return stats

def get_available_dates():
    """Get list of dates that have cross match results"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT created_at::date as date 
                FROM cross_match_results 
                ORDER BY date DESC
            """)
            dates = [row[0].strftime('%Y-%m-%d') for row in cur.fetchall()]
            cur.close()
            return dates
    except Exception as e:
        print(f"Error getting available dates: {e}")
        return []

def get_cross_match_results(limit=1000, date=None):
    """Get cross match results from database"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            
            # Check if flag column exists, if not add it
            try:
                cur.execute("SELECT flag FROM cross_match_results LIMIT 1")
            except psycopg2.Error:
                conn.rollback()
                cur.execute("ALTER TABLE cross_match_results ADD COLUMN flag BOOLEAN DEFAULT FALSE")
                conn.commit()
            
            query = "SELECT * FROM cross_match_results"
            params = []
            
            if date:
                query += " WHERE created_at::date = %s"
                params.append(date)
                
            query += " ORDER BY created_at DESC"
            
            if limit and not date: # Only apply limit if no date is specified (show all for a specific date)
                query += " LIMIT %s"
                params.append(limit)
                
            cur.execute(query, tuple(params))
            results = cur.fetchall()
            cur.close()
            return results
    except Exception as e:
        print(f"Error getting cross match results: {e}")
        return []

def update_cross_match_flag(result_id, flag_value):
    """Update flag status for a cross match result"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE cross_match_results 
                SET flag = %s 
                WHERE id = %s
            """, (flag_value, result_id))
            conn.commit()
            cur.close()
            return True
    except Exception as e:
        print(f"Error updating flag: {e}")
        return False

def save_flag_objects(flag_list):
    """
    Save flagged objects to database.
    flag_list: list of [name_prefix, name, ra, declination, discoverydate, internal_names]
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            count = 0
            for item in flag_list:
                # item structure: ['name_prefix', 'name', 'ra', 'declination', 'discoverydate', 'internal_names']
                if len(item) < 2:
                    continue
                    
                name = item[1]
                
                # Check if object exists in cross_match_results
                cur.execute("SELECT id FROM cross_match_results WHERE target_name = %s", (name,))
                results = cur.fetchall()
                
                if results:
                    # Update existing matches to be flagged
                    cur.execute("UPDATE cross_match_results SET flag = TRUE WHERE target_name = %s", (name,))
                    count += 1
                else:
                    # Insert a new record indicating it's a flagged object
                    # We use a special catalog name 'FLAGGED_LIST'
                    # Check if it exists in tns_objects
                    cur.execute("SELECT 1 FROM tns_objects WHERE name = %s", (name,))
                    if cur.fetchone():
                        cur.execute("""
                            INSERT INTO cross_match_results 
                            (target_name, catalog_name, match_data, separation_arcsec, flag)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (name, 'FLAGGED_LIST', '{}', 0, True))
                        count += 1
                    else:
                        # If not in tns_objects, we might want to insert it?
                        # But we need more data. For now, just skip and log.
                        print(f"Warning: Flagged object {name} not found in tns_objects. Skipping.")
            
            conn.commit()
            print(f"Processed {len(flag_list)} flagged objects. Updated/Inserted {count} records.")
            
    except Exception as e:
        print(f"Error saving flag objects: {e}")

import json

def save_cross_match_results(results_list):
    """
    Save cross match results to database.
    results_list: list of dictionaries containing match data.
    Each dict must have: 'tns_name', 'is_Host', and match details.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            count = 0
            for result in results_list:
                target_name = result.get('tns_name')
                if not target_name:
                    continue
                
                # Determine catalog name
                if 'lens_catalog' in result:
                    catalog_name = f"Lens_{result['lens_catalog']}"
                else:
                    catalog_name = 'DESI'
                
                separation = float(result.get('separation_arcsec', 0))
                is_host = result.get('is_Host', False)
                
                # Prepare match_data (remove TNS fields to avoid duplication)
                match_data = result.copy()
                tns_fields = ['tns_name_prefix', 'tns_name', 'tns_ra', 'tns_dec', 
                              'tns_discoverydate', 'tns_internal_names', 'lens_catalog']
                for field in tns_fields:
                    match_data.pop(field, None)
                
                # Check if this specific match already exists (to avoid duplicates on re-run)
                # We use separation as a proxy for uniqueness
                # Removed date check to avoid duplicates when processing overlapping days (e.g. past 3 days)
                check_query = """
                    SELECT id FROM cross_match_results 
                    WHERE target_name = %s 
                    AND catalog_name = %s 
                    AND abs(separation_arcsec - %s) < 0.0001
                """
                cur.execute(check_query, (target_name, catalog_name, separation))
                existing_id = cur.fetchone()
                
                if existing_id:
                    # Update the existing record
                    update_query = """
                        UPDATE cross_match_results
                        SET match_data = %s,
                            is_host = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """
                    cur.execute(update_query, (json.dumps(match_data, default=str), is_host, existing_id[0]))
                else:
                    insert_query = """
                        INSERT INTO cross_match_results 
                        (target_name, catalog_name, match_data, separation_arcsec, is_host)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    cur.execute(insert_query, (
                        target_name, 
                        catalog_name, 
                        json.dumps(match_data, default=str), 
                        separation,
                        is_host
                    ))
                count += 1
            
            conn.commit()
            print(f"Saved {count} cross match results to database.")
            
    except Exception as e:
        print(f"Error saving cross match results: {e}")

def save_target_image(target_name, image_data):
    """
    Save target image to database.
    image_data: bytes
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check if image exists
            cur.execute("SELECT id FROM target_images WHERE target_name = %s", (target_name,))
            existing = cur.fetchone()
            
            if existing:
                cur.execute("""
                    UPDATE target_images 
                    SET image_data = %s, updated_at = CURRENT_TIMESTAMP 
                    WHERE target_name = %s
                """, (image_data, target_name))
            else:
                cur.execute("""
                    INSERT INTO target_images (target_name, image_data) 
                    VALUES (%s, %s)
                """, (target_name, image_data))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error saving target image for {target_name}: {e}")
        return False

def get_target_image(target_name):
    """
    Get target image from database.
    Returns bytes or None.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT image_data FROM target_images WHERE target_name = %s", (target_name,))
            result = cur.fetchone()
            if result:
                return result[0] # Return bytes
            return None
    except Exception as e:
        print(f"Error getting target image for {target_name}: {e}")
        return None

def set_cross_match_host(match_id, target_name):
    """
    Set a specific match as host for a target.
    Sets is_host=True for match_id, and False for all other matches of this target.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Reset all matches for this target to False
            cur.execute("""
                UPDATE cross_match_results 
                SET is_host = FALSE 
                WHERE target_name = %s
            """, (target_name,))
            
            # Set selected match to True
            cur.execute("""
                UPDATE cross_match_results 
                SET is_host = TRUE 
                WHERE id = %s
            """, (match_id,))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error setting host for {target_name}: {e}")
        return False

def unset_cross_match_host(target_name):
    """
    Unset host for a target (set is_host=False for all matches).
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE cross_match_results 
                SET is_host = FALSE 
                WHERE target_name = %s
            """, (target_name,))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error unsetting host for {target_name}: {e}")
        return False

def update_object_abs_mag(target_name):
    """
    Recalculate and update brightest_abs_mag for an object based on its current redshift and brightest_mag.
    """
    print(f"DEBUG: update_object_abs_mag called for {target_name}")
    try:
        # Try relative import first (for module usage)
        from . import ext_M_calculator
    except ImportError:
        try:
            # Try absolute import (for script usage)
            import modules.ext_M_calculator as ext_M_calculator
        except ImportError:
            print("Could not import ext_M_calculator")
            return False

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 0. Resolve canonical name
            # Try exact match on name, or prefix+name, or case-insensitive match
            cur.execute("""
                SELECT name, name_prefix, redshift, ra, declination, discmagfilter
                FROM tns_objects 
                WHERE name = %s 
                   OR (COALESCE(name_prefix, '') || name) = %s
                   OR name ILIKE %s
                LIMIT 1
            """, (target_name, target_name, target_name))
            obj = cur.fetchone()
            
            if not obj:
                print(f"DEBUG: Object {target_name} not found in tns_objects")
                return False
                
            canonical_name = obj['name']
            print(f"DEBUG: Resolved {target_name} to canonical name {canonical_name}")
            
            # 1. Always recalculate brightest_mag from photometry
            # Fetch all photometry to handle potential text/mixed types in magnitude column
            # Query for both canonical name and input name to be safe
            possible_names = [canonical_name, target_name]
            # Also try name without prefix if it exists (e.g. AT2025wny -> 2025wny)
            if obj.get('name_prefix') and canonical_name.startswith(obj['name_prefix']):
                possible_names.append(canonical_name[len(obj['name_prefix']):])
            
            cur.execute("""
                SELECT magnitude, filter 
                FROM photometry 
                WHERE object_name = ANY(%s) AND magnitude IS NOT NULL
            """, (list(set(possible_names)),))
            rows = cur.fetchall()
            
            print(f"DEBUG: Found {len(rows)} photometry points for names {possible_names}")
            
            brightest_mag = None
            brightest_filter = None
            
            # Find minimum numeric magnitude in Python
            min_mag = float('inf')
            
            for row in rows:
                try:
                    mag_val = row['magnitude']
                    
                    # Debug print for problematic values
                    # print(f"DEBUG: Processing mag_val: {mag_val} (type: {type(mag_val)})")
                    
                    # Handle string magnitudes (e.g. ">19.5")
                    if isinstance(mag_val, str):
                        # Skip upper limits
                        if '>' in mag_val:
                            continue
                        val = float(mag_val)
                    # Handle float magnitudes that might be stored as float but we want to be safe
                    elif isinstance(mag_val, (int, float)):
                        val = float(mag_val)
                    else:
                        # Try to convert anything else to string first then check
                        str_val = str(mag_val)
                        if '>' in str_val:
                            continue
                        val = float(str_val)
                        
                    # Ensure val is float
                    if not isinstance(val, float):
                        val = float(val)
                        
                    # Ensure min_mag is float
                    if not isinstance(min_mag, float):
                        min_mag = float(min_mag)
                        
                    if val < min_mag:
                        min_mag = val
                        brightest_filter = row['filter']
                except Exception as e:
                    # print(f"DEBUG: Error processing photometry point: {e}")
                    continue
            
            if min_mag != float('inf'):
                brightest_mag = min_mag
                # print(f"DEBUG: Calculated brightest_mag: {brightest_mag} (Filter: {brightest_filter})")
                
                # Update brightest_mag in tns_objects
                cur.execute("""
                    UPDATE tns_objects 
                    SET brightest_mag = %s 
                    WHERE name = %s
                """, (brightest_mag, canonical_name))
                conn.commit() # Commit the brightest_mag update
                # print("DEBUG: Updated brightest_mag in DB")
            else:
                # print("DEBUG: No valid magnitude found")
                pass
            
            redshift = obj['redshift']
            ra = obj['ra']
            dec = obj['declination']
            
            # If we still don't have brightest_mag, we can't calculate abs mag
            if brightest_mag is None:
                # print("DEBUG: brightest_mag is None, skipping abs mag calc")
                return False
                
            # Parse redshift if it's a string
            try:
                if isinstance(redshift, str):
                    import re
                    match = re.search(r"[-+]?\d*\.\d+|\d+", redshift)
                    if match:
                        z = float(match.group())
                    else:
                        # print(f"DEBUG: Could not parse redshift string: {redshift}")
                        return False
                elif redshift is None:
                    # print("DEBUG: Redshift is None")
                    return False
                else:
                    z = float(redshift)
            except (ValueError, TypeError) as e:
                # print(f"DEBUG: Redshift parse error: {e}")
                return False
                
            if z <= 0:
                # print(f"DEBUG: Invalid redshift z={z}")
                return False
                
            # Calculate extinction
            filter_name = 'r' # Default
            
            # Try to get filter from brightest point
            if brightest_filter:
                filter_name = brightest_filter
            elif obj['discmagfilter']:
                 filter_name = obj['discmagfilter']
                 
            try:
                extinction = ext_M_calculator.get_extinction(ra, dec, filter_name)
                if not isinstance(extinction, (int, float)):
                    extinction = 0
            except Exception as e:
                # print(f"DEBUG: Extinction calc error: {e}")
                extinction = 0
                
            # print(f"DEBUG: Calculating Abs Mag with mag={brightest_mag}, z={z}, ext={extinction}")
            
            # Calculate Abs Mag
            if brightest_mag is not None:
                abs_mag = ext_M_calculator.apm_to_abm(brightest_mag, z, extinction)
                # print(f"DEBUG: Calculated abs_mag: {abs_mag}")
                
                if isinstance(abs_mag, (int, float)):
                    cur.execute("""
                        UPDATE tns_objects 
                        SET brightest_abs_mag = %s 
                        WHERE name = %s
                    """, (abs_mag, canonical_name))
                    conn.commit()
                    # print("DEBUG: Updated brightest_abs_mag in DB")
                    return True
                else:
                    # print(f"DEBUG: abs_mag result is not number: {abs_mag}")
                    pass
                
        return False
    except Exception as e:
        print(f"Error updating abs mag for {target_name}: {e}")
        import traceback
        traceback.print_exc()
        return False

def update_tns_redshift(target_name, redshift_str):
    """
    Update redshift in tns_objects table.
    redshift_str can be text like '0.03 (DESI)'
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check if redshift column is text or numeric
            cur.execute("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'tns_objects' AND column_name = 'redshift'
            """)
            col_type = cur.fetchone()[0]
            
            if 'char' in col_type or 'text' in col_type:
                # It's text, we can save the string directly
                cur.execute("""
                    UPDATE tns_objects 
                    SET redshift = %s 
                    WHERE name = %s
                """, (redshift_str, target_name))
            else:
                # It's numeric, we must extract the number
                # Try to extract float from string
                import re
                match = re.search(r"[-+]?\d*\.\d+|\d+", str(redshift_str))
                if match:
                    val = float(match.group())
                    cur.execute("""
                        UPDATE tns_objects 
                        SET redshift = %s 
                        WHERE name = %s
                    """, (val, target_name))
                else:
                    print(f"Could not extract numeric redshift from {redshift_str}")
                    return False
            
            conn.commit()
            
            # Trigger absolute magnitude update
            try:
                update_object_abs_mag(target_name)
            except Exception as e:
                print(f"Error triggering abs mag update: {e}")
                
            return True
    except Exception as e:
        print(f"Error updating redshift for {target_name}: {e}")
        return False

if __name__ == "__main__":
    init_tns_database()
    print("Database initialization completed")
