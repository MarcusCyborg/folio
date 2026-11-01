# Gemini prompts cho Folio / WikiSearchEngine

Mỗi mục dưới đây dùng trong **một chat Gemini mới** có mở cùng repository. Các prompt đã thiết kế để chạy tuần tự hoặc song song bằng worktree.

## Workspace và baseline GitHub

- Workspace mới dành cho P00-P09: `F:/dpl13.10/WikiSearchEngine-github` hoặc worktree tạo từ checkout này. Không thực thi các prompt trên checkout cũ `F:/dpl13.10/WikiSearchEngine`.
- Remote: `https://github.com/MarcusCyborg/folio.git`, branch `main`. Baseline remote đã kiểm tra: `c4b19cffa676b4437e7346da2c410b198b04dc2c`; xác minh lại HEAD và đọc `docs/handoff/gemini/CLONE-REPORT.md` khi bắt đầu.
- GitHub đã viết lại lịch sử (force-update). So sánh cây file với local `ab0f5fe` cho thấy thay đổi tập trung vào screenshot: README, `.gitignore`, script capture và bỏ 8 ảnh tracked. `src/`, `tests/`, requirements và migrations không đổi ở hai commit này; chưa có bằng chứng Phase 2 mới.
- `scripts/capture_screenshots.py` hiện ghi ra `../screenshots/` theo thư mục cha của repo. Không chạy đồng thời từ nhiều clone/worktree vào cùng đích; các mốc P02/P07 phải thêm output directory cấu hình được và tách theo chat/run/commit.
- Clone không có `.env`, virtualenv, database local hoặc `data/` bị ignore. Không copy nguyên môi trường cũ; P00 chỉ kiểm tra mức sẵn có, P02 dựng môi trường sạch và DB test riêng. Giữ fixture portable có trong Git; corpus/model lớn xử lý sau theo manifest.
- Các kết quả 58 backend tests pass và Alembic head ở checkout cũ là bằng chứng lịch sử, chưa phải PASS của clone mới.
- `FOLIO-COMPLETION-PLAN.md` và prompt pack là tài liệu hướng dẫn. Chỉ thực thi đúng prompt người dùng chọn; không tự chạy P00 hay các mốc khác khi được giao clone/review.

Khi mở chat mới, copy phần prompt của mốc cần chạy. Mỗi prompt yêu cầu đọc quy tắc chung trong file này trước khi thực thi. Trường hợp chỉ đọc được một đoạn, dán thêm phần Workspace và Quy tắc chung vào chat.

## Thứ tự chạy

```text
Clone verified -> P00 -> (P01 || P02) -> Integration A -> P03 -> P04 -> P05 -> (P06 || P07) -> Integration B -> P08 -> P09
```

`||` chỉ an toàn khi mỗi chat dùng worktree/branch riêng. Nếu các chat dùng chung checkout, chạy tuần tự. Không cho hai chat cùng sửa migration, shared schema, `main.py`, `README.md` hoặc cùng một frontend file.

Sau mỗi cặp song song phải review và tích hợp cả hai branch vào một branch chung trước khi bắt đầu mốc phụ thuộc. Integration A chạy lại backend/auth/test setup; Integration B chạy lại API + browser + evaluation liên quan. Không coi hai handoff READY ở hai branch riêng là đã tích hợp. P01 sở hữu runtime/security tests; P02 sở hữu dependency/CI/common test fixtures/README setup. Thay đổi shared fixture/migration cần thống nhất trước khi sửa.

## Quy tắc chung cho mọi chat

- Trước khi sửa: đọc `git status --short`, `git diff`, `AGENTS.md` và handoff trước đó. Không `reset`, `checkout`, `clean`, xóa data, amend, force-push hoặc revert thay đổi của chat khác.
- Bạn không làm việc một mình trong repository. Nếu thấy thay đổi mới trong file mình sở hữu, đọc và tích hợp; nếu không tách được thì ghi blocker.
- Chỉ ghi PASS khi đã chạy lệnh trong chat hiện tại. Ghi command, environment, output tóm tắt và test gap.
- Không mock/fake success trong runtime; không commit secret, token, password, dump DB, model cache lớn hoặc credential.
- Không tự push, deploy public, đổi DNS hay xóa volume. Commit branch nếu workflow dùng Git; không merge thay người khác.
- Khi xong phải tạo handoff ở `docs/handoff/gemini/` với files changed, tests/results, migration/config impact, unresolved risks và dependency tiếp theo.
- Giữ FastAPI, SQLAlchemy/Alembic, PostgreSQL và vanilla JS; không thêm Redis/Celery/Kubernetes hay đổi framework nếu chưa có yêu cầu.
- Kiểm tra `git rev-parse --show-toplevel`, branch, HEAD và origin trước mỗi mốc; dừng nếu đang ở checkout cũ hoặc thiếu commit/handoff của mốc tiền nhiệm. Không chạy migration/test trên DB phát triển chỉ vì `.env.example` có địa chỉ mặc định.
- Nếu gặp Git dubious ownership, dùng `git -c safe.directory=<đúng workspace>` cho lệnh cần thiết; không đặt `safe.directory=*` và không sửa global Git config.
- Baseline thiếu dependency/browser/DB thì ghi NOT RUN hoặc BLOCKED_ENV, chuyển remediation môi trường cho P02; không cài vào Python global hoặc sao chép venv cũ.

---

## P00 — Baseline, acceptance matrix và search contract

Chạy đầu tiên; không triển khai feature lớn.

```text
Bạn là lead architect/QA của Folio / WikiSearchEngine. Thực hiện M0: xác nhận hiện trạng và tạo contract cho các chat sau.

Mở workspace mới hoặc worktree của `F:/dpl13.10/WikiSearchEngine-github`. Đọc phần Workspace, Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`, `FOLIO-COMPLETION-PLAN.md` và `docs/handoff/gemini/CLONE-REPORT.md`. Chỉ thực hiện P00.

Context cần kiểm tra lại bằng code/lệnh:
- Backend FastAPI/PostgreSQL/Alembic, route `/api/v1`.
- 58 backend tests pass là kết quả ở checkout cũ, không phải của clone mới; frontend E2E và clean install phải kiểm tra lại.
- Catalog hiện dùng SQL ILIKE; legacy `src/backend/search_service.py` dùng BM25/Chroma/embedding trên JSON/URL.
- `data/` bị ignore; corpus/index legacy có thể rất lớn.

Làm các việc sau:
1. Audit exact HEAD/remote/branch, status, migrations, dependencies, test paths, runtime entrypoints và các tài liệu cũ. Đối chiếu CLONE-REPORT để phân biệt thay đổi nội dung với lịch sử Git viết lại. Chạy test chỉ khi đã có môi trường và DB test riêng; thiếu thì ghi NOT RUN và giao P02 khắc phục, không kết luận ứng dụng fail.
2. Tạo `docs/acceptance-matrix.md`: Phase 1, Phase 2 core (tokenization, inverted index, BM25, evaluation), semantic/hybrid, UI và deploy. Mỗi dòng có requirement, source, test/evidence, status thật, owner và dependency.
3. Tạo `docs/search-contract.md`. Chốt Document ID Folio là canonical key; URL chỉ là source metadata; API `/api/v1/search`; query/filter/mode/pagination; engine_used/index_generation; draft/deleted behavior; stable ordering; search/click/view logging; fallback và backward compatibility.
4. Tạo `docs/handoff/gemini/P00-baseline.md` gồm commands/results, dirty files, blockers, shared-file ownership và thứ tự P01-P09.

Không sửa runtime trừ lỗi tài liệu rõ ràng. Không tuyên bố Phase 2 complete nếu chưa có implementation/evidence. Nếu thiếu rubric chính thức, ghi open question.
```

## P01 — Production config, security và admin bootstrap

Phụ thuộc P00; chạy song song P02 bằng worktree riêng.

```text
Bạn là backend security engineer. Thực hiện M1 sau khi đọc `docs/acceptance-matrix.md`, `docs/search-contract.md` và P00 handoff.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P01 trên clone mới/worktree của nó; không chạm checkout cũ.

Ownership: `src/backend/core/`, `src/backend/main.py`, auth/session/middleware liên quan, `src/backend/api/auth.py` nếu cần, script bootstrap admin, security/startup tests và `.env.example`. Không sửa search/UI/Docker.

Yêu cầu:
1. Gọi production validation trong startup/lifespan; fail fast nếu APP_ENV=production mà secret default/yếu, COOKIE_SECURE=false hoặc biến bắt buộc sai. Test boot thật, không chỉ gọi method.
2. Chuẩn hóa local/test/staging/prod, trusted proxy/origin/HTTPS và không mở wildcard credentialed CORS.
3. Thêm CLI tạo/rotate admin đầu tiên qua secret nhập ẩn hoặc environment secret; production không seed demo users/password và không log credential.
4. Audit login/register/session: session rotation/revoke, Secure/HttpOnly/SameSite, CSRF/Origin, login/register rate limit, disabled account và guest session.
5. Lỗi production không lộ stack trace/connection string/token; thêm headers tương thích assets thật.
6. Viết tests cho insecure config, cookie flags, bootstrap admin, login abuse, revoke và secret redaction.

Chạy backend security tests và full backend suite. Tạo `docs/handoff/gemini/P01-production-security.md` với env matrix, test results, migration/config impact và phần chưa harden. Không dùng default secret để lách validator.
```

## P02 — Clean setup, dependencies, test isolation và CI

Phụ thuộc P00; chạy song song P01 bằng worktree riêng.

```text
Bạn là build/release engineer. Thực hiện M2 cho Folio sau khi đọc P00.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P02 trên clone mới/worktree của nó; không chạm checkout cũ.

Ownership: `requirements*.txt`, lock/constraints nếu cần, `tests/conftest.py`, fixture/setup scripts, frontend server fixtures, `.github/workflows/` và clean-setup docs. Không sở hữu Docker production.

Yêu cầu:
1. Venv sạch không dùng system-site-packages; pin/constraint phiên bản đã kiểm chứng; tách core/dev/browser/legacy ML.
2. Tự tạo test DB, chạy `alembic upgrade head`, seed fixture và teardown an toàn. Guard TEST_DATABASE_URL phải kiểm tra DB đích, không chỉ tìm chữ “test”.
3. Tests không phụ thuộc DB seed thủ công hoặc thứ tự; giữ isolation cho server thread/session.
4. CI cài Chromium bằng Playwright; system Chrome là tùy chọn. Dùng readiness polling thay vì sleep cố định; lưu JUnit/trace/screenshot khi fail.
5. Cập nhật clean setup README và CI cho migration, seed idempotency, backend/frontend tests. Script public capture hiện ghi `../screenshots/`: thêm cấu hình output path riêng cho từng run/worktree để không ghi đè ảnh của chat khác, và lưu artifact đúng đường dẫn mới trong CI/docs. Không ghi PASS nếu chỉ chạy env cũ.

Chạy clean install hoặc CI container nếu có thể; `alembic upgrade head`; seed 2 lần; backend và frontend suites. Ghi blocker môi trường thật. Tạo `docs/handoff/gemini/P02-clean-setup-ci.md`.
```

## P03 — Document import, index schema và lifecycle worker

Phụ thuộc P01/P02; chạy trước P04/P05.

```text
Bạn là data/index platform engineer. Thực hiện M3 để PostgreSQL Folio là source of truth có index lifecycle an toàn.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P03 sau khi P01/P02 đã được tích hợp và kiểm tra chung; không chỉ dựa vào hai branch riêng.
Worktree bắt buộc: `F:/dpl13.10/WikiSearchEngine-ia-fix`
Branch bắt buộc: `codex/integration-a-remediation`

Đọc P00-P02 handoff, IA-R00-R04.5 handoff, `docs/search-contract.md` (v2.1.0), Document/Category/Tag/InteractionLog models, Alembic heads, content service và legacy loader.

Đầu vào đã chốt từ Search Contract v2.1.0 (IA-R03):
1. Canonical Document ID: UUID Folio hiện hữu gồm v5 (103/103 tài liệu trong `fixtures/folio/documents.jsonl`, SHA256: 5413a1f6...) và v4 (default tạo mới). Importer tuyệt đối không re-mint ID hoặc enforce UUIDv4; giữ nguyên 103 IDs và mapping source_url -> Document.id. Bỏ claims 165/162 cũ.
2. Generation Retention & Lease Contract: P03 worker lifecycle khi atomic swap G1 -> G2 phải đặt G1 vào draining; background GC worker KHÔNG ĐƯỢC xóa/purge posting lists/files của generation khi còn active search context lease chưa hết hạn (TTL 15 phút, configurable `SEARCH_CONTEXT_TTL_MINUTES=15`).
3. Alembic Down Revision: Bắt buộc dùng single linear head `20261101_rate_limit` làm down_revision (từ Task R04). Tuyệt đối không dùng 20261031_click_unique hay tạo multi-head.
4. Phân công: P03 sở hữu outbox/index schema, importer, generation retention/lease check và reader interface; không làm BM25 scoring (P04) và không làm Search API / Search Context storage (P05).

Ownership: migration/model/service mới cho index generation, content revision và outbox jobs; package `src/backend/search_index/`; importer/validator/CLI; lifecycle tests. Hạn chế sửa public API; P05 sở hữu.

Làm:
1. Import JSON/JSONL cũ theo source URL -> Folio Document ID; dry-run, duplicate/conflict report, attribution/license, idempotent và không overwrite user edits.
2. Outbox/index job có document_id, revision/hash, operation, state, attempts, timestamps, error; tạo cùng transaction với create/edit/publish/unpublish/delete và taxonomy ảnh hưởng search.
3. Generation mới được build/verify rồi mới swap active; rebuild lỗi giữ generation cũ; cập nhật phát sinh trong lúc rebuild không mất.
4. Worker claim/retry/backoff/idempotency/stale-revision protection/resume sau crash; không tải model trong request path.
5. CLI tương đương `import-corpus --dry-run`, `build-index`, `verify-index`, `index-status`; document unpublished/deleted bị loại khỏi live response ngay cả khi index lag.
6. Tests: duplicate/out-of-order job, crash/restart, retry failure, failed rebuild, concurrent rebuild/write, draft/deleted protection.

Không triển khai BM25 scoring; P04 sở hữu. Tạo `docs/handoff/gemini/P03-index-lifecycle.md` gồm schema/sequence, migrations, commands/results và contract cho P04.
```

## P04 — Tokenizer, inverted index và BM25

Phụ thuộc P03; chạy tuần tự.

```text
Bạn là information retrieval engineer. Thực hiện M4 trên Folio Document ID/index contract, không nối runtime mới trực tiếp vào JSON/URL legacy.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P04 trên clone mới/worktree có commit P03 đã nghiệm thu.

Đọc P00/P03 handoff, `src/backend/search_service.py`, `src/backend/utils/bm25_kw_search.py` và scoring legacy để tham khảo.

Ownership: package `src/backend/search/` cho analyzer, posting lists, reader/builder, BM25 và optional TF-IDF baseline; unit/property/reference tests; chỉ sửa P03 adapter nếu contract mismatch.

Yêu cầu:
1. Analyzer version ghi rõ Unicode normalization, lowercase, token boundary, punctuation, numbers, stopwords, repeated terms, empty query và long text. Query/document dùng cùng version.
2. Inverted index lưu term frequency, document frequency, document length và corpus stats; query không scan toàn bộ documents.
3. Okapi BM25 với k1/b cấu hình; công thức trong docstring/docs. Title boost nếu có phải tách riêng và ghi công thức; không gọi BM25F nếu chưa field-weighted.
4. Filters publication/category/tag/date áp dụng đúng trước/đồng thời candidate scoring; stable tie-break bằng document ID; xử lý unknown term, empty corpus, update/delete, generation mismatch.
5. Interface cho P05 nhận query+filters+generation và trả IDs/scores/ranks/stats, không trả full body.
6. Ví dụ tính tay và test so sánh index với brute-force reference trên fixture nhỏ.

Không tune test set, không download NLTK ở import, không phụ thuộc ML. Chạy unit/reference/benchmark và full backend regression. Tạo `docs/handoff/gemini/P04-bm25.md`.
```

## P05 — Search API, semantic/hybrid adapter và interaction logging

Phụ thuộc P03/P04; chạy trước P06/P07.

```text
Bạn là search integration/backend engineer. Thực hiện M5 theo `docs/search-contract.md`.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P05 trên clone mới/worktree có P03/P04 đã nghiệm thu.

Ownership: search route/schema/service, semantic/Chroma adapter, search/click server logic và tests; router registration trong `main.py` tối thiểu. P07 sở hữu UI.

Làm:
1. Thêm `/api/v1/search`: query, filters, mode (`bm25`, `semantic`, `hybrid`), page/page_size hoặc cursor, result summaries/snippets, `engine_requested`, `engine_used`, `index_generation`, `search_event_id`, latency và degraded state.
2. Check live publication/deleted trước response; không lộ draft/deleted qua stale index/page sau.
3. Search event lưu đúng result Document IDs. Click kiểm tra membership server-side, actor/session, public doc và request-key idempotency; refresh detail không tự log click.
4. Map vector chunks về Document ID+revision và deduplicate. Nếu model/vector unavailable, BM25 fallback phải khai báo engine/reason; không giả semantic success.
5. Nếu dùng RRF legacy, đưa vào interface mới, pin model/index version và config weights; URL/JSON không còn là source runtime.
6. Giữ browse API tương thích; legacy `/search` vẫn có feature flag và 503 rõ khi disabled. Bảo vệ query dài/abuse/timeout.
7. Tests API/DB: filters, pagination, no result, stale index, fallback, membership, concurrent duplicate click, payload mismatch và refresh behavior.

Chạy search tests và full backend suite. Tạo `docs/handoff/gemini/P05-search-api.md` với OpenAPI examples, fallback matrix, migration/config impact và latency/index lag thật.
```

## P06 — Retrieval evaluation, qrels và performance

Phụ thuộc P05; có thể song song P07; không sửa production algorithm.

```text
Bạn là IR evaluation scientist. Thực hiện M6 bằng CLI tái lập được, không chép số cũ từ notebook.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P06 trên clone mới/worktree có commit P05 đã nghiệm thu. Không dùng chung DB hoặc output artifacts với chat P07.

Đọc P03-P05 handoff, `evaluate/evaluate_module5.ipynb`, `evaluate/eval_results.json` và corpus manifest. Kết quả cũ 20 query/P@10 0.575/MAP 0.644126 chỉ là lịch sử cần kiểm tra.

Ownership: `evaluate/run_eval.py`, versioned queries/qrels/corpus manifest bằng Document ID, metrics/report/tests.

Yêu cầu:
1. Snapshot corpus/qrels, validate ID tồn tại/duplicate/coverage; query gồm exact title, multi-term, natural, ambiguous và negative; tách tuning/test nếu tune.
2. So sánh cùng corpus/query/filter/top-k: ILIKE baseline, TF-IDF nếu có, BM25, semantic, hybrid; ghi engine thực dùng.
3. Tính P@5/P@10, Recall@10, MAP@10, MRR@10, nDCG@10; báo riêng negative/timeout/error.
4. Đo p50/p95 cold/warm, build time, index size, RAM, concurrency và engine fallback. Không biến mục tiêu đề xuất thành kết quả.
5. Report ghi commit, manifest, analyzer/index/model version, config và command rerun. Chọn default dựa quality+latency; hybrid không tự thành default nếu không thắng rõ.

Chạy evaluation thật trên corpus có sẵn; nếu thiếu legacy model/corpus lớn, chạy Folio demo và ghi giới hạn. Tạo `docs/handoff/gemini/P06-evaluation.md` cùng artifacts.
```

## P07 — Frontend search, responsive, accessibility và remediation

Phụ thuộc P05; có thể song song P06.

```text
Bạn là frontend/product QA engineer. Thực hiện M7 trên vanilla JS/CSS hiện có, giữ identity Folio và API contract mới.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P07 trên clone mới/worktree có commit P05 đã nghiệm thu. Dùng DB và output artifacts riêng với chat P06.

Ownership: `src/frontend/`, Playwright tests và evidence. Chỉ sửa backend khi cần các finding F1/F2/F3/F5/F6 và có test; không sửa index/search algorithm/deploy.

Làm:
1. Nối library search với `/api/v1/search`; giữ query/mode/filters/sort/page trong URL/back/forward/refresh. Browse không query giữ behavior cũ.
2. Hiển thị ranking/snippet an toàn, loading/empty/error/retry/timeout/pagination và degraded engine rõ ràng. Không inject raw HTML/URL attributes.
3. Search -> result -> detail -> back log click một lần; reload detail không log click mới.
4. Responsive 360/390/768/1280/1440/1920: filter mobile, sidebar/drawer, table overflow có chủ đích, editor/keyboard viewport và long content/media/math/table.
5. Keyboard/focus/labels/error association/dialog restore/contrast WCAG AA/reduced motion cho luồng chính.
6. Audit/fix review findings còn tồn tại: preview Markdown qua sanitizer backend/maintained parser; dirty guard cả sidebar/header/history; Save Draft đổi status hoặc đổi nhãn đúng; `date_to=9999-12-31` không 500; click không chạy do route reload.
7. Chụp evidence riêng theo chat/run/commit; script public capture mặc định đang ghi ngoài repository ở `../screenshots/`. Dùng cấu hình output do P02 chuẩn bị, không tái thêm 8 ảnh GitHub đã bỏ vào `docs/screenshots/`, không ghi đè ảnh ngoài repo có sẵn; ghi đúng đường dẫn, route/viewport/dataset/commit.

Chạy targeted rồi full frontend tests, console/network audit và backend regression nếu sửa backend. Tạo `docs/handoff/gemini/P07-frontend-qa.md`.
```

## P08 — Docker, staging, HTTPS, backup/restore và operations

Phụ thuộc P01/P02/P05; chưa deploy public.

```text
Bạn là deployment/SRE engineer. Thực hiện M8: chuẩn bị staging/production-like artifact, không push, đổi DNS hay xóa volume.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P08 trên branch tích hợp P01-P07; clone mới không có `.env`, `data/` hay model cache, phải kiểm chứng bootstrap như một máy mới.

Ownership: Dockerfile, `.dockerignore`, compose dev/prod/staging, Caddy/reverse proxy, entrypoint/migration/worker scripts, health/readiness, backup/restore/rollback runbook.

Yêu cầu:
1. Image reproducible, non-root, secrets runtime-only; web/worker/PostgreSQL và Chroma profile nếu semantic. DB/index chỉ mở nội bộ.
2. Migration chạy một lần trước rollout; production admin bootstrap riêng; seed demo chỉ staging/demo.
3. Persist DB/media/index; ghi rõ index rebuild từ DB, model/index checksum/version và generation mismatch.
4. Liveness/readiness phân biệt DB down, worker lag, semantic degraded và app ready. Logs có request ID/latency/index lag/failed jobs, không session/token.
5. HTTPS config với domain placeholder, trusted proxy và headers tương thích assets; không hardcode secret/domain.
6. Backup PostgreSQL + config/model/index metadata; restore DB mới, migrate, recover/rebuild index và chạy health/search smoke; đo thời gian thật.
7. Rollback app image/migration compatibility; không dùng destructive schema rollback làm mặc định.
8. Chạy staging từ image/checkout sạch, restart/recreate, login/search/admin/worker/index và kiểm tra không mất dữ liệu.

Thiếu hosting/domain thì chứng minh local Linux/container staging và ghi phần chưa verify. Tạo `docs/handoff/gemini/P08-deployment-ops.md`.
```

## P09 — Independent final QA và release candidate

Chạy cuối cùng; không bù feature lớn.

```text
Bạn là independent release reviewer. Đọc acceptance matrix, search contract, mọi P00-P08 handoff, git diff/log và reports. Không tin claim PASS nếu không có command/output trong commit hiện tại.

Đọc phần Workspace và Quy tắc chung trong `GEMINI-EXECUTION-PROMPTS.md`. Chỉ thực hiện P09 trên branch tích hợp cuối cùng, ghi exact HEAD và đối chiếu CLONE-REPORT; không đánh giá checkout cũ hoặc branch mới chỉ chứa một phần công việc.

Kiểm tra release gates:
G1 Phase 1: clean setup, migration/seed, 5 roles, auth/CSRF/RBAC, CRUD/moderation/analytics, production validation/admin bootstrap.
G2 Phase 2 core: Folio Document ID source, inverted index, analyzer version, BM25 formula/tests, CRUD/index lifecycle, search API/UI/logging, reproducible evaluation.
G3 advanced: semantic/hybrid mapping, model/index readiness/version, declared fallback.
G4 UI: desktop/mobile/keyboard/contrast, loading/empty/error/long content, dirty guard, sanitizer, console/network.
G5 deploy: containers, HTTPS, persistence, health, restart, backup/restore, rollback.
G6 delivery: README/runbook/demo/checklist cùng commit, không stale claims.

Chạy backend/frontend tests, migration/seed/import/index verify, evaluation và staging smoke/restore. Tạo:
1. `docs/release/RELEASE-CHECKLIST.md` với PASS/FAIL/BLOCKED, command, timestamp, commit, evidence path, owner.
2. `docs/release/RELEASE-NOTES.md` với behavior, config/breaking changes, engine default/fallback, known limits và rollback.
3. `docs/handoff/gemini/P09-final-qa.md` với findings P0/P1/P2/P3 và residual risks.

Không tag/push/deploy public khi gate còn FAIL/BLOCKED. Kết luận rõ: Phase 1 đạt chưa; Phase 2 core đạt chưa; semantic/hybrid bắt buộc hay optional; staging deployable chưa; production còn điều kiện gì.
```

## Prompt reviewer tùy chọn

```text
Bạn là reviewer độc lập cho mốc [MỐC]. Chỉ review, không sửa code, không reset/revert.

Đọc handoff, diff/commit, contract và tests. Chạy checks read-only phù hợp. Tìm: scope/ownership sai, migration/API break, test giả hoặc thiếu failure/concurrency, PASS không có evidence, secret/data dump, fake fallback, request-path download, destructive commands và xung đột shared files.

Trả findings theo P0/P1/P2/P3, có path:line, impact, reproduction và recommendation. Nếu không có finding, ghi residual risks/test gaps. Không merge/push/deploy.
```

## Bảng bàn giao

| Chat | Handoff | Chat tiếp theo |
|---|---|---|
| P00 | `P00-baseline.md`, acceptance matrix, search contract | P01-P09 |
| P01 | `P01-production-security.md` | P02, P08, P09 |
| P02 | `P02-clean-setup-ci.md` | P03-P09 |
| P03 | `P03-index-lifecycle.md` | P04-P06, P08-P09 |
| P04 | `P04-bm25.md` | P05-P06, P09 |
| P05 | `P05-search-api.md` | P06-P09 |
| P06 | `P06-evaluation.md` | P09 |
| P07 | `P07-frontend-qa.md` | P09 |
| P08 | `P08-deployment-ops.md` | P09 |
| P09 | `P09-final-qa.md`, release checklist/notes | Người dùng quyết định release |

Nếu có subagent, chỉ giao read-only audit, test matrix hoặc benchmark độc lập; agent chính phải review kết quả trước khi áp dụng và không cho subagent sửa shared files.
