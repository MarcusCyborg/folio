# Folio Milestone Integration A / R01 — Test Target Safety & Database Isolation Handoff

**Handoff ID:** `IA-R01-test-isolation`  
**Milestone:** Integration A — Task R01 (Remediation of Finding IA-02: Test DB Safety Guard & Run Isolation Lifecycle)  
**Date:** 2026-11-01  
**Author:** Folio Test Infrastructure Engineer  
**Status:** `PURE SAFETY VERIFIED / LIVE POSTGRESQL BLOCKED_ENV` (Integration A in progress; R01 complete, P03 NOT STARTED)

---

## 1. Executive Summary & Finding IA-02 Remediation

Finding **IA-02** identified critical vulnerabilities in the P02 test database guard and test fixtures lifecycle:
1. **Driver Target Query Override:** The previous guard checked only `url.database` parsed from the URL path. In PostgreSQL drivers (e.g., `psycopg`), query parameters such as `?dbname=folio` override the path when SQLAlchemy generates driver connection arguments (`create_connect_args`). As demonstrated in review evidence, `TEST_DATABASE_URL=.../review_test?dbname=folio` was accepted by the guard, but the driver connected directly to `folio` (the primary application database) where `DROP SCHEMA IF EXISTS public CASCADE` was executed.
2. **Implicit Default Port & Loopback Collision Bypasses:** Omitting the default PostgreSQL port (`5432`) in one URL or using loopback aliases (`localhost` vs `127.0.0.1` vs `127.0.0.2` vs `::1`) bypassed collision detection against `DATABASE_URL`.
3. **Blanket Backend Termination:** `ensure_test_database_exists` executed `pg_terminate_backend(pid)` indiscriminately across all connections on the server, killing concurrent test runs.
4. **Lack of Run Ownership Manifest:** The test harness assumed shared ownership of `folio_test` and could drop pre-existing or unowned databases based solely on the `_test` suffix.

### Summary of R01 Changes:
- **Pure Standalone Safety Guard:** Extracted target validation out of `tests/conftest.py` into [`src/backend/core/test_db_guard.py`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/src/backend/core/test_db_guard.py). This module has **zero imports** of the FastAPI application, database engines, or conftest fixtures.
- **Policy Effective Driver Target:**
  - Evaluates effective connection arguments via `engine.dialect.create_connect_args(engine.url)` without opening network sockets.
  - Strictly rejects connection-target query overrides (`dbname`, `database`, `host`, `hostaddr`, `port`, `service`, `servicefile`, `target_session_attrs`, `options`) and multi-host DSNs.
  - Enforces a safe allowlist for auxiliary query parameters (`sslmode`, `connect_timeout`, `application_name`, etc.).
  - Redacts credentials in all exception messages and error output—passwords are never leaked.
  - Normalizes default port `5432` and all loopback host aliases (`localhost`, `127.0.0.1`, `127.0.0.2`, `::1`).
  - Rejects protected/production database names (`postgres`, `template0`, `template1`, `folio`, `folio_prod`, `production`, `prod`, `dev`, `master`, `main`).
  - Sanitizes and controls ambient libpq environment variables (`PGDATABASE`, `PGSERVICE`, `PGHOST`, etc.).
- **Run ID Ownership Manifest (`TestRunManifest`):**
  - Unique run ID per test invocation (`run_<uuid>`).
  - Generates collision-resistant, valid PostgreSQL identifiers (e.g., `folio_test_run_<uuid>`).
  - Tracks explicitly created databases. Rejects mutation, schema reset, or teardown of unowned databases.
- **Pre-Mutation Connected Identity Check:**
  - `verify_connected_identity` queries `current_database()` on the live connection before DDL execution.
  - In case of identity mismatch, execution aborts immediately with `ConnectedIdentityMismatchError` **without issuing DROP statements**.
- **Selective Backend Termination:**
  - Replaced blanket backend termination with `selective_terminate_backends_sql(target_db)`:
    `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :target_db AND pid <> pg_backend_pid()`.
  - Backends of concurrent runs or other databases are untouched.

---

## 2. Git Metadata & Worktree Verification

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Active Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree |
| **Branch** | `codex/integration-a-remediation` | Local integration branch |
| **Baseline Ref** | `9232aa1` | Task R00 source integration commit |
| **Files Modified** | `tests/conftest.py` | Refactored conftest lifecycle & guard integration |
| **Files Created** | `src/backend/core/test_db_guard.py` | Standalone pure safety guard & manifest module |
| | `tests/safety/test_pure_safety.py` | Pure safety unit test suite (45 tests) |
| | `tests/safety/test_db_lifecycle.py` | Live PostgreSQL lifecycle & concurrency suite |
| **Files Excluded** | Auth (`src/backend/api/auth.py`), Search contracts | Strictly untouched per ownership boundaries |

---

## 3. Test Execution & Evidence

### 3.1 Pure Safety Test Suite (`test_pure_safety.py`)

Pure unit tests execute independently with `--noconftest`, verifying all safety invariants without loading dangerous fixtures or opening network connections:

```powershell
# Command:
cd F:\dpl13.10\WikiSearchEngine-ia-fix
F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\pytest.exe --noconftest tests/safety/test_pure_safety.py -v

# Masked Environment:
# APP_ENV=test
# DATABASE_URL=postgresql+psycopg://review:***@127.0.0.1:5432/folio
# TEST_DATABASE_URL=postgresql+psycopg://review:***@127.0.0.1:5432/folio_test

# Exit Code: 0
```

#### Results Summary:
- **Total Tests:** 45
- **Passed:** 45
- **Failed:** 0
- **Execution Time:** 0.34s

#### Coverage Matrix:
| Category | Test Function(s) | Result |
| :--- | :--- | :--- |
| **Credential Redaction** | `test_redact_url_credentials_standard`, `test_redact_url_credentials_no_username`, `test_redact_url_credentials_empty_or_none`, `test_exception_does_not_leak_password_on_invalid_url` | **PASS** |
| **Finding IA-02 Query Override Reproduction** | `test_reproduce_ia02_dbname_override_rejected` (`review_test?dbname=folio` reproduced via dialect connect args) | **PASS** |
| **Query Target Overrides** | `test_forbidden_target_query_overrides_rejected` (`host`, `port`, `service`, `database`, `hostaddr`, `options`), `test_unsupported_query_param_rejected`, `test_allowed_query_params_accepted` | **PASS** |
| **Port & Loopback Normalization** | `test_implicit_default_port_collides_with_explicit_5432`, `test_loopback_alias_localhost_collides_with_127_0_0_1`, `test_loopback_alias_127_0_0_2_collides_with_127_0_0_1`, `test_loopback_ipv6_alias_collides_with_127_0_0_1`, `test_same_target_distinct_test_db_does_not_collide` | **PASS** |
| **Database Name & Scheme Validation** | `test_protected_names_rejected` (12 protected names: `postgres`, `folio`, `prod`, `master`, etc.), `test_missing_database_name_rejected`, `test_non_test_designated_name_rejected`, `test_invalid_identifier_rejected`, `test_non_postgres_driver_rejected`, `test_multi_host_url_rejected` | **PASS** |
| **Run Ownership Manifest** | `test_manifest_creation_and_unique_naming`, `test_manifest_tracks_only_owned_databases`, `test_safe_reset_refuses_unowned_database`, `test_safe_teardown_refuses_unowned_database`, `test_provision_refuses_existing_unowned_database` | **PASS** |
| **Selective Termination** | `test_selective_terminate_sql_has_target_filter` (asserts `datname = '...'` filter) | **PASS** |
| **Connected Identity Guard** | `test_verify_connected_identity_success`, `test_verify_connected_identity_mismatch_raises_without_mutation` | **PASS** |
| **Concurrent Runs Isolation** | `test_concurrent_runs_have_isolated_names_and_teardown_scope` | **PASS** |
| **Ambient libpq Environment Control** | `test_ambient_env_check_and_sanitize` | **PASS** |

### 3.2 Review Evidence Probe Reproduction (`probe_guard_contract.py`)

We executed the original probe cases from `docs/handoff/review/evidence-20261101-cf1bdce021/probe_guard_contract.py` against the new guard:

```json
[
  {
    "case": "same_literal_target",
    "accepted": false
  },
  {
    "case": "same_target_implicit_default_port",
    "accepted": false
  },
  {
    "case": "same_target_host_alias",
    "accepted": false
  },
  {
    "case": "postgresql_query_target_override",
    "accepted": false
  },
  {
    "case": "protected_main_name",
    "accepted": false
  }
]
```

**Comparison:**
- In the original review report, `same_target_implicit_default_port`, `same_target_host_alias`, and `postgresql_query_target_override` were incorrectly accepted (`accepted: true`).
- With R01 remediation, all 5 unsafe cases are strictly rejected (`accepted: false`).

---

## 4. Database Ownership Manifest Specification

The `TestRunManifest` records lifecycle metadata and boundaries for every test run without storing secrets:

```json
{
  "run_id": "run_9a1e4c3b",
  "created_at": "2026-11-01T06:35:00.000000Z",
  "pid": 14220,
  "created_databases": [
    "folio_test_run_9a1e4c3b"
  ]
}
```

### Operational Rules:
1. `run_id` is generated at pytest session start using a random alphanumeric identifier.
2. `created_databases` tracks only databases created via `provision_test_database`.
3. `safe_reset_test_schema` and `safe_teardown_test_database` assert `manifest.is_owned(dbname)`.
4. If an existing database with the same name is found on the server during provisioning, but is NOT present in `manifest.created_databases`, provisioning aborts with `UnownedDatabaseError`.

---

## 5. Environment Status: `BLOCKED_ENV` for Live PostgreSQL 16 Checks

### 5.1 Host Environment Investigation
An exhaustive inspection of the host Windows system was performed:
- `docker`: Not installed / command not recognized.
- `wsl`: Windows Subsystem for Linux has no installed distributions.
- Local PostgreSQL services: Zero running services found matching `*postgres*`.
- Executables (`psql.exe`, `pg_ctl.exe`, `initdb.exe`): None present on system PATH or Program Files.

### 5.2 Handling per Remediation Plan
In strict compliance with section 5 of `INTEGRATION-A-REMEDIATION-PLAN.md` and user instructions:
> *"Thiếu runtime thì làm xong phần độc lập, ghi BLOCKED_ENV và pending DB checks, không thay bằng SQLite rồi báo hoàn tất."*
> *"Test lỗi do thiếu dịch vụ ghi BLOCKED_ENV; không sửa expected status, disable validator, thêm xfail/skip hoặc nuốt exception để đạt xanh."*

- **Pure validator & safety suite:** 100% complete and verified (45/45 PASS).
- **Live Database Suite (`tests/safety/test_db_lifecycle.py`):** Fully authored and verified syntactically. When executed without a running PostgreSQL instance, it reports `BLOCKED_ENV` (3 skipped with explicit prerequisite reason). SQLite was NOT substituted.

### 5.3 Pending Live PostgreSQL Checks (To execute once PG16 container/service is provisioned)
1. `TestLiveDatabaseLifecycle::test_live_provision_migrate_seed_and_teardown`:
   - Live execution of `CREATE DATABASE "{run_db}"` via `provision_test_database`.
   - Live execution of `alembic upgrade head` on the freshly provisioned test DB.
   - Live execution of `run_seed(target=test_engine)`.
   - Verification of document count > 0 in `documents` table.
   - Teardown via `safe_teardown_test_database` and verification of DB deletion.
2. `TestLiveDatabaseLifecycle::test_live_two_concurrent_runs_and_sentinel_isolation`:
   - Live creation of `folio_test_disposable_sentinel` with sentinel table and marker row.
   - Two concurrent runs (`run1`, `run2`) creating separate databases.
   - Teardown of `run1` leaves `run2` database and `folio_test_disposable_sentinel` completely intact with data preserved.
   - Teardown of `run2`.
   - Cleanup of disposable sentinel.
3. `TestLiveDatabaseLifecycle::test_live_existing_unowned_database_rejected`:
   - Pre-existing database on instance is rejected during provisioning attempt and preserved without DROP.

---

## 6. How to Run & Reproduce

### 6.1 Run Pure Safety Tests (No external service required)
```powershell
cd F:\dpl13.10\WikiSearchEngine-ia-fix
.\venv\Scripts\pytest.exe --noconftest tests/safety/test_pure_safety.py -v
```

### 6.2 Run Live Database Lifecycle Tests (Once PostgreSQL 16 is running)
```powershell
# Set administrative connection URL to PostgreSQL 16 instance:
$env:FOLIO_TEST_ADMIN_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"

# Run live lifecycle tests:
cd F:\dpl13.10\WikiSearchEngine-ia-fix
.\venv\Scripts\pytest.exe --noconftest tests/safety/test_db_lifecycle.py -v
```

---

## 7. Gaps, Blockers & Handoff to R02

1. **Finding IA-02 Status:** `FIXED (Pure Safety Verified; Live PG16 Environment Blocked)`.
2. **Finding IA-01 Status:** Remains in progress across remediation tasks.
3. **Task R02 Input:**
   - Worktree: `F:/dpl13.10/WikiSearchEngine-ia-fix`
   - Branch: `codex/integration-a-remediation`
   - Scope: Task R02 (Bootstrap identity rotation fix IA-03 & security regression tests).
4. **Boundary Reminder:** Dừng sau R01; chưa bắt đầu P03.
