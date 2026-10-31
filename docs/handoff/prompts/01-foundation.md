# Prompt: Chat 0 / Foundation

Hãy thực thi Foundation cho Folio trong repo WikiSearchEngine hiện tại. Đây là bước nền trước khi tôi chia cho bốn chat chạy song song; lần này hoàn thành Foundation rồi bàn giao, chưa tự làm toàn bộ feature UI/API ở các nhánh sau.

Đọc `AGENTS.md` nếu có, `ASSIGNMENT.md`, `docs/handoff/README.md`, `docs/handoff/CONTRACTS.md` và prompts 02–06 để biết các dependency cần cung cấp. Repo gốc ban đầu là `F:\dpl13.10\WikiSearchEngine`; dùng đường dẫn checkout thực tế.

Tôi đã chọn Folio, giữ FastAPI + HTML/CSS/JS modules, thêm PostgreSQL/SQLAlchemy/Alembic. Desktop/laptop là phạm vi giao diện; không tối ưu mobile. Tự xử lý các lựa chọn kỹ thuật thường lệ theo contracts; không hỏi lại stack hay tên. Các phần plan ghi đề xuất có thể chỉnh nếu cần nhưng phải cập nhật contract trước freeze và giải thích ngắn gọn.

Bạn là owner duy nhất của:

- Shared config, dependencies/manifests, compose/.env.example, app bootstrap và legacy adapter.
- Toàn bộ ORM models và migrations cho tất cả module, không chỉ auth.
- Core DB/security/dependencies/audit, auth/profile API và test helpers.
- Fixture 100 bài, seed script, nguồn/license, demo accounts.
- Frontend shell/core/token styles/components/fonts/vendor và routing stubs.
- CONTRACTS.md, tài liệu hướng dẫn core và foundation status.

Trước khi sửa, đọc git status/diff và giữ nguyên mọi thay đổi không thuộc mình. Plan ghi có sửa same-origin API_BASE ở app.js và ASSIGNMENT.md chưa tracked. Đừng reset/checkout/revert; không xóa data gốc. Không `git add .` thiếu kiểm tra.

Công việc theo thứ tự:

1. Chốt API schemas, permissions và frontend exports trong CONTRACTS. Nếu cần thêm field/model cho một requirement, làm bây giờ. Không để worker sau phải tự thêm migration xung đột.
2. Tách Phase 1 khỏi ML startup. Default app khởi động được khi không cài chromadb/sentence-transformers và không có vector dataset. Chỉ lazy import SearchService trên đường legacy bật flag. Giữ algorithms/crawler/evaluation và API legacy khi bật nếu có đủ dữ liệu.
3. Tạo PostgreSQL config/compose, models, migration đầy đủ, indexes/constraints, request-scoped sessions, audit helper transaction-safe. Validate protected last super admin có hướng triển khai/test rõ cho Admin worker.
4. Hiện thực register/login/logout/session/profile/password với cookie session, CSRF, password hash, active checks và effective permissions như contract. Không dùng JWT/localStorage chỉ để rút ngắn code. Public registration luôn member.
5. Tạo error schema thống nhất, dependency imports, test DB setup có guard chống reset nhầm, fixtures cho member/staff/guest và seed permissions.
6. Stream dữ liệu cũ để tạo `fixtures/folio/documents.jsonl` có 100 bài thực tế phù hợp AI/CS/Research. Chuyển fields đúng, viết summary thật, taxonomy có nghĩa; giữ URL nguồn, attribution và license đã kiểm chứng. Không bịa ngày/tác giả. Fixture phải được Git theo dõi, không nằm trong data/ ignored. Thêm một vài ảnh/sơ đồ liên quan có nguồn rõ để demo detail khi phù hợp.
7. Seed idempotent: lần sau không nhân đôi, không reset quyền đã chỉnh, không overwrite nội dung user sửa. 5 demo accounts chỉ local bằng DEMO_PASSWORD env; không hardcode password production. Thử seed hai lần.
8. Dựng shell Folio và shared UI nhỏ nhưng dùng được: fonts self-host, tokens, controls, notification/confirm/pagination/error helpers, session store, api wrapper, hash router/abort cleanup. Tạo public/admin route manifests và stylesheet stubs để các worker chỉ chạm lane của họ. Tài liệu `docs/ui-components.md` có markup và import examples.
9. Register backend router stubs `api/library.py`, `engagement.py`, `events.py`, `api/admin/__init__.py` trước static mount. Stubs không trả data/success giả. Foundation auth phải dùng được; feature stubs ghi rõ chưa triển khai.
10. Tạo tests/foundation và chạy trên PostgreSQL: migration fresh DB, auth/CSRF, register role escalation, disabled user, profile/password/session rotation, seed idempotency, no-ML startup, frontend import smoke check.

Được gọi subagent cho các phần không đụng file của nhau, ví dụ chuẩn bị fixture hoặc review test contract. Bạn vẫn chịu trách nhiệm nhất quán toàn bộ models/shared code. Không cho worker tự sửa cùng migration/model/config.

Chỉ bàn giao FOUNDATION_READY khi gate trong README và CONTRACTS thực sự pass. Nếu không chạy được database/runtime, ghi BLOCKED/PARTIAL và bằng chứng thay vì đánh dấu xong. Không tự mở bốn nhánh feature trước gate.

Đầu ra bắt buộc:

- Shared code thực tế, migrations, fixture portable, setup instructions và test results.
- CONTRACTS chuyển thành v1 frozen khi đủ gate, ghi mọi deviation trước freeze.
- `docs/handoff/status/foundation.md` theo template; danh sách shared exports/import paths, lệnh start/test, viewport đã kiểm tra, baseline commit nếu đã tạo.
- Commit nền chỉ chứa các files thuộc công việc đã kiểm tra, gồm assignment/plan cần cho worktrees; giữ sửa đổi unrelated nguyên vẹn. Không push.
- Cuối phản hồi nêu FOUNDATION_READY hoặc blocker thật, và baseline commit để tôi mở bốn chat/worktrees.
