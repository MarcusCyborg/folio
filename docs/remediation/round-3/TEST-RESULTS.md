# Folio — Kết Quả Kiểm Thử Xác Minh Vòng 3 (Round 3 Test Results)

- **Ngày thực thi:** `2026-11-10`
- **Worktree sản phẩm:** `F:/dpl13.10/folio-audit-remediation`
- **Branch / Base:** `codex/folio-audit-remediation-20261106` (working tree chứa Round 2 + Round 3 trên base commit `b659fe57a5f7c9bb7cfdb14cbf11813e7d512333`)
- **Môi trường kiểm thử thực tế (đã đóng băng mã nguồn trước khi chạy full suite):**
  - OS / Runtime: Windows, Python `3.10.11`, `pytest 9.2.0` (`F:/dpl13.10/WikiSearchEngine/env/Scripts/python.exe`)
  - Cơ sở dữ liệu: **PostgreSQL 16.10** cô lập trên `127.0.0.1:62375` (`POSTGRES_BIN_PATH=F:/dpl13.10/folio-live-runtime/pgsql/bin`)
  - Trình duyệt E2E: **Playwright Chromium 153.0.8010.12**
  - Thư mục cô lập tạm khi chạy suite: `INDEX_STORAGE_DIR` và `FOLIO_ARTIFACT_ROOT` trỏ ra `$env:TEMP` để giữ nguyên trạng cây thư mục repo và `fixtures/folio/documents.jsonl` (`SHA-256: dc197eff2de35dcb6c889eb81660e261013996c31fd5e67edd951f22d0010648`).
  - Trạng thái triển khai online: **`LIVE_ACCEPTANCE: NOT_RUN`** (không push, merge hay đụng Vercel/production).

---

## 1. Tổng Hợp Full Suite Chạy Sau Khi Đóng Băng Mã Nguồn (JUnit XML)

Tất cả các con số dưới đây được trích trực tiếp bằng parser XML từ 3 tệp JUnit XML trong `test-results/round-3/final-run/` sau chỉnh sửa mã nguồn/test cuối cùng:

| Bộ kiểm thử | Lệnh thực thi | Total | Passed | Failed | Errors | Skipped | Thời lượng | Trạng thái | Nguồn XML |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| **Artifact Isolation (`--noconftest`)** | `pytest --noconftest tests/safety/test_artifact_isolation.py -v --junitxml=test-results/round-3/final-run/artifact-junit.xml` | 8 | **8** | 0 | 0 | 0 | 5.41s | `LOCAL_PASS` | [`artifact-junit.xml`](../../../test-results/round-3/final-run/artifact-junit.xml) |
| **Safety + Security + Backend + Evaluate** | `pytest tests/safety tests/security tests/backend tests/evaluate --ignore=tests/safety/test_artifact_isolation.py -q --junitxml=test-results/round-3/final-run/backend-junit.xml` | 388 | **388** | 0 | 0 | 0 | 518.52s | `LOCAL_PASS` | [`backend-junit.xml`](../../../test-results/round-3/final-run/backend-junit.xml) |
| **Frontend Playwright Chromium E2E** | `pytest tests/frontend -q --junitxml=test-results/round-3/final-run/frontend-junit.xml` | 92 | **92** | 0 | 0 | 0 | 1638.98s | `LOCAL_PASS` | [`frontend-junit.xml`](../../../test-results/round-3/final-run/frontend-junit.xml) |
| **Tổng cộng toàn bộ 3 JUnit XML** | Toàn bộ test suite cô lập không trùng lắp | **488** | **488** | **0** | **0** | **0** | **2162.91s** | `LOCAL_PASS` | 3 JUnit XML hợp nhất |

### Phân rã theo phân hệ (trích trực tiếp từ JUnit XML)

- **Backend / Safety / Security / Evaluate (`backend-junit.xml`, 388 tests):**
  - `tests/safety` (trừ `test_artifact_isolation.py`): **82 passed**
  - `tests/security`: **36 passed**
  - `tests/backend/admin`: **31 passed**
  - `tests/backend/foundation`: **64 passed** (bao gồm bài spider `scrapy` đã chạy pass trong venv)
  - `tests/backend/integration`: **1 passed**
  - `tests/backend/library`: **20 passed**
  - `tests/backend/ops`: **30 passed**
  - `tests/backend/search`: **85 passed**
  - `tests/backend/search_index`: **22 passed**
  - `tests/evaluate`: **17 passed**
- **Artifact Isolation (`artifact-junit.xml`, 8 tests):**
  - `tests/safety/test_artifact_isolation.py`: **8 passed**
- **Frontend Playwright Chromium (`frontend-junit.xml`, 92 tests):**
  - `tests/frontend/admin`: **11 passed**
  - `tests/frontend/public`: **81 passed** (bao gồm toàn bộ `test_round2_regressions.py` + `test_round3_regressions.py`)

---

## 2. Kiểm Chứng CLI, Cấu Hình & Diễn Tập Vận Hành Trên Mã Nguồn Đóng Băng

| Công cụ / Kịch bản | Mục tiêu | Kết quả thực tế | Bằng chứng |
|---|---|---|---|
| `python -m pip check` | Toàn vẹn dependency trong venv | `No broken requirements found.` (exit 0) | Terminal log `task-1181` |
| `python scripts/ops/validate_compose_and_config.py` | Kiểm tra tĩnh Compose, port/network isolation, Dockerfile, proxy headers/CSP, `.gitattributes` LF, SSL certs | **11/11** checks PASSED (exit 0) | Terminal log `task-1181` |
| `python scripts/verify_seed_idempotency.py` | Kiểm tra idempotency Alembic + seed 2 lần trên PostgreSQL 16 | Exit 0: `{"dialect": "postgresql", "counts": [5, 100, 3, 6, 123], "preserved_ids": 103, "preserved_edits": true}` | Terminal log `task-1181` |
| `python evaluate/run_eval.py --validate-only` | Kiểm tra schema/corpus/queries/qrels | Exit 0: `VALIDATION PASSED (Zero integrity violations)` (103 docs, 30 queries) | Terminal log `task-1181` |
| `scripts/run_restore_drill.py` (`R3-01` positive drill theo đúng runbook) | Backup DB nguồn PG16 (`103` docs, `344` document_tags, `123` tags) -> restore sang `folio_restore_drill_round3_final` | Exit 0: `"status": "passed"`, parity 15 counts + 6 SHA-256 digests, `has_open_report_partial_unique_index: true` (`uq_reports_open_comment_reporter`), `index_recovery.valid: true`, `smoke_test.search_smoke_test.status: "passed"` | [`r3-01-drill-report.json`](../../../test-results/round-3/r3-01-drill-report.json) |
| `python scripts/ops/restore.py --archive ... --verify-only` | Xác minh offline checksum & dump archive | Exit 0: `"status": "verified_offline"`, `manifest_alembic_head: "20261106_report_open_unique"`, `verified_files_count: 5`, `database_dump_bytes: 3710462` | [`r3-01-verify-only.json`](../../../test-results/round-3/r3-01-verify-only.json) |
| Negative probe `R3-01` (restore vào DB đã có bảng) | Bảo đảm dump không chứa `--clean`/`DROP` và DB đích giữ nguyên dữ liệu khi thất bại | Exit 3 từ `psql` (`relation "review_marker" already exists` và `relation "alembic_version" already exists`), rollback sạch, 104 bài + canary row nguyên vẹn | [`r3-01-negative-probe.json`](../../../test-results/round-3/r3-01-negative-probe.json) |
| CLI `python evaluate/run_eval.py --split all --k 10` (`R3-05`) | Chạy evaluation thật trên PG16 đã seed & build BM25 index | Exit 0: `corpus_db_alignment="MATCH"`, `verification_status="VERIFIED_MATCH"`, SHA-256 DB == Manifest (`86164ce398b6e3e0...`), BM25 `MAP@10=0.7590`, `nDCG@10=0.8466`; `semantic_environment_status="BLOCKED_ENV"` (`ChromaDB service unreachable`) | [`eval_results_p06.json`](../../../test-results/round-3/eval/eval_results_p06.json), [`eval_chart_p06.png`](../../../test-results/round-3/eval/eval_chart_p06.png) |
| CLI `evaluate/run_eval.py` khi DB drift cùng số lượng (`published=100`) | Sửa nội dung 1 bài trong DB mà giữ nguyên `published=100` | Chạy mặc định chặn với exit **1** (`CorpusAlignmentError`); chạy kèm `--allow-mismatch` xuất `corpus_db_alignment="MISMATCH"`, `verification_status="INVALID_MISMATCH"`, chỉ ra đúng ID lệch `0343f3ac-e6ea-5655-9792-423e58ef59a4` | [`eval-mismatch-diag/eval_results_p06.json`](../../../test-results/round-3/eval-mismatch-diag/eval_results_p06.json) |

> [!NOTE]
> **Về script cũ [`scripts/ops/verify_ops_unit.py`](../../../scripts/ops/verify_ops_unit.py):** Script P08 này chưa được chỉnh sửa ở Vòng 2 và Vòng 3. Sau khi `R01` / `R3-01` yêu cầu backup/restore fail-closed (`pg_dump` / `psql` thật và không dùng `--clean`), bước 9 (`test_backup_restore_cycle`) trong script đó không tương thích với việc chạy không cần DB hoặc restore đè lên cùng `DATABASE_URL`; CI và quy trình nghiệm thu hiện tại dùng [`tests/backend/ops/test_backup_restore.py`](../../../tests/backend/ops/test_backup_restore.py) (30/30 ops tests pass) và [`scripts/run_restore_drill.py`](../../../scripts/run_restore_drill.py) thay thế.

---

## 3. Danh Sách Regression Node ID Đã Đối Chiếu Verbatim (`pytest --collect-only` + JUnit XML)

Mọi node ID dưới đây đã được xác minh tồn tại nguyên văn và đạt trạng thái **PASSED** trong lần chạy cuối:

- **R3-01 & R3-08 (Ops, Fail-Closed Restore, Bootstrap & Hardening):**
  - `tests/backend/ops/test_backup_restore.py::test_full_postgresql_backup_restore_and_drill_round_trip`
  - `tests/backend/ops/test_backup_restore.py::test_restore_fails_on_invalid_sql_and_rolls_back_atomically`
  - `tests/security/test_bootstrap_postgres_lifecycle.py::TestLivePostgresBootstrapLifecycle::test_live_cli_create_rerun_rotate_and_negative_matrix`
  - `tests/security/test_runtime_security_hardening.py::TestCookieAndOriginSecurity::test_cookie_security_flags`
  - `tests/security/test_runtime_security_hardening.py::TestProductionErrorRedaction::test_production_unhandled_error_zero_leak`
- **R3-02 (Login Reservation Giữa Request Thành Công & In-Flight):**
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_concurrent_login_barrier_enforces_exact_admission_limit_before_verify`
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_login_reservation_crash_expiry_and_success_reset`
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_r3_02_success_preserves_inflight_target_reservations_and_enforces_limit`
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_r3_02_concurrent_successes_prior_failures_expiry_and_idempotency`
- **R3-03 (Tag Manager Clamping, Stale Search Guard & Mobile Responsive):**
  - `tests/frontend/public/test_round3_regressions.py::test_r3_03_delete_last_tag_on_page_2_clamps_to_page_1`
  - `tests/frontend/public/test_round3_regressions.py::test_r3_03_delete_only_remaining_tag_renders_clean_empty_state_without_loop`
  - `tests/frontend/public/test_round3_regressions.py::test_r3_03_edit_last_tag_on_page_2_out_of_filter_clamps_to_page_1`
  - `tests/frontend/public/test_round3_regressions.py::test_r3_03_stale_search_guard_error_retry_and_mobile_viewport`
- **R3-04 (Semantic Timeout Bounded Pool, Session Isolation & Readiness):**
  - `tests/backend/search/test_search_fallbacks.py::test_bm25_mode_fallback_to_ilike`
  - `tests/backend/search/test_search_fallbacks.py::test_r15_semantic_timeout_enforced_with_graceful_fallback`
  - `tests/backend/search/test_search_fallbacks.py::test_r3_04_semantic_timeout_caps_total_concurrency_holds_slot_until_exit_and_recovers`
  - `tests/backend/search/test_search_fallbacks.py::test_r3_04_search_endpoint_never_passes_request_session_across_threads`
  - `tests/backend/search/test_search_fallbacks.py::test_r3_04_semantic_source_url_resolves_on_caller_thread_without_db_leak`
  - `tests/backend/search/test_search_fallbacks.py::test_r3_04_readiness_probe_uses_bounded_executor_without_thread_leak`
  - `tests/backend/ops/test_health_readiness.py::test_readiness_probe_structure_and_fallback`
- **R3-05 (Evaluation Corpus-DB Parity & Guardrails):**
  - `tests/evaluate/test_run_eval.py::test_ext02_corpus_provenance_digest_and_generation_metadata`
  - `tests/evaluate/test_run_eval.py::test_r3_05_execute_ilike_unpacks_tuple_and_returns_ranked_hits`
  - `tests/evaluate/test_run_eval.py::test_r3_05_corpus_db_alignment_detects_swapped_ids_content_drift_and_tampered_manifest`
- **R3-06 (SQL ILIKE Fallback Pagination Past 1,000):**
  - `tests/backend/search/test_search_pagination.py::test_r3_06_ilike_fallback_paginates_past_1000_results_with_filters`
- **R3-07 (KaTeX Heading TOC Clean Extraction):**
  - `tests/frontend/public/test_round3_regressions.py::test_r3_07_math_headings_toc_no_duplication_slug_and_scroll`
  - `tests/frontend/public/test_round2_regressions.py::test_r11_katex_math_rendering_and_xss_protection`

---

## 4. Phân Tách Phần Chưa Chạy / Phụ Thuộc Môi Trường Ngoài

1. **ChromaDB & SentenceTransformer Real E2E (`BLOCKED_ENV`):** Máy test không có `data/vector` hoặc ChromaDB container/service đang lắng nghe; các regression semantic kiểm tra hợp đồng concurrency, timeout, fallback và resolution thông qua adapter có kiểm soát trong pytest, còn kết nối ChromaDB server + embedding weights thật cần kiểm chứng thêm khi bật `--profile semantic`.
2. **Docker Compose Runtime (`BLOCKED_ENV`):** Chưa chạy `docker compose -f docker-compose.prod.yml up` trong vòng này; mới kiểm chứng cấu hình tĩnh bằng `validate_compose_and_config.py`.
3. **Website Công Khai `https://folio-wiki.vercel.app/` (`LIVE_ACCEPTANCE: NOT_RUN`):** Không thực thi thao tác commit/push/deploy hay kiểm thử trên dữ liệu production live theo ràng buộc nhiệm vụ.
