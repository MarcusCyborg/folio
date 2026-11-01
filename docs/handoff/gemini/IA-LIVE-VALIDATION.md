# Integration A — PostgreSQL live validation và sửa test infrastructure

**Ngày:** 01/11/2026, Asia/Saigon  
**Vai trò:** execution; quyết định readiness P03 thuộc reviewer root.  
**Phạm vi:** dựng PostgreSQL portable cô lập, thực thi live gates, sửa tối thiểu lỗi infrastructure phát hiện. Không push, trigger remote CI, merge main, deploy hay triển khai P03.

## 1. Ref và kết quả chính

| Mục | Giá trị |
|---|---|
| Worktree | `F:/dpl13.10/WikiSearchEngine-ia-fix` |
| Branch | `codex/integration-a-remediation` |
| Source cuối | `e958998ede00c4feb2477a9470c3981de636a42a` |
| Commits local mới | `c5dc1efae6fa8080196c3118ef5fe2a8fe316ea0`, `af3757b21cb0af4bfff30dbbfea1dab56b778d8f`, `e958998ede00c4feb2477a9470c3981de636a42a` |
| Migration head online | `20261101_rate_limit`, một linear head, parent `20261031_click_unique` |
| PostgreSQL runtime | PostgreSQL 16.10, Windows x64 portable; server `127.0.0.1:55463`, cluster mới riêng |
| Runtime khi handoff | **STOPPED**. Reviewer root đã chạy `pg_ctl stop -m fast -w` thành công sau independent verification. |
| Working diff source cuối | Rỗng. Report R2 của lượt trước được bảo toàn; handoff này là file mới. |

Backend CI suite đạt **190 passed, 0 skipped**, browser đạt **15 passed, 0 skipped** ở cả thứ tự thường và đảo toàn bộ 15 node IDs; artifact suite riêng đạt **8 passed, 0 skipped**. Seed hai pass trên PostgreSQL mới xác nhận counts, 103 IDs, mapping `source_url -> Document.id` và preserved edits. Có failure-hook probe có chủ đích tạo screenshot/trace thật.

**Không claim đủ 7 findings đã đóng:** IA-06 vẫn OPEN ở concurrent login admission. Probe live 8 processes với threshold 2 nhận **8 HTTP 401, 0 HTTP 429**. Remote CI/Linux vẫn **UNVERIFIED**. Đây là handoff thực thi, không tự tuyên bố P03 GO.

## 2. Runtime và clean environment

Không dừng ở kết luận 5432 unavailable: tải binary PostgreSQL từ nguồn EDB được PostgreSQL phân phối cho Windows:

- URL: [postgresql-16.10-1-windows-x64-binaries.zip](https://get.enterprisedb.com/postgresql/postgresql-16.10-1-windows-x64-binaries.zip)
- ZIP bytes: `322530154`; SHA256 tính từ file tải về: `EBB3B6AF4FA69DEA9951B66855BC4D42DC04E56CCB9AA7024CE3C58BD89D6B0C`.
- Binary/cache ngoài Git: `F:/dpl13.10/folio-live-runtime/pgsql/`.
- Cluster mới: `F:/dpl13.10/folio-live-runtime/run_20261101/data/`.
- Marker ownership: [OWNER.json](F:/dpl13.10/folio-live-runtime/run_20261101/OWNER.json).
- `initdb`: UTF8, locale C, user `folio_live`; test-only trust auth trên loopback, `listen_addresses='127.0.0.1'`, port riêng `55463`. Không cài Windows service, không admin install, không đổi system configuration hoặc DB shared.
- Logs: [initdb.log](F:/dpl13.10/folio-live-runtime/run_20261101/initdb.log), [server.log](F:/dpl13.10/folio-live-runtime/run_20261101/server.log).

Đã tạo venv mới bằng Python 3.10.11 tại `F:/dpl13.10/folio-live-runtime/venv-clean`, không dùng venv review cũ làm clean-install evidence. `include-system-site-packages = false`; install `requirements-browser.txt -c constraints.txt` exit 0; `pip check` trả `No broken requirements found.` Không upgrade dependency hàng loạt.

Evidence: [clean-install.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/clean-install.log), [pip-check.txt](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/pip-check.txt), [pip-freeze.txt](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/pip-freeze.txt).

## 3. Lỗi tìm thấy và sửa tối thiểu

| Lỗi được phát hiện | Sửa cuối cùng / evidence |
|---|---|
| Manifest chỉ gắn database name, có thể nhận admin URL khác endpoint nhưng cùng tên | `owned_endpoints` gắn host/port. Reset/teardown yêu cầu endpoint đúng; server identity kiểm tra database, address và port trước mutation. Ownership không gộp tất cả loopback IP như collision guard. |
| Provision validate driver target sau CREATE DATABASE | Validate target/query overrides/ambient libpq trước CREATE; kiểm tra connected admin identity trước mutation. Pure negative tests chứng minh không gọi engine/CREATE cho `?dbname=folio`; mismatch server port/endpoint bị từ chối. |
| PostgreSQL `inet_server_addr()::text` thực tế trả `127.0.0.1/32` | Strip host mask trước endpoint comparison; live connection được kiểm chứng tại port 55463. |
| Fixture dùng tên DB cố định, teardown chỉ dispose; lỗi migrate/seed trước yield có thể orphan DB | Conftest sinh DB name per-run; helper provision register sau CREATE; toàn bộ reset/migrate/seed/yield được bọc `try/finally`, drop đúng DB owned. |
| Explicit `from tests.conftest import TestingSessionLocal` gây import conftest lần hai, tạo engine trỏ DB khác chưa provision | Thêm `tests/__init__.py` để pytest và explicit import dùng một module instance. Trước sửa full backend trả 503 dù test riêng pass; sau sửa full suite pass. |
| Sentinel/two-run test tạo table và insert qua transaction chưa commit; tên test/sentinel cố định dễ collide giữa suite processes | Dùng `engine.begin()` và tên unique cho lifecycle, worker, sentinel/unowned DB. Reviewer root chạy hai pytest processes thực sự overlap, mỗi process 4 pass, sentinel và teardown vẫn đúng. |
| Bootstrap PG fixture chỉ `set_main_option` URL, bị `alembic/env.py` overwrite; thiếu import `Session`; chưa tạo active sessions để chứng minh revoke | Dùng Alembic `-x db_url` contract; fixture `try/finally`; một engine được dispose. Tạo 2 active sessions trước rotate, assert sessions gone/old token invalid; negative subprocess cases so sánh snapshot user/session/audit trước và sau rejection. |
| Browser reset xóa subset dữ liệu và nuốt exception | Restore tất cả application tables theo thứ tự FK, seed lại; PG reset đòi ownership + connected identity. Đóng contexts, stop/drain Uvicorn trước reset, readiness polling sau start lại. Không nuốt cleanup failure. |
| Multi-process limiter test dùng SQLite file | Đổi fixture sang PostgreSQL mới owned, online migrations và seed, teardown riêng. Registration overflow test assert đúng HTTP 201 cho từng admission; không chấp nhận 500/409 để xanh. |
| CI seed assertions chạy SQLite riêng trong khi raw seed commands chạy PG | Thêm `scripts/verify_seed_idempotency.py`: provision PG mới owned, migrate online, seed hai pass, assert counts/IDs/source mapping/preserved document summary và setting, teardown. CI gọi script này. |
| Browser CRUD test click Publish ngay khi form skeleton có mặt nhưng async document load chưa điền field | Trace có Validation Error, không có PATCH request. Test đợi title/category/content đã được load trước click. Không đổi validation/expected behavior hay application UI code. |
| CI backend chưa cài Playwright nhưng chạy real trace tests; chạy trace tests chung process sau session browser gây nested sync API loop | Backend ignore duy nhất artifact module và browser job chạy module đó bằng **pytest process riêng** trước frontend process. Hai JUnit paths đều upload. Không skip/xfail hay chỉ reorder để che lỗi lifetime. |

Các file source được commit rõ ràng; không stage report R2, binary, cluster, logs, secrets hoặc screenshots. Acceptance matrix UI-07/OPS-02 được đồng bộ tới handoff này; review cũ được giữ nguyên.

## 4. Commands/results và mức bằng chứng

Thư mục evidence bền vững ngoài repo: `F:/dpl13.10/folio-live-runtime/run_20261101/evidence/`.

| Kiểm tra | Kết quả | SHA / phạm vi |
|---|---|---|
| Clean venv install + `pip check` | exit 0, không broken requirements | Clean Windows Python 3.10.11, constraints hiện tại |
| `pytest tests/safety tests/security tests/backend --ignore=tests/safety/test_artifact_isolation.py -q` | **190 passed, 0 skipped**, exit 0 | `af3757b`; toàn bộ backend/tests source byte-identical ở `e958998` (delta chỉ CI/docs). Suite có cả live PG và pure/SQLite/mock tests; không gọi tất cả 190 là PG-only. |
| Reviewer root independent cùng combined backend command | **190 passed, 0 skipped**, exit 0 | `af3757b`, scope backend source như trên |
| `pytest tests/frontend -q` | **15 passed, 0 skipped**, exit 0 | `e958998`, HTTP live server + PostgreSQL thật |
| Thu thập 15 node IDs rồi chạy toàn bộ theo thứ tự đảo | **15 passed, 0 skipped**, exit 0 | `e958998`; collect-only chỉ dùng lập thứ tự, evidence là lượt execute sau đó |
| Reviewer root independent frontend | **15 passed, 0 skipped**, exit 0 | `e958998` |
| `pytest --noconftest tests/safety/test_artifact_isolation.py -q` | **8 passed, 0 skipped**, exit 0 | `e958998`; Playwright Chromium thật, không DB |
| Hai pytest processes root chạy lifecycle + bootstrap đồng thời | **4 passed mỗi process, 0 skipped**, exit 0 | `c5dc1ef`; lifecycle/bootstrap source giữ nguyên ở source cuối |
| `python scripts/verify_seed_idempotency.py` | exit 0; `[5,100,3,6,123]`; 103 IDs và source mapping giữ nguyên, edits được preserve | `af3757b`; script byte-identical ở source cuối; fresh owned PostgreSQL |
| `alembic upgrade head`; `alembic current` | exit 0; online current `20261101_rate_limit` | `e958998`; DB `folio` chỉ nằm trong cluster mới owned |
| `compileall -q src scripts tests`; `git diff --check` | exit 0 | Source cuối |
| Intentional pytest frontend failure probe | **1 expected failure**, exit 1; hook xuất PNG + trace ZIP hợp lệ | `af3757b`; hook/fixture/backend source unchanged ở `e958998`; probe file tạm đã xóa, không stage |
| Synchronized 8-process HTTP login probe, threshold 2 | **8 HTTP 401, 0 HTTP 429** — race được tái hiện | `af3757b`; PG mới owned; không monkeypatch app/limiter |

Evidence chính:

- [live-validation-manifest.json](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/live-validation-manifest.json): exact SHA, source file SHA256, JUnit summary, artifact run paths.
- [ci-backend-final.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/ci-backend-final.log), [JUnit](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/ci-backend-final.xml).
- [frontend-normal.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/frontend-normal.log), [frontend-reverse.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/frontend-reverse.log), [normal JUnit](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/frontend-normal.xml), [reverse JUnit](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/frontend-reverse.xml).
- [artifact-final.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/artifact-final.log), [seed-final.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/seed-final.log), [migration-head-final.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/migration-head-final.log).
- Reviewer evidence: `root-ci-backend.*`, `root-lifecycle-a.*`, `root-lifecycle-b.*`, `root-frontend-final.*`, `root-artifact-audit.json` trong cùng thư mục.

Các logs fail trước sửa được giữ (`first-live`, `live-02`, `backend-03`, `frontend-final-a`, `ci-browser-a/b`); không biến chúng thành PASS. Một số lượt chẩn đoán chạy khi source còn đổi nên không lấy metadata HEAD ghi sau lệnh của các logs này làm chứng nhận exact source SHA. Các lượt final và independent review nêu trên có phạm vi SHA rõ ràng.

## 5. Artifacts, trace và teardown

Hai browser runs final dùng thư mục riêng dưới `.../artifacts/WikiSearchEngine-ia-fix/e958998/` với run IDs khác nhau. JUnit và logs cũng dùng tên riêng. **51 tracked PNG** trong `docs/verification` giữ byte-identical với baseline `6ea2de6`; không dùng lại claim 52 của handoff R05. `git diff -- docs/verification` rỗng.

Failure probe thật qua `pytest_runtest_makereport` có PNG **454894 bytes**, ZIP **483938 bytes**, ZIP integrity valid, có `trace.trace` và `trace.network`. Snapshot/network được capture trước fixture đóng context; không chỉ tạo thư mục traces. Probe file đã xóa khỏi workspace. Evidence: [failure-hook-final.log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/failure-hook-final.log), [trace-audit-final.json](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/trace-audit-final.json), [baseline-png-audit-final.json](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/baseline-png-audit-final.json).

Database inventory sau các runs chỉ còn `folio`, `postgres`, `template0`, `template1`; không còn owned test DB bị orphan. [database-inventory.json](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/database-inventory.json). Reviewer root xác nhận inventory và đã stop cluster riêng sau verification. Không process validation nào của execution agent còn chạy.

## 6. Gaps và điều kiện bàn giao reviewer

1. **IA-06 OPEN — concurrent login admission:** state chia sẻ, restart persistence và registration atomic admission đã chạy thật trên PG. Tuy nhiên login tách read-only precheck và ghi failure sau password verification. Probe đồng bộ 8 OS processes cho cả 8 vượt admission threshold 2. [login-admission-race.json](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/login-admission-race.json), [log](F:/dpl13.10/folio-live-runtime/run_20261101/evidence/login-admission-race.log); probe tái lập ở `F:/dpl13.10/folio-live-runtime/probe_login_admission.py`. Theo remediation plan đây là non-blocker schema P03, nhưng phải sửa và chứng minh trước claim hoàn tất IA-06/production abuse protection. Không ghi 7/7 VERIFIED.
2. **G-H UNVERIFIED:** chưa push/trigger remote CI, chưa clean Linux run. YAML đã được sửa theo local execution; không suy diễn GitHub Actions success. Local Windows suite không thay thế Linux/remote evidence.
3. **Browser test command contract:** artifact module dùng Playwright driver riêng, frontend giữ browser session fixture. Chạy như workflow bằng hai pytest processes; không gộp hai driver lifetimes trong cùng process sau frontend session đã khởi tạo. Không skip tests.
4. Trace chẩn đoán còn thấy font 404 và console cleanup `closeAllDropdowns is not defined` từ frontend có sẵn. Chưa sửa các vấn đề UI ngoài phạm vi live gate; không coi browser regression pass là audit sạch mọi console warning/P07 hoàn tất.

R06/R3 reviewer quyết định G-A..G-H dựa trên evidence mới; không bắt đầu P03 chỉ vì execution handoff đã xong. Nếu được reviewer chấp nhận, P03 kế thừa source/ref này, giữ contract v2.1.0 và 103 UUIDv5 fixture IDs, migration `down_revision="20261101_rate_limit"`. Không quay về baseline main hay nhánh P01/P02 riêng.

## 7. Tái lập runtime và verification an toàn

Các command sau dùng cluster đã có marker ownership, hiện đã dừng. Đọc marker trước start; không chạy `initdb` hoặc reset trên thư mục/DB có sẵn không thuộc run.

```powershell
Set-Location F:\dpl13.10\WikiSearchEngine-ia-fix
$pgBin = 'F:\dpl13.10\folio-live-runtime\pgsql\bin'
$pgRun = 'F:\dpl13.10\folio-live-runtime\run_20261101'
Get-Content -LiteralPath "$pgRun\OWNER.json"
& "$pgBin\pg_ctl.exe" -D "$pgRun\data" -l "$pgRun\server.log" -w start

$env:APP_ENV = 'test'
$env:APP_SECRET = 'test_secret_key_32bytes_minimum_for_tests_12345'
$env:DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/folio'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/folio_test'
$env:FOLIO_TEST_ADMIN_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/postgres'
$env:FOLIO_ARTIFACT_ROOT = 'F:\dpl13.10\folio-live-runtime\next-run-artifacts'
$py = 'F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe'

& $py scripts/verify_seed_idempotency.py
& $py -m pytest tests/safety tests/security tests/backend --ignore=tests/safety/test_artifact_isolation.py -q
& $py -m pytest --noconftest tests/safety/test_artifact_isolation.py -q
& $py -m pytest tests/frontend -q

# Sau khi test/server processes hoàn tất; giữ logs/evidence để review.
& "$pgBin\pg_ctl.exe" -D "$pgRun\data" -m fast -w stop
```

Wrapper giữ log/exit code cho mỗi command nằm tại `F:/dpl13.10/folio-live-runtime/run_validation.py`; reverse runner tại `F:/dpl13.10/folio-live-runtime/run_frontend_reverse.py`. Mọi DB destructive path đi qua provision/manifest của fresh run. Giữ baseline report/evidence cũ, không reset shared DB.
