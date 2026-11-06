# Folio — Hướng Dẫn Phát Hành & Vận Hành Sản Xuất (Release Runbook)

Tài liệu này cung cấp quy trình chi tiết từng bước để triển khai bản phát hành đã khắc phục sau audit cho **Folio — Knowledge & Research Library** lên môi trường Production/Staging một cách an toàn và có thể kiểm chứng.

---

## 1. Danh Mục Biến Môi Trường Bắt Buộc (Production Environment)

Thiết lập các biến môi trường sau trên máy chủ production hoặc dashboard Vercel/Cloud:

```ini
APP_ENV=production
APP_SECRET=your-secure-random-256-bit-key-here
DATABASE_URL=postgresql+psycopg://username:password@pg-host:5432/folio_prod
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
RATE_LIMIT_ENABLED=true
INDEX_STORAGE_DIR=/var/data/folio/search_index/generations
MEDIA_UPLOAD_DIR=/var/data/folio/media
ALLOWED_CORS_ORIGINS=https://folio-wiki.vercel.app,https://your-custom-domain.com
```

> [!IMPORTANT]
> Khi `APP_ENV=production`, `COOKIE_SECURE=true` bắt buộc mọi kết nối phải qua HTTPS. Không bao giờ chạy production với `APP_ENV=development` hoặc để lộ `APP_SECRET`.

---

## 2. Quy Trình Triển Khai Sản Xuất (Step-by-Step Deployment)

### Bước 1: Sao lưu tiền triển khai (Pre-deployment Backup)
Trước khi thực hiện bất kỳ migration hoặc cập nhật mã nguồn nào, hãy tạo bản sao lưu toàn diện:
```bash
python scripts/ops/backup.py -o /secure/backups --include-vector --label "pre_release_20261106"
```
Kiểm tra manifest JSON và mã băm SHA256 được tạo ra trong thư mục sao lưu.

### Bước 2: Nâng cấp Cơ sở dữ liệu (Alembic Migration)
Chạy migration nâng cấp schema lên head mới nhất (bao gồm partial unique index `20261106_report_open_unique`):
```bash
alembic upgrade head
```
Xác nhận rằng migration chạy thành công trong transaction DDL mà không có lỗi.

### Bước 3: Khởi tạo Quản trị viên Ban Đầu (Bootstrap Super Admin)
Nếu cơ sở dữ liệu chưa có người dùng nào (trường hợp DB trắng trên production):
```bash
python scripts/bootstrap_admin.py --email "admin@folio.domain" --name "Folio Administrator"
```
Lệnh này có tính chất idempotent: nếu tài khoản đã tồn tại, script sẽ kiểm tra quyền và bỏ qua một cách an toàn mà không ghi đè mật khẩu.

### Bước 4: Khởi động Search Index & Worker Daemon
Nếu chạy trên môi trường có persistent worker/container (khác với serverless Vercel):
```bash
python scripts/run_worker.py
```
Worker sẽ tự động:
- Lắng nghe bảng Outbox (`index_jobs`).
- Xây dựng hoặc kích hoạt search generation.
- Quét và xử lý các chỉ mục tìm kiếm lexical BM25.

---

## 3. Quy Trình Khôi Phục Thảm Họa (Disaster Recovery Runbook)

Nếu xảy ra sự cố nghiêm trọng cần khôi phục lại dữ liệu từ bản sao lưu:

```bash
python scripts/ops/restore.py \
  --archive /secure/backups/folio_backup_xxxx.tar.gz \
  --target-db-url "postgresql+psycopg://user:pass@host:5432/folio" \
  --rebuild-index
```

### Các bước tự động được thực hiện bởi script phục hồi:
1. Xác thực toàn vẹn mã băm SHA256 từng file trong archive đối chiếu với `manifest.json`.
2. Khôi phục dữ liệu PostgreSQL qua tiện ích chuẩn với cờ bảo vệ `ON_ERROR_STOP=1`.
3. Tự động áp dụng `alembic upgrade head` đối với database đích.
4. Tái lập chỉ mục tìm kiếm inverted index và kích hoạt generation hoạt động.
5. Chạy Smoke Test kiểm tra số tài liệu xuất bản và khả năng truy vấn tìm kiếm trước khi bàn giao lưu lượng.
