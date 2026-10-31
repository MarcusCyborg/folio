# Folio Milestone Integration A / R00 — Local Source Integration Handoff

**Handoff ID:** `IA-R00-integration`  
**Milestone:** Integration A — Task R00 (Local Source Integration & Workspace Preparation)  
**Date:** 2026-11-01  
**Author:** Folio Integration Engineer  
**Status:** `SOURCE INTEGRATED / VALIDATION PENDING` (Integration A NOT PASSED; verification pending R01–R06)

---

## 1. Official Workspace & Git Metadata

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Official Integration Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree created in R00 |
| **Integration Branch** | `codex/integration-a-remediation` | Local integration branch (not merged into `main`) |
| **Source Repository** | `F:/dpl13.10/WikiSearchEngine-github` | Untouched, pristine working tree preserved |
| **Expected Remote** | `https://github.com/MarcusCyborg/folio.git` | Push/fetch target (NO remote push performed) |
| **Common Baseline Ref** | `main` (`c4b19cffa676b4437e7346da2c410b198b04dc2c`) | Common merge base for P01 and P02 |
| **Source Branch P01** | `feature/p01-security` (`740eb5f1cc5f6b0c90480310e37a36234086a726`) | Checked out in worktree `WikiSearchEngine-p01` |
| **Source Branch P02** | `feature/p02-clean-setup` (`1ac72ad8a9e979682ddad8253c0d6d3e49222055`) | Checked out in worktree `WikiSearchEngine-p02` |
| **Initial Merge SHA** | `25a6b554b5f904ecb1e60f0663dbd7bebf8836eb` | 3-way merge commit combining P01 and P02 |

---

## 2. Integration Procedure & Ancestry

1. **Worktree & Branch Creation:**
   Created integration branch `codex/integration-a-remediation` and dedicated worktree at `F:/dpl13.10/WikiSearchEngine-ia-fix` rooted at baseline commit `c4b19cf`.
2. **P01 Integration:**
   Fast-forward merged `feature/p01-security` (`740eb5f`). All security hardening modules, bootstrap scripts, and tests were incorporated cleanly.
3. **P02 Integration:**
   Merged `feature/p02-clean-setup` (`1ac72ad`). Git identified exactly one content conflict in `scripts/seed_folio.py`. All other files (requirements, constraints, conftest, CI workflows, screenshot scripts, and fixtures) merged automatically without conflict.
4. **Git Ancestry Graph:**
   ```text
   *   25a6b55 (HEAD -> codex/integration-a-remediation) merge(p02): integrate clean setup...
   |\  
   | * 1ac72ad (feature/p02-clean-setup) feat(p02): clean setup, stratified dependencies...
   * | 740eb5f (feature/p01-security) docs(handoff): update P01 handoff with final commit SHA
   * | 42bd60d fix(security): refine admin bootstrap commit handling...
   * | 998ba09 feat(security): implement M1 production validation...
   |/  
   * c4b19cf (main, origin/main) chore: move public screenshots outside the repository
   ```
   Both `feature/p01-security` and `feature/p02-clean-setup` are direct parents of the merge commit. Zero history rewrite or amend operations were executed.

---

## 3. Conflict Resolution & Seed API Behavior

The single conflict occurred in [`scripts/seed_folio.py`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/scripts/seed_folio.py). Resolution was performed strictly by behavior synthesis rather than picking `ours` or `theirs`:

### 3.1 Function Signature & API Contract
```python
def seed_database_all(db: Session, skip_demo_users: bool = False, auto_commit: bool = False):
    """Executes all seed stages within a session.

    If auto_commit is False (default when caller provides Session),
    flushes changes but leaves transaction commit/rollback to caller.
    """
    ...

def run_seed(target=None, db_url=None, skip_demo_users: bool = False):
    """
    Idempotent seeding entry point.
    target can be:
      - None (uses settings.DATABASE_URL via default SessionLocal)
      - a Session instance (caller manages lifecycle and transaction ownership; run_seed will not commit)
      - an Engine instance (run_seed creates an isolated session, commits on success, rollbacks on error)
    db_url can be a database URL string (run_seed creates an engine and session, commits on success).
    skip_demo_users: bool (if True, demo users are skipped; in production/staging they are always skipped).
    """
```

### 3.2 Invariants Preserved
1. **Transaction Ownership:**
   - When `target` is a `Session` (e.g., passed by unit tests or transactional harnesses), `seed_database_all` executes `db.flush()` and sets `auto_commit=False`. `run_seed` **does not commit**, ensuring the caller retains 100% control over commit or rollback.
   - When `target` is an `Engine`, `db_url`, or default `SessionLocal`, `run_seed` owns the session, commits on success (`auto_commit=True`), rolls back on exception, closes the session, and disposes the temporary engine if created.
2. **Production/Staging Demo User Exclusion:**
   - In `seed_demo_users(db: Session, skip: bool = False)`:
     ```python
     if skip or settings.APP_ENV in ("production", "staging"):
         print(f"Skipping local demo accounts seeding in {settings.APP_ENV} environment.")
         return
     ```
     Even if a caller passes `skip=False`, demo users are strictly excluded in `production` and `staging`. No flag can accidentally re-enable demo users in these environments.
3. **CLI Ambiguity Resolution:**
   - In `main()`:
     ```python
     group = parser.add_mutually_exclusive_group()
     group.add_argument("--db-url", type=str, default=None, help="Explicit database URL to seed")
     group.add_argument("--test", action="store_true", help="Seed TEST_DATABASE_URL instead of primary DATABASE_URL")
     parser.add_argument("--no-demo-users", action="store_true", help="Skip demo user account creation")
     ```
     `--db-url` and `--test` are mutually exclusive. Passing both triggers an immediate argparse rejection (`error: argument --test: not allowed with argument --db-url`), completely eliminating silent precedence bugs.
4. **Bootstrap Admin Import Safety:**
   - `scripts/bootstrap_admin.py` imports `seed_roles_and_permissions` and `seed_settings` from `scripts.seed_folio`. Neither function triggers database seeding at module import time.

---

## 4. Preservation of Tracked & Untracked Assets

### 4.1 Untracked Documents from Main Formally Tracked via P02
The following documents, which were untracked in `WikiSearchEngine-github`, were brought into version control via P02's commit `1ac72ad`:
- [`FOLIO-COMPLETION-PLAN.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/FOLIO-COMPLETION-PLAN.md)
- [`GEMINI-EXECUTION-PROMPTS.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/GEMINI-EXECUTION-PROMPTS.md)
- [`docs/acceptance-matrix.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/docs/acceptance-matrix.md)
- [`docs/handoff/gemini/CLONE-REPORT.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/docs/handoff/gemini/CLONE-REPORT.md)
- [`docs/handoff/gemini/P00-baseline.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/docs/handoff/gemini/P00-baseline.md)
- [`docs/search-contract.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/docs/search-contract.md)
- [`docs/handoff/gemini/P02-clean-setup-ci.md`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/docs/handoff/gemini/P02-clean-setup-ci.md)

SHA-256 hash comparison between the source untracked files and the worktree tracked files confirmed **100% exact match** across all files.

### 4.2 Review Artifacts Copied with Full Hash Verification
All 21 review documents and evidence files from `F:/dpl13.10/WikiSearchEngine-github/docs/handoff/review` were copied into `F:/dpl13.10/WikiSearchEngine-ia-fix/docs/handoff/review` without altering originals in the source repository:
- `docs/handoff/review/INTEGRATION-A-REVIEW.md`
- `docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md`
- `docs/handoff/review/GEMINI-INTEGRATION-A-FIX-PROMPTS.md`
- `docs/handoff/review/evidence-20261101-cf1bdce021/` (logs, probe scripts, inspection JSONs)

Verification script verified 21/21 files with 0 hash mismatches.

### 4.3 Exclusions Enforced
- **Zero** `.env` files copied.
- **Zero** `venv/` or virtual environments copied.
- **Zero** database files or sqlite caches copied.
- **Zero** model or data cache files copied.
- Pristine state of `F:/dpl13.10/WikiSearchEngine-github` maintained (100% clean tracked files, untracked files untouched).

---

## 5. Security & Invariant Verification Status

All subsystems from both P01 and P02 are present in the unified working tree:

| Subsystem | Source | Verification in R00 |
| :--- | :--- | :--- |
| **Lifespan Production Validation** (`validate_production`) | P01 | Source verified in `src/backend/main.py` and `src/backend/core/config.py` |
| **Security Middleware** (Headers, Origin verification) | P01 | Source verified in `src/backend/core/middleware.py` |
| **Rate Limiter** (`rate_limit.py`) | P01 | Source verified in `src/backend/core/rate_limit.py` |
| **Admin Bootstrap CLI** (`bootstrap_admin.py`) | P01 | Source verified in `scripts/bootstrap_admin.py` |
| **Security Hardening Tests** (`test_security_hardening.py`)| P01 | Source verified in `tests/backend/foundation/test_security_hardening.py` |
| **Dependency Stratification & Constraints** | P02 | Verified in `requirements*.txt` and `constraints.txt` |
| **Conftest Fixtures & Test Lifecycle** | P02 | Source verified in `tests/conftest.py` |
| **CI Workflow** | P02 | Source verified in `.github/workflows/ci.yml` |
| **Screenshot Capture Config** | P02 | Source verified in `scripts/capture_screenshots.py` |
| **Seed Execution & Invariants** | P01 + P02 | Resolved in `scripts/seed_folio.py`, py_compile passed (exit 0) |

> [!CAUTION]
> **R00 Safety Constraint Strictly Maintained:**  
> In accordance with instructions and Finding IA-02, **NO pytest fixtures, migrations, seeds, or DB-accessing CLI commands were executed** during R00. Guard P02 contains a known vulnerability (driver target query override) that could trigger a destructive `DROP SCHEMA` on non-test databases. Testing during R00 was strictly confined to static AST, file hash checks, py_compile, and Git ancestry validations.

---

## 6. Action Items & Instructions for R01

Chat R01 must take over the integration worktree and resolve **Finding IA-02**:

1. **Workspace:** Operate exclusively inside `F:/dpl13.10/WikiSearchEngine-ia-fix` on branch `codex/integration-a-remediation`. Do not touch `main` or P01/P02 worktrees.
2. **Isolate Pure Safety Validator:**
   - Extract the test database URL guard logic out of `tests/conftest.py` into a standalone, pure validation module with zero side effects.
   - Guard tests must execute via pure unit tests (`pytest --noconftest` or dedicated test directory) without loading application database fixtures.
3. **Effective Driver Target Policy:**
   - Inspect effective SQLAlchemy/psycopg connection arguments (`create_connect_args`).
   - Reject connection-target overrides (e.g. `?dbname=...`, `host=...`, `port=...`, `service=...`, multi-host).
   - Normalize default ports (5432) and loopback aliases (`localhost` vs `127.0.0.1`).
   - Ensure the database name is dynamically qualified and uniquely owned by the test run.
4. **Ownership Verification & Safe Teardown:**
   - Verify that destructive actions (`DROP SCHEMA`, connection termination) operate **only** against databases explicitly created and registered in the test run's ownership manifest.
   - Teardown must never terminate connections of concurrent runs or drop unowned schemas.
5. **PostgreSQL Environment:**
   - Provision an isolated PostgreSQL instance/container for test runs. If an isolated database server is unavailable, complete pure guard implementations, execute pure test matrix, and report `BLOCKED_ENV` without faking passes.
