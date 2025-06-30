import sqlite3
import os
from datetime import datetime, timezone
import uuid
from contextlib import contextmanager

DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'calendar.db')

def get_calendar_db_connection():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_calendar_db():
    conn = get_calendar_db_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_calendar_database():
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        
        # Events table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            all_day BOOLEAN DEFAULT 0,
            location TEXT,
            category TEXT DEFAULT 'general',
            color TEXT DEFAULT '#007AFF',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            recurrence_rule TEXT,
            is_public BOOLEAN DEFAULT 1
        )
        ''')
        
        # Calendar categories
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendar_categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL,
            description TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        ''')
        
        # Insert default categories
        default_categories = [
            ('meeting', 'Meeting', '#FF3B30', 'Lab meetings and discussions', 'system'),
            ('observation', 'Observation', '#34C759', 'Telescope observations', 'system'),
            ('deadline', 'Deadline', '#FF9500', 'Important deadlines', 'system'),
            ('conference', 'Conference', '#5856D6', 'Conferences and workshops', 'system'),
            ('maintenance', 'Maintenance', '#8E8E93', 'Equipment maintenance', 'system'),
            ('general', 'General', '#007AFF', 'General events', 'system')
        ]
        
        current_time = datetime.now(timezone.utc).isoformat()
        for cat_id, name, color, desc, creator in default_categories:
            cursor.execute('''
            INSERT OR IGNORE INTO calendar_categories 
            (id, name, color, description, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (cat_id, name, color, desc, creator, current_time))
        
        conn.commit()

def get_calendar_events(start_date=None, end_date=None, category=None):
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        
        query = 'SELECT * FROM calendar_events WHERE 1=1'
        params = []
        
        if start_date:
            query += ' AND date(start_date) >= date(?)'
            params.append(start_date)
        
        if end_date:
            query += ' AND date(start_date) <= date(?)'
            params.append(end_date)
        
        if category:
            query += ' AND category = ?'
            params.append(category)
        
        query += ' ORDER BY start_date ASC'
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def create_calendar_event(title, start_date, end_date, description=None, 
                         location=None, category='general', color='#007AFF', 
                         all_day=False, created_by='system', recurrence_rule=None):
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        
        event_id = str(uuid.uuid4())
        current_time = datetime.now(timezone.utc).isoformat()
        
        cursor.execute('''
        INSERT INTO calendar_events 
        (id, title, description, start_date, end_date, all_day, location, 
         category, color, created_by, created_at, updated_at, recurrence_rule, is_public)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (event_id, title, description, start_date, end_date, all_day, 
              location, category, color, created_by, current_time, current_time, 
              recurrence_rule, True))
        
        conn.commit()
        return event_id

def update_calendar_event(event_id, **kwargs):
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        
        kwargs['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [event_id]
        
        cursor.execute(f'''
        UPDATE calendar_events SET {set_clause} WHERE id = ?
        ''', values)
        
        conn.commit()
        return cursor.rowcount > 0

def delete_calendar_event(event_id):
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM calendar_events WHERE id = ?', (event_id,))
        conn.commit()
        return cursor.rowcount > 0

def get_calendar_categories():
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM calendar_categories ORDER BY name')
        return [dict(row) for row in cursor.fetchall()]

def create_calendar_category(name, color, description=None, created_by='system'):
    with get_calendar_db() as conn:
        cursor = conn.cursor()
        
        category_id = str(uuid.uuid4())
        current_time = datetime.now(timezone.utc).isoformat()
        
        cursor.execute('''
        INSERT INTO calendar_categories 
        (id, name, color, description, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (category_id, name, color, description, created_by, current_time))
        
        conn.commit()
        return category_id