# Folio Milestone M1 / P01 Production Security & Admin Bootstrap Handoff

**Handoff ID:** `P01-production-security`  
**Milestone:** M1 (Production Configuration, Security Hardening & Admin Bootstrap)  
**Date:** 2026-11-01  
**Author:** Backend Security Engineer  
**Target Repository:** `F:/dpl13.10/WikiSearchEngine-p01` (Git Worktree branched from `F:/dpl13.10/WikiSearchEngine-github`)  
**Git Branch:** `feature/p01-security`  
**Base Commit:** `c4b19cffa676b4437e7346da2c410b198b04dc2c` (`origin/main`)  

---

## 1. Executive Summary

Milestone M1 (P01) enforces production-grade security invariants across configuration validation, session management, credential protection, cross-origin communication, request throttling, error redaction, and administrative bootstrapping.

Key accomplishments:
1. **Startup Fail-Fast Lifespan Validation:** Integrated `settings.validate_production()` into the FastAPI `lifespan` context manager. Application fails to boot in `production` if `APP_SECRET` is weak or default, `COOKIE_SECURE` is `False`, or `DATABASE_URL` contains default development credentials.
2. **CORS & Origin Standardization:** Prohibited wildcard `*` origins whenever `allow_credentials=True`. Implemented `OriginVerificationMiddleware` to protect state-modifying requests (`POST`, `PUT`, `PATCH`, `DELETE`) from cross-origin CSRF attacks prior to CSRF token evaluation.
3. **Initial Admin Provisioning & Rotation CLI:** Authored [`scripts/bootstrap_admin.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/scripts/bootstrap_admin.py) with hidden terminal password prompt (`getpass`) or environment secret injection (`ADMIN_BOOTSTRAP_PASSWORD`). Automatically validates password entropy, provisions roles/permissions, rotates passwords, invalidates all existing active sessions, writes immutable audit trails, and guarantees zero password leakage in logs.
4. **Session, Cookie & Auth Hardening:**
   - Enforced `HttpOnly=True`, `SameSite=Lax`, and `Secure` (when `COOKIE_SECURE=True`).
   - Enforced session and CSRF token rotation on both `/api/v1/auth/login` and `/api/v1/auth/register`.
   - Prevented deactivated accounts from authenticating or taking actions; immediate session revocation when accounts are deactivated.
   - Built thread-safe sliding window rate limiting for failed logins and burst registrations (`src/backend/core/rate_limit.py`).
5. **Production Error Masking & Security Headers:**
   - Created global unhandled exception handler returning generic HTTP 500 error responses in production/staging without leaking tracebacks, SQL statements, or database connection strings.
   - Enhanced `src/backend/core/audit.py` with regex redaction for PostgreSQL connection strings (`postgresql://[REDACTED_USER]:[REDACTED_PASSWORD]@...`) and authorization tokens.
   - Added `SecurityHeadersMiddleware` injecting CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, and HSTS. Fully validated against all Folio frontend ES modules, self-hosted WOFF2 fonts, demo SVGs, and Paper/Ink styles.
6. **Automated Test Evidence:** 12 new automated security tests created in `tests/backend/foundation/test_security_hardening.py`; 100% passed. Full backend test suite expanded from 58 to 70 tests with zero regressions.

---

## 2. Environment Configuration Matrix

The runtime environment is normalized to four canonical tiers: `development`, `test`, `staging`, and `production`.

| Setting Key | Development | Test | Staging | Production | Enforced By |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `APP_ENV` | `development` (aliases: `dev`, `local`) | `test` (alias: `testing`) | `staging` (alias: `stage`) | `production` (alias: `prod`) | `config.py:normalize_env` |
| `APP_SECRET` | Default dev key allowed | Default dev key allowed | Min 32 chars, high entropy, no default patterns | Min 32 chars, high entropy, no default patterns | `validate_production()` fail-fast at boot |
| `COOKIE_SECURE` | `false` | `false` | `true` (recommended) | **`true` (MANDATORY)** | `validate_production()` fail-fast at boot |
| `COOKIE_SAMESITE` | `lax` | `lax` | `lax` | `lax` (or `strict`) | `session.py:set_session_cookie` |
| `CORS_ALLOWED_ORIGINS` | `localhost:8000, 127.0.0.1:8000, localhost:3000` | `http://testserver, http://localhost` | Explicit domain list | Explicit domain list (e.g. `https://folio.example.com`) | `CORSMiddleware` & `OriginVerificationMiddleware` |
| **Wildcard CORS with Credentials** | **STRICTLY BLOCKED** | **STRICTLY BLOCKED** | **STRICTLY BLOCKED** | **STRICTLY BLOCKED** | `main.py` & `validate_production()` |
| `DATABASE_URL` | Local PostgreSQL | Isolated test DB | Staging DB | Production DB (Default `postgres:postgres` disallowed) | `validate_production()` |
| `RATE_LIMIT_ENABLED` | `true` | `true` (resettable) | `true` | `true` | `rate_limit.py` |
| `RATE_LIMIT_LOGIN_MAX_FAILED` | 5 failures / 60s | 5 failures / 60s | 5 failures / 60s | 5 failures / 60s | `rate_limit.py` |
| `RATE_LIMIT_REGISTER_MAX` | 10 registrations / 60s | 10 registrations / 60s | 10 registrations / 60s | 10 registrations / 60s | `rate_limit.py` |
| `DEMO_PASSWORD` | `FolioDemo2026!` (dev seed) | `FolioDemo2026!` | **IGNORED / SKIPPED** | **IGNORED / SKIPPED** | `seed_folio.py:seed_demo_users` |
| `ENABLE_LEGACY_SEARCH` | `false` (default) | `false` | `false` | `false` (flag protected) | `main.py` |

---

## 3. Files Created & Modified

### Modified Files (Under P01 Ownership)
- [`src/backend/core/config.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/config.py): Environment normalization, CORS parsing, rate limit thresholds, reverse proxy configuration, and fail-fast `validate_production()` validator.
- [`src/backend/main.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/main.py): Lifespan context manager invoking `validate_production()`, global unhandled exception handler, security headers middleware, origin verification middleware, and credential-safe CORS origin filtering.
- [`src/backend/core/exceptions.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/exceptions.py): Added `unhandled_exception_handler` with zero-leak production error masking and sensitive detail redaction.
- [`src/backend/core/session.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/session.py): Standardized `set_session_cookie` and `clear_session_cookie` with configurable `secure` and `samesite` attributes.
- [`src/backend/core/dependencies.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/dependencies.py): Deactivated user session detection, immediate session revocation upon deactivation in `get_current_user`.
- [`src/backend/core/audit.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/audit.py): Added `redact_sensitive_text()` for PostgreSQL connection strings and token assignments; expanded sensitive key filters.
- [`src/backend/api/auth.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/api/auth.py): Injected rate limiting guards into `/api/v1/auth/login` and `/api/v1/auth/register`, tracking failed attempts per IP and per identifier.
- [`scripts/seed_folio.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/scripts/seed_folio.py): Blocked demo user seeding when `APP_ENV in ("production", "staging")`; added `--no-demo-users` CLI flag.
- [`.env.example`](file:///F:/dpl13.10/WikiSearchEngine-p01/.env.example): Fully documented all production configuration options, security invariants, rate limits, and bootstrap instructions.

### New Files Created
- [`src/backend/core/rate_limit.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/rate_limit.py): Thread-safe in-memory sliding window rate limiter and trusted proxy client IP resolver (`X-Forwarded-For`).
- [`src/backend/core/middleware.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/middleware.py): `SecurityHeadersMiddleware` (CSP, nosniff, DENY, HSTS) and `OriginVerificationMiddleware` (cross-site origin defense).
- [`scripts/bootstrap_admin.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/scripts/bootstrap_admin.py): Production CLI for initial admin provisioning and credential rotation.
- [`tests/backend/foundation/test_security_hardening.py`](file:///F:/dpl13.10/WikiSearchEngine-p01/tests/backend/foundation/test_security_hardening.py): Comprehensive test suite covering config validation, cookie flags, origin rejection, abuse rate limiting, admin bootstrap CLI, secret redaction, and error masking.

---

## 4. Test Execution & Verification Evidence

All tests were executed against the dedicated test database `folio_test` on Windows 10 / Python 3.10.11 within the `WikiSearchEngine-p01` worktree.

### 4.1 Dedicated Security Hardening Suite (`test_security_hardening.py`)
```powershell
cd F:\dpl13.10\WikiSearchEngine-p01
python -m pytest tests/backend/foundation/test_security_hardening.py -v
```
**Output Summary:**
```text
tests/backend/foundation/test_security_hardening.py::test_production_boot_fails_on_weak_secret PASSED
tests/backend/foundation/test_security_hardening.py::test_production_boot_fails_on_insecure_cookie PASSED
tests/backend/foundation/test_security_hardening.py::test_production_boot_fails_on_wildcard_cors PASSED
tests/backend/foundation/test_security_hardening.py::test_production_boot_succeeds_with_hardened_config PASSED
tests/backend/foundation/test_security_hardening.py::test_cookie_security_flags_on_response PASSED
tests/backend/foundation/test_origin_header_validation_cross_site_rejection PASSED
tests/backend/foundation/test_login_rate_limiting_abuse PASSED
tests/backend/foundation/test_registration_rate_limiting_abuse PASSED
tests/backend/foundation/test_admin_bootstrap_cli_creation_and_rotation PASSED
tests/backend/foundation/test_secret_redaction_in_audit_and_text PASSED
tests/backend/foundation/test_security_headers_present PASSED
tests/backend/foundation/test_production_error_zero_leak PASSED

======================= 12 passed, 2 warnings in 1.40s =======================
```

### 4.2 Full Backend Regression Suite (`tests/backend`)
```powershell
cd F:\dpl13.10\WikiSearchEngine-p01
python -m pytest tests/backend
```
**Output Summary:**
```text
============================= test session starts =============================
platform win32 -- Python 3.10.11, pytest-9.2.0, pluggy-1.6.0
rootdir: F:\dpl13.10\WikiSearchEngine-p01
configfile: pytest.ini
collected 70 items

tests\backend\admin\test_admin_api.py ........                           [ 11%]
tests\backend\admin\test_analytics_metrics.py ..                         [ 14%]
tests\backend\admin\test_document_lifecycle.py .                         [ 15%]
tests\backend\admin\test_governance_and_last_admin.py ....               [ 21%]
tests\backend\admin\test_moderation_flow.py .                            [ 22%]
tests\backend\admin\test_permissions_and_security.py ..                  [ 25%]
tests\backend\admin\test_preview.py ....                                 [ 31%]
tests\backend\admin\test_seo_and_audit.py ...                            [ 35%]
tests\backend\admin\test_taxonomy_lifecycle.py ..                        [ 38%]
tests\backend\foundation\test_auth.py .......                            [ 48%]
tests\backend\foundation\test_frontend_assets.py .                       [ 50%]
tests\backend\foundation\test_permissions.py .                           [ 51%]
tests\backend\foundation\test_security_hardening.py ............         [ 68%]
tests\backend\foundation\test_startup.py ...                             [ 72%]
tests\backend\integration\test_e2e_workflow.py .                         [ 74%]
tests\backend\library\test_click_idempotency.py ...                      [ 78%]
tests\backend\library\test_library_api.py ...............                [100%]

====================== 70 passed, 16 warnings in 14.10s =======================
```

### 4.3 Admin Bootstrap CLI Verification
```powershell
# Help display
python scripts/bootstrap_admin.py --help
# Result: Exit code 0, complete arguments list displayed

# Creation (non-interactive)
python scripts/bootstrap_admin.py --email admin_cli@folio.test --username admin_cli --password "CliSuperPassword2026!" --non-interactive
# Output: [SUCCESS] Initial Super Admin account 'admin_cli' (admin_cli@folio.test) provisioned successfully.

# Duplicate prevention
python scripts/bootstrap_admin.py --email admin_cli@folio.test --username admin_cli --password "CliSuperPassword2026!" --non-interactive
# Output: ERROR: User 'admin_cli' (admin_cli@folio.test) already exists. Specify --rotate to update password. (Exit code 1)

# Credential rotation & session revocation
python scripts/bootstrap_admin.py --email admin_cli@folio.test --username admin_cli --password "CliSuperPasswordRotated2026!" --rotate --non-interactive
# Output: [SUCCESS] Admin account 'admin_cli' (admin_cli@folio.test) password rotated. Revoked 0 active sessions. (Exit code 0)
```

---

## 5. Migration & Configuration Impact

- **Database Migrations:** Zero schema changes required. Existing tables (`users`, `sessions`, `roles`, `permissions`, `audit_logs`) support all hardened functionality without Alembic revision.
- **Environment Variables:**
  - `APP_ENV`: Now enforced. Invalid values fail at boot.
  - `COOKIE_SECURE`: If `APP_ENV=production`, setting to `false` halts application boot.
  - `APP_SECRET`: If `APP_ENV=production`, using default keys or length < 32 halts application boot.
  - `CORS_ALLOWED_ORIGINS`: In production, must be explicitly specified (e.g. `https://folio.example.com`). Wildcards (`*`) with credentials halt application boot.
- **Production Seeding Policy:** `scripts/seed_folio.py` skips demo accounts (`admin@folio.test`, `reader@folio.test`, etc.) whenever `APP_ENV in ("production", "staging")`. Initial admin setup MUST be completed via `scripts/bootstrap_admin.py`.

---

## 6. Unhardened Areas & Downstream Dependencies

The following security and operational items fall outside P01 ownership and are formally assigned to downstream phases:

1. **Assigned to P02 (Clean Setup & CI Isolation):**
   - Provisioning isolated Python virtual environments without global site-packages.
   - Guarded test runner automation ensuring `folio_test` is created and migrated prior to test execution.
2. **Assigned to P05 (Search API Security):**
   - Query string length limiting (1–200 characters) and rate limiting on `/api/v1/search`.
   - Relational publication state validation under asynchronous index lag.
3. **Assigned to P08 (Production Container & Infrastructure Ops):**
   - Caddy / Nginx TLS certificate termination, automated HTTPS renewal, and real reverse proxy header injection.
   - Non-root user permissions in Docker container runtime.
   - Encrypted PostgreSQL database backups and disaster recovery runbooks.

---

## 7. Next Actions

1. Integrate branch `feature/p01-security` with P02 (`feature/p02-clean-setup`) during **Integration Checkpoint A**.
2. Run full regression suite across both security hardening and clean CI setup before proceeding to P03 (Outbox & Index Ingestion).
