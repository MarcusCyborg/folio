# Folio Milestone Integration A / R04.5 — Integration Checkpoint Report

**Checkpoint ID:** `IA-R04.5-integration-checkpoint`  
**Milestone:** Integration A — Checkpoint R04.5 (Post R02–R04 Integration Verification)  
**Date:** 2026-11-01  
**Author:** Folio Integration Reviewer  
**Status:** `INTEGRATION STATIC PASS / LIVE DB BLOCKED`  
*(P03 NOT STARTED; Integration A NOT PASSED; Live PostgreSQL environment verification required before declaring Integration A PASS or GO P03)*

---

## 1. Official Worktree & Git Metadata

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Mandatory Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree |
| **Integration Branch** | `codex/integration-a-remediation` | Local integration branch (no push, no merge to main) |
| **Current Tested HEAD SHA** | `4024c3eff071ea4fc9dd5f5fa76b7735af1a60c6` | Commit prior to R04.5 checkpoint fixes |
| **Final R04.5 Commit SHA** | `262d28961907657651b39478ceacebcc288dff55` | Checkpoint remediation commit incorporating conftest & signature fixes |
| **Merge Base (Common Ancestor)**| `c4b19cffa676b4437e7346da2c410b198b04dc2c` | Common parent of P01 and P02 |
| **P01 Source Branch Ref** | `740eb5f1cc5f6b0c90480310e37a36234086a726` | `feature/p01-security` |
| **P02 Source Branch Ref** | `1ac72ad8a9e979682ddad8253c0d6d3e49222055` | `feature/p02-clean-setup` |
| **P01/P02 Merge Commit Ref** | `25a6b551616bcfde1649cac9fddad7d922ba2d78` | 3-way merge commit resolving `scripts/seed_folio.py` |

### 1.1 Complete Ancestry Chain Verification
The commit ancestry of `HEAD` (`codex/integration-a-remediation`) strictly incorporates all planned remediation streams R00 through R04 in linear topological order:

```text
* 4024c3e (HEAD) feat(rate-limit): remediate IA-06 shared distributed limiter, atomic row locking, and concurrency tests (R04)
* bf6b930 feat(security): remediate IA-03 bootstrap identity rotation, enforce session revocation commit, and verify startup security (R02)
* 4502472 docs(search-contract): remediate IA-04 canonical UUIDv4/v5 IDs and IA-05 search context pagination contract (R03)
* 86365ac fix(test-infra): remediate IA-02 test DB safety guard, manifest ownership, and fixture isolation (R01)
* 9232aa1 docs(handoff): record R00 source integration, conflict resolution, and remediation artifacts (R00)
*   25a6b55 merge(p02): integrate clean setup, test isolation, conftest, and CI pipeline with seed resolution
|\  
| * 1ac72ad (feature/p02-clean-setup) feat(p02): clean setup, stratified dependencies, test DB guard...
* | 740eb5f (feature/p01-security) docs(handoff): update P01 handoff with final commit SHA
* | 42bd60d fix(security): refine admin bootstrap commit handling and rate limit test cleanup
* | 998ba09 feat(security): implement M1 production validation, security headers, rate limiting, and admin bootstrap
|/  
* c4b19cf (main, origin/main) chore: move public screenshots outside the repository
```

- **Conflict Status:** Zero unresolved conflict markers (`git grep "<<<<<<<"` returned 0 matches).
- **Whitespace / Git Check:** Clean (`git diff --check` exited code 0).
- **Compilation:** All modules pass clean compilation (`python -m compileall src scripts tests` exit code 0).

---

## 2. Alembic Migration Chain & P03 Down-Revision Lock

The Alembic migration graph was audited via direct tool execution:

```powershell
& F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\alembic.exe heads
# Output:
# 20261101_rate_limit (head)

& F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\alembic.exe history
# Output:
# 20261031_click_unique -> 20261101_rate_limit (head), add_rate_limit_buckets_table
# efeaa3d84c9b -> 20261031_click_unique, click_idempotency_unique
# <base> -> efeaa3d84c9b, initial_folio_schema
```

### 2.1 Offline SQL Generation Verification
Executed `alembic upgrade head --sql` to verify transactional DDL integrity:
- **Result:** Successfully generated complete SQL migration script wrapped in `BEGIN; ... COMMIT;`.
- **Created Structures:**
  - Base schema tables (`app_settings`, `categories`, `permissions`, `roles`, `tags`, `users`, `audit_logs`, `documents`, `sessions`, `comments`, `interaction_logs`, `reports`, etc.).
  - Unique partial index `ix_interaction_logs_actor_request_unique` on `(actor_key, request_key) WHERE request_key IS NOT NULL`.
  - Rate limit persistent storage `rate_limit_buckets` table with `attempts JSONB` and indices on `action, updated_at`.
- **Down-Revision Requirement for P03:**
  The current head is **`20261101_rate_limit`**.
  Any migration created in **P03** (e.g. index generation metadata, outbox jobs) **MUST** declare:
  ```python
  down_revision = "20261101_rate_limit"
  ```
  P03 must not use `20261031_click_unique` or fork into multiple heads.

---

## 3. Finding IA-02 & Ownership Lifecycle Code Audit

### 3.1 Blocker Identified: Premature Manifest Registration in `tests/conftest.py`
- **Defect:** Line 55 of `tests/conftest.py` called `session_manifest.register_owned(target_validation.effective_database)` at module import time, before `ensure_test_database_exists` had verified or provisioned the database.
- **Impact:** If `TEST_DATABASE_URL` pointed to an existing database on the PostgreSQL instance that was created by another process or prior test run, line 55 prematurely claimed ownership in `session_manifest`. Subsequently, `prepare_test_database` called `safe_reset_test_schema(test_engine, session_manifest, ...)`, which accepted the target as owned and dropped its schema (`DROP SCHEMA IF EXISTS public CASCADE`), defeating the IA-02 safety guard.
- **R04.5 Minimal Fix:**
  1. Removed line 55 from `tests/conftest.py`.
  2. Database ownership is **strictly registered only after successful `CREATE DATABASE`** in `ensure_test_database_exists`.
  3. If the database already existed prior to the run, `session_manifest` does **not** register it and does **not** terminate active connections.
  4. When `safe_reset_test_schema` executes, `manifest.is_owned(...)` returns `False`, raising `UnownedDatabaseError` and aborting without issuing any `DROP` statement or opening an engine connection.
- **Regression Verification:** Added `TestR045RegressionSafeguards.test_safe_reset_refuses_pre_existing_unowned_db_without_create_database` in `tests/safety/test_pure_safety.py` proving that an unowned pre-existing DB is refused immediately with `UnownedDatabaseError` and zero engine connections.

---

## 4. `provision_test_database` Signature & Call-Site Audit

### 4.1 Keyword Argument Discrepancy Remediated
- **Defect:** In `tests/security/test_bootstrap_postgres_lifecycle.py:81`, the call site used `target_database=run_db_name`, whereas `src/backend/core/test_db_guard.py:530` declared `(admin_url_str, manifest, requested_dbname=None)`. If live PostgreSQL tests had run, this would have crashed with `TypeError: provision_test_database() got an unexpected keyword argument 'target_database'`.
- **R04.5 Minimal Fix:**
  1. Updated `provision_test_database` signature in `src/backend/core/test_db_guard.py` to accept both `requested_dbname: str | None = None, target_database: str | None = None`. Both keywords and positional arguments are supported seamlessly.
  2. Aligned `tests/security/test_bootstrap_postgres_lifecycle.py` to use `requested_dbname=run_db_name` and consume the returned URL.
  3. Added regression test `TestR045RegressionSafeguards.test_provision_test_database_signature_interoperability` in `tests/safety/test_pure_safety.py`, validating all 3 calling styles (keyword `requested_dbname`, keyword `target_database`, and positional).

---

## 5. Audit of Verification Claims (R02 & R04)

We explicitly separate claims by testing tier and underlying storage engine:

| Tier | Test Scope / Suite | Storage / Engine | Result in Worktree | Claim Status |
| :--- | :--- | :--- | :--- | :--- |
| **Pure Safety Guard** | `tests/safety/test_pure_safety.py` (47 tests) | In-Memory Dialect / Mocks | **47 PASSED** (0.39s) | **VERIFIED** |
| **Pure Rate Limiter** | `tests/safety/test_pure_rate_limit.py` (15 tests) | In-Memory Sliding Window | **15 PASSED** (0.05s) | **VERIFIED** |
| **Bootstrap Identity Matrix** | `tests/security/test_bootstrap_security.py` (19 tests) | Mock Session / CLI exit codes | **19 PASSED** (1.30s) | **VERIFIED** |
| **Subprocess Startup Security** | `tests/security/test_startup_subprocess.py` (8 tests) | Real OS Python Subprocesses | **8 PASSED** (10.74s) | **VERIFIED** |
| **Runtime Security & RBAC** | `tests/security/test_runtime_security_hardening.py` (8 tests) | FastAPI TestClient / SQLite Savepoints | **8 PASSED** (3.44s) | **VERIFIED** |
| **Multiprocess Rate Limiter** | `tests/backend/foundation/test_shared_rate_limit_concurrency.py` (11 tests) | **SQLite WAL File** (`sqlite:///{path}`) | **11 PASSED** (Hist/R04) | **VERIFIED ON SQLITE**<br/>*(NOT PostgreSQL verified)* |
| **PostgreSQL DB Lifecycle** | `tests/safety/test_db_lifecycle.py` | Live PostgreSQL Server | **SKIPPED (BLOCKED_ENV)** | **BLOCKED_ENV** |
| **PostgreSQL Bootstrap CLI** | `tests/security/test_bootstrap_postgres_lifecycle.py` | Live PostgreSQL Server | **SKIPPED (BLOCKED_ENV)** | **BLOCKED_ENV** |

### Policy Enforcement:
- As demonstrated above, the multi-process suite in `test_shared_rate_limit_concurrency.py` validates cross-process state persistence and concurrency using temporary **SQLite WAL files**. While proving independent process communication, it **DOES NOT** prove PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) or PostgreSQL server clocks (`clock_timestamp()`).
- In accordance with R04.5 instructions: **This suite is NOT labeled as PostgreSQL verified.**
- Live PostgreSQL tests remain strictly designated as **`BLOCKED_ENV`**. SQLite is not used as a substitute for PostgreSQL verification.

---

## 6. Execution Evidence of Safety Checks

### 6.1 Pure Safety & Security Test Suite
Executed command:
```powershell
F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\pytest.exe --noconftest `
  tests/safety/test_pure_safety.py `
  tests/security/test_bootstrap_security.py `
  tests/security/test_startup_subprocess.py `
  tests/security/test_runtime_security_hardening.py `
  tests/safety/test_pure_rate_limit.py -q
```
- **Exit Code:** `0`
- **Summary:** `97 passed, 1 warning in 18.29s`
- **Failures:** `0`

### 6.2 Python Bytecode Compilation
Executed command:
```powershell
F:\dpl13.10\WikiSearchEngine-p02\venv\Scripts\python.exe -m compileall src scripts tests
```
- **Exit Code:** `0`
- **Result:** All source, script, and test files compiled with zero syntax or syntax-related errors.

### 6.3 Host PostgreSQL Instance Probe
- Probed host loopback `127.0.0.1:5432`: Connection failed (`TCP connect to 127.0.0.1:5432 failed`).
- Windows services: No `postgres` or `postgresql` service found.
- Docker daemon: Not available on host.
- **PostgreSQL Availability:** **UNAVAILABLE (`BLOCKED_ENV`)**.
- In accordance with R04.5 safety rules: Zero live tests were executed against any unowned or shared databases.

---

## 7. Search Contract Alignment & P03 Input Synchronization

### 7.1 Canonical Fixture Preservation (Finding IA-04)
- Audited [`fixtures/folio/documents.jsonl`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/fixtures/folio/documents.jsonl):
  - **Total Record Count:** Exactly `103` documents (100 published, 3 draft).
  - **UUID Versions:** Exactly `103` version 5 UUIDs (`{5: 103}`).
  - **File SHA-256:** `5413a1f6265dc5f4ccea0081356690e54bd63ed78c6b63ad1fee9025b4183abe`.
  - **Contract Preservation:** Importer in P03 must preserve these exact UUIDv5 IDs and mapping `source_url -> Document.id` without re-minting.

### 7.2 Search Context Pagination & Lease Contract (Finding IA-05)
- Search Contract v2.1.0 specifications locked:
  - **Single Mechanism:** Server-Issued Actor-Bound Search Context (Candidate Snapshot Cursor).
  - **Absolute TTL:** 15 minutes (`SEARCH_CONTEXT_TTL_MINUTES=15`).
  - **Retention Lease:** P03 background GC worker **MUST NOT** purge generation files while active search contexts hold a valid lease.
  - **Count Semantics:** `snapshot_total` (exact for BM25), `snapshot_candidate_count` / `is_approximate_total: true` (for semantic/hybrid), and explicit boolean `has_more`.
  - **Pruning:** Fixed rank window, prune without backfill.

### 7.3 Stale Documentation Corrections
1. **`GEMINI-EXECUTION-PROMPTS.md`:** Updated P03 prompt block to mandate:
   - Worktree: `F:/dpl13.10/WikiSearchEngine-ia-fix`
   - Branch: `codex/integration-a-remediation`
   - Alembic Down Revision: Single linear head `20261101_rate_limit`.
   - References to IA-R00 through IA-R04.5 handoffs.
2. **`docs/acceptance-matrix.md`:** Updated Alembic revision notes in summary and item `P1-02` from stale `20261031_click_unique` to current head `20261101_rate_limit`.
3. **No Code Expansion:** Zero search engine, BM25, or corpus importer code was authored in R04.5.

---

## 8. Summary of Files Changed in R04.5 Scope

| File Path | Nature of Change |
| :--- | :--- |
| `tests/conftest.py` | Removed import-time `session_manifest.register_owned` call; manifest only registers after successful `CREATE DATABASE`. |
| `src/backend/core/test_db_guard.py` | Extended `provision_test_database` signature to support both `requested_dbname` and `target_database` keyword arguments. |
| `tests/security/test_bootstrap_postgres_lifecycle.py` | Corrected call site keyword argument from `target_database` to `requested_dbname`. |
| `tests/safety/test_pure_safety.py` | Added regression test class `TestR045RegressionSafeguards` (2 new tests: unowned DB safe_reset refusal and signature interoperability). |
| `GEMINI-EXECUTION-PROMPTS.md` | Synchronized P03 execution prompt with required worktree, branch, handoffs, and Alembic head `20261101_rate_limit`. |
| `docs/acceptance-matrix.md` | Corrected stale references to Alembic migration head to `20261101_rate_limit`. |
| `docs/handoff/gemini/IA-R04.5-integration-checkpoint.md` | This formal checkpoint handoff document. |

---

## 9. Integration Checkpoint Conclusion & Next Steps

### Official Status: `INTEGRATION STATIC PASS / LIVE DB BLOCKED`

- **Static Integrity:** All code compilation, git ancestry, Alembic migration chains, offline SQL generation, pure safety, subprocess security, and rate limit tests **PASS** unconditionally.
- **Integration Defects Remediated:** The conftest manifest premature registration bug and the `provision_test_database` signature mismatch have been resolved with regression tests.
- **PostgreSQL Environment:** Live PostgreSQL instance is not reachable (`BLOCKED_ENV`). Therefore, neither Integration A nor P03 can be declared unconditionally PASSED or GO.
- **Proceeding to R05:** Work may proceed to **R05 (Clean CI, artifacts, evidence manifest, and setup documentation)** within `F:/dpl13.10/WikiSearchEngine-ia-fix` on branch `codex/integration-a-remediation`. P03 remains locked until full integration verification.
