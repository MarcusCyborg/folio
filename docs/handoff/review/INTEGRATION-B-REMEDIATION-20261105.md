# Integration B Remediation Handoff Report (2026-11-05)

- **Repository / Workspace:** `F:\dpl13.10\WikiSearchEngine-github`
- **Branch:** `codex/integration-b`
- **Base HEAD SHA (before remediation):** `9a4ae5777cff1c8274bc51c1e037754ea255a619`
- **Code & Test Remediation Commit SHA:** `8f28d306ddd9c121bf8fa568d94fbb2c16bdda99`
- **Alembic Linear Head:** `20261105_context_fallback (head)`
- **Date:** 2026-11-05

---

## 1. Summary Table of Findings & Remediations (`IB-R01` – `IB-R06`)

| Finding ID | Severity | Root Cause | Files Modified | Remediation Summary | Verification & Regression Tests |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **IB-R01** | **P0** | `SearchEngine` cached `InvertedIndex` in `self._index_cache[generation_id]` indefinitely without checking whether `IndexWorker` (or another process) had updated the generation's posting files on disk. | `src/backend/search/index.py`<br>`src/backend/search/engine.py`<br>`src/backend/search_index/worker.py`<br>`tests/backend/search/test_integration_review_probe.py` | 1. `InvertedIndex.save()` writes `doc_entries.json` first, `postings.json` second, and `index_stats.json` last via PID+UUID `.tmp` files and atomic `os.replace`, embedding `index_version`, `checksum`, `docs_sha256`, and `postings_sha256`.<br>2. `InvertedIndex.load()` validates `docs_sha256` and `postings_sha256` against `index_stats.json` (with brief retry for concurrent atomic replaces) so readers never load half-written/torn state.<br>3. `SearchEngine.get_or_load_index()` compares `InvertedIndex.read_disk_signature()` against cached `_index_signatures[generation_id]` and reloads automatically when on-disk index state changes, while keeping existing `SearchContext` candidate snapshots immutable. | `test_review_disk_update_visible_to_existing_reader`<br>`test_ib_r01_search_bm25_sees_publish_edit_unpublish_delete_without_restart`<br>`test_ib_r01_reader_rejects_half_written_or_mismatched_checksum_and_keeps_snapshot` |
| **IB-R02** | **P1** | During `tag_ids` updates and soft-deletes, `record_revision_and_outbox_job()` computed `compute_doc_instance_hash(doc)` before `DocumentTag` mutations were flushed/refreshed in the identity map and before `deleted_at` timezone normalization, causing `IndexJob.revision_hash` to differ from post-commit `compute_doc_instance_hash(doc)` and causing `IndexWorker` to skip valid jobs as stale. | `src/backend/search_index/hashing.py`<br>`src/backend/search_index/outbox.py`<br>`src/backend/services/admin/content_service.py`<br>`src/backend/search_index/importer.py`<br>`tests/backend/search/test_integration_review_probe.py` | 1. `compute_doc_instance_hash(doc)` flushes pending session mutations and queries `DocumentTag.tag_id` rows directly from the active transaction rather than reading potentially stale `doc.document_tags` in the identity map.<br>2. `_normalize_deleted_at()` normalizes timezone-aware UTC datetimes and PostgreSQL naive UTC timestamps identically.<br>3. `admin_create_document`, `admin_update_document`, `admin_update_document_status`, `admin_delete_document`, and `record_revision_and_outbox_job` flush and expire relationship state within the same transaction before emitting revisions/jobs. | `test_review_tag_edit_job_matches_committed_document[False/True]`<br>`test_ib_r02_tag_add_and_remove_indexed_by_worker_and_rollback_safe[False/True]` |
| **IB-R03** | **P1** | `SemanticAdapter.query()` returned dense hits without enforcing PostgreSQL publication/deletion status, `category_id`, strict AND `tag_ids`, or UTC `date_from`/`date_to` bounds prior to RRF fusion and `SearchContext` snapshot creation. | `src/backend/services/search/search_service.py`<br>`tests/backend/search/test_integration_review_probe.py` | Added `SearchService._filter_semantic_candidates()`, which queries PostgreSQL to enforce `status == 'published'`, `deleted_at IS NULL`, `category_id` exact match, strict AND `tag_ids`, and inclusive UTC `date_from`/`date_to` on `created_at`, followed by deterministic tie-breaking (`-score, doc_id ASC`) and 1-based re-ranking **before** RRF fusion, `candidate_ids` snapshot, `snapshot_candidate_count`, and `SearchContext` persistence. | `test_review_dense_candidates_obey_category_filter[semantic/hybrid]`<br>`test_ib_r03_dense_candidates_obey_tags_dates_draft_and_soft_delete[semantic/hybrid]` |
| **IB-R04** | **P1** | `SearchContext` stored only requested `mode` (`bm25`, `semantic`, `hybrid`), so page 2+ reconstructed `engine_used = ctx.mode` with `is_degraded = False` and lost page 1's actual fallback state (`fallback_bm25` or `ilike_fallback`). | `src/backend/models/search_index.py`<br>`alembic/versions/20261105_search_context_fallback_meta.py`<br>`src/backend/search/context_manager.py`<br>`src/backend/services/search/search_service.py`<br>`tests/backend/search/test_integration_review_probe.py` | 1. Added `engine_used`, `is_degraded`, and `degraded_reason` columns to `search_contexts` via linear Alembic migration `20261105_context_fallback`.<br>2. `SearchContextManager.create_context()` persists actual `engine_used`, `is_degraded`, and `degraded_reason` on page 1 (covering semantic fallback, hybrid fallback, BM25->ILIKE fallback, and double fallback `semantic/hybrid -> BM25 failure -> ilike_fallback`).<br>3. Page 2+ restores `engine_used`, `is_degraded`, and `degraded_reason` directly from `SearchContext` while preserving actor, TTL, filter, page-size, and generation bindings. | `test_review_fallback_declaration_survives_next_page`<br>`test_ib_r04_pagination_preserves_hybrid_bm25_and_double_fallbacks_and_bindings` |
| **IB-R05** | **P1** | `evaluate/run_eval.py` omitted failed queries from the positive quality denominator (`len(p10_list)`), called `execute_ilike` directly in `verify_fallbacks()` with hardcoded `verified: True`, hardcoded `"693d031 (Milestone P05)"`, and lacked explicit latency boundary and `BLOCKED_ENV` declarations. | `evaluate/run_eval.py`<br>`tests/evaluate/test_run_eval.py` | 1. `evaluate_engine_queries()` records per-query `status` (`successful`, `degraded`, `failed`, `timeout`), `error`, and `error_type`, and appends `0.0` to all positive metric lists (`p5_list`, `p10_list`, `recall10_list`, `ap10_list`, `mrr10_list`, `ndcg10_list`) when a positive query fails or times out.<br>2. `PerformanceBenchmarker.verify_fallbacks()` marks active generations unavailable and calls real `evaluator.execute_bm25()` (`SearchService(mode="bm25")`), computing `verified` dynamically from `engine_used == "ilike_fallback" and is_degraded is True`.<br>3. Added `resolve_git_commit_sha()`, `build_latency_boundaries()` (`retrieval_only`, `service_api_database`, `semantic_model_latency`), and `BLOCKED_ENV` reporting when ChromaDB/SentenceTransformer is unavailable. | `test_ib_r05_failed_and_timeout_queries_included_in_quality_denominator`<br>`test_ib_r05_verify_fallbacks_calls_real_search_service_not_direct_ilike`<br>`test_ib_r05_dynamic_git_sha_and_latency_boundaries` |
| **IB-R06** | **P1** | `reset_browser_test_data()` in `tests/conftest.py` deleted all tables (including `index_generations`) and re-seeded documents without building an active lexical index generation, causing frontend BM25 requests and evidence screenshot `01` to display `ILIKE_FALLBACK`. | `tests/conftest.py`<br>`tests/frontend/public/test_p07_evidence.py`<br>`tests/frontend/public/test_search_results_ux.py` | 1. `reset_browser_test_data()` now calls `build_active_lexical_index_for_engine(engine)` and clears `search_engine` cache after `run_seed()`, and exposes the `active_lexical_index` fixture.<br>2. Kept existing route-mock fallback test (`test_degraded_engine_banner_and_badge`) and added `test_healthy_bm25_mode_returns_bm25_without_degraded_banner` and `test_deliberate_missing_index_fallback_displays_degraded_banner`.<br>3. Added `test_ib_r06_healthy_bm25_and_deliberate_fallback_evidence` writing screenshots into dedicated subdirectory `p07_evidence_ib_r06` without overwriting old baseline screenshots. | `test_healthy_bm25_mode_returns_bm25_without_degraded_banner`<br>`test_deliberate_missing_index_fallback_displays_degraded_banner`<br>`test_capture_p07_complete_evidence`<br>`test_ib_r06_healthy_bm25_and_deliberate_fallback_evidence` |

---

## 2. Database Migration & Linear Alembic Head

- **New Migration File:** `alembic/versions/20261105_search_context_fallback_meta.py`
  - **Revision ID:** `20261105_context_fallback`
  - **Down Revision:** `20261101_index_lifecycle`
  - **Schema Changes:** Adds `engine_used` (`VARCHAR(32)`), `is_degraded` (`BOOLEAN NOT NULL DEFAULT false`), and `degraded_reason` (`VARCHAR(500)`) to `search_contexts`, backfilling `engine_used = mode` for any pre-existing rows.
- **Output of `python -m alembic heads`:**
  ```text
  20261105_context_fallback (head)
  ```

---

## 3. Mandatory Verification & Test Suite Results

All tests were executed against an isolated PostgreSQL 16.10 instance (`127.0.0.1:55464`) using `F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe`:

1. **Integration B Review Probes & Regression Suite:**
   - Command: `python -m pytest tests/backend/search/test_integration_review_probe.py -q`
   - Result: `13 passed, 3 warnings in 23.49s`
2. **Search & Search Index Backend Suites:**
   - Command: `python -m pytest tests/backend/search tests/backend/search_index -q`
   - Result: `99 passed, 3 warnings in 97.45s (0:01:37)`
3. **Full Backend, Evaluation, Safety & Security Suites:**
   - Command: `python -m pytest tests/backend tests/evaluate tests/safety tests/security -q`
   - Result: `311 passed, 29 warnings in 168.14s (0:02:48)`
4. **Full Frontend Playwright Browser Suite:**
   - Command: `python -m pytest tests/frontend -q`
   - Result: `39 passed, 5 warnings in 278.60s (0:04:38)`
5. **Evaluation Dataset Integrity & Coverage Validation:**
   - Command: `python evaluate/run_eval.py --validate-only`
   - Result: `Status: VALIDATION PASSED (Zero integrity violations)` (`103` manifest docs: `100` published, `3` drafts; `30` queries: `24` positive, `6` negative)
6. **Alembic Heads Check:**
   - Command: `python -m alembic heads`
   - Result: `20261105_context_fallback (head)`
7. **Git Whitespace & Conflict Marker Check:**
   - Command: `git diff --check`
   - Result: Exit code `0` (clean)

---

## 4. Visual Evidence & Evaluation Artifacts

- **IB-R06 Dedicated Screenshot Subdirectory (`p07_evidence_ib_r06`):**
  - Healthy BM25 Desktop (`engine_used="bm25"`, `is_degraded=False`, `BM25` badge, no degraded banner):
    `F:\dpl13.10\folio-integration-backup-20261101\remediation-20261105\artifacts\WikiSearchEngine-github\9a4ae57\run_20261105_013922_6c92bc05\screenshots\p07_evidence_ib_r06\01_healthy_bm25_desktop_1440.png`
  - Deliberate Missing-Index Fallback (`engine_used="ilike_fallback"`, `is_degraded=True`, degraded banner visible):
    `F:\dpl13.10\folio-integration-backup-20261101\remediation-20261105\artifacts\WikiSearchEngine-github\9a4ae57\run_20261105_013922_6c92bc05\screenshots\p07_evidence_ib_r06\02_deliberate_ilike_fallback_banner_1440.png`
- **P07 Complete Evidence Run (`p07_evidence`):**
  - `F:\dpl13.10\folio-integration-backup-20261101\remediation-20261105\artifacts\WikiSearchEngine-github\9a4ae57\run_20261105_013922_6c92bc05\screenshots\p07_evidence\01_search_bm25_desktop_1440.png` (verified healthy `BM25` badge, no `ILIKE_FALLBACK`)
- **Post-Remediation Evaluation Output (`eval_results_p06.json`):**
  - `F:\dpl13.10\folio-integration-backup-20261101\remediation-20261105\eval_output\eval_results_p06.json`

---

## 5. Remaining Environment Limitations

- **Dense Vector Backend (`ChromaDB` / `sentence-transformers`):**
  - In the clean verification environment (`F:\dpl13.10\folio-live-runtime\venv-clean`), `chromadb` and `sentence-transformers` are not installed/running (`SemanticAdapter.check_availability()` returns `(False, "ChromaDB service unreachable")`).
  - Per `IB-R05`, `evaluate/run_eval.py` explicitly records `semantic_environment_status: "BLOCKED_ENV"` in `evaluation_metadata`, `operational_health.environment_status: "BLOCKED_ENV"` for `semantic` and `hybrid` modes, and `latency_boundaries.semantic_model_latency.status: "BLOCKED_ENV"`, without generating synthetic dense vector numbers.
