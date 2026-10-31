# Folio: kế hoạch triển khai và bàn giao cho Antigravity

Ngày lập: 2026-10-31. Đây là kế hoạch, chưa phải các chức năng đã triển khai.

Đọc nhanh: [giao kèo kỹ thuật](CONTRACTS.md), [prompt điều phối tự động](prompts/00-orchestrator.md), hoặc bắt đầu thủ công bằng [prompt Foundation](prompts/01-foundation.md).

## 1. Đích đến và các quyết định đã chọn

Phát triển WikiSearchEngine thành **Folio — Knowledge & Research Library**, thuộc đề tài Enterprise Document & Research Repository trong `ASSIGNMENT.md`.

- Giữ Python/FastAPI và tái sử dụng bộ dữ liệu Wikipedia hiện có.
- Dùng PostgreSQL 16+, SQLAlchemy 2 và Alembic cho dữ liệu ứng dụng.
- Giữ HTML/CSS/JavaScript, chuyển sang ES modules; không chuyển framework trong đợt này.
- Ưu tiên hoàn thành Phase 1: CRUD, tài khoản, RBAC, tương tác, tìm kiếm cơ bản và log đúng schema.
- Giữ mã semantic search/BM25 cũ như một khả năng mở rộng; không bắt buộc khởi tạo model hoặc ChromaDB để dùng Folio.
- UI tiếng Anh nhất quán, phù hợp dữ liệu nguồn tiếng Anh; tài liệu bàn giao/README có thể dùng tiếng Việt. Đây là mặc định triển khai có thể đổi sau.
- Tập trung laptop/desktop: kiểm tra 1280x720, 1366x768, 1440x900, 1920x1080 và zoom trình duyệt 125% trên laptop.
- Không thiết kế, tối ưu hay chụp kiểm thử mobile trong đợt này. Dùng bố cục co giãn giữa các cỡ desktop. Đề gốc có yêu cầu responsive; phạm vi này chủ động chưa chứng minh trải nghiệm điện thoại và phải ghi đúng trong tài liệu nghiệm thu.
- Không mở rộng sang chat AI, recommendation, email verification, reset password qua email, OAuth, thanh toán, microservices hay Elasticsearch.

## 2. Hiện trạng đã kiểm tra

| Thành phần | Bằng chứng trong repo | Hướng xử lý |
|---|---|---|
| Backend | `src/backend/main.py` chỉ có `/search`, `/health` và static mount | Bổ sung `/api/v1`, auth, database và các module nghiệp vụ |
| Startup | `SearchService()` được tạo ở module scope; import kéo theo ML dependencies | Tách đường chạy Phase 1, lazy import cho legacy search |
| Dữ liệu | `data/raw/wiki_crawler_dataset.jsonl`, khoảng 140.8 MB ở máy hiện tại | Stream để chọn 100 bài thật; không tải toàn bộ vào RAM nếu không cần |
| Record nguồn | Crawler sinh `id`, `title`, `url`, `text`; text là Markdown | Chuyển sang schema Document, không coi crawler id là khóa toàn hệ thống |
| UI cũ | `src/frontend/index.html`, `style.css`, `app.js` | Thay bằng thư viện nhiều màn hình và admin, không chỉ đổi màu/logo |
| Search nâng cao | `search_service.py`, `utils/`, `src/indexing/`, `evaluate/`, `wiki_bot/` | Giữ nguyên thuật toán/crawler/evaluation trừ adapter startup cần thiết |
| Thay đổi có sẵn | `src/frontend/app.js` đã đổi API_BASE sang same-origin; `ASSIGNMENT.md` chưa tracked | Bảo toàn; không reset/checkout/revert hoặc ghi đè thiếu xem xét |
| Seed portability | `data/` đang bị gitignore | Commit fixture nhỏ ở `fixtures/folio/`, không đặt fixture bàn giao trong `data/` |

Không coi các chức năng ghi ở kế hoạch là đã có. Chạy `git status` và đọc hướng dẫn repo hiện hành trước khi thực hiện vì trạng thái có thể thay đổi sau ngày lập kế hoạch.

## 3. Luồng sử dụng cần hoàn thành

### Người đọc

1. Mở Library, thấy ngay tài liệu mới, danh mục và phân trang.
2. Tìm theo từ khóa; lọc danh mục, thẻ, khoảng ngày; URL giữ trạng thái khi Back/Forward/reload.
3. Mở trang tài liệu, đọc nội dung và metadata, xem hình minh họa khi có, đi đến nguồn.
4. Đăng ký/đăng nhập, cập nhật hồ sơ và đổi mật khẩu.
5. Like/unlike, viết/sửa/xóa bình luận của mình, nhắc `@username`, báo cáo bình luận.

### Nhân sự quản trị

- Content Manager: quản lý tài liệu, publish/unpublish, quản lý categories/tags.
- Moderator: xem bình luận và báo cáo; ẩn/hiện/đánh dấu spam; tạm chặn quyền bình luận của tài khoản gây spam.
- Data & SEO Specialist: sửa SEO title/description/keywords/image alt và xem analytics thật.
- Super Admin: toàn bộ quyền; quản lý tài khoản, vai trò, ma trận quyền, nhật ký và cấu hình.

User tagging được triển khai theo cách nhắc người dùng bằng `@username` trong bình luận. Đây là cách diễn giải yêu cầu chưa được đề mô tả chi tiết; ghi rõ trong báo cáo. Chọn **like**, không thêm hệ thống rating riêng vì đề cho phép rating/liking.

## 4. Hướng UI đủ cụ thể để thi công

Đây là brief cho bản thiết kế mới, chưa phải giao diện được xem và duyệt qua ảnh render.

- Nền giấy sáng `#F6F4EE`, bề mặt `#FFFFFF`, chữ xanh mực `#20323D`, màu nhấn teal `#16675B`, đường kẻ `#DADFD9`. Kiểm tra contrast thực tế trước khi chốt tokens.
- Heading tài liệu dùng Source Serif 4; UI dùng Source Sans 3. Tự host WOFF2 và lưu license; có fallback serif/sans-serif nếu không tải được font.
- Wordmark Folio đơn giản, không dùng lại logo WikiSearch, tagline kỹ thuật hay footer SEG301 của bản cũ ở UI chính.
- Library: header khoảng 68px, sidebar danh mục khoảng 220px, vùng kết quả rộng; dòng tài liệu phân cách mảnh thay vì lồng nhiều card. Có title, summary 2–3 dòng, category/tag, tác giả/ngày và lượt xem/thích.
- Đầu trang có tìm kiếm và thông tin thư viện hữu ích; không chiếm phần lớn màn hình bằng hero quảng cáo. Số tài liệu phải lấy từ API.
- Detail: cột đọc khoảng 72–80 ký tự/dòng, metadata rõ ràng, mục lục nếu bài có headings; nguồn và tương tác dễ tìm. Nội dung dài phải đọc được.
- Admin: sidebar điều hướng cố định, bảng có toolbar/filter/pagination; form biên tập trong trang riêng; dùng confirm cho thao tác xóa và cảnh báo khi rời form chưa lưu.
- Tách khu đọc và quản trị nhưng giữ chung typography, tokens, controls và trạng thái.
- Không đưa cosine/BM25/RRF thành các bảng điểm lớn ở mỗi tài liệu. Nếu bật legacy demo, đặt ở màn hình hoặc mục kỹ thuật riêng.
- Chỉ dùng chuyển trạng thái ngắn, có `prefers-reduced-motion`; không cần motion showcase.
- Bắt buộc có keyboard focus, label, loading/empty/error/403/404, tiêu đề dài, ảnh lỗi và phiên đăng nhập hết hạn. Không hy sinh khả năng dùng bàn phím vì không tối ưu mobile.

## 5. Checklist đối chiếu assignment

| Yêu cầu | Phần việc | Bằng chứng nghiệm thu |
|---|---|---|
| Home + directory | Danh sách published, snippet, pagination, sort mới nhất | Có 100 tài liệu thật, chuyển trang không lặp/mất do thứ tự không ổn định |
| Detail | Nội dung đầy đủ, image nếu có, author/date/views/category/tags | Xem bài dài, fallback ảnh và nguồn; draft/deleted không lộ qua URL |
| Authentication/profile | Đăng ký, đăng nhập, logout, sửa hồ sơ, đổi mật khẩu | Reload giữ session; lỗi sai mật khẩu; tài khoản disabled bị chặn |
| Engagement | Comment CRUD của mình, like toggle, @mention, report | Người khác không sửa/xóa được comment; không duplicate likes |
| Basic search | SQL keyword search + category/tag/date | Truy vấn tham số hóa; kết hợp filter; pagination và clear filters |
| Super Admin | Users, roles/permissions, audit, settings | Backend 403 với vai trò khác; không vô hiệu hóa admin cuối cùng |
| Content Manager | Document CRUD, publish state, taxonomy CRUD | Tạo -> sửa -> publish -> unpublish -> delete -> không public |
| Moderator | Review comments, reports, spam controls | Hide/spam/dismiss thực sự thay dữ liệu và được audit |
| Data & SEO | SEO title/description/alt/keywords + analytics | Refresh còn dữ liệu; analytics lấy từ DB, không chart giả |
| Document schema | Đủ các trường ở Section 5 của đề | API và DB mapping được ghi trong CONTRACTS.md |
| Search/click logs | user_id/query_string/clicked_doc_id/timestamp | Search và click là các event riêng có liên kết; guest có user_id null |
| Seed data | 100 bài thật, nguồn rõ, seed lặp lại an toàn | Fresh DB chạy seed offline từ fixture; lần 2 không nhân đôi |
| Database | PostgreSQL, migration, indexes/constraints | Alembic upgrade trên DB mới và test PostgreSQL thật |
| Responsive | Co giãn trong laptop/desktop theo phạm vi người dùng | 4 viewport desktop; ghi rõ mobile chưa nghiệm thu |

## 6. Kiến trúc và ranh giới file

`CONTRACTS.md` là giao kèo kỹ thuật. Nếu cần thay đổi nó sau khi chia nhánh, coordinator duyệt và cập nhật một lần rồi thông báo toàn bộ worker.

```text
src/backend/
  main.py                       # Foundation; cuối cùng Integrator
  config.py                     # Giữ legacy constants, thêm cấu hình tương thích
  core/                         # config/db/security/dependencies/audit helpers
  models/                       # Foundation sở hữu TOÀN BỘ ORM models
  schemas/
    shared.py, auth.py           # Foundation
    library.py                  # Backend Library
    admin.py                    # Backend Admin
  api/
    auth.py                     # Foundation
    library.py                  # Backend Library
    engagement.py               # Backend Library
    events.py                   # Backend Library
    admin/                      # Backend Admin; export router tại __init__.py
  services/
    library/                    # Backend Library
    admin/                      # Backend Admin
  search_service.py, utils/      # Legacy, bảo toàn
src/frontend/
  index.html, app.js, style.css  # Foundation; cuối cùng Integrator
  core/                         # api/session/router/ui; Foundation
  assets/fonts/, assets/vendor/ # Foundation, dependencies local
  assets/demo/                  # Foundation, hình minh họa seed nếu cần
  public/                       # Frontend Library
  admin/                        # Frontend Admin
alembic/, fixtures/folio/        # Foundation
scripts/seed_folio.py            # Foundation
tests/backend/foundation/       # Foundation
tests/backend/library/          # Backend Library
tests/backend/admin/            # Backend Admin
tests/frontend/public/          # Frontend Library, nếu có test hữu ích
tests/frontend/admin/           # Frontend Admin, nếu có test hữu ích
tests/e2e/, docs/verification/  # Integrator
docs/handoff/status/<lane>.md   # Mỗi worker chỉ ghi file riêng
docs/handoff/requests/<lane>.md # Yêu cầu sửa shared file, mỗi worker file riêng
```

Foundation tạo sẵn test configuration, dependency manifests và router/page stubs để import chạy được. Các stub này phải được thay bằng chức năng thật trước nghiệm thu cuối. Stubs không được trả thành công giả.

## 7. Tiến độ theo dependency, không chạy tất cả cùng lúc

### Wave 0 — Foundation, một người sở hữu

Chạy `prompts/01-foundation.md`. Công việc:

1. Lập inventory và bảo toàn thay đổi hiện có; đọc các file kế hoạch và chốt CONTRACTS trước chia việc.
2. Tạo app config, PostgreSQL setup, SQLAlchemy models, Alembic migration đầu tiên, constraints/indexes.
3. Auth session, CSRF, password hashing, profile, permission dependency và audit helper.
4. Core dependencies nhẹ; optional legacy imports chỉ trong nhánh bật tính năng. `/health` và UI không cần model/Chroma.
5. Tạo fixture 100 bài thật, seed idempotent, 5 tài khoản demo local, danh mục/thẻ, ảnh minh họa có nguồn/license rõ nếu dùng.
6. Tạo shell UI, core JS, tokens/shared CSS, fonts/vendor local, hash router, entry stubs.
7. Tạo test setup PostgreSQL tách biệt và README chạy foundation. Không tự ý reset database có dữ liệu.
8. Chạy auth/schema/seed smoke tests; ghi `docs/handoff/status/foundation.md` với baseline và giao kèo đã chốt.

Chỉ ghi **FOUNDATION_READY** khi DB khởi tạo được, auth hoạt động, seed chạy hai lần đúng, app mở được không ML, core frontend imports resolve và các shared interfaces đã tồn tại. Phải có lệnh chạy và kết quả thực; nếu thiếu runtime/DB thì ghi blocker, không tự nhận đã pass.

### Wave 1 — Bốn nhánh độc lập chạy song song

| Nhánh/chat | Prompt | Sở hữu | Phụ thuộc |
|---|---|---|---|
| A — Backend Library | `02-backend-library.md` | Read/search/detail/engagement/events | Foundation + frozen models/contracts |
| B — Backend Admin | `03-backend-admin.md` | Content CRUD/taxonomy/users/RBAC/moderation/SEO/analytics/settings/audit API | Foundation + frozen models/contracts |
| C — Frontend Library | `04-frontend-library.md` | Directory/detail/auth/profile + public styles | Foundation core frontend + API contracts |
| D — Frontend Admin | `05-frontend-admin.md` | Tất cả admin screens + admin styles | Foundation core frontend + API contracts |

Frontend có thể dùng mock adapter rõ ràng chỉ trong development/test khi backend tương ứng chưa xong. Không được hardcode số liệu, users, permissions hoặc giả lưu thành công trong chế độ chạy thật. Khi bàn giao phải nêu chỗ nào chưa kiểm chứng với API thật.

Backend Admin sở hữu **mọi write tài liệu và taxonomy**. Backend Library chỉ đọc chúng. Moderator/SEO/User Admin cùng ở nhánh B để không tranh schema hay CRUD. Branch B được phép chia subagent theo các thư mục con của mình nếu khối lượng lớn.

### Wave 2 — Integration và nghiệm thu

Chạy `prompts/06-integration.md` khi cả bốn nhánh đã bàn giao:

Gate thực tế: hai backend đã hoàn thành scope và pass tests; hai frontend đã hoàn thành code và kiểm tra tương tác theo contract. Frontend được bàn giao PARTIAL nếu phần duy nhất còn thiếu là xác minh với backend thật; ghi `ReadyToIntegrate: yes` cùng danh sách checks chờ tích hợp. Không chờ frontend tự chứng minh tích hợp trong worktree không có backend, và cũng không chấp nhận thiếu screen/action dưới lý do này.

1. Merge lần lượt A -> B -> C -> D; đối chiếu contract trước khi giải quyết conflict.
2. Tích hợp router, shared CSS, shell menu theo effective permissions; sửa các shared-file requests.
3. Loại mock runtime, kiểm tra mọi UI mutation thật, data persistence và quyền backend.
4. Chạy migration/seed trên DB sạch; test toàn bộ permission matrix, workflow, logs, pagination và các lỗi quan trọng.
5. Kiểm tra trực quan ở các viewport đã chốt; chụp và mở ảnh xác minh nội dung, không tự nhận UI đẹp chỉ từ code.
6. Cập nhật README, `.env.example`, ERD, mapping assignment, tài khoản demo local, test report và kịch bản demo.
7. Đưa checklist cuối về pass/fail/not run có bằng chứng. Không gọi bản nộp là hoàn tất khi còn endpoint hoặc luồng cốt lõi giả.

### Ngoài critical path

Khôi phục/đóng gói legacy semantic demo nếu dependencies/data sẵn có và Phase 1 đã pass. Không để việc tải model, crawl lại 50k bài hay re-embedding chặn bài nộp này. Giữ `/search` tương thích nếu bật legacy; khi tắt trả 503 có thông báo rõ, không giả dữ liệu.

## 8. Hai cách sử dụng các prompt

### Cách khuyên dùng: một chat điều phối, tự gọi subagent

Paste toàn bộ `prompts/00-orchestrator.md` vào Antigravity mở tại repo. Chat này tự thực hiện/delegate Foundation, chờ gate, gọi bốn worker theo ownership, rồi tích hợp. Nếu giới hạn concurrency thấp, xếp hàng các nhánh; không cần có đủ bốn worker đồng thời.

Không đồng thời tự mở các chat thủ công cho cùng scope trong khi orchestrator đang điều phối tự động.

### Cách thủ công: nhiều chat do người dùng mở

1. Chat 0: paste `prompts/01-foundation.md`, đợi FOUNDATION_READY.
2. Tạo baseline commit **chỉ chứa các thay đổi được kiểm tra và thuộc công việc này**. Không dùng `git add .` thiếu kiểm tra; không amend/force-push. Bao gồm file kế hoạch, ASSIGNMENT và các shared interfaces cần cho mọi nhánh. Giữ những sửa đổi chưa đưa vào baseline nguyên vẹn.
3. Tạo bốn Git worktree từ cùng baseline, mỗi worktree một branch riêng: `codex/folio-library-api`, `codex/folio-admin-api`, `codex/folio-library-ui`, `codex/folio-admin-ui`. Mỗi chat mở đúng thư mục worktree tương ứng. Không chạy đồng thời nhiều chat trong cùng checkout nếu chưa có cơ chế ownership và thông báo thay đổi.
4. Paste prompts 02–05 vào bốn chat. Fixture nhỏ phải nằm trong baseline; thư mục `data/` và virtualenv bị ignore không tự xuất hiện trong worktree. Không sửa/xóa dữ liệu nguồn trong checkout gốc.
5. Mỗi backend worker dùng DB test riêng; mỗi server cần port riêng nếu chạy đồng thời. Không chia sẻ DB dùng cho migration/seed/reset trong test.
6. Khi hoàn thành, mỗi chat trả commit/branch, file status, lệnh test và requests. Chỉ commit file thuộc ownership; không tự merge các nhánh khác.
7. Chat 0 hoặc một chat tích hợp: paste `prompts/06-integration.md`, cung cấp 4 branch/commit. Giữ worktrees cho đến khi xác minh tích hợp; không tự xóa.

Trường hợp không dùng worktree: chỉ chạy trong cùng checkout khi tất cả agent chấp hành ownership, không cùng sửa shared files, không cùng chạy git checkout/merge/reset, có coordinator duy nhất thực hiện thay đổi chung. Worktree là lựa chọn mặc định cho các chat độc lập.

## 9. Giao thức bàn giao bắt buộc của mọi worker

File status dùng cấu trúc:

```text
Status: FOUNDATION_READY | READY_FOR_INTEGRATION | BLOCKED | PARTIAL
ReadyToIntegrate: yes | no (chỉ cho các lane Wave 1)
Scope and owned files:
Branch / commit (nếu có):
Implemented endpoints or screens:
Commands run and actual results:
Contract deviations / shared-file requests:
Known failures and unverified paths:
How to manually verify:
```

FOUNDATION_READY chỉ dùng cho Foundation khi đã pass gate. Không ghi READY_FOR_INTEGRATION nếu còn blocker trong scope. Dùng PARTIAL nếu UI mới kiểm tra bằng fixture vì backend chưa sẵn sàng; integration có trách nhiệm kiểm tra lại với DB thật. `ReadyToIntegrate: yes` không có nghĩa đã đạt Definition of Done của toàn ứng dụng.

## 10. Definition of done cho bản nộp

- Fresh setup từ repo + fixture, không cần tải bộ vector DB hay chạy crawler.
- 100 tài liệu published đủ trường, có dữ liệu thực và nguồn; draft/test content được đánh dấu đúng.
- Tài khoản demo của 5 vai trò dùng được; mật khẩu demo chỉ phục vụ local, không hardcode trong source production.
- Không thể leo thang quyền bằng sửa request body, URL, cookie hay gọi API trực tiếp.
- CRUD nội dung, publish/unpublish, taxonomy, engagement, @mentions, moderation, SEO, settings, permissions và analytics chạy thật.
- Search/click/view có log đúng semantics; dashboard tính từ log thật và không tính view thành click.
- Xóa/ẩn tài liệu không còn xuất hiện trên public API, detail, comment, like hoặc click endpoints.
- Seed chạy lặp lại không nhân đôi và không âm thầm ghi đè dữ liệu người dùng sửa.
- Mọi chức năng chính hoạt động khi không cài thư viện ML và không có data/vector.
- Desktop UI đã xem ở các cỡ đã chốt; console/network không có lỗi chưa giải thích.
- Test report chỉ rõ checks đã chạy, chưa chạy và giới hạn mobile. README có lệnh PowerShell, setup DB, migrate, seed, run, test và optional legacy.
- Không sửa `ASSIGNMENT.md` để làm checklist dễ hơn; không đổi tên field hoặc bớt chức năng nhằm che thiếu sót.

## 11. Demo đề xuất, khoảng 8–10 phút

1. Library có 100 tài liệu -> search + category/tag/date -> đổi trang -> detail.
2. Đăng ký member -> sửa profile -> like -> comment có @mention -> report.
3. Content Manager -> tạo bài -> publish -> thấy public -> unpublish -> public không truy cập được.
4. Moderator -> xử lý report/spam -> comment thay đổi trên public.
5. Data & SEO -> lưu metadata -> xem dashboard và query/click vừa tạo.
6. Super Admin -> đổi quyền một role/tài khoản -> chứng minh API 403 khi thiếu quyền -> xem audit và settings.
7. Mở schema/test report, chỉ ra Document Store và logs sẵn sàng cho Phase 2.

Không chạy legacy semantic demo trong luồng này nếu nó làm thời gian demo phụ thuộc tải model.
