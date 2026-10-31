# Prompt: Chat D / Frontend Admin

Bạn triển khai toàn bộ khu quản trị **Folio** cho assignment. Phạm vi UI là laptop/desktop; không tối ưu/test mobile. Các worker khác làm backend/public UI cùng lúc, nên không revert thay đổi người khác hay sửa ngoài ownership.

Đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md`, `docs/handoff/status/foundation.md`, `docs/ui-components.md` và shared frontend code. Chỉ bắt đầu khi Foundation READY. Tuân thủ API/schema/permissions đã freeze.

Ownership:

- `src/frontend/admin/**`, gồm `index.js` route manifest và `admin.css`.
- `tests/frontend/admin/**` khi có test hữu ích.
- `docs/handoff/status/frontend-admin.md`, `docs/handoff/requests/frontend-admin.md`.
- Evidence dưới `docs/verification/admin/`.

Không sửa root frontend shell/core/styles/assets, backend/models/migrations/manifests. Dùng api/session/router/ui helpers chung. Nếu cần shared component hoặc core fix, ghi requests; không fork core hoặc tạo token system riêng.

Thiết kế cùng nhận diện Folio: nền giấy, xanh mực/teal, typography và controls Foundation. Admin ưu tiên bảng dữ liệu dễ scan, toolbar/filter/pagination, form có label rõ, sidebar trong admin content area. Không thêm biểu đồ hoặc stats trang trí không có dữ liệu thật. Màn hình mới đầu tiên nên thấy ngay việc có thể làm.

Hoàn thành routes/admin flows của CONTRACTS:

1. Admin entry tìm route đầu tiên theo effective permissions; sidebar chỉ hiện mục được phép; unauthorized deep link có 403 rõ ràng, không trang trắng. Quyền UI dùng `can(permission)`, không hardcode tên role.
2. Documents: list/search/status/category/page, create/edit form có title/summary/content/author/category/tags/source/image, preview nội dung an toàn, save draft, publish/unpublish, delete confirm. Dirty form warning và giữ input khi request lỗi. Không WYSIWYG nặng; textarea Markdown + preview phù hợp là đủ.
3. Taxonomy: categories/tags create/edit/delete; xử lý 409 đang được sử dụng, không báo thành công giả.
4. Moderation: comments queue visible/hidden/spam, reports queue có comment context, dismiss/hide/spam actions, suspend/restore commenting theo contract. Pending/error states, audit reason khi yêu cầu.
5. SEO: document list và form title/description/keywords/image alt; Data & SEO xem/sửa đúng phạm vi, không lộ editor content write cho họ. Preview chỉ minh họa metadata; không hứa công cụ tìm kiếm sẽ hiển thị y hệt.
6. Analytics: period filter, totals/daily/top queries/top documents từ API thật. Chart hoặc bảng nhỏ dễ đọc; zero data có trạng thái đúng. Không giả trend/percentage. Ghi Search requests đúng định nghĩa trong contract.
7. Users: search/filter, role assignment, enable/disable; báo protection của last super admin theo server, UI không giả quyền.
8. Roles/permissions: danh sách catalog, permission toggles theo role, save actual DB; super_admin protected. Thay đổi quyền làm UI refresh session khi cần.
9. Audit logs: actor/action/entity/time, filters/pagination, redacted before/after viewer; không expose secret.
10. Settings: site name/description, registration/comments enable; actual save/persistence và feedback.

Tất cả action phải gọi API theo contract, disable khi pending và giữ error hữu ích. UI guard bổ trợ backend authorization, không thay thế. Xử lý 401, 403 sau revoke quyền, 409 conflict, 422 field errors, 429 và server unavailable.

Nếu backend chưa xong, dùng mocks chỉ trong development/test có nhãn rõ. Tuyệt đối không shipping fallback fake data hoặc toast Save successful khi chưa có API thật. Status PARTIAL nếu còn cần kiểm tra backend.

Bạn có thể chia subagent theo screens không trùng file (content/taxonomy, moderation/SEO/analytics, users/roles/settings/audit). Bạn giữ route manifest, admin.css và phối hợp shared lane components, không nhiều agent sửa một file chung.

Kiểm tra routes và actions cho các permission sets thực, keyboard và dirty editor, form errors, long titles, table overflow/pagination, empty analytics. Batch screenshots 1280x720, 1366x768, 1440x900, 1920x1080 và zoom 125% laptop; mở ảnh xác minh. Test meaningful flows, không snapshot mọi CSS.

Khi xong: ghi status theo template, màn hình/flow đã làm, backend vs mock verification, lệnh test, screenshot paths, commit chỉ ownership nếu branch riêng, shared requests. Không tự merge/push và không tuyên bố toàn hệ thống đã hoàn tất.
