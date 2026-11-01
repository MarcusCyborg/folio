# Folio Milestone Integration A / R04 — Shared Distributed Rate Limiter Handoff

**Handoff ID:** `IA-R04-shared-rate-limit`  
**Milestone:** Integration A — Task R04 (Remediation of Finding IA-06: Shared Distributed Rate Limiter)  
**Date:** 2026-11-01  
**Author:** Folio Backend Concurrency Engineer  
**Status:** `CODE COMPLETE & MULTIPROCESS VERIFIED / LIVE POSTGRESQL ENVIRONMENT BLOCKED_ENV` (Integration A in progress; R04 complete, P03 NOT STARTED)  

---

## 1. Executive Summary & Finding IA-06 Remediation

Finding **IA-06** identified that the initial rate limiter implementation in P01 relied on an in-memory dictionary with a local `threading.Lock` within a single process:
1. **Process Isolation Vulnerability:** In a multi-worker deployment (e.g. multiple Uvicorn/Gunicorn processes or containers), each worker maintained its own independent in-memory dictionary. An attacker alternating requests between workers could multiply the allowable login/registration attempts by the number of worker processes.
2. **Loss of State on Restart:** Any worker restart wiped all rate limit counters, eliminating burst protection.
3. **Transaction Coupling & Rollback Flaw:** If rate limiting shared the main database transaction, an authentication failure (HTTP 401) causing a transaction rollback could inadvertently erase the recorded failure counter.
4. **Improper Counter Reset Scope:** On successful login, the existing code called `record_successful_login(rate_limit_ip_key)`, which reset the IP-wide counter, allowing an attacker who authenticated one valid account to wipe the IP counter for all other targeted accounts.
5. **Lack of Retry-After Header:** 429 responses returned generic error messages without conveying how many seconds the client must wait.
6. **Silent Fallback Risk:** Hardcoded local fallbacks can claim distributed guarantees without actually enforcing them.

### Summary of R04 Remediation:
- **Shared Persistent Store (`rate_limit_buckets`):**
  Implemented a distributed rate limiter backed by the existing PostgreSQL database (no Redis/Celery required). State is stored in a dedicated table `rate_limit_buckets`.
- **Atomic Admission via Row-Level Locking:**
  Evaluates and increments sliding-window counters within an atomic database transaction using row-level locking (`SELECT ... FOR UPDATE` in PostgreSQL). Concurrent requests cannot read stale remaining counts or exceed configured limits.
- **Deterministic Lock Ordering:**
  When multiple keys are locked (e.g. target account and IP-wide counter during login), keys are sorted lexicographically prior to lock acquisition, mathematically eliminating deadlocks.
- **Autonomous Transaction Lifecycle (Rollback Independence):**
  Rate limit checks and hit recordings execute and `COMMIT` on their own dedicated, isolated database session. Even if the main HTTP request subsequently fails authentication (HTTP 401) or encounters an error, the rate limit hit is already committed and is never rolled back.
- **Authoritative Monotonic DB Clock:**
  Sliding window timestamps are evaluated against the database engine's clock (`SELECT EXTRACT(EPOCH FROM clock_timestamp())`), completely preventing host clock drift across multiple worker machines.
- **Strict Success Isolation Policy:**
  On successful login, ONLY the target account key (`login:target:...`) is reset. The IP-wide counter (`login:ip:...`) is explicitly NOT reset, preventing account takeover sprayers from wiping IP abuse limits.
- **HTTP 429 & Retry-After Contract:**
  When rate limits are exceeded, endpoints return HTTP 429 `TOO_MANY_REQUESTS` accompanied by a standard `Retry-After: <seconds>` HTTP response header indicating the exact ceiling time until the oldest attempt in the window expires.
- **Failure Transparency (No Silent Fallback):**
  If the database store is unreachable or down, the limiter raises `RateLimitStoreUnavailableError`, which translates to HTTP 503 `RATE_LIMIT_UNAVAILABLE` with all credentials strictly redacted. It never silently degrades to a local in-memory lock while claiming distributed consistency.
- **Bounded Retention:**
  Attempts are stored as bounded sliding-window arrays. A cleanup routine (`cleanup_expired`) prunes entries older than the retention threshold (1 hour).
- **Privacy-Preserving Keys:**
  Keys are formatted using 16-character SHA-256 digests (`login:target:<ip_hash>:<email_hash>`, `login:ip:<ip_hash>`, `register:ip:<ip_hash>`). Raw passwords, tokens, and plain-text emails are never stored in keys or written to logs.

---

## 2. Rate Limiting Architecture & Policy Specification

```text
+-----------------------------------------------------------------------------------+
|                              Client HTTP Request                                  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| FastAPI Endpoint: /api/v1/auth/login or /api/v1/auth/register                     |
| 1. Extract client IP (trusted proxy validation via X-Forwarded-For)               |
| 2. Build hashed privacy-preserving keys (login:target, login:ip, register:ip)     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| PostgresRateLimiter (Autonomous Session & Immediate Commit)                       |
| 1. Upsert bucket row: INSERT INTO rate_limit_buckets ... ON CONFLICT DO NOTHING   |
| 2. Lock row: SELECT attempts, clock_timestamp() FROM rate_limit_buckets FOR UPDATE|
| 3. Filter attempts in window: [t for t in attempts if t > now - window_seconds]   |
| 4. If count >= limit:                                                             |
|      Calculate retry_after = ceil(oldest + window - now)                          |
|      Commit & Return RateLimitResult(allowed=False, retry_after=...)              |
| 5. If count < limit:                                                              |
|      active.append(now); UPDATE rate_limit_buckets SET attempts = active          |
|      Commit & Return RateLimitResult(allowed=True, retry_after=0)                 |
+-----------------------------------------------------------------------------------+
       |                                                            |
       | (allowed=False)                                            | (allowed=True)
       v                                                            v
+------------------------------------+             +--------------------------------+
| HTTP 429 Too Many Requests         |             | Proceed to Password / Creation |
| Headers: Retry-After: <seconds>    |             | On 401: record_failed_logins   |
| Body: {"error": "TOO_MANY_REQUESTS"|             | On 200: record_success (target)|
+------------------------------------+             +--------------------------------+
```

### Policy Rules Matrix:

| Action / Endpoint | Key Format | Default Limit | Window | Success Action | Exceeded Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`login_target`** (`POST /api/v1/auth/login`) | `login:target:<ip_hash>:<email_hash>` | 5 failed attempts | 60s | Reset target bucket | HTTP 429 + `Retry-After: <sec>` |
| **`login_ip`** (`POST /api/v1/auth/login`) | `login:ip:<ip_hash>` | 15 failed attempts | 60s | **NO RESET** (preserved) | HTTP 429 + `Retry-After: <sec>` |
| **`register_ip`** (`POST /api/v1/auth/register`) | `register:ip:<ip_hash>` | 10 attempts | 60s | N/A (rate limited burst) | HTTP 429 + `Retry-After: <sec>` |
| **Store Down** | All | N/A | N/A | N/A | HTTP 503 `RATE_LIMIT_UNAVAILABLE` |

---

## 3. Alembic Migration Chain Status

Task R04 introduces a dedicated migration to provision the persistent rate limit table.

### 3.1 Migration Metadata
- **New Revision ID:** `20261101_rate_limit`
- **Revises (down_revision):** `20261031_click_unique`
- **File:** [`alembic/versions/20261101_rate_limit_buckets.py`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/alembic/versions/20261101_rate_limit_buckets.py)
- **Table Created:** `rate_limit_buckets`
  - `key_hash` VARCHAR(64) PRIMARY KEY
  - `action` VARCHAR(32) NOT NULL
  - `attempts` JSONB NOT NULL DEFAULT `'[]'`
  - `created_at` TIMESTAMPTZ NOT NULL DEFAULT `clock_timestamp()`
  - `updated_at` TIMESTAMPTZ NOT NULL DEFAULT `clock_timestamp()`
  - Indexes: `ix_rate_limit_buckets_action_updated`, `ix_rate_limit_buckets_updated_at`

### 3.2 Single Linear Chain Verification
```powershell
cd F:\dpl13.10\WikiSearchEngine-ia-fix
.\venv\Scripts\alembic.exe heads
# Output:
# 20261101_rate_limit (head)
```
Exactly **ONE (1) linear Alembic head** exists.

### 3.3 Offline Static SQL Verification
Both clean upgrade from scratch and forward upgrade from previous head were generated and validated offline:
- Upgrading from previous head `20261031_click_unique` to `20261101_rate_limit`:
  `alembic upgrade --sql 20261031_click_unique:head` -> Valid transactional DDL, non-destructive.
- Upgrading from clean DB (`base:head`):
  `alembic upgrade --sql base:head` -> Complete schema generation including `rate_limit_buckets`.
- Downgrade script:
  `alembic downgrade --sql 20261101_rate_limit:20261031_click_unique` -> Cleanly drops index and table.

---

## 4. Test Execution & Evidence

### 4.1 Pure Rate Limiter Safety Tests (`test_pure_rate_limit.py`)
Executed with `--noconftest` (in-memory, zero external service dependency):
```powershell
cd F:\dpl13.10\WikiSearchEngine-ia-fix
F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\pytest.exe --noconftest tests/safety/test_pure_rate_limit.py -v
```
**Results:** **15 / 15 PASSED** in 2.69s

| Test Case | Description | Result |
| :--- | :--- | :--- |
| `test_hash_identifier_properties` | 16-character deterministic SHA-256 digests | **PASS** |
| `test_build_login_target_key_privacy` | No raw emails or plain credentials in keys | **PASS** |
| `test_build_login_ip_key_privacy` | Bounded format under 64 characters | **PASS** |
| `test_build_register_ip_key_privacy` | Bounded registration key format | **PASS** |
| `test_normalize_bucket_key_masks_raw_identifiers` | Arbitrary credentials digested | **PASS** |
| `test_rate_limit_result_bool_compatibility` | Boolean truthiness & retry_after arithmetic | **PASS** |
| `test_sqlite_limiter_check_and_record_register` | Atomic admission & rejection | **PASS** |
| `test_sqlite_limiter_login_sliding_window` | Consecutive failures trigger rejection | **PASS** |
| `test_successful_login_resets_only_target_account` | Success on User A preserves User B & IP | **PASS** |
| `test_record_failed_logins_sorts_keys` | Multi-key sorted lock ordering | **PASS** |
| `test_store_unavailable_raises_explicit_exception` | Store down raises 503, redacts secrets | **PASS** |
| `test_reset_and_cleanup_expired` | Maintenance cleanup & test reset | **PASS** |
| `test_get_client_ip_direct` | Direct connection host extraction | **PASS** |
| `test_get_client_ip_trusted_proxy` | Trusted reverse proxy X-Forwarded-For | **PASS** |
| `test_get_client_ip_untrusted_proxy_ignored` | Untrusted proxy spoofing ignored | **PASS** |

### 4.2 Multi-Process Concurrency & Integration Tests (`test_shared_rate_limit_concurrency.py`)
Executed with `--noconftest` spawning independent operating system Python worker processes sharing database:
```powershell
cd F:\dpl13.10\WikiSearchEngine-ia-fix
F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\pytest.exe --noconftest tests/backend/foundation/test_shared_rate_limit_concurrency.py -v
```
**Results:** **10 / 10 PASSED** in 33.80s

| Test Case | Concurrency Invariant Verified | Result |
| :--- | :--- | :--- |
| `test_two_independent_processes_alternating_failed_logins` | Two separate OS processes alternating failures reach shared limit 5. Both processes report blocked. | **PASS** |
| `test_process_restart_preserves_rate_limit_state` | Worker process exits and restarts; database preserves counters without loss. | **PASS** |
| `test_success_one_account_does_not_reset_ip_counter` | Cross-process success on Account A clears Account A but preserves Account B and IP-wide counters. | **PASS** |
| `test_auth_transaction_rollback_does_not_rollback_rate_limit` | Main HTTP session encounters 401 error and rolls back; rate limiter hit is already committed. | **PASS** |
| `test_rate_limiter_store_down_raises_service_unavailable` | DB down produces HTTP 503 with zero secret leakage. No silent in-memory fallback. | **PASS** |
| `test_api_login_abuse_returns_429_with_retry_after_header` | Full FastAPI login API returns 429 and valid `Retry-After: <sec>` header. | **PASS** |
| `test_api_registration_abuse_returns_429_with_retry_after` | Full FastAPI register API returns 429 and valid `Retry-After: <sec>` header. | **PASS** |
| `test_concurrent_processes_burst_registration_atomic_admission` | 8 concurrent processes fire registrations on same IP (limit 4). Exactly 4 admitted, exactly 4 blocked with 429. | **PASS** |
| `test_window_expiry_restores_admission` | Sliding window expires after TTL; key is restored to allowed state. | **PASS** |
| `test_distinct_keys_isolation` | Hits against Key A do not alter or increment Key B. | **PASS** |

### 4.3 Regression Test Verification
1. **R01 Pure DB Safety:** `tests/safety/test_pure_safety.py` (45 passed in 0.31s).
2. **R02 Bootstrap Admin Security:** `tests/security/test_bootstrap_security.py` (19 passed in 6.13s).
3. **R02 Startup Subprocess & Runtime:** `tests/security/test_startup_subprocess.py` and `test_runtime_security_hardening.py` (16 passed in 11.57s).
4. **Combined Targeted Suite:** **70 passed in 36.64s** (`test_pure_safety.py` + `test_pure_rate_limit.py` + `test_shared_rate_limit_concurrency.py`). Zero regressions.

---

## 5. Git Metadata & Worktree Verification

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Active Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree |
| **Branch** | `codex/integration-a-remediation` | Local integration branch |
| **Preceding Commit** | `bf6b930` | Task R02 bootstrap identity rotation & security verification |
| **Files Modified** | `src/backend/core/rate_limit.py` | Shared PostgreSQL rate limiter with atomic admission & DB clock |
| | `src/backend/api/auth.py` | Rate limit integration: hashed keys, non-resetting IP, Retry-After header |
| | `src/backend/core/exceptions.py` | Header propagation in `AppException` & `app_exception_handler` |
| | `src/backend/core/session.py` | Safe offset-naive datetime comparison handling |
| | `src/backend/main.py` | `RateLimitStoreUnavailableError` HTTP 503 exception handler |
| | `src/backend/models/__init__.py` | Registered and exported `RateLimitBucket` |
| **Files Created** | `src/backend/models/rate_limit.py` | `RateLimitBucket` SQLAlchemy ORM model |
| | `alembic/versions/20261101_rate_limit_buckets.py` | Migration adding `rate_limit_buckets` table (head: `20261101_rate_limit`) |
| | `tests/safety/test_pure_rate_limit.py` | Pure unit test suite (15 tests) |
| | `tests/backend/foundation/test_shared_rate_limit_concurrency.py` | Multi-process concurrency and integration test suite (10 tests) |
| | `docs/handoff/gemini/IA-R04-shared-rate-limit.md` | Official R04 handoff report |
| **Untouched Scopes** | Importer, index worker, vector search | Strictly preserved per ownership boundary |

---

## 6. Gaps, Environment Limitations & Handoff to R05 / P03

1. **Finding IA-06 Status:** `CODE COMPLETE & MULTIPROCESS VERIFIED / LIVE POSTGRESQL MULTIPROCESS BLOCKED_ENV`.
   - The distributed rate-limiting logic, atomic row-level locking, rollback independence, and multi-process concurrency were completely implemented and verified with independent OS worker processes.
   - Because the host Windows machine lacks a running PostgreSQL 16 service (no Docker daemon, no WSL distributions, no local `postgres.exe`), live PostgreSQL-specific socket checks remain pending environment provisioning (`BLOCKED_ENV`). In strict compliance with remediation plan rules, SQLite is NOT claimed as a replacement for PostgreSQL verification.
2. **Alembic Head for Downstream Tasks (R05 / R06 / P03):**
   - Head revision ID: `20261101_rate_limit` (Revises: `20261031_click_unique`).
   - Milestone P03 MUST use `20261101_rate_limit` as its `down_revision` when introducing index and outbox schema migrations.
3. **Boundary Reminder:** Dừng sau R04; chưa bắt đầu P03.
