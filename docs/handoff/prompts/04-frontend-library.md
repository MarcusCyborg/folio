# Prompt: Chat C / Frontend Library

Bạn triển khai UI public của **Folio — Knowledge & Research Library**. Tôi muốn một thư viện có nhận diện và trải nghiệm khác WikiSearch cũ, hoàn thành chức năng assignment. Tập trung laptop/màn hình lớn; không thiết kế hoặc test mobile.

Bạn không làm một mình: backend và frontend admin đang được triển khai song song. Không revert chỉnh sửa người khác, không sửa file ngoài scope, không tự đổi API schema.

Đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md`, `docs/handoff/status/foundation.md`, `docs/ui-components.md`, core frontend và token styles. Bắt đầu sau Foundation READY. Nếu contract/source helpers lệch nhau, ghi request; không tạo api/session/router thứ hai.

Ownership:

- `src/frontend/public/**`, gồm `index.js` route manifest và `public.css`.
- `tests/frontend/public/**` nếu test hữu ích.
- `docs/handoff/status/frontend-library.md`, `docs/handoff/requests/frontend-library.md`.
- Evidence của lane dưới `docs/verification/public/`.

Không sửa `index.html`, root `app.js`, root `style.css`, `core/**`, shared assets/vendor/fonts, backend, models, migration hay manifests. Yêu cầu shared shell/component/token bổ sung ghi requests. Dùng helpers Foundation đã tạo.

Visual brief:

- Paper-white, ink blue, teal, Source Serif 4 headings/reading và Source Sans 3 UI theo tokens.
- Library có kết quả thật ngay first viewport, sidebar categories khoảng 220px, search/filter controls và list document rows. Tránh hero lớn, card lồng card, score dashboard kỹ thuật và fake usage numbers.
- Detail chú trọng đọc dài, title/summary/author/Added date/views/category/tags, ảnh khi có, source/attribution, like và comments. Width cột đọc hợp lý, không kéo dòng chữ hết màn hình 1920px.
- Layout co giãn từ laptop 1280 tới desktop 1920; không dùng global min-width khiến laptop bị tràn; không xây menu mobile.
- Text tiếng Anh nhất quán. Mọi con số lấy API thật. Có visible focus, labels, loading, empty, errors, retry, forbidden/not found và session expiration.

Screens/flows phải hoàn thành:

1. `#/library`: query/category/tag/date/sort/page phản ánh trên URL, Back/Forward/reload đúng; đổi filter reset page. Abort request cũ để response chậm không đè kết quả mới. Không spam log bởi rerender thừa.
2. `#/documents/:id`: lấy detail, chỉ chèn rendered_content đã sanitize từ backend; source URLs an toàn. Ghi view once per navigation; search click event theo contract, direct links không fake click. Analytics lỗi không làm mất khả năng đọc bài.
3. Like/unlike gọi API; comments paginated, create/edit/delete own; @username autocomplete từ endpoint; plain text escaped; report comment với reason. Tôn trọng comments_enabled và suspension, báo error từ server.
4. `#/login`, `#/register`: validation thật, error field, disabled submit khi pending, refresh user/CSRF sau success; next route chỉ nội bộ. Không gán role từ browser.
5. `#/profile`: display name/bio, đổi mật khẩu với current_password; feedback và session rotation đúng.
6. Cập nhật document title/meta khi mở tài liệu; reset về Folio khi rời route. Không hứa server-side SEO với hash router.

Nếu backend chưa sẵn sàng, có thể dùng test/dev mock adapter theo đúng contract, tách rõ khỏi runtime. Không hardcode thành công của save/login/like/comment. Status phải PARTIAL nếu chỉ kiểm chứng với mock; backend integration sẽ được làm ở Wave 2.

Functional checks: query/filter URL state, pagination, click->detail, direct detail không click log, view retry idempotence, login/logout/profile, like retry, comment own edit/delete, mentions/report, 401/403/404, long text và loading race. Không viết unit test chỉ để assert CSS string.

Visual checks theo batch: 1280x720, 1366x768, 1440x900, 1920x1080; thêm zoom 125% ở laptop. Mở ảnh chụp để xác minh; thử keyboard/focus, error/empty và form pending, không chỉ ảnh trạng thái đẹp. Nếu chỉ có mock backend, ghi nhãn evidence đó.

Có thể gọi subagent review UI hoặc kiểm tra flow trong ownership của mình; không để subagent thay core/shared CSS. Khi xong ghi status/template, screenshot paths, test commands thực, backend/mock status, commit nếu branch riêng và shared requests. Không merge/push.
