# Prompt sửa Integration A cho từng chat Gemini

Ngày lập: 01/11/2026. Dùng cùng [kế hoạch chi tiết](F:/dpl13.10/WikiSearchEngine-github/docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md).

## Cách dùng

Mở một chat Gemini mới cho mỗi R00-R04.5 và R05-R06, chạy tuần tự. Copy nguyên block của chat đó. R00 bắt đầu từ repo nguồn và chuẩn bị worktree tích hợp. Các chat sau mở worktree ghi trong `IA-R00-integration.md`, mặc định đề nghị `F:/dpl13.10/WikiSearchEngine-ia-fix`.

Nếu thiếu quyền đọc file, đưa nội dung review/plan/handoff tương ứng cho Gemini; không để agent đoán và tự báo hoàn tất. Không giao tất cả prompt cùng lúc cho các chat sửa chung một checkout. Các prompt không yêu cầu spawn subagents.

Chưa chạy P03. Không có prompt nào cho phép push/deploy hoặc sửa main.

R04.5 là checkpoint tích hợp bắt buộc sau R04 và trước R05. Đây là bước review/sửa lỗi ghép, không phải một worktree song song.

## R00 — Tích hợp local, bảo toàn workspace

```text
Bạn là integration engineer của Folio. Chỉ thực hiện R00, chưa chạy P03.

Repo nguồn: F:/dpl13.10/WikiSearchEngine-github
Repo cũ cấm dùng làm workspace: F:/dpl13.10/WikiSearchEngine
Remote dự kiến: https://github.com/MarcusCyborg/folio.git

Đọc AGENTS.md áp dụng, git status/diff, rồi:
- docs/handoff/review/INTEGRATION-A-REVIEW.md
- docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md, nhất là mục 1-4
- GEMINI-EXECUTION-PROMPTS.md và handoff P00/P01/P02 tại đúng worktree.

Refs tham khảo, phải kiểm tra lại:
main c4b19cffa676b4437e7346da2c410b198b04dc2c
feature/p01-security 740eb5f1cc5f6b0c90480310e37a36234086a726
feature/p02-clean-setup 1ac72ad8a9e979682ddad8253c0d6d3e49222055

Nhiệm vụ này cho phép tạo worktree/branch tích hợp riêng và merge LOCAL hai
nhánh P01/P02 vào đó; đây là ngoại lệ giới hạn đối với lệnh cấm merge chung
trong prompt pack cũ. Đề nghị branch codex/integration-a-remediation và path
F:/dpl13.10/WikiSearchEngine-ia-fix. Nếu đã tồn tại, kiểm tra trước khi dùng.
Không merge vào main, không reset/clean/amend/force/push/deploy.

Bạn không làm việc một mình. Giữ file untracked/edits của người khác. So sánh
tài liệu nguồn trước copy vì P02 đã track nhiều file đang untracked ở main.
Không copy .env, venv, DB, data/model cache hoặc ghi đè report cũ.

Tích hợp P01 rồi P02, giải quyết conflict theo behavior, không chọn ours/theirs
nguyên file. Giữ seed run_seed(target=..., db_url=...) và skip_demo_users/
--no-demo-users; production/staging không seed demo. Chốt transaction ownership
khi caller truyền Session và policy --test/--db-url không nhập nhằng.
Giữ toàn bộ lifespan/config/bootstrap/security tests cùng fixtures/constraints/CI.

CHƯA chạy pytest fixture, seed, migration hoặc CLI truy cập DB: guard P02 còn lỗi
có thể DROP schema thật. Chỉ kiểm tra source/diff/ancestry an toàn ở R00.

Commit local đúng file thuộc nhiệm vụ sau khi review diff, không stage secret hoặc
output không liên quan. Viết docs/handoff/gemini/IA-R00-integration.md ghi worktree
chính thức, SHA, conflict resolutions, seed API, source branches và việc R01 cần làm.
Nếu tên handoff tồn tại tạo timestamp. Đưa report/plan/prompt cần thiết sang worktree
bằng copy đối chiếu; không thay bản gốc ở repo nguồn.

Kết thúc với SOURCE INTEGRATED / VALIDATION PENDING nếu đúng thực tế, không tuyên bố
Integration A PASS. Phản hồi tiếng Việt: path mở cho R01, HEAD, files/decisions,
checks đã chạy và blockers. Dừng sau R00.
```

## R01 — Sửa guard và dựng test isolation

```text
Bạn là test infrastructure engineer của Folio. Chỉ thực hiện R01 sửa IA-02.

Đọc AGENTS.md, git status/diff/refs, IA-R00-integration.md và mục 1-3,5 của
docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md. Đọc review gốc IA-02 và
probe_guard_contract.py trong evidence của review. Làm việc tại worktree tích hợp
do R00 ghi, không main hoặc worktree P01/P02 riêng. Giữ edits của người khác;
phát hiện thay đổi đồng thời thì dừng và báo. Không reset/revert/push/deploy.

Ownership: module validate/provision test DB, tests/conftest.py, test fixtures
lifecycle, pure safety tests và cấu hình hạ tầng TEST riêng. Không sửa auth/search.

Đầu tiên tách validator thuần khỏi import app/engine/conftest. Chạy pure tests
không load fixture DB nguy hiểm. Reproduce bằng connect args, tuyệt đối không mở
connection tới URL minh họa review_test?dbname=folio.

Sửa theo policy effective driver target: reject target query overrides/DSN không
hỗ trợ, normalize default port và alias loopback, kiểm soát libpq env/service có
thể đổi đích. Không in URL chứa password khi báo lỗi. URL path có chữ test không
phải chứng minh safety hoặc ownership.

Provision PostgreSQL test mới với run ID/manifest sở hữu, không dùng shared
folio_test hoặc DB hiện có. Chỉ DROP/reset/terminate tài nguyên run tạo; DB đã tồn
tại mà không thuộc manifest phải fail/chọn tên mới. Kiểm tra connected identity
trước mutation. Không blanket terminate connections của run khác.

Dùng PostgreSQL 16 riêng bằng runtime/container sẵn có nếu khả thi; không đổi
dịch vụ hệ thống, không lấy DB thật để bù thiếu môi trường. Thiếu runtime thì làm
xong phần độc lập, ghi BLOCKED_ENV và pending DB checks, không thay bằng SQLite
rồi báo hoàn tất.

Tests bắt buộc: dbname/host/port/service override; default port/host alias collision;
invalid/protected names; existing unowned DB; two concurrent runs; migrate/seed
fresh DB; teardown chỉ tài nguyên run. Sentinel nằm trong instance test disposable,
không nằm trên DB thật. Không chạy full fixture trước khi pure safety tests pass.

Không thêm framework. Commit local phạm vi sửa sau kiểm tra diff. Viết
docs/handoff/gemini/IA-R01-test-isolation.md với command/env masked/exit/results,
DB ownership manifest không secret, safe setup và gaps. Không ghi PASS từ việc
file tồn tại. Dừng sau R01; chưa P03.
```

## R02 — Sửa bootstrap và xác minh security tích hợp

```text
Bạn là backend security engineer của Folio. Chỉ thực hiện R02 sửa IA-03 và kiểm
chứng P01 trên worktree tích hợp của IA-R00-integration.md.

Đọc AGENTS.md, status/diff/refs, handoff R00/R01, review IA-03 và mục 1-3,6 của
INTEGRATION-A-REMEDIATION-PLAN.md trong docs/handoff/review. Không chạy DB tests
khi safety/provisioning R01 chưa đạt. Nếu môi trường thiếu, hoàn thành phần độc
lập và báo BLOCKED_ENV; không coi SQLite là chứng nhận PostgreSQL.

Ownership: scripts/bootstrap_admin.py và security/startup/bootstrap tests.
Chỉ sửa config/main/auth nếu có regression thực tế trong phạm vi này. Bạn không
làm việc một mình; giữ edits của người khác, dừng khi có thay đổi đồng thời.
Không reset/revert/push/deploy/main merge; không bắt đầu P03.

Sửa rotate: email + username sau normalize phải xác định cùng một super_admin.
Khớp một nửa, trỏ hai người, member, account thiếu/inactive không được đổi password,
promote hoặc reactivate ngầm. Recovery nếu cần phải là operation riêng có policy
và identity checks; không dùng --rotate làm recovery ẩn. Create duplicate an toàn,
không mutate account có sẵn; exit already-exists có thể khác 0 nhưng phải rõ.

Giữ ID/role khi rotate; password hash, revoke sessions và audit có transaction
đúng. Rejection không partial mutation/success audit. Dùng env/getpass, không
default password hoặc password trên CLI/log. Không làm mất seed production guard.

Chạy CLI subprocess trên PostgreSQL mới đã migrate chưa seed tay: create, rerun,
rotate/revoke. Test mismatch hai chiều, two-account collision, member/inactive,
target thiếu, missing/weak password; so trạng thái trước/sau rejection.

Chạy startup subprocess với env valid/invalid thật; kiểm tra validator fail sớm,
cookie flags, CORS/Origin/CSRF, guest/member/staff RBAC, disabled-user/revoke và
public error redaction. Không chỉ gọi validator trực tiếp. Dùng DB/run R01 riêng,
không disable bảo vệ runtime để test xanh. Chạy targeted rồi full backend khi khả thi.

Commit local đúng phạm vi; viết docs/handoff/gemini/IA-R02-bootstrap-security.md
với source SHA, commands/exit, PASS/FAIL/BLOCKED, migration/config impact và gaps.
Không ghi 70 tests pass từ handoff cũ. Dừng sau R02.
```

## R03 — Chốt contract Document ID và pagination

```text
Bạn là search contract owner của Folio. Chỉ thực hiện R03 sửa IA-04/IA-05 bằng
tài liệu; chưa viết importer, index schema/outbox/worker hoặc public search API.

Dùng worktree tích hợp ghi trong IA-R00-integration.md. Đọc AGENTS.md, status/diff,
handoff R00-R02, review IA-04/IA-05, search-contract.md, acceptance-matrix.md và
mục 1-3,7 của docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md.
Giữ edits người khác; không reset/revert/push/deploy; không overwrite report gốc.

Ownership: docs/search-contract.md, docs/acceptance-matrix.md, bổ sung đầu vào P03
trong prompt pack và handoff mới. Không sửa fixture ID để làm khớp contract.

Chốt ID canonical là UUID Folio hiện hữu gồm v4/v5; v4 chỉ là default tạo mới.
Đếm/hash fixture thật, giữ 103 IDs và source mappings. Kiểm tra counts thay vì chép
con số 165 từ báo cáo cũ.

Chốt MỘT cơ chế ổn định pagination qua cả generation swap và update trong cùng
generation; pin generation đơn thuần chưa đủ khi index còn mutable. Đọc phương án
đề nghị của plan: server-issued actor-bound search context giữ ordered candidate
IDs/scores, absolute TTL 15 phút configurable, retention/expiry rõ. Có thể chọn
phương án nhỏ hơn nếu chứng minh cùng invariants, nhưng phải ghi quyết định cuối.

Định nghĩa token/context request/response, query/filter/page_size binding, expiry
status/error code, generation lease/GC, live publication check, pruning/backfill,
counts lexical vs semantic candidate window và has_more. Không claim exact live
total từ snapshot/top-k. Date filters đề nghị created_at UTC như browse; ghi rõ
unknown taxon/error semantics, stable tie-break và freshness 60 giây ở tải demo.

Viết ví dụ page1 G1 -> write/swap G2 -> page2, expired context, unpublish giữa trang,
semantic limited window. Phân công P03 retention/reader contract, P05 context API/
storage; không implement chúng trong R03. Sửa wording Alembic heads và phân biệt
proposed contract với implemented runtime.

Review nội bộ tính nhất quán của examples/table, commit local tài liệu thuộc scope,
viết docs/handoff/gemini/IA-R03-search-contract.md với decisions và đầu vào P03.
Không gắn FROZEN nếu còn lựa chọn ảnh hưởng schema chưa chốt. Dừng sau R03.
```

## R04 — Sửa rate limit nhiều process

```text
Bạn là backend concurrency engineer của Folio. Chỉ thực hiện R04 sửa IA-06.

Dùng worktree tích hợp của R00. Đọc AGENTS.md, status/diff, handoff R01-R03,
review IA-06, rate_limit.py/auth.py và mục 1-3,8 của remediation plan trong
docs/handoff/review. Không dùng fixture nếu DB isolation chưa được xác minh.
Bạn không làm việc một mình; giữ edits khác, dừng khi thấy thay đổi đồng thời.
Không reset/revert/push/deploy hoặc bắt đầu P03.

Ownership: shared rate-limit store/logic, auth integration, migration hardening
nếu cần, tests concurrency và env/docs liên quan. Không sửa index/search schema.

Triển khai limiter chia sẻ bằng PostgreSQL hiện có; không thêm Redis/Celery.
Không đóng finding bằng in-memory Lock, multiprocessing.Manager hoặc chỉ ghi
deploy 1 worker. Trước code ghi policy keys/action, limits/window, successful login,
429/Retry-After, restart và store unavailable.

Admission/update phải atomic khi nhiều requests/processes. Failed auth/rejected
request không làm counter rollback theo transaction auth. Success một account không
reset counters IP của account khác. Lock ordering nhất quán; retention bounded;
không log password/token hoặc dùng raw credential làm key. Store down có failure
rõ, không silent fallback sang local limiter rồi claim same guarantees.

Nếu thêm migration, upgrade DB sạch và DB ở head trước đó trong môi trường test
riêng; không reset dữ liệu. Giữ một Alembic head và ghi head mới cho P03.

Chạy hai Python/web processes độc lập dùng chung DB owned: alternating/concurrent
attempts, expiry, restart, success/failure, rollback, unavailable store và khác key.
Kiểm chứng 429 qua API thật; unit test hai object trong một process chưa đủ.
Sau targeted checks chạy security/backend regression. Không nới tests để né policy.

Commit local scope sau diff review; viết docs/handoff/gemini/IA-R04-shared-rate-limit.md
với policy, migration head, commands/results/gaps. Thiếu DB/multiprocess evidence
thì ghi chưa VERIFIED dù code đã viết. Dừng sau R04.
```

## R04.5 — Integration A checkpoint sau R02-R04

```text
Bạn là integration reviewer của Folio. Chỉ thực hiện checkpoint R04.5 sau khi
R02, R03 và R04 đã hoàn thành trên worktree tích hợp; chưa chạy P03 và chưa làm
R05 artifact/CI remediation.

Worktree bắt buộc: F:/dpl13.10/WikiSearchEngine-ia-fix
Branch: codex/integration-a-remediation
Đọc AGENTS.md, status/diff/refs, IA-R00/R01/R02/R03/R04 handoff, review gốc và
mục R04.5 của INTEGRATION-A-REMEDIATION-PLAN.md. Không làm việc trên main/P01/P02,
không reset/revert/push/deploy. Giữ edits khác; dừng nếu source đổi đồng thời.

Mục tiêu là kiểm tra giao điểm thực tế, không chỉ đọc claim trong handoff.

1. Xác minh ancestry có R00, R01, R02, R03, R04; audit changed files, unresolved
   conflict, imports và `git diff --check`. Ghi exact SHA.
2. Chạy `alembic heads`, `alembic history` và `alembic upgrade head --sql` bằng
   venv sạch nếu có. Head phải là `20261101_rate_limit`; ghi rõ P03 phải dùng
   head này làm down_revision.
3. Audit IA-02 bằng code: trong `tests/conftest.py`, manifest chỉ được register
   database sau CREATE DATABASE thành công. Nếu target đã tồn tại trước run mà
   đang được register trước provisioning, đó là blocker; sửa tối thiểu và thêm
   regression test chứng minh safe_reset từ chối unowned DB. Không dùng DB thật.
4. Audit mọi call site của `provision_test_database`: signature hiện dùng
   `requested_dbname`; sửa test/helper gọi `target_database` nếu còn lệch, hoặc
   đổi signature nhất quán. Chạy `python -m compileall` và pure tests để chứng
   minh lỗi live sẽ không bị che bởi BLOCKED_ENV.
5. Đọc claims R02/R04: tách pure, SQLite, OS-process và PostgreSQL evidence. Nếu
   multiprocess suite dùng SQLite, không gọi đó là PostgreSQL verified. Live PG
   thiếu thì ghi BLOCKED_ENV; không thay bằng SQLite.
6. Chạy các kiểm tra an toàn không cần PostgreSQL:
   `pytest --noconftest tests/safety/test_pure_safety.py tests/security/test_bootstrap_security.py tests/security/test_startup_subprocess.py tests/security/test_runtime_security_hardening.py tests/safety/test_pure_rate_limit.py -q`,
   compileall và offline migration. Nếu có PostgreSQL instance mới do R01 sở hữu,
   chạy thêm live lifecycle và bootstrap; tuyệt đối không dùng shared DB.
7. Đối chiếu R03 contract với migration head và prompt P03: UUIDv5 fixture giữ
   nguyên, context TTL/lease/count semantics không mâu thuẫn, prompt P03 trỏ
   worktree/head đúng. Chỉ sửa tài liệu stale, không viết importer/index/search.

Nếu phát hiện lỗi ownership/signature/migration/integration, sửa tối thiểu trong
scope R04.5, thêm test và ghi rõ; không tự mở rộng thành R05/P03. Commit local
đúng file sau diff review, không commit secret/output ảnh.

Tạo docs/handoff/gemini/IA-R04.5-integration-checkpoint.md gồm exact SHA,
ancestry, migration head, files changed, commands/exit/results, PG availability,
fixes và gaps. Trạng thái phải là một trong:
- INTEGRATION BLOCKED nếu còn lỗi ownership/signature/migration hoặc test nền fail.
- INTEGRATION STATIC PASS / LIVE DB BLOCKED nếu static đạt nhưng không có PG.
- INTEGRATION CHECKPOINT PASS chỉ khi static và live PG evidence đều đạt.

Không tuyên bố Integration A PASS hoặc GO P03 chỉ từ pure/SQLite/collect-only.
Phản hồi tiếng Việt và dừng sau R04.5.
```

## R05 — Sửa artifacts, fixtures và CI; chạy regression

```text
Bạn là build/test engineer của Folio. Chỉ thực hiện R05 sửa IA-07 và các gap
reproducibility/Integration A trong plan. Dùng worktree tích hợp của R00.

Đọc AGENTS.md, status/diff/refs, toàn bộ handoff R00-R04, review gốc và mục 1-3,9
của docs/handoff/review/INTEGRATION-A-REMEDIATION-PLAN.md. Không dùng shared DB,
không reset/revert edits khác, không push/deploy/main merge, chưa P03.

Ownership: capture scripts, frontend/common test fixtures, artifact helpers,
CI/README/requirements khi cần. Không refactor application UI hoặc search.

Thống nhất output root cấu hình được, unique worktree+commit+run ID cho screenshot,
trace và JUnit. Sửa cả public/admin tests và capture helpers; không chỉ script
capture_screenshots.py. Không ghi ../screenshots hoặc docs/verification; không
revert bộ PNG đã có. Run sau không ghi đè run trước hoặc output chat khác.

Traces phải start/stop thật trước đóng context. Kiểm thử failure artifacts bằng
lỗi có chủ đích rồi bỏ lỗi đó; không fake ảnh/trace. Browser tests dùng sessions
riêng không tự rollback theo db_session: sửa isolation và chứng minh thứ tự không
ảnh hưởng. Chạy suite hai lần/thứ tự khác trên DB owned, giữ ảnh tracked nguyên vẹn.

Tạo venv MỚI không dùng system-site-packages, install constraints và pip check.
Provision PostgreSQL mới bằng harness R01; Alembic upgrade head thật; seed hai lần
và ASSERT counts/IDs/source URLs/users, bảo toàn edit cần giữ, không so toàn bộ audit
timestamp phải giống hệt. Chạy bootstrap, full backend/security và frontend trên cùng
source SHA. Đếm fixture thật; sửa README/handoff claim 162/165, không sửa dataset
cho khớp report cũ. Không gọi collect-only hay offline SQL là PASS full setup.

CI phải dùng runtime/PG16/Chromium đúng, env cùng P01, targets hợp guard R01,
artifacts mới, error propagation. Trigger hiện có feature/**: sửa phù hợp branch
codex/**/PR và optional workflow_dispatch. Không tự push hoặc trigger remote;
nếu chưa có CI run đúng SHA, ghi UNVERIFIED. Thiếu Linux/Docker ghi phạm vi local rõ.

Không thêm framework, không upgrade dependency hàng loạt, không skip/xfail tests
chỉ để xanh. Phân loại fail do môi trường, regression hoặc bug ngoài scope; sửa
minimal trong scope, ghi phần còn lại để R06 quyết định.

Commit local source sửa sau review diff; ghi source SHA được test riêng với commit
chỉ chứa docs/evidence. Viết docs/handoff/gemini/IA-R05-clean-ci-artifacts.md với
commands/exit/results, artifacts, fixture counts/hash, migration head, clean setup
instructions và gaps. Chưa tự tuyên bố P03 GO; dừng sau R05.
```

## R06 — Reviewer độc lập, quyết định P03

```text
Bạn là reviewer độc lập của Folio sau remediation Integration A. Chỉ review,
chạy checks cô lập và viết báo cáo; không tự sửa application code, merge/push/deploy
hoặc bắt đầu P03. Dùng worktree/branch tích hợp được R00 bàn giao, không mặc định main.

Đọc AGENTS.md, actual refs/status/diff, INTEGRATION-A-REVIEW.md, toàn bộ IA-R00-R05,
contract/acceptance matrix cuối và mục 1-3,10-11 của remediation plan trong
docs/handoff/review. Không tin PASS chỉ vì handoff nói đã hoàn thành.

Kiểm tra từng IA-01..IA-07 bằng source và evidence mới. Phân biệt code FIXED với
behavior VERIFIED. Đọc safety/provisioning code trước chạy test; chỉ DB mới owned,
không reset DB có sẵn. Giữ file/ảnh/report cũ và dừng nếu source đang đổi đồng thời.

Bắt buộc xác minh: một SHA tích hợp có P01/P02/repairs; seed API không mất security
hoặc test target; effective DB guard/ownership/sentinel/two runs; PostgreSQL fresh
migration/seed asserts; bootstrap CLI identity negative + revoke; startup env thật,
auth/RBAC/CSRF/error paths; contract ID/generation/context/count/expiry; backend và
browser regression với artifacts riêng. Kiểm tra multi-process limiter và trace
thật; không dùng SQLite, collect-only hoặc SQL offline thay evidence tương ứng.

Đối chiếu Linux/remote CI đúng SHA nếu truy cập được; không có run thì UNVERIFIED,
không bịa success và không tự push/trigger để tạo bằng chứng. Ghi lỗi môi trường
riêng với application bug. Dùng gates G-A..G-H của plan để đánh giá nền P03.

Tạo docs/handoff/review/INTEGRATION-A-REVIEW-R2.md; nếu tồn tại dùng timestamp.
Gồm verdict, exact branch/source SHA/migration head/dirty files, findings cụ thể,
matrix IA OPEN/FIXED/VERIFIED/DEFERRED, commands/results, evidence links và gaps.
Không sửa lại review gốc để làm mất lịch sử NO-GO.

GO chỉ khi nền P03 đủ bằng chứng và không blocker. GO WITH CONDITIONS chỉ cho
điều kiện không cần hoàn tất trước P03. Nếu bắt buộc làm trước thì phải coi blocker
và NO-GO. IA-06/IA-07 không tự thành blocker schema, nhưng không claim sửa đủ 7
findings nếu còn mở. Sẵn sàng P03 không có nghĩa production-ready.

Nếu được GO/conditional hợp lệ: bàn giao exact worktree/ref/source SHA, migration
head sau R04, contract version và safe test commands cho P03. Nếu NO-GO: giao rõ
finding về owner R tương ứng, chưa triển khai feature bù. Trả lời tiếng Việt và
dừng sau báo cáo.
```
