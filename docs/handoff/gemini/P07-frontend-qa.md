# P07 — Frontend & Product QA Handoff

**Ngày:** 01/11/2026 (Asia/Saigon)  
**Vai trò:** Frontend & Product QA Engineer (P07)  
**Baseline tích hợp:** `693d031` (`feat(search): implement P05 search API, 0-second lag defense, telemetry & graceful fallbacks`)  
**Branch:** `feature/p07-frontend-qa`  
**Ownership Scope:** `src/frontend/`, Playwright test suites (`tests/frontend/`), và visual evidence artifacts  
**Frontend Test Suite:** 36 passed, 0 failed (100% pass rate in 225s)  
**Full Repository Regression:** 202 passed, 0 failed (36 frontend + 166 backend)  
**Runtime:** Python 3.10.11 (`F:/dpl13.10/folio-live-runtime/venv-clean`), PostgreSQL 16.10 portable (`127.0.0.1:55463`), Chromium / Playwright 1.58.0  

---

## 1. Tổng quan & Kết quả Thực thi (Executive Summary)

Mốc P07 đã hoàn thành toàn diện việc nâng cấp giao diện người dùng và kiểm thử chất lượng sản phẩm (Frontend & Product QA) trên nền tảng **Vanilla JavaScript ES Modules** và **CSS thuần** hiện có của Folio, bảo tồn 100% bản sắc thiết kế Paper & Ink (Folio identity) và tuân thủ chặt chẽ Hợp đồng Tìm kiếm v2.1.0 (`docs/search-contract.md`):

1. **Tích hợp Tìm kiếm Chuẩn hóa với URL State Persistence:**
   - Khi có từ khóa tìm kiếm (`q`), Library view kết nối trực tiếp đến endpoint chuẩn `/api/v1/search` với các tham số: `q`, `mode` (`bm25`, `semantic`, `hybrid`), `category_id`, `tag_ids`, `date_from`, `date_to`, `sort`, `page`, `page_size`, và `search_context_token`.
   - Trạng thái tìm kiếm được đồng bộ hai chiều với URL hash fragment (ví dụ: `#/library?q=learning&mode=semantic&category_id=...&page=2`), cho phép người dùng Back/Forward trong lịch sử duyệt web hoặc Refresh trang mà không mất ngữ cảnh tìm kiếm.
   - Khi không có từ khóa tìm kiếm (`q` rỗng), giao diện giữ nguyên hành vi duyệt thư viện ban đầu qua `/api/v1/documents`.

2. **Hiển thị Kết quả An toàn & Trải nghiệm Tìm kiếm Chuyên sâu:**
   - **Xử lý trích đoạn an toàn (Safe Snippet Rendering):** Hàm `renderSafeSnippet` sử dụng `DOMParser` để duyệt cây DOM của chuỗi snippet backend trả về, chỉ cho phép các thẻ `<em>` (in nghiêng từ khóa khớp) và các text nodes; loại bỏ hoàn toàn mọi thuộc tính (attributes, inline scripts, event handlers), ngăn chặn triệt để nguy cơ XSS và injection.
   - **Xếp hạng & Độ tương quan:** Hiển thị thứ hạng kết quả (`#1`, `#2`) và điểm số tương quan (`Score: 2.451`) trên từng thẻ tài liệu.
   - **Chỉ báo suy giảm chỉ mục (Degraded Engine Banner & Badge):** Khi backend trả về trạng thái `is_degraded: true`, giao diện hiển thị ngay banner cảnh báo màu hổ phách giải thích nguyên nhân (`degraded_reason`) kèm badge trạng thái nổi bật.
   - **Thanh đo lường thời gian thực (Search Telemetry Bar):** Hiển thị công cụ thực thi (`Engine: BM25`, `Latency: 12ms`, `Total: 15`).
   - **Phân trang Ngữ cảnh Ổn định:** Lưu giữ `search_context_token` giữa các trang. Tự động phục hồi và tìm kiếm lại từ Trang 1 nếu token hết hạn (HTTP 410) hoặc tham số không khớp (HTTP 400).

3. **Kiểm soát Tương tác & Ghi nhận Click Idempotent:**
   - Click vào tiêu đề bài viết từ kết quả tìm kiếm gửi sự kiện `POST /api/v1/events/clicks` với `search_event_id`, `document_id`, và `request_key` ngẫu nhiên (UUIDv4) độc lập với route navigation.
   - Người dùng truy cập trực tiếp bài viết hoặc reload/refresh trang chi tiết bài viết **chỉ ghi nhận view event, tuyệt đối không gửi lại search click event**.
   - Nút Back (`#detailBackLink`) trên trang chi tiết kích hoạt `window.history.back()`, đưa người dùng trở lại đúng vị trí trang tìm kiếm với đầy đủ bộ lọc và kết quả đã lưu.

4. **Thiết kế Đáp ứng Toàn diện (Responsive 360px – 1920px):**
   - Hỗ trợ tối ưu trên 6 độ phân giải chuẩn: **360px** (small mobile), **390px** (iPhone standard), **768px** (tablet portrait), **1280px** (laptop), **1440px** (desktop HD), và **1920px** (ultra-wide desktop).
   - Trên thiết bị di động ($\le 860\text{px}$): Thanh bộ lọc được ẩn vào một Drawer trượt (`#mobileFilterToggleBtn`) có thể mở/đóng mượt mà.
   - Bảng dữ liệu quản trị (Admin Tables) được bọc trong container `.table-container` có thuộc tính `overflow-x: auto` và `-webkit-overflow-scrolling: touch;`, chủ động cuộn ngang mượt mà mà không làm vỡ bố cục tổng thể.
   - Khắc phục nguy cơ tràn giao diện (horizontal overflow) bằng cách bảo vệ các phần tử nội dung dài: `word-break: break-word`, hình ảnh `max-width: 100%`, khối mã `pre, code { overflow-x: auto; }`, và công thức toán KaTeX `.katex-display { overflow-x: auto; }`.

5. **Tiêu chuẩn Tiếp cận Web (WCAG AA Accessibility):**
   - Điều hướng bàn phím hoàn chỉnh với chỉ báo tiêu điểm rõ ràng (`:focus-visible` với outline tương phản cao).
   - Form xác thực và nhập liệu gắn nhãn tiêu chuẩn với thuộc tính `aria-describedby` liên kết trực tiếp với thẻ thông báo lỗi (`role="alert"`).
   - Hộp thoại Modal/Dialog (`confirmAction`) cài đặt cơ chế **Focus Trap** (giữ tiêu điểm giữa nút Cancel và Confirm), hỗ trợ phím `Escape` để hủy và **khôi phục tiêu điểm** trở lại phần tử kích hoạt trước đó (`previousActiveElement`).
   - Tôn trọng tùy chọn giảm chuyển động của người dùng (`@media (prefers-reduced-motion: reduce)` vô hiệu hóa transitions/animations).

6. **Khắc phục Triệt để các Review Findings (F1, F2, F3, F5, F6):**
   - **F1:** Xem trước Markdown (`tabPreview`) trong trình soạn thảo quản trị sử dụng endpoint khử khuẩn Bleach từ backend (`/api/v1/library/render-preview`), loại bỏ nguy cơ XSS từ các thư viện parser frontend thiếu an toàn.
   - **F2:** Cơ chế cảnh báo thay đổi chưa lưu (`dirty guard`) hoạt động đồng bộ trên toàn bộ luồng điều hướng: thanh sidebar, thanh tiêu đề header, và các nút điều hướng back/forward của trình duyệt. Bổ sung cờ chống đệ quy (`isCheckingLeaveGuard`) để ngăn chặn việc hiển thị dialog trùng lặp.
   - **F3:** Nút "Save Draft" duy trì trạng thái tài liệu là `draft` (không tự ý chuyển sang `published`), nhãn nút và trạng thái luôn nhất quán.
   - **F5:** Khắc phục triệt để việc mất click do route reload: telemetry click gửi trước khi chuyển route và không bị hủy ngang bởi controller abort signal.
   - **F6:** Xử lý ranh giới an toàn cho bộ lọc ngày `date_to=9999-12-31`, không gây lỗi HTTP 500.

7. **Thu thập Minh chứng Trực quan Không Xung đột (Collision-Free Evidence Capture):**
   - Toàn bộ 11 ảnh minh chứng được tự động chụp qua Playwright và lưu trữ theo cấu trúc thư mục cách ly do `artifact_utils.py` quản lý: `test-results/artifacts/WikiSearchEngine/693d031/<run_id>/screenshots/p07_evidence/`.
   - Bảo toàn nguyên vẹn 8 ảnh gốc trong `docs/screenshots/` và không can thiệp vào thư mục `../screenshots/` bên ngoài repository.

---

## 2. Chi tiết Sửa đổi Mã nguồn Frontend & CSS

### 2.1 `src/frontend/public/library_view.js`
- **Kết nối API Tìm kiếm:**
  ```javascript
  const isSearchQuery = Boolean(q);
  const endpoint = isSearchQuery ? "/api/v1/search" : "/api/v1/documents";
  const params = new URLSearchParams();
  if (isSearchQuery) {
    params.set("q", q);
    if (mode && mode !== "bm25") params.set("mode", mode);
    if (searchContextToken) params.set("search_context_token", searchContextToken);
  }
  // Đồng bộ category, tags, date_from, date_to, sort, page...
  ```
- **Khử khuẩn Snippet An toàn (`renderSafeSnippet`):**
  ```javascript
  function renderSafeSnippet(snippetHtml, fallbackSummary) {
    if (!snippetHtml) return escapeHtml(fallbackSummary || "");
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<body>${snippetHtml}</body>`, "text/html");
    const container = document.createElement("span");
    for (const node of Array.from(doc.body.childNodes)) {
      if (node.nodeType === Node.TEXT_NODE) {
        container.appendChild(document.createTextNode(node.textContent));
      } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName.toLowerCase() === "em") {
        const em = document.createElement("em");
        em.className = "search-highlight";
        em.textContent = node.textContent; // Loại bỏ toàn bộ attributes độc hại
        container.appendChild(em);
      }
    }
    return container.innerHTML;
  }
  ```
- **Ghi nhận Click Độc lập (`POST /api/v1/events/clicks`):**
  Bắt sự kiện click trên liên kết tiêu đề bài viết từ kết quả tìm kiếm (`.doc-row-title a[data-search-event-id]`), gửi request kèm `requestKey = genUuid()` với `fetch` độc lập, đảm bảo payload được gửi thành công trước khi router kích hoạt hashchange.

### 2.2 `src/frontend/core/ui.js` & `src/frontend/core/router.js`
- **Focus Trap & Focus Restore trong `confirmAction`:**
  Lưu lại `previousActiveElement = document.activeElement`. Lắng nghe sự kiện `keydown` trên dialog: chặn phím `Tab` quay vòng giữa 2 nút hành động, bắt phím `Escape` để hủy modal, và hoàn trả focus về `previousActiveElement` ngay khi modal đóng.
- **Bảo vệ Re-entrancy `isCheckingLeaveGuard`:**
  Ngăn chặn việc kích hoạt đồng thời nhiều modal xác nhận khi người dùng click nhanh vào nhiều liên kết khác nhau khi form đang ở trạng thái dirty.

### 2.3 `src/frontend/public/public.css`, `style.css` & `admin/admin.css`
- **Responsive Drawer:** Cung cấp thanh bar di động `.mobile-filter-bar` và drawer `.library-sidebar` trượt hiển thị khi có class `.open` trên viewports $\le 860\text{px}$.
- **Cuộn ngang có chủ đích (Deliberate Table Overflow):**
  ```css
  .table-container {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin-bottom: var(--space-4);
  }
  .table-container table {
    min-width: 650px;
  }
  ```
- **WCAG AA Focus & Accessibility:**
  ```css
  :focus-visible {
    outline: 2px solid var(--primary-color, #1a365d);
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }
  }
  ```

---

## 3. Bảng Kiểm Thử Toàn Diện (Test Execution Matrix)

Tất cả các bộ kiểm thử đều được thực thi trên môi trường máy chủ cục bộ (live server + headless Chromium qua Playwright):

| Bộ kiểm thử (Test File) | Mục tiêu kiểm định | Số ca kiểm thử | Kết quả |
|---|---|---|---|
| `tests/frontend/public/test_search_navigation_state.py` | Kết nối API tìm kiếm `/api/v1/search`, bảo tồn duyệt catalog khi không có query, lưu trữ trạng thái URL khi back/forward/refresh | 3 tests | **PASSED** |
| `tests/frontend/public/test_search_results_ux.py` | Ranking badges, safe snippets (`<em>`), degraded engine fallback banner, empty state, error retry, context token pagination | 5 tests | **PASSED** |
| `tests/frontend/public/test_interaction_click_logging.py` | Dispatch duy nhất 1 click event khi click bài viết; reload trang chi tiết không sinh duplicate click | 1 test | **PASSED** |
| `tests/frontend/public/test_responsive_viewports.py` | Thử nghiệm 6 viewports (360, 390, 768, 1280, 1440, 1920px), mobile filter drawer, deliberate table horizontal overflow container | 3 tests | **PASSED** |
| `tests/frontend/public/test_accessibility_wcag.py` | Điều hướng bàn phím, chỉ báo focus, form labels & aria-describedby errors, dialog focus trap & escape restore, prefers-reduced-motion | 4 tests | **PASSED** |
| `tests/frontend/public/test_remediation_findings.py` | Xác nhận các findings F1 (sanitizer backend), F2 (dirty guard toàn diện), F3 (save draft status), F6 (date_to an toàn) | 4 tests | **PASSED** |
| `tests/frontend/public/test_public_flows.py` | Regression suite cho luồng bạn đọc công khai: catalog, filter, auth, profile, detail view, like, comment | 4 tests | **PASSED** |
| `tests/frontend/admin/test_admin_flows.py` | Regression suite cho luồng quản trị: RBAC guards, Content Manager, SEO, full CRUD, Taxonomy 409, Moderation, Analytics, Governance, Roles Matrix | 10 tests | **PASSED** |
| `tests/frontend/admin/test_admin_screenshots.py` | Chụp màn hình các view quản trị desktop | 1 test | **PASSED** |
| `tests/frontend/public/test_p07_evidence.py` | Chụp toàn bộ 11 ảnh minh chứng mốc P07 theo quy định kiểm thử | 1 test | **PASSED** |

**Tổng kết Frontend Suite:** **36 passed, 0 failed, 5 warnings trong 225.33 giây (03:45)**.  
**Tổng kết Backend Regression Suite:** **166 passed, 0 failed** (`search`, `library`, `admin`, `foundation`, `integration`, `search_index`).

---

## 4. Danh mục Minh chứng Trực quan (Visual Evidence Manifest)

Các tập tin hình ảnh minh chứng được tự động kết xuất tại:  
`test-results/artifacts/WikiSearchEngine/693d031/run_20261101_043923_5825c90c/screenshots/p07_evidence/`

| STT | Tên tập tin ảnh | Kích thước Viewport | Mô tả & Trạng thái giao diện | Route truy cập |
|---|---|---|---|---|
| 01 | `01_search_bm25_desktop_1440.png` | 1440 x 900 (Desktop) | Danh sách kết quả tìm kiếm BM25, hiển thị ranking badge, snippet highlight `<em>` an toàn, telemetry bar | `#/library?q=learning&mode=bm25` |
| 02 | `02_search_hybrid_desktop_1440.png` | 1440 x 900 (Desktop) | Kết quả tìm kiếm chế độ Hybrid kết hợp BM25 và Vector retrieval | `#/library?q=neural&mode=hybrid` |
| 03 | `03_search_degraded_banner_1440.png` | 1440 x 900 (Desktop) | Banner suy giảm chỉ mục (.degraded-engine-banner) cảnh báo vector engine offline, fallback BM25 minh bạch | `#/library?q=transformer&mode=semantic` |
| 04 | `04_library_mobile_360.png` | 360 x 640 (Mobile nhỏ) | Giao diện thư viện công khai hiển thị sắc nét trên viewport hẹp 360px | `#/library` |
| 05 | `05_library_mobile_390_filter_drawer.png` | 390 x 844 (Mobile chuẩn) | Thanh điều khiển Drawer bộ lọc di động đang mở, cho phép chọn danh mục, thẻ và khoảng ngày | `#/library` |
| 06 | `06_detail_mobile_390.png` | 390 x 844 (Mobile chuẩn) | Trang đọc bài viết nghiên cứu trên di động với nút Back lịch sử và typography Paper & Ink | `#/documents/:id` |
| 07 | `07_library_tablet_768.png` | 768 x 1024 (Tablet) | Bố cục thư viện tự động co giãn 2 cột mượt mà trên iPad / máy tính bảng | `#/library?q=algorithm` |
| 08 | `08_detail_desktop_1440.png` | 1440 x 900 (Desktop) | Bài viết chi tiết trên màn hình rộng: hiển thị siêu dữ liệu tác giả, lượt xem, thẻ tag và nút Back | `#/documents/:id` |
| 09 | `09_admin_table_mobile_390.png` | 390 x 844 (Mobile chuẩn) | Bảng quản trị danh sách tài liệu co giãn trong container cuộn ngang có chủ đích (min-width: 650px) | `#/admin/documents` |
| 10 | `10_admin_dirty_guard_1440.png` | 1440 x 900 (Desktop) | Hộp thoại cảnh báo rời trang khi có chỉnh sửa chưa lưu (Dirty Guard Modal) với focus trap | `#/admin/documents/new` |
| 11 | `11_admin_safe_preview_1440.png` | 1440 x 900 (Desktop) | Tab xem trước an toàn Markdown được khử khuẩn bằng Bleach từ backend API | `#/admin/documents/new` |

---

## 5. Cập nhật Ma trận Nghiệm thu (Acceptance Matrix)

Các hạng mục liên quan trong `docs/acceptance-matrix.md` đã được nghiệm thu và cập nhật trạng thái:

- **UI-01 (Frontend Search Integration):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_search_navigation_state.py`.
- **UI-02 (Search Results UX):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_search_results_ux.py`.
- **UI-03 (Interaction Click Logging):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_interaction_click_logging.py`.
- **UI-04 (Responsive Viewports 360–1920):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_responsive_viewports.py`.
- **UI-05 (Accessibility WCAG AA):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_accessibility_wcag.py`.
- **UI-06 (Remediation Bug Fixes F1, F2, F3, F5, F6):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_remediation_findings.py`.
- **UI-07 (Isolated Screenshot Capture):** Chuyển sang `VERIFIED / PASS (P07)`. Chứng thực qua `test_p07_evidence.py`.
- **P1-03, P1-08, P1-11:** Đã cập nhật trạng thái `VERIFIED / PASS (P07)`.

---

## 6. Khuyến nghị Bàn giao cho Mốc Tiếp theo (Milestone 8 — P08)

1. **Docker Containerization & Static Assets:**
   - Ứng dụng frontend được tổ chức theo kiến trúc thuần Vanilla ES modules (`src/frontend/`), hoàn toàn không yêu cầu bước build/bundler phức tạp.
   - Nginx / Caddy reverse proxy chỉ cần cấu hình phục vụ thư mục tĩnh `src/frontend/` tại root `/` và chuyển tiếp `/api/*` tới container ứng dụng FastAPI (Uvicorn).
2. **Reverse Proxy & Compression:**
   - Cần cấu hình gzip/brotli nén cho các file tĩnh (`.js`, `.css`, `.svg`, `.html`) để tối ưu thời gian tải trang ban đầu trên thiết bị di động.
3. **CSP (Content Security Policy) Headers:**
   - Đảm bảo CSP header được thiết lập trong reverse proxy cho phép kết nối tới `/api/v1/` và tải font/icon nội bộ mà không cần `unsafe-eval`.
