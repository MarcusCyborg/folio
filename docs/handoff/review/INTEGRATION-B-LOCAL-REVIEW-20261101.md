# Integration B: independent local review and source handoff

Date: 2026-11-01 (Asia/Saigon).

**Source integration: COMPLETE. Functional acceptance: NO-GO pending the
search lifecycle/filter fixes below. No push or deployment performed.**

## Canonical workspace and Git evidence

- Continue in `F:/dpl13.10/WikiSearchEngine-github`, branch `codex/integration-b`.
- Integrated application source SHA: `ba4f628cbdc5bc1214f0e6d26d4120eed0747b9d`.
- First parent, P07 plus P03-P05 and Integration A:
  `f19891f70a582b2f43dcf6f160be59217451c2d2`.
- Second parent, P06 evaluation:
  `4aaa6cc6abe42914d10d0c8de82025653fa253f3`.
- Both parent ancestry checks return exit 0. P06/P07 merged automatically,
  including both sets of acceptance-matrix changes. Application `src/` matches
  P07; `evaluate/` and `tests/evaluate/` match the committed P06 tree.
- Local import refs: `codex/import-p07`, `codex/import-p06`. `main` was not moved.
- Linear Alembic head: `20261101_index_lifecycle`.

The old checkouts were read only. Their untracked reports and P06's two modified
benchmark outputs remain in place. Those benchmark outputs were also copied to
`F:/dpl13.10/folio-integration-backup-20261101/p06-uncommitted-evaluation/`.
They are historical runs, not measurements of this integration SHA.

All pre-existing untracked target files were copied to
`F:/dpl13.10/folio-integration-backup-20261101/target-local/` before switching.
The 22 files overlapping tracked incoming paths were preserved under
`displaced/` in that backup; the target now uses the integrated tracked versions.
The integration manifest records their hashes. Some byte differences are only
line endings; later search contracts and acceptance updates are retained.

## Findings

### [P1] IB-R01: published edits never invalidate a warm lexical reader

Location: `src/backend/search/engine.py:85`,
`src/backend/search_index/worker.py:169`.

The engine caches an index forever by generation ID. The worker overwrites that
same generation's files, without notifying the API process. A warm API reader
therefore continues serving old title/content/taxonomy postings until restart or
a generation rebuild, violating the expected publish/edit freshness even with
two users. Reproduction loads a one-document index, writes a second document to
the same generation, and observes that the existing reader still reports one.

Required repair: publish an atomic index version and invalidate/reload readers
across processes when it changes. Keep already issued context candidate lists
stable. Verify publish/edit -> worker -> new search in the same running API.

### [P1] IB-R02: tag edits enqueue the wrong revision hash

Location: `src/backend/services/admin/content_service.py:205`,
`src/backend/services/admin/content_service.py:221`,
`src/backend/search_index/hashing.py:42`.

Tag rows are deleted/recreated directly; with autoflush disabled, the outbox hash
reads an unflushed or cached `doc.document_tags` relationship. After commit the
job hash differs from the actual document hash. The worker then treats the
current edit as stale and completes it without updating search. Reproduced both
with the relationship initially loaded and initially unloaded.

Required repair: flush and refresh/expire the relationship before recording the
revision and outbox job, within the same transaction. Test actual worker
processing and search by newly added/removed tags, including rollback behavior.

### [P2] IB-R03: semantic and hybrid ignore selected category/tag/date filters

Location: `src/backend/services/search/search_service.py:390` and `:461`.

The dense adapter receives only the query and candidate limit. Its candidates
are used directly, or fused with filtered lexical hits; hydration checks only
publication/deletion. A semantic candidate from another category appears in both
semantic and hybrid responses despite an explicit category filter. Both cases
failed independent HTTP probes. Tag/date paths have the same missing filter.

Required repair: filter dense candidates before fusion/context snapshot creation
using the agreed AND tag and UTC created_at semantics. Cover category, tags and
dates in both modes, not just BM25.

### [P2] IB-R04: pagination falsely reports semantic success after fallback

Location: `src/backend/services/search/search_service.py:310`,
`src/backend/models/search_index.py` (SearchContext).

Page one falls back to BM25 and reports degradation correctly. Page two restores
`engine_used` from the requested mode and resets degradation to false; the
context does not store the actual engine/reason. The same results now appear to
come from semantic retrieval. Reproduced through the HTTP API with page_size=1.

Required repair: persist actual retrieval metadata in the context and return it
unchanged on subsequent pages. Also audit the double-fallback paths: they can
serve ILIKE while retaining the `fallback_bm25` label.

### [P2] IB-R05: P06 output overstates benchmark evidence

Locations: `evaluate/run_eval.py:504`, `:700`, `:712`, `:824`.

Static review finds that failed queries increment error_count but are omitted
from the aggregate quality denominator; a partially failing engine can receive
inflated quality metrics. The missing-index fallback probe calls ILIKE directly
and unconditionally marks it verified, without inducing a missing index through
SearchService. Report provenance hardcodes the old P05 commit. TF-IDF latency
measures the in-memory scorer while BM25 includes the service, database/context
and telemetry path, so those timings are not equivalent boundaries.

Required before final academic/release acceptance: keep failures in the
denominator, test actual degradation, record real SHA/snapshot identity and
declare timing boundaries. This review ran validator and unit tests; it did not
reproduce live dense-model quality or certify the historical five-engine table.

### [P2] IB-R06: browser passes do not prove healthy BM25 end to end

Locations: `tests/conftest.py:164`,
`tests/frontend/public/test_p07_evidence.py`.

Frontend reset reseeds data but does not build a lexical index. The newly
captured `01_search_bm25_desktop_1440.png` visibly says `ILIKE_FALLBACK`.
Thus 36 browser passes demonstrate UI flows/fallback handling, not the intended
BM25 engine on the integrated code. Add a healthy-index browser case asserting
`engine_used == bm25`, plus a separate deliberate fallback case.

## Verification actually run

Fresh, review-owned PostgreSQL 16.10 cluster:
`F:/dpl13.10/folio-integration-backup-20261101/pgdata`, loopback port 55464.
Tests provisioned unique run-owned databases; existing Folio databases were not
reset. Python 3.10 clean runtime from `folio-live-runtime/venv-clean`.
After validation only `postgres` remained apart from template databases; the
review-owned cluster was stopped cleanly with pg_ctl. Its files are retained.

| Check | Result |
| --- | --- |
| Existing backend/evaluation/safety/security suites | 291 passed, 4 skipped, 246.32 s |
| Four skipped database lifecycle/bootstrap cases rerun with FOLIO_TEST_ADMIN_URL | 4 passed, 0 skipped |
| Existing frontend suite, Chromium | 36 passed, 207.25 s |
| Independent regression probes | 6 failed: cache, two dense-filter modes, fallback pagination, two tag relationship states |
| P06 --validate-only | 103 manifest entries, 30 queries, validation passed |
| Alembic heads and fresh migrations in tests | One head; upgrade/seed succeeded |
| Source transfer checks | P07 src and committed P06 evaluation files preserved |

Totals across the existing suite: **331 distinct existing tests passed** after
rerunning the four initially skipped cases. This does not override the **six
new failing regression cases**. The new probes are deliberately ordinary tests,
not xfail/skip, so future CI exposes the defects until fixed.

The first attempt against old port 55463 skipped all tests because that server
was stopped. No pass claim is based on that attempt. The review used its own
cluster instead. An initial extra tag probe had an incorrect model import; it
was corrected before recording the final six-failure evidence.

Evidence: `docs/handoff/review/evidence-integration-b-20261101/` contains JUnit
XML, console logs, validator output, detector output and integration manifest.
Full screenshots remain outside Git under
`F:/dpl13.10/folio-integration-backup-20261101/browser-artifacts/`.

## Frontend technical audit

Impeccable audit guidance was used; the incumbent Paper/Ink interface was kept.
New mobile 360px and desktop 1440px captures were visually inspected. Existing
tests cover 360/390/768/1280/1440/1920 viewports and keyboard interactions.
No physical touch-device test or full WCAG certification was performed.

| Dimension | Score / 4 | Evidence/limit |
| --- | --- | --- |
| Accessibility | 3 | Existing keyboard/focus/ARIA tests pass; no comprehensive contrast audit |
| Performance | 2 | Native modules; no independent browser performance profiling |
| Theming | 3 | Consistent incumbent tokens; some hardcoded callout colors |
| Responsive | 3 | Viewport tests/captures pass; physical touch unverified |
| Integrity | 3 | Coherent interface; engine labels/tests have findings above |
| Total | 14 / 20 | Good UI baseline, qualified by search correctness findings |

The detector reported two colored left borders. They mark warning/error
callouts in this established interface, so they are not treated as blockers or
grounds for redesign. The meaningful issues are retrieval behavior and proof
of the engine actually used.

## P08 handoff and remaining conditions

Use this canonical branch for all further work, not the old source worktrees or
`main`. Source migration is complete; GitHub push is not a prerequisite.

Fix IB-R01 through IB-R04 and prove the healthy-index browser path before marking
Integration B functionally accepted. IB-R05 must be addressed before using P06
metrics as final release/academic evidence. P08 packaging can be prepared on
this branch, but must not assume the application is already accepted.

P08 must also supply the scheduled/long-running index worker entry point (the
current code exposes run_once only), shared persistent index storage, initial
index build, health checks and restore/rebuild procedure. Until file-writer
coordination is implemented and tested, use one index writer and serialize
rebuild operations; SKIP LOCKED protects jobs but not the shared JSON files.

Rate-limit-only hardening is deferred as requested. No new rate-limit blocker
was introduced. This task reviewed and integrated source; application behavior
was not rewritten. Fixes should be separate reviewable commits on this branch.

## Reproduce

Start the review-owned cluster with pg_ctl only if it is stopped, or supply a
different isolated PostgreSQL server. Run from the canonical workspace:

```powershell
$env:APP_ENV = 'test'
$env:DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55464/folio_ib_review'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55464/folio_ib_probe_test'
$env:FOLIO_TEST_ADMIN_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55464/postgres'
$env:INDEX_STORAGE_DIR = 'F:/dpl13.10/folio-integration-backup-20261101/probe-index'
$env:FOLIO_ARTIFACT_ROOT = 'F:/dpl13.10/folio-integration-backup-20261101/probe-artifacts'
& F:/dpl13.10/folio-live-runtime/venv-clean/Scripts/python.exe -m pytest tests/backend/search/test_integration_review_probe.py -q --tb=short
```

The command should currently fail six assertions. Existing-suite command:
`python -m pytest tests/backend tests/evaluate tests/safety tests/security --ignore=tests/backend/search/test_integration_review_probe.py -q`.
Browser command: `python -m pytest tests/frontend -q`.
Use distinct INDEX_STORAGE_DIR/artifact roots for concurrent suite runs.
