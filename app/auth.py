from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Optional

import jwt

from .config import SETTINGS


def _pbkdf2_hash(password: str, salt: bytes) -> bytes:
    """Calcule un digest PBKDF2-HMAC pour un mot de passe."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)


def hash_password(password: str) -> str:
    """Retourne un hash sale encode en base64."""
    salt = os.urandom(16)
    digest = _pbkdf2_hash(password, salt)
    return base64.b64encode(salt + digest).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifie un mot de passe par rapport au hash stocke."""
    try:
        raw = base64.b64decode(stored_hash.encode("utf-8"))
        salt = raw[:16]
        digest = raw[16:]
        candidate = _pbkdf2_hash(password, salt)
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def create_access_token(username: str) -> str:
    """Cree un token JWT signe."""
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + SETTINGS.jwt_exp_minutes * 60,
    }
    return jwt.encode(payload, SETTINGS.secret_key, algorithm=SETTINGS.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Decode un JWT et retourne le username, ou None si invalide."""
    try:
        payload = jwt.decode(token, SETTINGS.secret_key, algorithms=[SETTINGS.jwt_algorithm])
        return payload.get("sub")
    except Exception:
        return None
