# Kế hoạch sửa Integration A cho Gemini

Ngày lập: 01/11/2026. Trạng thái: kế hoạch, chưa thực hiện sửa code hoặc merge.

Nguồn: [INTEGRATION-A-REVIEW.md](F:/dpl13.10/WikiSearchEngine-github/docs/handoff/review/INTEGRATION-A-REVIEW.md), FOLIO-COMPLETION-PLAN.md và GEMINI-EXECUTION-PROMPTS.md.

## 1. Mục tiêu và cách tổ chức

Sửa 7 findings IA-01 đến IA-07, bổ sung bằng chứng còn thiếu và tạo một SHA tích hợp đủ điều kiện bắt đầu P03. Giữ FastAPI, PostgreSQL, SQLAlchemy/Alembic, vanilla JS. Chưa triển khai importer, outbox, index worker, BM25 hay search API mới.

Đề nghị dùng **8 chat Gemini chạy tuần tự**, gồm R00-R04.5 và R05-R06. Tất cả dùng cùng worktree tích hợp do R00 chuẩn bị. Không tiếp tục sửa rải rác trên P01/P02 rồi chỉ trao đổi handoff.

```text
R00: Tích hợp source, chưa chạy fixture cũ
  -> R01: Test DB safety + môi trường PostgreSQL riêng
  -> R02: Bootstrap identity + startup/security regression
  -> R03: Chốt Document ID và pagination/generation contract
  -> R04: Rate limit dùng chung giữa process
  -> R04.5: Integration A checkpoint sau R02-R04
  -> R05: Artifact isolation + clean setup/CI + regression
  -> R06: Review độc lập -> GO / GO WITH CONDITIONS / NO-GO
  -> P03 chỉ khi không còn blocker
```

R00 tích hợp trước để các bản sửa cùng nằm trên một nền. Việc này không mâu thuẫn ưu tiên IA-02: **không chạy pytest fixture, seed, migration hoặc CLI đụng DB trong R00**. R01 phải đóng đường unsafe trước lần chạy tích hợp đầu tiên.

IA-06 và IA-07 vẫn là non-blocker đối với kiến trúc P03 như báo cáo gốc. Kế hoạch mặc định sửa cả hai vì người dùng yêu cầu sửa các findings; không đổi phân loại để buộc làm trước mọi tính năng production.

R04.5 là checkpoint bắt buộc trước R05, không phải một remediation stream mới. Nó rà lại ancestry, migration head, shared test fixture và các handoff sau khi R02-R04 đã cùng nằm trên branch. R04.5 được phép sửa lỗi tích hợp nhỏ phát hiện tại checkpoint; nếu phát hiện lỗi thiết kế lớn thì dừng và tạo follow-up thay vì mở P03.

## 2. Baseline, workspace và quyền thao tác

Đã đọc lại refs khi lập kế hoạch:

| Vai trò | Ref / đường dẫn | SHA tham khảo |
| --- | --- | --- |
| Repo nguồn | `F:/dpl13.10/WikiSearchEngine-github`, main | `c4b19cffa676b4437e7346da2c410b198b04dc2c` |
| P01 | `feature/p01-security`, `F:/dpl13.10/WikiSearchEngine-p01` | `740eb5f1cc5f6b0c90480310e37a36234086a726` |
| P02 | `feature/p02-clean-setup`, `F:/dpl13.10/WikiSearchEngine-p02` | `1ac72ad8a9e979682ddad8253c0d6d3e49222055` |
| Branch tích hợp đề nghị | `codex/integration-a-remediation` | R00 tạo hoặc xác minh nhánh phù hợp đã có |
| Worktree tích hợp đề nghị | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Chưa tạo trong lượt lập kế hoạch |

Mỗi chat phải xác minh lại refs, origin, status, AGENTS.md và handoff. SHA trên là mốc tham khảo, không phải lệnh reset. Nếu nhánh đã thay đổi, đọc diff mới để cập nhật phạm vi; không ghi đè hoặc bỏ các thay đổi mới.

Khi người dùng giao prompt R00, phạm vi của prompt bao gồm tạo worktree/branch mới và tích hợp local P01/P02 vào branch đó. Đây là ngoại lệ có giới hạn so với quy tắc "không merge thay người khác" của prompt pack cũ. **Không merge vào main**, không rewrite lịch sử, không push, không deploy. R01-R05 được commit local các file thuộc nhiệm vụ sau khi review diff; không amend. R06 chỉ kiểm tra và viết báo cáo.

Việc lập kế hoạch này không thực hiện các thao tác trên. Không tự tạo chat mới hoặc nhắn sang các chat cũ; người dùng mở chat và giao prompt tương ứng.

Repo nguồn có tài liệu untracked, trong khi P02 đã track một số file cùng tên. R00 phải kiểm kê và so sánh nội dung trước copy. Tuyệt đối không stash/reset/clean/xóa những file đó để "làm sạch" main. Không copy `.env`, venv, DB, model cache hoặc thư mục data cũ.

Sau R00, target nghiệm thu và P03 là **worktree/branch tích hợp được ghi rõ trong handoff**, không còn mặc định main. Main có thể giữ nguyên trong suốt đợt sửa; readiness của branch tích hợp không đồng nghĩa đã cập nhật main.

## 3. Quy tắc bằng chứng dùng chung

- Chỉ PASS nếu chat hiện tại thực thi kiểm tra phù hợp. Lưu command, cwd, SHA, runtime, env đã che secret, exit code, test count và đường dẫn artifact.
- `collect-only`, SQL offline, mock hoặc SQLite chỉ chứng minh đúng phạm vi đó; không thay PostgreSQL migration/full suite hoặc browser tests.
- Test lỗi do thiếu dịch vụ ghi BLOCKED_ENV; không sửa expected status, disable validator, thêm xfail/skip hoặc nuốt exception để đạt xanh.
- Không dùng DB phát triển/production hoặc shared `folio_test`. Chỉ tác động tài nguyên mới do run sở hữu; teardown kiểm tra ownership và đúng đích thực tế.
- Không in password/token/full connection URL. CLI bootstrap lấy secret từ environment hoặc getpass, không từ đối số hiện trên process list.
- Không thêm Redis/Celery, framework test hoặc plugin random-order chỉ để sửa findings. Dùng pytest, Playwright, SQLAlchemy/Psycopg và stdlib hiện có.
- Dừng ngay khi thấy source đang bị sửa đồng thời không thuộc chat; báo phạm vi ảnh hưởng. Không đánh giá một snapshot không ổn định.
- Giữ nguyên báo cáo review cũ. Handoff/review mới nếu tên tồn tại thì thêm timestamp, không overwrite evidence cũ.

Handoff cho mỗi R gồm: branch/HEAD đầu vào, source SHA được kiểm tra, diff/files changed, quyết định, tests PASS/FAIL/BLOCKED, migration/env/CLI impact, artifact paths, việc còn lại và đầu vào cho R tiếp theo. Không chép số test lịch sử làm kết quả mới.

## 4. R00 — Tạo bản tích hợp có thể sửa và kiểm chứng

**Sửa:** phần source của IA-01. **Owner:** worktree tích hợp, merge conflicts, seed entrypoints và tài liệu baseline. Chưa được đánh IA-01 CLOSED vì còn thiếu test tích hợp.

### Công việc

1. Đọc report, hai handoff và diff hai nhánh so với common ancestor đã kiểm chứng. Kiểm kê file untracked ở repo nguồn.
2. Tạo worktree mới từ baseline xác minh được; tạo nhánh đề nghị nếu chưa có. Nếu đích đã tồn tại, xác minh nó thuộc đúng công việc trước khi tái sử dụng; không force hoặc xóa đích.
3. Tích hợp P01 rồi P02 vào nhánh mới. Giải quyết từng conflict theo behavior cần giữ; không dùng ours/theirs cho cả file.
4. Đưa report/plan/prompt/handoff cần thiết sang worktree bằng copy có đối chiếu, giữ bản gốc ở repo nguồn. Bản report đóng băng không được sửa nội dung; tài liệu contract cập nhật sau ở R03.
5. Hợp nhất `scripts/seed_folio.py`: giữ `run_seed(target=..., db_url=...)`, policy `skip_demo_users` và CLI `--no-demo-users`. Production/staging luôn bỏ demo users; một flag không được vô tình bật demo lại.
6. Làm rõ `--db-url` và `--test`: không được có precedence âm thầm khi cả hai được nhập. Seed function nhận Session từ caller phải có transaction ownership rõ, không tự commit ngoài ý caller. Engine/CLI sở hữu session có commit/rollback đầy đủ.
7. Giữ P01 lifespan, security middleware/config/bootstrap/tests và P02 requirements/constraints/fixture/CI. Đảm bảo bootstrap import các seed helper không chạy seed tại import.
8. Kiểm tra diff và ancestry; chỉ kiểm tra tĩnh an toàn, chưa chạy code có thể kết nối DB. Không xử lý lại 34 PNG có sẵn trong commit P02 dưới danh nghĩa cleanup.

### Nghiệm thu

- Cả hai source branch được bao gồm trong ancestry hoặc có giải thích merge tương đương rõ ràng; không mất các implementation kể trên.
- Không thay main, hai worktree nguồn hoặc file untracked có sẵn.
- Handoff `docs/handoff/gemini/IA-R00-integration.md` ghi worktree chính thức, source SHA, conflict resolutions và seed API cuối cùng.
- Trạng thái: SOURCE INTEGRATED, VALIDATION PENDING. Không GO/P03 lúc này.

## 5. R01 — Guard hiệu lực và DB test do run sở hữu

**Sửa:** IA-02; tạo nền thực thi cho R02-R06. **Owner:** test-target validation/provisioning module, conftest lifecycle, test infrastructure riêng; không sửa auth/search.

### Thiết kế yêu cầu

1. Tách validator thuần khỏi conftest và khỏi import ứng dụng/engine. Unit tests cho validator phải chạy được trước khi các fixture DB được load, ví dụ một test path riêng hoặc `pytest --noconftest` cho nhóm thuần.
2. Chọn policy URL test nhỏ, rõ: driver PostgreSQL đã hỗ trợ; host/port/database tường minh hoặc được normalize có kiểm soát; reject connection-target overrides như `dbname`, `host`, `port`, `service`, multi-host và hình thức DSN không được policy hỗ trợ. Allowlist query thật sự cần như timeout/SSL phải không đổi đích.
3. Đối chiếu với connect args hiệu lực của dialect, không chỉ `make_url().database`. Kiểm soát ambient libpq env/service files để chúng không thay đích sau bước guard; không log credential khi reject URL.
4. Chuẩn hóa port mặc định và alias loopback; không coi so sánh hostname là bằng chứng ownership. Provision một instance/DB riêng có tên duy nhất theo run và identifier đúng quy tắc PostgreSQL.
5. Chỉ reset/drop/terminate tài nguyên đã xác minh là do run tạo. Nếu DB dự định tạo đã tồn tại ngoài manifest sở hữu, chọn tên mới hoặc từ chối; không nhận làm của mình chỉ vì có `_test`.
6. Trước mutation, xác nhận connected database/server identity phù hợp manifest. Query kiểm tra identity không được đi kèm DROP tự động khi mismatch. Quyền DB role chỉ đủ phạm vi test nếu khả thi.
7. Loại bỏ cơ chế blanket terminate mọi connection vào shared test DB. Mỗi run có engine/session/server riêng; shutdown/dispose theo thứ tự trước cleanup.
8. Dựng PostgreSQL 16 test mới bằng runtime sẵn có, container riêng nếu Docker đã hoạt động, hoặc runtime local riêng không dùng data directory/service cũ. Không thay cấu hình dịch vụ hệ thống hoặc dùng remote DB thật để lách thiếu môi trường.

Nếu không provision được PostgreSQL: vẫn hoàn thành code guard và unit tests thuần, ghi BLOCKED_ENV rõ ràng. Không chứng nhận R01 DONE, không chạy fixture cũ để thử vận may; phần verification phụ thuộc DB chờ môi trường. Không dùng venv review còn sót làm bằng chứng clean install mới.

### Test bắt buộc

| Ca | Mong đợi |
| --- | --- |
| Path `review_test?dbname=folio` | Reject trước connection/mutation |
| Query override host/port/service và DSN không hỗ trợ | Reject, không lộ secret |
| Cùng target với default port bỏ trống/explicit, loopback alias | Không vượt collision protection |
| Database thiếu, protected name, URL malformed/không phải PostgreSQL | Reject rõ, không traceback chứa credentials |
| DB đã tồn tại nhưng không thuộc manifest run | Không DROP/CREATE SCHEMA/terminate |
| Hai runs đồng thời | DB khác nhau, không thấy dữ liệu hoặc ngắt connection của nhau |
| Fresh DB do run sở hữu | Alembic upgrade head thành công, seed đúng target |
| Teardown/retry sau lỗi | Chỉ dọn tài nguyên của run, không orphan process/connection không kiểm soát |

Bổ sung sentinel trên DB khác trong **cùng instance test disposable** để chứng minh nó không đổi sau rejection/teardown. Không dùng database thật làm sentinel. Handoff: `IA-R01-test-isolation.md`, gồm manifest không secret và cách tái tạo môi trường.

## 6. R02 — Bootstrap đúng identity và chứng minh nền security

**Sửa:** IA-03; kiểm chứng P01 trên source tích hợp. **Owner:** bootstrap CLI, security regression tests; config/main/auth chỉ sửa khi test chỉ ra lỗi trong phạm vi P01.

### Behavior cần chốt

- Create: chỉ tạo khi cả email và username chưa dùng. Va chạm một trong hai trả lỗi rõ, không đổi user có sẵn.
- Rotate: hai identity sau normalize phải thuộc cùng một account và account đó là super_admin phù hợp policy. Email/username trỏ hai người, khớp một nửa, member hoặc account không tồn tại đều fail không mutation.
- Rotate không âm thầm promote hoặc reactivate. Nếu cần recovery admin disabled, mô tả một command/flag vận hành riêng với identity checks; không mở rộng `--rotate` thành recovery ngầm. Có thể để recovery ngoài đợt sửa nếu tài liệu chỉ rõ.
- Rerun create với cùng identity được phép trả lỗi already-exists có exit code/documentation rõ; không yêu cầu exit 0 giả, nhưng không tạo trùng hay thay password/role.
- Rotate thành công giữ ID/role, cập nhật hash, revoke sessions theo policy, audit trong cùng transaction. Khi fail không ghi success audit hoặc partial mutation.
- Giữ password ở env/getpass; không có default password. Cân nhắc bỏ `--password` hoặc đánh dấu deprecated nếu tồn tại; không dùng nó trong automation/tests.

### Verification

1. DB PostgreSQL vừa migrate, chưa seed demo: CLI tạo admin thật; rerun; rotate; hash và session revocation được xác minh.
2. Negative matrix: mismatch từng chiều, hai user khác nhau, member, inactive account, no target, password thiếu/yếu, duplicate create/race nếu code cần xử lý unique constraint.
3. Snapshot account/hash/role/session trước và sau mỗi rejection; không chỉ assert exit code.
4. Fresh subprocess env production: valid boot; weak/missing secret, insecure cookie, invalid APP_ENV, wildcard CORS fail startup. TestClient lifespan có thể bổ trợ; không chỉ gọi validator method.
5. Guest/member/staff endpoints: 401/403 đúng ở backend, CSRF/origin rejection, disabled-user/revoke, cookie flags và health error redaction. Không disable limiter trên runtime để làm các tests pass; fixture reset phải có phạm vi test riêng.
6. Production/staging seed không tạo demo accounts; bootstrap vẫn hoạt động sau migration, không phụ thuộc schema/roles đã seed tay.

Handoff: `IA-R02-bootstrap-security.md`. Những test cần PostgreSQL không được thay bằng SQLite rồi báo PASS toàn mốc.

## 7. R03 — Contract đủ rõ để P03 không phải làm lại

**Sửa:** IA-04/IA-05. **Owner:** search contract, acceptance matrix, phần đầu vào P03 trong prompt pack; không sửa schema/index/API lúc này.

### Quyết định cần ghi thành contract

1. **ID:** UUID Folio hiện hữu là canonical, gồm v4/v5. Giữ nguyên 103 ID fixture và source URL mapping; default v4 chỉ áp dụng tạo mới. Không chuyển ID hàng loạt hoặc thêm validator UUID4 trên dữ liệu hiện có.
2. **Generation và pagination:** generation pinning đơn thuần không đủ nếu index cùng generation vẫn được worker cập nhật. Chốt cách giữ thứ tự/điểm của một search context khi có write hoặc generation swap.
3. **Phương án đề nghị:** search context do server cấp, gắn actor/session, query/filter/mode/page_size và generation; giữ snapshot danh sách candidate IDs/scores/order. Trang tiếp theo gửi token/context của request đầu. API/session storage thực hiện ở P05, generation lifecycle/retention contract cho P03. Không yêu cầu thêm dịch vụ ngoài PostgreSQL.
4. **Lifetime đề nghị:** TTL tuyệt đối 15 phút, cấu hình được, không gia hạn vô hạn khi đọc trang. Generation/context còn lease không được GC. Context hết hạn, bị mất hoặc generation không còn phục vụ trả lỗi rõ để client tìm lại; không âm thầm chuyển generation. Gemini phải chốt status/error code và ví dụ JSON trong doc. Đây là default thiết kế đề nghị, chưa phải behavior hiện có.
5. **Mutation trong context:** luôn check published/deleted live trước trả title/snippet. Định nghĩa trang bị prune trả ngắn hay backfill; default đơn giản là cửa sổ rank cố định, prune không backfill để không tạo duplicate giữa trang. Không để `has_more`/empty-page handling tự mâu thuẫn chính sách đó.
6. **Counts:** lexical có exact count tại snapshot; semantic/hybrid chỉ biết candidate window. Phân biệt `snapshot_total`/count accuracy với live total sau prune; không trả một field tên `total` mà claim exact live corpus cho mọi mode. Chốt null/omitted/flags và `has_more` bằng ví dụ, không chỉ thêm lời chú thích mơ hồ.
7. **Filters/sort:** đề nghị dùng `created_at` UTC cho date filters để nhất quán browse hiện tại; ghi rõ AND tags, invalid UUID/unknown taxon semantics, rank DESC và ID ASC trong snapshot. Mặc định browse không đổi, query search dùng relevance.
8. **Freshness:** publish/edit mục tiêu 60 giây ở tải demo; unpublish/delete bị chặn ngay sau commit bằng live DB. Có ví dụ page sau cũng không lộ tài liệu vừa unpublish.

Gemini có thể chọn cơ chế khác nếu chứng minh được cùng invariant với thay đổi nhỏ hơn, nhưng phải ghi **một quyết định cuối cùng**, tác động P03/P04/P05 và ví dụ nghiệm thu. Không để nhiều phương án chưa chốt rồi gắn FROZEN.

### Nghiệm thu tài liệu

- Script/read check xác nhận 103 IDs không đổi, 100 published/3 draft; không dùng lại con số 165 từ handoff cũ.
- Ví dụ page 1 G1 -> publish/edit -> G2 active -> page 2, expired context, unpublish giữa trang và semantic limited candidates có kết quả rõ.
- Một bảng ownership xác định P03 cần hỗ trợ generation retention/read interfaces; P05 thực hiện context API/storage; chưa có migration outbox/index được tạo.
- Sửa tài liệu "2 Alembic heads" thành chain/head thực tế; dùng head sau R04 khi bàn giao cuối. Không rewrite lịch sử review cũ.
- Handoff: `IA-R03-search-contract.md`; liệt kê những quyết định đã khóa và chỗ còn thuộc P04/P05.

## 8. R04 — Rate limit chung cho nhiều process

**Sửa:** IA-06. **Owner:** rate-limit backend/storage, auth integration, migration riêng nếu cần, tests concurrency. Migration này là hardening P01, không phải index schema P03.

Ưu tiên dùng PostgreSQL đang có làm shared store. Thread lock/dictionary hoặc multiprocessing.Manager trong một process tree không đủ cho worker/service độc lập. Không đóng finding chỉ bằng ghi "deploy 1 worker"; đó chỉ là mitigation chưa đáp ứng yêu cầu sửa đầy đủ.

### Công việc

1. Ghi policy trước: key theo IP/account/action, ngưỡng/window, successful login ảnh hưởng counters thế nào, 429/Retry-After, restart và DB/store unavailable. Không log raw password/token; hạn chế lưu email nguyên văn trong counters.
2. Chọn atomic admission/update trong transaction/row locking hoặc cơ chế PostgreSQL tương đương. Concurrent requests không thể cùng đọc remaining rồi vượt ngưỡng. Lock ordering nhất quán nếu cần nhiều key.
3. Counter của request bị từ chối/sai password không được mất vì transaction HTTP auth rollback. Không reset bộ đếm IP của các account khác khi một account login thành công.
4. Quy định failure khi store down: không âm thầm đổi sang limiter local không bảo đảm policy. Trả lỗi tạm thời rõ và không lộ connection data.
5. Bounded retention/cleanup cho entries hết window; thay đổi clock/window phải kiểm thử. Dùng DB clock hoặc cách tránh skew đã giải thích.
6. Migration forward-compatible với DB hiện tại và không reset users/sessions; giữ một Alembic head sau tích hợp. Cập nhật env defaults/test fixtures và tài liệu vận hành.

### Nghiệm thu

- Hai Python/web processes độc lập chia sẻ cùng store test: alternating và concurrent attempts vẫn giới hạn theo policy tổng, không theo từng process.
- Test boundary/window expiry, restart một worker, successful login, auth transaction rollback, unavailable store, khác IP/account/action; đơn vị test keys riêng, không đụng counters run khác.
- API abuse thật trả 429; không chỉ unit test hai instance cùng process. Security/backend regression pass.
- Handoff: `IA-R04-shared-rate-limit.md`, ghi migration head mới để R05/R06/P03 dùng đúng down_revision sau này.

## 9. R04.5 — Integration A checkpoint sau R02-R04

**Mục tiêu:** xác nhận remediation đã ghép đúng trên một branch, không chỉ đúng khi đọc từng handoff. Không bắt đầu P03 và không chạy destructive fixture trên DB chưa được R01 xác nhận.

1. Xác minh branch/HEAD/ancestry chứa R00, R01, R02, R03 và R04; đối chiếu changed files với handoff, tìm conflict resolution còn sót và import cycle.
2. Kiểm tra `alembic heads`, `alembic history` và SQL offline: phải có một head `20261101_rate_limit`; P03 sau này dùng head này làm `down_revision`.
3. Review ownership: manifest chỉ đăng ký database sau `CREATE DATABASE` thành công; DB tồn tại trước đó phải bị từ chối, không được coi là owned chỉ vì target URL hợp lệ. Kiểm tra `safe_reset` không chạy trên unowned DB.
4. Review mọi live PostgreSQL test call site chống lệch tên argument/signature. Cụ thể, `provision_test_database` phải được gọi bằng `requested_dbname` hoặc signature phải đổi nhất quán; không để live test chỉ fail khi PostgreSQL xuất hiện.
5. Phân biệt pure/SQLite/multiprocess với PostgreSQL live trong R02/R04 handoff. Không ghi PostgreSQL verified nếu môi trường live vẫn `BLOCKED_ENV`.
6. Chạy checks không cần PostgreSQL: pure safety, startup/bootstrap unit, pure rate-limit, compile và migration offline. Nếu có PostgreSQL owned thì chạy thêm lifecycle; nếu chưa, ghi `BLOCKED_ENV` và không dùng shared DB.
7. Kiểm tra R03 contract và prompt P03 khớp R04 head, UUIDv5 preservation và search-context TTL/lease/count semantics; chỉ sửa tài liệu stale, không mở rộng sang importer/index.

Tạo `docs/handoff/gemini/IA-R04.5-integration-checkpoint.md` với exact SHA, ancestry, migration head, changed-file audit, commands/results, PostgreSQL availability và lỗi đã sửa. Nếu còn lỗi ownership/signature/migration: `INTEGRATION BLOCKED`. Nếu static đạt nhưng thiếu PostgreSQL: `INTEGRATION STATIC PASS / LIVE DB BLOCKED`; chưa được tuyên bố Integration A PASS hay GO P03.

## 10. R05 — Artifact, fixtures, clean setup và CI

**Sửa:** IA-07; các gap P02/Integration A. **Owner:** browser fixtures/tests/capture scripts, requirements/constraints khi thật sự cần, CI, README/setup, evidence manifest.

### Artifact và test isolation

- Một artifact-root cấu hình được cho capture và pytest, cùng convention `<worktree-or-checkout>/<commit>/<run-id>/<suite>/...`. Default nằm trong checkout ignored output, không ghi `../screenshots/` hoặc `docs/verification/`.
- Run ID duy nhất gồm random suffix, không chỉ timestamp theo giây. Screenshot/trace/JUnit của workers/tests không trùng tên; chống path traversal nếu dùng test name/path làm filename.
- Áp dụng cho public/admin screenshots, failure hook, public capture và các capture helper còn hardcode. Giữ `--output-dir`/env behavior đã có hoặc ghi rõ thay đổi tương thích.
- Playwright context được start tracing trước hành động, stop/save khi fail trước đóng browser. Cố ý gây một lỗi kiểm tra để xác minh screenshot + trace mở được rồi bỏ lỗi chủ động; không để test fail này vào full suite.
- Browser fixture không tự động được rollback bởi backend `db_session`. Thiết kế isolation thật cho test server/session/data; test thay settings, roles, users, comments không làm test sau phụ thuộc thứ tự. Nếu reset DB giữa test, chỉ reset DB owned khi server/connections liên quan đã dừng.
- Chạy frontend hai lần và theo một thứ tự khác bằng node IDs/runner sẵn có, không thêm plugin chỉ để shuffle; kiểm tra data state giữa test nếu cần. Baseline ảnh tracked trước/sau run phải giữ nguyên, kể cả ảnh đã được P02 commit trước đây.

### Clean setup/CI

1. Venv mới không dùng system packages; pin/constraints được kiểm tra bằng install và `pip check`. Không cập nhật dependencies hàng loạt ngoài việc cần để tái lập.
2. Provision DB mới qua harness đã sửa, Alembic upgrade head thật. Không `Base.metadata.create_all` thay migration evidence.
3. Seed hai lần và assert count/IDs/source URLs/user uniqueness; test một bản chỉnh sửa cần bảo toàn không bị overwrite. Audit timestamp/log rows có thể tăng theo policy, không đòi toàn DB byte-for-byte giống nhau.
4. Bootstrap từ DB vừa migrate, rồi full backend/security suite và frontend suite trên cùng source SHA.
5. CI: Python/runtime chính xác, PG16 service/instance riêng, migrated/seeded DB targets theo guard mới, APP_ENV nhất quán P01, Chromium do Playwright cài, artifact paths mới và failure propagation không nuốt lỗi.
6. Workflow hiện chỉ nhận main/feature branches: cập nhật trigger phù hợp `codex/**` hoặc PR target/main và optional workflow_dispatch. Không gọi workflow đang tồn tại là "CI pass" nếu branch mới chưa có run.
7. README/env template ghi cùng tên biến với code, quyền/provision DB test, seed CLI cuối cùng, artifacts và command Linux/Windows. Sửa 162/165 claims theo dataset thực tế, không sửa fixture cho khớp báo cáo cũ.
8. Nếu runtime Docker/Linux chưa có, ghi đúng giới hạn. Không tự push/trigger remote workflow; chuẩn bị artifact local và ghi cần run CI sau hành động được user giao riêng.

Nghiệm thu: regression có evidence mới, output không đụng docs/verification, fail path có trace/screenshot thật, cùng SHA. Handoff: `IA-R05-clean-ci-artifacts.md`. IA-01 chỉ chuyển VERIFIED sau khi các tests nền tích hợp đạt; kết luận readiness cuối thuộc R06.

## 11. R06 — Review độc lập và khóa đầu vào P03

**Owner:** đọc source/diff/tests, thực thi kiểm tra cô lập và báo cáo mới; không tự sửa code để vừa là implementer vừa duyệt finding.

Đọc review gốc, tất cả IA-R00-R05, contract cuối, actual Git state và logs. Kiểm tra bằng source và các negative tests, không chỉ tin checklist implementer.

### Gates

| Gate | Bằng chứng tối thiểu | Quyết định |
| --- | --- | --- |
| G-A source integration | Một source SHA có P01/P02 và repairs, seed API không mất phía nào | Thiếu: NO-GO |
| G-B DB safety | Guard effective target + ownership + hai runs + sentinel | Fail/thiếu: NO-GO |
| G-C bootstrap/security | Identity negatives, actual startup, CLI trên PG mới, RBAC/CSRF | Fail/thiếu nền: NO-GO |
| G-D contract | ID preservation, generation/context/count/expiry được chốt | Mơ hồ ảnh hưởng schema: NO-GO |
| G-E reproducibility | Clean venv, online migration, seed asserts, full backend/browser với artifact an toàn | Thiếu bằng chứng trọng yếu: NO-GO |
| G-F rate limit | Hai process và concurrency đúng policy | Còn mở: non-blocker P03 nhưng không claim sửa đủ 7 findings/production-ready |
| G-G artifact | Hai runs tách biệt, tracked evidence không đổi, trace thật | Còn mở: có thể conditional nếu có regression evidence từ disposable checkout an toàn |
| G-H Linux/remote CI | CI run đúng SHA, hoặc clean Linux run có phạm vi rõ | Remote chưa chạy không tự thành application failure; ghi UNVERIFIED, xét mức đủ nền P03 |

Báo cáo mới: `docs/handoff/review/INTEGRATION-A-REVIEW-R2.md` hoặc timestamp nếu tên tồn tại. Mỗi IA có OPEN/FIXED/VERIFIED/DEFERRED, evidence và blocker flag. FIXED chỉ nghĩa code đã sửa; VERIFIED cần kiểm chứng phù hợp.

GO khi không còn blocker và đủ bằng chứng nền. GO WITH CONDITIONS chỉ cho phần còn lại không phải điều kiện phải làm trước P03. NO-GO nếu G-A đến G-E chưa đủ; không dùng conditional để che blocker. Sẵn sàng P03 không đồng nghĩa production deployable.

## 12. Handoff cuối và cách bắt đầu P03

- Ghi worktree, integration branch, **source SHA đã test**, migration head hiện tại, env/seed commands và contract version. Nếu commit cuối chỉ bổ sung report, ghi cả source SHA đã test và commit docs; không nhầm chúng.
- Không để P03 tự suy ra phải quay về main c4b19cf hoặc nhánh P01/P02 riêng.
- Nếu R04 thêm migration rate-limit, P03 lấy Alembic head đã kiểm chứng sau đó làm down_revision; không hardcode head cũ từ baseline.
- Giữ ID hiện hữu gồm UUIDv5; outbox/generation theo contract đã sửa; không viết BM25 hoặc public search API trong P03.
- Gửi lại reviewer khi có blocker mới. Không tự triển khai P03 chỉ vì hoàn tất R05 hoặc vì có hai handoff READY.

Prompt cho từng chat nằm tại [GEMINI-INTEGRATION-A-FIX-PROMPTS.md](F:/dpl13.10/WikiSearchEngine-github/docs/handoff/review/GEMINI-INTEGRATION-A-FIX-PROMPTS.md).
