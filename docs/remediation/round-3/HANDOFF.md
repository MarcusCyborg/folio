# Folio — Tài Liệu Bàn Giao Khắc Phục Vòng 3 (Round 3 Handoff — Đã Bổ Sung Vòng 4 Cho Triển Khai & Runbook)

> [!IMPORTANT]
> **Cập nhật từ Vòng 4 (10/11/2026):** Phần cấu hình triển khai, hợp đồng env Compose (`--env-file .env.production`), cutover storage không phá hủy (`FOLIO_INDEX_VOLUME` / `FOLIO_MEDIA_VOLUME`) và cấp phát TLS (`cert-init` / `cert-preflight`) đã được chuẩn hóa ở Vòng 4. Để thực hiện triển khai, khôi phục và bàn giao hiện hành, hãy sử dụng [`docs/remediation/round-4/HANDOFF.md`](../round-4/HANDOFF.md) và [`docs/remediation/round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md).

- **Ngày bàn giao:** `2026-11-10`
- **Worktree sửa sản phẩm:** `F:/dpl13.10/folio-audit-remediation`
- **Branch:** `codex/folio-audit-remediation-20261106` (working tree chưa commit trên nền `b659fe57a5f7c9bb7cfdb14cbf11813e7d512333`, giữ trọn vẹn toàn bộ Vòng 2 và Vòng 3)
- **Tài liệu Vòng 3:** [STATUS.md](./STATUS.md) | [TEST-RESULTS.md](./TEST-RESULTS.md) | [RELEASE-RUNBOOK.md](./RELEASE-RUNBOOK.md)

---

## 1. Kết Luận Trạng Thái Theo 3 Lớp Tách Biệt

1. **Phase 1 Local Demo (`FIXED` / Đạt chuẩn demo & nghiệm thu cục bộ):**
   - Tất cả luồng chính Phase 1 (đăng ký/đăng nhập, rate limit đồng thời, session đa tab, 4 vai trò + `super_admin`, CRUD/publish/archive bài viết, bình luận/like/@mention, danh mục/tag/lọc ngày, tìm kiếm SQL, audit/logging, responsiveness, backup/restore sang DB mới) đã đóng sạch toàn bộ lỗi mở từ review 10/11/2026 (`R3-01`, `R3-02`, `R3-03`, `R3-06`, `R3-07`, phần config `R3-08`).
   - Trên PostgreSQL 16.10 thật và Playwright Chromium, bộ kiểm thử đóng băng đạt **488/488 PASSED (0 failed, 0 skipped)** cùng diễn tập khôi phục CLI thành công.
2. **Phần Tìm Kiếm Nâng Cao & Đánh Giá (`R3-04`, `R3-05`, Vector/BM25):**
   - **Đã đóng xong cục bộ:** Executor pool + semaphore giới hạn cho semantic/readiness (`R3-04`), không chia sẻ request `db: Session` qua thread, sửa `idx-gen-fallback` luôn mang `status="archived"`, và xác minh corpus-vs-DB đối chiếu cả ID + status + nội dung/title/summary SHA-256 trong `evaluate/run_eval.py` (`R3-05`). BM25 trên PostgreSQL 16 + corpus thật đạt `VERIFIED_MATCH`, `MAP@10=0.7590`, `nDCG@10=0.8466`.
   - **Tình trạng Vector / ChromaDB thật (`BLOCKED_ENV`):** Máy kiểm thử chưa khởi chạy dịch vụ HTTP ChromaDB hay thư mục `data/vector`, nên phần thực thi semantic model/vector thật không đánh dấu pass thay cho test adapter có kiểm soát.
3. **Website Công Khai (`https://folio-wiki.vercel.app/` -> `LIVE_ACCEPTANCE: NOT_RUN`):**
   - Toàn bộ bản sửa Vòng 2 và Vòng 3 **chưa được commit, push hay deploy** lên Vercel/staging/production. Website online hiện vẫn chạy bản build cũ trước khi sửa và **chỉ được coi là đã cập nhật sau khi nhóm hoàn tất các bước ở Mục 4**.

---

## 2. Tóm Tắt Kỹ Thuật Những Thay Đổi Chính Ở Vòng 3

1. **`R3-01` — Runbook Diễn Tập & Rollback Nhất Quán:**
   - Phát hành [`docs/remediation/round-3/RELEASE-RUNBOOK.md`](./RELEASE-RUNBOOK.md) làm tài liệu vận hành chính và gắn đính chính trên [`docs/remediation/round-2/RELEASE-RUNBOOK.md`](../round-2/RELEASE-RUNBOOK.md) để xóa mâu thuẫn lệnh.
   - Đúng 100% cờ CLI thực tế (`--admin-url`, `--source-db-url`, `--target-db-name`, `--work-dir`, `--keep-target-db`), khóa JSON (`"status": "passed"`), mô tả đúng `pg_dump` không dùng `--clean --if-exists`, entrypoint Vercel `src/backend/main.py`, partial unique index `uq_reports_open_comment_reporter`, và quy trình rollback tạo database + `INDEX_STORAGE_DIR`/vùng media riêng trước khi cutover.
2. **`R3-02` — Bảo Toàn Login Reservation Của Các Request Đang Chạy:**
   - Trong [`src/backend/core/rate_limit.py`](../../../src/backend/core/rate_limit.py), `_lock_and_read_bucket()` đọc lại hàng sau race delete; `commit_login_reservation_success()` khóa theo thứ tự xác định `{target_key, ip_key}`, chỉ xóa lịch sử failed cũ và `reservation_token` của chính request thành công trên `login_target`, **giữ nguyên** mọi reservation chưa hết hạn của các request song song đang verify Argon2.
3. **`R3-03` — Tag Manager Pagination Clamping:**
   - Trong [`src/frontend/admin/content_views.js`](../../../src/frontend/admin/content_views.js), `loadTaxonomies(clampAttempt = 0)` tự kéo `tagPage` về `totalPages` khi xóa hoặc sửa tag cuối cùng của trang > 1 ra khỏi bộ lọc (`totalTags > 0`), và reset về trang 1 khi `totalTags === 0` mà không gây vòng lặp request hay race response cũ.
4. **`R3-04` & `R3-06` — Semantic Concurrency Giới Hạn, Tách Thread Session, Fallback `idx-gen-fallback` & Bỏ Trần SQL 1.000:**
   - Trong [`src/backend/services/search/search_service.py`](../../../src/backend/services/search/search_service.py), [`src/backend/core/config.py`](../../../src/backend/core/config.py), [`src/backend/search/semantic.py`](../../../src/backend/search/semantic.py) và [`src/backend/main.py`](../../../src/backend/main.py): dùng pool executor chia sẻ + `BoundedSemaphore` (`SEMANTIC_EXECUTOR_WORKERS=2`, `SEMANTIC_MAX_PENDING=2`, và pool readiness `1+1`), giữ slot tới khi `task_fn()` thoát `finally`, không truyền foreground `db: Session` sang worker thread (`resolve` `source_url` trên caller thread), thu dọn pool trong `lifespan`.
   - Sửa bản ghi placeholder `idx-gen-fallback` mang `status="archived"` và `GenerationManager.get_active_generation()` (`generation_num > 0`, `status == "active"`) để fallback tìm kiếm không làm hỏng trạng thái active generation.
   - Bỏ trần `top_k=1000` khỏi `_execute_ilike_fallback` để SQL fallback trả đủ toàn bộ `snapshot_total` (kiểm chứng với `1001` kết quả / 11 trang). Đồng thời tối ưu `InvertedIndex.load()` ([`src/backend/search/index.py`](../../../src/backend/search/index.py)) và eager-load category/tags giảm độ trễ thực thi ổn định.
5. **`R3-05` — Xác Minh Corpus-DB Theo Nội Dung & ID:**
   - Trong [`evaluate/run_eval.py`](../../../evaluate/run_eval.py), `verify_corpus_db_alignment()` tính tập ID published/draft, trạng thái không bị soft-delete, và SHA-256 title/summary/content từng bài để phát hiện cả trường hợp tráo bài hoặc sửa nội dung mà giữ nguyên tổng số bài (`100`). Mặc định chặn run sai lệch (`CorpusAlignmentError`, exit 1); cờ `--allow-mismatch` xuất kết quả chẩn đoán mang nhãn `INVALID_MISMATCH`. Đã đồng bộ [`evaluate/corpus_manifest.json`](../../../evaluate/corpus_manifest.json) mà không đụng [`fixtures/folio/documents.jsonl`](../../../fixtures/folio/documents.jsonl).
6. **`R3-07` — TOC Với Tiêu Đề Có Công Thức KaTeX:**
   - Trong [`src/frontend/public/detail_view.js`](../../../src/frontend/public/detail_view.js), `extractHeadingLabel()` và bước tạo `<nav class="document-toc card">` chạy **trước** `renderMathInContainer(readingColumn)`, loại bỏ hoàn toàn hiện tượng lặp `x2x^2x2` trong text và slug của mục lục.
7. **`R3-08` — Đồng Bộ Template Cấu Hình Phát Hành:**
   - Cập nhật [`.env.production.example`](../../../.env.production.example) khớp 100% [`Settings`](../../../src/backend/core/config.py) và [`RELEASE-RUNBOOK.md`](./RELEASE-RUNBOOK.md).

---

## 3. Ranh Giới Đã Giữ Nguyên (Không Tự Ý Sửa / Không Vi Phạm Phạm Vi)

- Không sửa mã sản phẩm trong `F:/dpl13.10/WikiSearchEngine`, giữ nguyên `.presentation-build/`, `docs/presentation/`, các hồ sơ review trước đó và dữ liệu seed `fixtures/folio/documents.jsonl`.
- Không tự commit, push, merge, deploy Vercel hay ghi vào cơ sở dữ liệu production.
- Không thêm framework mới hoặc giữ dữ liệu tạm PostgreSQL sau kiểm chứng.

---

## 4. Việc Cần Làm Tiếp Theo Để Triển Khai & Nghiệm Thu Live

1. **Rà soát diff và commit trên worktree sản phẩm:**
   - Kiểm tra `git status` và `git diff` tại `F:/dpl13.10/folio-audit-remediation` (đảm bảo bao gồm cả các tệp untracked hợp lệ: `docs/remediation/round-2/`, `docs/remediation/round-3/`, `src/frontend/assets/vendor/`, `src/frontend/core/math.js`, `tests/frontend/public/test_round2_regressions.py`, `tests/frontend/public/test_round3_regressions.py`, và **không** commit thư mục artifact tạm nếu chưa có quy định khác).
2. **Push branch và kiểm tra GitHub Actions CI (`.github/workflows/ci.yml`):**
   - Xác nhận cả hai job `backend-and-database` và `frontend-e2e` xanh trên Ubuntu + PostgreSQL 16 + Playwright Chromium.
3. **Triển khai staging / production theo [`round-4/RELEASE-RUNBOOK.md`](../round-4/RELEASE-RUNBOOK.md) (đã thay thế bản Vòng 3):**
   - Nạp đúng `.env.production` với mọi lệnh Compose qua `--env-file .env.production` (`APP_ENV=production`, `APP_SECRET` mạnh >= 32 ký tự, `POSTGRES_PASSWORD` không rỗng, `COOKIE_SECURE=true`, `CORS_ALLOWED_ORIGINS` không chứa `*`, `RATE_LIMIT_ENABLED=true`, `SEMANTIC_EXECUTOR_WORKERS=2`, `SEMANTIC_MAX_PENDING=2`).
   - Cấp phát TLS vào volume `folio-proxy-certs` qua `cert-init` (self-signed staging hoặc `--import-cert`/`--import-key` với CA production) để `cert-preflight` thông qua trước khi bật `proxy`.
   - Chạy backup tiền triển khai -> `docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migration` -> `scripts/bootstrap_admin.py` (nếu cần khởi tạo/xoay vòng `super_admin`) -> diễn tập `scripts/run_restore_drill.py` trên DB đích staging cô lập; khi rollback/cutover dùng hồ sơ `.env.restored` với cặp `FOLIO_INDEX_VOLUME` / `FOLIO_MEDIA_VOLUME` mới.
   - Nếu bật Semantic Vector: khởi chạy ChromaDB (`--profile semantic` hoặc dịch vụ ngoài cấu hình `CHROMA_HOST`/`CHROMA_PORT`), dựng index + vector và chạy lại `evaluate/run_eval.py --split test` để xác minh semantic end-to-end (bước này hiện đang `BLOCKED_ENV` tại local).
4. **Smoke test trên URL công khai (`https://folio-wiki.vercel.app/` hoặc domain staging):**
   - Kiểm tra `/health/live`, `/health/ready` (`database: "ok"`, `env: "production"`), cookie flags (`HttpOnly`, `Secure`, `SameSite=Lax`), đăng nhập đủ các vai trò quản trị, tạo/sửa/lọc/chi tiết KaTeX+TOC, Tag Manager phân trang + mobile, rồi mới chốt nghiệm thu live.
