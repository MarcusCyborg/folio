# Folio — Kết Quả Kiểm Thử Xác Minh Vòng 4 (Round 4 Test Results)

- **Ngày thực thi:** `2026-11-10` (và bổ sung kiểm chứng follow-up sau review độc lập: `2026-11-11`)
- **Worktree sản phẩm:** `F:/dpl13.10/folio-audit-remediation`
- **Branch / Base (`HEAD`):** `codex/folio-audit-remediation-20261106` / `b659fe57a5f7c9bb7cfdb14cbf11813e7d512333`
- **Môi trường kiểm thử thực tế (sau khi đóng băng toàn bộ mã nguồn, Compose/Docker config, test và runbook):**
  - OS / Python: Windows, Python `3.10.11`, `pytest 9.2.0` (`F:/dpl13.10/WikiSearchEngine/env/Scripts/python.exe`)
  - PostgreSQL: **PostgreSQL 16.10** cô lập tạm thời trên `127.0.0.1:56790` (`POSTGRES_BIN_PATH=F:/dpl13.10/folio-live-runtime/pgsql/bin`, dùng `FOLIO_TEST_ADMIN_URL`, `TEST_DATABASE_URL`, `DATABASE_URL` động theo cụm tạm)
  - Lưu trữ cô lập: `INDEX_STORAGE_DIR` và `FOLIO_ARTIFACT_ROOT` đặt trong `$env:TEMP` để giữ nguyên cây mã nguồn
  - Trạng thái ngoài máy cục bộ: **Docker Compose CLI config render: `LOCAL_PASS` (bằng standalone `docker-compose.exe` v5.7.0 chính thức)**, **Docker/Nginx runtime: `NOT_RUN` (chưa dựng container daemon)**, **ChromaDB HTTP / ML model: `BLOCKED_ENV`**, **Website live (`https://folio-wiki.vercel.app/`): `LIVE_ACCEPTANCE: NOT_RUN`**

> [!NOTE]
> **Không gộp số liệu kiểm thử Round 3 vào Round 4:**
> Mọi con số dưới đây là **kết quả chạy mới hoàn toàn của Vòng 4** trên bản sửa đổi đã đóng băng. Round 4 chỉ sửa cấu hình triển khai, script ops, `Settings.validate_production()`, test ops và runbook/tài liệu (không sửa mã nguồn frontend `.js`/`.css`/`.html`); 92 bài Playwright Chromium của Vòng 3 được tham chiếu như baseline tiền-Vòng-4 tại [`docs/remediation/round-3/TEST-RESULTS.md`](../round-3/TEST-RESULTS.md), **không** cộng vào tổng kết quả Vòng 4.

---

## 1. Tổng Hợp Bộ Kiểm Thử Pytest Vòng 4 (JUnit XML Độc Lập)

Trích trực tiếp từ hai tệp JUnit XML trong `test-results/round-4/` sau khi đóng băng mã nguồn:

| Bộ kiểm thử | Lệnh thực thi (rút gọn biến kết nối) | Total | Passed | Failed | Errors | Skipped | Thời lượng | Trạng thái | Nguồn XML |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| **Artifact Isolation (`--noconftest`)** | `pytest --noconftest tests/safety/test_artifact_isolation.py -v --junitxml=test-results/round-4/artifact-junit.xml` | 8 | **8** | 0 | 0 | 0 | 4.85s | `LOCAL_PASS` | [`artifact-junit.xml`](../../../test-results/round-4/artifact-junit.xml) |
| **Safety + Security + Backend (incl. Ops/R4) + Evaluate** | `pytest tests/safety tests/security tests/backend tests/evaluate --ignore=tests/safety/test_artifact_isolation.py -q --junitxml=test-results/round-4/backend-junit.xml` | 396 | **396** | 0 | 0 | 0 | 640.35s | `LOCAL_PASS` | [`backend-junit.xml`](../../../test-results/round-4/backend-junit.xml) |
| **Tổng cộng Vòng 4 (2 JUnit XML hợp nhất)** | Toàn bộ backend, security, safety, ops/deployment & evaluate không trùng lặp | **404** | **404** | **0** | **0** | **0** | **645.20s** | `LOCAL_PASS` | 2 JUnit XML |

### Phân rã theo phân hệ (trích từ `backend-junit.xml` & `artifact-junit.xml`)

- `tests.safety.test_artifact_isolation` (`artifact-junit.xml`): **8 passed**
- `tests.safety` (ngoại trừ `test_artifact_isolation`, `backend-junit.xml`): **82 passed**
  - `tests.safety.test_browser_isolation_order`: 3
  - `tests.safety.test_ci_database_configuration`: 8
  - `tests.safety.test_db_lifecycle` (trực tiếp trên PG 16.10 qua `FOLIO_TEST_ADMIN_URL`): 3
  - `tests.safety.test_pure_rate_limit`: 15
  - `tests.safety.test_pure_safety`: 50
  - `tests.safety.test_seed_idempotency_asserts`: 3
- `tests.security`: **36 passed**
  - `tests.security.test_bootstrap_postgres_lifecycle` (CLI trên PG 16.10): 1
  - `tests.security.test_bootstrap_security`: 19
  - `tests.security.test_runtime_security_hardening`: 8
  - `tests.security.test_startup_subprocess`: 8
- `tests.backend.ops`: **38 passed** (gồm **30** test ops/backup/restore/worker/health sẵn có + **8** test mới trong [`tests/backend/ops/test_deployment_contracts.py`](../../../tests/backend/ops/test_deployment_contracts.py))
- `tests.backend.admin`: **31 passed**
- `tests.backend.foundation`: **64 passed**
- `tests.backend.integration`: **1 passed**
- `tests.backend.library`: **20 passed**
- `tests.backend.search`: **85 passed**
- `tests.backend.search_index`: **22 passed**
- `tests.evaluate`: **17 passed** (`test_eval_metrics`: 6 + `test_run_eval`: 11)

---

## 2. Danh Sách Test Hợp Đồng Triển Khai Mới Vòng 4 (`test_deployment_contracts.py`)

Toàn bộ 8 node ID dưới đây đã chạy và đạt **PASSED** trong `backend-junit.xml`:

| Hạng mục | Node ID Verbatim | Thời lượng | Nội dung đã kiểm chứng thực tế |
|---|---|---|---|
| `R4-01` | `tests/backend/ops/test_deployment_contracts.py::TestR401EnvContract::test_compose_interpolation_and_live_subprocess_honor_non_default_env_file` | 4.188s | Nội suy `.env.production.example` (giá trị non-default: `SEMANTIC_EXECUTOR_WORKERS=4`, `SEMANTIC_MAX_PENDING=6`, `SEARCH_TIMEOUT_SECONDS=11.5`, `SEARCH_CONTEXT_TTL_MINUTES=27`, `RATE_LIMIT_ENABLED=false`) qua bộ suy diễn Compose đệ quy (hoặc `docker compose config` khi có Docker), sau đó khởi chạy subprocess Python cô lập với `TestClient(app)` chứng minh `Settings` và `_get_semantic_executor_state()` áp dụng đúng cấu hình container. |
| `R4-01` | `tests/backend/ops/test_deployment_contracts.py::TestR401EnvContract::test_missing_or_placeholder_secrets_fail_closed` | 7.896s | Bản copy nguyên văn `.env.production.example` (thiếu `APP_SECRET` / `POSTGRES_PASSWORD`) lỗi rõ ràng tại bước nội suy `${VAR:?...}`; `APP_SECRET` rỗng hoặc `replace_with...` bị `Settings.validate_production()` từ chối ở `APP_ENV=production`. |
| `R4-01` | `tests/backend/ops/test_deployment_contracts.py::TestR401EnvContract::test_host_python_cli_does_not_auto_load_dotenv_production` | 0.272s | Chứng minh Python CLI trên host không tự đọc `.env.production` ở thư mục làm việc (`cwd`), xác thực lý do runbook bắt buộc export hoặc chạy trong service `ops`. |
| `R4-03` | `tests/backend/ops/test_deployment_contracts.py::TestR403TlsProvisioningCli::test_empty_and_partial_cert_volume_fail_closed_and_preserve_existing` | 1.407s | Subprocess `scripts/ops/init_certs.py` thực thi thực tế: volume rỗng fail preflight; trạng thái thiếu 1 tệp (`folio.crt` không có `folio.key` hoặc ngược lại) từ chối và giữ nguyên SHA-256 tệp hiện có. |
| `R4-03` | `tests/backend/ops/test_deployment_contracts.py::TestR403TlsProvisioningCli::test_self_signed_init_idempotency_domain_preflight_and_ca_import_cli` | 6.192s | Sinh self-signed qua `CERT_DIR`, chạy `--check-only --expected-domain` (pass đúng domain, fail domain sai), xác minh chạy lại không `--force` giữ nguyên SHA-256, từ chối CA cert hết hạn / sai domain không chạm cert đang có, từ chối ghi đè nếu thiếu `--force`, và import thành công leaf+CA chain khi có `--force`. |
| `R4-02` | `tests/backend/ops/test_deployment_contracts.py::TestR402StorageCutoverAndSwitchBack::test_compose_cutover_volumes_switch_all_storage_consumers_together` | 0.178s | Nội suy `docker-compose.prod.yml` khi gán `FOLIO_INDEX_VOLUME` / `FOLIO_MEDIA_VOLUME` / `DATABASE_URL` mới chứng minh cả `web`, `worker`, `migration`, `ops` chuyển đồng bộ sang volume & DB mới mà không sửa bản baseline. |
| `R4-02` | `tests/backend/ops/test_deployment_contracts.py::TestR402StorageCutoverAndSwitchBack::test_restore_post_migration_escapes_percent_encoded_password` | 0.007s | Chứng minh `run_post_restore_migrations()` escape `%` -> `%%` trong `sqlalchemy.url` đối với mật khẩu đã URL-encode (`p%40ss%25word`). |
| `R4-02` | `tests/backend/ops/test_deployment_contracts.py::TestR402StorageCutoverAndSwitchBack::test_real_pg16_restore_cutover_and_switch_back_with_distinct_sentinels` | 46.773s | Diễn tập end-to-end trên **PostgreSQL 16.10** + storage sentinel V1 vs V2: sao lưu V1 -> sửa dữ liệu sang V2 -> chạy CLI `scripts/ops/restore.py --index-storage-dir ... --media-dir ...` khôi phục V1 vào DB mới + storage mới -> chứng minh storage V2 cũ nguyên vẹn -> boot subprocess `TestClient(app)` cutover đọc đúng generation V1 + media V1 -> boot subprocess switch-back đọc lại đúng generation V2 + media V2. |

---

## 3. Kiểm Chứng Tĩnh, Dependency & CLI Thực Tế Trên Mã Nguồn Đóng Băng

| Công cụ / Lệnh | Kết quả thực tế | Bằng chứng lưu giữ |
|---|---|---|
| `python scripts/ops/validate_compose_and_config.py` | **12/12 checks PASSED** (exit `0`), phát hiện chính xác Docker CLI vắng mặt (`BLOCKED_ENV`) | [`static-validation.txt`](../../../test-results/round-4/static-validation.txt) |
| `python -m pip check` | `No broken requirements found.` (exit `0`) | [`static-validation.txt`](../../../test-results/round-4/static-validation.txt) |
| Kiểm tra LF tất cả `*.sh` | **0** tệp chứa CRLF (`ShellCRLFCount: 0`) | [`git-fingerprint.txt`](../../../test-results/round-4/git-fingerprint.txt) |
| `python scripts/verify_seed_idempotency.py` | Exit `0` trên PG 16.10: `{"dialect": "postgresql", "counts": [5, 100, 3, 6, 123], "preserved_ids": 103, "preserved_edits": true}` | [`r4-seed-idempotency.txt`](../../../test-results/round-4/r4-seed-idempotency.txt) |
| `python scripts/run_restore_drill.py --target-db-name folio_restore_drill_round4_final` | Exit `0` trên PG 16.10: `"status": "passed"`, parity 15 counts (`documents_total: 103`) + 6 SHA-256 digests, `has_open_report_partial_unique_index: true`, `index_recovery.valid: true`, `smoke_test.search_smoke_test.status: "passed"` | [`r4-drill-report.json`](../../../test-results/round-4/r4-drill-report.json) |
| `python scripts/ops/restore.py --archive ... --verify-only` | Exit `0`: `"status": "verified_offline"`, `manifest_alembic_head: "20261106_report_open_unique"`, `database_dump_bytes: 3623110` | [`r4-verify-only.json`](../../../test-results/round-4/r4-verify-only.json) |
| `python scripts/ops/init_certs.py` + `--check-only --expected-domain r4.folio.test` | Exit `0`: sinh self-signed cert/key trong `CERT_DIR` tạm và thông qua preflight SAN khớp (`b39c4eaa...`) | [`r4-tls-cli-check.json`](../../../test-results/round-4/r4-tls-cli-check.json) |
| Kiểm tra rò rỉ thông tin nhạy cảm trong artifact | Đã quét toàn bộ thư mục `test-results/round-4/`: **0** mật khẩu/credential xuất hiện ở dạng rõ | Kiểm tra trước khi bàn giao |

---

## 4. Ranh Giới Chưa Chạy Do Môi Trường (`BLOCKED_ENV` / `NOT_RUN`)

1. **Docker Compose Render vs Container Runtime:** Đã dùng standalone Docker Compose v5.7.0 chính thức kiểm chứng config render (baseline, cutover, empty secrets fail-closed). Khởi động container thật (`up -d`, Nginx/Postgres/Worker/Chroma trên Docker daemon) là **`Docker/Nginx runtime: NOT_RUN`** (chưa thực hiện kiểm tra container sống cục bộ).
2. **ChromaDB Server & SentenceTransformer Real E2E:** **`BLOCKED_ENV`** (chưa khởi chạy HTTP Chroma server hoặc vector store).
3. **Website Công Khai (`https://folio-wiki.vercel.app/`) & Git Operations:** **`LIVE_ACCEPTANCE: NOT_RUN`** — không tự commit, push, merge hay deploy Vercel.

---

## 5. Kết Quả Kiểm Chứng Follow-up Sau Review Round 4 (11/11/2026)

Thực thi độc lập trên PostgreSQL 16.10 tạm cô lập, không ghi đè thư mục `test-results/round-4/`. Toàn bộ artifact mới được lưu tại `test-results/round-4-followup/`:

| Kiểm tra / Hạng mục | Lệnh & Công cụ thực tế | Kết quả thực tế | Artifact lưu giữ |
|---|---|---|---|
| **Targeted Ops & Security Suite** | `pytest tests/backend/ops tests/security -q --junitxml=test-results/round-4-followup/ops-security.xml` | **78 passed, 0 failed, 0 errors, 0 skipped** (186.87s trên PG 16.10) | [`ops-security.xml`](../../../test-results/round-4-followup/ops-security.xml), [`ops-security-log.txt`](../../../test-results/round-4-followup/ops-security-log.txt) |
| **Static Checks (gồm shell quote check mới)** | `python scripts/ops/validate_compose_and_config.py` | **12/12 static checks PASSED** (exit `0`) | [`static-validation.txt`](../../../test-results/round-4-followup/static-validation.txt) |
| **Compose v5.7.0 CLI Render Probe** | `docker-compose.exe config --format json` (v5.7.0 chính thức với dummy env) | Render thành công baseline & cutover, empty secrets bị từ chối; giữ đúng `HSTS_HEADER` và `ADMIN_BOOTSTRAP_DISPLAY_NAME` | [`compose-render-probe.json`](../../../test-results/round-4-followup/compose-render-probe.json) |
| **Git Bash Env Source Probe** | `C:\Program Files\Git\bin\bash.exe -c "set -a && source ... && set +a"` | Exit `0`, `stderr: ""`, nạp đúng `$HSTS_HEADER` (kèm dấu nháy kép bên trong) và `$ADMIN_BOOTSTRAP_DISPLAY_NAME` (kèm khoảng trắng); staging disable HSTS nạp đúng | [`host-env-source-probe.json`](../../../test-results/round-4-followup/host-env-source-probe.json) |
| **TLS Fullchain & Staging Probe** | Probe độc lập kiểm tra bundle leaf + DER `YWJj` hỏng & chuỗi 3 chứng chỉ hợp lệ | Từ chối bundle hỏng trước khi ghi đích; `--force` giữ nguyên hash cert/key cũ và OpenSSL vẫn nạp được cặp cũ; `--check-only` từ chối; chuỗi 3 cert hợp lệ nạp thành công qua OpenSSL và giữ nguyên bytes | [`tls-fullchain-probe.json`](../../../test-results/round-4-followup/tls-fullchain-probe.json) |

### 4 test hợp đồng triển khai mới bổ sung trong `test_deployment_contracts.py` (tổng cộng 12/12 test cases pass):

1. `test_env_production_template_compatible_with_bash_source_and_compose`: Đối chiếu bản sao template điền dummy secrets qua `dotenv_values`, internal parser, Compose interpolation, và Git Bash `source` thật; xác nhận `$HSTS_HEADER` và `$ADMIN_BOOTSTRAP_DISPLAY_NAME` nạp chính xác, 0 command-not-found error, và staging disable HSTS nạp đúng.
2. `test_fullchain_with_malformed_non_leaf_der_rejected_and_preserves_existing_on_force`: Cài đặt cặp hợp lệ trước, import bundle leaf tốt + khối base64 `YWJj` (DER hỏng) kèm `--force`: import bị từ chối trước khi chạm đích, SHA-256 cert/key cũ không đổi, `SSLContext.load_cert_chain` vẫn nạp được cặp cũ. Thư mục đích trống cũng không bị tạo file.
3. `test_check_only_rejects_corrupted_or_truncated_non_leaf_fullchain`: `--check-only` từ chối fullchain chứa non-leaf DER `YWJj`, truncated PEM (thiếu END marker), hoặc non-cert PEM block kể cả khi leaf hợp lệ và đúng domain/key.
4. `test_valid_multi_cert_fullchain_imports_preserves_bytes_and_loads_in_openssl`: Tạo chuỗi 3 chứng chỉ (leaf -> intermediate CA -> root CA) với CA riêng không nằm trong OS trust store; import thành công, giữ nguyên 100% bytes, `--check-only` pass, và `SSLContext.load_cert_chain` nạp thành công.
