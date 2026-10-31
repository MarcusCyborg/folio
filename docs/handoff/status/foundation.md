# Foundation Status Report

Status: FOUNDATION_READY
ReadyToIntegrate: not applicable (Foundation gatekeeper)
Scope and owned files:
- Shared configuration, runtime manifests (`requirements.txt`, `requirements-dev.txt`, `requirements-legacy.txt`, `docker-compose.yml`, `.env.example`).
- Core security, authentication, session, CSRF and dependency injection (`src/backend/core/**`).
- Complete SQLAlchemy ORM models, relationships and Alembic initial migration (`src/backend/models/**`, `alembic/**`).
- Portable 100-document fixture and idempotent seed script (`fixtures/folio/**`, `scripts/seed_folio.py`).
- Frontend shell, tokens, typography, shared UI components and routing stubs (`src/frontend/**`, `docs/ui-components.md`).
- Auth API endpoints (`src/backend/api/auth.py`, `src/backend/schemas/auth.py`).
- Feature router stubs (`api/library.py`, `engagement.py`, `events.py`, `api/admin/__init__.py`).
- Foundation verification tests (`tests/backend/foundation/**`).

Branch / commit:
- Baseline on `main` (commit ready after staging foundation files).

Implemented endpoints or screens:
- `GET /health`: Lightweight PostgreSQL healthcheck without ML dependency.
- `GET /search`: Legacy semantic search adapter with 503 protection when disabled.
- `GET /api/v1/auth/session`: Guest or user session retrieval with CSRF token.
- `POST /api/v1/auth/register`: Public registration with forced `member` role and session rotation.
- `POST /api/v1/auth/login`: Authenticated credential verification with session rotation.
- `POST /api/v1/auth/logout`: Session revocation back to guest session.
- `PATCH /api/v1/auth/profile`: Display name and bio modification for current user.
- `POST /api/v1/auth/password`: Password update with other-session revocation.
- Static mount `/`: Serves HTML shell, CSS tokens, and ES modules router.

Commands run and actual results:
1. `alembic upgrade head`:
   - Output: `Running upgrade -> efeaa3d84c9b, initial_folio_schema` (Exit code 0).
2. `python scripts/seed_folio.py` (Run 1):
   - Output: `Seed complete. Database now contains: 5 users, 100 published documents, 3 drafts, 6 categories, 79 tags.` (Exit code 0).
3. `python scripts/seed_folio.py` (Run 2 — Idempotency check):
   - Output: `Seed complete. Database now contains: 5 users, 100 published documents, 3 drafts, 6 categories, 79 tags.` (Exit code 0, 0 duplicates).
4. `pytest tests/backend/foundation -v`:
   - Output: `12 passed in 0.94s` (Exit code 0).

Contract deviations / shared-file requests:
- Contract frozen as `v1 frozen` (2026-10-31).
- No deviations from CONTRACTS.md.

Known failures and unverified paths:
- None for Foundation scope. Feature endpoints in library and admin correctly return `501 NOT_IMPLEMENTED` stubs awaiting Wave 1 workers.

How to manually verify:
1. Ensure PostgreSQL is running on localhost:5432.
2. Run `alembic upgrade head`.
3. Run `python scripts/seed_folio.py`.
4. Run `pytest tests/backend/foundation -v`.
5. Run `uvicorn src.backend.main:app --port 8000` and visit `http://127.0.0.1:8000/`.
