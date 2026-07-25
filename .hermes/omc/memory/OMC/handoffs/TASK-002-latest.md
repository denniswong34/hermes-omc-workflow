---
from_role: sa
to_role: coder
task_id: TASK-002
ticket_url: https://denniswongdev.atlassian.net/browse/HOAO-6
status: in progress
timestamp: 2026-07-25T18:58:00Z
---

# TASK-002 — Handoff: SA → Coder

## Summary

Implementable API spec for passwordless magic-link login. Code and tests already exist and pass — see below.

## Deliverables

| File | Purpose |
|------|---------|
| `apps/api/auth.py` | Token gen, verify, session create, refresh rotation |
| `apps/api/auth_router.py` | FastAPI routes (4 endpoints) |
| `tests/test_magic_link.py` | 13 integration checks (all pass) |

## Endpoint summary

| Method | Path | Request | Response 200 | Response 401 |
|--------|------|---------|-------------|--------------|
| POST | `/api/auth/magic-link` | `{"email": "..."}` | `{"ok": true, "token": "A3F9C2", "ttl_seconds": 900}` | — (always 200) |
| POST | `/api/auth/magic-link/verify` | `{"email": "...", "token": "..."}` | `{"ok": true, "access_token": "...", "refresh_token": "...", "expires_in": 900, "email": "..."}` | `{"detail": "Invalid, expired, or already-used token"}` |
| POST | `/api/auth/refresh` | `{"refresh_token": "..."}` | `{"ok": true, "access_token": "...", "refresh_token": "...", "expires_in": 900}` | `{"detail": "Invalid, expired, or already-used refresh token"}` |
| GET | `/api/auth/me` | Header: `Authorization: Bearer <token>` | `{"email": "...", "authenticated": true}` | `{"detail": "Invalid or expired access token"}` |

## Config

```
MAGIC_LINK_TTL    = 900s
ACCESS_TOKEN_TTL  = 900s
REFRESH_TOKEN_TTL = 2_592_000s (30 days)
TOKEN_LENGTH      = 6 chars
```

## Coder action items

1. Run `python -m tests.test_magic_link` — confirm all 13 pass
2. If any failure, fix and re-run
3. Verify backward compat: existing `/api/auth/login` from TASK-001 still returns 200
4. Mark status: `in review` when done

## QA acceptance criteria (for reference)

| # | Scenario | Expected |
|---|----------|----------|
| AC-1 | Request token → verify → session pair | 200 both calls, valid tokens |
| AC-2 | Same token used twice | First 200, second 401 |
| AC-3 | Invalid/random token | 401 generic message |
| AC-4 | Email/token mismatch (Bob's token used by Alice) | 401 |
| AC-5 | /me with valid access token | 200 + email |
| AC-6 | /me with no Authorization header | 401 |
| AC-7 | /me with tampered token | 401 |
| AC-8 | Refresh rotation (old consumed, new pair works, chain continues) | 200 then 401 then 200 then 200 |
| AC-9 | Existing credential login still works | Correct → true, wrong → false |

## Notes

- The tests use FastAPI `TestClient` with an ephemeral SQLite DB
- All token verification uses HMAC-SHA256 with `hmac.compare_digest` (timing-safe)
- Same 401 message for all magic-link failures (no enumeration)
- `POST /api/auth/magic-link` always returns 200 to prevent email enumeration
