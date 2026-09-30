"""auth schema — users, groups, usr_group, invitations, system settings,
object permissions, source permissions.

All SQL targets the 'Kinder' database auth schema.
Return dicts use backward-compatible key names matching the legacy kinder_web DB.
"""

import hashlib
import logging
import re
import secrets

from psycopg2 import extras

from . import get_db_connection

logger = logging.getLogger(__name__)

# Direct-login (username + password) accounts created by an admin without an email
# get a placeholder address in this RFC 2606 reserved TLD: it can never receive
# mail nor be verified by Google, so it is only an internal identity key.
PLACEHOLDER_EMAIL_DOMAIN = 'users.invalid'
USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')


def is_placeholder_email(email: str | None) -> bool:
    return bool(email) and email.strip().lower().endswith('@' + PLACEHOLDER_EMAIL_DOMAIN)


def placeholder_email_for(username: str) -> str:
    return f'{username.strip().lower()}@{PLACEHOLDER_EMAIL_DOMAIN}'


def valid_username(username: str | None) -> bool:
    return bool(username) and bool(USERNAME_RE.match(username))


# ---------------------------------------------------------------------------
# One-time schema migration: ensure api_key_requested_at column exists
# ---------------------------------------------------------------------------

def _ensure_api_key_request_col() -> None:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "ALTER TABLE auth.users "
                "ADD COLUMN IF NOT EXISTS api_key_requested_at TIMESTAMPTZ"
            )
            conn.commit()
    except Exception as e:
        logger.warning("_ensure_api_key_request_col: %s", e)

_ensure_api_key_request_col()


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
    for tf in ('api_key_requested_at', 'api_key_created_at', 'api_key_last_used_at'):
        if d.get(tf) and hasattr(d[tf], 'isoformat'):
            d[tf] = d[tf].isoformat()
    # API keys are stored hashed: the plaintext is never available after issue.
    d.pop('api_key', None)
    d.pop('api_key_hash', None)
    d['has_api_key'] = bool(d.get('has_api_key'))
    d['username'] = d.get('username') or None
    d['has_placeholder_email'] = is_placeholder_email(d.get('email'))
    d['api_key_request_pending'] = bool(d.get('api_key_requested_at'))
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

# Never select password_hash / api_key_hash here: these dicts reach templates, JSON
# and the session.
_USER_SELECT = (
    "SELECT u.usr_id, u.email, u.name, u.picture_url, u.roles, "
    "u.last_login, u.join_date, u.api_key_requested_at, "
    "(u.api_key_hash IS NOT NULL) AS has_api_key, u.api_key_hint, "
    "u.api_key_created_at, u.api_key_last_used_at, u.google_sub, u.username, "
    "(u.password_hash IS NOT NULL) AS has_password, "
    "COALESCE(u.must_change_password, FALSE) AS must_change_password, "
    "COALESCE(u.session_version, 0) AS session_version "
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


ROLE_LEVELS = {'guest': 0, 'user': 1, 'admin': 50, 'super_admin': 99}


def save_user(email: str, name: str = '', picture_url: str = '',
              is_admin: bool = False, role: str | None = None,
              username: str | None = None) -> dict | None:
    """Insert (or refresh) a user. ``role`` ('guest'/'user'/'admin') wins over ``is_admin``.
    ``username`` (direct-login name) is only set on insert."""
    if role in ROLE_LEVELS:
        roles = ROLE_LEVELS[role]
    else:
        roles = 50 if is_admin else 1
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "INSERT INTO auth.users (email, name, picture_url, roles, last_login, username) "
                "VALUES (%s,%s,%s,%s,now(),%s) "
                "ON CONFLICT (email) DO UPDATE "
                "SET name = EXCLUDED.name, picture_url = EXCLUDED.picture_url, "
                "    last_login = now() "
                "RETURNING usr_id, email, name, picture_url, roles, last_login, join_date, "
                "(api_key_hash IS NOT NULL) AS has_api_key",
                (email, name, picture_url, roles, username or None)
            )
            row = cur.fetchone()
            conn.commit()
        return _user_row_to_dict(row) if row else None
    except Exception as e:
        logger.error("save_user %s: %s", email, e)
        return None


def update_user(email: str, **kwargs) -> bool:
    """Update arbitrary user fields.  Accepted keys:
    name, picture_url, roles, role ('guest'/'user'/'admin'), is_admin (bool → roles 50/1),
    last_login. A super_admin (roles 99) is never downgraded by ``role``/``is_admin``.
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
    if 'role' in kwargs and kwargs['role'] in ROLE_LEVELS:
        kwargs = {k: v for k, v in kwargs.items() if k != 'is_admin'}  # explicit role wins
    for k, v in kwargs.items():
        if k == 'role':
            if v not in ROLE_LEVELS:
                continue
            sets.append("roles = CASE WHEN roles >= 99 THEN roles ELSE %s END")
            params.append(ROLE_LEVELS[v])
        elif k == 'is_admin':
            sets.append("roles = CASE WHEN roles >= 99 THEN roles ELSE %s END")
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


# ---------------------------------------------------------------------------
# Password (local) login — accounts are created by admins only
# ---------------------------------------------------------------------------

def get_password_hash(email: str) -> str | None:
    """Stored password hash for *email* (case-insensitive), or None."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT password_hash FROM auth.users WHERE lower(email) = lower(%s)",
            (email,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def get_login_account(identifier: str) -> tuple[str, str | None] | None:
    """(canonical email, password_hash) for a direct-login identifier.

    An identifier containing '@' is matched against the email, anything else
    against the username (usernames cannot contain '@'); both case-insensitive."""
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    column = 'email' if '@' in identifier else 'username'
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT email, password_hash FROM auth.users WHERE lower({column}) = lower(%s) "
            "ORDER BY usr_id LIMIT 1",
            (identifier,)
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else None


def username_taken(username: str, exclude_email: str | None = None) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM auth.users WHERE lower(username) = lower(%s) "
            "AND (%s::text IS NULL OR email <> %s) LIMIT 1",
            (username, exclude_email, exclude_email)
        )
        return cur.fetchone() is not None


def set_username(email: str, username: str) -> bool:
    """Give *email* a direct-login username (False if taken / user missing)."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE auth.users SET username = %s WHERE email = %s", (username, email))
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("set_username %s: %s", email, e)
        return False


def get_login_email(email: str) -> str | None:
    """Canonical stored email for a case-insensitive login identifier."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT email FROM auth.users WHERE lower(email) = lower(%s)", (email,))
        row = cur.fetchone()
    return row[0] if row else None


def set_password_hash(email: str, password_hash: str | None,
                      must_change: bool = False) -> int | None:
    """Set (or with None, remove) a user's password hash.

    Bumps ``session_version`` so every existing session of that user is logged
    out. Returns the new session_version, or None if the user does not exist."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET password_hash = %s, must_change_password = %s, "
                "password_changed_at = now(), "
                "session_version = COALESCE(session_version, 0) + 1 "
                "WHERE email = %s RETURNING session_version",
                (password_hash, bool(must_change and password_hash), email)
            )
            row = cur.fetchone()
            conn.commit()
        return row[0] if row else None
    except Exception as e:
        logger.error("set_password_hash %s: %s", email, e)
        return None


def bump_session_version(email: str) -> int | None:
    """Invalidate every existing session of *email* ("log out all devices").

    Returns the new session_version, or None if the user does not exist."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET session_version = COALESCE(session_version, 0) + 1 "
                "WHERE email = %s RETURNING session_version",
                (email,)
            )
            row = cur.fetchone()
            conn.commit()
        return row[0] if row else None
    except Exception as e:
        logger.error("bump_session_version %s: %s", email, e)
        return None


def set_google_sub(email: str, google_sub: str) -> bool:
    """Bind a Google account id to *email* (only when none is bound yet)."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET google_sub = %s WHERE email = %s AND google_sub IS NULL",
                (google_sub, email)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("set_google_sub %s: %s", email, e)
        return False


# ---------------------------------------------------------------------------
# API keys — only sha256(key) + the last 4 characters are stored
# ---------------------------------------------------------------------------

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def generate_api_key_for_user(email: str) -> str | None:
    """Generate (or replace) *email*'s API key and clear any pending request.

    Only the hash and a 4-character hint are stored. The plaintext key is
    returned exactly once so the caller can show it to the user."""
    api_key = secrets.token_urlsafe(32)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET api_key = NULL, api_key_hash = %s, api_key_hint = %s, "
                "api_key_created_at = now(), api_key_last_used_at = NULL, "
                "api_key_requested_at = NULL WHERE email = %s",
                (hash_api_key(api_key), api_key[-4:], email)
            )
            if cur.rowcount == 0:
                return None
            conn.commit()
        return api_key
    except Exception as e:
        logger.error("generate_api_key: %s", e)
        return None


def revoke_api_key(email: str) -> bool:
    """Admin action: remove a user's API key and clear any pending request."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET api_key = NULL, api_key_hash = NULL, api_key_hint = NULL, "
                "api_key_created_at = NULL, api_key_last_used_at = NULL, "
                "api_key_requested_at = NULL WHERE email = %s",
                (email,)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("revoke_api_key %s: %s", email, e)
        return False


def request_api_key(email: str) -> bool:
    """User action: mark that this user is requesting a new or reset API key."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE auth.users SET api_key_requested_at = now() WHERE email = %s",
                (email,)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("request_api_key %s: %s", email, e)
        return False


def get_api_key_requests() -> list[dict]:
    """Return users with a pending API key request, ordered by request time."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            cur.execute(
                "SELECT email, name, (api_key_hash IS NOT NULL) AS has_key, api_key_requested_at "
                "FROM auth.users WHERE api_key_requested_at IS NOT NULL "
                "ORDER BY api_key_requested_at ASC"
            )
            out = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get('api_key_requested_at') and hasattr(d['api_key_requested_at'], 'isoformat'):
                    d['api_key_requested_at'] = d['api_key_requested_at'].isoformat()
                out.append(d)
        return out
    except Exception as e:
        logger.error("get_api_key_requests: %s", e)
        return []


def get_user_by_api_key(api_key: str) -> dict | None:
    """User dict for a presented API key (looked up by its sha256), or None."""
    api_key = (api_key or '').strip()
    if not api_key or len(api_key) > 256:
        return None
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(
            f"{_USER_SELECT} WHERE u.api_key_hash = %s",
            (hash_api_key(api_key),)
        )
        row = cur.fetchone()
        if not row:
            return None
        d = _user_row_to_dict(row)
        # Last-used timestamp, written at most once per minute per key.
        try:
            cur.execute(
                "UPDATE auth.users SET api_key_last_used_at = now() WHERE usr_id = %s "
                "AND (api_key_last_used_at IS NULL "
                "     OR api_key_last_used_at < now() - interval '1 minute')",
                (d['usr_id'],)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning("get_user_by_api_key: last-used update failed: %s", e)
        cur.execute(
            "SELECT g.name FROM auth.usr_group ug "
            "JOIN auth.groups g ON ug.group_id = g.group_id "
            "WHERE ug.usr_id = %s AND ug.status = 'joined' ORDER BY g.name",
            (d['usr_id'],)
        )
        d['groups'] = [r['name'] for r in cur.fetchall()]
    # Same rule the web session uses (core.auth.refresh_user_session).
    d['is_admin'] = bool(d.get('is_admin'))
    d['is_great_lab_member'] = 'GREAT_Lab' in d['groups'] or d['is_admin']
    return d


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
# Page permissions  (stored in auth.system_settings as JSON)
# ---------------------------------------------------------------------------

def get_page_groups(page_key: str) -> list[str]:
    """Return extra group names allowed to access a private-area page."""
    import json
    raw = get_setting(f'page_perm:{page_key}')
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def set_page_groups(page_key: str, group_names: list[str]) -> bool:
    """Persist the list of extra group names for a private-area page."""
    import json
    return set_setting(f'page_perm:{page_key}', json.dumps(group_names))


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
                        user_roles: int | None = None) -> bool:
    """Return True if the user can open the object.

    Rules (same as ``transient._build_where(apply_permissions=True)``):
      * unknown object                       -> False
      * permission 'public' (or unset/other) -> True for everyone
      * restricted and ``user_email`` None    -> False
      * admin (``user_roles`` >= 50, or — when ``user_roles`` is None — the
        ``auth.users.roles`` of ``user_email`` >= 50) -> True
      * permission 'login'                    -> True for a non-guest account
        (roles >= 1: user/admin); guests are refused
      * permission 'groups'                   -> True only for a joined member of
        one of the object's groups (an empty group list means admins only)
    """
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
            if perm not in ('groups', 'login'):
                return True
            if not user_email:
                return False
            if user_roles is None:
                cur.execute("SELECT roles FROM auth.users WHERE lower(email) = lower(%s)",
                            (user_email,))
                r = cur.fetchone()
                user_roles = (r[0] or 0) if r else 0
            if user_roles >= 50:
                return True
            if perm == 'login':
                return user_roles >= 1   # guests (roles 0) do not see 'login' objects
            if not groups:
                return False
            cur.execute(
                "SELECT 1 FROM auth.usr_group ug "
                "JOIN auth.users u ON ug.usr_id = u.usr_id "
                "WHERE u.email = %s AND ug.group_id = ANY(%s) AND ug.status = 'joined' "
                "LIMIT 1",
                (user_email, groups)
            )
            return cur.fetchone() is not None
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
    """Replace all default_permissions rows with the given list.
    Each item: {source, permission, groups[int]}"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            # Delete all existing rows first, then re-insert from the batch.
            # This ensures removed entries are also deleted from the DB.
            cur.execute("DELETE FROM transient.default_permissions")
            for p in permissions:
                if not p.get('source'):
                    continue
                cur.execute(
                    "INSERT INTO transient.default_permissions "
                    "(source, permissions_set, groups) "
                    "VALUES (%s,%s,%s)",
                    (p['source'], p.get('permission', 'public'),
                     p.get('groups', []))
                )
            conn.commit()
        return True
    except Exception as e:
        logger.error("set_default_source_permissions_batch: %s", e)
        return False


def _system_default_for_source(source_name: str) -> str:
    """System-wide fallback permission when no default_permissions row exists.
    Sources whose name contains 'TNS' (case-insensitive) are public;
    everything else requires login."""
    if 'tns' in source_name.lower():
        return 'public'
    return 'login'


def filter_by_source_permissions(object_name: str, data_type: str,
                                  source_list: list,
                                  user_email: str | None = None,
                                  user_groups: list | None = None,
                                  is_admin: bool = False):
    """Return subset of sources/records the user is allowed to see.
    user_groups: list of group NAME strings from session.
    object_source_permissions.allowed_groups: INT[] (group IDs) in DB.
    NULL = login-mode override, [] = blocked, [ids] = specific groups."""
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

    user_group_set = set(user_groups or [])

    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=extras.RealDictCursor)
            # Per-object overrides (allowed_groups is INT[] of group IDs)
            cur.execute(
                "SELECT source_name, is_public, allowed_groups "
                "FROM transient.object_source_permissions "
                "WHERE object_name = %s AND data_type = %s AND source_name = ANY(%s)",
                (object_name, data_type, source_names)
            )
            overrides = {r['source_name']: r for r in cur.fetchall()}

            # System-wide defaults (groups stored as INT[] of group IDs)
            cur.execute(
                "SELECT source, permissions_set, groups "
                "FROM transient.default_permissions "
                "WHERE source = ANY(%s)",
                (source_names,)
            )
            defaults = {r['source']: r for r in cur.fetchall()}

            # Build id->name map for defaults comparison
            cur.execute("SELECT name, group_id FROM auth.groups")
            id_to_name = {r['group_id']: r['name'] for r in cur.fetchall()}

        allowed_sources = set()
        for src in source_names:
            if src in overrides:
                r = overrides[src]
                if r['is_public']:
                    allowed_sources.add(src)
                elif user_email is None:
                    pass  # not logged in, not public
                else:
                    ag = r.get('allowed_groups')  # None = login mode, [] = blocked, [ids...] = specific groups
                    if ag is None:
                        allowed_sources.add(src)  # login mode override: any logged-in user
                    elif len(ag) == 0:
                        pass  # blocked — empty array means nobody except admin
                    else:
                        ag_names = {id_to_name[gid] for gid in ag if gid in id_to_name}
                        if user_group_set & ag_names:
                            allowed_sources.add(src)
                    # no intersection → denied
            elif src in defaults:
                d = defaults[src]
                perm = d.get('permissions_set', 'login')
                if perm == 'public':
                    allowed_sources.add(src)
                elif perm == 'login':
                    if user_email is not None:
                        allowed_sources.add(src)
                else:  # 'groups'
                    if user_email is not None:
                        group_ids = d.get('groups') or []
                        default_group_names = {id_to_name[gid] for gid in group_ids if gid in id_to_name}
                        # Empty / unresolvable group list = nobody but admins
                        # (matches the admin UI semantics).
                        if user_group_set & default_group_names:
                            allowed_sources.add(src)
            else:
                # System default: TNS sources are public, everything else needs login
                perm = _system_default_for_source(src)
                if perm == 'public':
                    allowed_sources.add(src)
                elif user_email is not None:
                    allowed_sources.add(src)

        if is_record_list:
            return [
                item for item in source_list
                if (item.get('telescope') or item.get('source') or item.get('source_name') or 'Unknown') in allowed_sources
            ]
        return [src for src in source_list if src in allowed_sources]
    except Exception as e:
        # Fail closed: permissions could not be determined, so show nothing.
        logger.error("filter_by_source_permissions: %s", e)
        return []


# ---------------------------------------------------------------------------
# Data consistency (no-ops in new single-DB design; kept for compat)
# ---------------------------------------------------------------------------

def check_data_consistency() -> dict:
    return {'status': 'ok', 'issues': []}


def clean_data_consistency() -> int:
    return 0
