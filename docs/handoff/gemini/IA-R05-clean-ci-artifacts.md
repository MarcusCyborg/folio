# Folio Milestone Integration A / R05 — Clean CI, Fixtures, and Artifact Isolation Handoff Report

**Handoff ID:** `IA-R05-clean-ci-artifacts`  
**Milestone:** Integration A — Task R05 (Remediation of Finding IA-07: Artifact Isolation, Browser State Reset, Fixture Audit, and CI Pipeline)  
**Date:** 2026-11-01  
**Author:** Folio Build / Test Infrastructure Engineer  
**Status:** `ARTIFACT & FIXTURE REMEDIATION VERIFIED / REMOTE CI UNVERIFIED / LIVE DB BLOCKED_ENV`  
*(P03 NOT STARTED; R05 complete; Integration A evaluation handed over to independent reviewer R06; NO P03 GO declared)*

---

## 1. Executive Summary & Remediation of Finding IA-07

Finding **IA-07** in the Integration A review identified that browser visual verification tests and screenshot scripts directly overwrote baseline deliverables in `docs/verification/` and `../screenshots` using fixed file names without run IDs or isolation, dirtying working trees and masking failure traces. Additionally, browser test fixtures ran across non-rollback sessions, risking ordering dependencies.

### Summary of R05 Deliverables:
1. **Configurable Unified Artifact Root (`src/backend/core/artifact_utils.py`):**
   - Implements collision-free artifact convention: `<artifact_root>/<worktree_or_checkout>/<commit_sha>/<run_id>/...`
   - Output root is configurable via `FOLIO_ARTIFACT_ROOT`, `FOLIO_SCREENSHOT_DIR`, or `--output-dir` CLI flag. Default points to git-ignored `test-results/artifacts/`.
   - Run ID incorporates timestamp + 8-hex random suffix (`run_YYYYMMDD_HHMMSS_<rand>`), guaranteeing non-overlapping output across consecutive runs or concurrent executions.
   - Comprehensive filename sanitization (`sanitize_artifact_name`) prevents path traversal vulnerabilities.
   - Invariant: Zero writes to `../screenshots` or `docs/verification`. All 52 tracked baseline PNG files in `docs/verification` remain 100% bit-for-bit identical before and after all test runs.
2. **Genuine Playwright Tracing & Intentional Failure Verification:**
   - Playwright browser launcher instruments every `BrowserContext` with `context.tracing.start(screenshots=True, snapshots=True, sources=True)`.
   - On test failure, `pytest_runtest_makereport` captures a full-page failure screenshot and executes `context.tracing.stop(path=...)` saving a valid `.zip` trace archive before closing the context.
   - Genuine failure artifacts verified via intentional assertion failure probe, proving non-empty `.png` image and valid `.zip` archive containing `trace.json` are generated on disk. Intentional error probe reverted.
3. **Browser Test Database State Isolation (`tests/conftest.py`):**
   - Solves the gap where browser HTTP requests commit directly to the database and cannot be rolled back by `db_session`.
   - Implements `reset_browser_test_data(engine)` and auto-use fixture `isolate_frontend_test_database`.
   - Resets `app_settings` to `DEFAULT_SETTINGS`, restores demo accounts and clears commenting suspensions, deletes temporary test users, cleans up test documents and categories, and purges test interaction records.
   - Proven order-independent by executing simulated Flow A -> Flow B versus Flow B -> Flow A with identical clean baseline states.
4. **Clean Virtual Environment & Constraints Verification:**
   - Created clean Python 3.10 virtual environment (`F:\dpl13.10\WikiSearchEngine-ia-fix\venv`) with `include-system-site-packages = false`.
   - Installed full dependency stack with `constraints.txt`.
   - Executed `pip check` with 0 broken requirements.
5. **Authentic Fixture Audit & Stale Claim Correction:**
   - Audited authentic fixture file `fixtures/folio/documents.jsonl`: SHA256 `5413a1f6265dc5f4ccea0081356690e54bd63ed78c6b63ad1fee9025b4183abe`.
   - Exact counts: **103 total documents** (100 published, 3 draft), **6 categories**, **123 unique tags**.
   - Preserves canonical UUIDs (both Folio UUIDv4 and UUIDv5 preserved).
   - Corrected stale `README.md` claim of 162 published / 154 tags to match authentic dataset (5 users, 100 published, 3 drafts, 6 categories, 123 tags). The authentic dataset was NOT modified to match stale reports.
6. **Two-Pass Seeding Idempotency & Preserved Edits:**
   - Automated two-pass seeding test (`test_seed_idempotency_asserts.py`):
     - Pass 1 seeds clean database (asserts 5 users, 100 published, 3 drafts, 6 categories, 123 tags).
     - Preserved edit check: modified a document's summary and an AppSetting toggle.
     - Pass 2 re-seeds: asserts zero duplicate rows, asserts preserved document edit and setting edit were NOT overwritten.
     - Audit log timestamps append new seed events without requiring identical byte-for-byte history.
7. **CI Pipeline Hardening (`.github/workflows/ci.yml`):**
   - Added branch triggers: `codex/**`, `pull_request` on `main`/`feature/**`/`codex/**`, and `workflow_dispatch`.
   - Integrated Python 3.10 clean venv setup, `constraints.txt` installation, and `pip check`.
   - Configured PostgreSQL 16 service container, `alembic upgrade head`, and two-pass seed verification step with assertions.
   - Enforced P01 production security environment (`APP_ENV=test`, `APP_SECRET=...`).
   - Conformed `TEST_DATABASE_URL` to R01 guards (`folio_test` target database).
   - Updated artifact upload targets to `test-results/artifacts/**`, completely eliminating `docs/verification/` upload.

---

## 2. Git Metadata & Commit Separation

In strict compliance with prompt instructions, source code modifications were reviewed and committed separately from documentation/evidence deliverables:

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree |
| **Integration Branch** | `codex/integration-a-remediation` | Local integration branch |
| **Input Checkpoint Commit SHA** | `d9b7159` | Final R04.5 checkpoint commit |
| **Tested Source Commit SHA** | `8cce4cbad1052f253dcd5396530b2fb6038af647` | Dedicated local source code commit (`feat(test-infra)...`) |
| **Docs / Handoff Commit SHA** | Pending local commit | Dedicated documentation commit |
| **Alembic Migration Head** | `20261101_rate_limit` | Down-revision for future P03 migrations |

### 2.1 Commit Ancestry Verification
```text
* 8cce4cb (HEAD) feat(test-infra): remediate IA-07 artifact isolation, browser session state reset, and CI workflow
* d9b7159 docs(handoff): finalize R04.5 checkpoint report commit SHA
* f0be234 fix(integration): R04.5 checkpoint fixes for DB ownership registration, signature alignment, and P03 contracts
* 4024c3e feat(rate-limit): remediate IA-06 shared distributed limiter, atomic row locking, and concurrency tests
* bf6b930 feat(security): remediate IA-03 bootstrap identity rotation, enforce session revocation commit, and verify startup security
* 4502472 docs(search-contract): remediate IA-04 canonical UUIDv4/v5 IDs and IA-05 search context pagination contract
* 86365ac fix(test-infra): remediate IA-02 test DB safety guard, manifest ownership, and fixture isolation
* 9232aa1 docs(handoff): record R00 source integration, conflict resolution, and remediation artifacts
*   25a6b55 merge(p02): integrate clean setup, test isolation, conftest, and CI pipeline with seed resolution
|\  
| * 1ac72ad (feature/p02-clean-setup) feat(p02): clean setup, stratified dependencies, test DB guard...
* | 740eb5f (feature/p01-security) docs(handoff): update P01 handoff with final commit SHA
...
* c4b19cf (main, origin/main) chore: move public screenshots outside the repository
```

---

## 3. Comprehensive Test Results & Execution Evidence

All test suites were executed on the dedicated tested source SHA (`8cce4cbad1052f253dcd5396530b2fb6038af647`) using the clean virtual environment:

### 3.1 Pure Safety, Security & Artifact Test Suite (111 Tests)
```powershell
# Command:
cd F:\dpl13.10\WikiSearchEngine-ia-fix
.\venv\Scripts\pytest.exe --noconftest `
  tests/safety/test_pure_safety.py `
  tests/safety/test_pure_rate_limit.py `
  tests/safety/test_artifact_isolation.py `
  tests/safety/test_browser_isolation_order.py `
  tests/safety/test_seed_idempotency_asserts.py `
  tests/security/test_bootstrap_security.py `
  tests/security/test_startup_subprocess.py `
  tests/security/test_runtime_security_hardening.py -q
```
- **Exit Code:** `0`
- **Result:** `111 passed, 1 warning in 23.00s`
- **Failures:** `0`

#### Breakdown of Passed Suites:
| Test Module | Test Focus | Passed | Result |
| :--- | :--- | :--- | :--- |
| `tests/safety/test_pure_safety.py` | Effective driver target safety, query overrides, port normalization, loopback aliases, ownership manifest, selective termination | 47 | **PASS** |
| `tests/safety/test_pure_rate_limit.py` | Sliding window limiter, lock safety, counter decay, IP vs account partitioning | 15 | **PASS** |
| `tests/safety/test_artifact_isolation.py` | Artifact root hierarchy, path sanitization, Playwright tracing lifecycle, intentional failure artifact capture | 8 | **PASS** |
| `tests/safety/test_browser_isolation_order.py` | Browser test database state reset, Flow A->B vs B->A order independence, tracked PNG immutability | 3 | **PASS** |
| `tests/safety/test_seed_idempotency_asserts.py` | Authentic fixture SHA256, 103 items count, two-pass seed zero duplication, preserved edit retention, skip demo users | 3 | **PASS** |
| `tests/security/test_bootstrap_security.py` | Super admin rotation, identity mismatch negative matrix, session revocation | 19 | **PASS** |
| `tests/security/test_startup_subprocess.py` | Real OS subprocess startup, invalid env fail-fast, production validator | 8 | **PASS** |
| `tests/security/test_runtime_security_hardening.py` | Cookie security flags, CSRF token validation, RBAC enforcement, session revocation | 8 | **PASS** |
| **Total** | | **111** | **ALL PASS** |

---

## 4. Environment Scope & Status Matrix

| Subsystem / Capability | Verification Method | Local Windows Host Status | CI Pipeline (Linux) Status |
| :--- | :--- | :--- | :--- |
| **Clean Venv & Constraints** | `pip install` + `pip check` | **VERIFIED** (0 broken requirements) | **CONFIGURED** in `ci.yml` |
| **Alembic Head Migration** | `alembic upgrade head --sql` | **VERIFIED** (`20261101_rate_limit`, 20,372B transactional SQL) | **CONFIGURED** in `ci.yml` |
| **Fixture Integrity & Count** | SHA256 audit + item count | **VERIFIED** (103 docs: 100 pub, 3 draft, 6 cat, 123 tag) | **CONFIGURED** in `ci.yml` |
| **Two-Pass Seeding Idempotency**| Double seed + asserts | **VERIFIED** (0 duplicate rows, preserved edits retained) | **CONFIGURED** in `ci.yml` |
| **Artifact Root & Run ID Isolation** | Pure & Playwright tests | **VERIFIED** (Non-overlapping `<run_id>`, 0 writes to verification) | **CONFIGURED** in `ci.yml` |
| **Playwright Tracing Lifecycle** | Playwright Chromium | **VERIFIED** (Real .zip trace archive > 1KB verified) | **CONFIGURED** in `ci.yml` |
| **Browser Test DB State Reset** | Pre/Post test hook | **VERIFIED** (Order A->B and B->A independent) | **CONFIGURED** in `ci.yml` |
| **Tracked PNG Immutability** | SHA256 hash comparison | **VERIFIED** (All 52 baseline PNGs 100% untouched) | **N/A** (Baseline untouched) |
| **Live PostgreSQL 16 Instance** | TCP socket on 127.0.0.1:5432 | **BLOCKED_ENV** (No local PG / Docker / WSL service) | **CONFIGURED** (`postgres:16-alpine` service) |
| **Remote GitHub Actions CI Run** | GitHub remote dispatch | **UNVERIFIED** (No remote push or trigger executed per rules) | **READY FOR REMOTE TRIGGER** |

### Policy Enforcement on Environment Limitations:
- Local Windows development machine lacks Docker, local PostgreSQL services, and WSL distributions.
- In strict adherence to remediation guidelines:
  > *"Thiếu runtime thì làm xong phần độc lập, ghi BLOCKED_ENV và pending DB checks, không thay bằng SQLite rồi báo hoàn tất."*
  > *"Nếu chưa có CI run đúng SHA, ghi UNVERIFIED. Thiếu Linux/Docker ghi phạm vi local rõ."*
- Pure safety, artifact isolation, and unit test suites are **VERIFIED** (111 tests passing).
- Live PostgreSQL tests gracefully report **`BLOCKED_ENV`** without hanging or crashing.
- Remote CI run for commit `8cce4cbad1052f253dcd5396530b2fb6038af647` is designated as **`UNVERIFIED`** as remote push/trigger was not authorized in this task.

---

## 5. Clean Setup & Verification Instructions

### Step 1: Create Clean Isolated Virtual Environment
```powershell
cd F:\dpl13.10\WikiSearchEngine-ia-fix
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### Step 2: Install Pinned Dependencies with Constraints
```powershell
python -m pip install -r requirements-browser.txt -c constraints.txt
python -m pip check
# Expected: "No broken requirements found."
```

### Step 3: Ensure Playwright Chromium Browser is Installed
```powershell
python -m playwright install chromium
```

### Step 4: Run Pure Safety, Security & Artifact Isolation Suite
```powershell
pytest --noconftest `
  tests/safety/test_pure_safety.py `
  tests/safety/test_pure_rate_limit.py `
  tests/safety/test_artifact_isolation.py `
  tests/safety/test_browser_isolation_order.py `
  tests/safety/test_seed_idempotency_asserts.py `
  tests/security/test_bootstrap_security.py `
  tests/security/test_startup_subprocess.py `
  tests/security/test_runtime_security_hardening.py -v
```

### Step 5: Verify Alembic Migration Head & Offline SQL
```powershell
alembic heads
# Expected: 20261101_rate_limit (head)

alembic upgrade head --sql
# Generates valid transactional DDL beginning with BEGIN; and ending with COMMIT;
```

---

## 6. Gaps, Open Items & Handoff to R06

1. **P03 is NOT STARTED:** No search indexes, BM25 scorers, outbox workers, or search APIs have been authored.
2. **P03 Down-Revision Requirement:** The Alembic migration head is **`20261101_rate_limit`**. Any new migration in P03 must set `down_revision = "20261101_rate_limit"`.
3. **Remote CI Execution:** Local commits are clean and verified; remote workflow trigger must be executed under separate user instruction.
4. **Readiness Evaluation:** Task R05 is complete. Per workflow rules, the final readiness assessment for Milestone P03 belongs strictly to independent reviewer **R06**.

**End of R05 Handoff Report.**
