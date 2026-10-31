# Prompt: Chat tích hợp / QA / Bản nộp

Bạn tích hợp và hoàn thiện **Folio — Knowledge & Research Library** từ các nhánh Foundation, Backend Library, Backend Admin, Frontend Library và Frontend Admin. Hãy sửa lỗi tích hợp và hoàn thành bản nộp, không chỉ review rồi để lại danh sách lỗi.

Đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md`, toàn bộ `docs/handoff/status/` và `requests/`. Xem git status, branch/worktree/commit trước khi ghép. Nếu có nhánh chưa bàn giao, chỉ làm việc độc lập an toàn và ghi phần phụ thuộc; không giả định stub là tính năng đã xong.

Scope đã chốt: FastAPI/PostgreSQL/SQLAlchemy/Alembic, HTML/CSS/JS modules, tên Folio, UI laptop/desktop, Phase 1 đầy đủ; ML/legacy optional. Không mở rộng sang mobile hoặc đổi framework.

Bạn là owner shared files/integration trong bước này. Worker khác phải đã dừng ghi trước khi bạn sửa file của họ. Bảo toàn mọi thay đổi unrelated. Không reset/revert bừa, amend, force-push, xóa dữ liệu hoặc worktree. Có thể tạo integration branch và commit chỉ thay đổi đã kiểm tra; không push/deploy.

Thực hiện:

1. Khi có bốn branch riêng, merge theo thứ tự Library API -> Admin API -> Public UI -> Admin UI từ baseline phù hợp. Đọc conflict theo contracts, không dùng ours/theirs hàng loạt. Nếu code đã ở cùng checkout thì không merge giả; kiểm kê đúng hiện trạng.
2. Xử lý shared-file requests; chốt models/migrations duy nhất, imports/router mounts, schema exports, api/session/CSRF lifecycle, shared CSS và route manifests. Mọi contract change ghi rõ rồi cập nhật tất cả consumers.
3. Kiểm tra app startup với core-only dependencies, ENABLE_LEGACY_SEARCH=false và không data/vector. UI/API/health/auth/CRUD phải chạy. Legacy disabled trả 503 rõ. Không tải model/crawl/re-embed để che startup coupling.
4. Kiểm tra fresh PostgreSQL setup -> alembic upgrade -> seed -> seed lại. Có 100 published records thật từ fixture portable, không duplicated; role permissions chỉnh không bị seed reset, user edits không bị overwrite. Xác minh source notes/images/licenses và không bịa metadata.
5. Loại test/dev mock khỏi production paths; rà mọi button/link/form có chức năng thật. Đảm bảo status counters/analytics từ API. UI không được dùng localStorage giả DB.
6. Chạy tests của tất cả lanes; thêm tests/e2e cho những ranh giới tích hợp quan trọng còn thiếu. Dùng DB test riêng có guard, không test bằng reset DB đang dùng của tôi.
7. Kiểm tra API auth/permission bằng request trực tiếp, không chỉ nhìn UI: role escalation, CSRF, disabled/expired sessions, revoke permissions, last admin invariant, own-comment permissions và các endpoint liên quan tài liệu hidden/deleted.
8. Kiểm tra create->edit->publish->search->detail->unpublish->delete; login/profile/password; like/comment/@mention/report; moderation/suspension; SEO/settings/roles; audit và analytics.
9. Tạo search + result click + detail view thật, đối chiếu DB log/query/ID/user/timestamp; guest user_id null; click ownership/result membership; retry không duplicate. Không được count direct view thành click hoặc overwrite search event.
10. Kiểm tra HTML/Markdown/URL safety trên nội dung, comments, metadata và search text. Không đưa secret/hash/session vào response, console, audit hoặc screenshot.
11. Visual QA trên 1280x720, 1366x768, 1440x900, 1920x1080 và zoom 125% laptop: Library, detail dài, login/profile, admin table/editor, moderation, SEO/analytics, roles/settings. Kiểm tra focus, loading/empty/error, long labels, overflow và pending states. Chụp, mở xem ảnh, sửa lỗi có ảnh hưởng. Không tối ưu mobile.
12. Có thể gọi subagent độc lập review security/RBAC và visual/UX trên code cuối, giao scope read-only rõ. Bạn xử lý findings rồi chạy lại checks liên quan. Không để reviewer sửa cùng file với bạn.

Tài liệu bàn giao cần có:

- `README.md`: Folio, mục đích, stack, setup PowerShell từ fresh clone, DB/venv/install/migrate/seed/run/test, `.env.example`, demo accounts/password env local, troubleshooting, optional legacy và desktop scope. Không tuyên bố UI mobile đã pass.
- `docs/architecture.md`: modules, ERD, roles/permissions, Document fields và search/click semantics; mapping tags relation -> API field.
- `docs/assignment-checklist.md`: từng requirement của ASSIGNMENT -> file/API/screen/test evidence -> PASS/FAIL/NOT RUN. Không sửa đề bài.
- `docs/demo-script.md`: 8–10 phút theo plan, ai đăng nhập vai trò nào, thao tác gì, kết quả nào chứng minh yêu cầu.
- `docs/verification/TEST-REPORT.md`: môi trường, commands thực, results, screenshot paths, issues đã sửa, blockers/limitations. Không viết passed khi chưa chạy.
- `docs/handoff/status/integration.md`: final scope, commits, remaining known issues và cách chạy.

Ưu tiên kết thúc Definition of Done trong handoff README. Không dừng vì đã merge xong nếu còn chức năng stub hoặc broken flow. Nếu có blocker môi trường không tự giải được, bàn giao cụ thể phần nào chưa xác minh và lệnh người dùng cần chạy, không gọi bản nộp là hoàn tất.

Cuối phản hồi ngắn gọn: đã thay đổi gì, lệnh chạy, tests thật, nơi xem UI/evidence, và các giới hạn còn lại. Không tự push, deploy hoặc xóa worktrees.
