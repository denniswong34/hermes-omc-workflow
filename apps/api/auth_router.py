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
# Passwordless magic-link (TASK-012)
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

    Sends a one-time 6-character magic-link token to the given email.
    Since no real email backend is configured, the token is returned in the
    response for development/testing purposes.
    """
    token = generate_magic_link_token(body.email)
    return {
        "ok": True,
        "message": f"Magic-link token sent to {body.email}",
        "token": token,  # exposed for dev; remove in production
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
    Pass the token as: Authorization: Bearer <access_token>
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
