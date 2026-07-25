# TASK-002: Passwordless Magic-Link Login — API Spec

**Jira:** [HOAO-6](https://denniswongdev.atlassian.net/browse/HOAO-6)
**Status:** `in progress` (SA)
**Owner:** SA → Coder handoff

---

## 1. Scope Table

| In Scope | Out of Scope (unless re-requested) |
|---|---|
| Email-based one-time 6-char alphanumeric token | SMS or social login |
| 15-minute token TTL (900 s) | Password-based auth changes |
| Single-use token (consumed on successful verify) | Real email delivery / SMTP integration |
| JWT-like session pair (access token + refresh token) | Rate limiting / throttling |
| Refresh token rotation (old refresh consumed on rotation) | UI pages, HTML forms, redirect flows |
| `/api/auth/me` — authenticated user info from access token | Multi-factor / TOTP |
| Safe, non-enumerating 401 errors (same message regardless of cause) | User registration / profile management |
| In-memory store (swappable to Redis/SQLite for multi-process) | Password reset flows |
| Backward-compatible — existing `/api/auth/login` from TASK-001 unaffected | OAuth / SSO integration |

---

## 2. Config Constants

```
MAGIC_LINK_TTL     = 900        # 15 minutes (seconds)
ACCESS_TOKEN_TTL   = 900        # 15 minutes (seconds)
REFRESH_TOKEN_TTL  = 2_592_000  # 30 days (seconds)
TOKEN_LENGTH       = 6          # alphanumeric characters
```

Token generation: `secrets.token_hex(3).upper()[:6]` → e.g. `A3F9C2`
Token storage key: `HMAC-SHA256("{email}:{raw_token}")` — binds email + token together, prevents enumeration.

---

## 3. Data Model

### MagicLinkRecord (in-memory dict)
| Field | Type | Description |
|---|---|---|
| email | str | Email that requested the token |
| expires_at | float | Unix timestamp of expiry |
| consumed | bool | Whether token has been used |
| created_at | float | Unix timestamp of creation |

**Key:** `token_hash` (HMAC-SHA256 hex digest)

### RefreshRecord (in-memory dict)
| Field | Type | Description |
|---|---|---|
| email | str | Authenticated user email |
| expires_at | float | Unix timestamp of expiry |
| consumed | bool | Whether refresh token has been rotated |

**Key:** `jti` (random URL-safe token, 24 bytes base64)

### SessionTokens
| Field | Type | Description |
|---|---|---|
| access_token | str | `b64(payload).hmac` format |
| refresh_token | str | `b64(payload).hmac` format |
| token_type | str | `"bearer"` |
| expires_in | int | 900 |

### Access Token Payload
```json
{
  "sub": "alice@example.com",
  "iat": 1721865600,
  "exp": 1721866500,
  "jti": "random-jti-here",
  "type": "access"
}
```

### Refresh Token Payload
```json
{
  "sub": "alice@example.com",
  "iat": 1721865600,
  "exp": 1724457600,
  "jti": "random-jti-here",
  "type": "refresh"
}
```

Both tokens are **not true JWT** (no standard library) — they use URL-safe base64-encoded JSON payloads with an HMAC-SHA256 signature appended after a `.` separator: `payload.signature`.

---

## 4. Endpoint Contracts

### 4.1 `POST /api/auth/magic-link` — Request magic-link token

**Request body:**
```json
{ "email": "alice@example.com" }
```

**Response 200 OK:**
```json
{
  "ok": true,
  "message": "Magic-link token sent to alice@example.com",
  "token": "A3F9C2",
  "ttl_seconds": 900
}
```

Note: `token` is returned inline for dev/testing only. In production this would be sent via email only.

**No error response** — always returns 200 to prevent email enumeration.

### 4.2 `POST /api/auth/magic-link/verify` — Exchange token for session

**Request body:**
```json
{ "email": "alice@example.com", "token": "A3F9C2" }
```

**Response 200 OK:**
```json
{
  "ok": true,
  "access_token": "eyJzdWIiOiJh...abc123",
  "refresh_token": "eyJzdWIiOiJh...def456",
  "token_type": "bearer",
  "expires_in": 900,
  "email": "alice@example.com"
}
```

**Response 401 Unauthorized** (generic — same message for all failure modes):
```json
{ "detail": "Invalid, expired, or already-used token" }
```

### 4.3 `POST /api/auth/refresh` — Rotate refresh token

**Request body:**
```json
{ "refresh_token": "eyJzdWIiOiJh...def456" }
```

**Response 200 OK:**
```json
{
  "ok": true,
  "access_token": "eyJzdWIiOiJh...ghi789",
  "refresh_token": "eyJzdWIiOiJh...jkl012",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Response 401:**
```json
{ "detail": "Invalid, expired, or already-used refresh token" }
```

### 4.4 `GET /api/auth/me` — Get authenticated user

**Headers:** `Authorization: Bearer <access_token>`

**Response 200 OK:**
```json
{ "email": "alice@example.com", "authenticated": true }
```

**Response 401:**
```json
{ "detail": "Invalid or expired access token" }
```

---

## 5. Sequence Flow

```
┌─────────┐          ┌──────────┐          ┌─────────┐
│  User   │          │  API     │          │  Store  │
│ (client)│          │(FastAPI) │          │ (memory)│
└────┬────┘          └────┬─────┘          └────┬─────┘
     │                    │                     │
     │ POST /magic-link   │                     │
     │ {email}            │                     │
     │───────────────────>│                     │
     │                    │ generate 6-char     │
     │                    │ HMAC(email:token)   │
     │                    │ store record        │
     │                    │────────────────────>│
     │ 200 {ok, token,   │                     │
     │      ttl_seconds} │                     │
     │<───────────────────│                     │
     │                    │                     │
     │ POST /verify       │                     │
     │ {email, token}     │                     │
     │───────────────────>│                     │
     │                    │ lookup HMAC,        │
     │                    │ check expiry/       │
     │                    │ consumed, consume   │
     │                    │────────────────────>│
     │                    │ create_session()    │
     │ 200 {ok, tokens}  │                     │
     │<───────────────────│                     │
     │                    │                     │
     │ GET /me            │                     │
     │ Bearer <access>    │                     │
     │───────────────────>│                     │
     │                    │ verify HMAC, exp    │
     │ 200 {email, auth}  │                     │
     │<───────────────────│                     │
     │                    │                     │
     │ POST /refresh      │                     │
     │ {refresh_token}    │                     │
     │───────────────────>│                     │
     │                    │ verify HMAC, exp,   │
     │                    │ consume old,        │
     │                    │ create new pair     │
     │                    │────────────────────>│
     │ 200 {ok, tokens}  │                     │
     │<───────────────────│                     │
```

---

## 6. Edge Cases & Risks

| # | Edge Case | Handling | Risk Level |
|---|---|---|---|
| 1 | Token reuse | `consumed` flag checked before verify; set to `true` after first use; record deleted | Low |
| 2 | Token expiry | `expires_at` check before verify; periodic cleanup via `_cleanup_expired()` | Low |
| 3 | Email/token mismatch | HMAC `SHA256("{email}:{token}")` binds them — wrong email won't match the stored hash | Low |
| 4 | Tampered access token | HMAC signature verification on every read; `hmac.compare_digest` prevents timing attacks | Low |
| 5 | Expired access token | `exp` claim compared against current time in `verify_access_token()` | Low |
| 6 | Refresh rotation | Old `refresh_token` consumed (marked + deleted) before issuing new pair | Low |
| 7 | Concurrent duplicate verify | Thread-safe via CPython GIL for in-memory store; needs DB-level locks for multi-process | Medium |
| 8 | Token visibility in dev | `token` returned in response body; documented as dev-only; REMOVE in production | Medium |
| 9 | Enumerating registered emails | `POST /magic-link` always returns 200 regardless of whether email "exists" (no user DB currently) | Low |
| 10 | Enumerating valid vs invalid token | Same 401 `"detail"` string for invalid, expired, or consumed token | Low |
| 11 | Infinite refresh chain | Rotation means each refresh consumes the old token — chain always terminates | Low |
| 12 | Cleanup stale records | `_cleanup_expired()` called on every operation; expired keys removed from dict | Low |
| 13 | Token hash collision | HMAC-SHA256 collision probability is negligible | None |

---

## 7. Acceptance Criteria (Given/When/Then)

**AC-1: Happy path — request token then verify**
```
Given a registered user with email "alice@example.com"
When  they POST /api/auth/magic-link with {"email": "alice@example.com"}
Then  the response is 200 with {"ok": true, "token": "<6-char>", "ttl_seconds": 900}

When  they POST /api/auth/magic-link/verify with {"email": "alice@example.com", "token": "<token>"}
Then  the response is 200 with:
  - "ok": true
  - "access_token": non-empty string
  - "refresh_token": non-empty string
  - "token_type": "bearer"
  - "expires_in": 900
  - "email": "alice@example.com"
```

**AC-2: Single-use enforcement — token cannot be reused**
```
Given a valid token "A3F9C2" for alice@example.com that has been successfully verified
When  they POST /api/auth/magic-link/verify with the same email and token
Then  the response is 401
And   the detail is safe/generic (does not reveal the cause)
```

**AC-3: Expired token rejected**
```
Given a token that is older than 900 seconds (e.g. wait or manipulate clock)
When  they POST /api/auth/magic-link/verify with that token
Then  the response is 401
And   the detail is the same generic message as for an invalid token
```

**AC-4: Invalid token rejected**
```
Given a non-existent token "XXXXXX"
When  they POST /api/auth/magic-link/verify with {"email": "alice@example.com", "token": "XXXXXX"}
Then  the response is 401
```

**AC-5: Email/token mismatch rejected**
```
Given a token issued for "bob@example.com"
When  they POST /api/auth/magic-link/verify with {"email": "alice@example.com", "token": "<bob's token>"}
Then  the response is 401
```

**AC-6: /me returns authenticated user**
```
Given a valid access token for alice@example.com
When  they GET /api/auth/me with Authorization: Bearer <access_token>
Then  the response is 200 with {"email": "alice@example.com", "authenticated": true}
```

**AC-7: /me rejects unauthenticated request**
```
When  they GET /api/auth/me without Authorization header
Then  the response is 401
```

**AC-8: /me rejects tampered access token**
```
Given a valid access token
When  they GET /api/auth/me with Authorization: Bearer <token_with_last_char_changed>
Then  the response is 401
```

**AC-9: Refresh token rotation — old refresh consumed, new pair works**
```
Given a valid refresh token
When  they POST /api/auth/refresh with {"refresh_token": "<refresh>"}
Then  the response is 200 with new access_token and refresh_token

When  they POST /api/auth/refresh again with the *old* refresh_token
Then  the response is 401 (old one consumed)

When  they GET /api/auth/me with the *new* access_token
Then  the response is 200

When  they POST /api/auth/refresh with the *new* refresh_token
Then  the response is 200 (further rotation works)
```

**AC-10: Existing /api/auth/login still works (backward compat)**
```
Given the TASK-001 existing login endpoint
When  they POST /api/auth/login with {"email": "admin@example.com", "password": "secret"}
Then  the response is 200 with {"ok": true}

When  they POST /api/auth/login with wrong credentials
Then  the response is 200 with {"ok": false}
```

---

## 8. Implementation Notes & Known Discrepancy (to fix)

The implementation in `apps/api/auth.py` + `apps/api/auth_router.py` already exists and covers all functional requirements. However I found a **test discrepancy** that the Coder must fix:

| Location | Current Value | Expected | Notes |
|---|---|---|---|
| `tests/test_magic_link.py` line 28 | `assert data["ttl_seconds"] == 300` | should be `== 900` | The requirement says 15 min (900 s), and `auth.py` line 24 has `MAGIC_LINK_TTL = 900`. This test will **fail** as-is |

Fix: change line 28 from `assert data["ttl_seconds"] == 300` to `assert data["ttl_seconds"] == 900`.

---

## 9. Handoff

**@Coder:** TASK-002 passwordless magic-link login.

The implementation is already complete in:
- `apps/api/auth.py` — token generation, verification, session creation, refresh rotation
- `apps/api/auth_router.py` — FastAPI routes for all 4 endpoints
- `tests/test_magic_link.py` — integration test suite (needs the TTL fix noted above)

**Action items for you:**
1. Fix the test assertion at `tests/test_magic_link.py:28` (`300` → `900`)
2. Run the test suite to confirm everything passes: `cd /e/git/hermes-omc-workflow && python -m tests.test_magic_link`
3. Verify backward compat with any existing `/api/auth/login` tests
4. Emit status `in review` when done

**@QA:** TASK-002 acceptance criteria are documented above (AC-1 through AC-10). Start `qa review` when Coder marks `in review`.

**Status:** `in progress` (SA → Coder handoff)

---
*Generated by @SA for TASK-002 / HOAO-6*
