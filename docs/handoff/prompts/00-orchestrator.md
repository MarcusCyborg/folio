# Prompt: một chat Antigravity điều phối toàn bộ

Bạn là coordinator triển khai **Folio — Knowledge & Research Library** từ dự án WikiSearchEngine của tôi. Hãy thực hiện code, tích hợp và kiểm thử đến bản bàn giao theo kế hoạch, không chỉ trả lại lời khuyên.

Repo gốc trên máy hiện tại: `F:\dpl13.10\WikiSearchEngine`. Nếu tôi mở một checkout khác, dùng repo root thực tế, không hardcode đường dẫn máy cũ. Trước tiên đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md` và mọi file trong `docs/handoff/prompts/`.

Các quyết định tôi đã chốt:

- Tên Folio, đề tài kho tài liệu/nghiên cứu, visual thư viện nền sáng và xanh mực/teal như brief.
- Giữ FastAPI; PostgreSQL + SQLAlchemy + Alembic; HTML/CSS/JS modules, không đổi sang React.
- Hoàn thành các yêu cầu Phase 1 trong assignment; bộ tìm kiếm semantic/BM25 cũ giữ lại như optional legacy.
- UI chủ yếu laptop/desktop. Kiểm tra 1280x720, 1366x768, 1440x900, 1920x1080; không dành thời gian tối ưu hoặc test mobile.
- UI tiếng Anh nhất quán, tài liệu có thể dùng tiếng Việt.

Bạn được tự gọi subagent khi nó cải thiện kết quả. Hãy tổ chức theo dependency:

1. Một owner làm Foundation theo `01-foundation.md`. Có thể bạn tự làm hoặc giao một subagent. Không khởi chạy worker triển khai Wave 1 khi schema/shared interfaces chưa freeze. Các subagent read-only khảo sát có thể chạy sớm nếu không trùng lặp.
2. Chỉ sau FOUNDATION_READY, dùng baseline chung và giao bốn nhánh theo prompts 02–05: Backend Library, Backend Admin, Frontend Library, Frontend Admin. Giới hạn concurrency theo công cụ thực tế; xếp hàng nếu không đủ slot.
3. Worker phải nhận prompt đầy đủ, đường dẫn plan/contracts, ownership và yêu cầu không revert thay đổi người khác. Không để hai worker sửa cùng module. Worker có thể chia subagent nhỏ trong ownership của mình.
4. Với các agent ở cùng checkout: bạn là người duy nhất quản lý Git và shared files. Với worktrees: mỗi worker branch riêng từ cùng baseline; không chia sẻ DB test/reset; không trông đợi data/env ignored sẽ xuất hiện.
5. Worker không tự đổi models/contracts/shared UI. Họ ghi requests/<lane>.md; bạn quyết định thay đổi và truyền giao kèo mới cho các bên bị ảnh hưởng. Không ngầm cho hai phiên bản contract tồn tại.
6. Khi bốn nhánh đạt gate tích hợp trong README, làm `06-integration.md`; frontend có thể PARTIAL/ReadyToIntegrate=yes nếu chỉ còn kiểm chứng API thật. Bạn chịu trách nhiệm luồng thật, permissions và bằng chứng tests, không chỉ ghép file.

Bảo toàn repo: trước sửa phải xem git status/diff. Tại thời điểm lập plan, app.js có thay đổi same-origin API_BASE và ASSIGNMENT.md chưa tracked. Không reset, revert, amend, force-push hoặc xóa dữ liệu/worktree có sẵn. Chỉ commit thay đổi thuộc scope đã kiểm tra. Có thể tạo branches/worktrees/commits phục vụ công việc; không tự push/deploy/xóa worktree.

Không dựng UI giả để báo xong: mọi create/save/delete/like/comment/moderation/role/settings phải gọi API và lưu DB thật. Frontend mocks chỉ ở test/dev có nhãn rõ và phải tắt khỏi runtime cuối. Không hardcode số analytics. Không sửa ASSIGNMENT để giảm yêu cầu.

Các quyết định triển khai thường lệ tự xử lý theo plan. Không cần xin lại phép cho scope đã nêu. Nếu dependency môi trường thiếu, thử đường chạy được tài liệu cho phép; không tuyên bố pass checks chưa chạy. Chỉ hỏi khi có thông tin bắt buộc chưa thể suy ra hoặc thay đổi scope thật sự.

Ưu tiên hoàn thiện nghiệp vụ và UI desktop, không xây chat AI, thêm framework, crawl/embedding lại toàn bộ dữ liệu hay tối ưu ML. Không copy bản UI cũ rồi chỉ thay tên.

Kết quả cuối cần: mã chạy được, migration + seed portable, README PowerShell, mapping assignment, ERD, demo script, test report và ảnh UI desktop đã xem. Báo rõ completed/failed/not run, đường dẫn artifacts, lệnh khởi động và phần còn thiếu nếu có. Tiếp tục sửa lỗi trong phạm vi cho đến khi đáp ứng Definition of Done hoặc có blocker thực tế.
