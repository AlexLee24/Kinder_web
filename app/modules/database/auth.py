"""auth schema — users, groups, usr_group, invitations, system settings,
object permissions, source permissions.

All SQL targets the 'Kinder' database auth schema.
Return dicts use backward-compatible key names matching the legacy kinder_web DB.
"""

import logging
import secrets
import string
from datetime import datetime

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _user_row_to_dict(row) -> dict:
    """Map auth.users row to the dict shape expected by legacy callers."""
    d = dict(row)
    # Backward compat aliases
    d['email'] = d.get('email', '')
    d['is_admin'] = (d.get('roles', 0) or 0) >= 50
    d['is_super_admin'] = (d.get('roles', 0) or 0) >= 99
    d['role_level'] = d.get('roles', 0)
    # role string alias (used by templates)
    roles = d.get('roles', 0) or 0
    d['role'] = 'admin' if roles >= 50 else ('user' if roles >= 1 else 'guest')
    d['profile_picture'] = d.get('picture_url', '')
    d['picture'] = d.get('picture_url', '')  # template alias
    d['display_name'] = d.get('name', '')
    d.setdefault('groups', [])   # filled in by get_users()
    if d.get('last_login') and hasattr(d['last_login'], 'isoformat'):
        d['last_login'] = d['last_login'].isoformat()
    if d.get('join_date') and hasattr(d['join_date'], 'isoformat'):
        d['join_date'] = d['join_date'].isoformat()
    return d


def _group_row_to_dict(row) -> dict:
    d = dict(row)
    d['group_name'] = d.get('name', '')
    d['manager_email'] = d.get('manager_email', None)
    if d.get('created_at') and hasattr(d['created_at'], 'isoformat'):
        d['created_at'] = d['created_at'].isoformat()
    return d


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

_USER_SELECT = (
    "SELECT u.usr_id, u.email, u.name, u.picture_url, u.roles, "
    "u.last_login, u.join_date, u.api_key "
    "FROM auth.users u"
)


def get_user(email: str) -> dict | None:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"{_USER_SELECT} WHERE u.email = %s", (email,))
        row = cur.fetchone()
        if not row:
            return None
        d = _user_row_to_dict(row)
        # Include group membership in a single extra query (far cheaper than get_users())
        cur.execute(
            "SELECT g.name FROM auth.usr_group ug "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE ug.usr_id = %s AND ug.status = 'joined' ORDER BY g.name",
            (d['usr_id'],)
        )
        d['groups'] = [r['name'] for r in cur.fetchall()]
    return d


def get_users() -> dict[str, dict]:
    """Return {email: user_dict} with groups list included per user."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"{_USER_SELECT} ORDER BY u.join_date DESC")
        rows = [_user_row_to_dict(r) for r in cur.fetchall()]
        # Fetch group memberships for all users in one query
        cur.execute("""
            SELECT u.email, g.name AS group_name
            FROM auth.usr_group ug
            JOIN auth.users u  ON ug.usr_id   = u.usr_id
            JOIN auth.groups g ON ug.group_id  = g.group_id
            WHERE ug.status = 'joined'
        """)
        memberships = cur.fetchall()
    users: dict[str, dict] = {}
    for r in rows:
        users[r['email']] = r
    for m in memberships:
        email = m['email']
        if email in users:
            users[email]['groups'].append(m['group_name'])
    return users


def user_exists(email: str) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM auth.users WHERE email = %s", (email,))
        return cur.fetchone() is not None


def save_user(email: str, name: str = '', picture_url: str = '',
              is_admin: bool = False) -> dict | None:
    roles = 50 if is_admin else 1
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "INSERT INTO auth.users (email, name, picture_url, roles) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (email) DO UPDATE "
                "SET name = EXCLUDED.name, picture_url = EXCLUDED.picture_url, "
                "    last_login = now() "
                "RETURNING usr_id, email, name, picture_url, roles, last_login, join_date, api_key",
                (email, name, picture_url, roles)
            )
            row = cur.fetchone()
            conn.commit()
        return _user_row_to_dict(row) if row else None
    except Exception as e:
        logger.error("save_user %s: %s", email, e)
        return None


def update_user(email: str, **kwargs) -> bool:
    """Update arbitrary user fields.  Accepted keys:
    name, picture_url, roles, is_admin (bool → roles 50/1).
    """
    mapping = {
        'name':            'name',
        'picture_url':     'picture_url',
        'picture':         'picture_url',
        'roles':           'roles',
        'profile_picture': 'picture_url',
        'display_name':    'name',
        'last_login':      'last_login',
    }
    sets = []
    params = []
    for k, v in kwargs.items():
        if k == 'is_admin':
            sets.append("roles = %s")
            params.append(50 if v else 1)
        elif k in mapping:
            sets.append(f"{mapping[k]} = %s")
            params.append(v)
    if not sets:
        return False
    params.append(email)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE auth.users SET {', '.join(sets)} WHERE email = %s",
                params
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_user %s: %s", email, e)
        return False


def delete_user(email: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth.users WHERE email = %s", (email,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_user %s: %s", email, e)
        return False


def generate_api_key_for_user(email: str) -> str | None:
    alphabet = string.ascii_letters + string.digits
    api_key = ''.join(secrets.choice(alphabet) for _ in range(48))
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET api_key = %s WHERE email = %s",
                (api_key, email)
            )
            if cur.rowcount == 0:
                return None
            conn.commit()
        return api_key
    except Exception as e:
        logger.error("generate_api_key: %s", e)
        return None


def get_user_by_api_key(api_key: str) -> dict | None:
    if not api_key:
        return None
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            f"{_USER_SELECT} WHERE u.api_key = %s",
            (api_key,)
        )
        row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

_GROUP_SELECT = (
    "SELECT g.group_id, g.name, g.description, g.joinable, "
    "g.create_by, g.manager, "
    "u.email AS manager_email, u.name AS manager_name "
    "FROM auth.groups g "
    "LEFT JOIN auth.users u ON g.manager = u.usr_id"
)


def get_groups(user_email: str | None = None) -> dict[str, dict]:
    """Return {group_name: group_dict} with members list per group.
    If user_email given, only return groups that user belongs to."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        if user_email:
            cur.execute(
                f"{_GROUP_SELECT} "
                "WHERE EXISTS ("
                "  SELECT 1 FROM auth.usr_group ug "
                "  JOIN auth.users u2 ON ug.usr_id = u2.usr_id "
                "  WHERE ug.group_id = g.group_id AND u2.email = %s AND ug.status = 'joined'"
                ") ORDER BY g.name",
                (user_email,)
            )
        else:
            cur.execute(f"{_GROUP_SELECT} ORDER BY g.name")
        rows = [_group_row_to_dict(r) for r in cur.fetchall()]
        # Fetch all members in one query
        cur.execute("""
            SELECT g.name AS group_name, u.email
            FROM auth.usr_group ug
            JOIN auth.groups g ON ug.group_id = g.group_id
            JOIN auth.users  u ON ug.usr_id   = u.usr_id
            WHERE ug.status = 'joined'
        """)
        memberships = cur.fetchall()
    groups: dict[str, dict] = {}
    for r in rows:
        r.setdefault('members', [])
        groups[r['name']] = r
    for m in memberships:
        gn = m['group_name']
        if gn in groups:
            groups[gn]['members'].append(m['email'])
    return groups


def get_all_groups() -> list[dict]:
    return get_groups()


def create_group(name: str, description: str = '',
                 creator_email: str | None = None,
                 manager_email: str | None = None,
                 joinable: bool = True) -> dict | None:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            creator_id = None
            manager_id = None
            if creator_email:
                cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (creator_email,))
                r = cur.fetchone()
                creator_id = r['usr_id'] if r else None
            if manager_email:
                cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (manager_email,))
                r = cur.fetchone()
                manager_id = r['usr_id'] if r else None
            cur.execute(
                "INSERT INTO auth.groups (name, description, joinable, create_by, manager) "
                "VALUES (%s,%s,%s,%s,%s) "
                "RETURNING group_id, name, description, joinable, create_by, manager",
                (name, description, joinable, creator_id, manager_id)
            )
            row = cur.fetchone()
            conn.commit()
        return _group_row_to_dict(row) if row else None
    except Exception as e:
        logger.error("create_group %s: %s", name, e)
        return None


def delete_group(name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth.groups WHERE name = %s", (name,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_group %s: %s", name, e)
        return False


def group_exists(name: str) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM auth.groups WHERE name = %s", (name,))
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# User ↔ Group membership  (auth.usr_group)
# ---------------------------------------------------------------------------

def add_user_to_group(email: str, group_name: str,
                      status: str = 'joined') -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (email,))
            ur = cur.fetchone()
            cur.execute("SELECT group_id FROM auth.groups WHERE name=%s", (group_name,))
            gr = cur.fetchone()
            if not ur or not gr:
                return False
            cur.execute(
                "INSERT INTO auth.usr_group (usr_id, group_id, status) "
                "VALUES (%s,%s,%s) "
                "ON CONFLICT (usr_id, group_id) DO UPDATE SET status = EXCLUDED.status",
                (ur[0], gr[0], status)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("add_user_to_group %s %s: %s", email, group_name, e)
        return False


def remove_user_from_group(email: str, group_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM auth.usr_group "
                "WHERE usr_id = (SELECT usr_id FROM auth.users WHERE email=%s LIMIT 1) "
                "AND group_id = (SELECT group_id FROM auth.groups WHERE name=%s LIMIT 1)",
                (email, group_name)
            )
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("remove_user_from_group: %s", e)
        return False


def user_in_group(email: str, group_name: str) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM auth.usr_group ug "
            "JOIN auth.users u ON ug.usr_id = u.usr_id "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE u.email = %s AND g.name = %s AND ug.status = 'joined'",
            (email, group_name)
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Group join requests  (same table, status='request')
# ---------------------------------------------------------------------------

def create_group_request(email: str, group_name: str) -> bool:
    return add_user_to_group(email, group_name, status='request')


def get_group_requests(group_name: str | None = None) -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        if group_name:
            cur.execute(
                "SELECT ug.usr_id, ug.group_id, ug.status, ug.created_at, "
                "u.email, u.name AS user_name, g.name AS group_name "
                "FROM auth.usr_group ug "
                "JOIN auth.users u ON ug.usr_id = u.usr_id "
                "JOIN auth.groups g ON ug.group_id = g.group_id "
                "WHERE ug.status = 'request' AND g.name = %s",
                (group_name,)
            )
        else:
            cur.execute(
                "SELECT ug.usr_id, ug.group_id, ug.status, ug.created_at, "
                "u.email, u.name AS user_name, g.name AS group_name "
                "FROM auth.usr_group ug "
                "JOIN auth.users u ON ug.usr_id = u.usr_id "
                "JOIN auth.groups g ON ug.group_id = g.group_id "
                "WHERE ug.status = 'request' "
                "ORDER BY ug.created_at DESC"
            )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            if d.get('created_at') and hasattr(d['created_at'], 'isoformat'):
                d['created_at'] = d['created_at'].isoformat()
            out.append(d)
        return out


def get_group_request(email: str, group_name: str) -> dict | None:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            "SELECT ug.usr_id, ug.group_id, ug.status, ug.created_at, "
            "u.email, u.name AS user_name, g.name AS group_name "
            "FROM auth.usr_group ug "
            "JOIN auth.users u ON ug.usr_id = u.usr_id "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE u.email = %s AND g.name = %s",
            (email, group_name)
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_user_group_requests(email: str) -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            "SELECT ug.usr_id, ug.group_id, ug.status, ug.created_at, "
            "u.email, g.name AS group_name "
            "FROM auth.usr_group ug "
            "JOIN auth.users u ON ug.usr_id = u.usr_id "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE u.email = %s ORDER BY ug.created_at DESC",
            (email,)
        )
        return [dict(r) for r in cur.fetchall()]


def update_group_request_status(email: str, group_name: str,
                                 new_status: str) -> bool:
    """new_status: 'joined' | 'rejected' | 'request'"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.usr_group SET status = %s "
                "WHERE usr_id = (SELECT usr_id FROM auth.users WHERE email=%s LIMIT 1) "
                "AND group_id = (SELECT group_id FROM auth.groups WHERE name=%s LIMIT 1)",
                (new_status, email, group_name)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_group_request_status: %s", e)
        return False


def delete_group_request(email: str, group_name: str) -> bool:
    return remove_user_from_group(email, group_name)


# ---------------------------------------------------------------------------
# Invitations  (auth.invitations — created by _ensure_extra_tables)
# ---------------------------------------------------------------------------

def get_invitations(status: str = 'pending') -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            "SELECT token, email, is_admin, role, invited_by, "
            "invited_at, status, accepted_at "
            "FROM auth.invitations WHERE status = %s ORDER BY invited_at DESC",
            (status,)
        )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            for tf in ('invited_at', 'accepted_at'):
                if d.get(tf) and hasattr(d[tf], 'isoformat'):
                    d[tf] = d[tf].isoformat()
            out.append(d)
        return out


def create_invitation(email: str = '', is_admin: bool = False,
                      role: str = 'user',
                      invited_by_email: str | None = None) -> str | None:
    token = secrets.token_urlsafe(32)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            invited_by = None
            if invited_by_email:
                cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (invited_by_email,))
                r = cur.fetchone()
                invited_by = r[0] if r else None
            cur.execute(
                "INSERT INTO auth.invitations "
                "(token, email, is_admin, role, invited_by) "
                "VALUES (%s,%s,%s,%s,%s)",
                (token, email or None, is_admin, role, invited_by)
            )
            conn.commit()
        return token
    except Exception as e:
        logger.error("create_invitation: %s", e)
        return None


def get_invitation(token: str) -> dict | None:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM auth.invitations WHERE token = %s",
            (token,)
        )
        row = cur.fetchone()
    if row:
        d = dict(row)
        for tf in ('invited_at', 'accepted_at'):
            if d.get(tf) and hasattr(d[tf], 'isoformat'):
                d[tf] = d[tf].isoformat()
        return d
    return None


def update_invitation(token: str, **kwargs) -> bool:
    sets = []
    params = []
    allowed = {'email', 'is_admin', 'role', 'status', 'accepted_at'}
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return False
    params.append(token)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE auth.invitations SET {', '.join(sets)} WHERE token = %s",
                params
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_invitation: %s", e)
        return False


def delete_invitation(token: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth.invitations WHERE token = %s", (token,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_invitation: %s", e)
        return False


def clean_accepted_invitations() -> int:
    """Delete invitations with status='accepted'."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM auth.invitations WHERE status = 'accepted'")
            n = cur.rowcount
            conn.commit()
        return n
    except Exception as e:
        logger.error("clean_accepted_invitations: %s", e)
        return 0


# ---------------------------------------------------------------------------
# System settings  (auth.system_settings)
# ---------------------------------------------------------------------------

def get_setting(key: str, default=None):
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM auth.system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        return row[0] if row else default
    except Exception as e:
        logger.error("get_setting %s: %s", key, e)
        return default


def set_setting(key: str, value: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO auth.system_settings (key, value) VALUES (%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                (key, str(value))
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("set_setting %s: %s", key, e)
        return False


# ---------------------------------------------------------------------------
# Object permissions  (backed by transient.objects.permission + .groups)
# ---------------------------------------------------------------------------

def get_object_permissions(object_name: str) -> dict:
    """Return {permission, groups} for named object."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT permission, groups FROM transient.objects WHERE name = %s LIMIT 1",
            (object_name,)
        )
        row = cur.fetchone()
    if row:
        return {'permission': row[0], 'groups': row[1] or []}
    return {'permission': 'public', 'groups': []}


def grant_object_permission(object_name: str, group_name: str,
                            granted_by: str = '') -> bool:
    """Add group_name to transient.objects.groups; set permission='groups'."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT group_id FROM auth.groups WHERE name=%s", (group_name,))
            r = cur.fetchone()
            if not r:
                return False
            gid = r[0]
            cur.execute(
                "UPDATE transient.objects "
                "SET permission = 'groups', "
                "    groups = (SELECT array_agg(DISTINCT x) FROM unnest(groups || ARRAY[%s]) x) "
                "WHERE name = %s",
                (gid, object_name)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("grant_object_permission: %s", e)
        return False


def revoke_object_permission(object_name: str, group_name: str) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT group_id FROM auth.groups WHERE name=%s", (group_name,))
            r = cur.fetchone()
            if not r:
                return False
            gid = r[0]
            cur.execute(
                "UPDATE transient.objects "
                "SET groups = array_remove(groups, %s) "
                "WHERE name = %s",
                (gid, object_name)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("revoke_object_permission: %s", e)
        return False


def check_object_access(object_name: str, user_email: str | None = None,
                        user_roles: int = 0) -> bool:
    """Return True if the user can access the object."""
    # Admins always have access
    if user_roles >= 50:
        return True
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT permission, groups FROM transient.objects WHERE name = %s LIMIT 1",
                (object_name,)
            )
            row = cur.fetchone()
        if row is None:
            return False
        perm, groups = row
        if perm == 'public':
            return True
        if user_email is None:
            return False
        if perm == 'login':
            return True
        if perm == 'groups' and groups:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM auth.usr_group ug "
                    "JOIN auth.users u ON ug.usr_id = u.usr_id "
                    "WHERE u.email = %s AND ug.group_id = ANY(%s) AND ug.status = 'joined' "
                    "LIMIT 1",
                    (user_email, groups)
                )
                return cur.fetchone() is not None
        return False
    except Exception as e:
        logger.error("check_object_access: %s", e)
        return False


# ---------------------------------------------------------------------------
# Source-level permissions  (transient.object_source_permissions)
# ---------------------------------------------------------------------------

def get_source_permissions(object_name: str,
                           data_type: str = 'phot') -> list[dict]:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT id, object_name, data_type, source_name, "
                "allowed_groups, is_public, updated_at "
                "FROM transient.object_source_permissions "
                "WHERE object_name = %s AND data_type = %s",
                (object_name, data_type)
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_source_permissions: %s", e)
        return []


def get_default_source_permissions(source_name: str | None = None) -> list[dict]:
    """Return defaults from transient.default_permissions."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            if source_name:
                cur.execute(
                    "SELECT source, permissions_set AS permission, groups "
                    "FROM transient.default_permissions WHERE source = %s",
                    (source_name,)
                )
            else:
                cur.execute(
                    "SELECT source, permissions_set AS permission, groups "
                    "FROM transient.default_permissions"
                )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_default_source_permissions: %s", e)
        return []


def set_source_permissions_batch(object_name: str, data_type: str,
                                  permissions: list[dict]) -> bool:
    """Each item in permissions: {source_name, is_public, allowed_groups[]}"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            for p in permissions:
                cur.execute(
                    "INSERT INTO transient.object_source_permissions "
                    "(object_name, data_type, source_name, is_public, allowed_groups) "
                    "VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (object_name, data_type, source_name) DO UPDATE "
                    "SET is_public=EXCLUDED.is_public, "
                    "    allowed_groups=EXCLUDED.allowed_groups, "
                    "    updated_at=now()",
                    (object_name, data_type,
                     p['source_name'], p.get('is_public', False),
                     p.get('allowed_groups'))
                )
            conn.commit()
        return True
    except Exception as e:
        logger.error("set_source_permissions_batch: %s", e)
        return False


def set_default_source_permissions_batch(permissions: list[dict]) -> bool:
    """Each item: {source, permission, groups[]}"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            for p in permissions:
                cur.execute(
                    "INSERT INTO transient.default_permissions "
                    "(source, permissions_set, groups) "
                    "VALUES (%s,%s,%s) "
                    "ON CONFLICT (source) DO UPDATE "
                    "SET permissions_set=EXCLUDED.permissions_set, "
                    "    groups=EXCLUDED.groups",
                    (p['source'], p.get('permission', 'public'),
                     p.get('groups', []))
                )
            conn.commit()
        return True
    except Exception as e:
        logger.error("set_default_source_permissions_batch: %s", e)
        return False


def filter_by_source_permissions(object_name: str, data_type: str,
                                  source_list: list,
                                  user_email: str | None = None,
                                  user_groups: list[int] | None = None,
                                  is_admin: bool = False):
    """Return subset of sources or source-backed records the user is allowed to see."""
    if not source_list:
        return []
    if is_admin:
        return source_list

    is_record_list = isinstance(source_list[0], dict)
    source_names = []
    if is_record_list:
        for item in source_list:
            source_names.append(
                item.get('telescope') or item.get('source') or item.get('source_name') or 'Unknown'
            )
    else:
        source_names = list(source_list)

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT source_name, is_public, allowed_groups "
                "FROM transient.object_source_permissions "
                "WHERE object_name = %s AND data_type = %s AND source_name = ANY(%s)",
                (object_name, data_type, source_names)
            )
            rows = {r['source_name']: r for r in cur.fetchall()}

        allowed_sources = set()
        for src in source_names:
            if src not in rows:
                # No override → default public
                allowed_sources.add(src)
                continue
            r = rows[src]
            if r['is_public']:
                allowed_sources.add(src)
                continue
            if user_email is None:
                continue
            ag = r.get('allowed_groups') or []
            if not ag or (user_groups and any(g in ag for g in user_groups)):
                allowed_sources.add(src)

        if is_record_list:
            return [
                item for item in source_list
                if (item.get('telescope') or item.get('source') or item.get('source_name') or 'Unknown') in allowed_sources
            ]
        return [src for src in source_list if src in allowed_sources]
    except Exception as e:
        logger.error("filter_by_source_permissions: %s", e)
        return source_list


# ---------------------------------------------------------------------------
# Data consistency (no-ops in new single-DB design; kept for compat)
# ---------------------------------------------------------------------------

def check_data_consistency() -> dict:
    return {'status': 'ok', 'issues': []}


def clean_data_consistency() -> int:
    return 0
