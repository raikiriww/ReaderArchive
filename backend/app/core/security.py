from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

ALGORITHM = "HS256"
LEGACY_PASSWORD_ALGORITHM = "pbkdf2_sha256"
PAGE_TOKEN_COOKIE_BYTES = 32

password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> tuple[str, str, datetime]:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    token_id = secrets.token_urlsafe(PAGE_TOKEN_COOKIE_BYTES)
    payload = {"exp": expire, "sub": str(subject), "jti": token_id}
    encoded_jwt = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt, token_id, expire


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, stored_hash: str) -> tuple[bool, str | None]:
    if stored_hash.startswith(f"{LEGACY_PASSWORD_ALGORITHM}$"):
        verified = _verify_legacy_password(plain_password, stored_hash)
        return verified, get_password_hash(plain_password) if verified else None
    return password_hash.verify_and_update(plain_password, stored_hash)


def _verify_legacy_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != LEGACY_PASSWORD_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)
