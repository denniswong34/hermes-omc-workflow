"""Auth HTTP routes — TASK-002: passwordless magic-link login."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from apps.api.auth import (
    create_session,
    generate_magic_link_token,
    login as check_creds,
    refresh_session,
    verify_access_token,
    verify_magic_link_token,
)
from apps.api.email import (
    ConsoleEmailProvider,
    get_email_provider,
    send_magic_link_email,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Existing credential login (TASK-001)
# ---------------------------------------------------------------------------


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/api/auth/login")
def login(body: LoginBody):
    """POST /api/auth/login — validate credentials against the stub login()."""
    ok = check_creds(body.email, body.password)
    return {"ok": ok}


# ---------------------------------------------------------------------------
# Passwordless magic-link (TASK-002)
# ---------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    email: str


class MagicLinkVerify(BaseModel):
    email: str
    token: str


class RefreshBody(BaseModel):
    refresh_token: str


@router.post("/api/auth/magic-link")
def request_magic_link(body: MagicLinkRequest):
    """POST /api/auth/magic-link

    Generates a one-time 6-character token and delivers it via the
    configured email provider.  When the provider is ConsoleEmailProvider
    (i.e. MAILER_BACKEND=dev or unset with no SMTP_* vars) the token is
    also returned in the response for local testing convenience.
    """
    token = generate_magic_link_token(body.email)

    try:
        send_magic_link_email(body.email, token, ttl_minutes=15)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    # In dev mode the token is returned inline for testing; in production
    # we reveal nothing about whether the account exists (non-enumerating).
    provider = get_email_provider()
    if isinstance(provider, ConsoleEmailProvider):
        return {
            "ok": True,
            "message": f"Magic-link token sent to {body.email}",
            "token": token,  # exposed for dev/testing only
            "ttl_seconds": 900,
        }

    return {
        "ok": True,
        "message": "If the email exists, a token has been sent",
        "ttl_seconds": 900,
    }


@router.post("/api/auth/magic-link/verify")
def verify_magic_link(body: MagicLinkVerify):
    """POST /api/auth/magic-link/verify

    Exchanges a valid magic-link token + email for a JWT session pair
    (access + refresh). Invalidates the token after first use.
    """
    email = verify_magic_link_token(body.email, body.token)
    if email is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid, expired, or already-used token",
        )

    session = create_session(email)
    return {
        "ok": True,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
        "email": email,
    }


@router.post("/api/auth/refresh")
def refresh(body: RefreshBody):
    """POST /api/auth/refresh

    Exchange a valid refresh token for a new access + refresh pair
    (token rotation — old refresh is consumed).
    """
    session = refresh_session(body.refresh_token)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid, expired, or already-used refresh token",
        )

    return {
        "ok": True,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
    }


@router.get("/api/auth/me")
def me(authorization: str | None = Header(None)):
    """GET /api/auth/me

    Returns the email from the access token if valid.
    Pass the token as: Authorization: Bearer ***
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    email = verify_access_token(token)
    if email is None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    return {"email": email, "authenticated": True}
