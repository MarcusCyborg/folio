# Integration A: independent review P00-P02

Ngày review: 01/11/2026, múi giờ Asia/Saigon. Báo cáo dựa trên source và các kiểm tra mới trong lượt review này.

## 1. Kết luận: NO-GO

**Chưa đủ điều kiện bắt đầu P03 trên checkout được yêu cầu.** `main` vẫn ở baseline `c4b19cf`; P01 và P02 tồn tại trên hai nhánh/worktree riêng. Không có một bản tích hợp để nghiệm thu. Đây là blocker trực tiếp theo prompt P03, không phải yêu cầu deploy production.

Kiểm tra bổ sung trên hai nhánh phát hiện guard test database P02 có thể chấp nhận URL trỏ vào database thật trước lệnh xóa schema, và bootstrap P01 có thể rotate nhầm người dùng rồi nâng quyền member. Contract P00 còn mâu thuẫn về phiên bản Document ID và thiếu quyết định phân trang/generation có ảnh hưởng thiết kế P03.

Dependency install sạch trên Windows thành công; startup probes chạy được. Chưa chứng minh migration online, full backend/browser regression, bootstrap trên PostgreSQL sạch hoặc CI Linux. Không lấy số 58/70/15 pass từ handoff làm bằng chứng mới.

## 2. Phạm vi và trạng thái Git

| Thành phần | Đường dẫn / ref | Trạng thái kiểm chứng |
| --- | --- | --- |
| Repo nghiệm thu | `F:/dpl13.10/WikiSearchEngine-github` | Đúng repo được yêu cầu; remote `https://github.com/MarcusCyborg/folio.git` |
| Branch / HEAD | `main`, `c4b19cffa676b4437e7346da2c410b198b04dc2c` | Không có tracked staged/unstaged changes trước và sau kiểm tra |
| P01 bổ sung | `F:/dpl13.10/WikiSearchEngine-p01`, `feature/p01-security` | HEAD `740eb5f1cc5f6b0c90480310e37a36234086a726`; commits `998ba09`, `42bd60d`, `740eb5f` |
| P02 bổ sung | `F:/dpl13.10/WikiSearchEngine-p02`, `feature/p02-clean-setup` | HEAD `1ac72ad8a9e979682ddad8253c0d6d3e49222055` |
| Mốc diff | `c4b19cf` -> từng nhánh P01/P02 | `git merge-base main <branch>` trả chính `c4b19cf` cho cả hai; có căn cứ dùng làm baseline |
| P00 | Tài liệu untracked ở repo nghiệm thu | Đọc nội dung thực tế; không coi là commit đã tích hợp |
| Handoff | P00/P01 trong repo nghiệm thu; P02 tại worktree P02 | Bản copy P01 ở main ghi `42bd60d`; HEAD nhánh thực tế là commit docs `740eb5f` |

Các file untracked có sẵn tại repo nghiệm thu:

```text
FOLIO-COMPLETION-PLAN.md
GEMINI-EXECUTION-PROMPTS.md
docs/acceptance-matrix.md
docs/search-contract.md
docs/handoff/gemini/CLONE-REPORT.md
docs/handoff/gemini/P00-baseline.md
docs/handoff/gemini/P01-production-security.md
```

P01 cũng còn các tài liệu P00/plan untracked; P02 đã đưa chúng vào commit. Không có tracked dirty changes ở hai worktree khi kiểm tra. Các HEAD và tracked diffs giữ nguyên qua các lần kiểm tra; không phát hiện chỉnh sửa source đồng thời. Artifact bàn giao của review là báo cáo và evidence trong `docs/handoff/review/`; không sửa tracked source.

Đã tìm `AGENTS.md` ở `F:/`, `F:/dpl13.10/`, repo đích và hai worktree; không tìm thấy file áp dụng. Checkout cũ không dùng làm workspace kiểm thử. Lệnh đọc trạng thái ban đầu tại cwd cũ xảy ra trước khi đọc xong yêu cầu đính kèm; không có thao tác ghi ở đó.

Không merge, checkout, reset, commit, push, sửa application code hoặc triển khai P03. Việc đọc nhánh riêng nhằm chỉ ra rủi ro khi tích hợp; mọi PASS ở nhánh riêng đều được ghi đúng phạm vi.

## 3. Findings theo mức độ nghiêm trọng

### IA-01 — High — P01/P02 chưa nằm trong checkout nghiệm thu

**Chặn P03: Có.** Prompt yêu cầu hai phần được tích hợp và kiểm tra chung trước P03.

- Nguồn yêu cầu: [GEMINI-EXECUTION-PROMPTS.md:25](F:/dpl13.10/WikiSearchEngine-github/GEMINI-EXECUTION-PROMPTS.md:25), [GEMINI-EXECUTION-PROMPTS.md:116](F:/dpl13.10/WikiSearchEngine-github/GEMINI-EXECUTION-PROMPTS.md:116).
- Vị trí hiện trạng: [main.py:27](F:/dpl13.10/WikiSearchEngine-github/src/backend/main.py:27), [config.py:22](F:/dpl13.10/WikiSearchEngine-github/src/backend/core/config.py:22), [tests/conftest.py:14](F:/dpl13.10/WikiSearchEngine-github/tests/conftest.py:14).
- Tái hiện: kiểm tra `git worktree list --porcelain`, `git log main..feature/p01-security`, `git log main..feature/p02-clean-setup`; chạy `probe_runtime.py` trên main.
- Thực tế: main chưa có lifespan gọi validator, chưa có `scripts/bootstrap_admin.py`, `.github/workflows/ci.yml`, constraints hay fixture P02. Boot vẫn thành công với production cookie không Secure và secret ngắn. Fault injection `/health` còn trả chi tiết lỗi nội bộ. Các hành vi này được P01 cải thiện ở nhánh riêng, chưa có ở main.
- Mong đợi: cùng một checkout chứa cả hai phần, cùng env/seed API/test fixture, có regression evidence mới.
- Tác động: P03 sẽ phát triển trên nền cũ; các kết quả test ở nhánh riêng không chứng minh giao điểm security/setup.
- Sửa tối thiểu: tích hợp P01/P02 bằng công việc riêng được giao; giữ tài liệu untracked và xử lý phần chung `scripts/seed_folio.py` có chủ đích. P01 có `skip_demo_users`/`--no-demo-users`; P02 có `run_seed(target=..., db_url=...)` được conftest gọi. Không chọn nguyên một phía làm mất hợp đồng phía kia.
- Nghiệm thu lại: một SHA tích hợp chứa cả hai ancestry và implementation, không mất production seed guard; migrate/seed hai lần/backend/auth/browser cùng chạy trên DB riêng. Review này không thực hiện merge và không khẳng định merge tự động sẽ sạch.

### IA-02 — High — Guard P02 kiểm tra URL khác đích thực tế của driver

**Chặn P03: Có.** P03 cần môi trường migration/lifecycle test an toàn; fixture hiện có thể xóa schema ngoài đích đã kiểm tra.

- Vị trí: [tests/conftest.py:41](F:/dpl13.10/WikiSearchEngine-p02/tests/conftest.py:41), [tests/conftest.py:67](F:/dpl13.10/WikiSearchEngine-p02/tests/conftest.py:67), [tests/conftest.py:132](F:/dpl13.10/WikiSearchEngine-p02/tests/conftest.py:132).
- Trigger cụ thể: `TEST_DATABASE_URL=postgresql+psycopg://review@127.0.0.1:5432/review_test?dbname=folio` trong khi `DATABASE_URL` trỏ tới `folio` ở cùng server. Đây là URL minh họa, không phải cấu hình đã dùng để kết nối.
- Thực tế: hàm guard chấp nhận path `review_test`; SQLAlchemy `engine.dialect.create_connect_args(engine.url)` trả `dbname=folio`. Query parameters ghi đè database path trước khi psycopg kết nối. `prepare_test_database` sẽ dùng engine này để chạy `DROP SCHEMA IF EXISTS public CASCADE` nếu có quyền.
- Biến thể đã chứng minh: cùng DB `folio_test` với port mặc định bị bỏ qua ở một URL, hoặc `localhost` so với `127.0.0.1`, cũng qua collision guard. Cặp URL giống hệt và tên `folio` trong path bị từ chối đúng.
- Mong đợi: kiểm tra đích kết nối hiệu lực; từ chối query override/DSN ngoài chính sách; chỉ được reset tài nguyên test do run sở hữu.
- Tác động: mất dữ liệu khi URL hợp lệ về cú pháp nhưng đích thực tế không phải test; hai run cùng DB cũng có thể terminate connection của nhau tại dòng 113.
- Sửa tối thiểu: reject connection-target overrides, chuẩn hóa port/host và kiểm tra database hiệu lực; dùng tên DB duy nhất theo run, xác nhận ownership trước thao tác phá hủy. Không suy ra quyền xóa chỉ từ hậu tố `_test`.
- Nghiệm thu lại: các ca query `dbname`, port mặc định, alias host, URL thiếu/sai đều bị chặn trước tạo engine hoặc trước mutation; hai run độc lập không đụng connection/schema của nhau. Thử destructive path chỉ trên DB mới do test sở hữu.
- Bằng chứng: `guard-contract.json`; probe trích đúng function qua AST và gọi driver argument builder, **không import conftest, không mở DB connection, không chạy DROP**.

### IA-03 — High — Rotate bootstrap có thể chọn nhầm tài khoản và tự nâng quyền

**Chặn P03: Có, để nghiệm thu nền P01 theo yêu cầu bootstrap không tự nâng quyền ngoài dự kiến.** Đây là lỗi CLI vận hành, không phải đường leo quyền từ HTTP công khai.

- Vị trí: [bootstrap_admin.py:80](F:/dpl13.10/WikiSearchEngine-p01/scripts/bootstrap_admin.py:80), [bootstrap_admin.py:95](F:/dpl13.10/WikiSearchEngine-p01/scripts/bootstrap_admin.py:95), [bootstrap_admin.py:162](F:/dpl13.10/WikiSearchEngine-p01/scripts/bootstrap_admin.py:162).
- Tái hiện: có user `existing_member`, email `member@invalid.example`, role `member`; gọi bootstrap với username đó, email khác và `rotate=True`.
- Thực tế: lookup dùng `email OR username` rồi `.first()`; bỏ qua email không khớp, đổi password, đặt `role_key=super_admin`, kích hoạt tài khoản và báo rotate thành công. Probe thu được `targeted_existing_member=true`, `role_after=super_admin`, `email_matches_requested=false`.
- Mong đợi: rotate đúng admin đã định danh; mismatch email/username hoặc user không phải admin phải bị từ chối. Nếu cần recovery/promotion, phải là thao tác riêng rõ ràng theo chính sách vận hành.
- Tác động: operator gõ sai email/username vẫn có thể đổi mật khẩu và nâng quyền người khác; trường hợp email và username thuộc hai người còn không có lựa chọn xác định.
- Sửa tối thiểu: kiểm tra identity khớp duy nhất, kiểm tra role trước rotate; tách recovery nếu thật sự cần. Không âm thầm promote khi cờ chỉ mang nghĩa rotate password.
- Nghiệm thu lại: admin đúng rotate/revoke thành công; member, identity mismatch, hai identity trùng hai người đều fail không thay đổi DB. Kiểm tra bootstrap CLI subprocess trên PostgreSQL sạch, không đưa password lên command line.
- Giới hạn bằng chứng: logic được chạy trên SQLAlchemy SQLite in-memory với schema và function thật; không coi đây là chứng nhận PostgreSQL/migration/CLI end-to-end.

### IA-04 — Medium — Contract UUIDv4 loại bỏ toàn bộ ID fixture hiện có

**Chặn P03: Có, cần chốt sửa contract trước khi viết importer/schema.** Không yêu cầu đổi ID dữ liệu.

- Vị trí: [search-contract.md:13](F:/dpl13.10/WikiSearchEngine-github/docs/search-contract.md:13), [documents.jsonl:1](F:/dpl13.10/WikiSearchEngine-github/fixtures/folio/documents.jsonl:1), [seed_folio.py:156](F:/dpl13.10/WikiSearchEngine-github/scripts/seed_folio.py:156), [document.py:19](F:/dpl13.10/WikiSearchEngine-github/src/backend/models/document.py:19).
- Tái hiện: parse tất cả `id` trong JSONL bằng `uuid.UUID(...).version`.
- Thực tế: **103/103 ID là UUIDv5**, có 100 published + 3 draft; contract lại gọi canonical ID là UUIDv4. Model lưu `String(36)`, default mới tạo UUIDv4, seed giữ ID từ fixture.
- Mong đợi: Document ID là ID Folio hiện hữu, giữ nguyên qua import/index/log; chấp nhận các phiên bản UUID đã có. Default UUIDv4 cho bài mới không phải ràng buộc UUIDv4 cho mọi dữ liệu.
- Tác động: importer hoặc foreign-key/API validation theo contract có thể reject tất cả fixture hoặc cấp lại ID, làm hỏng liên kết, qrels và interaction log.
- Sửa tối thiểu: đổi wording sang UUID canonical không ràng buộc v4; quy định preserve existing ID khi map source URL. Không migrate lại toàn bộ ID.
- Nghiệm thu lại: fixture 103 tài liệu giữ nguyên ID; import lại không tạo bản sao; FK/index/log đều tham chiếu ID đó.

### IA-05 — Medium — Phân trang chưa có hợp đồng giữ generation và candidate window

**Chặn P03: Có, ở mức quyết định contract tối thiểu.** Không yêu cầu triển khai search API trước P03.

- Vị trí: [search-contract.md:36](F:/dpl13.10/WikiSearchEngine-github/docs/search-contract.md:36), [search-contract.md:76](F:/dpl13.10/WikiSearchEngine-github/docs/search-contract.md:76), [search-contract.md:113](F:/dpl13.10/WikiSearchEngine-github/docs/search-contract.md:113). Nguồn yêu cầu: [FOLIO-COMPLETION-PLAN.md:144](F:/dpl13.10/WikiSearchEngine-github/FOLIO-COMPLETION-PLAN.md:144).
- Trigger thiết kế: request page 1 ở generation G1; worker swap G2; client request page 2. Request hiện chỉ có `page/page_size`, không có generation/session/cursor binding hoặc quy tắc hết hạn.
- Thực tế: tie-break bằng ID chỉ bảo đảm thứ tự trong cùng tập/điểm; không giữ được thứ tự qua generation swap. Response dùng `total/total_pages` chung cho mọi mode, chưa nêu exact lexical count hay giới hạn candidate window/`has_more` cho semantic/hybrid.
- Mong đợi: contract giải thích cách nối các trang cùng search context/generation, thời gian giữ generation cũ hoặc lỗi khi context hết hạn; định nghĩa count/window cho từng mode.
- Tác động: P03 có thể xóa generation cũ quá sớm hoặc thiết kế storage/reader interface không đủ cho P04/P05; phân trang có thể trùng/mất kết quả và báo total sai.
- Sửa tối thiểu: thêm quyết định ngắn về generation/session binding, retention/expiry và count semantics. Giữ API browse hiện tại; chưa chọn thêm kiến trúc search ngoài plan.
- Nghiệm thu lại: một ví dụ page 1 -> swap -> page 2 có kết quả hoặc lỗi được định nghĩa; semantic/hybrid không tuyên bố exact corpus total từ top-k. Ghi thêm date filter dùng `created_at` hay `published_at` và freshness 60 giây từ plan để P03/P04 không tự suy diễn.

### IA-06 — Medium — Rate limiter P01 chưa dùng chung giữa các process

**Chặn P03: Không.** Có thể xử lý độc lập trước nghiệm thu abuse protection/production nhiều process; không ảnh hưởng schema importer/index.

- Vị trí: [rate_limit.py:9](F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/rate_limit.py:9), [rate_limit.py:55](F:/dpl13.10/WikiSearchEngine-p01/src/backend/core/rate_limit.py:55), [auth.py:149](F:/dpl13.10/WikiSearchEngine-p01/src/backend/api/auth.py:149). Yêu cầu M1: rate limit nhất quán giữa process tại [FOLIO-COMPLETION-PLAN.md:94](F:/dpl13.10/WikiSearchEngine-github/FOLIO-COMPLETION-PLAN.md:94).
- Trigger: hai web workers phục vụ cùng IP/email; gửi failed logins hoặc registrations luân phiên tới mỗi process.
- Thực tế: singleton chứa dictionary/Lock trong từng process; worker thứ hai có bộ đếm rỗng, restart cũng xóa bộ đếm. Test abuse hiện chỉ kiểm tra một TestClient/process.
- Mong đợi: ngưỡng áp dụng nhất quán theo policy đã nêu trong M1.
- Tác động: tổng số attempts vượt giới hạn theo số process; thread-safe không chứng minh process-safe.
- Sửa tối thiểu: dùng cơ chế chia sẻ phù hợp stack đã chọn, hoặc ghi rõ hạn chế một web process có cưỡng chế và điều kiện hoàn thiện trước production. Không tự thêm Redis/Celery trong review.
- Nghiệm thu lại: gửi requests tới hai process vẫn áp dụng cùng ngưỡng; policy restart được ghi rõ. Finding này là phân tích đường code, chưa chạy load test nhiều process.

### IA-07 — Medium — P02 vẫn ghi đè screenshot bàn giao từ browser tests

**Chặn P03: Không.** Có thể chạy regression trong bản sao dùng riêng cho review, không có ảnh bàn giao cần giữ, rồi lưu artifact riêng. Không bắt buộc sửa finding này trước P03 nếu cách chạy đó đã chứng minh regression; cần sửa trước chạy suite trên checkout chứa ảnh cần bảo toàn.

- Vị trí: [test_admin_screenshots.py:12](F:/dpl13.10/WikiSearchEngine-p02/tests/frontend/admin/test_admin_screenshots.py:12), [test_public_flows.py:14](F:/dpl13.10/WikiSearchEngine-p02/tests/frontend/public/test_public_flows.py:14), [tests/conftest.py:26](F:/dpl13.10/WikiSearchEngine-p02/tests/conftest.py:26).
- Trigger: chạy `pytest tests/frontend` hai lần trong cùng checkout hoặc chạy với bộ ảnh bàn giao đang có.
- Thực tế: public/admin tests vẫn ghi vào `docs/verification/...` với tên cố định; failure artifacts cũng không có run ID. Diff P02 chứa 34 PNG thay đổi trong thư mục verification. Script capture riêng đã có `--output-dir`/`FOLIO_SCREENSHOT_DIR`, nhưng cấu hình đó không điều khiển các tests này.
- Mong đợi: toàn bộ screenshot/trace output tách theo run/worktree/commit; không ghi đè ảnh bàn giao. Các worktree hiện có thư mục verification riêng nên không khẳng định chúng ghi vào cùng path; lỗi còn lại là overwrite ảnh tracked và không tách run.
- Tác động: chạy test làm dirty/ghi đè bằng chứng cũ; khó xác định ảnh thuộc lần chạy nào.
- Sửa tối thiểu: dùng chung artifact-root cấu hình được trong capture và fixtures; thêm run ID; cập nhật CI artifact paths. Không phục hồi các ảnh public đã bỏ khỏi Git.
- Nghiệm thu lại: chạy browser suite hai lần, thư mục output khác nhau và `git diff -- docs/verification` rỗng. Kiểm tra trace thật: hiện conftest tạo thư mục traces nhưng không thấy lệnh `context.tracing.start/stop`, nên không coi trace là đã được chứng minh.

## 4. Bảng đối chiếu yêu cầu

Quy ước: PASS chỉ áp dụng cho bằng chứng được mô tả ở cùng dòng. Các PASS nhánh riêng không nâng trạng thái Integration A. FAIL là sai lệch implementation/contract đã thấy; UNVERIFIED là chưa có bằng chứng thực thi đủ, bao gồm thiếu dịch vụ.

| Yêu cầu | Nguồn | Implementation / tài liệu | Bằng chứng mới | Trạng thái |
| --- | --- | --- | --- | --- |
| Xác định đúng repo, ref, phạm vi tích hợp | Prompt chung/P03 | main và hai worktree | Git refs/log/diff/status; không có P01/P02 trong main | FAIL (IA-01) |
| P00 phân biệt lịch sử với baseline mới | P00 mục 1 | `docs/handoff/gemini/P00-baseline.md` | Đọc văn bản; 58 pass được gắn historical, clone ghi NOT RUN | PASS |
| Acceptance matrix có scope/source/owner/check | P00 mục 2 | `docs/acceptance-matrix.md` | Đối chiếu yêu cầu Phase 1/2/UI/release; không claim Phase 2 complete | PASS ở mức đặc tả; các test rows chưa nghiệm thu |
| Core lexical khác legacy/advanced | P00 + plan M0 | matrix, main, catalog, legacy service | Catalog dùng ILIKE; `/search` legacy feature flag; `/api/v1/search` là tương lai | PASS |
| Canonical ID không mâu thuẫn dữ liệu | P00 mục 3 | contract:13, document model, fixture | 103 UUIDv5 đối lập yêu cầu UUIDv4 | FAIL (IA-04) |
| Query, mode, filter, response, lỗi cơ bản | P00 mục 3 | contract mục 2/3/6/7 | q 1-200/trim/422; AND tags; date range; live publication; explicit fallback; backward compatibility | PASS phần đã định nghĩa; unknown taxonomy/error schema chi tiết và trường date còn UNVERIFIED |
| Stable pagination và generation | P00 + M4 | contract:36/76/113 | Không có binding/expiry; thiếu candidate-window counts | FAIL (IA-05) |
| Production validator trong startup thật | P01 mục 1 | main vs P01 lifespan | TestClient chạy lifespan: main nhận cấu hình sai; P01 từ chối 4 case | FAIL ở main; PASS targeted ở P01 |
| Dev/test/staging/prod, cookie, CORS | P01 mục 2/4 | P01 config/session/middleware | Có normalize aliases, explicit origins, cookie flags; startup wildcard rejection | PASS phần startup đã chạy; HTTPS/proxy/cookie browser UNVERIFIED |
| Bootstrap sạch, lặp lại, rotate đúng người | P01 mục 3/6 | P01 bootstrap CLI/function | SQLite probe create/hash/duplicate/revoke thành công; mismatch promote member | FAIL (IA-03); PostgreSQL CLI UNVERIFIED |
| Auth/CSRF/RBAC thực thi ở backend | P01 mục 4 | dependencies.py, auth, admin router | Đọc dependency guards; chưa chạy HTTP role tests trên PostgreSQL | UNVERIFIED |
| Lỗi production không lộ internals | P01 mục 5/6 | health/error handler | Fault injection: main lộ marker; P01 trả 503 không marker | FAIL ở main; PASS targeted ở P01 |
| Abuse limit nhất quán nhiều process | Plan M1 | P01 rate_limit.py | Counter trong RAM từng process | FAIL (IA-06), non-blocker P03 |
| Clean venv/dependency install | P02 mục 1 | P02 requirements + constraints | Venv mới, system-site-packages=false; install + pip check exit 0 | PASS Windows dependency subset; Linux/legacy UNVERIFIED |
| Test DB guard và isolation | P02 mục 2/3 | main/P02 conftest | Main substring guard; P02 driver dbname override qua guard trước DROP | FAIL (IA-02) |
| Migration DB sạch | P02 mục 2 | 2 Alembic revisions | Một head, offline SQL exit 0; online không có PG test server | UNVERIFIED |
| Seed hai lần/idempotency | P02 mục 5 | seed script, workflow | Workflow chạy 2 lệnh nhưng không assert counts/IDs; chưa chạy PG sạch | UNVERIFIED |
| Backend regression | P01/P02 | tests/backend | 58 collected ở main; DB setup negative probe error; không có test body pass | UNVERIFIED |
| Frontend browser suite | P02 mục 4/5 | tests/frontend | 15 collected ở main; chưa chạy browser E2E | UNVERIFIED |
| Frontend lint/typecheck/build | Công cụ hiện có | Vanilla JS, không package.json/build scripts | Không có lệnh chuẩn được repo khai báo | NOT APPLICABLE |
| Chromium/readiness | P02 mục 4 | P02 common fixtures/CI | Đọc cấu hình: bundled Chromium mặc định, health polling; main còn system Chrome/sleep | FAIL ở main; implementation P02 có, runtime UNVERIFIED |
| Artifact isolation | P02 mục 5 | capture + browser tests | Capture P02 cấu hình được; tests vẫn overwrite tracked verification | FAIL (IA-07) |
| CI Linux đúng SHA | P02 mục 5 | `.github/workflows/ci.yml` chỉ ở P02 | Đọc jobs Python 3.10/PG16/backend/browser, không continue-on-error; GitHub API main SHA: 0 runs | UNVERIFIED runtime; chưa có workflow ở main |
| P01/P02 env/seed giao nhau | Integration A | seed API, config, fixtures | Chưa tích hợp; seed signatures/CLI khác nhau cần hợp nhất | FAIL (IA-01) |
| Importer/outbox/worker/BM25/search API | P03-P05 | Chưa triển khai | Đây là phạm vi tiếp theo | NOT APPLICABLE cho nghiệm thu P00-P02 |

## 5. Kiểm tra đã thực thi và evidence

Evidence nằm trong `docs/handoff/review/evidence-20261101-cf1bdce021/`. JSON và logs là kết quả lượt này; script probes được giữ để tái hiện. Không có .env, credentials hay database dump trong evidence.

Lệnh dọn thư mục tạm đã bị chính sách thực thi tự động từ chối (`blocked by policy`); không thử lách bằng công cụ khác. Thư mục `C:/Users/Admin/AppData/Local/Temp/folio-ia-review-cf1bdce021` còn chứa venv và bản gốc probes/logs. Evidence bàn giao đã được sao chép và kiểm tra JSON trước bước dọn này.

### 5.1 Môi trường

- Windows, Python 3.10.11. Venv riêng được tạo bằng `python -m venv` tại `%TEMP%/folio-ia-review-cf1bdce021/venv`; `include-system-site-packages = false`.
- Không dùng venv cũ/P01/P02, không đọc hoặc copy secrets trong `.env`; probes đặt `PYTHON_DOTENV_DISABLED=1`, `PYTHONDONTWRITEBYTECODE=1` và URL test riêng.
- Cài đúng manifests P02 vào venv review: `python -m pip install -r F:/dpl13.10/WikiSearchEngine-p02/requirements-browser.txt -c F:/dpl13.10/WikiSearchEngine-p02/constraints.txt --disable-pip-version-check`. Exit 0. Wheel cache có được pip sử dụng; không phải model cache hay global site-packages. Không kiểm chứng install cache-empty/offline/Linux.
- `python -m pip check`: exit 0, `No broken requirements found.` Versions thực tế lưu ở `pip-freeze.txt`. Các dependency transitively không pin hết vẫn có thể đổi ở lần cài khác.
- Không tìm thấy `docker`, `psql`, `pg_ctl` trong PATH, service PostgreSQL/Docker hoặc listener 5432/5433 bằng các lệnh đã chạy. Không suy ra không thể có server ở nơi khác. Không có PostgreSQL test mới được provision trong lượt này; không dùng DB có sẵn của người dùng để bù.

### 5.2 Lệnh và kết quả

`python` trong bảng là Python của venv review. Cwd mặc định là repo nghiệm thu, trừ khi nêu nhánh khác.

| ID | Lệnh / điều kiện | Kết quả và exit | Phạm vi bằng chứng |
| --- | --- | --- | --- |
| C01 | `git remote -v`, `branch --show-current`, `rev-parse HEAD`, `status --short`, `diff`, `diff --cached`, `worktree list --porcelain`, `log main..<branch>`, `merge-base` | Exit 0 sau xử lý ownership bằng lệnh đọc phù hợp | Main chưa tích hợp; phạm vi refs đã xác định. Không sửa global Git config |
| C02 | `python -m venv ...`; pip install P02 constraints; `pip check` | Exit 0 | Clean dependency install Windows; không chứng minh full setup |
| C03 | `python probe_guard_contract.py` | Exit 0; 3 ca guard nguy hiểm được chấp nhận, 2 ca được chặn | Pure function + effective driver kwargs; không connection/mutation |
| C04 | `python probe_runtime.py F:/dpl13.10/WikiSearchEngine-github` | Exit 0; valid boot thành công nhưng 4 cấu hình sai cũng boot; bootstrap absent | FAIL yêu cầu production startup. Exit 0 nghĩa probe hoàn tất, không phải gate pass |
| C05 | `python probe_runtime.py F:/dpl13.10/WikiSearchEngine-p01` | Exit 0; valid boot thành công, 4 case sai raise ValueError | PASS targeted lifespan; không phải HTTPS/server deployment |
| C06 | Cùng runtime probes: DB unreachable + injected internal error `/health` | HTTP 503 ở cả hai; marker bị lộ trên main, được giấu ở P01 | Chứng minh error path; fault injection được khai báo rõ |
| C07 | Cùng P01 probe: bootstrap trên SQLite in-memory | Create/hash/duplicate rejection/rotate/revoke PASS; member mismatch bị promote | FAIL IA-03; không chứng minh migration/CLI/PostgreSQL |
| C08 | `python -m alembic heads` | Exit 0; `20261031_click_unique (head)` | Hai revision cùng một chain; cả P01/P02 không thay migration |
| C09 | `python -m alembic upgrade head --sql` | Exit 0 | SQL offline sinh được; không phải migration đã apply |
| C10 | `python -m alembic upgrade head` trong negative environment probe | Exit 1; connection timeout | UNVERIFIED online migration, lỗi môi trường có chủ đích; không kết luận migration/application bug |
| C11 | `python -m pytest tests/backend --collect-only -q -p no:cacheprovider` | Exit 0; 58 collected | Collection/import main thành công, không phải 58 passed |
| C12 | `python -m pytest tests/backend -q --maxfail=1 --tb=short -p no:cacheprovider --junitxml=<review-temp>/backend-junit.xml` | Exit 1; 1 setup ERROR, chưa test body nào chạy | UNVERIFIED backend suite; negative environment probe, không báo application regression |
| C13 | `python -m pytest tests/frontend --collect-only -q -p no:cacheprovider` | Exit 0; 15 collected | Không launch browser, không tạo ảnh mới/ghi đè ảnh bàn giao |
| C14 | `gh api repos/MarcusCyborg/folio/actions/runs --method GET -f head_sha=c4b19cffa676b4437e7346da2c410b198b04dc2c --jq '{total_count, runs: [.workflow_runs[] | {head_sha,status,conclusion,html_url}]}'` | Exit 0; `total_count=0`, `runs=[]` | Không có run CI cho HEAD main được API trả về tại lúc review |
| C15 | Cùng GitHub API query với `head_sha=1ac72ad8a9e979682ddad8253c0d6d3e49222055` | Exit 0; `total_count=0`, `runs=[]` | Cũng không có run được API trả về cho HEAD P02; không claim CI passed |

Với C10/C12, `run_checks.py` giữ một socket loopback được bind nhưng không listen và trỏ URL không mật khẩu tới port đó, tên DB riêng `ia_review_main_test`/`ia_review_suite_test`. Mục đích là xác nhận runner dừng ở lỗi thiếu DB mà không bao giờ chạm tài nguyên có sẵn. Đây **không phải** nỗ lực dùng database thật rồi thất bại, và **không** chứng minh suite hoạt động trên PostgreSQL. Các logs ghi connection timeout đúng điều kiện này.

Không chạy full frontend vì chưa có PostgreSQL riêng và tests hiện còn overwrite artifact paths. Không thêm framework test hoặc cài optional legacy ML/model. Không có lint/typecheck/build command frontend được khai báo để chạy.

## 6. Giới hạn, mâu thuẫn evidence và phần chưa xác minh

1. Chưa có bản tích hợp; mọi kết quả P01/P02 riêng không thay thế Integration A. Không tự merge để tạo bản nghiệm thu giả định.
2. Chưa chạy migration/seed/bootstrap subprocess/role checks/browser E2E trên PostgreSQL mới. SQLite probe chỉ dùng chứng minh lỗi chọn user và thao tác bootstrap; khác biệt transaction/concurrency/SQL dialect còn chưa kiểm chứng.
3. Chưa chạy HTTPS reverse proxy, cookie browser, origin flows hoàn chỉnh, disabled-user/revoke qua HTTP, production DB invalid-URL matrix, nhiều web process, import-cycle regression sau merge hoặc CI Linux. Không coi guard đọc source là auth test đã pass.
4. P02 handoff/README ghi 162 published + 3 drafts và fixture 165, trong khi fixture hiện tại cùng baseline chứa 100 published + 3 drafts, 103 ID/URL duy nhất. Không có thay đổi fixture trong diff P02. Cần giải thích dataset/environment của evidence cũ và thay bằng run sạch; không suy diễn rằng con số đó chứng minh seed bị lỗi.
5. P00 matrix gọi hai revision là "Alembic heads"; lệnh thực tế chỉ có một head `20261031_click_unique`. Đây là chỉnh tài liệu, không phải migration conflict.
6. Contract có query validation, publication/live DB defense, fallback khai báo engine và backward compatibility. Chưa đặc tả đủ generation pinning/count window; date filter chưa nói trường timestamp; chưa chốt xử lý taxonomy ID đúng cú pháp nhưng không tồn tại. Các chi tiết response errors/API sau có thể hoàn thiện ở P05 nếu không đổi nền P03.
7. P01 handoff nói production cần explicit CORS list, nhưng code cho list rỗng với same-origin behavior; chưa có bằng chứng đó là lỗi bảo mật. Cần sửa mô tả cho đúng policy. Không báo wildcard vulnerability ở P01 vì middleware lọc wildcard và validator production từ chối nó.
8. P02 fixture savepoint áp dụng cho `db_session`/TestClient; live browser server dùng SessionLocal riêng và nhiều frontend test không dùng fixture đó. Chưa chứng minh isolation giữa browser tests/order independence. CI seed chạy hai lần nhưng không assert IDs/counts/unchanged edits; chưa coi idempotency là đã đạt.
9. CI jobs có PG16 service, Python 3.10, venv, migration/seed/backend và Chromium/frontend; không thấy `continue-on-error` che test fail. Điều đó là kiểm tra cấu hình tĩnh, không phải kết quả remote CI.
10. P00 không tuyên bố legacy BM25/Chroma đã tích hợp Folio. Các hạng mục importer/outbox/BM25/search API/evaluation/deploy sau vẫn đúng phạm vi P03-P09, không bị đánh FAIL vì chưa làm.

## 7. Việc cần sửa theo thứ tự

### Blocker trước khi bắt đầu P03

1. **IA-02:** sửa guard và ownership DB test trước khi chạy fixture P02 có DROP/terminate. Dùng DB mới, tên duy nhất; không chạy lại vào shared `folio_test` để thử sửa.
2. **IA-03:** rotate chỉ đúng admin đã xác minh identity; negative tests cho mismatch/member/multiple matches.
3. **IA-04/IA-05:** chốt canonical UUID không ràng buộc v4 và quyết định generation/session/expiry/count. Đây là bổ sung contract ngắn, không làm trước tính năng P03/P05.
4. **IA-01:** tích hợp P01/P02 vào một branch/checkout, giữ seed signatures/CLI/security guards, mang đủ handoff vào bản chung.
5. Chạy lại migration sạch, seed idempotency, bootstrap, backend/security và frontend cần thiết bằng artifact path an toàn; ghi SHA/dataset/env thật. Phần thiếu bằng chứng nền này cũng là blocker nghiệm thu Integration A.

### Non-blocker đối với thiết kế P03

- **IA-06:** hoàn thiện cross-process rate limiting trước production nhiều workers; có owner và điều kiện nghiệm thu riêng.
- **IA-07:** thống nhất artifact paths; trong lúc chờ có thể chạy browser regression trong bản sao disposable và lưu output riêng, không overwrite evidence của người dùng. Không buộc thay đổi schema index.
- Sửa handoff seed counts, Alembic-head wording, CORS policy docs; bổ sung assertion idempotency/trace evidence và chứng minh browser isolation.
- Hosting/domain, production HTTPS rollout, legacy model/cache, semantic quality, UI responsive và retrieval evaluation tiếp tục ở đúng các mốc sau. Không dùng chúng làm blocker P03 trong báo cáo này.

## 8. Điều kiện nghiệm thu lại Integration A

- Cung cấp một SHA tích hợp xác định, status và diff được ghi; có P00 contract cập nhật và cả P01/P02 implementation.
- DB test được tạo mới, không trùng app DB kể cả query override/host alias/default port; fixture không reset tài nguyên không thuộc run.
- Alembic upgrade từ DB trống thành công; kiểm tra đúng head và schema. Seed lần hai không thêm trùng document/user, giữ ID/URL và các chỉnh sửa cần bảo toàn; giải thích counts theo fixture thực tế.
- Startup từ env thực: valid production thành công; thiếu/yếu secret, insecure cookie, invalid environment và cấu hình quan trọng không hợp lệ fail sớm. Public error không lộ nội bộ.
- Bootstrap CLI dùng secret env/getpass trên DB vừa migrate: tạo admin, chạy lại an toàn, rotate đúng identity, revoke session; mismatch/member không promote ngoài policy.
- Backend suite mới chứa cả security tests P01 và fixtures P02 chạy pass; có API role/CSRF/disabled-user/abuse checks. Không dùng collection count hoặc report cũ để thay.
- Browser suite chạy trên test DB và Chromium riêng, artifacts tách run; không overwrite tracked verification. Kiểm tra seed/env/CORS integration ở cùng checkout.
- Nếu CI chưa có run cho SHA đó, giữ Linux CI là UNVERIFIED và chỉ cân nhắc GO WITH CONDITIONS khi đã có bằng chứng local/clean đủ cho nền P03; không gọi là GO nếu blocker nền còn tồn tại.

## 9. Bàn giao cho P03

Những nền tảng có thể giữ: PostgreSQL là nguồn chính; `Document.id` hiện hữu là khóa canonical; source URL có unique index và là metadata/provenance; `source_license`/`source_attribution` đã có; published/deleted phải được kiểm tra live; outbox cùng transaction; rebuild generation mới rồi swap, chống stale revision. Schema index/outbox/worker mới vẫn thuộc P03.

Đoạn bổ sung đề nghị cho prompt P03, **chỉ dùng sau khi Integration A được nghiệm thu lại**:

> Bắt đầu từ SHA tích hợp P01/P02 đã được ghi trong báo cáo Integration A mới. Không chạy trên `main` c4b19cf hoặc chỉ một nhánh riêng. Giữ nguyên mọi Document ID đã có, gồm UUIDv5 trong fixture; UUIDv4 chỉ là default tạo mới. Đọc quyết định bổ sung của search contract về generation/session binding, retention/expiry và count/window trước thiết kế generation/reader. Dùng test DB do run sở hữu với guard đã kiểm tra effective driver target; không reset shared database. Giữ API seed hợp nhất của P01/P02 và production demo-user guard. Bằng chứng chuẩn là migration/seed/bootstrap/backend/browser mới trên cùng SHA, không phải các handoff 58/70 tests cũ. P03 chỉ triển khai importer, schema/outbox và lifecycle worker; BM25 scoring và search API tiếp tục thuộc P04/P05.

Kết luận này chỉ đánh giá khả năng bắt đầu P03. Chưa có bằng chứng để tuyên bố sẵn sàng deploy production.
