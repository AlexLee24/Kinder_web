import logging
import psycopg2
from psycopg2 import pool, extras
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os
import json
from datetime import datetime
from contextlib import contextmanager
from dotenv import load_dotenv

# Load PostgreSQL connection settings from .env
basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '..', '..', 'kinder.env')
load_dotenv(dotenv_path, override=True)

DB_HOST = os.getenv("PG_HOST", "localhost")
DB_PORT = os.getenv("PG_PORT", "5432")
DB_USER = os.getenv("PG_USER", "postgres")
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_NAME = "kinder_web"  # Specific for this module

logger = logging.getLogger(__name__)

# Connection pool
connection_pool = None

def init_connection_pool(minconn=1, maxconn=20):
    """Initialize PostgreSQL connection pool"""
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn,
                maxconn,
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
        except Exception as e:
            logger.error('Error initializing connection pool for %s: %s', DB_NAME, e)
            raise e
    return connection_pool

@contextmanager
def get_db_connection():
    """Get connection from pool with context manager"""
    pool = init_connection_pool()
    conn = pool.getconn()
    try:
        # Return DictCursor by default to mimic dictionary-like access
        # But for list comprehensions like row[0], we might need care. 
        # database.py often uses dict(row) or row['col']. 
        # Using RealDictCursor handles dict(row) well (it's already a dict subclass).
        # For row[0], we must change the code to use column names.
        yield conn
    finally:
        pool.putconn(conn)


def _split_csv_values(raw_value):
    if raw_value is None:
        return []
    s = str(raw_value).strip()
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def _normalize_log_filter_columns(filter_value, exp_value, count_value):
    """Normalize log filter payloads into comma-separated columns."""
    rows = []

    if isinstance(filter_value, list):
        rows = [x for x in filter_value if isinstance(x, dict)]
    elif isinstance(filter_value, str):
        raw = filter_value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    rows = [x for x in parsed if isinstance(x, dict)]
                elif isinstance(parsed, dict):
                    rows = [parsed]
            except Exception:
                rows = []

    if not rows:
        filters = _split_csv_values(filter_value)
        exp_list = _split_csv_values(exp_value)
        count_list = _split_csv_values(count_value)
        for i, f in enumerate(filters):
            rows.append({
                'filter': f,
                'exp': exp_list[i] if i < len(exp_list) else (exp_list[0] if len(exp_list) == 1 else None),
                'count': count_list[i] if i < len(count_list) else (count_list[0] if len(count_list) == 1 else None),
            })

    clean_rows = []
    for row in rows:
        f_name = str(row.get('filter', '')).strip()
        if not f_name:
            continue
        exp = row.get('exp')
        cnt = row.get('count')
        clean_rows.append({
            'filter': f_name,
            'exp': str(exp).strip() if exp not in (None, '') else '',
            'count': str(cnt).strip() if cnt not in (None, '') else ''
        })

    if not clean_rows:
        return None, None, None

    filter_csv = ','.join([r['filter'] for r in clean_rows])
    exp_csv = ','.join([r['exp'] for r in clean_rows]) if any(r['exp'] for r in clean_rows) else None
    count_csv = ','.join([r['count'] for r in clean_rows]) if any(r['count'] for r in clean_rows) else None
    return filter_csv, exp_csv, count_csv

def init_database():
    """Initialize database tables"""
    # Create DB if not exists - logic is tricky inside app since we connect to specific DB.
    # We assume DB created by migration script. Here we just ensure tables exist.
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Users
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    picture TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    role VARCHAR(20) DEFAULT 'guest',
                    last_login TIMESTAMP,
                    invited_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Groups
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    created_by TEXT REFERENCES users(email),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User Groups
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_groups (
                    user_email TEXT,
                    group_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_email, group_name),
                    FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE,
                    FOREIGN KEY (group_name) REFERENCES groups (name) ON DELETE CASCADE
                )
            ''')
            
            # Invitations
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS invitations (
                    token TEXT PRIMARY KEY,
                    email TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    role VARCHAR(20) DEFAULT 'user',
                    invited_by TEXT REFERENCES users(email),
                    invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    accepted_at TIMESTAMP
                )
            ''')
            
            # Object Permissions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS object_permissions (
                    object_name TEXT,
                    group_name TEXT,
                    granted_by TEXT REFERENCES users(email),
                    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (object_name, group_name),
                    FOREIGN KEY (group_name) REFERENCES groups (name) ON DELETE CASCADE,
                    FOREIGN KEY (granted_by) REFERENCES users (email)
                )
            ''')

            # Group Requests
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS group_requests (
                    id SERIAL PRIMARY KEY,
                    user_email TEXT REFERENCES users(email) ON DELETE CASCADE,
                    group_name TEXT REFERENCES groups(name) ON DELETE CASCADE,
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_email, group_name)
                )
            ''')

            # System Settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            
            # Observation Targets
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS observation_targets (
                    id SERIAL PRIMARY KEY,
                    telescope VARCHAR(10),
                    name TEXT,
                    mag TEXT,
                    ra TEXT,
                    dec TEXT,
                    priority VARCHAR(20),
                    repeat_count INT DEFAULT 0,
                    auto_exposure BOOLEAN DEFAULT TRUE,
                    filters JSONB,
                    plan TEXT,
                    program TEXT,
                    created_by TEXT REFERENCES users(email),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    note_gl TEXT,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            # Migration
            try:
                cursor.execute('ALTER TABLE observation_targets ADD COLUMN IF NOT EXISTS note_gl TEXT')
                cursor.execute('ALTER TABLE observation_targets ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE')
            except Exception as e:
                pass


            # Observation Logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS observation_logs (
                    id SERIAL PRIMARY KEY,
                    target_name TEXT,
                    obs_date DATE,
                    user_name TEXT,
                    is_triggered BOOLEAN DEFAULT FALSE,
                    is_observed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(target_name, obs_date)
                )
            """)

            # Migration: add columns to observation_logs if not exist
            try:
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS trigger_filter TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS trigger_exp TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS trigger_count TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS observed_filter TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS observed_exp TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS observed_count TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS priority VARCHAR(20)')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS telescope_use VARCHAR(10)')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS target_name TEXT')
                # Allow multiple values like "300,300" and "4,1" for multi-filter logs.
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN trigger_exp TYPE TEXT USING trigger_exp::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN trigger_count TYPE TEXT USING trigger_count::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN observed_exp TYPE TEXT USING observed_exp::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN observed_count TYPE TEXT USING observed_count::TEXT')
                cursor.execute('''
                    UPDATE observation_logs
                    SET trigger_filter = (
                            SELECT string_agg(elem->>'filter', ',' ORDER BY ord)
                            FROM jsonb_array_elements(trigger_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        ),
                        trigger_exp = (
                            SELECT string_agg(COALESCE(elem->>'exp', ''), ',' ORDER BY ord)
                            FROM jsonb_array_elements(trigger_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        ),
                        trigger_count = (
                            SELECT string_agg(COALESCE(elem->>'count', ''), ',' ORDER BY ord)
                            FROM jsonb_array_elements(trigger_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        )
                    WHERE trigger_filter IS NOT NULL
                      AND TRIM(trigger_filter) LIKE '[%'
                ''')
                cursor.execute('''
                    UPDATE observation_logs
                    SET observed_filter = (
                            SELECT string_agg(elem->>'filter', ',' ORDER BY ord)
                            FROM jsonb_array_elements(observed_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        ),
                        observed_exp = (
                            SELECT string_agg(COALESCE(elem->>'exp', ''), ',' ORDER BY ord)
                            FROM jsonb_array_elements(observed_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        ),
                        observed_count = (
                            SELECT string_agg(COALESCE(elem->>'count', ''), ',' ORDER BY ord)
                            FROM jsonb_array_elements(observed_filter::jsonb) WITH ORDINALITY AS x(elem, ord)
                        )
                    WHERE observed_filter IS NOT NULL
                      AND TRIM(observed_filter) LIKE '[%'
                ''')
                cursor.execute('''
                    UPDATE observation_logs l
                    SET target_name = t.name
                    FROM observation_targets t
                    WHERE l.target_name IS NULL
                      AND l.target_id = t.id
                ''')
                cursor.execute('''
                    UPDATE observation_logs
                    SET target_id = NULL
                    WHERE target_name IS NOT NULL
                ''')
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_observation_logs_target_name_obs_date ON observation_logs(target_name, obs_date)")
            except Exception as e:
                pass

            conn.commit()


# --- Users ---

def get_user(email):
    """Get single user info"""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()
            
            if user:
                user_dict = dict(user)
                # Get groups
                cursor.execute('''
                    SELECT group_name FROM user_groups 
                    WHERE user_email = %s
                ''', (email,))
                # Use column name 'group_name' instead of index 0
                groups = [row['group_name'] for row in cursor.fetchall()]
                user_dict['groups'] = groups
                return user_dict
            return None

def get_users():
    """Get all users"""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM users')
            users = cursor.fetchall()
            
            result = {}
            for user in users:
                user_dict = dict(user)
                cursor.execute('''
                    SELECT group_name FROM user_groups 
                    WHERE user_email = %s
                ''', (user['email'],))
                groups = [row['group_name'] for row in cursor.fetchall()]
                user_dict['groups'] = groups
                result[user['email']] = user_dict
            
            return result

def save_user(email, name, picture=None, is_admin=False, role='guest', last_login=None, invited_at=None):
    """Save or update user"""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Upsert in Postgres
            cursor.execute('''
                INSERT INTO users 
                (email, name, picture, is_admin, role, last_login, invited_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) 
                DO UPDATE SET
                    name = EXCLUDED.name,
                    picture = EXCLUDED.picture,
                    last_login = EXCLUDED.last_login
            ''', (email, name, picture, is_admin, role, last_login, invited_at))
            conn.commit()
            return True


import secrets

def generate_api_key():
    """Generates a random API key"""
    return secrets.token_urlsafe(32)

def generate_api_key_for_user(email):
    """Generate and save an API key for a specific user"""
    api_key = generate_api_key()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('UPDATE users SET api_key = %s WHERE email = %s', (api_key, email))
            conn.commit()
    return api_key

def get_user_by_api_key(api_key):
    """Look up a user by their API key"""
    if not api_key:
        return None
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM users WHERE api_key = %s', (api_key,))
            user = cursor.fetchone()
            if user:
                user_dict = dict(user)
                cursor.execute('SELECT group_name FROM user_groups WHERE user_email = %s', (user['email'],))
                groups = [row['group_name'] for row in cursor.fetchall()]
                user_dict['groups'] = groups
                return user_dict
            return None


def update_user(email, **kwargs):
    """Update user info"""
    if not kwargs:
        return False
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            set_clause = ', '.join([f"{key} = %s" for key in kwargs.keys()])
            values = list(kwargs.values()) + [email]
            
            cursor.execute(f'''
                UPDATE users SET {set_clause} WHERE email = %s
            ''', values)
            conn.commit()
            return cursor.rowcount > 0

def delete_user(email):
    """Delete user"""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Foreign keys have ON DELETE CASCADE/SET NULL mostly?
            # user_groups has ON DELETE CASCADE.
            # But invitations.invited_by, groups.created_by, object_permissions.granted_by might prevent deletion?
            # Creating tables above showed REFERENCES users(email), implying default action (NO ACTION / RESTRICT).
            # SQLite default is separate. 
            # Original code manually deletes from user_groups then users.
            
            # Manually delete dependencies if FK constraints restrict it.
            cursor.execute('DELETE FROM user_groups WHERE user_email = %s', (email,))
            # groups created by user? object_permissions granted by user?
            # If standard FK behavior, deleting user might fail if they created groups.
            # Current schema definition (above) doesn't specify ON DELETE for created_by.
            # Let's try to delete user.
            try:
                cursor.execute('DELETE FROM users WHERE email = %s', (email,))
                conn.commit()
                return cursor.rowcount > 0
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def user_exists(email):
    """Check if user exists"""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1 FROM users WHERE email = %s', (email,))
            return cursor.fetchone() is not None

# --- Groups ---

def get_groups():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM groups')
            groups = cursor.fetchall()
            
            result = {}
            for group in groups:
                group_dict = dict(group)
                cursor.execute('''
                    SELECT user_email FROM user_groups 
                    WHERE group_name = %s
                ''', (group['name'],))
                members = [row['user_email'] for row in cursor.fetchall()]
                group_dict['members'] = members
                result[group['name']] = group_dict
            
            return result

def create_group(name, description=None, created_by=None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute('''
                    INSERT INTO groups (name, description, created_by)
                    VALUES (%s, %s, %s)
                ''', (name, description, created_by))
                conn.commit()
                return True
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def delete_group(name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM user_groups WHERE group_name = %s', (name,))
            cursor.execute('DELETE FROM groups WHERE name = %s', (name,))
            conn.commit()
            return cursor.rowcount > 0

def group_exists(name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1 FROM groups WHERE name = %s', (name,))
            return cursor.fetchone() is not None

# --- User Groups ---

def add_user_to_group(user_email, group_name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute('''
                    INSERT INTO user_groups (user_email, group_name)
                    VALUES (%s, %s)
                ''', (user_email, group_name))
                conn.commit()
                return True
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def remove_user_from_group(user_email, group_name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                DELETE FROM user_groups 
                WHERE user_email = %s AND group_name = %s
            ''', (user_email, group_name))
            conn.commit()
            return cursor.rowcount > 0

def user_in_group(user_email, group_name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT 1 FROM user_groups 
                WHERE user_email = %s AND group_name = %s
            ''', (user_email, group_name))
            return cursor.fetchone() is not None

# --- Group Requests ---

def create_group_request(user_email, group_name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute('''
                    INSERT INTO group_requests (user_email, group_name)
                    VALUES (%s, %s)
                ''', (user_email, group_name))
                conn.commit()
                return True
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def get_group_requests(status='pending'):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT r.id, r.user_email, u.name as user_name, r.group_name, r.status, r.created_at
                FROM group_requests r
                JOIN users u ON r.user_email = u.email
                WHERE r.status = %s
                ORDER BY r.created_at DESC
            ''', (status,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

def update_group_request_status(request_id, status):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                UPDATE group_requests
                SET status = %s
                WHERE id = %s
            ''', (status, request_id))
            conn.commit()
            return cursor.rowcount > 0

def delete_group_request(request_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM group_requests WHERE id = %s', (request_id,))
            conn.commit()
            return cursor.rowcount > 0

def get_group_request(request_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM group_requests WHERE id = %s', (request_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

def get_user_group_requests(user_email):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT group_name, status 
                FROM group_requests 
                WHERE user_email = %s
            ''', (user_email,))
            return {row[0]: row[1] for row in cursor.fetchall()}

# --- Invitations ---

def get_invitations():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM invitations')
            invitations = cursor.fetchall()
            
            result = {}
            for invitation in invitations:
                result[invitation['token']] = dict(invitation)
            
            return result

def create_invitation(token, email=None, is_admin=False, role='user', invited_by=None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute('''
                    INSERT INTO invitations (token, email, is_admin, role, invited_by)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (token, email, is_admin, role, invited_by))
                conn.commit()
                return True
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def get_invitation(token):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM invitations WHERE token = %s', (token,))
            invitation = cursor.fetchone()
            return dict(invitation) if invitation else None

def update_invitation(token, **kwargs):
    if not kwargs:
        return False
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            set_clause = ', '.join([f"{key} = %s" for key in kwargs.keys()])
            values = list(kwargs.values()) + [token]
            
            cursor.execute(f'''
                UPDATE invitations SET {set_clause} WHERE token = %s
            ''', values)
            conn.commit()
            return cursor.rowcount > 0

def delete_invitation(token):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM invitations WHERE token = %s', (token,))
            conn.commit()
            return cursor.rowcount > 0

def clean_accepted_invitations():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM invitations WHERE status = %s', ('accepted',))
            conn.commit()
            return cursor.rowcount

# --- Consistency ---

def check_data_consistency():
    issues = {
        'orphaned_user_groups': [],
        'orphaned_group_users': [],
        'missing_users': [],
        'missing_groups': []
    }
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT ug.user_email, ug.group_name 
                FROM user_groups ug
                LEFT JOIN users u ON ug.user_email = u.email
                WHERE u.email IS NULL
            ''')
            rows = cursor.fetchall()
            issues['orphaned_user_groups'] = [[row[0], row[1]] for row in rows]
            
            cursor.execute('''
                SELECT ug.user_email, ug.group_name 
                FROM user_groups ug
                LEFT JOIN groups g ON ug.group_name = g.name
                WHERE g.name IS NULL
            ''')
            rows = cursor.fetchall()
            issues['orphaned_group_users'] = [[row[0], row[1]] for row in rows]
            
            issues['total_issues'] = (
                len(issues['orphaned_user_groups']) + 
                len(issues['orphaned_group_users'])
            )
    
    return issues

def clean_data_consistency():
    cleaned_count = 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                DELETE FROM user_groups 
                WHERE user_email NOT IN (SELECT email FROM users)
            ''')
            cleaned_count += cursor.rowcount
            
            cursor.execute('''
                DELETE FROM user_groups 
                WHERE group_name NOT IN (SELECT name FROM groups)
            ''')
            cleaned_count += cursor.rowcount
            
            conn.commit()
    return cleaned_count

# --- Permissions ---

def get_all_groups():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM groups ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]

def get_object_permissions(object_name):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute('''
                SELECT op.*, g.description as group_description 
                FROM object_permissions op
                JOIN groups g ON op.group_name = g.name
                WHERE op.object_name = %s
            ''', (object_name,))
            return [dict(row) for row in cursor.fetchall()]

def grant_object_permission(object_name, group_name, granted_by):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute('''
                    INSERT INTO object_permissions (object_name, group_name, granted_by)
                    VALUES (%s, %s, %s)
                ''', (object_name, group_name, granted_by))
                conn.commit()
                return True
            except psycopg2.IntegrityError:
                conn.rollback()
                return False

def revoke_object_permission(object_name, group_name):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                DELETE FROM object_permissions 
                WHERE object_name = %s AND group_name = %s
            ''', (object_name, group_name))
            conn.commit()
            return cursor.rowcount > 0

def check_object_access(object_name, user_email):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            # 1. Admin check
            cursor.execute('SELECT is_admin FROM users WHERE email = %s', (user_email,))
            user = cursor.fetchone()
            if not user:
                return False
            if user['is_admin']:
                return True
                
            # 2. Check if permissions set
            cursor.execute('SELECT COUNT(*) as count FROM object_permissions WHERE object_name = %s', (object_name,))
            row = cursor.fetchone()
            if row['count'] == 0:
                return False
                
            # 3. Check group
            cursor.execute('''
                SELECT 1 FROM object_permissions op
                JOIN user_groups ug ON op.group_name = ug.group_name
                WHERE op.object_name = %s AND ug.user_email = %s
            ''', (object_name, user_email))
            
            return cursor.fetchone() is not None

# --- Settings ---

def get_setting(key, default=None):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            try:
                cursor.execute('SELECT value FROM system_settings WHERE key = %s', (key,))
                row = cursor.fetchone()
                return row['value'] if row else default
            except psycopg2.Error:
                conn.rollback()
                return default

def set_setting(key, value):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            ''', (key, str(value)))
            conn.commit()
            return True


# --- Observation Targets ---
def save_observation_target(telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, filters, plan, program, note_gl, user_email):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO observation_targets 
                (telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, filters, plan, program, note_gl, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''', (telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, json.dumps(filters), plan, program, note_gl, user_email))
            new_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            return new_id
    except Exception as e:
        logger.error('Error saving target: %s', e)
    return None

def update_observation_target_status(target_id: int, is_active: bool) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE observation_targets
                SET is_active = %s
                WHERE id = %s
            ''', (is_active, target_id))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error('Error updating target status: %s', e)
        return False

def get_observation_targets():
    targets = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, filters, plan, program, note_gl, created_by, created_at, is_active
                FROM observation_targets
                ORDER BY created_at ASC
            ''')
            rows = cursor.fetchall()
            for row in rows:
                targets.append({
                    'id': row[0],
                    'telescope': row[1],
                    'name': row[2],
                    'mag': row[3],
                    'ra': row[4],
                    'dec': row[5],
                    'priority': row[6],
                    'repeat_count': row[7],
                    'auto_exposure': row[8],
                    'filters': row[9],
                    'plan': row[10],
                    'program': row[11],
                    'note_gl': row[12],
                    'created_by': row[13],
                    'created_at': row[14].isoformat() if row[14] else None,
                    'is_active': row[15] if row[15] is not None else True
                })
            cursor.close()
    except Exception as e:
        logger.error('Error fetching targets: %s', e)
    return targets

def delete_observation_target(target_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM observation_targets WHERE id = %s', (target_id,))
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        logger.error('Error deleting target: %s', e)

def update_observation_target(target_id, telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, filters, plan, program, note_gl):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE observation_targets
                SET telescope=%s, name=%s, mag=%s, ra=%s, dec=%s, priority=%s,
                    repeat_count=%s, auto_exposure=%s, filters=%s, plan=%s, program=%s, note_gl=%s
                WHERE id=%s
            ''', (telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, json.dumps(filters), plan, program, note_gl, target_id))
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        logger.error('Error updating target: %s', e)

def get_observation_log_months():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    SELECT DISTINCT
                        EXTRACT(YEAR FROM l.obs_date) as yr,
                        EXTRACT(MONTH FROM l.obs_date) as mo
                    FROM observation_logs l
                    LEFT JOIN observation_targets t ON l.target_id = t.id
                    WHERE COALESCE(NULLIF(TRIM(l.target_name), ''), NULLIF(TRIM(t.name), '')) IS NOT NULL
                      AND (l.is_triggered = TRUE OR l.is_observed = TRUE)
                    ORDER BY yr DESC, mo DESC
                ''')
            except Exception as col_err:
                # Fallback for very old schema without target_name/target_id compatibility
                if getattr(col_err, 'pgcode', None) == '42703':
                    conn.rollback()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT DISTINCT EXTRACT(YEAR FROM obs_date) as yr, EXTRACT(MONTH FROM obs_date) as mo
                        FROM observation_logs
                        WHERE is_triggered = TRUE OR is_observed = TRUE
                        ORDER BY yr DESC, mo DESC
                    ''')
                else:
                    raise
            results = []
            for row in cursor.fetchall():
                results.append({'year': int(row[0]), 'month': int(row[1])})
            cursor.close()
            return results
    except Exception as e:
        logger.error('Error fetching observation log months: %s', e)

def get_observation_logs(year, month):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    SELECT l.id,
                           l.target_name,
                           l.obs_date, l.user_name, l.is_triggered, l.is_observed,
                           trigger_filter, trigger_exp, trigger_count,
                           observed_filter, observed_exp, observed_count, priority, telescope_use
                    FROM observation_logs l
                    WHERE EXTRACT(YEAR FROM l.obs_date) = %s AND EXTRACT(MONTH FROM l.obs_date) = %s
                ''', (year, month))
            except Exception as col_err:
                if getattr(col_err, 'pgcode', None) == '42703':  # undefined_column
                    conn.rollback()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT l.id,
                               COALESCE(t.name, CONCAT('Deleted target #', l.target_id::text)) AS target_name,
                               l.obs_date, l.user_name, l.is_triggered, l.is_observed,
                               trigger_filter, trigger_exp, trigger_count,
                               observed_filter, observed_exp, observed_count, telescope_use
                        FROM observation_logs l
                        LEFT JOIN observation_targets t ON l.target_id = t.id
                        WHERE EXTRACT(YEAR FROM l.obs_date) = %s AND EXTRACT(MONTH FROM l.obs_date) = %s
                    ''', (year, month))
                else:
                    raise
            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                d = dict(zip(columns, row))
                d.setdefault('priority', None)
                results.append(d)
            cursor.close()
            return results
    except Exception as e:
        logger.error('Error fetching observation logs: %s', e)

def upsert_observation_log(target_name, obs_date, user_name, is_triggered, is_observed,
                            trigger_filter=None, trigger_exp=None, trigger_count=None,
                            observed_filter=None, observed_exp=None, observed_count=None,
                            priority=None, telescope_use=None):
    try:
        trigger_filter, trigger_exp, trigger_count = _normalize_log_filter_columns(
            trigger_filter, trigger_exp, trigger_count
        )
        observed_filter, observed_exp, observed_count = _normalize_log_filter_columns(
            observed_filter, observed_exp, observed_count
        )

        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS target_name TEXT')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS priority VARCHAR(20)')
                cursor.execute('ALTER TABLE observation_logs ADD COLUMN IF NOT EXISTS telescope_use VARCHAR(10)')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN trigger_exp TYPE TEXT USING trigger_exp::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN trigger_count TYPE TEXT USING trigger_count::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN observed_exp TYPE TEXT USING observed_exp::TEXT')
                cursor.execute('ALTER TABLE observation_logs ALTER COLUMN observed_count TYPE TEXT USING observed_count::TEXT')

                # Automatically fallback telescope_use if not provided but log is created
                if not telescope_use:
                    telescope_use = 'SLT'

                # Since `target_name, obs_date` was the previous UNIQUE key
                # To allow the same target on SLT and LOT on the same day, we must make sure `telescope_use` is part of the WHERE.
                cursor.execute('''
                    UPDATE observation_logs
                    SET user_name = %s,
                        is_triggered = %s,
                        is_observed = %s,
                        trigger_filter = %s,
                        trigger_exp = %s,
                        trigger_count = %s,
                        observed_filter = %s,
                        observed_exp = %s,
                        observed_count = %s,
                        priority = %s,
                        telescope_use = %s,
                        created_at = CURRENT_TIMESTAMP
                    WHERE target_name = %s AND obs_date = %s AND telescope_use = %s
                ''', (
                    user_name, is_triggered, is_observed,
                    trigger_filter, trigger_exp, trigger_count,
                    observed_filter, observed_exp, observed_count,
                    priority, telescope_use,
                    target_name, obs_date, telescope_use
                ))

                if cursor.rowcount == 0:
                    cursor.execute('''
                        INSERT INTO observation_logs
                            (target_name, obs_date, user_name, is_triggered, is_observed,
                             trigger_filter, trigger_exp, trigger_count,
                             observed_filter, observed_exp, observed_count, priority, telescope_use)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        target_name, obs_date, user_name, is_triggered, is_observed,
                        trigger_filter, trigger_exp, trigger_count,
                        observed_filter, observed_exp, observed_count, priority, telescope_use
                    ))
            except Exception as write_err:
                conn.rollback()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO observation_logs
                        (target_name, obs_date, user_name, is_triggered, is_observed,
                         trigger_filter, trigger_exp, trigger_count,
                         observed_filter, observed_exp, observed_count, priority, telescope_use)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        target_name, obs_date, user_name, is_triggered, is_observed,
                        trigger_filter, trigger_exp, trigger_count,
                        observed_filter, observed_exp, observed_count, priority, telescope_use
                    ))
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        logger.error('Error upserting observation log: %s', e)
        return False


def delete_observation_log(target_name, obs_date, telescope_use=None):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if telescope_use:
                cursor.execute(
                    'DELETE FROM observation_logs WHERE target_name = %s AND obs_date = %s AND telescope_use = %s',
                    (target_name, obs_date, telescope_use)
                )
            else:
                cursor.execute(
                    'DELETE FROM observation_logs WHERE target_name = %s AND obs_date = %s',
                    (target_name, obs_date)
                )
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            return deleted > 0
    except Exception as e:
        logger.error('Error deleting observation log: %s', e)
