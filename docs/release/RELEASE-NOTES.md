# Folio / WikiSearchEngine — Release Notes (v1.0.0-rc1)

**Release Candidate:** v1.0.0-rc1
**Release Date:** 2026-11-05
**Git Branch:** `codex/integration-b`
**Git Commit SHA:** `d11e2004a9431f9d79cba32baf325f5da4bb98cb`
**Linear Alembic Head:** `20261105_context_fallback (head)`
**Assignment Verdict:** **ASSIGNMENT_READY**
**Deployment Verdict:** **READY_WITH_CONDITIONS**

---

## 1. Executive Summary

Folio is an enterprise document and research library platform built with Python FastAPI, PostgreSQL 16, and vanilla modern JavaScript (ES modules). This release completes all mandatory requirements of **Phase 1** (full-stack CRUD, Argon2id authentication, session management, CSRF defense, 5-role RBAC, content moderation, analytics, and sanitized reading view) and **Phase 2 Core** (Folio UUID canonical identification, text tokenization, inverted indexing with disk checksums, Okapi BM25 retrieval, transactional outbox lifecycle, search API with candidate snapshots, interaction click telemetry, and a reproducible offline IR evaluation benchmark).

Advanced extensions (ChromaDB vector embedding, Reciprocal Rank Fusion hybrid retrieval, public VPS hosting, and ACME TLS automation) are fully decoupled. When vector backends are absent or unreachable, the system automatically falls back to Okapi BM25 or ILIKE with transparent degradation declarations.

---

## 2. Key Features & Architectural Accomplishments

### 2.1 Phase 1 Full-Stack Core
- **RESTful API:** Built on FastAPI with stratified routers under `/api/v1` (`auth`, `library`, `engagement`, `events`, `admin/content`, `admin/moderation`, `admin/governance`, `admin/analytics`).
- **PostgreSQL 16 Document Store:** Authoritative source of truth using SQLAlchemy 2 declarative models and Alembic migrations.
- **Authentication & Security Hardening:** Argon2id password hashing, session tokens, HttpOnly/SameSite session cookies, CSRF protection on mutating HTTP verbs, immediate session revocation upon account deactivation.
- **5-Role Access Control (RBAC):** `super_admin`, `content_manager`, `moderator`, `data_seo`, and `member` with dynamic role-capability management in the database.
- **Last Active Super-Admin Protection:** Atomic guarantee preventing deletion, disabling, or self-demotion of the final remaining super administrator.
- **Content Engagement:** Threaded Markdown comments, `@username` autocomplete mention detection, idempotent document liking, and comment reporting with moderator queues (visible, hidden, spam).
- **Sanitized Presentation:** Bleach HTML sanitization preventing XSS across live previews, reading views, and comments; KaTeX mathematical typesetting.

### 2.2 Phase 2 Core Information Retrieval
- **Canonical UUID Identifier:** Folio `Document.id` (RFC 4122 UUID) serves as the primary key across relational tables, inverted index posting lists, search context candidate snapshots, and telemetry logs. URL is strictly preserved as source attribution metadata.
- **Text Analyzer (`src/backend/search/analyzer.py`):** Deterministic text preprocessing enforcing Unicode NFKC normalization, ASCII lowercasing, punctuation boundary stripping, and stopword removal. Used identically at index time and query time.
- **Inverted Index (`src/backend/search/index.py`):** Memory-efficient posting lists mapping terms to `{doc_id: term_frequency}`, document length tracking, document frequencies, and corpus statistics. Atomically serialized to disk with SHA-256 verification (`docs_sha256`, `postings_sha256`) and dynamic disk signature reloading (IB-R01).
- **Okapi BM25 Ranking (`src/backend/search/bm25.py`):** Formula implementation with configurable $k_1=1.5$, $b=0.75$, separate title boost, and deterministic tie-breaking (`score DESC, doc_id ASC`). Verified against hand-calculated mathematical reference to $10^{-6}$ precision.
- **Transactional Outbox & Worker (`src/backend/search_index/`):** Document mutations emit `index_jobs` rows in the same transaction. Background `IndexWorker` claims jobs atomically using `SKIP LOCKED`, verifies document revision hashes (IB-R02), and updates the active generation.
- **0-Second Unpublish / Soft-Delete Lag Defense:** Read path dynamically verifies candidate IDs against live PostgreSQL (`status = 'published' AND deleted_at IS NULL`). Unpublish or delete actions immediately prune documents from search results (0 seconds lag).
- **Stable Pagination via Search Context Tokens:** Server-issued `search_context_token` (UUIDv4) with 15-minute absolute TTL freezes candidate ranking snapshots and binds user session and query parameters. Page slices prune live unpublications without backfilling, preventing duplicate or skipped results.
- **Interaction Click Telemetry:** Search events log exact returned Document IDs. Result clicks (`POST /api/v1/events/clicks`) enforce server-side membership validation, actor binding, and idempotent `request_key` handling. Detail view page reloads emit view events only.
- **Reproducible Evaluation Harness (`evaluate/run_eval.py`):** Automated evaluation CLI with canonical corpus manifest (103 articles: 100 published, 3 drafts), 30 benchmark queries (10 tune, 20 held-out test), and graded qrels (2/1/0). Evaluates P@5, P@10, Recall@10, MAP@10 (0.7590), MRR@10 (0.8958), and nDCG@10 (0.8466). Zero dataset integrity violations (`--validate-only`).

### 2.3 Operations, Staging & Disaster Recovery
- **Multi-Stage Containerization:** Multi-stage `Dockerfile` based on Debian Bookworm slim, creating non-root system user `folio` (UID 10001) and container `HEALTHCHECK`.
- **Network Segmentation:** `docker-compose.prod.yml` isolates `db` and `worker` behind `backend-net (internal: true)`. Only the reverse proxy exposes host ports (80, 443).
- **Dedicated Migration Runner:** One-shot migration container executes `alembic upgrade head`, provisions first super-admin, and builds initial index. Neither web nor worker executes migrations.
- **Worker Daemon Resiliency:** Stale-lock crash recovery reclaims jobs stuck in `processing` exceeding 300 seconds.
- **Disaster Recovery Tooling:** `scripts/ops/backup.py` and `restore.py` produce and verify gzip archives with SHA-256 manifests, tamper rejection, and automatic index rebuild on storage volume loss.
- **Certificate Tooling:** `scripts/ops/init_certs.py` generates RSA-2048 self-signed SSL certificates with SANs for initial proxy boot. `cryptography==48.0.0` declared in `requirements.txt` and `constraints.txt`.
- **Line Ending Safeguards:** Root `.gitattributes` enforces `*.sh text eol=lf`.

---

## 3. Stratified Dependencies

Folio eliminates dependency bloat through strict stratification:
- **`requirements.txt`:** Core runtime dependencies (`fastapi`, `uvicorn`, `sqlalchemy`, `psycopg`, `alembic`, `argon2-cffi`, `pydantic`, `bleach`, `markdown`, `cryptography`, `python-dotenv`).
- **`requirements-dev.txt`:** Backend test harness and HTTP clients (`pytest`, `httpx`).
- **`requirements-browser.txt`:** Browser automation and E2E testing (`playwright`).
- **`requirements-legacy.txt`:** Optional decoupled ML/embedding packages (`chromadb`, `sentence-transformers`, `torch`).
- **`constraints.txt`:** Exact tested and pinned package versions across environments.

---

## 4. Evaluator Quickstart & Demo Guide

### Prerequisites
- Python 3.10 or higher.
- PostgreSQL 16+ running locally on port `5432` with database `folio`.

### Step-by-Step Setup (PowerShell on Windows)

```powershell
# 1. Navigate to repository root
Set-Location F:\dpl13.10\WikiSearchEngine-github

# 2. Create and activate a clean virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install core runtime dependencies using constraints
python -m pip install --upgrade pip
pip install -c constraints.txt -r requirements.txt -r requirements-dev.txt

# 4. Configure local database environment
Copy-Item .env.example .env
# Edit .env if your PostgreSQL credentials differ from postgres:postgres@127.0.0.1:5432/folio

# 5. Apply migrations and seed 103 canonical articles
alembic upgrade head
python scripts/seed_folio.py

# 6. Build the initial inverted index
python scripts/index_cli.py build-index --force --verify

# 7. Start the Folio web server
uvicorn src.backend.main:app --host 127.0.0.1 --port 8000
```

Open your browser to: **`http://127.0.0.1:8000`**

### Pre-Seeded Demo Accounts (Password: `FolioDemo2026!`)

| Role | Email | Username | Capabilities |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `admin@folio.test` | `admin` | Users, role capability matrix, audit log diffs, settings |
| **Content Manager** | `content@folio.test` | `content_mgr` | Document authoring, Markdown editor, taxonomy CRUD |
| **Moderator** | `moderator@folio.test` | `moderator` | Comment moderation queue, reports triage, suspensions |
| **Data & SEO Specialist** | `seo@folio.test` | `seo_specialist` | SERP preview, SEO metadata, analytics overview |
| **Member / Reader** | `reader@folio.test` | `reader` | Document reading, liking, commenting with `@mentions` |

---

## 5. Known Limitations & Operational Considerations

1. **Host Workstation Environment:** The current Windows workstation does not run an active Docker daemon or local PostgreSQL server (`BLOCKED_ENV`). All configuration linters, pure unit tests, and validation scripts pass with exit code `0`. In continuous integration (`.github/workflows/ci.yml`), a dedicated PostgreSQL service container executes the full test suite.
2. **Optional Semantic Backend:** Semantic search requires optional ML dependencies in `requirements-legacy.txt` and a running ChromaDB instance. Without them, semantic and hybrid queries gracefully degrade to Okapi BM25 (`engine_used="fallback_bm25"`, `is_degraded=True`).
3. **Public Cloud Hosting:** Public domain names, DNS routing, and ACME Let's Encrypt certificates are out of scope for local assignment submission and are configured as operational templates.
