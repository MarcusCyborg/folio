# Folio — Kết Quả Kiểm Thử Xác Minh Vòng 2 (Round 2 Test Results)

- **Ngày thực thi:** `2026-11-10`
- **Branch / Base:** `codex/folio-audit-remediation-20261106` (descendant of `b659fe57a5f7c9bb7cfdb14cbf11813e7d512333`, trước khi commit các thay đổi Vòng 2)
- **Môi trường kiểm thử thực tế:**
  - OS / Runtime: Windows, Python `3.10.11`, `pytest 9.2.0`
  - Cơ sở dữ liệu: **PostgreSQL 16.10** thực tế (`127.0.0.1:55510`, `POSTGRES_BIN_PATH=F:\dpl13.10\folio-live-runtime\pgsql\bin`)
  - Trình duyệt E2E: **Playwright Chromium 153.0.8010.12**
  - Trạng thái triển khai live: **`DEPLOYMENT_PENDING`** (không push, merge hay chạm môi trường Vercel/production)

---

## 1. Tổng hợp kết quả chạy toàn bộ bộ kiểm thử (Full Suite Runs)

Mọi số liệu dưới đây được trích trực tiếp từ tệp báo cáo **JUnit XML** xuất ra trong `test-results/round-2/`:

| Bộ kiểm thử | Lệnh thực thi | Collected / Total | Passed | Failed | Skipped | Thời lượng | Trạng thái | Nguồn bằng chứng |
|---|---|---:|---:|---:|---:|---:|---|---|
| **Artifact Isolation (Standalone)** | `pytest --noconftest tests/safety/test_artifact_isolation.py -v` | 8 | 8 | 0 | 0 | 1.67s | `LOCAL_PASS` | Console output |
| **Backend + Safety + Security + Evaluate** | `pytest tests/safety tests/security tests/backend tests/evaluate --junitxml=test-results/round-2/backend-junit.xml -q` | 387 | **386** | **0** | **1** | 232.80s | `LOCAL_PASS` | `test-results/round-2/backend-junit.xml` |
| **Frontend Playwright E2E** | `pytest tests/frontend --junitxml=test-results/round-2/frontend-junit.xml -q` | 87 | **87** | **0** | **0** | 673.29s | `LOCAL_PASS` | `test-results/round-2/frontend-junit.xml` |
| **Tổng hợp hai suite JUnit hợp nhất** | `backend-junit.xml` + `frontend-junit.xml` | **474** | **473** | **0** | **1** | 906.09s | `LOCAL_PASS` | JUnit XML artifacts |

> [!NOTE]
> **Chi tiết 1 mục `skipped` duy nhất trong 474 tests:**
> - Node ID: `tests/backend/foundation/test_wiki_content.py::test_spider_removes_edit_controls_before_markdown_conversion`
> - Lý do: `could not import 'scrapy': No module named 'scrapy'` (`pytest.importorskip("scrapy")` vì môi trường kiểm thử cục bộ không cài package `scrapy` tùy chọn dành riêng cho crawler offline). Toàn bộ 473 bài test còn lại đều chạy thật và **Pass 100% (0 Failed, 0 Errors)**.

---

## 2. Phân rã số lượng test theo phân hệ (trích trực tiếp từ JUnit XML)

### 2.1 Backend, Safety, Security & Evaluate (`backend-junit.xml`)

| Phân hệ (`classname` prefix) | Total | Passed | Skipped | Failed |
|---|---:|---:|---:|---:|
| `tests/safety` | 90 | 90 | 0 | 0 |
| `tests/security` | 36 | 36 | 0 | 0 |
| `tests/backend/admin` | 31 | 31 | 0 | 0 |
| `tests/backend/foundation` | 62 | 61 | 1 (`scrapy`) | 0 |
| `tests/backend/integration` | 1 | 1 | 0 | 0 |
| `tests/backend/library` | 20 | 20 | 0 | 0 |
| `tests/backend/ops` | 30 | 30 | 0 | 0 |
| `tests/backend/search` | 80 | 80 | 0 | 0 |
| `tests/backend/search_index` | 22 | 22 | 0 | 0 |
| `tests/evaluate` | 15 | 15 | 0 | 0 |
| **Tổng cộng Backend/Safety/Security/Evaluate** | **387** | **386** | **1** | **0** |

### 2.2 Frontend Playwright E2E (`frontend-junit.xml`)

| Phân hệ | Total | Passed | Skipped | Failed |
|---|---:|---:|---:|---:|
| `tests/frontend/admin` | 11 | 11 | 0 | 0 |
| `tests/frontend/public` | 76 | 76 | 0 | 0 |
| **Tổng cộng Frontend Playwright** | **87** | **87** | **0** | **0** |

---

## 3. Kiểm chứng ổn định riêng các bài Flaky trước đây (Repeat Runs)

| Bài kiểm thử | Kết quả sau sửa | Số lần chạy lặp liên tiếp | Thời gian mỗi lượt |
|---|---|---:|---|
| `tests/frontend/public/test_search_navigation_state.py::test_search_api_connected_on_query` | `3 / 3 PASSED` | 3 lượt | 10.53s – 10.75s |
| `tests/frontend/public/test_motion_and_lifecycle.py::test_toc_smooth_scroll_and_heading_highlight` | `3 / 3 PASSED` | 3 lượt | 11.02s – 13.24s |

---

## 4. Danh sách Regression Tests Vòng 2 đã kiểm chứng thật (Verified Node IDs)

Mỗi node ID dưới đây đã được xác minh tồn tại qua `pytest --collect-only` và thực thi pass trong báo cáo JUnit XML:

- **R01 & R18 (`OPS-04` Fail-Closed Backup/Restore & Drill):**
  - `tests/backend/ops/test_backup_restore.py::test_backup_fails_when_pg_dump_missing`
  - `tests/backend/ops/test_backup_restore.py::test_backup_fails_when_pg_dump_nonzero`
  - `tests/backend/ops/test_backup_restore.py::test_backup_fails_when_pg_dump_timeout`
  - `tests/backend/ops/test_backup_restore.py::test_backup_fails_when_db_offline_and_redacts_secrets`
  - `tests/backend/ops/test_backup_restore.py::test_restore_fails_when_psql_missing`
  - `tests/backend/ops/test_backup_restore.py::test_restore_detects_missing_file`
  - `tests/backend/ops/test_backup_restore.py::test_restore_fails_when_target_db_offline`
  - `tests/backend/ops/test_backup_restore.py::test_restore_verifies_checksum_tampering`
  - `tests/backend/ops/test_backup_restore.py::test_restore_fails_on_invalid_sql_and_rolls_back_atomically`
  - `tests/backend/ops/test_backup_restore.py::test_restore_fails_when_smoke_test_fails`
  - `tests/backend/ops/test_backup_restore.py::test_full_postgresql_backup_restore_and_drill_round_trip`
- **R03 (`AUTH-01` Atomic Login Admission Before Argon2):**
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_concurrent_login_barrier_enforces_exact_admission_limit_before_verify`
  - `tests/backend/foundation/test_shared_rate_limit_concurrency.py::test_login_reservation_crash_expiry_and_success_reset`
- **R04 (`F03` Catalog Sort Options):**
  - `tests/backend/library/test_library_api.py::test_r04_catalog_sort_options_order_correctly`
- **R05 (`B08` Concurrent Report Open Unique Migration):**
  - `tests/backend/admin/test_moderation_flow.py::test_r05_report_open_unique_migration_handles_equal_timestamps_and_concurrent_reports`
- **R06 (`B04` Unknown Taxonomy Validation Order & SearchContext):**
  - `tests/backend/search/test_search_filters_api.py::test_r06_unknown_taxonomy_validates_all_params_and_persists_pagination_context`
- **R07 & B07 (`admin_list_tags` Filter Count & UI Pagination > 100):**
  - `tests/backend/admin/test_taxonomy_lifecycle.py::test_b07_admin_tags_filtered_total_and_pagination_beyond_100`
  - `tests/frontend/public/test_round2_regressions.py::test_r07_r08_taxonomy_mobile_layout_and_pagination_over_100_tags`
- **R08 (`F07` Taxonomy Responsive Grid Geometry):**
  - `tests/frontend/public/test_round2_regressions.py::test_r07_r08_taxonomy_mobile_layout_and_pagination_over_100_tags`
  - Ảnh chụp thực tế: `test-results/round-2/r08-taxonomy-mobile-360.png` (`scrollWidth <= innerWidth`, không cắt nút ở `360x800`, `390x844`, `768x1024`, `1440x900`)
- **R09 (`F11` Taxonomy Load Error Alert & Retry):**
  - `tests/frontend/public/test_round2_regressions.py::test_r09_taxonomy_load_error_shows_retry_and_recovers`
- **R10 (`F10` Mention Autocomplete Rapid-Input Race):**
  - `tests/frontend/public/test_round2_regressions.py::test_r10_mention_autocomplete_rapid_input_prevents_stale_selection`
- **R11 (`F08` Self-Hosted KaTeX Rendering & XSS Protection):**
  - `tests/backend/foundation/test_wiki_content.py::test_r11_math_normalization_nested_braces_code_preservation_and_xss_safety`
  - `tests/frontend/public/test_round2_regressions.py::test_r11_katex_math_rendering_and_xss_protection`
  - Ảnh chụp thực tế: `test-results/round-2/r11-katex-math-detail.png` (render công thức `.katex`, không gọi CDN ngoài, giữ nguyên fenced code, XSS `window.__xssFired === false`)
- **R12 (`B03` Atomic `source_url` 409 Handling on PATCH):**
  - `tests/backend/admin/test_document_lifecycle.py::test_r12_patch_source_url_conflict_with_tags_and_soft_deleted_returns_409_atomically`
- **R13 (`AUTH-02`/`AUTH-03` Multi-Tab Session Sync & Immediate Deactivation Block):**
  - `tests/frontend/public/test_round2_regressions.py::test_r13_multi_tab_session_synchronization`
  - `tests/backend/admin/test_governance_and_last_admin.py::test_r13_deactivating_user_blocks_immediately_and_prevents_resuscitation`
- **R14 (`EXT-03` Hybrid Fallback Pagination Beyond 100):**
  - `tests/backend/search/test_search_fallbacks.py::test_r14_hybrid_ilike_fallback_reports_true_total_and_paginates_past_100`
- **R15 (`EXT-04` & `OPS-06` Bounded Semantic Timeout & Lightweight Readiness):**
  - `tests/backend/search/test_search_fallbacks.py::test_r15_semantic_timeout_enforced_with_graceful_fallback`
  - `tests/backend/ops/test_health_readiness.py::test_readiness_probe_structure_and_fallback`
- **R16 (`OPS-07` Entrypoint Log Secret Redaction):**
  - `tests/backend/ops/test_worker_daemon.py::test_r16_docker_entrypoints_do_not_echo_database_url`
- **EXT-01 (Vector Lifecycle Sync & HTTP Chroma Config):**
  - `tests/backend/ops/test_worker_daemon.py::test_ext01_worker_syncs_semantic_vector_lifecycle_on_publish_update_unpublish_delete`
- **EXT-02 (Evaluation Corpus Provenance & Index Generation Verification):**
  - `tests/evaluate/test_run_eval.py::test_ext02_corpus_provenance_digest_and_generation_metadata`

---

## 5. Kiểm chứng CLI thực tế cho R17 (`scripts/bootstrap_admin.py`) trên PostgreSQL 16 cô lập

Đã khởi tạo database tạm `folio_bootstrap_drill` trên PostgreSQL 16 cục bộ, chạy `python -m alembic upgrade head` (áp dụng đủ 6 revision tới `20261106_report_open_unique`), rồi thực thi trực tiếp đúng cờ được ghi trong [`RELEASE-RUNBOOK.md`](./RELEASE-RUNBOOK.md):

1. Tạo tài khoản ban đầu với `--email "ops-admin@folio.example.com" --username "opsadmin" --display-name "Folio Operations Lead" --non-interactive` + `ADMIN_BOOTSTRAP_PASSWORD`: **exit `0`** (`[SUCCESS] Initial Super Admin account 'opsadmin' provisioned`).
2. Chạy lặp không `--rotate`: **exit `2`** (`ALREADY_EXISTS`, không ghi đè mật khẩu).
3. Chạy với `--rotate`: **exit `0`** (`password rotated`, thu hồi phiên cũ).
4. Sau khi kiểm chứng đã `DROP DATABASE folio_bootstrap_drill`.

---

## 6. Phần chưa triển khai lên Live (`DEPLOYMENT_PENDING`)

- Chưa push commit Vòng 2 lên GitHub remote (`codex/folio-audit-remediation-20261106`) và chưa merge vào `main`.
- Chưa chạy GitHub Actions CI workflow trên bản sửa Vòng 2.
- Chưa deploy lên Vercel hay chạy `alembic upgrade head` / `scripts/bootstrap_admin.py` trên database production live.
