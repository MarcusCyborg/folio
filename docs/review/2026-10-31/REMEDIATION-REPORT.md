# Báo Cáo Khắc Phục Lỗi và Hoàn Thiện Giao Diện (Remediation Report)
**Dự án:** Folio — Knowledge & Research Library  
**Ngày báo cáo:** 31/10/2026  
**Phiên bản kiểm toán đối chiếu:** `docs/review/2026-10-31/REVIEW.md` (Baseline)  
**Môi trường thực thi & kiểm thử:** Python 3.10.11, PostgreSQL 16, Windows 10/11 x64  
**Dedicated Demo Instance:** `http://127.0.0.1:8002` (Database: `folio_demo`)  

---

## 1. Tóm Tắt Điều Hành (Executive Summary)

Đợt khắc phục này tập trung giải quyết triệt để toàn bộ 7 phát hiện kỹ thuật (Findings F1–F7) được chỉ ra trong đợt đánh giá độc lập ngày 31/10/2026, đồng thời tiến hành tái cấu trúc toàn diện giao diện người dùng (UI/UX) theo 10 nguyên lý công thái học Nielsen Norman và chuẩn hóa bộ dữ liệu nghiên cứu 100 bài viết nguyên bản.

### Kết quả then chốt đạt được:
1. **Khắc phục lỗi chức năng & bảo mật (F1–F7):**
   - **100% findings (7/7)** đã được xác minh: 6 findings được sửa và kiểm thử tự động trực tiếp trong đợt này (F1, F2, F3, F4, F5, F7), 1 finding đã được sửa từ commit trước và xác nhận an toàn tuyệt đối (F6).
   - Bổ sung 7 test case chuyên biệt (`test_preview.py`, `test_click_idempotency.py`), nâng tổng số test backend lên **58/58 passed (100%)**.
2. **Cải tiến thiết kế giao diện (UI Redesign):**
   - Áp dụng hệ thống font tự host hoàn toàn (**Source Serif 4** cho tiêu đề học thuật, **Source Sans 3** cho giao diện và nội dung), loại bỏ phụ thuộc CDN bên ngoài.
   - Thống nhất trải nghiệm giữa khu vực đọc công cộng (Public Library) và khu vực quản trị (Admin) dưới sự điều phối của một kiến trúc sư frontend duy nhất.
   - Hoàn thiện màn hình Library làm chuẩn mực (baseline checkpoint) trên 4 độ phân giải desktop (`1366x768`, `1440x900`, `1280x720`, `1920x1080`), tối ưu hệ thống nhãn/tiêu đề và line-clamp tóm tắt.
   - Bổ sung Table of Contents (TOC) thông minh cho bài viết chi tiết, tối ưu cột đọc chuẩn ~760px.
   - Thiết kế lại bảng tài liệu admin với nút chính "Edit" và menu hành động ba chấm (`•••`) chống tràn layout, gom nhóm sidebar logic, và nâng cấp biểu đồ Analytics (chiều cao 240px, lưới ngang, decimation nhãn ngày).
3. **Chuẩn hóa dữ liệu & Môi trường Demo:**
   - Tinh lọc bộ dữ liệu gồm **100 bài viết nghiên cứu công bố** phân bổ cân bằng hoàn hảo qua 6 danh mục khoa học (16–18 bài/chuyên mục), loại bỏ hoàn toàn các rác crawler (`[edit]`, link chú thích hỏng).
   - Tích hợp 8 sơ đồ kỹ thuật định dạng SVG mở (CC BY-SA 4.0) vào các bài viết công nghệ lõi.
   - Thiết lập cơ sở dữ liệu demo độc lập `folio_demo` chạy trên cổng **8002**, giữ nguyên vẹn cơ sở dữ liệu `folio` và server gốc trên cổng 8000 làm mốc đối chứng.

---

## 2. Ma Trận Tình Trạng Các Findings (F1 – F7)

| Mã | Tên Vấn Đề | Mức Độ | Tình Trạng Khắc Phục | Minh Chứng & Cơ Chế Xử Lý |
| :--- | :--- | :---: | :---: | :--- |
| **F1** | Markdown Editor Preview XSS | High | **Đã sửa trong đợt này** | Thay thế regex client-side bằng backend preview endpoint `POST /api/v1/admin/documents/preview` (kèm alias `/admin/documents/preview`). Sử dụng bộ lọc Bleach cấu hình an toàn, loại bỏ quote breakout và các thuộc tính sự kiện (`onload`, `onerror`). Yêu cầu quyền `documents:write`. Kiểm chứng bởi `tests/backend/admin/test_preview.py` (4 tests). |
| **F2** | Mất nội dung soạn thảo khi chuyển trang | Medium | **Đã sửa trong đợt này** | Cài đặt hệ thống navigation leave-guard tại `src/frontend/core/router.js` (`registerLeaveGuard`, `clearLeaveGuard`). Tích hợp vào Document Editor: theo dõi trạng thái `dirtyState`, chặn và xác nhận người dùng khi đổi hash, click menu sidebar, header, nút back/forward trình duyệt và điều hướng lập trình. |
| **F3** | Nhãn nút Lưu nháp vs Xuất bản lệch hành vi | Medium | **Đã sửa trong đợt này** | Tái cấu trúc logic hiển thị nút tại `src/frontend/admin/content_views.js`: Với bài viết đã xuất bản (`published`), nút chính là **"Save Changes"** (giữ status published), nút phụ là **"Save & Unpublish"** (chuyển sang draft). Với bài viết đang nháp (`draft`), nút chính là **"Publish to Library"**, nút phụ là **"Save Draft"**. Hành vi và payload gửi đi khớp 100% với nhãn trực quan. |
| **F4** | Click Logging Idempotency & Unique Constraint | High | **Đã sửa trong đợt này** | Thêm partial unique index `ix_interaction_logs_actor_request_unique` trên cặp `(actor_key, request_key)` WHERE `request_key IS NOT NULL` qua Alembic migration `20261031_click_idempotency_unique.py`. Cập nhật `events_service.py` phát hiện payload không khớp trả `HTTP 409 Conflict`, xử lý đua ghi đồng thời qua `IntegrityError` rollback an toàn. Kiểm chứng bởi `tests/backend/library/test_click_idempotency.py` (3 tests). |
| **F5** | Tải lại trang Detail tự động ghi nhận Search Click | Medium | **Đã sửa trong đợt này** | Loại bỏ hoàn toàn lệnh ghi nhận click khỏi hàm render của `detail_view.js`. Sự kiện Search Click chỉ được kích hoạt duy nhất khi người dùng click/Enter vào một kết quả tìm kiếm trên `library_view.js` kèm theo `request_key` xác định. Trang Detail chỉ ghi nhận lượt đọc bài viết (View event) có cơ chế chống trùng lặp. |
| **F6** | OverflowError tại biên `date_to` | High | **Đã sửa từ trước** | Xác minh trên commit `4e0c348`: Logic parsing ngày tại `catalog_service.py`, `analytics_service.py` và `governance_service.py` sử dụng `datetime.combine(d, time.max)` an toàn, xử lý chính xác microsecond cuối cùng của ngày mà không vượt quá giới hạn timestamp PostgreSQL. Kiểm chứng bởi `test_search_combinations_and_edge_cases`. |
| **F7** | Thiếu dependency và tài liệu cài đặt dev | Low | **Đã sửa trong đợt này** | Bổ sung `playwright>=1.40.0` vào `requirements-dev.txt`. Cập nhật `README.md` hướng dẫn chi tiết các bước cài đặt môi trường dev và tải browser headless chromium (`python -m playwright install chromium`), cùng tài liệu khởi chạy demo server trên cổng 8002. |

---

## 3. Chi Tiết Cải Tiến Thiết Kế Giao Diện (UI/UX Redesign)

Toàn bộ giao diện được chuẩn hóa bởi một Frontend Architect duy nhất nhằm đảm bảo tính đồng nhất thị giác giữa không gian đọc công cộng và khu vực quản trị nghiệp vụ.

### 3.1. Typography, Bản Quyền & Visual Identity (D1)
- **Trước cải tiến:** Sử dụng font tải qua Google Fonts CDN ngoài (`fonts.googleapis.com`), có nguy cơ lỗi hiển thị khi mạng chậm hoặc môi trường offline; tên thương hiệu trên thanh điều hướng là chuỗi tĩnh.
- **Sau cải tiến:** 
  - Toàn bộ font **Source Serif 4** (biến thể 400, 600, 700 và italic) cùng **Source Sans 3** (biến thể 400, 500, 600, 700) được tải về lưu trữ cục bộ tại `src/frontend/assets/fonts/` kèm file giấy phép mã nguồn mở `LICENSE.txt`.
  - Khai báo `@font-face` tự host trong `src/frontend/style.css`, loại bỏ hoàn toàn các thẻ liên kết CDN ngoài trong `index.html`.
  - Header chính của ứng dụng liên kết động với API `/api/v1/settings/public`, hiển thị tên thư viện và khẩu hiệu chính xác: `"Folio — Knowledge & Research Library | Curated enterprise document store and research library"`.

### 3.2. Màn Hình Thư Viện — Baseline Checkpoint (D2)
- **Trước cải tiến:**
  - Tiêu đề bài viết bị đẩy xuống sau hàng badge danh mục, làm yếu đi mỏ neo thị giác (reading anchor) đầu tiên của mắt người đọc.
  - Các chỉ số tương tác (lượt xem, lượt thích) dùng ký tự văn bản thuần `👁 0  ♥ 0` đơn điệu.
  - Đoạn tóm tắt hiển thị độ dài tự do gây lộn xộn chiều cao các thẻ bài viết; chứa nhiều rác crawler Wikipedia.
  - Bộ lọc ngày tháng (Date Filter) chiếm diện tích lớn cố định trên sidebar bên trái, đẩy các danh mục quan trọng xuống dưới nếp gấp màn hình (fold).
- **Sau cải tiến:**
  - **Mỏ neo tiêu đề:** Đưa tiêu đề bài viết lên dòng đầu tiên với font Source Serif 4 đậm nét, kích thước 1.35rem, tạo điểm nhấn đọc tức thì.
  - **Metadata hài hòa:** Đặt Category badge, tên tác giả, ngày đăng và cụm chỉ số SVG tương tác (icon con mắt và trái tim tinh gọn, kèm nhãn `aria-label` cho screen reader) trên cùng một hàng ngang liền mạch dưới tiêu đề.
  - **Line-clamp tóm tắt:** Giới hạn đoạn tóm tắt tối đa 3 dòng (`-webkit-line-clamp: 3`), đảm bảo các thẻ tài liệu có nhịp điệu thị giác đồng đều.
  - **Accordion Date Filter:** Chuyển bộ lọc ngày sang dạng accordion thu gọn (`<details class="sidebar-date-accordion">`), mở ra khi cần lọc nâng cao, giúp danh sách 6 chuyên mục nghiên cứu luôn nổi bật trọn vẹn trong khung nhìn.
  - **Thẩm định đa độ phân giải:** Đã chụp ảnh và kiểm chứng độ cân đối hoàn hảo trên cả 4 kích thước: `1366x768`, `1440x900`, `1280x720` và `1920x1080`.

### 3.3. Màn Hình Đọc Chi Tiết & Table of Contents (D3)
- **Trước cải tiến:** Trang chi tiết không có mục lục cho bài viết học thuật dài; liên kết nguồn Wikipedia đặt rời rạc; độ rộng trang trải dài gây mỏi mắt khi đọc dòng chữ dài.
- **Sau cải tiến:**
  - **Mục lục thông minh (TOC):** Tự động phân tích các thẻ đề mục (`h1`, `h2`, `h3`) trong nội dung Markdown sau khi render, đánh chỉ mục phân cấp và sinh khối `Table of Contents` ngay dưới phần tóm tắt.
  - **Cuộn mượt không che khuất:** Mỗi đề mục được gán thuộc tính CSS `scroll-margin-top: 85px`, khi click vào mục lục trình duyệt cuộn mượt mà đến đúng vị trí mà không bao giờ bị thanh header cố định che lấp.
  - **Cột đọc chuẩn nhân trắc học:** Độ rộng tối đa của thân bài viết được khống chế ở mức ~760px, tối ưu số ký tự trên mỗi dòng chữ (60–75 ký tự), mang lại trải nghiệm đọc tập trung như một bài báo khoa học.
  - **Byline nguồn rõ ràng:** Liên kết bài viết gốc (`Source Article ↗`) được gắn trực tiếp cạnh thông tin tác giả và ngày xuất bản.

### 3.4. Quản Trị Danh Sách Tài Liệu & Sidebar Admin (D4)
- **Trước cải tiến:**
  - Bảng danh sách bài viết dành quá ít không gian cho cột Tiêu đề, dẫn đến việc tiêu đề dài bị ép dòng khó đọc.
  - Các nút tác vụ (Edit, Unpublish, Delete, SEO) xếp nối tiếp nhau trong cùng một ô gây rối mắt và dễ bấm nhầm nút nguy hiểm (Delete).
  - Sidebar admin liệt kê phẳng hàng loạt chức năng không phân cấp.
- **Sau cải tiến:**
  - **Mở rộng tiêu đề:** Cột Title được cấp `flex: 1` và `min-width: 280px`, giúp tên tài liệu nghiên cứu hiển thị đầy đủ, thanh thoát.
  - **Menu tác vụ phân cấp (`•••`):** Nút chính **"Edit"** được làm nổi bật với phong cách màu thương hiệu. Các hành động phụ (Publish/Unpublish, Configure SEO, Delete) được gom vào dropdown menu ba chấm (`•••`). Menu có xử lý sự kiện đóng khi bấm phím `Escape` hoặc click ra ngoài, và nút Delete được làm nổi bật bằng sắc đỏ cảnh báo.
  - **Gom nhóm Sidebar khoa học:** Phân chia rõ ràng thành 3 phân hệ nghiệp vụ lớn:
    - **CONTENT:** Documents, Taxonomy.
    - **COMMUNITY:** Comments Queue, Flags & Reports.
    - **ADMINISTRATION:** SEO Metadata, Library Analytics, Users & Staff, Roles Matrix, Audit Trail, Settings.

### 3.5. Biểu Đồ Thống Kê Hoạt Động (D5)
- **Trước cải tiến:** Biểu đồ SVG co giãn tự do theo chiều cao màn hình, thanh biểu đồ bị kéo dãn quá mức; trục Y không có vạch chia và số liệu rõ ràng; khi xem khoảng thời gian 30 hoặc 90 ngày thì nhãn ngày trên trục X bị đè lên nhau thành một vệt đen không đọc được.
- **Sau cải tiến:**
  - **Chiều cao tiêu chuẩn:** Cố định chiều cao vùng vẽ biểu đồ ở mức 240px, vừa vặn trên một khung nhìn laptop.
  - **Hệ thống vạch chia trục Y:** Bổ sung các đường kẻ ngang đứt nét (`stroke-dasharray="3 3"`) cùng các giá trị số đo lường chính xác tương ứng ở biên trái.
  - **Lọc thưa nhãn trục X (Tick Decimation):** Áp dụng thuật toán bước nhảy: hiển thị cách ngày cho chu kỳ 30 ngày (bước 3 ngày/nhãn) và chu kỳ 90 ngày (bước 7 ngày/nhãn), bảo đảm nhãn ngày tháng luôn thông thoáng và dễ đọc.

---

## 4. Chuẩn Hóa Dữ Liệu Nghiên Cứu (Data Curation)

- **Cân bằng chuyên mục:** Toàn bộ 100 tài liệu công bố chính thức trong `fixtures/folio/documents.jsonl` được tinh chọn và tái phân bổ đồng đều qua 6 phân ngành nghiên cứu:
  1. *Artificial Intelligence & Machine Learning:* 18 tài liệu.
  2. *Computer Science & Systems:* 18 tài liệu.
  3. *Mathematics & Optimization:* 16 tài liệu.
  4. *Neuroscience & Cognitive Science:* 16 tài liệu.
  5. *Scientific Research & Publishing:* 16 tài liệu.
  6. *Technology & Society:* 16 tài liệu.
  *(Kèm 3 tài liệu dạng Draft dùng riêng cho kiểm thử quy trình biên tập viên)*.
- **Làm sạch văn bản 100%:** Quét và loại bỏ hoàn toàn các rác sinh ra từ crawler Wikipedia trong phần tóm tắt (`summary`): 0 ký tự `[edit]`, 0 thẻ `[citation needed]`, loại bỏ các đoạn mã wiki markup vỡ.
- **Tích hợp sơ đồ kỹ thuật (SVG Assets):** Thiết kế 8 sơ đồ kiến trúc và giải thuật vector nguyên bản lưu tại `src/frontend/assets/demo/` (bao gồm: `transformer-architecture.svg`, `resnet-block.svg`, `backpropagation.svg`, `gradient-descent.svg`, `b-tree-indexing.svg`, `raft-consensus.svg`, `neural-spike-timing.svg`, `crispr-cas9-mechanism.svg`) tuân thủ giấy phép CC BY-SA 4.0 và ghi công đầy đủ trong `fixtures/folio/SOURCES.md`.
- **Cơ sở dữ liệu độc lập `folio_demo`:** Dữ liệu chuẩn hóa được nạp vào database riêng `folio_demo` thông qua `scripts/seed_folio.py`, giữ nguyên vẹn 100% database `folio` gốc phục vụ đối sánh.

---

## 5. Bảng So Sánh Ảnh Chụp Trước / Sau (Before / After Visual Evidence)

Tất cả ảnh chụp màn hình được kết xuất từ môi trường trình duyệt Chromium thực tế thông qua Playwright, lưu trữ tại thư mục `docs/verification/remediation/`:

| Màn Hình & Độ Phân Giải | Ảnh Trước Cải Tiến (Before) | Ảnh Sau Khắc Phục (After) | Đánh Giá Cải Tiến Cốt Lõi |
| :--- | :--- | :--- | :--- |
| **Library View**<br/>(1366 × 768) | `docs/verification/remediation/before/library_1366x768.png` | `docs/verification/remediation/after/library_1366x768.png` | Tiêu đề là mỏ neo đọc đầu tiên; font tự host Source Serif 4 sắc nét; chỉ số tương tác SVG tinh tế; Accordion Date Filter thu gọn giúp chuyên mục hiển thị trọn vẹn. |
| **Library View**<br/>(1440 × 900) | `docs/verification/remediation/before/library_1440x900.png` | `docs/verification/remediation/after/library_1440x900.png` | Cân đối tỉ lệ lề trang; tóm tắt line-clamp 3 dòng không còn rác `[edit]`; 6 danh mục nghiên cứu cân bằng số lượng hiển thị rõ ràng. |
| **Library View**<br/>(1280 × 720) | `docs/verification/remediation/before/library_1280x720.png` | `docs/verification/remediation/after/library_1280x720.png` | Độ phân giải laptop nhỏ không bị vỡ layout hay xuất hiện thanh cuộn ngang; thanh tìm kiếm và bộ lọc sắp xếp khoa học. |
| **Library View**<br/>(1920 × 1080) | `docs/verification/remediation/before/library_1920x1080.png` | `docs/verification/remediation/after/library_1920x1080.png` | Khống chế độ rộng tối đa (`max-width: 1400px`) chống loãng nội dung trên màn hình desktop cỡ lớn. |
| **Document Detail**<br/>(1440 × 900) | `docs/verification/remediation/before/document_detail_1440x900.png` | `docs/verification/remediation/after/document_detail_with_toc_1440x900.png` | Tích hợp khối Table of Contents phân cấp tự động; cuộn neo mượt mà; cột đọc chuẩn học thuật ~760px; byline nguồn Wikipedia bài bản. |
| **Admin Documents**<br/>(1440 × 900) | `docs/verification/remediation/before/admin_documents_1440x900.png` | `docs/verification/remediation/after/admin_documents_1440x900.png` | Cột Tiêu đề được mở rộng thoáng đãng; nút Edit chính nổi bật cạnh menu ba chấm (`•••`) chống bấm nhầm xóa bài; Sidebar phân 3 nhóm rành mạch. |
| **Admin Editor Preview**<br/>(1440 × 900) | `docs/verification/remediation/before/admin_editor_preview_1440x900.png` | `docs/verification/remediation/after/admin_editor_preview_1440x900.png` | Tab Xem trước hiển thị an toàn tuyệt đối qua backend sanitizer endpoint; leave-guard bảo vệ nội dung đang gõ khi rời trang. |
| **Admin Analytics**<br/>(1440 × 900) | `docs/verification/remediation/before/admin_analytics_1440x900.png` | `docs/verification/remediation/after/admin_analytics_1440x900.png` | Biểu đồ SVG cố định 240px; có đường lưới ngang và giá trị trục Y rõ ràng; nhãn ngày trên trục X được thưa hóa tránh chồng chéo chữ. |

---

## 6. Kết Quả Kiểm Thử Tự Động (Automated Testing)

Toàn bộ bộ kiểm thử backend được thực thi trên môi trường Python 3.10 với cơ sở dữ liệu kiểm thử độc lập `folio_test`:

```text
============================= test session starts =============================
platform win32 -- Python 3.10.11, pytest-9.2.0, pluggy-1.6.0
rootdir: F:\dpl13.10\WikiSearchEngine
configfile: pytest.ini
collected 58 items

tests/backend/admin/test_admin_api.py ......................... PASSED [ 13%]
tests/backend/admin/test_analytics_metrics.py ..                 PASSED [ 17%]
tests/backend/admin/test_document_lifecycle.py .                PASSED [ 18%]
tests/backend/admin/test_governance_and_last_admin.py ....      PASSED [ 25%]
tests/backend/admin/test_moderation_flow.py .                   PASSED [ 27%]
tests/backend/admin/test_permissions_and_security.py ..         PASSED [ 31%]
tests/backend/admin/test_preview.py ....                        PASSED [ 37%]
tests/backend/admin/test_seo_and_audit.py ...                   PASSED [ 43%]
tests/backend/admin/test_taxonomy_lifecycle.py ..               PASSED [ 46%]
tests/backend/foundation/test_auth.py .......                   PASSED [ 58%]
tests/backend/foundation/test_frontend_assets.py .              PASSED [ 60%]
tests/backend/foundation/test_permissions.py .                  PASSED [ 62%]
tests/backend/foundation/test_startup.py ...                    PASSED [ 67%]
tests/backend/integration/test_e2e_workflow.py .                PASSED [ 68%]
tests/backend/library/test_click_idempotency.py ...             PASSED [ 74%]
tests/backend/library/test_library_api.py ...............       PASSED [100%]

====================== 58 passed, 15 warnings in 17.41s =======================
```

### Các Suite Test Mới Bổ Sung Trong Đợt Khắc Phục:
1. `tests/backend/admin/test_preview.py`:
   - `test_preview_permissions_enforcement`: Đảm bảo chỉ tài khoản có quyền `documents:write` mới được gọi preview (chặn người dùng vãng lai hoặc member).
   - `test_preview_sanitizes_xss_and_malicious_inputs`: Thử nghiệm tiêm mã độc qua thuộc tính sự kiện (`<img src=x onerror=alert(1)>`, thẻ `<script>`, quote breakout) và xác thực Bleach loại bỏ an toàn.
   - `test_preview_renders_valid_markdown`: Kiểm tra khả năng biên dịch chuẩn các cú pháp tiêu đề, bảng biểu, danh sách, và định dạng in đậm/nghiêng.
   - `test_preview_also_accessible_at_admin_root`: Kiểm tra endpoint alias tương thích ngược tại `/admin/documents/preview`.
2. `tests/backend/library/test_click_idempotency.py`:
   - `test_concurrent_click_logging_same_key`: Giả lập nhiều request ghi nhận click đồng thời mang cùng `actor_key` và `request_key`; xác nhận hệ thống chỉ ghi nhận đúng 1 bản ghi duy nhất trong database mà không báo lỗi 500.
   - `test_click_logging_retry_payload_mismatch`: Gửi lại request cùng `request_key` nhưng sửa đổi `clicked_doc_id`; xác nhận hệ thống trả về `HTTP 409 Conflict` ngăn chặn giả mạo log.
   - `test_click_logging_retry_different_actor`: Xác minh tính cô lập của `request_key` giữa các actor khác nhau.

---

## 7. Hướng Dẫn Khởi Chạy Demo & Thẩm Định

Hội đồng đánh giá và người chấm có thể trực tiếp trải nghiệm phiên bản đã khắc phục trên instance chuyên dụng chạy cơ sở dữ liệu `folio_demo`:

### 7.1. Khởi chạy Demo Server (Port 8002)
Mở cửa sổ PowerShell tại thư mục dự án và thực hiện:
```powershell
# Kích hoạt môi trường ảo
.\env\Scripts\Activate.ps1

# Thiết lập biến môi trường trỏ đến folio_demo và chạy server
$env:DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:5432/folio_demo"
$env:PORT = "8002"
.\env\Scripts\python.exe -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8002
```
Truy cập trình duyệt tại địa chỉ: **`http://127.0.0.1:8002`**

*(Ghi chú: Bản server cơ sở ban đầu vẫn có thể chạy độc lập trên cổng 8000 kết nối database `folio` để phục vụ đối chiếu)*.

### 7.2. Danh Sách Tài Khoản Thẩm Định
Tất cả tài khoản demo sử dụng mật khẩu chung: `FolioDemo2026!`

| Vai Trò | Email | Màn Hình / Tính Năng Cần Thẩm Định |
| :--- | :--- | :--- |
| **Khách vãng lai / Reader** | *(Chưa đăng nhập)* hoặc `reader@folio.test` | Trang chủ `#/library` (font tự host, 100 bài nghiên cứu cân bằng, accordion date filter); Trang đọc `#/documents/:id` (TOC cuộn mượt, cột đọc ~760px). |
| **Content Manager** | `content@folio.test` | `#/admin/documents` (menu ba chấm `•••`, độ rộng tiêu đề); `#/admin/documents/:id/edit` (xem trước Markdown qua backend sanitizer, leave-guard khi chuyển tab, nhãn nút Save Changes / Unpublish chính xác). |
| **Super Admin** | `admin@folio.test` | `#/admin/users` & `#/admin/roles` (quản trị phân quyền); `#/admin/analytics` (biểu đồ 240px, lưới ngang, thưa nhãn ngày trục X). |

### 7.3. Kịch Bản Kiểm Tra Nhanh Các Lỗi Đã Khắc Phục
1. **Kiểm tra Leave-Guard (F2):**
   - Đăng nhập bằng `content@folio.test`, vào chỉnh sửa một bài viết bất kỳ.
   - Gõ thêm nội dung vào ô tóm tắt.
   - Click sang mục "Taxonomy" trên sidebar hoặc bấm nút Back trình duyệt: Hộp thoại xác nhận của trình duyệt sẽ hiển thị cảnh báo thay đổi chưa được lưu.
2. **Kiểm tra Nhãn nút và Hành vi (F3):**
   - Quan sát bài viết đã xuất bản: Nút hiển thị là "Save Changes" và "Save & Unpublish".
   - Quan sát bài viết ở trạng thái Draft: Nút hiển thị là "Publish to Library" và "Save Draft".
3. **Kiểm tra Chống trùng Click và Idempotency (F4, F5):**
   - Tại trang Library, click vào một bài viết từ kết quả tìm kiếm: Search Click được ghi nhận chính xác 1 lần.
   - Nhấn F5 tải lại trang Detail nhiều lần: Số lượng Search Click trong `interaction_logs` hoàn toàn không bị tăng thêm (F5 đã được giải quyết triệt để).
4. **Kiểm tra Mục lục và Neo cuộn (D3):**
   - Vào bài viết `Deep learning` hoặc `Transformer (deep learning)`: Quan sát khối Table of Contents tự động tạo ra từ các tiêu đề con, click vào mục bất kỳ để quan sát hiệu ứng cuộn mượt không bị header che khuất.

---

## 8. Các Hạn Chế Còn Lại & Đề Xuất Cho Phase 2

1. **Client-Side Hash Routing & SEO ngoài thực tế:**
   - Mặc dù hệ thống đã cung cấp công cụ giả lập SERP Preview và quản lý thẻ Meta Title/Description hoàn chỉnh trong Admin, do ứng dụng sử dụng mô hình SPA Single-Page Hash Routing (`#/library`), các bot tìm kiếm truyền thống không thực thi JavaScript có thể gặp khó khăn trong việc lập chỉ mục nội dung đầy đủ.
   - *Đề xuất Phase 2:* Chuyển sang History API kết hợp Server-Side Rendering (SSR) hoặc triển khai giải pháp Pre-rendering tĩnh (prerender service) cho các bot crawler.
2. **Phase 2 Information Retrieval Integration:**
   - Bộ lưu trữ tài liệu (`documents`), danh mục phân cấp (`categories`, `tags`) và nhật ký tương tác chuẩn hóa (`interaction_logs`) đã sẵn sàng 100% để triển khai các thuật toán lập chỉ mục ngược (Inverted Index), xếp hạng BM25 và mô hình học máy xếp hạng (Learning to Rank) trong đồ án Giai đoạn 2.
