"""Auth stubs — TASK-002: passwordless magic-link login."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Keys & config
# ---------------------------------------------------------------------------

SECRET_KEY: bytes = os.environ.get(
    "OMC_AUTH_SECRET",
    "dev-secret-change-in-production-32chars!",  # 32+ bytes
).encode("utf-8")

MAGIC_LINK_TTL: int = 900        # 15 minutes (TASK-001 requirement)
ACCESS_TOKEN_TTL: int = 900      # 15 minutes
REFRESH_TOKEN_TTL: int = 2592000  # 30 days

# ---------------------------------------------------------------------------
# In-memory stores  (swap with Redis / SQLite for multi-process deployment)
# ---------------------------------------------------------------------------

# token_hash -> MagicLinkRecord
_magic_links: dict[str, "MagicLinkRecord"] = {}

# refresh_jti -> RefreshRecord
_refresh_tokens: dict[str, "RefreshRecord"] = {}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MagicLinkRecord:
    email: str
    expires_at: float  # unix ts
    consumed: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class RefreshRecord:
    email: str
    expires_at: float  # unix ts
    consumed: bool = False


@dataclass
class SessionTokens:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hmac_sign(payload: str) -> str:
    """Return a hex HMAC-SHA256 signature for *payload*."""
    return hmac.new(SECRET_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_jti() -> str:
    """Random unique token id."""
    return secrets.token_urlsafe(24)


def _b64_encode(data: dict) -> str:
    """URL-safe base64 encode a JSON payload (no padding)."""
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(payload: str) -> Optional[dict]:
    """Inverse of _b64_encode."""
    try:
        # Re-pad
        padded = payload + "=" * (4 - len(payload) % 4) if len(payload) % 4 else payload
        raw = base64.urlsafe_b64decode(padded)
        return json.loads(raw)
    except Exception:
        return None


def _now() -> float:
    return time.time()


def _cleanup_expired() -> None:
    """Remove expired magic-link and refresh records."""
    t = _now()
    expired_magic = [k for k, v in _magic_links.items() if v.expires_at < t]
    for k in expired_magic:
        del _magic_links[k]
    expired_refresh = [k for k, v in _refresh_tokens.items() if v.expires_at < t]
    for k in expired_refresh:
        del _refresh_tokens[k]


# ---------------------------------------------------------------------------
# Existing credential check (kept for backward compat with TASK-001 login)
# ---------------------------------------------------------------------------


def login(email: str, password: str) -> bool:
    """Stub: validate credentials (email + password)."""
    return email == "admin@example.com" and password == "secret"


# ---------------------------------------------------------------------------
# Magic-link token lifecycle
# ---------------------------------------------------------------------------


def generate_magic_link_token(email: str) -> str:
    """Generate a 6-char alphanumeric token, HMAC-sign it, store a record.

    Returns the raw 6-char token (the user receives this via email).
    """
    _cleanup_expired()

    raw_token = secrets.token_hex(3).upper()[:6]  # e.g. "A3F9C2"
    token_hash = _hmac_sign(f"{email}:{raw_token}")

    _magic_links[token_hash] = MagicLinkRecord(
        email=email,
        expires_at=_now() + MAGIC_LINK_TTL,
        consumed=False,
    )

    return raw_token


def verify_magic_link_token(email: str, raw_token: str) -> Optional[str]:
    """Verify a magic-link token.

    Returns the email on success, or None if the token is invalid, expired,
    already consumed, or doesn't match.
    """
    _cleanup_expired()

    token_hash = _hmac_sign(f"{email}:{raw_token}")
    record = _magic_links.get(token_hash)

    if record is None:
        return None  # not found or expired (cleaned up)

    if record.consumed:
        return None  # one-time use violated

    if record.expires_at < _now():
        del _magic_links[token_hash]
        return None  # expired

    if record.email != email:
        return None  # email mismatch

    # Consume — one-time use
    record.consumed = True
    del _magic_links[token_hash]

    return record.email


# ---------------------------------------------------------------------------
# Session (JWT-like) token lifecycle
# ---------------------------------------------------------------------------


def create_session(email: str) -> SessionTokens:
    """Issue an access + refresh token pair for the given email."""
    now = _now()

    jti = _generate_jti()
    access_payload = {
        "sub": email,
        "iat": int(now),
        "exp": int(now + ACCESS_TOKEN_TTL),
        "jti": jti,
        "type": "access",
    }
    access_b64 = _b64_encode(access_payload)
    access_sig = _hmac_sign(access_b64)
    access_token = f"{access_b64}.{access_sig}"

    refresh_jti = _generate_jti()
    refresh_payload = {
        "sub": email,
        "iat": int(now),
        "exp": int(now + REFRESH_TOKEN_TTL),
        "jti": refresh_jti,
        "type": "refresh",
    }
    refresh_b64 = _b64_encode(refresh_payload)
    refresh_sig = _hmac_sign(refresh_b64)
    refresh_token = f"{refresh_b64}.{refresh_sig}"

    # Store refresh token so we can invalidate it
    _refresh_tokens[refresh_jti] = RefreshRecord(
        email=email,
        expires_at=now + REFRESH_TOKEN_TTL,
        consumed=False,
    )

    return SessionTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_TTL,
    )


def verify_access_token(token: str) -> Optional[str]:
    """Validate an access token. Returns the email (subject) or None."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        b64_payload, sig = parts
        expected_sig = _hmac_sign(b64_payload)
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = _b64_decode(b64_payload)
        if payload is None:
            return None
        if payload.get("type") != "access":
            return None
        if payload.get("exp", 0) < _now():
            return None
        return payload.get("sub")
    except Exception:
        return None


def refresh_session(refresh_token: str) -> Optional[SessionTokens]:
    """Exchange a valid refresh token for a new session pair.

    The old refresh token is consumed (rotation).
    Returns None if invalid / expired / already used.
    """
    try:
        parts = refresh_token.split(".")
        if len(parts) != 2:
            return None
        b64_payload, sig = parts
        expected_sig = _hmac_sign(b64_payload)
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = _b64_decode(b64_payload)
        if payload is None:
            return None
        if payload.get("type") != "refresh":
            return None
        if payload.get("exp", 0) < _now():
            return None

        jti = payload.get("jti")
        email = payload.get("sub")
        if not jti or not email:
            return None

        record = _refresh_tokens.get(jti)
        if record is None or record.consumed:
            return None

        # Consume old refresh token (rotation)
        record.consumed = True
        del _refresh_tokens[jti]

        # Issue new pair
        return create_session(email)
    except Exception:
        return None
