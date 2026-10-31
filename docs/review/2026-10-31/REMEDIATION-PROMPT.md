# Prompt cho Antigravity: sửa lỗi và hoàn thiện UI Folio

Hãy sửa trực tiếp dự án **Folio — Knowledge & Research Library** của tôi dựa trên báo cáo review. Tôi không hài lòng với chất lượng UI hiện tại. Mục tiêu là một bản chạy đúng, có giao diện được thiết kế nhất quán và đã kiểm tra bằng dữ liệu thật; hãy triển khai, chạy thử, sửa lỗi và bàn giao kết quả.

## 1. Đọc hiện trạng trước khi sửa

Repo ban đầu: `F:\dpl13.10\WikiSearchEngine`. Nếu đang ở checkout khác, dùng đường dẫn thực tế.

Đọc theo thứ tự:

1. `AGENTS.md` nếu có, git status/diff và các commit mới nhất.
2. `ASSIGNMENT.md`.
3. `docs/review/2026-10-31/REVIEW.md` — nguồn findings và lý do cần sửa.
4. `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md` — ngữ cảnh sản phẩm và giao kèo đang dùng.
5. Source liên quan, test hiện có và ảnh trong `docs/verification/`. Phân biệt ảnh dùng dữ liệu test với dữ liệu demo thực.

Review được lập trên commit `40d5068`; khi soạn prompt đã thấy commit mới `4e0c348` xử lý date boundary. Vì vậy hãy kiểm tra từng finding trên HEAD hiện tại, ghi rõ Already fixed / Reproduced / Source-confirmed / Not reproduced. Không áp dụng lại một bản sửa đã có, không coi số dòng trong review là bất biến.

Giữ FastAPI, PostgreSQL, SQLAlchemy/Alembic và HTML/CSS/JS modules. Giữ tên Folio và chức năng assignment. UI tiếng Anh, báo cáo bàn giao tiếng Việt. Phạm vi chỉ laptop/desktop; không triển khai hay dành thời gian tối ưu mobile. ML/semantic search tiếp tục optional.

## 2. Cách tổ chức thực hiện

Bạn là coordinator và chịu trách nhiệm chất lượng cuối. Được tự gọi subagent, nhưng **chỉ có một owner quyết định và tích hợp toàn bộ frontend/design system**. Không chia public UI và admin UI cho hai agent tự chọn ngôn ngữ thiết kế khác nhau.

Có thể chạy song song:

- Backend/data integrity: click idempotency, migrations, date validation, dependency/setup; sở hữu backend, Alembic và backend tests liên quan.
- Content/data curation: fixture, script chuẩn bị dữ liệu và source notes; không sửa UI/backend hoặc tự ghi đè DB đang dùng.
- Frontend owner: shell/router/editor/public/admin/CSS, sửa lỗi UI và thiết kế; một người tích hợp các thay đổi cùng file.
- Sau khi có ảnh render: một reviewer độc lập chỉ review, không sửa source đồng thời.

Coordinator quản lý thay đổi API/shared schema, dependency manifests chung và Git. Giao rõ ownership cho từng agent; nhắc họ không làm một mình, không revert thay đổi người khác. Nếu chat độc lập thì dùng worktree/branch riêng từ cùng baseline. Mỗi lane dùng test DB/port riêng khi cần. Không tự push/deploy/reset/xóa dữ liệu hoặc worktree.

## 3. Sửa lỗi chức năng trước

Xử lý F1–F7 trong REVIEW và các lỗi nhỏ có liên quan. Mỗi finding phải có bằng chứng sửa hoặc lý do không còn áp dụng.

### F1: Preview Markdown an toàn

- Bỏ cách dùng regex tự ghép HTML chưa được sanitize.
- Dùng parser được duy trì + sanitize HTML cuối cùng, hoặc một backend preview endpoint có permission phù hợp dùng chung sanitizer với trang đọc.
- Kiểm tra chính payload quote/event-handler trong review. Không chỉ escape chuỗi đầu vào rồi tiếp tục ghép attributes.
- Test trên output thật của renderer, bảo đảm không còn event attributes/unsafe protocols; vẫn render đúng headings, code, table, link và ký tự đặc biệt.
- Không lưu payload thử nghiệm vào database ứng dụng đang dùng.

### F2: Chặn mất nội dung chưa lưu

- Đưa leave guard vào router trước khi abort/cleanup/xóa DOM.
- Bao phủ editor Back, sidebar, header, điều hướng bằng code và browser Back/Forward trong hash router; giữ native beforeunload cho reload/đóng tab.
- Cancel giữ nguyên input, URL phù hợp và route hiện tại; Confirm mới rời đi. Không tạo vòng lặp history, nhiều dialog hoặc render nhầm route khi người dùng bấm nhanh.
- Sau khi lưu thành công hoặc chấp nhận discard, không hỏi lại vô ích.

### F3: Hành vi lưu/xuất bản phải khớp nhãn

- Với bài đã published: dùng **Save Changes** để lưu và giữ published; dùng **Save & Unpublish** cho hành động lưu rồi đưa về draft.
- Với bài draft/mới: dùng **Save Draft** và **Publish**.
- Nếu chọn một cách diễn đạt khác, phải thể hiện rõ trạng thái cuối trước khi bấm. Không để Save as Draft âm thầm cập nhật nội dung công khai.
- Kiểm tra failure giữa bước lưu và bước đổi trạng thái: không toast thành công giả hoặc tạo trùng tài liệu khi retry. Bảo toàn nội dung form và báo đúng trạng thái thực.

### F4–F5: Click logging đúng và chống trùng thực sự

- Thêm unique constraint/index đúng phạm vi actor + request key, xử lý cạnh tranh bằng database và trả lại event gốc khi retry cùng payload.
- Cùng key nhưng khác document/search event phải bị từ chối, không trả success giả.
- Trước migration kiểm tra dữ liệu trùng đã tồn tại. Không âm thầm xóa log người dùng: cần có chiến lược bảo toàn/backup và báo cáo; dùng DB test/demo riêng để thử migration.
- Ghi click tại thao tác mở kết quả tìm kiếm; refresh detail, direct URL và Back/Forward không tự sinh click mới. View vẫn là event riêng theo navigation.
- Không chặn đọc bài khi logging lỗi. Retry cùng thao tác giữ cùng request key. Không tính click kép từ cả link handler và detail render.
- Kiểm tra chuột, Enter và hành vi mở tab mới được hỗ trợ; giải thích rõ giới hạn nếu có, không phá hành vi native của link.
- Test hai request đồng thời, retry, khác actor, khác payload và các navigation nêu trên.

### F6–F7 và phần tích hợp còn lệch

- Kiểm tra bản sửa date boundary hiện có trên catalog/audit/analytics; kiểm tra ngày tối đa và from > to. Giữ bản sửa đúng đã có.
- Khai báo đủ dependencies chạy test, bao gồm Playwright/browser setup; README phải dùng đúng requirements-dev và chuẩn bị DB test.
- Kiểm chứng trong venv sạch, không dựa vào system-site-packages của env cũ. Không ghi pass nếu chưa chạy được môi trường sạch.
- SEO title phải được sử dụng đúng trên detail; site name/description phải áp dụng vào shell/metadata khi setting thay đổi.
- Duy trì permission enforcement ở backend, CSRF/session và API contracts. Nếu cần đổi contract, cập nhật cả consumers và tests.

## 4. Làm lại UI với một hướng thiết kế rõ ràng

Hướng đã chọn: **thư viện tri thức biên tập gọn, dễ scan, có chất lượng trình bày**, dùng nền giấy sáng, chữ xanh mực, accent teal và cặp Source Serif 4 / Source Sans 3. Có thể tinh chỉnh sắc độ và typography sau khi nhìn render. Không cần thay identity, framework, thêm dark mode hoặc hiệu ứng lớn.

### Library là màn hình chuẩn để chốt trước

- Dùng list tài liệu trên nền giấy, separator mảnh; tránh những mảng trắng dài có chữ sát mép như hiện tại.
- Tiêu đề tài liệu là điểm đọc đầu tiên. Summary tối đa ba dòng ở catalog; metadata gọn một dòng hoặc cụm phụ rõ; hiển thị ít tag chính và có cách xem phần còn lại.
- Giảm độ nổi của counters; không để nhiều số 0 và emoji trở thành vật trang trí lặp lại. Dùng icons nhất quán, có nhãn truy cập.
- Search là hành động chính. Header gọn, Library title/count tạo ngữ cảnh; không có hero quảng cáo chiếm đầu trang.
- Sidebar category khoảng 220px; date filter là phần phụ có thể thu gọn. Giữ đủ category/tag/date/sort/pagination theo assignment.
- Có kết quả và thông tin hữu ích ngay ở first viewport 1366x768. Khống chế chiều dài dòng và container ở 1920px; không kéo mọi thứ hết ngang màn hình.
- Chỉnh spacing theo nhóm nội dung và thứ bậc; không tăng padding đồng loạt rồi gọi là thiết kế mới.

### Bắt buộc có checkpoint bằng ảnh render thật

1. Chụp Library hiện tại dùng dữ liệu demo thật làm before.
2. Hoàn thiện một màn Library mới với nhiều title/summary dài ngắn thật tại 1366x768 và 1440x900.
3. Mở ảnh và tự kiểm tra: thứ tự nhìn, spacing, chiều dài dòng, readability, nội dung above-the-fold và overflow.
4. Cho reviewer độc lập xem before/after cùng brief, không chỉ diff source. Sửa nhận xét có ảnh hưởng trước khi nhân rộng.
5. Đưa ảnh before/after cho tôi xem trong cập nhật tiến độ và ghi lý do các thay đổi. Tôi có thể điều chỉnh hướng khi đang làm; không hỏi lại màu/font/stack đã chốt. Nếu chưa có phản hồi, tiếp tục theo brief và checkpoint review độc lập, không coi im lặng là tôi đã duyệt.

**Chỉ áp dụng rộng sau khi checkpoint này có kết quả cụ thể.** Nếu hai ảnh gần như giống nhau ngoài màu/kích thước, hoặc reviewer còn thấy lỗi bố cục chính, tiếp tục sửa Library trước. Không dùng việc screenshot file tồn tại làm tiêu chí đạt.

### Sau Library: detail và admin

- Detail: giữ cột đọc khoảng 72–80 ký tự/dòng; heading/paragraph/code/table rõ; summary không lặp quá nhiều với mở bài. Thêm TOC từ headings với anchor duy nhất, source link gần byline; không để header sticky che heading khi nhảy mục.
- Admin documents: mở rộng title, Edit là hành động chính, secondary actions vào menu gọn có keyboard/Escape/focus đúng. Delete vẫn có confirm. Tránh cột nút đỏ lặp chiếm sự chú ý.
- Admin sidebar: nhóm Content / Community / Administration hoặc các nhóm dễ hiểu tương đương; chỉ hiện mục theo effective permissions.
- Editor: thanh Save/Publish nhìn thấy khi làm việc; metadata phụ có thể thu gọn; content là vùng trọng tâm. Save pending/error/dirty states rõ ràng.
- Analytics: tick theo chiều rộng và date range, chữ khoảng 11–12 CSS px trở lên, plot cao khoảng 220–260px, Y-axis/grid nhẹ; 7/30/90 ngày đều đọc được. Không scale toàn bộ chart khiến chữ nhỏ dần.
- Auth/profile/moderation/settings/SEO: áp dụng chung tokens/controls/spacing. Không để mỗi màn là một template khác.
- Self-host fonts với license, giữ fallback; tránh thêm CDN để demo phụ thuộc mạng. Giữ focus/labels, reduced-motion và loading/empty/error/403/404.

## 5. Biên tập dữ liệu thật để UI có chất lượng

- Kiểm tra lại 100 bài: liên quan chủ đề, taxonomy hợp lý, summary có nghĩa và sạch `[edit]`, `[citation needed]`, disambiguation/crawler debris. Không cắt mất nội dung gốc chỉ để screenshot đẹp.
- Không lấy 100 record đầu rồi gọi là curated. Dùng nguồn hiện có để có tập bài phù hợp hơn nếu cần; không crawl/embedding lại toàn bộ corpus.
- Giữ title/source URL/author/license đúng; mapping category/tag phải được kiểm tra, không random hoặc ép số lượng cho đẹp.
- Thêm một số ảnh/sơ đồ liên quan có nguồn/license rõ để chứng minh detail images hoạt động; không cần ảnh mọi card, không dùng stock không liên quan. Có fallback khi ảnh lỗi.
- Ngày added dùng ngày nhập thực hoặc ghi rõ demo dates; không trình bày ngày tạo giả như provenance thật.
- Fixture update và DB update là hai việc khác nhau. Seed hiện tại bảo toàn edits nên thay JSON không tự làm UI đang chạy đổi theo. Hãy dựng **database demo sạch riêng** từ fixture mới, chạy server review trên port riêng và bàn giao rõ URL/lệnh. Không overwrite bài hoặc tài khoản trong DB đang dùng để buộc hình ảnh giống fixture.
- Sau khi demo bản mới đạt, hướng dẫn chuyển cấu hình sang DB demo mới; không tự xóa DB cũ. Tài liệu phải nói rõ đã update DB nào.

## 6. Kiểm tra có bằng chứng, không tự chứng nhận bằng lời

- Chạy backend suite và regression tests mới, chạy frontend flows với API thật. Không giảm assertions hoặc sửa expected chỉ để xanh.
- Test DB phải được xác minh khác DB ứng dụng bằng host/port/database đã parse, không chỉ tìm chữ test trong cả URL. Mọi reset/seed/test writes chỉ vào database test/demo được xác định.
- Tách DB cho kiểm thử mutation khỏi DB dùng để chụp UI. Screenshot cuối dùng dataset demo sạch, không có các bài Quantum Computing tên ngẫu nhiên hoặc fixture dư từ test trước.
- Kiểm tra 1280x720, 1366x768, 1440x900, 1920x1080. Kiểm tra browser zoom 125% thật bằng công cụ hỗ trợ; `device_scale_factor` không thay thế page zoom. Nếu không thực hiện được zoom thật, ghi Not run, không gọi là certified.
- Chụp và mở xem Library, detail dài, editor, documents table, moderation, analytics, roles/settings; kiểm tra keyboard, pending, empty, error và long text. Không chỉ ảnh happy path.
- Có thể dùng checks đo overflow/layout để bổ trợ; không coi screenshot existence, số ảnh hoặc số tests pass là đánh giá thẩm mỹ.
- Review độc lập sau tích hợp: UI consistency và các bug F1–F7. Chỉ chạy lại checks liên quan sau sửa, tránh lặp toàn bộ suite khi không có lý do.

## 7. Bàn giao

Tạo `docs/review/2026-10-31/REMEDIATION-REPORT.md`, giữ nguyên REVIEW.md làm baseline. Mỗi finding có status, file/commit xử lý, cách kiểm tra, kết quả thật và phần chưa xác minh.

Lưu ảnh mới vào thư mục remediation riêng, giữ baseline before/after. Ghi viewport, dataset/DB, route và commit của ảnh. Cập nhật README/setup/demo-script/checklist theo thực tế; bỏ các tuyên bố verified/certified chưa có bằng chứng.

Kết quả trả cho tôi cần:

- Các lỗi đã sửa và giới hạn còn lại.
- Ảnh before/after của Library và ít nhất một màn admin, hiển thị trực tiếp nếu công cụ cho phép.
- URL xem demo mới, lệnh chạy, DB đang dùng.
- Test commands/results thực tế, checks chưa chạy.
- Đường dẫn report và bằng chứng.

Tự xử lý các quyết định triển khai thường lệ trong phạm vi này. Nếu có blocker môi trường, thử đường chạy phù hợp trước rồi báo đúng chỗ bị chặn. Đừng kết thúc ở một bản plan, một bộ ảnh mock hoặc lời khẳng định đã đẹp hơn mà chưa mở giao diện thực tế.
