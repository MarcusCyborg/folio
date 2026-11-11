# Folio — Hướng Dẫn Phát Hành, Cấu Hình Env, TLS & Cutover Không Phá Hủy (Round 4 Authoritative Runbook)

> [!IMPORTANT]
> **TÀI LIỆU VẬN HÀNH CHÍNH THỨC HIỆN HÀNH (Vòng 4 — `R4-01`..`R4-04`, 10/11/2026):**
> Tài liệu này thay thế [`docs/remediation/round-3/RELEASE-RUNBOOK.md`](../round-3/RELEASE-RUNBOOK.md), [`docs/remediation/round-2/RELEASE-RUNBOOK.md`](../round-2/RELEASE-RUNBOOK.md) và [`docs/remediation/2026-11-06/RELEASE-RUNBOOK.md`](../2026-11-06/RELEASE-RUNBOOK.md).
> **Ranh giới kiểm chứng hiện tại:**
> - Hợp đồng env, Compose interpolation, `Settings`, pool tìm kiếm có giới hạn, CLI `init_certs.py`, và diễn tập backup/restore/cutover/switch-back trên **PostgreSQL 16.10** cục bộ đã được kiểm chứng thực tế (`LOCAL_PASS`).
> - **Compose config render: `LOCAL_PASS`** bằng standalone Docker Compose v5.7.0 chính thức. **Docker/Nginx runtime: `NOT_RUN`** do chưa khởi chạy Docker daemon/container tại môi trường kiểm thử cục bộ.
> - Trạng thái triển khai và nghiệm thu trực tuyến vẫn là **`LIVE_ACCEPTANCE: NOT_RUN`**.

---

## 1. Kiến Trúc Triển Khai & Topology Thực Tế

Folio hỗ trợ hai mô hình triển khai được định nghĩa trực tiếp trong mã nguồn:

| Thành phần / Đặc tính | Mô hình A: Persistent Container / VM ([`docker-compose.prod.yml`](../../../docker-compose.prod.yml)) | Mô hình B: Serverless Vercel ([`vercel.json`](../../../vercel.json) — SQL-First Mode) |
|---|---|---|
| **Web Runtime / Entrypoint** | `web` (`folio-web`) chạy [`entrypoint-web.sh`](../../../docker/entrypoints/entrypoint-web.sh) -> `uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'` (chỉ trong mạng nội bộ `frontend-net` / `backend-net`) | Serverless function trỏ trực tiếp tới [`src/backend/main.py`](../../../src/backend/main.py) kèm `"includeFiles": "src/frontend/**"` (không dùng `api/index.py`) |
| **PostgreSQL 16** | `db` (`folio-postgres`, `postgres:16-alpine`, volume `${FOLIO_PGDATA_VOLUME:-folio-pgdata}`) trên `backend-net` (`internal: true`) | Managed PostgreSQL (Neon / Supabase / RDS) qua biến `DATABASE_URL` |
| **Migration Runner** | Dịch vụ one-shot `migration` (`profiles: ["tools"]`) chạy [`entrypoint-migrate.sh`](../../../docker/entrypoints/entrypoint-migrate.sh): `alembic upgrade head` -> bootstrap tùy chọn -> dựng index nếu trống | Chạy thủ công từ CI/bastion có kết nối DB trước khi chuyển traffic: `python -m alembic upgrade head` |
| **Operations Runner** | Dịch vụ one-shot `ops` (`profiles: ["tools"]`, `entrypoint: ["python3"]`) gắn cùng volume `folio-index-data`, `folio-media-data`, `./backups:/app/backups` và `backend-net` để chạy `backup.py`, `restore.py`, `bootstrap_admin.py` | Chạy từ bastion/CI runner có `postgresql-client-16` (`pg_dump`/`psql`) |
| **Background Worker** | `worker` (`folio-worker`) chạy [`entrypoint-worker.sh`](../../../docker/entrypoints/entrypoint-worker.sh) -> `python3 scripts/run_worker.py` (không chạy Alembic) | Không có daemon nền trong serverless function |
| **Lexical Search (BM25)** | Đầy đủ qua volume `${FOLIO_INDEX_VOLUME:-folio-index-data}` -> `/app/data/search_index` (`INDEX_STORAGE_DIR=/app/data/search_index/generations`) | Tự suy giảm an toàn sang PostgreSQL SQL-First (`engine_used: "ilike_fallback"`, `is_degraded: true`); phân trang qua 1.000 kết quả |
| **Media Storage** | Volume `${FOLIO_MEDIA_VOLUME:-folio-media-data}` -> `/app/data/media` (`MEDIA_DIR=/app/data/media`) dùng chung cho `web`, `worker`, `migration`, `ops` | Không dùng lưu trữ đĩa cục bộ cho media bền vững nếu không gắn object storage bên ngoài |
| **Semantic Vector Search** | Tùy chọn qua `--profile semantic` (`chroma`, `chromadb/chroma:0.5.20`, volume `${FOLIO_CHROMA_VOLUME:-folio-chroma-data}`, `CHROMA_HOST=chroma`, `CHROMA_PORT=8000`) | Tắt mặc định (`is_degraded: true`), trừ khi cấu hình HTTP Chroma bên ngoài qua `CHROMA_HOST` / `CHROMA_PORT` |
| **Reverse Proxy & TLS** | Chỉ `proxy` (`folio-proxy`, `nginx:1.25-alpine`) mở cổng host (`PROXY_HTTP_PORT`, `PROXY_HTTPS_PORT`); phụ thuộc bắt buộc `web` (`service_healthy`) và **`cert-preflight` (`service_completed_successfully`)**; volume cert `${FOLIO_CERTS_VOLUME:-folio-proxy-certs}` | Edge HTTPS + CDN do Vercel quản lý |
| **TLS Init & Preflight** | `cert-init` (`profiles: ["tools"]`, mount RW `folio-proxy-certs:/app/certs`) và `cert-preflight` (mặc định, mount RO, `init_certs.py --check-only`) | Không áp dụng |

---

## 2. Hợp Đồng Biến Môi Trường & Quy Tắc Nạp Env (`R4-01`)

### 2.1. Phân biệt rõ 3 tầng nạp env

1. **Tầng Compose Interpolation (đọc trên host bởi CLI `docker compose`):**
   - `docker compose` mặc định chỉ tự đọc tệp `.env` cùng thư mục, **không tự đọc `.env.production`**.
   - Vì `docker-compose.prod.yml` dùng biểu thức nội suy `${APP_SECRET:?...}`, `${POSTGRES_PASSWORD:?...}`, `${FOLIO_INDEX_VOLUME:-folio-index-data}`, mọi lệnh Compose bắt buộc phải truyền tường minh:
     ```bash
     docker compose --env-file .env.production -f docker-compose.prod.yml <command>
     ```
   - Việc thêm `env_file:` vào một service riêng lẻ không thay thế được `--env-file` vì giá trị trong `env_file:` không tham gia bước nội suy `${...}` của Compose YAML (nơi tạo `DATABASE_URL` mặc định và tên volume cutover).
2. **Tầng Container Environment (bên trong `web`, `worker`, `migration`, `ops`, `proxy`, `db`):**
   - Toàn bộ các biến cấu hình đã quảng bá trong [`.env.production.example`](../../../.env.production.example) đều được chuyển tường minh vào container trong [`docker-compose.prod.yml`](../../../docker-compose.prod.yml), gồm: `APP_ENV`, `APP_SECRET`, `DATABASE_URL`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `CORS_ALLOWED_ORIGINS`, `TRUSTED_PROXIES`, `RATE_LIMIT_ENABLED`, `SEARCH_CONTEXT_TTL_MINUTES`, `SEARCH_TIMEOUT_SECONDS`, `SEMANTIC_EXECUTOR_WORKERS`, `SEMANTIC_MAX_PENDING`, `INDEX_STORAGE_DIR`, `MEDIA_DIR`, `ENABLE_LEGACY_SEARCH`, `CHROMA_PATH`, `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_COLLECTION_NAME`, `EMBEDDING_MODEL_NAME`, `WORKER_POLL_INTERVAL`, `WORKER_BATCH_SIZE`, `CERT_EXPECTED_DOMAIN`.
3. **Tầng Host Python CLI vs Container `ops`:**
   - [`src/backend/core/config.py`](../../../src/backend/core/config.py#L8) chỉ nạp `PROJECT_ROOT/.env` (nếu có), **không** tự đọc `.env.production`; cờ `--env-file .env.production` của `docker compose` cũng không có hiệu lực với lệnh Python chạy trực tiếp trên host.
   - Tên host `@db:5432` chỉ phân giải được bên trong mạng Docker nội bộ `backend-net`, **không bao giờ dùng `@db:5432` khi chạy CLI từ host bên ngoài Docker network**.
   - Do đó, trên máy chạy Docker Compose, hãy thực thi các công cụ quản trị thông qua service `ops`:
     ```bash
     docker compose --env-file .env.production -f docker-compose.prod.yml run --rm ops <script> [args...]
     ```
   - Chỉ chạy `python scripts/...` trực tiếp trên host/bastion khi kết nối tới PostgreSQL mà host với bastion phân giải được trực tiếp (`127.0.0.1` hoặc Managed PG endpoint) và đã export tường minh biến môi trường vào shell hiện tại:
     ```bash
     # Đảm bảo .env.production dùng LF và bọc ngoặc đơn '...' quanh giá trị có khoảng trắng/dấu nháy/chấm phẩy
     # (như HSTS_HEADER và ADMIN_BOOTSTRAP_DISPLAY_NAME trong .env.production.example)
     set -a && source .env.production && set +a
     # Hoặc chỉ nạp tạm cho một lệnh Python mà không giữ biến trong shell cha (cần python-dotenv):
     # python3 -c "import os, subprocess, sys; from dotenv import dotenv_values; os.environ.update({k: v for k, v in dotenv_values('.env.production').items() if v is not None}); sys.exit(subprocess.call(sys.argv[1:]))" python3 scripts/<script>.py
     # Đảm bảo DATABASE_URL lúc này trỏ tới endpoint truy cập được từ host, không phải '@db:5432'
     ```

### 2.2. Khởi tạo `.env.production` trên máy chủ mới (Fail-Closed Secrets)

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

> [!CAUTION]
> - `.env.production.example` **cố ý để trống** `APP_SECRET=`, `POSTGRES_PASSWORD=`, `DATABASE_URL=` và `ADMIN_BOOTSTRAP_PASSWORD=`. Nếu chưa điền secret mạnh, cả `docker compose --env-file .env.production -f docker-compose.prod.yml config` (qua `${VAR:?...}`) lẫn [`Settings.validate_production()`](../../../src/backend/core/config.py#L101-L156) (chặn chuỗi rỗng, < 32 ký tự, < 10 ký tự phân biệt, mẫu yếu `replace_with` / `placeholder` / `changeme` / `postgres:postgres` / `COOKIE_SECURE=false` ở `production` / `CORS_ALLOWED_ORIGINS` chứa `*`) đều sẽ **từ chối ngay lập tức**.
> - **Lưu ý ký tự đặc biệt:**
>   1. Trong tệp `--env-file` của Compose, tránh ký tự `$` trần trong `APP_SECRET` hoặc `POSTGRES_PASSWORD` (vì Compose nội suy `$`), hoặc thoát bằng `$$`. Sinh `APP_SECRET` an toàn bằng:
>      `python3 -c "import secrets; print(secrets.token_urlsafe(36))"`
>   2. Ưu tiên mật khẩu `POSTGRES_PASSWORD` dùng ký tự URL-safe (`[A-Za-z0-9_-]`). Nếu `POSTGRES_PASSWORD` chứa ký tự đặc biệt (`@`, `:`, `%`, `/`) và bạn đặt tường minh `DATABASE_URL`, phải URL-encode phần mật khẩu trong `DATABASE_URL` (Cả `alembic/env.py` lẫn `scripts/ops/restore.py` đều đã escape `%` -> `%%` cho ConfigParser).
> - Không đặt mật khẩu thật, secret hay nội dung `.env.production` / `.env.restored` vào log, JSON hay Git (các tệp này đã bị chặn trong `.gitignore`).

### 2.3. Kiểm tra tĩnh và render cấu hình không cần daemon

- Kiểm tra cấu trúc tĩnh (chạy được cả khi chưa có Docker):
  ```bash
  python3 scripts/ops/validate_compose_and_config.py
  ```
- Trên máy chủ/CI có Docker CLI (không cần Docker daemon cho bước render cấu hình):
  ```bash
  docker compose --env-file .env.production -f docker-compose.prod.yml config
  ```
  Nếu muốn kiểm tra với bộ tuning non-default trong môi trường thử nghiệm:
  ```bash
  # Trên tệp test-env tạm (xóa sau khi kiểm tra):
  docker compose --env-file /tmp/.env.test -f docker-compose.prod.yml config --format json
  ```

---

## 3. Quy Trình Cấp Phát, Kiểm Tra Preflight & Gia Hạn TLS (`R4-03`)

Template Nginx ([`default.conf.template`](../../../docker/proxy/templates/default.conf.template#L46-L47)) luôn cấu hình server block HTTPS đọc `/etc/nginx/certs/folio.crt` và `/etc/nginx/certs/folio.key` từ volume `folio-proxy-certs`. Để tránh tình trạng `proxy` khởi động và sập vòng lặp khi mới dựng máy chủ:
- Dịch vụ `cert-preflight` chạy tự động trước `proxy` (`depends_on: cert-preflight: condition: service_completed_successfully`), kiểm tra RO bằng `scripts/ops/init_certs.py --check-only --expected-domain "${CERT_EXPECTED_DOMAIN:-${DOMAIN_NAME:-localhost}}"`.
- Nếu thiếu một trong hai tệp, chứng chỉ hết hạn, private key không khớp public key chứng chỉ, hoặc SAN/CN không khớp domain kỳ vọng, `cert-preflight` sẽ **fail-closed với thông báo lỗi rõ ràng** và chặn `proxy` không cho lên trạng thái lỗi.

### Nhánh A: Môi trường Staging / Local (Chứng chỉ Self-Signed)

1. Trong `.env.production`, cấu hình đúng domain và tắt HSTS nếu không dùng CA tin cậy:
   ```ini
   DOMAIN_NAME=staging.folio.example.com
   STAGING_DOMAIN=localhost
   CERT_EXPECTED_DOMAIN=staging.folio.example.com
   HSTS_HEADER='# HSTS disabled in staging'
   ```
2. Khởi tạo chứng chỉ vào named volume `folio-proxy-certs`:
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-init
   ```
   - `cert-init` tự đọc `CERT_DIR=/app/certs`, `DOMAIN_NAME`, `STAGING_DOMAIN` (hoặc nhận `--domain`, `--staging-domain`, `--days`).
   - Mặc định **không ghi đè** nếu đã có cặp `folio.crt` + `folio.key` hợp lệ. Nếu trạng thái đang dở dang (chỉ có `.crt` hoặc chỉ có `.key`), script **từ chối an toàn** thay vì âm thầm xóa tệp còn lại; chỉ ghi đè khi truyền thêm `--force`.

### Nhánh B: Môi trường Production (Import chứng chỉ CA thật / Let's Encrypt)

Công cụ [`scripts/ops/init_certs.py`](../../../scripts/ops/init_certs.py) hỗ trợ `--import-cert` và `--import-key`:
- Sao chép nguồn vào vùng staging tạm cô lập để giải mã và xác thực **toàn bộ** các khối X.509 PEM/DER trong chuỗi (`fullchain.pem`) + `privkey.pem`, kiểm tra khả năng nạp thực tế qua `ssl.SSLContext.load_cert_chain()` của OpenSSL (tách biệt kiểm tra cú pháp/nạp chain với xác minh trust store PKI), kiểm tra hạn dùng chứng chỉ leaf, khớp cặp khóa public/private, và khớp `--expected-domain` **trước** khi chạm vào `folio-proxy-certs`. Nếu bất kỳ khối non-leaf nào hỏng/cắt cụt hoặc không hợp lệ, volume `folio-proxy-certs` **giữ nguyên hoàn toàn** (kể cả khi truyền `--force`).
- Ghi từng tệp qua tệp tạm rồi `Path.replace` tuần tự (`folio.crt` trước, sau đó `folio.key`) kèm đặt quyền `0644` (`folio.crt`) và `0600` (`folio.key`). Lưu ý: mỗi lần `replace` là nguyên tử riêng từng tệp, **không phải** giao dịch nguyên tử cho cả cặp hai tệp; vì vậy trong quy trình gia hạn phải chờ `cert-init --force` hoàn tất xong mới chạy `cert-preflight` và reload Nginx.

> [!IMPORTANT]
> **Xử lý quyền đọc khóa gốc khi nguồn chứng chỉ thuộc quyền `root` (như `/etc/letsencrypt/live/<domain>/`):**
> Container `cert-init` chạy mặc định dưới user non-root `folio` (`UID/GID 10001`), nên không thể đọc trực tiếp file khóa `0600 root:root` từ `/etc/letsencrypt`. Hãy chọn **một trong hai** cách sau:
>
> - **Cách 1 (khuyến nghị trên host quản trị tin cậy):** chạy `cert-init` tạm thời với `--user 0:0` và mount `:ro` vào thư mục `/etc/letsencrypt/live/${DOMAIN_NAME}` (chú ý truyền `-L` / trỏ tới thư mục chứa đích nếu symlink trỏ sang `../../archive/`, nên mount luôn `/etc/letsencrypt:/etc/letsencrypt:ro`). `init_certs.py` sẽ tự động `chown` cặp tệp đích trong `/app/certs` về `folio:folio` (`10001:10001`) để `cert-preflight` và container non-root đọc an toàn:
>   ```bash
>   DOMAIN_VAL=$(grep -E '^DOMAIN_NAME=' .env.production | cut -d= -f2-)
>   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
>     --user 0:0 \
>     -v /etc/letsencrypt:/etc/letsencrypt:ro \
>     cert-init \
>     --import-cert "/etc/letsencrypt/live/${DOMAIN_VAL}/fullchain.pem" \
>     --import-key "/etc/letsencrypt/live/${DOMAIN_VAL}/privkey.pem" \
>     --expected-domain "${DOMAIN_VAL}"
>   ```
>   *(Khi thay chứng chỉ cũ đã tồn tại, thêm cờ `--force` ở cuối lệnh.)*
>
> - **Cách 2 (giữ container UID `10001`):** sao chép tạm `fullchain.pem` và `privkey.pem` vào thư mục đệm cấp quyền `0750` (nhóm/UID `10001`), chạy `cert-init` không cần `--user 0:0`, sau đó **xóa/shred ngay** thư mục đệm trên host (`shred -u ... && rm -rf ...`).

### Kiểm tra Preflight & Quy trình Gia Hạn (Renewal)

1. Chạy lại `cert-preflight` độc lập để xác nhận volume cert sẵn sàng:
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-preflight
   ```
2. Khi gia hạn chứng chỉ CA định kỳ (chạy **tuần tự** từng bước, không chạy đồng thời `cert-preflight` hoặc `nginx -s reload` trong lúc `cert-init --force` đang thay tuần tự hai tệp `folio.crt` rồi `folio.key`):
   ```bash
   # Bước 1: Validate fullchain mới từ staging rồi thay tuần tự folio.crt -> folio.key (per-file replace)
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
     --user 0:0 -v /etc/letsencrypt:/etc/letsencrypt:ro cert-init \
     --import-cert "/etc/letsencrypt/live/${DOMAIN_VAL}/fullchain.pem" \
     --import-key "/etc/letsencrypt/live/${DOMAIN_VAL}/privkey.pem" \
     --expected-domain "${DOMAIN_VAL}" --force

   # Bước 2 (chỉ chạy sau khi Bước 1 exit 0): Kiểm tra preflight toàn chain & syntax Nginx, sau đó reload không rớt kết nối
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-preflight
   docker compose --env-file .env.production -f docker-compose.prod.yml exec proxy nginx -t
   docker compose --env-file .env.production -f docker-compose.prod.yml exec proxy nginx -s reload
   ```
   *(Lưu ý: Nếu cấu hình proxy thay thế dùng [`Caddyfile`](../../../docker/proxy/Caddyfile), giữ nhất quán `DOMAIN_NAME`, `TLS_CERT_PATH`, `TLS_KEY_PATH` tương ứng.)*

---

## 4. Quy Trình Triển Khai / Nâng Cấp Chuẩn Trên Docker Compose

1. **Chuẩn bị quyền thư mục bind trên host (UID/GID `10001` của user `folio`):**
   ```bash
   mkdir -p backups
   sudo chown -R 10001:10001 backups
   ```
   *(Các named volume Docker `folio-pgdata`, `folio-index-data`, `folio-media-data`, `folio-proxy-certs` tự kế thừa quyền `folio:folio` `10001:10001` từ `Dockerfile` khi được tạo mới.)*
2. **Kiểm tra cấu hình tĩnh và render Compose:**
   ```bash
   python3 scripts/ops/validate_compose_and_config.py
   docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
   ```
3. **Nếu đang nâng cấp hệ thống chạy sẵn — quiesce & backup trước khi migration:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml stop worker web
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm ops \
     scripts/ops/backup.py -o /app/backups --label "pre_release_$(date -u +%Y%m%d_%H%M%S)"
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm --no-deps ops \
     scripts/ops/restore.py --archive /app/backups/<backup_file>.tar.gz --verify-only
   ```
4. **Khởi động `db` (chờ healthy) và chạy một lượt dịch vụ `migration`:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d db
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migration
   ```
   Revision head hiện tại là `20261106_report_open_unique` (tạo partial unique index `uq_reports_open_comment_reporter`).
5. **Khởi tạo hoặc xoay vòng mật khẩu `super_admin` (giữ trống `ADMIN_BOOTSTRAP_PASSWORD=` trong `.env.production`):**
   - Tài khoản demo trong `seed_folio.py` tự động bị bỏ qua khi `APP_ENV` là `staging`/`production`.
   - Khởi tạo/xoay vòng tường minh qua `ops` để nhận đúng exit code (`0` tạo/xoay thành công, `2` `ALREADY_EXISTS`, không bị che bởi `|| true` như trong `entrypoint-migrate.sh`):
     ```bash
     docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
       -e ADMIN_BOOTSTRAP_PASSWORD='<mat-khau-manh-12-ky-tu-tro-len>' \
       ops scripts/bootstrap_admin.py \
       --email "admin@folio.example.com" \
       --username "superadmin" \
       --display-name "Folio Super Administrator" \
       --non-interactive
     # Khi xoay vòng mật khẩu định kỳ: thêm cờ --rotate
     ```
6. **Cấp phát TLS (Mục 3) & xác minh `cert-preflight`:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm cert-preflight
   ```
7. **Khởi động toàn bộ dịch vụ & smoke check:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
   # Hoặc nếu bật ChromaDB nội bộ:
   # docker compose --env-file .env.production -f docker-compose.prod.yml --profile semantic up -d --build
   ```
   Kiểm tra:
   - `docker compose --env-file .env.production -f docker-compose.prod.yml ps`
   - `curl -fsS -k https://127.0.0.1/health/live` (bỏ `-k` khi dùng CA production và đúng host DNS)
   - `curl -fsS -k https://127.0.0.1/health/ready` (`database: "ok"`, `search.engine: "bm25"`, `is_degraded: false` hoặc kiểm tra trạng thái `semantic`)
   - Kiểm tra chứng chỉ TLS phục vụ thực tế: `openssl s_client -connect "${DOMAIN_VAL}:443" -servername "${DOMAIN_VAL}" </dev/null 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName -dates`

---

## 5. Sao Lưu, Xác Minh & Diễn Tập Tự Động (`backup.py`, `restore.py`, `run_restore_drill.py`)

### 5.1. Cờ CLI thực tế đã kiểm chứng

- **[`scripts/ops/backup.py`](../../../scripts/ops/backup.py):**
  - `-o / --output-dir`, `--db-url`, `--include-vector`, `--label`, `--index-storage-dir`, `--media-dir`, `--timeout`.
  - Thứ tự phân giải thư mục media (`get_media_storage_root`): `--media-dir` -> `MEDIA_DIR` -> `MEDIA_UPLOAD_DIR` -> `<PROJECT_ROOT>/data/media`.
  - Dùng `pg_dump -F p --no-owner --no-acl` (không `--clean --if-exists`), tạo `checksums.sha256` + `manifest.json`, xuất báo cáo gồm khóa `"storage_paths"`.
  - **Cảnh báo Semantic Vector:** Cờ `--include-vector` chỉ sao lưu `CHROMA_PATH` nếu là thư mục vector nhúng cục bộ trên đĩa; khi dùng HTTP Chroma container (`--profile semantic`, volume `folio-chroma-data`), bản backup lexical từ `ops` **không** tự sao lưu dữ liệu bên trong container `chroma`. Cần sao lưu volume `folio-chroma-data` riêng hoặc build lại collection từ DB sau khi khôi phục.
- **[`scripts/ops/restore.py`](../../../scripts/ops/restore.py):**
  - `-a / --archive`, `--target-db-url`, `--rebuild-index`, `--index-storage-dir`, `--media-dir`, `--skip-migrations`, `--skip-smoke-test`, `--verify-only`, `--timeout`.
  - Thực thi `psql -v ON_ERROR_STOP=1 --single-transaction`, sau đó `run_post_restore_migrations()` (đã escape `%` -> `%%`), khôi phục/verify index + media, rồi smoke check (`"status": "success"`).
- **[`scripts/run_restore_drill.py`](../../../scripts/run_restore_drill.py):**
  - `--admin-url` (bắt buộc), `--source-db-url` (bắt buộc), `--target-db-name` (bắt buộc bắt đầu bằng `folio_restore_drill_`), `--work-dir`, `--keep-target-db`, `--drop-owned-target-db`.
  - Trả JSON `"status": "passed"` với `verified_counts` (15 trường), `verified_digests` (6 SHA-256), `verified_constraints.has_open_report_partial_unique_index: true` (`uq_reports_open_comment_reporter`), `index_recovery.valid: true`, `smoke_test.search_smoke_test.status: "passed"`.

---

## 6. Quy Trình Khôi Phục & Cutover Storage Không Phá Hủy + Switch-Back (`R4-02`)

> [!CAUTION]
> **Không ghi đè DB hay volume đang chạy và không chuyển đổi nửa vời:**
> 1. Do `pg_dump` không dùng `--clean` và `restore_database()` dùng `ON_ERROR_STOP=1 --single-transaction`, `restore.py` vào DB đã có bảng sẽ thất bại sạch và rollback (không chạm dữ liệu cũ).
> 2. Không dùng cách `export INDEX_STORAGE_DIR=...` trên host khi chạy Docker Compose: trong `docker-compose.prod.yml`, `web` và `worker` mount cố định volume vào `/app/data/search_index` và `/app/data/media`. Cutover an toàn phải đổi **tên volume lưu trữ** (`FOLIO_INDEX_VOLUME`, `FOLIO_MEDIA_VOLUME`) bằng tệp env hồ sơ cutover (`.env.restored`), giữ nguyên container path và giữ trọn DB + volume cũ để quay lui ngay lập tức.
> 3. Tránh lưu dữ liệu khôi phục vào tầng ghi tạm (ephemeral container layer): luôn kiểm tra cả DB đích lẫn volume đích trước khi `--force-recreate`.

### Các bước Cutover & Switch-Back chuẩn trên Compose host

1. **Giữ bản sao cấu hình cũ & dừng lưu lượng ghi (quiesce):**
   ```bash
   cp .env.production .env.production.prev
   chmod 600 .env.production.prev
   docker compose --env-file .env.production -f docker-compose.prod.yml stop worker web
   ```
   *(Tùy chọn: nếu cần lưu dấu vết lỗi hiện tại trước khi chuyển, chạy `ops scripts/ops/backup.py -o /app/backups --label emergency_pre_cutover`.)*

2. **Xác minh offline archive dự định khôi phục:**
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm --no-deps ops \
     scripts/ops/restore.py --archive /app/backups/folio_backup_<timestamp>.tar.gz --verify-only
   ```
   Xác nhận `"status": "verified_offline"` và `database_dump_bytes > 0`.

3. **Tạo một database mới hoàn toàn rỗng (giữ nguyên DB cũ):**
   - Ví dụ tạo database `folio_restored_<timestamp>` ngay trên PostgreSQL container `db` đang giữ `folio-pgdata` (hoặc trên managed PostgreSQL đích ngoài Docker):
     ```bash
     TS="20261110_210000"
     DB_USER=$(grep -E '^POSTGRES_USER=' .env.production | cut -d= -f2-)
     docker compose --env-file .env.production -f docker-compose.prod.yml exec db \
       psql -U "${DB_USER}" -d postgres -v ON_ERROR_STOP=1 \
       -c "CREATE DATABASE folio_restored_${TS} OWNER \"${DB_USER}\";"
     ```

4. **Tạo hồ sơ `.env.restored` trỏ tới DB mới và cặp volume lưu trữ mới (giữ nguyên volume cũ):**
   ```bash
   cp .env.production .env.restored
   chmod 600 .env.restored
   ```
   Chỉnh 3 dòng sau trong `.env.restored` (giữ `FOLIO_PGDATA_VOLUME=folio-pgdata` và `FOLIO_CERTS_VOLUME=folio-proxy-certs` nếu dùng cùng server DB & TLS hiện có):
   ```ini
   DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@db:5432/folio_restored_20261110_210000
   FOLIO_INDEX_VOLUME=folio-index-data-restored-20261110_210000
   FOLIO_MEDIA_VOLUME=folio-media-data-restored-20261110_210000
   ```
   - *Lưu ý nếu dùng **bind mount** thư mục host thay vì Docker named volume:* tạo thư mục mới trên host và cấp đúng quyền trước khi restore/chạy container:
     `mkdir -p /srv/folio_restored_${TS}/{search_index/generations,media} && sudo chown -R 10001:10001 /srv/folio_restored_${TS}`
   - *Lưu ý nếu dùng **`--profile semantic`** với HTTP Chroma container:* đồng thời đặt `FOLIO_CHROMA_VOLUME=folio-chroma-data-restored-${TS}` (hoặc `CHROMA_COLLECTION_NAME` tách biệt) để tránh lẫn vector giữa DB cũ và DB khôi phục.

5. **Thực thi `restore.py` vào DB mới & volume mới qua hồ sơ `.env.restored`:**
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml run --rm ops \
     scripts/ops/restore.py \
     --archive /app/backups/folio_backup_<timestamp>.tar.gz \
     --index-storage-dir /app/data/search_index/generations \
     --media-dir /app/data/media
   ```
   - Mặc định bỏ `--rebuild-index` sẽ khôi phục nguyên trạng generation được đóng gói trong archive (nếu archive không chứa index hoặc muốn build lại hoàn toàn từ PostgreSQL mới, thêm `--rebuild-index`).
   - Xác nhận exit `0`, `"status": "success"`, `storage_paths.index_storage_dir == "/app/data/search_index/generations"`, `storage_paths.media_dir == "/app/data/media"`, `index_recovery.valid == true`, `smoke_test.search_smoke_test.status == "passed"`.
   - Nếu chạy bằng Python CLI trực tiếp trên host với DB đích ngoài mạng Docker (không dùng `@db:5432`): truyền đủ `--target-db-url "<HOST_REACHABLE_URL>" --index-storage-dir "<NEW_HOST_IDX_DIR>" --media-dir "<NEW_HOST_MEDIA_DIR>"` và `chown -R 10001:10001` các thư mục đích trước khi gắn vào container.

6. **Nếu bật `--profile semantic`: đồng bộ lại vector store cho bộ dữ liệu mới trước khi mở traffic:**
   - Backup lexical không thay thế backup/rebuild của HTTP Chroma server. Nếu chạy semantic profile, khởi chạy Chroma volume mới (`docker compose --env-file .env.restored -f docker-compose.prod.yml --profile semantic up -d chroma`) và re-index các tài liệu `published` từ DB mới vào collection mới.

7. **Kiểm tra cấu hình render và Cutover (`--force-recreate`):**
   ```bash
   docker compose --env-file .env.restored -f docker-compose.prod.yml config --format json | head -n 60
   docker compose --env-file .env.restored -f docker-compose.prod.yml up -d --force-recreate web worker proxy
   ```
   (`--force-recreate` bảo đảm container `web` và `worker` gắn lại mount tới `FOLIO_INDEX_VOLUME` / `FOLIO_MEDIA_VOLUME` mới và nhận `DATABASE_URL` mới.)

8. **Nghiệm thu sau cutover:**
   - Kiểm tra `GET /health/live` và `GET /health/ready` (`database: "ok"`, `search.engine: "bm25"`, kiểm tra `index_generation` khớp generation khôi phục).
   - Truy vấn `/api/v1/search?q=...`, kiểm tra bài viết, file media khôi phục và thao tác đăng nhập.

9. **Switch-Back tức thời nếu có sự cố trong giai đoạn theo dõi:**
   - Vì database cũ (`folio`) và volume cũ (`folio-index-data`, `folio-media-data`) không hề bị chỉnh sửa hay xóa trong suốt bước 1–8:
     ```bash
     docker compose --env-file .env.production.prev -f docker-compose.prod.yml stop worker web
     docker compose --env-file .env.production.prev -f docker-compose.prod.yml up -d --force-recreate web worker proxy
     ```
   - Kiểm tra lại `/health/ready`, truy vấn tìm kiếm và media của hệ thống trước cutover. Chỉ thu hồi DB cũ và volume cũ sau khi giai đoạn theo dõi đã nghiệm thu an toàn hoàn toàn.

---

## 7. Triển Khai Vercel Serverless (`SQL-First`) & Checklist Nghiệm Thu Live

- **Trên Vercel (`vercel.json` -> `src/backend/main.py`):**
  1. Thiết lập Environment Variables trực tiếp trên Vercel Project Settings: `APP_ENV=production`, `APP_SECRET`, `DATABASE_URL`, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=lax`, `CORS_ALLOWED_ORIGINS`, `RATE_LIMIT_ENABLED=true`, `SEARCH_CONTEXT_TTL_MINUTES=15`, `SEARCH_TIMEOUT_SECONDS=5.0`.
  2. Chạy backup + `python -m alembic upgrade head` từ CI/bastion có PostgreSQL client trước khi promote deployment.
  3. Chấp nhận hành vi dự kiến ở serverless nếu chưa gắn external Chroma/disk index: `/health/ready` báo `search.engine: "ilike_fallback"`, `is_degraded: true`, tìm kiếm SQL vẫn phân trang đầy đủ > 1.000 kết quả.

- **Checklist Nghiệm Thu Live (`LIVE_ACCEPTANCE: NOT_RUN` tại Vòng 4):**
  - [ ] Merge / commit có rà soát đầy đủ trên `folio-audit-remediation` và push nhánh, xác nhận CI xanh.
  - [ ] Xác nhận trên host Docker thật: `docker compose --env-file .env.production -f docker-compose.prod.yml config`, `cert-init`, `cert-preflight`, `up -d --build`, cutover & switch-back sentinel end-to-end.
  - [ ] Xác nhận `/health/live`, `/health/ready`, TLS HTTPS thực tế, cookie `HttpOnly` + `Secure` + `SameSite=Lax`, đăng nhập đa vai trò, tạo/sửa/xóa tài liệu + media + tìm kiếm và Tag Manager / KaTeX TOC trên URL công khai.
