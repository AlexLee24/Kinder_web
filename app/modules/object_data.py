import sqlite3
import os
import json
from pathlib import Path
from datetime import datetime

class ObjectDataDB:
    def __init__(self):
        self.db_path = Path(os.path.dirname(__file__)).parent / "data" / "object_data.db"
        self.db_path.parent.mkdir(exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(str(self.db_path))
    
    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Photometry table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photometry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_name TEXT NOT NULL,
                mjd REAL NOT NULL,
                magnitude REAL,
                magnitude_error REAL,
                filter TEXT,
                telescope TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Spectroscopy table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spectroscopy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_name TEXT NOT NULL,
                wavelength REAL NOT NULL,
                intensity REAL NOT NULL,
                phase REAL,
                telescope TEXT,
                spectrum_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Comments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                user_name TEXT NOT NULL,
                user_picture TEXT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_name) REFERENCES photometry(object_name)
            )
        ''')
        
        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photometry_object ON photometry(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photometry_mjd ON photometry(mjd)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spectroscopy_object ON spectroscopy(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_spectroscopy_spectrum_id ON spectroscopy(spectrum_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_object ON comments(object_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(created_at)')
        
        conn.commit()
        conn.close()
    
    def add_photometry_point(self, object_name, mjd, magnitude=None, magnitude_error=None, 
                           filter_name=None, telescope=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO photometry (object_name, mjd, magnitude, magnitude_error, filter, telescope)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (object_name, mjd, magnitude, magnitude_error, filter_name, telescope))
        
        conn.commit()
        point_id = cursor.lastrowid
        conn.close()
        return point_id
    
    def add_spectrum_data(self, object_name, wavelength_data, intensity_data, 
                         phase=None, telescope=None, spectrum_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if spectrum_id is None:
            spectrum_id = f"{object_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Insert multiple wavelength/intensity pairs
        for wavelength, intensity in zip(wavelength_data, intensity_data):
            cursor.execute('''
                INSERT INTO spectroscopy (object_name, wavelength, intensity, phase, telescope, spectrum_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (object_name, wavelength, intensity, phase, telescope, spectrum_id))
        
        conn.commit()
        conn.close()
        return spectrum_id
    
    def get_photometry(self, object_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM photometry 
            WHERE object_name = ? 
            ORDER BY mjd ASC
        ''', (object_name,))
        
        results = cursor.fetchall()
        conn.close()
        
        columns = ['id', 'object_name', 'mjd', 'magnitude', 'magnitude_error', 
                  'filter', 'telescope', 'created_at', 'updated_at']
        return [dict(zip(columns, row)) for row in results]
    
    def get_spectroscopy(self, object_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM spectroscopy 
            WHERE object_name = ? 
            ORDER BY spectrum_id, wavelength ASC
        ''', (object_name,))
        
        results = cursor.fetchall()
        conn.close()
        
        columns = ['id', 'object_name', 'wavelength', 'intensity', 'phase', 
                  'telescope', 'spectrum_id', 'created_at', 'updated_at']
        return [dict(zip(columns, row)) for row in results]
    
    def get_spectrum_list(self, object_name):
        """Get list of available spectra for an object"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT spectrum_id, telescope, phase, 
                   MIN(wavelength) as min_wave, MAX(wavelength) as max_wave,
                   COUNT(*) as point_count, MIN(created_at) as obs_date
            FROM spectroscopy 
            WHERE object_name = ? 
            GROUP BY spectrum_id
            ORDER BY obs_date DESC
        ''', (object_name,))
        
        results = cursor.fetchall()
        conn.close()
        
        columns = ['spectrum_id', 'telescope', 'phase', 'min_wavelength', 
                  'max_wavelength', 'point_count', 'observation_date']
        return [dict(zip(columns, row)) for row in results]
    
    def delete_photometry_point(self, point_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM photometry WHERE id = ?', (point_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        return deleted
    
    def delete_spectrum(self, spectrum_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM spectroscopy WHERE spectrum_id = ?', (spectrum_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        return deleted
    
    # Comment functionality
    def add_comment(self, object_name, user_email, user_name, user_picture, content):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Use UTC timestamp with explicit timezone info
        from datetime import datetime, timezone
        utc_now = datetime.now(timezone.utc)
        # Format as ISO string with Z suffix to indicate UTC
        utc_timestamp = utc_now.strftime('%Y-%m-%d %H:%M:%S') + 'Z'
        
        cursor.execute('''
            INSERT INTO comments (object_name, user_email, user_name, user_picture, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (object_name, user_email, user_name, user_picture, content, utc_timestamp))
        
        conn.commit()
        comment_id = cursor.lastrowid
        conn.close()
        return comment_id
    
    def get_comments(self, object_name):
        """Get all comments for an object, ordered by creation time"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, object_name, user_email, user_name, user_picture, content, created_at
            FROM comments 
            WHERE object_name = ? 
            ORDER BY created_at ASC
        ''', (object_name,))
        
        results = cursor.fetchall()
        conn.close()
        
        columns = ['id', 'object_name', 'user_email', 'user_name', 'user_picture', 'content', 'created_at']
        return [dict(zip(columns, row)) for row in results]
    
    def delete_comment(self, comment_id):
        """Delete a comment by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        return deleted
    
    def get_comment_by_id(self, comment_id):
        """Get a specific comment by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, object_name, user_email, user_name, user_picture, content, created_at
            FROM comments 
            WHERE id = ?
        ''', (comment_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            columns = ['id', 'object_name', 'user_email', 'user_name', 'user_picture', 'content', 'created_at']
            return dict(zip(columns, result))
        return None

# Global instance
object_db = ObjectDataDB()