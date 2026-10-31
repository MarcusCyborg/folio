# Prompt: Chat A / Backend Library

Bạn triển khai Backend Library của **Folio**. Đây là một nhánh của công việc đang chạy song song; bạn không làm một mình trong codebase. Không revert thay đổi của người khác và không chỉnh file ngoài ownership. Nếu dùng worktree, làm trên branch/worktree đã được giao, không checkout sang branch chat khác.

Trước tiên đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md`, `docs/handoff/status/foundation.md` và source core/models/auth của Foundation. Chỉ bắt đầu viết feature khi Foundation có READY và contracts frozen. Nếu thiếu, ghi blocker rõ; không tự tạo một schema song song.

Ownership của bạn:

- `src/backend/api/library.py`, `engagement.py`, `events.py`.
- `src/backend/schemas/library.py`, `src/backend/services/library/**`.
- `tests/backend/library/**`.
- `docs/handoff/status/backend-library.md`, `docs/handoff/requests/backend-library.md`.

Không sửa ORM/models/migration/main.py/core/auth/dependencies/manifests/frontend. Admin worker sở hữu write documents/taxonomy. Nếu cần shared change, ghi request với lý do, interface cần có và ảnh hưởng; coordinator quyết định.

Hãy hoàn thành toàn bộ Library/Engagement/Events API trong Section 6 của CONTRACTS:

1. Public settings, categories/tags; published document list có pagination/sort/search/filter và detail đầy đủ metadata. Search dùng SQL tham số hóa, escape wildcard, stable ordering, đúng timezone/date boundaries và multi-tag AND.
2. `rendered_content` từ Markdown/plain source qua parser raw-HTML-disabled và HTML sanitizer an toàn; tránh XSS/unsafe URL. Dùng dependencies Foundation đã cung cấp, yêu cầu thêm nếu thiếu thay vì tự đổi manifest.
3. View event idempotent + views_count atomic. Like/unlike idempotent, uniqueness trong database.
4. Comment create/list/own-edit/own-delete; derive @mentions từ username ở server; mention lookup không lộ email. Validate visibility của parent trên mọi route. Không cho owner tự sửa comment hidden/spam để vượt moderation.
5. Report comment có duplicate-open protection. Enforcement comments_enabled, commenting suspension, rate limit/duplicate spam guard. Chủ sở hữu vẫn xóa comment của mình khi suspended.
6. Search/click logging đúng semantics: search response trả event id; click liên kết event gốc, kiểm actor/session, membership result_doc_ids và publication, copy query server-side. Không overwrite search rows hoặc coi direct page view là click.
7. Guest được read/search/view và logging qua guest session, member/staff mới được tương tác cần login. Dùng shared CSRF/session dependencies; không tin user_id do client gửi.

Tests trên PostgreSQL test DB riêng của lane:

- Search kết hợp category/tags/date, page boundaries, q rỗng và ký tự `%`/`_`, stable sort.
- Draft/unpublished/deleted không lộ qua detail/comments/likes/views/click; public counts không bao gồm hidden/spam comments.
- Cross-user comment edit/delete bị từ chối; mention escaping và không leak email.
- Like, click và view retries không double count; user/guest ownership event được kiểm tra.
- Comment setting/suspension/rate limit/duplicate enforcement.
- Markdown/raw HTML/unsafe link không chạy script trong output; malformed inputs trả error contract.

Tự gọi subagent nếu hữu ích, chỉ chia các thư mục/tests trong lane mình; không cho họ sửa shared files. Backend Library không tự tạo UI hoặc thay search engine legacy.

Khi hoàn thành, chạy tests thực, ghi status theo template và commit chỉ file thuộc ownership nếu đang dùng branch riêng. Không merge/push. Bàn giao endpoint list, test commands/results, commit, shared requests và phần chưa kiểm chứng. Không nói đã tích hợp frontend nếu mới test API.
