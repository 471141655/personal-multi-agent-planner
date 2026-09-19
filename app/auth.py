from __future__ import annotations

import hashlib
import hmac

from app.config import get_settings


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str) -> bool:
    settings = get_settings()
    expected = settings.app_password_hash or hash_password(settings.app_password)
    return hmac.compare_digest(hash_password(password), expected)

