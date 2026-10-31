# Prompt: Chat B / Backend Admin

Bạn triển khai Backend Admin của **Folio** theo assignment. Có các worker khác đang làm cùng dự án; không revert hoặc đụng file của họ. Làm trong worktree/branch được giao, không tự checkout/merge nhánh khác.

Đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md`, `docs/handoff/status/foundation.md` và models/core/auth hiện có. Chỉ bắt đầu khi Foundation READY, contracts frozen. Không dựng schema hoặc quyền theo cách riêng.

Ownership:

- `src/backend/api/admin/**`, export `router` từ `__init__.py`.
- `src/backend/schemas/admin.py`, `src/backend/services/admin/**`.
- `tests/backend/admin/**`.
- `docs/handoff/status/backend-admin.md`, `docs/handoff/requests/backend-admin.md`.

Không sửa models/migrations/main.py/core/auth/shared manifests/frontend. Yêu cầu shared change phải ghi requests với ảnh hưởng rõ. Bạn sở hữu toàn bộ writes tài liệu/taxonomy; public Library worker chỉ đọc chúng.

Hiện thực toàn bộ Section 7 của CONTRACTS, gồm:

1. Document CRUD, draft/published state, publish validation, soft-delete; tất cả list/detail cần quyền đúng. Dùng field allowlist, không cho status/SEO/author-id lách qua mass assignment.
2. Taxonomy CRUD; slug uniqueness, conflict khi xóa category/tag đang dùng; admin list thấy cả taxonomy chưa có tài liệu public.
3. Users list/filter/update role/active; roles/permission catalog và assign permissions. Quyền thay đổi có hiệu lực request kế tiếp. Bảo vệ active super_admin cuối cùng dưới concurrency bằng transaction/lock phù hợp, không chỉ count trước update.
4. Moderation comments + reports và spam suspension. Dismiss/hide/mark_spam đúng state machine, comment mutation và report resolution atomic. Không cho moderator sửa role hoặc giả nội dung tác giả.
5. SEO endpoint chỉ nhận SEO fields/alt text; Data & SEO không thể sửa body/status hoặc gọi document writes. Admin SEO list/detail dùng shared document reads có permission riêng.
6. Analytics query từ interaction_logs/view_events thật, date range UTC, daily zero-fill, top query/document, totals nhất quán; không random số, không coi search request count là unique users.
7. Audit log list redacted; global settings whitelist và validation. Mọi admin mutation cần audit trong cùng transaction, không ghi secret/password/token.

Được chia subagents trong phạm vi của bạn để giảm tải:

- content/taxonomy: routers/services riêng và tests tương ứng;
- governance: users/roles/settings/audit riêng;
- moderation/SEO/analytics: modules riêng.

Nếu chia, bạn giữ ownership `__init__.py`, schemas/admin.py hoặc chia schemas thành package có export tương thích do bạn tích hợp; không cho nhiều agent ghi cùng file. Thông báo họ không làm một mình và không sửa models/contracts. Bạn chịu trách nhiệm final router export và tests toàn lane.

Test ưu tiên:

- Permission matrix đầy đủ qua API, bao gồm forged role fields và direct request không qua UI.
- Create/edit/publish/unpublish/delete + taxonomy conflicts.
- Role update, disabled account, permission revocation có hiệu lực; last admin invariant và trường hợp cạnh tranh.
- Moderator không sửa document/user role, Data & SEO không sửa content/status.
- Resolve report atomic, hidden/spam bị loại đúng ở DB; không resurrect owner-deleted comment.
- SEO/settings persistence, audit redaction, transaction rollback không để log thành công giả.
- Analytics tính đúng từ event fixture được tạo có chủ đích; zero-event periods; bad/inverted date range.

Chạy PostgreSQL test DB riêng, không reset DB của lane khác. Khi bàn giao ghi file status theo template, commands và kết quả thật, commit nếu dùng branch riêng, shared requests và phần chưa chạy. Không tự merge/push hoặc tự nhận toàn app đã xong.
