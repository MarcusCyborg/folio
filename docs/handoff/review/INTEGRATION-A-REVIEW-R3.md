# Integration A — R06 sau PostgreSQL live validation

Ngày: 01/11/2026 (Asia/Saigon). Reviewer: Codex root; implementation/validation: subagent `gpt-6.1-sol`.

**Verdict: GO WITH CONDITIONS cho P03.** Các gate bắt buộc G-A đến G-E đã có bằng chứng trên môi trường local Windows sạch với PostgreSQL 16.10 thật. Không còn blocker môi trường của R2. IA-06 còn lỗi concurrent login; Linux/remote CI chưa được kiểm chứng. Hai mục này không phải điều kiện phải hoàn tất trước P03 theo mục 11 remediation plan, nhưng không được coi dự án đã production-ready hoặc đã đóng cả bảy finding.

Báo cáo này bổ sung lịch sử; không thay đổi kết luận hoặc nội dung của review gốc/R2 tại thời điểm các review đó được viết. Chưa triển khai P03, chưa push, merge main hay deploy.

## 1. Findings còn mở

### [P1] IA-06: concurrent login vượt ngưỡng thất bại

`src/backend/api/auth.py:175` và `:180` đọc hạn mức trước xác thực; `:205` ghi thất bại trong giao dịch khác. `src/backend/core/rate_limit.py:209` không reserve admission. Row lock lúc ghi counter không ngăn nhiều request đã cùng vượt qua bước đọc.

Probe trên PostgreSQL owned, source `af3757b`, cấu hình ngưỡng 2: tám OS processes gửi HTTP login sai đồng thời đều nhận 401, không request nào nhận 429. Đây là lỗi behavior được tái hiện, không còn chỉ là thiếu evidence. Source auth/limiter không đổi trong commit cuối.

- Evidence: `F:/dpl13.10/folio-live-runtime/run_20261101/evidence/login-admission-race.json` và `.log`.
- Owner tiếp theo: R04; cần atomic admission/reservation cho login, giữ tính độc lập với auth rollback và policy target/IP, bổ sung concurrent HTTP regression.
- **Không chặn P03 theo G-F**, phải giải quyết trước nghiệm thu brute-force protection/production nhiều worker. Các bài registration admission, persisted counter và restart trên PG pass không đóng finding login này.

### [P2] G-H: Linux/remote CI chưa thực thi

Đã sửa workflow để chạy assertions seed trên PG và tách hai tiến trình pytest cho artifact/browser. Chạy tương đương trên Windows là bằng chứng local; không xác nhận GitHub Actions/Linux đã pass. Không push/dispatch remote trong đợt này.

- Owner tiếp theo: R05/CI; chạy workflow đúng source ref khi chuyển sang nghiệm thu Linux/remote.
- **Không chặn P03** vì các gate nền đã có live local evidence. Không dùng báo cáo này làm chứng nhận deploy Linux.

## 2. Source và môi trường

| Mục | Giá trị |
| --- | --- |
| Worktree | `F:/dpl13.10/WikiSearchEngine-ia-fix` |
| Branch | `codex/integration-a-remediation` |
| Source bàn giao P03 | `e958998ede00c4feb2477a9470c3981de636a42a` |
| Handoff docs commit | `bb3751c630f5fd6957d161474769b63be3b7ddaf` — chỉ thêm `IA-LIVE-VALIDATION.md` |
| Các commit sửa | `c5dc1ef` hạ tầng PG/guard; `af3757b` CI/editor readiness/seed mapping; `e958998` tách lifetime Playwright và cập nhật acceptance matrix |
| Alembic head | `20261101_rate_limit` — một head |
| Contract | `docs/search-contract.md` v2.1.0; preserve UUIDv4/v5 và 103 ID fixture |
| Runtime | PostgreSQL 16.10 portable, cluster mới tại `F:/dpl13.10/folio-live-runtime/run_20261101/data`, loopback `127.0.0.1:55463` |
| Venv | `F:/dpl13.10/folio-live-runtime/venv-clean`, Python 3.10.11, `include-system-site-packages=false`, constraints install và `pip check` pass |
| Working changes | Source sạch khi khóa `e958998`; báo cáo R2 có sẵn được giữ nguyên. Báo cáo/handoff mới là docs, không phải source chưa test. |

Backend/seed/failure-hook được kiểm chứng ở `af3757b`; diff `af3757b..e958998` chỉ là `.github/workflows/ci.yml` và `docs/acceptance-matrix.md`, không đổi application/tests/scripts. Root đã kiểm tra diff này. Frontend và artifact command cuối chạy trực tiếp trên `e958998`.

## 3. Những sửa đổi đã review

- Guard validate effective target trước CREATE; manifest ràng buộc endpoint; reset/teardown kiểm tra connected database và server trước mutation.
- Fixture tạo DB riêng mỗi run và cleanup bằng `finally`. Thêm `tests/__init__.py` để pytest và import `tests.conftest` dùng cùng module, tránh hai engine khiến login trả 503.
- Browser dừng/drain server trước reset dữ liệu, xác minh ownership, không nuốt lỗi cleanup; reset đủ bảng rồi seed baseline.
- Sửa migration target của bootstrap fixture bằng Alembic x-argument; kiểm tra CLI negative snapshots và revoke session thực trên PG. Sửa transaction bị rollback trong lifecycle test và tên DB cố định gây collision.
- Multi-process limiter suite dùng fresh migrated PostgreSQL thay SQLite. Giữ nguyên finding concurrent login chưa được sửa.
- Script `scripts/verify_seed_idempotency.py` assert counts, 103 IDs, source URL mapping và bảo toàn edits qua hai lần seed trên PG owned.
- CI chuyển artifact tests cần Playwright sang browser job; dùng hai pytest processes để không lồng runtime Sync API. Browser CRUD đợi editor tải dữ liệu trước Publish, không bỏ validation.

## 4. Evidence độc lập và kết quả cuối

Evidence root: `F:/dpl13.10/folio-live-runtime/run_20261101/evidence/`. Mỗi lệnh test có log/JSON; các suite có JUnit XML. Logs trước sửa bị fail được giữ để đối chiếu, không cộng vào số PASS cuối.

| Check | Người chạy / source | Kết quả |
| --- | --- | --- |
| Hai processes lifecycle + bootstrap CLI đồng thời, `--noconftest` | Root / `c5dc1ef` | `root-lifecycle-a` và `root-lifecycle-b`: mỗi run **4 passed**, không skip; sentinel/owned teardown/CLI negatives/revoke thật |
| Safety + security + backend theo CI, loại artifact sang job riêng | Root / `af3757b` | `root-ci-backend`: **190 passed, 0 skipped**, exit 0; 129.88s pytest |
| Cùng nhóm CI backend | Subagent / `af3757b` | `ci-backend-final`: **190 passed, 0 skipped** |
| Migration + two-pass seed assertions | Root / `af3757b` | `root-seed-final`: exit 0; 5 users, 100 published, 3 drafts, 6 categories, 123 tags; 103 IDs/mapping và edits giữ nguyên |
| Frontend PostgreSQL + Chromium | Root / `e958998` | `root-frontend-final`: **15 passed, 0 skipped**, 93.95s pytest |
| Frontend thứ tự thường và đảo ngược toàn bộ node IDs | Subagent / `e958998` | Hai run riêng: **15 passed/run**, không skip |
| Artifact tests trong process riêng | Subagent / `e958998` | `artifact-final`: **8 passed** |
| Real pytest failure hook | Subagent / `af3757b`; root đọc artifacts | `failure-hook-final`: exit 1 có chủ ý; PNG 454,894 bytes và ZIP 483,938 bytes hợp lệ, có network/trace. Probe đã bỏ khỏi source. |
| Baseline images | Root / `e958998` | `root-artifact-audit.json`: **51/51 tracked PNG** byte-identical với `6ea2de6`. Không dùng số 52 trong handoff cũ. |
| Dependencies / compile / migration head | Root / `e958998` | `pip check`, compileall, Alembic heads và diff check pass |

190 tests gồm pure/mock/SQLite/subprocess cùng các test PG; không gọi toàn bộ 190 là PostgreSQL tests. PG lifecycle, bootstrap CLI, backend/API, multi-process shared-store và frontend được thực thi với PostgreSQL thật. Không dùng offline SQL hoặc collect-only thay bằng chứng này.

Giới hạn ngoài gate nền: handoff ghi nhận font 404 và console cleanup `closeAllDropdowns is not defined` từ frontend hiện có. Chưa sửa hoặc nghiệm thu riêng các mục UI này; browser tests pass không có nghĩa console/UI audit hoàn tất. Theo dõi ở P07.

Root xác nhận cuối cùng server chỉ còn `folio`, `postgres`, `template0`, `template1`; không còn DB test orphan. Root đã dừng đúng cluster owned bằng `pg_ctl -D .../data stop -m fast -w`, exit 0. Giữ runtime/data/log ngoài Git để có thể tái lập; không cài service hệ thống.

## 5. Gates và trạng thái IA

| Gate | Kết luận |
| --- | --- |
| G-A source integration | PASS: một ref chứa P01/P02 và remediation; source cuối được review và regression |
| G-B safety | PASS local PG: effective guard/endpoint, ownership, hai processes, sentinel và teardown |
| G-C bootstrap/security | PASS local: CLI trên PG mới, negatives/revoke; startup subprocess và backend RBAC/CSRF |
| G-D contract | PASS static: ID/generation/context TTL/lease/count đã chốt, chưa yêu cầu implementation P03/P05 |
| G-E reproducibility | PASS local Windows: clean venv, migration/seed, backend/browser, artifact evidence |
| G-F rate limit | PARTIAL / OPEN: PG shared-store tests pass; concurrent login bug đã reproduce, non-blocker P03 |
| G-G artifacts | PASS local: nhiều run tách biệt, browser đổi thứ tự, baseline bất biến, real failure trace |
| G-H Linux/remote | UNVERIFIED, non-blocker P03 với evidence local hiện tại |

IA-01, IA-02, IA-03 và IA-07: VERIFIED trong phạm vi local nêu trên. IA-04/IA-05: VERIFIED STATIC ở mức contract. IA-06: PARTIAL/OPEN, giao R04; không đánh dấu cả bảy finding đã đóng.

## 6. Bàn giao P03

Có thể bắt đầu P03 từ `e958998ede00c4feb2477a9470c3981de636a42a` hoặc descendant chỉ bổ sung docs của nó, tại worktree/branch đã ghi. Migration mới phải dùng `down_revision = "20261101_rate_limit"`. Đọc contract v2.1.0, giữ canonical IDs/source mappings, hỗ trợ generation retention/search-context lease. Chỉ làm importer/schema/outbox/lifecycle worker theo P03; chưa kéo BM25 scoring hoặc public search API từ P04/P05 vào đây.

Hướng dẫn start/stop portable PG, env và command tái lập nằm trong [IA-LIVE-VALIDATION.md](../gemini/IA-LIVE-VALIDATION.md). Đừng dùng command mặc định trỏ tới DB có sẵn của người dùng. IA-06 và Linux CI được theo dõi song song với P03, phải đóng trước các mốc nghiệm thu tương ứng.
