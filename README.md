# Folio — Knowledge & Research Library

Folio is an enterprise document and research repository built to fulfill the **Phase 1** requirements of the Information Retrieval course assignment while providing the data schema and standardized interaction logging pipeline required for **Phase 2** (inverted indexing, BM25 ranking, and retrieval evaluation).

---

## 1. Project Overview & Features

- **Domain:** Enterprise Document & Research Repository.
- **Client Interface:**
  - Responsive single-page application using native JavaScript ES modules and client-side hash routing.
  - Paper-and-ink visual aesthetic inspired by academic libraries: paper white (`#F6F4EE`), deep ink blue (`#20323D`), teal accents (`#16675B`), Source Serif 4 headings, and Source Sans 3 UI typography.
  - Single-column reading view with sanitized Markdown rendering, KaTeX math notation, cover images, and source citations.
  - Multi-faceted research filtering: ILIKE keyword search, academic categories, multi-tag filtering (`AND` logic), and date ranges.
  - Reader engagement: Argon2id authentication, session management, CSRF defense, liking, threaded comments with Markdown, `@mentions` autocomplete, and content report flagging.
- **Role-Based Access Control (RBAC):**
  - **Super Administrator:** Manage users, assign roles, configure dynamic role capability matrix in database, inspect immutable system audit trail with JSON state diffs, and configure global settings.
  - **Content Manager:** Full document authoring with Markdown editor and live preview, draft/publish workflow, and category/tag taxonomy management with foreign-key conflict protection.
  - **Moderator:** Review comments queue (visible, hidden, spam), resolve flagged reports, and apply temporary commenting suspensions with audit reasons.
  - **Data & SEO Specialist:** Configure document SEO metadata (meta titles, descriptions, keywords, alt text) with Google SERP simulator, and monitor library analytics dashboards with zero-filled daily series.
- **Phase 2 Search Engine Preparation:**
  - Complete Document Store (`id`, `title`, `content`, `summary`, `category_id`, `tags`, `author`, `created_at`, `views_count`).
  - Standardized interaction logging table (`interaction_logs`) recording discrete search events (capturing `query_string`, `search_event_id`, and `result_doc_ids`) and result click events (validating result membership and parent search event linkage).
  - Seed dataset containing **100 authentic published Wikipedia research articles** and **3 drafts** (no *Lorem Ipsum*).

---

## 2. Technology Stack

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy 2 (sync sessions), Alembic migrations, Pydantic v2.
- **Database:** PostgreSQL 16+ RDBMS with native UUIDs and JSONB columns.
- **Security:** Argon2id password hashing (`argon2-cffi`), HttpOnly session cookies, CSRF token validation, Bleach HTML/Markdown sanitization.
- **Frontend:** Vanilla HTML5, CSS3, native ES modules, client-side hash router (`#/library`, `#/documents/:id`, `#/admin/*`). Zero compile/bundling overhead.
- **Target Viewports:** Certified for laptop and desktop screens: `1280x720`, `1366x768`, `1440x900`, `1920x1080` (and laptop zoom 125%). Mobile optimizations are explicitly out of scope for this release.

---

## 3. Quickstart & Clean Setup (PowerShell on Windows)

### Prerequisites
- Python 3.10 or higher.
- PostgreSQL 16+ running locally on port `5432` with databases `folio` and `folio_test`.
- Git.

### Step 1: Clone & Navigate to Repository
```powershell
git clone https://github.com/MarcusCyborg/folio.git
cd folio
```

### Step 2: Clean Virtual Environment & Stratified Dependencies
Folio uses strictly isolated virtual environments (`include-system-site-packages = false`) and stratified dependencies pinned and constrained against verified package versions (`constraints.txt`).

```powershell
# Create clean isolated virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Upgrade pip and install core runtime & test dependencies with constraints
python -m pip install --upgrade pip
pip install -c constraints.txt -r requirements.txt -r requirements-dev.txt

# (Optional) Install Playwright browser testing dependencies
pip install -c constraints.txt -r requirements-browser.txt
python -m playwright install chromium

# (Optional) Decoupled legacy ML / crawl dependencies
# pip install -r requirements-legacy.txt
```

**Dependency Stratification:**
- `requirements.txt`: Minimal core production runtime (FastAPI, Uvicorn, SQLAlchemy, Psycopg 3, Alembic, Argon2-cffi, Pydantic, Bleach, Markdown, python-dotenv).
- `requirements-dev.txt`: Test harness and backend assertion libraries (Pytest, HTTPX).
- `requirements-browser.txt`: Browser automation & E2E suite (Playwright).
- `requirements-legacy.txt`: Decoupled legacy embeddings/ML dependencies (ChromaDB, Sentence-Transformers, PyTorch).
- `constraints.txt`: Exact tested and verified package versions across environments.

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Ensure your PostgreSQL connection string in `.env` matches your local setup:
```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/folio
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/folio_test
ENABLE_LEGACY_SEARCH=false
```

### Step 4: Apply Database Migrations & Seed Research Data
Run Alembic to create or upgrade the database schema:
```powershell
alembic upgrade head
```

Populate the database with the curated research fixture (fully idempotent):
```powershell
python scripts/seed_folio.py
```
*Output confirms: `Seed complete. Database now contains: 5 users, 162 published documents, 3 drafts, 6 categories, 154 tags.`*
Running `python scripts/seed_folio.py` multiple times is safe and produces identical state without duplicates.

### Step 5: Launch Development Server
```powershell
uvicorn src.backend.main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser and navigate to: **`http://127.0.0.1:8000`**

### Dedicated Clean Demo Server (Remediated Baseline on Port 8002)
To run a clean presentation instance on the dedicated `folio_demo` database:
```powershell
# 1. Create database in PostgreSQL:
# createdb -U postgres folio_demo

# 2. Run migrations and seed clean dataset:
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/folio_demo"
alembic upgrade head
python scripts/seed_folio.py

# 3. Launch demo server:
uvicorn src.backend.main:app --host 127.0.0.1 --port 8002
```
Navigate to: **`http://127.0.0.1:8002`**

---

## 4. Automated Testing & Verification

### Test Database Isolation & Guard
Tests do NOT touch or depend on manual seeds from your development database.
- `tests/conftest.py` strictly validates `TEST_DATABASE_URL`:
  - Enforces that the target database name contains `test`.
  - Blocks connection if `TEST_DATABASE_URL` matches the production/development `DATABASE_URL`.
  - Refuses to run against default root/system databases (`postgres`, `template0`, `template1`).
- The test harness automatically creates `folio_test` if missing, cleans active connection locks, runs `alembic upgrade head`, seeds test fixtures idempotently, and wraps each test in a savepoint rollback (`create_savepoint`) for zero test-ordering dependencies.
- Frontend browser fixtures use readiness polling against `/health` (replacing fixed sleeps) and Playwright's bundled Chromium with optional system browser channel fallbacks.

### Running Backend Suite (58 Tests)
```powershell
pytest tests/backend -v --junitxml=test-results/junit-backend.xml
```
All **58 automated backend tests** run against the dedicated test database (`folio_test`) and complete in ~16s.

### Running Frontend Browser Suite (15 Tests)
```powershell
pytest tests/frontend -v --junitxml=test-results/junit-frontend.xml
```
All **15 automated Playwright browser tests** (covering Admin RBAC flows, Super Admin CRUD, Taxonomy, Moderation, SEO SERP simulator, and Public flows) complete in ~40s.

### Configurable Public Screenshot Capture
The screenshot capture script (`scripts/capture_screenshots.py`) supports configurable output paths and server targets to prevent cross-worktree file clobbering:
```powershell
# Default outputs to local repo 'screenshots/' with readiness check against http://127.0.0.1:8002
python scripts/capture_screenshots.py

# Or specify custom target and output directory:
python scripts/capture_screenshots.py --output-dir screenshots/ --base-url http://127.0.0.1:8000
```
Environment variable overrides are also supported: `FOLIO_BASE_URL` and `FOLIO_SCREENSHOT_DIR`.

---

## 5. Demo Accounts

All demo accounts are pre-seeded with the uniform password: `FolioDemo2026!`

| Role | Email | Username | Key Capabilities |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `admin@folio.test` | `admin` | Users, dynamic role permission matrix, audit diffs, settings |
| **Content Manager** | `content@folio.test` | `content_mgr` | Document CRUD, Markdown editor with live preview, taxonomy |
| **Moderator** | `moderator@folio.test` | `moderator` | Comments queue, resolve reports, user commenting suspension |
| **Data & SEO Specialist** | `seo@folio.test` | `seo_specialist` | SEO metadata, Google SERP simulator, analytics overview |
| **Reader / Member** | `reader@folio.test` | `reader` | Public reading, liking, commenting with `@mentions`, reporting |

---

## 6. Project Structure

```text
folio/
├── .github/
│   └── workflows/
│       └── ci.yml                   # GitHub Actions CI workflow (Postgres, venv, pytest, Playwright)
├── alembic/                         # Database schema migrations
│   └── versions/
│       └── efeaa3d84c9b_initial_folio_schema.py
├── docs/                            # Project documentation & deliverables
│   ├── architecture.md              # System architecture, ERD, RBAC, logging
│   ├── assignment-checklist.md      # Item-by-item verification against assignment
│   ├── demo-script.md               # 8–10 minute step-by-step evaluator guide
│   ├── handoff/                     # Wave handoffs, contracts, and lane statuses
│   └── verification/
│       └── TEST-REPORT.md           # QA test report & desktop viewport evidence
├── fixtures/
│   └── folio/
│       ├── documents.jsonl          # Authentic research articles + drafts
│       └── SOURCES.md               # Wikipedia citations & licensing notes
├── scripts/
│   ├── capture_screenshots.py       # Configurable public screenshot capture script
│   └── seed_folio.py                # Idempotent database seed script
├── src/
│   ├── backend/
│   │   ├── api/                     # FastAPI route controllers
│   │   │   ├── auth.py              # Login, register, session, profile
│   │   │   ├── library.py           # Catalog, documents, taxonomy
│   │   │   ├── engagement.py        # Likes, comments, mentions, reports
│   │   │   ├── events.py            # Search click interaction logging
│   │   │   └── admin/               # RBAC-guarded admin endpoints
│   │   ├── core/                    # Config, database, security, audit, Bleach
│   │   ├── models/                  # SQLAlchemy 2 declarative models
│   │   ├── schemas/                 # Pydantic v2 validation schemas
│   │   └── services/                # Business logic services
│   └── frontend/
│       ├── index.html               # Single-page application entry point
│       ├── app.js                   # Client shell & component bootstrap
│       ├── style.css                # Folio Paper-and-Ink design system
│       ├── core/                    # API client, session/RBAC, router, UI helpers
│       ├── public/                  # Library catalog, reading column, auth views
│       └── admin/                   # Control panel, editor, moderation, analytics
├── tests/
│   ├── conftest.py                  # Pytest fixtures, DB guard, live_server, Playwright
│   ├── backend/                     # Pytest automated backend test suites (58 tests)
│   │   ├── foundation/              # Auth, CSRF, sessions, startup, permissions
│   │   ├── library/                 # Search, detail, likes, comments, anti-spam
│   │   ├── admin/                   # Documents CRUD, taxonomy, RBAC, moderation, SEO, analytics
│   │   └── integration/             # Full multi-persona lifecycle test
│   └── frontend/                    # Playwright browser E2E & visual test suites (15 tests)
│       ├── admin/                   # Admin UI flows & multi-viewport screenshots
│       └── public/                  # Library catalog, reading column, mentions, auth
├── constraints.txt                  # Pinned verified package versions
├── requirements.txt                 # Core runtime dependencies
├── requirements-dev.txt             # Testing and development dependencies
├── requirements-browser.txt         # Playwright and browser test dependencies
└── requirements-legacy.txt          # Optional decoupled ML/embedding dependencies
```

---

## 7. Continuous Integration (CI)

Folio includes an automated GitHub Actions workflow (`.github/workflows/ci.yml`) triggered on every push and pull request to `main` and feature branches.

The pipeline executes:
1. **Service Container:** Spins up PostgreSQL 16 on port 5432 with health check.
2. **Clean Installation:** Sets up Python 3.10 virtual environment and installs dependencies using `constraints.txt`.
3. **Migration Verification:** Applies Alembic migrations (`alembic upgrade head`) from scratch.
4. **Seed Idempotency Check:** Runs `python scripts/seed_folio.py` consecutively twice to verify strict zero-duplicate idempotency.
5. **Backend Test Suite:** Executes all 58 backend tests, producing JUnit XML report.
6. **Frontend Test Suite:** Installs Playwright Chromium browser binary and runs all 15 browser E2E tests, capturing failure traces/screenshots and uploading test artifacts.

---

## 8. Troubleshooting

- **PostgreSQL Connection Error:** Ensure PostgreSQL is active on port 5432 and the `folio` database exists (`createdb -U postgres folio`).
- **CSRF Token Rejected (403 Forbidden):** The frontend handles CSRF tokens automatically via `GET /api/v1/auth/session` and sends `X-CSRF-Token` headers. If testing via curl/Postman, fetch `/api/v1/auth/session` first to obtain a valid session cookie and CSRF token.
- **Permission Denied (403 Forbidden) on Admin Routes:** Verify that the signed-in account holds the necessary capability permission. Refer to the demo accounts table above.
- **Last Super Admin Demotion (409 Conflict):** Folio strictly prevents removing or demoting the final active super administrator to avoid system lockout.

---

## 9. Optional Legacy ML Search Note

The repository preserves legacy search and crawling code developed during earlier milestones (located in `search_service.py`, `wiki_bot/`, and `utils/`). This legacy subsystem is **completely decoupled** and guarded by the `ENABLE_LEGACY_SEARCH` environment variable (defaults to `false`).

When disabled, Folio starts instantly without any requirement for heavy vector embedding models, GPU acceleration, or local ChromaDB databases. Enabling `ENABLE_LEGACY_SEARCH=true` requires installing optional dependencies listed in `requirements-legacy.txt`.
