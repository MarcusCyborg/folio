# Folio Milestone M2 / P02 Clean Setup, Test Isolation & CI Handoff

**Handoff ID:** `P02-clean-setup-ci`  
**Date:** 2026-10-31  
**Author:** Build & Release Engineer  
**Workspace:** `F:/dpl13.10/WikiSearchEngine-p02` (Dedicated Git worktree branched from `main` of `WikiSearchEngine-github`)  
**Branch:** `feature/p02-clean-setup`  
**Base Commit:** `c4b19cffa676b4437e7346da2c410b198b04dc2c` (Synchronized with `origin/main`)  
**Historical Checkout:** `F:/dpl13.10/WikiSearchEngine` (Untouched, verified clean)  

---

## 1. Executive Summary

Milestone M2 (Prompt P02) establishes a fully reproducible, clean-slate environment and testing harness for Folio:
1. **Isolated Stratified Dependencies:** Zero pollution from global system Python; pinned and constrained requirements separated into core runtime, development/test, browser automation, and decoupled legacy ML.
2. **Automated Test Database Lifecycle:** Automatic provisioning, connection lock clearing, programmatic migration (`alembic upgrade head`), and idempotent seeding of `folio_test`.
3. **Strict Target Database Guard:** Enforces that `TEST_DATABASE_URL` targets an explicit test database containing `test`, rejects production `DATABASE_URL` collisions, and blocks accidental execution against Postgres system catalogs (`postgres`, `template0`, `template1`).
4. **Zero-Order Test Isolation:** Every test executes inside a nested database savepoint (`create_savepoint`), rolling back all mutations upon teardown. Tests do not rely on previous test side-effects or manual pre-seeding.
5. **Robust Frontend Test Fixtures:** Replaced arbitrary `time.sleep` with socket readiness polling (`/health`), bundled Playwright Chromium browser launch, automatic failure screenshot and trace captures, and configurable screenshot generation.
6. **Continuous Integration (CI):** Fully automated GitHub Actions workflow (`.github/workflows/ci.yml`) with PostgreSQL 16 service container, 2x seed idempotency verification, backend suite, and frontend Playwright suite with artifact uploads.

---

## 2. Command Executions & Verification Results

All verification commands were executed directly in the clean worktree `F:/dpl13.10/WikiSearchEngine-p02` using the newly created virtual environment `venv`.

### 2.1 Clean Virtual Environment & Dependency Installation
```powershell
cd "F:/dpl13.10/WikiSearchEngine-p02"

# 1. Create clean virtual environment without system packages
python -m venv venv

# Verify pyvenv.cfg
Get-Content venv/pyvenv.cfg
# Output:
# home = C:\Users\Admin\AppData\Local\Programs\Python\Python310
# include-system-site-packages = false
# version = 3.10.11

# 2. Upgrade pip and install with constraints
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -c constraints.txt -r requirements.txt -r requirements-dev.txt -r requirements-browser.txt

# 3. Install Playwright browser binaries
.\venv\Scripts\python.exe -m playwright install chromium
```
**Result:** Clean installation succeeded with 0 conflicts. Exact versions recorded in `constraints.txt`.

---

### 2.2 Database Migrations & 2x Seed Idempotency Check
```powershell
# 1. Run migrations against test database
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/folio_test"
.\venv\Scripts\alembic.exe upgrade head

# 2. First seed run
.\venv\Scripts\python.exe scripts/seed_folio.py --db-url "postgresql+psycopg://postgres:postgres@localhost:5432/folio_test"
# Output:
# Seeding default roles and permissions...
# Seeding global application settings...
# Seeding demo users...
# Seeding taxonomy and research documents from fixtures...
# Documents fixture processed. Total items in fixture: 165
# Seed complete. Database now contains: 5 users, 162 published documents, 3 drafts, 6 categories, 154 tags.

# 3. Second seed run (Idempotency verification)
.\venv\Scripts\python.exe scripts/seed_folio.py --db-url "postgresql+psycopg://postgres:postgres@localhost:5432/folio_test"
# Output:
# Seeding default roles and permissions...
# Seeding global application settings...
# Seeding demo users...
# Seeding taxonomy and research documents from fixtures...
# Documents fixture processed. Total items in fixture: 165
# Seed complete. Database now contains: 5 users, 162 published documents, 3 drafts, 6 categories, 154 tags.
```
**Result:** **100% IDEMPOTENT**. Counts before and after the second run were identical:
- Users: 5
- Published Documents: 162
- Drafts: 3
- Categories: 6
- Tags: 154

---

### 2.3 Full Backend Test Suite (58 Tests)
```powershell
.\venv\Scripts\pytest.exe tests/backend -v --tb=short --junitxml=test-results/junit-backend.xml
```
**Execution Summary:**
- Collected: 58 items
- Passed: 58 (100%)
- Failed: 0
- Execution Time: 15.75s
- XML Report: `F:\dpl13.10\WikiSearchEngine-p02\test-results\junit-backend.xml`

**Test Breakdown:**
- Foundation Suite (`test_auth.py`, `test_frontend_assets.py`, `test_permissions.py`, `test_startup.py`): 12 passed
- Library API Suite (`test_library_api.py`, `test_click_idempotency.py`): 18 passed
- Admin Suite (`test_admin_api.py`, `test_analytics_metrics.py`, `test_document_lifecycle.py`, `test_governance_and_last_admin.py`, `test_moderation_flow.py`, `test_permissions_and_security.py`, `test_preview.py`, `test_seo_and_audit.py`, `test_taxonomy_lifecycle.py`): 27 passed
- End-to-End Workflow (`test_e2e_workflow.py`): 1 passed

---

### 2.4 Full Frontend Browser Suite (15 Tests)
```powershell
.\venv\Scripts\pytest.exe tests/frontend -v --tb=short --junitxml=test-results/junit-frontend.xml
```
**Execution Summary:**
- Collected: 15 items
- Passed: 15 (100%)
- Failed: 0
- Execution Time: 40.19s
- XML Report: `F:\dpl13.10\WikiSearchEngine-p02\test-results\junit-frontend.xml`

**Test Breakdown:**
- Admin Flows (`test_admin_flows.py`): 10 passed
  - `test_admin_entry_and_rbac_guards`
  - `test_content_manager_permissions`
  - `test_data_seo_specialist_permissions`
  - `test_super_admin_full_documents_crud_and_dirty_guard`
  - `test_taxonomy_manager_and_409_conflict_handling`
  - `test_moderation_queue_actions_and_suspension`
  - `test_seo_management_and_preview_simulation`
  - `test_analytics_dashboard_metrics`
  - `test_users_governance_and_last_super_admin_protection`
  - `test_roles_matrix_and_settings`
- Admin Visual Multi-Viewport Screenshots (`test_admin_screenshots.py`): 1 passed
  - `test_capture_admin_screens_and_viewports`
- Public Flows (`test_public_flows.py`): 4 passed
  - `test_library_catalog_and_viewports`
  - `test_library_filtering_search_and_pagination`
  - `test_auth_validation_and_profile_management`
  - `test_document_detail_reading_like_and_discussions`

---

### 2.5 Configurable Public Screenshot Capture
```powershell
.\venv\Scripts\python.exe scripts/capture_screenshots.py --output-dir screenshots/ --base-url http://127.0.0.1:8003
```
**Execution Output:**
```text
Starting screenshot capture targeting http://127.0.0.1:8003 -> F:\dpl13.10\WikiSearchEngine-p02\screenshots...
Checking server readiness at http://127.0.0.1:8003/health...
Server at http://127.0.0.1:8003 is ready!
Capturing 01_library_homepage.png (1366x768)...
Capturing 02_library_desktop.png (1920x1080)...
Capturing 03_library_search_results.png...
Capturing 04_library_category_filter.png...
Capturing 05_document_detail.png...
Capturing 06_document_detail_scrolled.png...
Capturing 07_login_page.png...
Capturing 08_register_page.png...
All 8 public page screenshots captured successfully in F:\dpl13.10\WikiSearchEngine-p02\screenshots!
```
**Result:** Verified that all 8 public screenshots were written directly to `F:\dpl13.10\WikiSearchEngine-p02\screenshots` without touching or clobbering `../screenshots`.

---

## 3. Files Created, Modified & Owned

### 3.1 P02 Owned Files
| Path | Action | Description |
| :--- | :--- | :--- |
| [`requirements.txt`](file:///F:/dpl13.10/WikiSearchEngine-p02/requirements.txt) | Modified | Core runtime dependencies pinned to verified versions |
| [`requirements-dev.txt`](file:///F:/dpl13.10/WikiSearchEngine-p02/requirements-dev.txt) | Modified | Backend dev & test dependencies (`pytest`, `httpx`) |
| [`requirements-browser.txt`](file:///F:/dpl13.10/WikiSearchEngine-p02/requirements-browser.txt) | Created | Browser test dependencies (`playwright`) |
| [`requirements-legacy.txt`](file:///F:/dpl13.10/WikiSearchEngine-p02/requirements-legacy.txt) | Modified | Decoupled ML/NLP/vector dependencies |
| [`constraints.txt`](file:///F:/dpl13.10/WikiSearchEngine-p02/constraints.txt) | Created | Pinned constraints matching exact verified environment |
| [`tests/conftest.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/tests/conftest.py) | Modified | Strict DB guard, auto-creation, programmatic migration, savepoint isolation, live server readiness polling, Playwright launcher, failure artifacts hook |
| [`scripts/seed_folio.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/scripts/seed_folio.py) | Modified | Idempotent programmatic `run_seed(target=...)`, CLI args `--db-url`, `--test` |
| [`scripts/capture_screenshots.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/scripts/capture_screenshots.py) | Modified | Added `--output-dir`, `--base-url`, environment variable overrides, readiness polling against `/health` |
| [`.github/workflows/ci.yml`](file:///F:/dpl13.10/WikiSearchEngine-p02/.github/workflows/ci.yml) | Created | GitHub Actions pipeline for PostgreSQL, clean install, migration, seed idempotency, backend & frontend suites |
| [`README.md`](file:///F:/dpl13.10/WikiSearchEngine-p02/README.md) | Modified | Clean setup docs, dependency stratification, test guard explanations, CI section |
| [`.gitignore`](file:///F:/dpl13.10/WikiSearchEngine-p02/.gitignore) | Modified | Added `screenshots/` and `test-results/` to prevent untracked test artifacts |
| [`tests/frontend/admin/test_admin_flows.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/tests/frontend/admin/test_admin_flows.py) | Modified | Fixed selector alignment (`Configure SEO`), markdown preview wait, tag pagination prefix (`00-`) |
| [`tests/frontend/admin/test_admin_screenshots.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/tests/frontend/admin/test_admin_screenshots.py) | Modified | Handled unsaved changes dirty guard modal when navigating away from editor |
| [`tests/frontend/public/test_public_flows.py`](file:///F:/dpl13.10/WikiSearchEngine-p02/tests/frontend/public/test_public_flows.py) | Modified | Added networkidle and active filter chip waits to prevent search result click races |

### 3.2 Untracked P00 Baseline Artifacts Preserved
- `FOLIO-COMPLETION-PLAN.md`
- `GEMINI-EXECUTION-PROMPTS.md`
- `docs/acceptance-matrix.md`
- `docs/search-contract.md`
- `docs/handoff/gemini/CLONE-REPORT.md`
- `docs/handoff/gemini/P00-baseline.md`

---

## 4. Architecture & Security Invariants

### 4.1 Strict Test Database Guard
`tests/conftest.py` applies three strict layers of protection before any connection is allowed:
```python
def validate_test_database_target(test_url: str):
    parsed = make_url(test_url)
    db_name = (parsed.database or "").lower()

    # 1. Target database must contain 'test'
    if "test" not in db_name:
        raise RuntimeError(
            f"REFUSING TO RUN TESTS: Target database '{db_name}' in TEST_DATABASE_URL "
            f"does not contain 'test'. Guard prevented accidental mutation of non-test database."
        )

    # 2. Refuse system catalogs
    if db_name in ("postgres", "template0", "template1"):
        raise RuntimeError(
            f"REFUSING TO RUN TESTS: Target database '{db_name}' is a PostgreSQL system database."
        )

    # 3. Collision guard against development/production DATABASE_URL
    dev_url = os.environ.get("DATABASE_URL")
    if dev_url:
        dev_parsed = make_url(dev_url)
        if (parsed.host == dev_parsed.host and 
            parsed.port == dev_parsed.port and 
            parsed.database == dev_parsed.database):
            raise RuntimeError(
                f"REFUSING TO RUN TESTS: TEST_DATABASE_URL points to the same database "
                f"as DATABASE_URL ('{parsed.database}'). Separation of test data is mandatory."
            )
```

### 4.2 Deadlock-Free Teardown & Isolation
- **Connection Purge:** `ensure_test_database_exists` executes `SELECT pg_terminate_backend(pid)` for all other active backends on `folio_test` before dropping or recreating schemas.
- **Engine Pooling:** `test_engine` uses `poolclass=pool.NullPool` to eliminate connection caching and prevent locks from surviving across fixtures.
- **Savepoint Isolation:** Each test function receives a SQLAlchemy session wrapped in `join_transaction_mode="create_savepoint"`. All test modifications (document creates, user demotions, comment submissions) are rolled back to the savepoint at fixture teardown, guaranteeing zero test order dependencies.

### 4.3 Centralized Server & Browser Lifecycle
- **Dynamic Port Selection:** `live_server` binds to port `0` to allocate a random free socket, avoiding port collision across runs.
- **Readiness Polling:** Replaced all hardcoded `sleep` calls with `urllib.request` readiness polling against `/health` at 50ms intervals (timeout 15s).
- **Failure Artifacts:** Pytest hook `pytest_runtest_makereport` inspects test outcomes; any failure in browser tests automatically captures a viewport screenshot to `test-results/screenshots/{test_name}.png`.

---

## 5. Real Environment Blockers & Open Risks

1. **Local PostgreSQL Service Requirement:**
   - Tests require an accessible PostgreSQL server (default: `127.0.0.1:5432`, user `postgres`).
   - If PostgreSQL is down or password differs from `.env`, tests cannot execute. In CI, this is handled seamlessly via the `postgres:16-alpine` service container.
2. **Third-Party Deprecation Warnings:**
   - `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
   - `Alembic DeprecationWarning: The version_path_separator configuration parameter is deprecated.`
   - `StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated.`
   - *Status:* Harmless warnings from upstream library updates; all functionality is fully operational.
3. **Dirty Guard Navigation in SPA:**
   - The vanilla JS SPA contains an unsaved changes leave guard when form inputs are modified (`#/admin/documents/new`). Navigations from dirty forms must dismiss the modal or cleanly submit. Documented in test fixtures.

---

## 6. Handoff Contract for Downstream Milestones

### 6.1 Integration A (Merge P01 + P02)
- **Branch:** `feature/p02-clean-setup` is ready for review and integration with `feature/p01-security`.
- **Ownership Notice:**
  - P02 modified `requirements.txt`, `requirements-dev.txt`, `tests/conftest.py`, `scripts/seed_folio.py`, `scripts/capture_screenshots.py`, `README.md`, `.gitignore`, and added `.github/workflows/ci.yml`.
  - P01 owns `src/backend/core/config.py`, auth middleware, production validation, and security tests.
  - When merging into Integration A, verify that `TEST_DATABASE_URL` uses `postgresql+psycopg://` driver syntax and run both `pytest tests/backend` and `pytest tests/frontend`.

### 6.2 Contract for P03 (Document Import & Index Lifecycle Worker)
- **Virtualenv:** Use `.\venv\Scripts\Activate.ps1`. Install any new dependencies through `constraints.txt` and `requirements.txt`.
- **Test Database:** Target `folio_test`. Do not disable the test guard in `tests/conftest.py`.
- **Migrations:** Add new migrations in `alembic/versions/` with distinct down-revisions.
- **Test Execution:** Tests should use the `db_session` fixture with nested savepoints to maintain zero state pollution.
