from __future__ import annotations

import hashlib
import hmac
import base64
import binascii
import json
import time

from app.config import get_settings


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str) -> bool:
    settings = get_settings()
    expected = settings.app_password_hash or hash_password(settings.app_password)
    return hmac.compare_digest(hash_password(password), expected)


def _token_secret() -> bytes:
    settings = get_settings()
    return (settings.app_password_hash or hash_password(settings.app_password)).encode("utf-8")


def issue_access_token(user_id: int = 1) -> str:
    settings = get_settings()
    payload = {"sub": user_id, "exp": int(time.time()) + settings.auth_token_ttl_seconds}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).rstrip(b"=")
    signature = hmac.new(_token_secret(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode('ascii')}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def verify_access_token(token: str) -> int | None:
    try:
        encoded_text, signature_text = token.split(".", 1)
        encoded = encoded_text.encode("ascii")
        padding = b"=" * (-len(signature_text) % 4)
        supplied = base64.urlsafe_b64decode(signature_text.encode("ascii") + padding)
        expected = hmac.new(_token_secret(), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return None
        payload_padding = b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + payload_padding))
        if int(payload["exp"]) < int(time.time()):
            return None
        return int(payload["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        return None
