# Folio — Hướng Dẫn Phát Hành, Diễn Tập Staging & Khôi Phục Thảm Họa (Round 2 Release Runbook — ĐÃ THAY THẾ)

> [!CAUTION]
> **TÀI LIỆU ĐÃ ĐƯỢC THAY THẾ TỪ VÒNG 3 (`R3-01` / `R3-08`) VÀ CẬP NHẬT TIẾP TẠI VÒNG 4 (`R4-01`..`R4-03`, 10/11/2026):**
> Bản runbook Vòng 2 này đã lỗi thời; kể cả một số lệnh Compose thiếu `--env-file .env.production`, thiếu bước `cert-init` TLS và cách cutover index bằng `export INDEX_STORAGE_DIR` ở các bản trước đã được thay thế hoàn toàn.
> **Vui lòng sử dụng tài liệu vận hành chính thức mới nhất tại [`docs/remediation/round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md).** Các ví dụ lệnh bên dưới đã được đính chính lại cho khớp mã nguồn hiện tại để không tồn tại bộ lệnh mâu thuẫn trong repo.

> [!IMPORTANT]
> **Trạng thái triển khai thực tế:** `DEPLOYMENT_PENDING` / `LIVE_ACCEPTANCE: NOT_RUN` — Chưa push, merge hay triển khai lên Vercel hoặc cơ sở dữ liệu production live.

---

## 1. Kiến Trúc Triển Khai & Ma Trận Môi Trường (`OPS-05`)

Folio hỗ trợ hai mô hình triển khai rõ ràng; chi tiết đầy đủ xem [`docs/remediation/round-3/RELEASE-RUNBOOK.md`](../round-3/RELEASE-RUNBOOK.md):

| Thành phần / Đặc tính | Mô hình A: Persistent Container / VM (`docker-compose.prod.yml`) | Mô hình B: Serverless Vercel (`src/backend/main.py` theo `vercel.json` — SQL-First Mode) |
| :--- | :--- | :--- |
| **Web Runtime** | `folio-web` (Uvicorn ASGI, persistent process) | Vercel Python Serverless Function trỏ `src/backend/main.py` với `includeFiles: "src/frontend/**"` |
| **PostgreSQL 16** | `folio-postgres` (`postgres:16-alpine` + `folio-pgdata`) | Managed PostgreSQL (Neon / Supabase / RDS) qua `DATABASE_URL` |
| **Background Worker** | `folio-worker` (`scripts/run_worker.py` đọc bảng `index_jobs`) | **Không có daemon nền** trong serverless function |
| **Lexical Search (BM25)** | Đầy đủ qua volume chung `folio-index-data` (`/app/data/search_index/generations`) | Tự động suy giảm an toàn sang **PostgreSQL SQL-First** (`engine_used: "ilike_fallback"`, `is_degraded: true`) nếu không có volume bền vững |
| **Semantic Vector Search** | Tùy chọn qua profile `--profile semantic` (`folio-chroma` + `CHROMA_HOST=chroma`, `CHROMA_PORT=8000`) | Tắt mặc định (`is_degraded: true`), trừ khi kết nối tới Chroma HTTP server bên ngoài qua `CHROMA_HOST` / `CHROMA_PORT` |
| **Backup / Restore CLI** | Chạy trực tiếp trong container `web`/`worker` (đã đóng gói sẵn `postgresql-client-16` `pg_dump` / `psql`, `R18`) | Chạy từ bastion/CI runner có cài `postgresql-client` (`pg_dump` / `psql`) |

---

## 2. Danh Mục Biến Môi Trường Đã Kiểm Chứng (`R17`, `EXT-01`)

Các tên biến dưới đây khớp trực tiếp với [`Settings`](../../../src/backend/core/config.py#L47-L151) và [`docker-compose.prod.yml`](../../../docker-compose.prod.yml):

```ini
# Bắt buộc cho Staging / Production
APP_ENV=production
APP_SECRET=<chuoi-ngau-nhien-toi-thieu-32-ky-tu-do-phuc-tap-cao>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<pg-host>:5432/<db_name>
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
CORS_ALLOWED_ORIGINS=https://folio-wiki.vercel.app,https://your-custom-domain.com
TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8

# Rate Limiting & Timeout
RATE_LIMIT_ENABLED=true
SEARCH_TIMEOUT_SECONDS=5.0
SEARCH_CONTEXT_TTL_MINUTES=15

# Lưu trữ chỉ mục (Mô hình Container / VM; media CLI dùng mặc định ./data/media)
INDEX_STORAGE_DIR=/app/data/search_index/generations
ENABLE_LEGACY_SEARCH=false

# Tùy chọn Semantic Vector Search (EXT-01)
CHROMA_PATH=/app/data/vector
CHROMA_HOST=chroma
CHROMA_PORT=8000
CHROMA_COLLECTION_NAME=wiki_ai_english
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
```

> [!CAUTION]
> - Tên biến CORS chính xác là **`CORS_ALLOWED_ORIGINS`** (không dùng `ALLOWED_CORS_ORIGINS`). Nếu chứa `*` khi `APP_ENV` là `staging` hoặc `production`, [`Settings.validate_production()`](../../../src/backend/core/config.py#L99-L152) sẽ từ chối khởi động (fail-fast).
> - Không bao giờ in hoặc echo giá trị `DATABASE_URL` ra log triển khai (`R16` / `OPS-07`).

---

## 3. Quy Trình Diễn Tập Staging & Phát Hành (`OPS-01`, `OPS-02`, `OPS-03`)

> [!NOTE]
> Xem hướng dẫn đầy đủ, quy trình TLS `cert-init`, cutover storage qua `FOLIO_INDEX_VOLUME`/`FOLIO_MEDIA_VOLUME` và ma trận biến cấu hình tại [`docs/remediation/round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md).

### Bước 1: Kiểm tra công cụ PostgreSQL Client & Sao lưu tiền triển khai (`R01`, `R18`, `OPS-03`)

Xác nhận `pg_dump` và `psql` (PostgreSQL 16+) sẵn sàng trong môi trường vận hành (hoặc bên trong container `folio-web` / `folio-worker`):

```bash
pg_dump --version
psql --version
python scripts/ops/backup.py -o /secure/backups --label "pre_release_$(date -u +%Y%m%d_%H%M%S)"
# Chỉ thêm --include-vector khi CHROMA_PATH tồn tại và được bật
```

- [`scripts/ops/backup.py`](../../../scripts/ops/backup.py) tự động kiểm tra tồn tại `pg_dump`, thực thi `pg_dump -F p --no-owner --no-acl -f ...` (không dùng `--clean --if-exists`), ghi `manifest.json` kèm SHA-256 từng tệp và đóng gói thành `.tar.gz`. Nếu `pg_dump` vắng mặt hoặc lỗi, script thoát với mã lỗi khác `0` (fail-closed, không bao giờ tạo backup giả).

### Bước 2: Diễn tập khôi phục trên database mới cô lập (`OPS-01`, `OPS-02`, `R3-01`)

Chạy diễn tập khôi phục toàn phần sang database mới mang tiền tố `folio_restore_drill_`:

```bash
python scripts/run_restore_drill.py \
  --admin-url "<LOCAL_ADMIN_URL>" \
  --source-db-url "<LOCAL_SOURCE_URL>" \
  --target-db-name "folio_restore_drill_round3_<unique>" \
  --work-dir "<NEW_ISOLATED_DIR>" \
  --keep-target-db
```

Xác nhận báo cáo JSON trả về `"status": "passed"` với đầy đủ checksum SHA-256, `alembic upgrade head`, số lượng/digest bản ghi `documents` / `users` / ràng buộc, và smoke query tìm kiếm.

### Bước 3: Áp dụng Migration Cơ sở dữ liệu (`R05`)

```bash
python -m alembic upgrade head
```

Lệnh này áp dụng toàn bộ migration bao gồm partial unique index `uq_reports_open_comment_reporter` ([`20261106_report_open_unique.py`](../../../alembic/versions/20261106_report_open_unique.py)) chống trùng lặp báo cáo vi phạm khi gửi đồng thời.

### Bước 4: Khởi tạo hoặc Xoay vòng Tài khoản Super Admin (`R17`)

Cung cấp mật khẩu qua biến môi trường `ADMIN_BOOTSTRAP_PASSWORD` (tối thiểu 12 ký tự, không trùng mật khẩu mẫu) và dùng đúng cờ **`--display-name`**:

```bash
export ADMIN_BOOTSTRAP_PASSWORD="<mat-khau-manh-toi-thieu-12-ky-tu>"
python scripts/bootstrap_admin.py \
  --email "admin@folio.example.com" \
  --username "superadmin" \
  --display-name "Folio Super Administrator" \
  --non-interactive
```

- **Tính chất an toàn:**
  - Nếu tài khoản chưa tồn tại: tạo mới `super_admin`, ghi audit `auth.admin_bootstrap_created` và thoát mã `0`.
  - Nếu tài khoản đã tồn tại (không truyền `--rotate`): từ chối ghi đè và thoát mã `2` (`ALREADY_EXISTS`).
  - Khi cần xoay vòng mật khẩu định kỳ: thêm cờ `--rotate` (cập nhật hash, thu hồi toàn bộ phiên cũ, ghi audit `auth.admin_bootstrap_rotated`).

### Bước 5: Khởi động Dịch vụ & Kiểm tra Sức khỏe (`OPS-06`)

Với mô hình Docker Compose (`docker-compose.prod.yml`), luôn truyền `--env-file .env.production` và cấp phát TLS vào `folio-proxy-certs` trước khi bật `proxy`:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-init
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
# Nếu bật tìm kiếm ngữ nghĩa ChromaDB:
# docker compose --env-file .env.production -f docker-compose.prod.yml --profile semantic up -d --build
```

Kiểm tra các điểm cuối vận hành:
1. `GET /health/live` -> `200 OK` (`{"status": "alive"}`).
2. `GET /health/ready` -> `200 OK` (`status: "ready"`, `database: "ok"`, `index_generation` đang hoạt động; probe nhẹ <= 2s không nạp lại trọng số mô hình ML trên mỗi lần kiểm tra).
3. Đăng nhập quản trị, kiểm tra `/#/admin/taxonomy`, `/#/documents/<id>`, và `/api/v1/search?q=learning`.

---

## 4. Quy Trình Rollback & Khôi Phục Thảm Họa Không Phá Hủy (`OPS-02`, `R3-01`, `R4-02`)

Xem chi tiết quy trình đầy đủ tại [`docs/remediation/round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md):

1. **Dừng lưu lượng ghi / tạm dừng worker:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml stop worker web
   ```
2. **Tạo một database rỗng mới và hồ sơ `.env.restored` với cặp volume `FOLIO_INDEX_VOLUME` / `FOLIO_MEDIA_VOLUME` tách biệt — không restore đè trực tiếp vào `$DATABASE_URL` đang có bảng (PostgreSQL sẽ từ chối an toàn dưới `ON_ERROR_STOP=1 --single-transaction`):**
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml run --rm ops \
     scripts/ops/restore.py \
     --archive /app/backups/folio_backup_<timestamp>.tar.gz \
     --rebuild-index
   ```
3. **Cutover bằng hồ sơ `.env.restored`, giữ nguyên DB/volume cũ để quay lui tức thời:**
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml up -d --force-recreate web worker proxy
   curl -fsS http://127.0.0.1/health/live
   ```
