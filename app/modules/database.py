import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager

DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'kinder.db')

def init_database():
    """初始化資料庫和建立表格"""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        
        # 建立使用者表格
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                picture TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                last_login TEXT,
                invited_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 建立群組表格
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                name TEXT PRIMARY KEY,
                description TEXT,
                created_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users (email)
            )
        ''')
        
        # 建立使用者群組關聯表格
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_groups (
                user_email TEXT,
                group_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_email, group_name),
                FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE,
                FOREIGN KEY (group_name) REFERENCES groups (name) ON DELETE CASCADE
            )
        ''')
        
        # 建立邀請表格
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invitations (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                invited_by TEXT,
                invited_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                accepted_at TEXT,
                FOREIGN KEY (invited_by) REFERENCES users (email)
            )
        ''')
        
        conn.commit()

@contextmanager
def get_db_connection():
    """資料庫連接上下文管理器"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# 使用者相關操作
def get_users():
    """取得所有使用者"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()
        
        result = {}
        for user in users:
            user_dict = dict(user)
            # 取得使用者的群組
            cursor.execute('''
                SELECT group_name FROM user_groups 
                WHERE user_email = ?
            ''', (user['email'],))
            groups = [row[0] for row in cursor.fetchall()]
            user_dict['groups'] = groups
            result[user['email']] = user_dict
        
        return result

def save_user(email, name, picture=None, is_admin=False, last_login=None, invited_at=None):
    """儲存或更新使用者"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (email, name, picture, is_admin, last_login, invited_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email, name, picture, is_admin, last_login, invited_at))
        conn.commit()
        return True

def update_user(email, **kwargs):
    """更新使用者資訊"""
    if not kwargs:
        return False
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 建構動態更新查詢
        set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [email]
        
        cursor.execute(f'''
            UPDATE users SET {set_clause} WHERE email = ?
        ''', values)
        conn.commit()
        return cursor.rowcount > 0

def delete_user(email):
    """刪除使用者並從所有群組中移除"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 先刪除用戶的群組關聯
        cursor.execute('DELETE FROM user_groups WHERE user_email = ?', (email,))
        # 再刪除用戶
        cursor.execute('DELETE FROM users WHERE email = ?', (email,))
        conn.commit()
        return cursor.rowcount > 0

def user_exists(email):
    """檢查使用者是否存在"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM users WHERE email = ?', (email,))
        return cursor.fetchone() is not None

# 群組相關操作
def get_groups():
    """取得所有群組"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM groups')
        groups = cursor.fetchall()
        
        result = {}
        for group in groups:
            group_dict = dict(group)
            # 取得群組成員
            cursor.execute('''
                SELECT user_email FROM user_groups 
                WHERE group_name = ?
            ''', (group['name'],))
            members = [row[0] for row in cursor.fetchall()]
            group_dict['members'] = members
            result[group['name']] = group_dict
        
        return result

def create_group(name, description=None, created_by=None):
    """建立群組"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO groups (name, description, created_by)
                VALUES (?, ?, ?)
            ''', (name, description, created_by))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def delete_group(name):
    """刪除群組並移除所有用戶關聯"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 先刪除群組的用戶關聯
        cursor.execute('DELETE FROM user_groups WHERE group_name = ?', (name,))
        # 再刪除群組
        cursor.execute('DELETE FROM groups WHERE name = ?', (name,))
        conn.commit()
        return cursor.rowcount > 0

def group_exists(name):
    """檢查群組是否存在"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM groups WHERE name = ?', (name,))
        return cursor.fetchone() is not None

# 使用者群組關聯操作
def add_user_to_group(user_email, group_name):
    """將使用者加入群組"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO user_groups (user_email, group_name)
                VALUES (?, ?)
            ''', (user_email, group_name))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def remove_user_from_group(user_email, group_name):
    """將使用者從群組移除"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM user_groups 
            WHERE user_email = ? AND group_name = ?
        ''', (user_email, group_name))
        conn.commit()
        return cursor.rowcount > 0

def user_in_group(user_email, group_name):
    """檢查使用者是否在群組中"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM user_groups 
            WHERE user_email = ? AND group_name = ?
        ''', (user_email, group_name))
        return cursor.fetchone() is not None

# 邀請相關操作
def get_invitations():
    """取得所有邀請"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM invitations')
        invitations = cursor.fetchall()
        
        result = {}
        for invitation in invitations:
            result[invitation['token']] = dict(invitation)
        
        return result

def create_invitation(token, email, is_admin=False, invited_by=None):
    """建立邀請"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO invitations (token, email, is_admin, invited_by)
                VALUES (?, ?, ?, ?)
            ''', (token, email, is_admin, invited_by))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def get_invitation(token):
    """取得特定邀請"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM invitations WHERE token = ?', (token,))
        invitation = cursor.fetchone()
        return dict(invitation) if invitation else None

def update_invitation(token, **kwargs):
    """更新邀請狀態"""
    if not kwargs:
        return False
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [token]
        
        cursor.execute(f'''
            UPDATE invitations SET {set_clause} WHERE token = ?
        ''', values)
        conn.commit()
        return cursor.rowcount > 0

def delete_invitation(token):
    """刪除邀請"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM invitations WHERE token = ?', (token,))
        conn.commit()
        return cursor.rowcount > 0

def clean_accepted_invitations():
    """清理所有已接受的邀請"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM invitations WHERE status = ?', ('accepted',))
        conn.commit()
        return cursor.rowcount

def check_data_consistency():
    """檢查並返回資料一致性問題"""
    issues = {
        'orphaned_user_groups': [],
        'orphaned_group_users': [],
        'missing_users': [],
        'missing_groups': []
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 檢查孤立的用戶群組關聯（用戶不存在但群組關聯存在）
        cursor.execute('''
            SELECT ug.user_email, ug.group_name 
            FROM user_groups ug
            LEFT JOIN users u ON ug.user_email = u.email
            WHERE u.email IS NULL
        ''')
        rows = cursor.fetchall()
        issues['orphaned_user_groups'] = [[row[0], row[1]] for row in rows]
        
        # 檢查孤立的群組用戶關聯（群組不存在但用戶關聯存在）
        cursor.execute('''
            SELECT ug.user_email, ug.group_name 
            FROM user_groups ug
            LEFT JOIN groups g ON ug.group_name = g.name
            WHERE g.name IS NULL
        ''')
        rows = cursor.fetchall()
        issues['orphaned_group_users'] = [[row[0], row[1]] for row in rows]
        
        # 統計問題
        issues['total_issues'] = (
            len(issues['orphaned_user_groups']) + 
            len(issues['orphaned_group_users'])
        )
    
    return issues

def clean_data_consistency():
    """清理資料一致性問題"""
    cleaned_count = 0
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 清理孤立的用戶群組關聯
        cursor.execute('''
            DELETE FROM user_groups 
            WHERE user_email NOT IN (SELECT email FROM users)
        ''')
        cleaned_count += cursor.rowcount
        
        # 清理孤立的群組用戶關聯
        cursor.execute('''
            DELETE FROM user_groups 
            WHERE group_name NOT IN (SELECT name FROM groups)
        ''')
        cleaned_count += cursor.rowcount
        
        conn.commit()
    
    return cleaned_count
