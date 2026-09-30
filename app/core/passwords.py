"""Password hashing and policy for admin-created (non-Google) accounts.

Hashes use werkzeug's default scheme (scrypt, salted). Plain passwords are never
stored or logged.
"""
from werkzeug.security import check_password_hash, generate_password_hash

MIN_LENGTH = 10
MAX_LENGTH = 128   # caps hashing cost per request

# Verified when the account does not exist or has no password, so a failed
# login takes the same time either way (no account enumeration by timing).
_DUMMY_HASH = generate_password_hash('kinder-dummy-password-never-valid')


def password_problem(password, email: str = '') -> str | None:
    """Return a human-readable reason the password is unacceptable, or None."""
    if not isinstance(password, str):
        return 'Password is required.'
    if len(password) < MIN_LENGTH:
        return f'Password must be at least {MIN_LENGTH} characters.'
    if len(password) > MAX_LENGTH:
        return f'Password must be at most {MAX_LENGTH} characters.'
    if password.strip() != password:
        return 'Password must not start or end with spaces.'
    if len(set(password)) < 4:
        return 'Password is too simple.'
    lowered = password.lower()
    local_part = (email or '').split('@')[0].lower()
    if (email and lowered == email.lower()) or (len(local_part) >= 4 and local_part in lowered):
        return 'Password must not contain your email address.'
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash: str | None, password) -> bool:
    """Constant-work check: always runs one hash verification."""
    if not isinstance(password, str) or not password or len(password) > MAX_LENGTH:
        check_password_hash(_DUMMY_HASH, 'x')
        return False
    if not stored_hash:
        check_password_hash(_DUMMY_HASH, password)
        return False
    try:
        return check_password_hash(stored_hash, password)
    except (ValueError, TypeError):
        return False
