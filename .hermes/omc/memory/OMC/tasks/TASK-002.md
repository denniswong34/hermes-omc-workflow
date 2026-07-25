---
task_id: TASK-002
status: in progress
assignee: sa
topic: engineering
ticket_url: https://denniswongdev.atlassian.net/browse/HOAO-6
updated: 2026-07-25T18:58:00Z
---

# TASK-002: Passwordless Magic-Link Login

**Jira:** HOAO-6

## Goal

Deliver a passwordless login flow — user enters email, receives a one-time 6-character alphanumeric token, exchanges it for an authenticated JWT session pair (access + refresh). Token expires in 15 minutes, is single-use, and errors return safe non-enumerating 401 responses.

## Spec

Full API spec written in `.hermes/omc/memory/OMC/wf_bd77e2aed1b8/handoffs/TASK-002-latest.md`

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/magic-link` | Request 6-char OTP token by email |
| POST | `/api/auth/magic-link/verify` | Exchange token for JWT session pair |
| POST | `/api/auth/refresh` | Rotate refresh token (old consumed) |
| GET | `/api/auth/me` | Get authenticated user from access token |

### Config

```
MAGIC_LINK_TTL    = 900s (15 min)
ACCESS_TOKEN_TTL  = 900s (15 min)
REFRESH_TOKEN_TTL = 2_592_000s (30 days)
TOKEN_LENGTH      = 6 chars
```

### Key design decisions

- HMAC-SHA256 binds email + token together (prevents enumeration)
- Same 401 message for all failure modes (invalid/expired/consumed)
- Refresh token rotation (old consumed on each refresh)
- In-memory storage (swappable to Redis/SQLite for multi-process)
- Backward compatible — existing `/api/auth/login` unchanged

## Acceptance criteria

| # | Scenario | Expected |
|---|----------|----------|
| AC-1 | Happy path: request → verify → session tokens | 200 on both, valid access+refresh |
| AC-2 | Single-use: same token used twice | First 200, second 401 |
| AC-3 | Invalid token | 401 same message |
| AC-4 | Email/token mismatch | 401 same message |
| AC-5 | /me valid access token | 200 + email |
| AC-6 | /me no auth header | 401 |
| AC-7 | /me tampered access token | 401 |
| AC-8 | Refresh rotation: old consumed, new pair works | First 200, old refresh 401, new pair 200 |
| AC-9 | Backward compat: existing login still works | Creds OK → true, wrong → false |

## Implementation notes

Implementation complete and tested:

- `apps/api/auth.py` — token gen, verify, session create, refresh rotation
- `apps/api/auth_router.py` — FastAPI routes for all 4 endpoints
- `tests/test_magic_link.py` — 13 integration checks, all pass

### 2026-07-25T18:58:00Z — @sa

Verified: all 13 test checks pass. TTL confirmed at 900s. Full spec documented in handoff packet.

## Handoff log

- 2026-07-25T18:53:00Z — @pm → @sa: TASK-002 (HOAO-6) — produce API spec + acceptance criteria, hand to @Coder
- 2026-07-25T18:58:00Z — @sa → @coder: TASK-002 spec + acceptance criteria ready. Code + tests already exist at apps/api/auth.py, apps/api/auth_router.py, tests/test_magic_link.py. All 13 tests pass. Verify and emit `in review`.
