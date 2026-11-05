# Folio Milestone M0 / P00 Baseline Audit & Architecture Handoff

**Handoff ID:** `P00-baseline`  
**Date:** 2026-10-31  
**Author:** Lead Architect & QA Lead  
**Target Repository:** `F:/dpl13.10/WikiSearchEngine-github`  
**Git HEAD:** `c4b19cffa676b4437e7346da2c410b198b04dc2c`  
**Branch:** `main` (synchronized with `origin/main`)  
**Upstream Remote:** `https://github.com/MarcusCyborg/folio.git`

---

## 1. Audit Commands, Environments & Results

All verification commands were executed within the verified clone `F:/dpl13.10/WikiSearchEngine-github`.

### 1.1 Git Baseline & History Reorganization
```powershell
cd "F:/dpl13.10/WikiSearchEngine-github"
git rev-parse HEAD
# Output: c4b19cffa676b4437e7346da2c410b198b04dc2c

git branch --show-current
# Output: main

git remote -v
# Output:
# origin  https://github.com/MarcusCyborg/folio.git (fetch)
# origin  https://github.com/MarcusCyborg/folio.git (push)

git status --short
# Output on tracked files: Clean (0 modified tracked files)
```

**Git History Rewrite Analysis (Cross-reference with [CLONE-REPORT.md](file:///F:/dpl13.10/WikiSearchEngine-github/docs/handoff/gemini/CLONE-REPORT.md)):**
- Remote `main` at commit `c4b19cf` was force-updated relative to the historical checkout `ab0f5fe`.
- Tree-comparison confirms that content differences are strictly confined to:
  1. [`.gitignore`](file:///F:/dpl13.10/WikiSearchEngine-github/.gitignore): Added `/docs/screenshots/`.
  2. [`README.md`](file:///F:/dpl13.10/WikiSearchEngine-github/README.md): Adjusted screenshot documentation path to parent `screenshots/`.
  3. [`scripts/capture_screenshots.py`](file:///F:/dpl13.10/WikiSearchEngine-github/scripts/capture_screenshots.py): Resolves output path to parent directory (`../screenshots/`).
  4. Removed 8 tracked public screenshot PNG files from Git.
- **Zero code changes** exist in [`src/`](file:///F:/dpl13.10/WikiSearchEngine-github/src), [`tests/`](file:///F:/dpl13.10/WikiSearchEngine-github/tests), [`alembic/`](file:///F:/dpl13.10/WikiSearchEngine-github/alembic), or requirements files. The rewrite does **not** signify that Phase 2 features have been implemented.

---

### 1.2 Database Migrations Audit
```powershell
Get-ChildItem alembic/versions
```
**Found 2 Alembic revisions:**
1. [`alembic/versions/efeaa3d84c9b_initial_folio_schema.py`](file:///F:/dpl13.10/WikiSearchEngine-github/alembic/versions/efeaa3d84c9b_initial_folio_schema.py): Establishes complete Phase 1 schema (users, roles, permissions, sessions, documents, categories, tags, document_tags, comments, comment_mentions, document_likes, reports, interaction_logs, view_events, audit_logs, app_settings).
2. [`alembic/versions/20261031_click_idempotency_unique.py`](file:///F:/dpl13.10/WikiSearchEngine-github/alembic/versions/20261031_click_idempotency_unique.py): Adds unique constraint on `(actor_key, search_event_id, clicked_doc_id, request_key)` to guarantee click idempotency.

---

### 1.3 Python Environment, Dependencies & Test Isolation
```powershell
python --version
# Output: Python 3.10.11 (System Python: C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe)

Test-Path ".env", "env", "venv", "data"
# Output: False, False, False, False
```

**Environment Verification Findings:**
- The new clone does **not** possess a local `.env`, a dedicated virtual environment (`env/` or `venv/`), or a configured test database.
- System Python has global packages, but running tests against global Python or unisolated databases violates project rules ([GEMINI-EXECUTION-PROMPTS.md Rules 36 & 38](file:///F:/dpl13.10/WikiSearchEngine-github/GEMINI-EXECUTION-PROMPTS.md#L36-L38)).
- **Test Execution Status:** **NOT RUN (BLOCKED_ENV)**.
  - The historical 58 passed tests were executed in the previous checkout (`WikiSearchEngine`).
  - Because no isolated virtualenv and dedicated test database (`folio_test`) exist yet in this clone, tests were intentionally not run.
  - This is **NOT** an application failure. Environment creation and test automation are formally assigned to [P02](file:///F:/dpl13.10/WikiSearchEngine-github/GEMINI-EXECUTION-PROMPTS.md#L88-L107).

---

### 1.4 Dependencies & Runtime Entrypoints
1. **Dependency Stratification:**
   - [`requirements.txt`](file:///F:/dpl13.10/WikiSearchEngine-github/requirements.txt): Core Phase 1 runtime (FastAPI, SQLAlchemy, Psycopg 3, Alembic, Argon2-cffi, Bleach, Markdown).
   - [`requirements-dev.txt`](file:///F:/dpl13.10/WikiSearchEngine-github/requirements-dev.txt): Testing & tooling (pytest, httpx, playwright).
   - [`requirements-legacy.txt`](file:///F:/dpl13.10/WikiSearchEngine-github/requirements-legacy.txt): Optional ML and crawling stack (Scrapy, ChromaDB, Sentence-Transformers, NLTK).
2. **Runtime Entrypoints:**
   - Main Web Application: [`src/backend/main.py`](file:///F:/dpl13.10/WikiSearchEngine-github/src/backend/main.py) mounting `/api/v1` routers, lightweight `/health`, lazy-loaded legacy `/search`, and static frontend at root `/`.
   - Seeding Script: [`scripts/seed_folio.py`](file:///F:/dpl13.10/WikiSearchEngine-github/scripts/seed_folio.py) populating exactly 100 published articles and 3 drafts from [`fixtures/folio/documents.jsonl`](file:///F:/dpl13.10/WikiSearchEngine-github/fixtures/folio/documents.jsonl).
   - Database Container: [`docker-compose.yml`](file:///F:/dpl13.10/WikiSearchEngine-github/docker-compose.yml) providing PostgreSQL 16 on port 5432.

---

## 2. Inventory of Untracked / Modified Files

The tracked repository tree remains 100% clean. The untracked files present in `F:/dpl13.10/WikiSearchEngine-github` are:

| File Path | Description / Purpose |
| :--- | :--- |
| [`FOLIO-COMPLETION-PLAN.md`](file:///F:/dpl13.10/WikiSearchEngine-github/FOLIO-COMPLETION-PLAN.md) | Master completion plan across all phases M0–M9 |
| [`GEMINI-EXECUTION-PROMPTS.md`](file:///F:/dpl13.10/WikiSearchEngine-github/GEMINI-EXECUTION-PROMPTS.md) | Execution prompt pack for phases P00–P09 |
| [`docs/handoff/gemini/CLONE-REPORT.md`](file:///F:/dpl13.10/WikiSearchEngine-github/docs/handoff/gemini/CLONE-REPORT.md) | Clone verification report and Git history analysis |
| [`docs/acceptance-matrix.md`](file:///F:/dpl13.10/WikiSearchEngine-github/docs/acceptance-matrix.md) | Acceptance verification matrix created in M0/P00 |
| [`docs/search-contract.md`](file:///F:/dpl13.10/WikiSearchEngine-github/docs/search-contract.md) | Canonical Folio IR & Search Contract created in M0/P00 |
| [`docs/handoff/gemini/P00-baseline.md`](file:///F:/dpl13.10/WikiSearchEngine-github/docs/handoff/gemini/P00-baseline.md) | This baseline audit and handoff document |

---

## 3. Blockers, Technical Debt & Key Decisions

1. **Blocker 1 (Test Environment Isolation):**
   - *Status:* Assigned to P02.
   - *Impact:* Automated test suites cannot be executed in this clone without an isolated virtualenv and dedicated `folio_test` DB.
2. **Blocker 2 (Production Security Validation):**
   - *Status:* Assigned to P01.
   - *Impact:* `validate_production()` exists in [`src/backend/core/config.py`](file:///F:/dpl13.10/WikiSearchEngine-github/src/backend/core/config.py#L22) but is not invoked during application startup/lifespan.
3. **Blocker 3 (Shared Screenshot Output Path):**
   - *Status:* Assigned to P02 / P07.
   - *Impact:* [`scripts/capture_screenshots.py`](file:///F:/dpl13.10/WikiSearchEngine-github/scripts/capture_screenshots.py) writes directly to `F:/dpl13.10/screenshots/`. Running parallel worktrees risks clobbering screenshot artifacts. Output directory must be made CLI-configurable.
4. **Architectural Decision (Canonical Document ID):**
   - All Phase 2 IR components (posting lists, BM25 scores, vector embeddings, interaction logs) must use `Document.id` (UUID) as the primary key. URLs are strictly source metadata.
5. **Architectural Decision (Stale Index Defense):**
   - The search pipeline MUST verify candidate document IDs against live PostgreSQL state to prevent returning unpublished or soft-deleted documents during index lag.

---

## 4. Shared-File Ownership Matrix (P01–P09)

To enable safe parallel worktree execution without merge conflicts or regressions:

| Phase | Sole Owned Paths & Responsibilities | Prohibited Shared Files (Must coordinate) |
| :--- | :--- | :--- |
| **P00** | Contracts, acceptance matrix, baseline audit (`docs/`) | No modifications to `src/`, `alembic/`, `tests/` |
| **P01** | `src/backend/core/`, security middleware, `api/auth.py`, admin bootstrap CLI, security tests, `.env.example` | Do NOT edit search, UI, or Docker configs |
| **P02** | `requirements*.txt`, `tests/conftest.py`, test DB setup, `.github/workflows/`, clean setup docs | Do NOT modify production business logic |
| **P03** | Index outbox migrations, `src/backend/search_index/`, ingestion CLI, lifecycle tests | Do NOT modify public API routes or BM25 scoring |
| **P04** | `src/backend/search/` (tokenizer, analyzer, inverted index, Okapi BM25 scoring), IR unit tests | Do NOT modify public API endpoints or frontend |
| **P05** | `/api/v1/search` endpoint, semantic/hybrid adapter, interaction logging, search integration tests | Do NOT modify frontend UI or inverted index builder |
| **P06** | `evaluate/run_eval.py`, evaluation qrels/queries, IR evaluation reports | Read-only access to search service; no production code edits |
| **P07** | `src/frontend/`, Playwright E2E tests, responsive/a11y fixes, screenshot capture scripts | Do NOT modify search algorithms or DB migrations |
| **P08** | Dockerfile, `docker-compose.prod.yml`, Caddy reverse proxy, backup/restore runbooks | Do NOT modify frontend application code |
| **P09** | Release gate checklist, release notes, independent QA verification | Read-only audit; zero feature implementation |

> [!WARNING]
> **Strict Concurrency Rule:** Two parallel chats MUST NEVER concurrently edit [`alembic/`](file:///F:/dpl13.10/WikiSearchEngine-github/alembic), [`src/backend/main.py`](file:///F:/dpl13.10/WikiSearchEngine-github/src/backend/main.py), [`src/backend/models/`](file:///F:/dpl13.10/WikiSearchEngine-github/src/backend/models), or [`README.md`](file:///F:/dpl13.10/WikiSearchEngine-github/README.md). Any shared file change requires sequential integration.

---

## 5. Execution Sequence for Subsequent Chats

```text
Clone Verified -> P00 (DONE) -> (P01 || P02) -> Integration A -> P03 -> P04 -> P05 -> (P06 || P07) -> Integration B -> P08 -> P09
```

- **Next Immediate Step:** Run **P01** (Production config, security, admin bootstrap) and **P02** (Clean setup, dependencies, test isolation, CI).
- If running concurrently, P01 and P02 MUST use separate git worktrees/branches:
  - Branch `feature/p01-security` for P01.
  - Branch `feature/p02-clean-setup` for P02.
- Upon completion of P01 and P02, perform **Integration Checkpoint A** to merge both branches and verify backend security + test suite before proceeding to P03.
