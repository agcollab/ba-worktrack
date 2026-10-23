"""Passwords, login tokens, CSRF tokens and encryption of stored secrets.

- Passwords are hashed with bcrypt (one-way: we can check a password, never read it back).
- Login tokens are JWTs signed with SECRET_KEY, kept in an HttpOnly cookie.
- JIRA / ADO tokens are encrypted with Fernet (two-way: the connector needs the real value).
"""
import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

JWT_ALGORITHM = "HS256"
# bcrypt only looks at the first 72 bytes; longer passwords are rejected by validation
MAX_PASSWORD_BYTES = 72


# ---- passwords ------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:MAX_PASSWORD_BYTES], bcrypt.gensalt(settings.BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:MAX_PASSWORD_BYTES], hashed.encode())
    except ValueError:  # malformed hash in the database
        return False


def password_problems(password: str) -> list[str]:
    """Return what is wrong with a new password (empty list = acceptable)."""
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        problems.append("at most 72 bytes")
    if not any(c.isdigit() for c in password):
        problems.append("a number")
    if not any(c.isalpha() for c in password):
        problems.append("a letter")
    return problems


# ---- login tokens -----------------------------------------------------------

def create_access_token(user_id: int, minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=minutes or settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """The user id inside a valid, unexpired token, else None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# ---- CSRF -------------------------------------------------------------------

def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


# ---- encryption of stored secrets -------------------------------------------

def _fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY
    if not key:
        # Derive a stable key from SECRET_KEY so a fresh install works out of the box
        digest = hashlib.sha256(("fernet:" + settings.SECRET_KEY).encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored token cannot be decrypted; was ENCRYPTION_KEY changed?") from exc
