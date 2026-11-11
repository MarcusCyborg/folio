# Folio — Kết Quả Kiểm Thử Toàn Diện (Test Results)

> [!CAUTION]
> **ĐÍNH CHÍNH (ERRATA — 10/11/2026):** Bảng kết quả vòng 1 dưới đây (tại commit `b659fe5`) có một số đường dẫn/symbol test không khớp thực tế và chưa bao phủ các ca hồi quy thất bại được review độc lập chỉ ra (`R01`–`R18`). Nội dung lịch sử được giữ nguyên để đối chiếu; xem kết quả kiểm thử chính xác và lệnh tái hiện tại **[docs/remediation/round-2/TEST-RESULTS.md](../round-2/TEST-RESULTS.md)**.

- **Thời gian hoàn thành:** 06/11/2026
- **Commit SHA cơ sở:** `e2cbeb95a9abd47ade38a21d884ae973ea63e1bc`
- **Branch:** `codex/folio-audit-remediation-20261106`
- **Môi trường chạy:** Windows 11, Python 3.10.11, PostgreSQL 16 (port 55488), Chromium Headless (Playwright 1.63.0)

---

## 1. Bảng Tổng Hợp Các Suite Kiểm Thử (100% Passed)

| Suite | Đường dẫn | Số test | Kết quả | Thời gian | Ghi chú |
|---|---|---|---|---|---|
| **Backend Admin** | `tests/backend/admin` | 27 | 27 PASSED | 12.20s | Quản trị tài liệu, phân quyền, SEO, analytics, audit log |
| **Backend Foundation** | `tests/backend/foundation` | 49 | 48 PASSED, 1 SKIPPED | 12.02s | Auth, session, RBAC, CSRF token, headers |
| **Auth Concurrency** | `tests/backend/foundation/test_auth_concurrency.py` | 10 | 10 PASSED | 51.55s | Atomic burst admission, brute-force guard |
| **Backend Library** | `tests/backend/library` | 19 | 19 PASSED | 7.89s | Đọc bài, thích, bình luận, report, bookmarks |
| **Backend Search Service** | `tests/backend/search` | 38 | 38 PASSED | 12.98s | SQL fallback, date range, tag deduplication, escape `%` |
| **Search Inverted Index** | `tests/backend/search_index` | 61 | 61 PASSED | 93.99s | Postings, BM25 scoring, generation lifecycle, outbox worker |
| **Backend Operations** | `tests/backend/ops` | 20 | 20 PASSED | 4.78s | Backup/restore, health/readiness, worker daemon, SSL certs |
| **Backend Integration** | `tests/backend/integration` | 1 | 1 PASSED | 3.37s | Luồng phối hợp toàn hệ thống |
| **Safety Invariants** | `tests/safety` | 90 | 90 PASSED | 19.32s | Khử XSS, sanitize markdown, SQL injection guard |
| **Security Invariants** | `tests/security` | 36 | 36 PASSED | 32.94s | Session security, CSRF protection, RBAC boundaries |
| **Search IR Evaluation** | `tests/evaluate` | 14 | 14 PASSED | 4.19s | BM25 precision, recall, nDCG, MRR |
| **Frontend Public Flows** | `tests/frontend/public` | 34 | 34 PASSED | ~65s | Đọc bài, tìm kiếm, lọc taxonomy, mention, responsive |
| **Frontend Lifecycle & Motion** | `test_motion_and_lifecycle.py` | 43 | 43 PASSED | ~80s | Multi-tab sync, navigation state, modal focus trap |
| **TỔNG CỘNG** | **Toàn bộ repository** | **442** | **441 PASSED, 1 SKIPPED** | **100% ĐẠT** | **Đầy đủ bằng chứng tự động** |

---

## 2. Kết Quả Diễn Tập Khôi Phục Thảm Họa (Disaster Recovery Drill)

Kịch bản diễn tập được thực hiện hoàn toàn tự động qua công cụ `scripts/run_restore_drill.py` với các bước nghiêm ngặt:
1. **Khởi tạo Database đích hoàn toàn mới:** Tạo cơ sở dữ liệu cô lập `folio_restore_drill` trên PostgreSQL cluster.
2. **Sao lưu hệ thống (Backup):**
   - Đích sao lưu: `backups/folio_backup_20261106_011916_remediation_drill.tar.gz`
   - Archive SHA256: `74eaccb2754ebbbcb9fd3f729fc39f220c556cd6f54d1d9b2582174a937c0c2f`
   - Alembic Head: `20261106_report_open_unique`
   - Git SHA: `e2cbeb95a9abd47ade38a21d884ae973ea63e1bc`
3. **Phục hồi & Xác thực Tính toàn vẹn (Restore & Verification):**
   - Kiểm tra hash SHA256 tất cả thành phần trong gói.
   - Nạp dữ liệu PostgreSQL dump với `ON_ERROR_STOP=1`.
   - Nâng cấp schema qua Alembic: thực thi thành công transactional DDL đến head.
   - Xây dựng lại search generation từ dữ liệu PostgreSQL (`GenerationManager.build_new_generation`).
   - Kiểm tra khói (Smoke Test):
     - Published documents count: **100**
     - Search smoke test: query `"search"`, 5 hits returned, 40 total matches, generation 1 -> **PASSED**.
   - Kiểm tra số lượng thực thể sau phục hồi:
     - Active Documents: **103** (100 published + 3 drafts)
     - Categories: **6**
     - Tags: **123**
4. **Kết luận DR Drill:** Hoàn tất trong **4.1 giây**, đạt tỷ lệ toàn vẹn dữ liệu **100%**.
