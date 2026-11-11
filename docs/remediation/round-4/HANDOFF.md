# Folio — Tài Liệu Bàn Giao Khắc Phục Vòng 4 (Round 4 Handoff)

- **Ngày bàn giao:** `2026-11-10` (cập nhật follow-up sau review độc lập: `2026-11-11`)
- **Worktree sản phẩm:** `F:/dpl13.10/folio-audit-remediation`
- **Branch / Base (`HEAD`):** `codex/folio-audit-remediation-20261106` / `b659fe57a5f7c9bb7cfdb14cbf11813e7d512333` (working tree chưa commit giữ nguyên toàn bộ sửa chữa Vòng 2, Vòng 3, Vòng 4 và hai điểm follow-up)
- **Tài liệu Vòng 4 chính thức:** [STATUS.md](./STATUS.md) | [TEST-RESULTS.md](./TEST-RESULTS.md) | [RELEASE-RUNBOOK.md](./RELEASE-RUNBOOK.md)

---

## 1. Kết Luận Nhanh Cho Người Tiếp Nhận

1. **Những gì đã hoàn thành và kiểm chứng ở Vòng 4 & Follow-Up:**
   - **`R4-01` & P3 Follow-up (Hợp đồng env, nạp biến host & cấu hình container):** Mọi lệnh Compose dùng tường minh `--env-file .env.production`. Secret bắt buộc để rỗng trong template mẫu (`APP_SECRET=`, `POSTGRES_PASSWORD=`, `ADMIN_BOOTSTRAP_PASSWORD=`), fail-closed cả ở bước nội suy Compose (`:?`) lẫn `Settings.validate_production()`. Bọc ngoặc đơn `'...'` toàn bộ giá trị `HSTS_HEADER` và `ADMIN_BOOTSTRAP_DISPLAY_NAME` trong `.env.production.example`; Git Bash thật source file copy dummy exit `0`, `stderr == ""` và nạp đúng 100% hai biến; Compose v5.7.0 CLI render giữ nguyên giá trị.
   - **`R4-02` (Cutover storage không phá hủy & switch-back):** Tham số hóa 5 volume ngoài bằng `FOLIO_{PGDATA,INDEX,MEDIA,CHROMA,CERTS}_VOLUME`; đồng bộ `MEDIA_DIR=/app/data/media` và quyền `/app/data/...` (`10001:10001`) trong [`Dockerfile`](../../../Dockerfile); thêm `--index-storage-dir` / `--media-dir` + `get_media_storage_root()` trên [`scripts/ops/backup.py`](../../../scripts/ops/backup.py) và [`scripts/ops/restore.py`](../../../scripts/ops/restore.py). Diễn tập PostgreSQL 16.10 thật chứng minh restore V1 sang DB/storage mới giữ nguyên sentinel V2 cũ, cutover đọc V1 và switch-back đọc V2.
   - **`R4-03` & P2 Follow-up (Cấp phát & kiểm tra TLS trước khi bật Proxy):** Thêm `cert-init` và `cert-preflight` vào `docker-compose.prod.yml`; `proxy` bắt buộc đợi `cert-preflight: service_completed_successfully`. Cập nhật `scripts/ops/init_certs.py` xác thực toàn bộ các khối PEM X.509 trong bundle và kiểm tra nạp qua `ssl.SSLContext.load_cert_chain` từ staging tạm cô lập trước khi ghi đích. Từ chối bundle chứa non-leaf DER hỏng (như base64 `YWJj`) kể cả khi import `--force` (giữ nguyên SHA-256 cert/key cũ và OpenSSL vẫn nạp được cặp cũ) và từ chối trên `--check-only`. Import chuỗi 3 cert hợp lệ thành công và giữ nguyên toàn bộ bytes chain. Làm rõ trong tài liệu quy trình per-file atomic replace (không phải transaction nguyên tử cả cặp).
   - **`R4-04` & Follow-up Verification:** [`validate_compose_and_config.py`](../../../scripts/ops/validate_compose_and_config.py) đạt **12/12** checks; bộ kiểm thử trọng tâm `pytest tests/backend/ops tests/security -q` đạt **78/78 PASSED** trên PostgreSQL 16.10 cô lập (`test-results/round-4-followup/ops-security.xml`); standalone Docker Compose v5.7.0 CLI render pass; Git Bash env source probe pass; TLS fullchain probe pass. Toàn bộ artifact mới được lưu tại `test-results/round-4-followup/` (giữ nguyên `test-results/round-4/`).

2. **Những gì giữ nguyên & chưa chạy (`BLOCKED_ENV` / `NOT_RUN`):**
   - Toàn bộ sửa chữa Vòng 2 và Vòng 3 (login reservation, tag pagination clamp, bounded semantic pool, corpus content alignment, SQL >1.000, KaTeX TOC) được giữ nguyên vẹn; không sửa mã nguồn tại `F:/dpl13.10/WikiSearchEngine`, `.presentation-build/`, `docs/presentation/`, hay `fixtures/folio/documents.jsonl`.
   - Máy kiểm chứng không cài Docker daemon nên việc khởi động container thật (`up -d`, Nginx/Postgres/Worker/Chroma trên Docker daemon) là **`Docker/Nginx runtime: NOT_RUN`** (chỉ render config bằng Compose v5.7.0).
   - ChromaDB HTTP + ML model E2E là **`BLOCKED_ENV`** và triển khai trực tuyến Vercel/production là **`LIVE_ACCEPTANCE: NOT_RUN`**.

---

## 2. Danh Sách Thay Đổi Riêng Vòng 4 & Follow-Up (Trên Nền Working Tree Vòng 2 + Vòng 3)

- **Sửa mới / mở rộng:**
  - `.env.production.example`, `.gitignore`, `.dockerignore`
  - `Dockerfile`, `docker-compose.prod.yml`
  - `src/backend/core/config.py`
  - `scripts/ops/init_certs.py` (xác thực fullchain, staging loadability, OpenSSL load_cert_chain, per-file replace note)
  - `scripts/ops/backup.py`, `scripts/ops/restore.py`, `scripts/ops/validate_compose_and_config.py` (bổ sung shell quote check)
  - `tests/backend/ops/test_deployment_contracts.py` (mở rộng lên 12 test cases, gồm 4 test follow-up mới)
  - Đính chính runbook cũ: `docs/remediation/round-3/{RELEASE-RUNBOOK,HANDOFF}.md`, `docs/remediation/round-2/RELEASE-RUNBOOK.md`, `docs/remediation/2026-11-06/RELEASE-RUNBOOK.md`
  - Bộ tài liệu Round 4: `docs/remediation/round-4/{RELEASE-RUNBOOK,STATUS,TEST-RESULTS,HANDOFF}.md`
  - Artifact kiểm chứng (bỏ qua bởi `.gitignore`): `test-results/round-4/` (8 tệp gốc) và `test-results/round-4-followup/` (6 tệp mới).

## 3. Việc Cần Làm Tiếp Theo Trên Máy Chủ Có Docker & Khi Nghiệm Thu Live

1. **Rà soát và commit sạch trên `F:/dpl13.10/folio-audit-remediation`:**
   - Kiểm tra `git status` và `git diff` (không commit `.env.production`, `.env.restored`, `test-results/`, hay key/cert).
   - Chạy `pytest tests/frontend` một lượt trên CI/Linux (hoặc Ubuntu GitHub Actions CI khi push) để xác nhận trọn bộ backend + frontend xanh cùng lúc trên cùng cây commit.
2. **Xác minh thực tế Docker Compose trên máy có Docker CLI/daemon (mở khóa phần `BLOCKED_ENV` của Vòng 4):**
   ```bash
   # 1. Tạo .env.test tạm (không dùng secret production thật) để test fail-closed & render
   cp .env.production.example /tmp/.env.incomplete
   docker compose --env-file /tmp/.env.incomplete -f docker-compose.prod.yml config   # Kỳ vọng FAIL báo APP_SECRET

   cp .env.production.example .env.production && chmod 600 .env.production
   # Điền APP_SECRET, POSTGRES_PASSWORD, DOMAIN_NAME, CORS_ALLOWED_ORIGINS thật
   docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet

   # 2. Dựng DB + migrate + test cert-preflight chặn proxy khi thiếu cert
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d db
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migration
   # Kiểm tra proxy tự chặn nếu chạy 'up -d proxy' trước khi có cert; sau đó provision cert:
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-init
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-preflight
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

   # 3. Diễn tập cutover & switch-back theo Mục 6 của round-4/RELEASE-RUNBOOK.md
   ```
3. **Nghiệm thu Live (`LIVE_ACCEPTANCE`):**
   - Thực hiện theo checklist tại [Mục 7 của RELEASE-RUNBOOK.md](./RELEASE-RUNBOOK.md#7-triển-khai-vercel-serverless-sql-first--checklist-nghiệm-thu-live) trước khi xác nhận hoàn tất triển khai công khai.
