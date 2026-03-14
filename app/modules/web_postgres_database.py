
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
            print(f"Error initializing connection pool for {DB_NAME}: {e}")
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')


            # Observation Logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS observation_logs (
                    id SERIAL PRIMARY KEY,
                    target_id INTEGER REFERENCES observation_targets(id) ON DELETE CASCADE,
                    obs_date DATE,
                    user_name TEXT,
                    is_triggered BOOLEAN DEFAULT FALSE,
                    is_observed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(target_id, obs_date)
                )
            """)
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
        print(f"Error saving target: {e}")
    return None

def get_observation_targets():
    targets = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, telescope, name, mag, ra, dec, priority, repeat_count, auto_exposure, filters, plan, program, note_gl, created_by, created_at
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
                    'created_at': row[14].isoformat() if row[14] else None
                })
            cursor.close()
    except Exception as e:
        print(f"Error fetching targets: {e}")
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
        print(f"Error deleting target: {e}")
    return False

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
        print(f"Error updating target: {e}")
    return False

def get_observation_logs(year, month):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, target_id, obs_date, user_name, is_triggered, is_observed,
                       trigger_filter, trigger_exp, trigger_count,
                       observed_filter, observed_exp, observed_count
                FROM observation_logs
                WHERE EXTRACT(YEAR FROM obs_date) = %s AND EXTRACT(MONTH FROM obs_date) = %s
            ''', (year, month))
            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            cursor.close()
            return results
    except Exception as e:
        print(f"Error fetching observation logs: {e}")
    return []

def upsert_observation_log(target_id, obs_date, user_name, is_triggered, is_observed,
                            trigger_filter=None, trigger_exp=None, trigger_count=None,
                            observed_filter=None, observed_exp=None, observed_count=None):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO observation_logs
                    (target_id, obs_date, user_name, is_triggered, is_observed,
                     trigger_filter, trigger_exp, trigger_count,
                     observed_filter, observed_exp, observed_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (target_id, obs_date)
                DO UPDATE SET
                    user_name       = EXCLUDED.user_name,
                    is_triggered    = EXCLUDED.is_triggered,
                    is_observed     = EXCLUDED.is_observed,
                    trigger_filter  = EXCLUDED.trigger_filter,
                    trigger_exp     = EXCLUDED.trigger_exp,
                    trigger_count   = EXCLUDED.trigger_count,
                    observed_filter = EXCLUDED.observed_filter,
                    observed_exp    = EXCLUDED.observed_exp,
                    observed_count  = EXCLUDED.observed_count,
                    created_at      = CURRENT_TIMESTAMP
            ''', (target_id, obs_date, user_name, is_triggered, is_observed,
                  trigger_filter, trigger_exp, trigger_count,
                  observed_filter, observed_exp, observed_count))
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        print(f"Error upserting observation log: {e}")
    return False


def delete_observation_log(target_id, obs_date):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM observation_logs WHERE target_id = %s AND obs_date = %s',
                (target_id, obs_date)
            )
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            return deleted > 0
    except Exception as e:
        print(f"Error deleting observation log: {e}")
    return False
