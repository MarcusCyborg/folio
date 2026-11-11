# Folio — Hướng Dẫn Phát Hành, Diễn Tập Staging & Khôi Phục Thảm Họa (Round 3 Operational Runbook — ĐÃ CẬP NHẬT SANG VÒNG 4)

> [!CAUTION]
> **TÀI LIỆU ĐÃ ĐƯỢC THAY THẾ TỪ VÒNG 4 (`R4-01`, `R4-02`, `R4-03`, `R4-04`, 10/11/2026):**
> Bản Vòng 3 này từng thiếu cờ `--env-file .env.production` cho các lệnh Docker Compose, thiếu quy trình cấp phát TLS vào volume `folio-proxy-certs` trước khi bật `proxy`, và hướng dẫn cutover bằng `export INDEX_STORAGE_DIR` trên host không đổi được mount trong Compose.
> **Vui lòng sử dụng tài liệu vận hành chính thức mới nhất tại [`docs/remediation/round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md).** Các ví dụ lệnh bên dưới đã được đính chính lại cho nhất quán để không tồn tại bộ lệnh mâu thuẫn trong repo.

> [!IMPORTANT]
> **Ghi chú lịch sử Vòng 3 (10/11/2026):** Tài liệu này thay thế [`docs/remediation/round-2/RELEASE-RUNBOOK.md`](../round-2/RELEASE-RUNBOOK.md) và [`docs/remediation/2026-11-06/RELEASE-RUNBOOK.md`](../2026-11-06/RELEASE-RUNBOOK.md). Trạng thái triển khai online hiện tại vẫn là **`LIVE_ACCEPTANCE: NOT_RUN`** (chưa push, merge hay chạm môi trường Vercel/production live).

---

## 1. Kiến Trúc Triển Khai & Ma Trận Môi Trường Thực Tế (`R3-08`)

Folio hỗ trợ hai mô hình triển khai được định nghĩa trực tiếp trong mã nguồn:

| Thành phần / Đặc tính | Mô hình A: Persistent Container / VM ([`docker-compose.prod.yml`](../../../docker-compose.prod.yml)) | Mô hình B: Serverless Vercel ([`vercel.json`](../../../vercel.json) — SQL-First Mode) |
| :--- | :--- | :--- |
| **Web Runtime / Entrypoint** | `folio-web` chạy [`entrypoint-web.sh`](../../../docker/entrypoints/entrypoint-web.sh) -> `uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'` (chỉ đứng sau Nginx/Caddy trong mạng nội bộ) | Serverless function trỏ trực tiếp tới [`src/backend/main.py`](../../../src/backend/main.py) kèm `"includeFiles": "src/frontend/**"` (lưu ý: repo **không** dùng `api/index.py`) |
| **PostgreSQL 16** | `folio-postgres` (`postgres:16-alpine` + volume `folio-pgdata`) trên `backend-net` (`internal: true`) | Managed PostgreSQL (Neon / Supabase / RDS) qua biến `DATABASE_URL` |
| **Migration Runner** | Dịch vụ one-shot `migration` (`profiles: ["tools"]`) chạy [`entrypoint-migrate.sh`](../../../docker/entrypoints/entrypoint-migrate.sh): `alembic upgrade head`, bootstrap admin tùy chọn, build index khởi đầu nếu trống | Chạy thủ công từ CI/bastion có kết nối DB trước khi chuyển traffic: `python -m alembic upgrade head` |
| **Background Worker** | `folio-worker` chạy [`entrypoint-worker.sh`](../../../docker/entrypoints/entrypoint-worker.sh) -> `python3 scripts/run_worker.py` (không tự chạy Alembic) | **Không có daemon nền** trong serverless function |
| **Lexical Search (BM25)** | Đầy đủ qua volume chung `folio-index-data` gắn `/app/data/search_index` (`INDEX_STORAGE_DIR=/app/data/search_index/generations`) | Tự suy giảm an toàn sang **PostgreSQL ILIKE SQL-First** (`engine_used: "ilike_fallback"`, `is_degraded: true`) nếu không có generation index trên đĩa; phân trang vượt 1.000 bản ghi (`R3-06`) |
| **Semantic Vector Search** | Tùy chọn qua `--profile semantic` (`folio-chroma`, `chromadb/chroma:0.5.20`, `CHROMA_HOST=chroma`, `CHROMA_PORT=8000`) | Tắt mặc định (`is_degraded: true`), trừ khi cấu hình HTTP Chroma bên ngoài qua `CHROMA_HOST` / `CHROMA_PORT`; executor tìm kiếm và readiness probe bị chặn tải đồng thời qua pool giới hạn (`R3-04`) |
| **Reverse Proxy & TLS** | Chỉ `proxy` (`folio-proxy`) mở cổng host (`PROXY_HTTP_PORT`, `PROXY_HTTPS_PORT`); template Nginx ([`default.conf.template`](../../../docker/proxy/templates/default.conf.template)) và Caddy ([`Caddyfile`](../../../docker/proxy/Caddyfile)) | Edge HTTPS + CDN do Vercel quản lý |
| **PostgreSQL Client Tools** | Đã cài `postgresql-client-16` trong [`Dockerfile`](../../../Dockerfile) (`pg_dump` / `psql` khớp PostgreSQL 16) | Chạy backup/restore/drill từ host/runner có `postgresql-client-16` hoặc đặt `POSTGRES_BIN_PATH` |

---

## 2. Biến Môi Trường Đã Đối Chiếu Mã Nguồn ([`config.py`](../../../src/backend/core/config.py) & [`.env.production.example`](../../../.env.production.example))

```ini
# Bắt buộc cho Staging / Production
APP_ENV=production
APP_SECRET=<chuoi-ngau-nhien-it-nhat-32-ky-tu-toi-thieu-10-ky-tu-khac-nhau>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<pg-host>:5432/<db_name>
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
CORS_ALLOWED_ORIGINS=https://folio-wiki.vercel.app,https://your-domain.example
TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8

# Rate Limiting, Timeout & Concurrency (R3-04)
RATE_LIMIT_ENABLED=true
SEARCH_TIMEOUT_SECONDS=5.0
SEARCH_CONTEXT_TTL_MINUTES=15
SEMANTIC_EXECUTOR_WORKERS=2
SEMANTIC_MAX_PENDING=2

# Lưu trữ chỉ mục & Legacy search
INDEX_STORAGE_DIR=/app/data/search_index/generations
ENABLE_LEGACY_SEARCH=false

# Tùy chọn Semantic Vector Search
CHROMA_PATH=/app/data/vector
CHROMA_HOST=
CHROMA_PORT=8000
CHROMA_COLLECTION_NAME=wiki_ai_english
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
```

> [!CAUTION]
> - **Fail-fast khi khởi động ([`Settings.validate_production()`](../../../src/backend/core/config.py#L99-L152)):** Nếu `APP_ENV` là `production` mà `COOKIE_SECURE=false` hoặc `DATABASE_URL` chứa `postgres:postgres`, hoặc với cả `staging`/`production` mà `APP_SECRET` ngắn hơn 32 ký tự / ít hơn 10 ký tự phân biệt / khớp mẫu mặc định (`changeme`, `default`, `development`, `insecure`, `folio_dev_insecure`, `test_secret`) hoặc `CORS_ALLOWED_ORIGINS` chứa `*`, ứng dụng từ chối khởi động ngay trong `lifespan`.
> - **Tên biến CORS chính xác:** `CORS_ALLOWED_ORIGINS` (không dùng `ALLOWED_CORS_ORIGINS`). Nếu để trống ở `staging`/`production`, hệ thống mặc định same-origin only.
> - **Media upload path:** Từ Vòng 4, [`scripts/ops/backup.py`](../../../scripts/ops/backup.py) và [`scripts/ops/restore.py`](../../../scripts/ops/restore.py) phân giải theo thứ tự `--media-dir` -> `MEDIA_DIR` -> `MEDIA_UPLOAD_DIR` -> `<PROJECT_ROOT>/data/media` (đồng bộ với `MEDIA_DIR=/app/data/media` trong Dockerfile/Compose) và hỗ trợ thêm `--index-storage-dir`. Không đặt mật khẩu thật của `DATABASE_URL` hay `ADMIN_BOOTSTRAP_PASSWORD` vào log hoặc tài liệu.
> - **Proxy boundary:** [`entrypoint-web.sh`](../../../docker/entrypoints/entrypoint-web.sh#L43) truyền `--proxy-headers --forwarded-allow-ips='*'` cho Uvicorn và [`RequestLoggingMiddleware`](../../../src/backend/core/middleware.py#L36) dùng `TRUSTED_PROXIES` để tin cậy `X-Forwarded-For`; vì vậy **tuyệt đối không** expose trực tiếp cổng `8000` của `web` ra internet công cộng.

---

## 3. Quy Trình Sao Lưu Tiền Triển Khai & Diễn Tập Khôi Phục (`R3-01`)

### 3.1. Tạo bản sao lưu nhất quán ([`scripts/ops/backup.py`](../../../scripts/ops/backup.py))

1. **Tạm dừng ghi trước khi tạo snapshot (khi cần đồng bộ tuyệt đối DB + index + media trên production/staging):**
   - Trong Docker Compose (luôn truyền `--env-file .env.production`):
     ```bash
     docker compose --env-file .env.production -f docker-compose.prod.yml stop worker web
     ```
   - Mục đích: ngăn worker ghi chéo vào `INDEX_STORAGE_DIR` và ngăn upload vào `/app/data/media` trong lúc đóng gói archive.
2. **Kiểm tra PostgreSQL 16 client và chạy backup:**
   ```bash
   pg_dump --version
   psql --version
   python scripts/ops/backup.py \
     --output-dir /secure/backups \
     --db-url "$SOURCE_DATABASE_URL" \
     --label "pre_release_$(date -u +%Y%m%d_%H%M%S)"
   # Chỉ thêm --include-vector khi CHROMA_PATH tồn tại và được dùng trong cấu hình:
   #   ... --include-vector
   ```
3. **Cờ thực tế của `backup.py` & `pg_dump`:**
   - CLI hỗ trợ đúng các cờ: `-o / --output-dir`, `--db-url`, `--include-vector`, `--label`, `--timeout`.
   - `dump_postgresql_database()` gọi:
     `pg_dump -h <host> -p <port> -U <user> -d <db> -F p --no-owner --no-acl -f <dump_file>`.
   - **Quan trọng:** Dump SQL này **không** dùng `--clean --if-exists`. Vì vậy file dump là SQL thuần tạo mới schema/bảng/dữ liệu trên một database trống và sẽ **từ chối an toàn (fail-closed)** nếu chạy đè vào database đang có sẵn bảng.
4. **Kiểm tra offline toàn vẹn archive trước khi lưu trữ hoặc dùng để khôi phục:**
   ```bash
   python scripts/ops/restore.py \
     --archive /secure/backups/folio_backup_<timestamp>.tar.gz \
     --verify-only
   ```
   Xác nhận JSON trả về `"status": "verified_offline"` với `verified_files_count >= 1` và `database_dump_bytes > 0`.

### 3.2. Diễn tập khôi phục tự động vào database mới cô lập ([`scripts/run_restore_drill.py`](../../../scripts/run_restore_drill.py))

- **Các cờ CLI thực tế của `scripts/run_restore_drill.py`:**
  - `--admin-url` (**bắt buộc**, trỏ tới database quản trị như `.../postgres` để tạo DB mới cô lập)
  - `--source-db-url` (**bắt buộc**, URL database nguồn cần backup)
  - `--target-db-name` (tùy chọn; **bắt buộc** bắt đầu bằng `folio_restore_drill_` và không bao giờ trùng `PROTECTED_DB_NAMES` như `folio`, `production`, `staging`, `postgres`)
  - `--work-dir` (tùy chọn; thư mục làm việc cô lập chứa `backups/`, `restored_index/`, `restored_media/`)
  - `--keep-target-db` (tùy chọn; giữ DB đích sau khi drill xong để kiểm tra thủ công)
  - `--drop-owned-target-db` (tùy chọn **chỉ dùng chủ ý** khi muốn dựng lại từ một tên `folio_restore_drill_*` đã tồn tại; **không dùng làm mặc định**)

- **Lệnh diễn tập chuẩn (thay các giá trị cục bộ/staging trong shell riêng, không copy URL có mật khẩu vào báo cáo):**
  ```bash
  python scripts/run_restore_drill.py \
    --admin-url <LOCAL_ADMIN_URL> \
    --source-db-url <LOCAL_SOURCE_URL> \
    --target-db-name folio_restore_drill_round3_<unique> \
    --work-dir <NEW_ISOLATED_DIR> \
    --keep-target-db
  ```
- **Schema JSON kỳ vọng khi thành công (exit code `0`):**
  - `"status": "passed"` (lưu ý: **không** phải `drill_status: PASSED`)
  - `"verified_counts"` khớp toàn bộ giữa nguồn và đích (`documents_total`, `documents_published`, `users`, `roles`, `categories`, `tags`, `comments`, `reports`, ...)
  - `"verified_digests"` khớp SHA-256 trên `documents`, `document_tags`, `users`, `document_seo`, `comments`, `reports`
  - `"verified_constraints.has_open_report_partial_unique_index": true` (tên index thực tế: `uq_reports_open_comment_reporter`)
  - `"index_recovery.valid": true` và `"smoke_test.search_smoke_test.status": "passed"`

---

## 4. Quy Trình Triển Khai / Nâng Cấp An Toàn (`R3-08`)

1. **Validate cấu hình cục bộ trước khi chạm môi trường đích:**
   ```bash
   python scripts/ops/validate_compose_and_config.py
   ```
2. **Tạo backup tiền triển khai và kiểm chứng offline (`--verify-only`)** theo Mục 3.1 (tạm dừng ghi nếu dùng snapshot vật lý/thư mục).
3. **Áp dụng migration tới `head` trên database đích:**
   ```bash
   python -m alembic upgrade head
   ```
   - Với Docker Compose, chạy qua service one-shot `migration` (không chạy migration từ `web` hay `worker`, luôn truyền `--env-file .env.production`):
     ```bash
     docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migration
     ```
   - Revision head hiện tại là `20261106_report_open_unique`, tạo partial unique index **`uq_reports_open_comment_reporter`** ([`alembic/versions/20261106_report_open_unique.py`](../../../alembic/versions/20261106_report_open_unique.py#L150)).
4. **Bootstrap hoặc xoay vòng mật khẩu `super_admin` ([`scripts/bootstrap_admin.py`](../../../scripts/bootstrap_admin.py)):**
   - Tài khoản demo trong `scripts/seed_folio.py` tự động bị bỏ qua khi `APP_ENV` là `staging` hoặc `production`.
   - Cung cấp mật khẩu qua biến môi trường `ADMIN_BOOTSTRAP_PASSWORD` (>= 12 ký tự, >= 6 ký tự phân biệt, không thuộc từ điển yếu):
     ```bash
     python scripts/bootstrap_admin.py \
       --email "admin@folio.example.com" \
       --username "superadmin" \
       --display-name "Folio Super Administrator" \
       --non-interactive
     ```
   - Lần đầu chưa tồn tại -> tạo `super_admin`, ghi audit `auth.admin_bootstrap_created`, exit `0`.
   - Đã tồn tại mà không có `--rotate` -> từ chối an toàn, exit `2` (`ALREADY_EXISTS`).
   - Khi cần xoay vòng mật khẩu định kỳ -> thêm `--rotate` (giữ nguyên role/ID nếu đang active `super_admin`, thu hồi toàn bộ phiên cũ, ghi audit `auth.admin_bootstrap_rotated`, exit `0`).
5. **Cấp phát TLS trước khi khởi động Proxy & chạy smoke checklist sau triển khai:**
   (Xem chi tiết nhánh self-signed vs CA import `--import-cert`/`--import-key` trong [`round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md); `cert-preflight` sẽ tự chặn `proxy` nếu thiếu/hết hạn/sai domain cert.)
   ```bash
   # Ví dụ môi trường staging self-signed; với production CA dùng cert-init --import-cert ... --import-key ...
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-init
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
   # Nếu bật semantic HTTP ChromaDB:
   # docker compose --env-file .env.production -f docker-compose.prod.yml --profile semantic up -d --build
   ```
   Kiểm tra:
   - `GET /health/live` -> `200 OK` (`{"status": "alive"}`)
   - `GET /health/ready` -> `200 OK`, `database: "ok"`, kiểm tra `search.engine` (`bm25` trên Compose hoặc `ilike_fallback` hợp lệ nếu serverless chưa có volume index) và `semantic.status` (`available` nếu bật Chroma + model, hoặc `unavailable` có lý do rõ ràng)
   - Đăng nhập bằng `super_admin`, mở `/#/library`, `/#/documents/<id>` (kiểm tra TOC & công thức KaTeX), `/#/admin/taxonomy` (kiểm tra mobile + tìm kiếm/phân trang tag) và `/api/v1/search?q=learning`

---

## 5. Quy Trình Khôi Phục Thảm Họa & Rollback Không Phá Hủy (`R3-01`)

> [!CAUTION]
> **Không bao giờ chạy `restore.py` trực tiếp vào `$DATABASE_URL` đang có bảng hoặc đang phục vụ traffic.**
> - Do `backup.py` không dùng `--clean --if-exists` và `restore_database()` thực thi `psql -v ON_ERROR_STOP=1 --single-transaction`, mọi lệnh restore vào DB đã có bảng sẽ bị PostgreSQL từ chối (`relation "..." already exists`), transaction rollback sạch, và toàn bộ hàng dữ liệu cũ được giữ nguyên.
> - **Không dùng `--drop-owned-target-db` hoặc `DROP DATABASE` lên database đang chạy** để "chữa cháy". Luôn khôi phục sang **một database mới rỗng**, xác minh đạt 100%, chuyển cấu hình kết nối rồi mới restart, đồng thời giữ lại database cũ làm đường lùi.

### Các bước rollback / khôi phục chuẩn

1. **Tạm dừng ghi & worker trên môi trường mục tiêu (quiesce nguồn/đích):**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml stop worker web
   ```
   (Nếu cần giữ nguyên trạng thái lỗi để điều tra sau khi quay lui, tạo thêm backup snapshot khẩn của DB hiện tại trước khi chuyển.)
2. **Xác minh offline archive dự định khôi phục:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm --no-deps ops \
     scripts/ops/restore.py --archive /app/backups/folio_backup_<timestamp>.tar.gz --verify-only
   ```
3. **Tạo một database mới hoàn toàn rỗng và chuẩn bị cặp volume storage tách biệt (quy trình đầy đủ xem [`round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md)):**
   - Trên PostgreSQL: tạo database mới rỗng `folio_restored_<YYYYMMDD_HHMMSS>` (giữ nguyên DB cũ).
   - Tạo `.env.restored` từ `.env.production` với `DATABASE_URL` trỏ sang DB mới và **đổi tên Docker volume**:
     ```ini
     DATABASE_URL=postgresql+psycopg://<user>:<password>@db:5432/folio_restored_<timestamp>
     FOLIO_INDEX_VOLUME=folio-index-data-restored-<timestamp>
     FOLIO_MEDIA_VOLUME=folio-media-data-restored-<timestamp>
     ```
     (Nếu chạy native host CLI thay vì container `ops`, dùng cờ `--index-storage-dir` và `--media-dir` cùng với thư mục đã `chown -R 10001:10001` khi mount vào container.)
4. **Thực thi `restore.py` vào database mới & volume mới qua profile `.env.restored`:**
   - Các cờ CLI thực tế của [`scripts/ops/restore.py`](../../../scripts/ops/restore.py): `-a / --archive`, `--target-db-url`, `--rebuild-index`, `--index-storage-dir`, `--media-dir`, `--skip-migrations`, `--skip-smoke-test`, `--verify-only`, `--timeout`.
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml run --rm ops \
     scripts/ops/restore.py \
     --archive /app/backups/folio_backup_<timestamp>.tar.gz \
     --rebuild-index
   ```
   Xác nhận exit code `0`, JSON `"status": "success"`, `index_recovery.valid: true`, và `smoke_test.search_smoke_test.status: "passed"`. Nếu bước này lỗi, DB và volume cũ vẫn nguyên vẹn 100%.
5. **Cutover bằng hồ sơ `.env.restored` và khởi động lại dịch vụ (`--force-recreate`):**
   - Nếu bật `--profile semantic`, đồng bộ lại collection vector từ DB mới trước khi chuyển traffic (backup lexical không tự sao lưu ChromaDB server).
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml up -d --force-recreate web worker proxy
   ```
6. **Kiểm tra sau chuyển đổi:**
   - Kiểm tra `/health/live`, `/health/ready`, số lượng bài viết/user, truy vấn tìm kiếm, file media và thao tác CRUD/đăng nhập.
7. **Giữ lại database cũ (`folio`) và volume cũ (`folio-index-data`, `folio-media-data`) trong thời gian theo dõi:**
   - Nếu cần switch-back ngay, chỉ cần dựng lại bằng `.env.production` cũ: `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate web worker proxy`. Chỉ thu hồi DB/volume cũ sau khi nghiệm thu ổn định hoàn toàn.
