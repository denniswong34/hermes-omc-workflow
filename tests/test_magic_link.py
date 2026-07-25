"""Tests for TASK-002: passwordless magic-link login API."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="omc-api-")
os.environ["OMC_DB_PATH"] = str(Path(tmp) / "api.db")

from fastapi.testclient import TestClient

from apps.api.main import app


def main() -> None:
    c = TestClient(app)

    # ── 1. Request magic-link token ──────────────────────────────────
    r = c.post("/api/auth/magic-link", json={"email": "alice@example.com"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["ok"] is True
    assert "message" in data
    assert "token" in data
    assert len(data["token"]) == 6, f"Token should be 6 chars: {data['token']}"
    assert data["ttl_seconds"] == 900  # TASK-002: 15 min per requirement
    token1 = data["token"]
    print(f"  1. Magic-link token requested: {token1}")

    # ── 2. Verify with a valid token ─────────────────────────────────
    r = c.post(
        "/api/auth/magic-link/verify",
        json={"email": "alice@example.com", "token": token1},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["ok"] is True
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["email"] == "alice@example.com"
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    print(f"  2. Magic-link verified. Access: {access_token[:40]}...")

    # ── 3. Reuse same token should fail (one-time use) ───────────────
    r = c.post(
        "/api/auth/magic-link/verify",
        json={"email": "alice@example.com", "token": token1},
    )
    assert r.status_code == 401, (
        f"Expected 401 for reused token, got {r.status_code}: {r.text}"
    )
    print("  3. Reused token correctly rejected (401)")

    # ── 4. Invalid token ─────────────────────────────────────────────
    r = c.post(
        "/api/auth/magic-link/verify",
        json={"email": "alice@example.com", "token": "XXXXXX"},
    )
    assert r.status_code == 401
    print("  4. Invalid token correctly rejected (401)")

    # ── 5. Wrong email for token ─────────────────────────────────────
    r = c.post("/api/auth/magic-link", json={"email": "bob@example.com"})
    token2 = r.json()["token"]
    r = c.post(
        "/api/auth/magic-link/verify",
        json={"email": "alice@example.com", "token": token2},
    )
    assert r.status_code == 401, (
        f"Expected 401 for email/token mismatch, got {r.status_code}"
    )
    print("  5. Email/token mismatch correctly rejected (401)")

    # ── 6. Verify access token with /me ──────────────────────────────
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json()["email"] == "alice@example.com"
    assert r.json()["authenticated"] is True
    print("  6. /me endpoint works with valid access token")

    # ── 7. /me without auth ──────────────────────────────────────────
    r = c.get("/api/auth/me")
    assert r.status_code == 401
    print("  7. /me without auth correctly rejected (401)")

    # ── 8. Refresh token rotation ────────────────────────────────────
    r = c.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["ok"] is True
    new_access = data["access_token"]
    new_refresh = data["refresh_token"]
    print("  8. Token refreshed successfully")

    # Old refresh should be consumed
    r = c.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401, (
        f"Expected 401 for consumed refresh, got {r.status_code}"
    )
    print("  9. Old refresh token correctly rejected after rotation (401)")

    # New access token should work
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"
    print(" 10. New access token works after refresh")

    # New refresh token should also work
    r = c.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert r.status_code == 200
    print(" 11. New refresh token works for further rotation")

    # ── 12. Original /api/auth/login still works ─────────────────────
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "secret"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r = c.post(
        "/api/auth/login", json={"email": "wrong@example.com", "password": "wrong"}
    )
    assert r.json()["ok"] is False
    print(" 12. Existing login endpoint still works")

    # ── 13. Tampered access token ────────────────────────────────────
    r = c.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_access[:-1]}X"},
    )
    assert r.status_code == 401
    print(" 13. Tampered access token correctly rejected (401)")

    print("\nAll TASK-002 magic-link tests passed ✓")


if __name__ == "__main__":
    main()
