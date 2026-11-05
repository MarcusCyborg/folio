# Folio Milestone Integration A / R03 — Search Contract, Canonical Identifiers & Pagination Stability Handoff

**Handoff ID:** `IA-R03-search-contract`  
**Milestone:** Integration A — Task R03 (Search Contract Documentation, Remediation of Findings IA-04 & IA-05)  
**Date:** 2026-11-01  
**Author:** Folio Search Contract Owner & QA Lead  
**Status:** `CONTRACT SPECIFICATION APPROVED / PENDING P03-P05 IMPLEMENTATION` (Zero runtime code implemented in R03; specifications locked for P03–P05)

---

## 1. Executive Summary & Remediation Scope

Task **R03** resolves findings **IA-04** and **IA-05** exclusively through formal documentation and contract locking. No runtime code (corpus importer, index schema/outbox migrations, background worker, BM25 scoring, or public search API endpoints) was implemented in this task, strictly adhering to milestone ownership boundaries.

### 1.1 Finding IA-04 Remediation (Canonical Identifier & Fixture Preservation)
- **Problem in Baseline:** Contract v2.0.0 stipulated that canonical document IDs must strictly be `UUIDv4`, which directly conflicted with the official seed dataset where 100% of IDs are `UUIDv5`. An importer or validator enforcing UUIDv4 would have rejected or re-minted all fixture IDs, breaking qrels, URLs, and interaction logs.
- **Remediation Delivered in R03:**
  - Defined canonical document ID as any valid RFC 4122 UUID string representation stored in `documents.id` (`String(36)`), supporting existing **UUIDv5** and **UUIDv4**.
  - Default for newly created documents authored via Admin UI / API remains `uuid.uuid4()` as defined in `src/backend/models/document.py::gen_uuid`.
  - Verified fixture ground truth: [`fixtures/folio/documents.jsonl`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/fixtures/folio/documents.jsonl) contains **exactly 103 documents** (100 published, 3 draft, SHA256: `5413a1f6265dc5f4ccea0081356690e54bd63ed78c6b63ad1fee9025b4183abe`).
  - Superseded conflicting legacy documentation claims of "165 documents" or "162 published documents".
  - Mandated that the P03 importer perform idempotent `source_url -> Document.id` mapping without modifying existing IDs.

### 1.2 Finding IA-05 Remediation (Search Context Pagination & Generation Stability)
- **Problem in Baseline:** Contract v2.0.0 lacked a pagination stability contract. Querying page 1 under generation G1 followed by worker promotion of G2 caused non-deterministic candidate drift, skipped documents, and duplicate items. Furthermore, the contract declared a single `total` field without distinguishing exact lexical counts from finite semantic candidate windows.
- **Remediation Delivered in R03:**
  - Selected and locked **MỘT (1) cơ chế duy nhất**: **Server-Issued Actor-Bound Search Context** (Candidate Snapshot Cursor).
  - Specified request/response binding, context tokens, and an **absolute TTL of 15 minutes** (`SEARCH_CONTEXT_TTL_MINUTES=15`, configurable).
  - Defined error codes: HTTP `410 Gone` (`SEARCH_CONTEXT_EXPIRED`), HTTP `400 Bad Request` (`CONTEXT_PARAMETER_MISMATCH`), and HTTP `403 Forbidden` (`CONTEXT_ACTOR_MISMATCH`).
  - Defined generation retention lease contract: P03 garbage collection MUST NOT purge generation files while active search contexts hold a valid lease.
  - Specified defense-in-depth live PostgreSQL publication verification (`status = 'published' AND deleted_at IS NULL`).
  - Locked the pruning policy: **Rank-window fixed, prune without backfill** to guarantee zero cross-page duplicates.
  - Clarified count semantics: `snapshot_total` (exact for BM25), `snapshot_candidate_count` and `is_approximate_total: true` (for semantic/hybrid), and explicit boolean `has_more`.
  - Standardized date filters on `Document.created_at` in UTC (identical to `/api/v1/documents`), defined taxonomy error semantics, established strict tie-break `(score DESC, Document.id ASC)`, and affirmed 60s demo freshness with 0s unpublish/delete latency.

---

## 2. Git Metadata & Worktree Verification

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Active Integration Worktree** | `F:/dpl13.10/WikiSearchEngine-ia-fix` | Dedicated integration worktree |
| **Integration Branch** | `codex/integration-a-remediation` | Local integration branch (no push, no main merge) |
| **Source Commit Baseline** | `86365ac` | Task R01 completion commit |
| **Files Modified in Scope** | `docs/search-contract.md` | Search Contract v2.1.0 specifications |
| | `docs/acceptance-matrix.md` | Matrix update: Alembic head wording & IR rows |
| | `GEMINI-EXECUTION-PROMPTS.md` | P03 input specifications supplemented |
| **Files Created in Scope** | `docs/handoff/gemini/IA-R03-search-contract.md` | This handoff report |
| **Preserved Unowned Changes** | `scripts/bootstrap_admin.py` | R02 work-in-progress edits strictly preserved untouched |

---

## 3. Fixture Verification & Canonical Ground Truth

Direct execution of static inspection on [`fixtures/folio/documents.jsonl`](file:///F:/dpl13.10/WikiSearchEngine-ia-fix/fixtures/folio/documents.jsonl):

```python
# Command:
python -c "
import json, uuid, hashlib

with open('fixtures/folio/documents.jsonl', 'rb') as f:
    content = f.read()

sha256 = hashlib.sha256(content).hexdigest()
lines = [json.loads(line) for line in content.decode('utf-8').splitlines() if line.strip()]

status_counts = {}
uuid_versions = {}
source_urls = set()
ids = set()

for doc in lines:
    st = doc.get('status')
    status_counts[st] = status_counts.get(st, 0) + 1
    doc_id = doc.get('id')
    ids.add(doc_id)
    u = uuid.UUID(doc_id)
    uuid_versions[u.version] = uuid_versions.get(u.version, 0) + 1
    source_urls.add(doc.get('source_url'))

print(f'Total count: {len(lines)}')
print(f'SHA256: {sha256}')
print(f'Status counts: {status_counts}')
print(f'UUID versions: {uuid_versions}')
print(f'Unique IDs: {len(ids)}')
print(f'Unique source URLs: {len(source_urls)}')
"
```

### Verification Results:
- **Total Records:** `103`
- **File SHA256:** `5413a1f6265dc5f4ccea0081356690e54bd63ed78c6b63ad1fee9025b4183abe`
- **Status Counts:** `published: 100`, `draft: 3`
- **UUID Versions:** `version 5: 103` (100% of fixture IDs are UUIDv5)
- **Unique Canonical IDs:** `103`
- **Unique Source URLs:** `103`
- **Historical Claims Resolution:** Earlier documentation referencing 165 or 162 documents is formally superseded. All components in P03–P06 must validate against 103 documents.

---

## 4. Key Architectural Decisions Recorded in Contract v2.1.0

### 4.1 Server-Issued Actor-Bound Search Context
1. **Context Creation (`page=1`):** Server evaluates the search query against the active index generation, captures candidate document IDs in ranked order, stores the context with a unique `search_context_token` (UUIDv4), and acquires an active retention lease on the generation.
2. **Context Resumption (`page >= 2`):** Client provides `search_context_token`. Server verifies:
   - `actor_key` matches request session.
   - `now() <= expires_at`.
   - Query, mode, filters, and page_size match the context.
3. **Absolute Expiration (15 Minutes):** Context expires after 15 minutes (`SEARCH_CONTEXT_TTL_MINUTES=15`). No sliding extension. Expired requests return HTTP `410 Gone` with code `SEARCH_CONTEXT_EXPIRED` and `reissue_search: true`.
4. **Generation Lease & Safe Garbage Collection:** P03 background cleaner checks generation lease counters. When generation G1 is retired after G2 activation, G1 stays in `draining` until all contexts referencing G1 expire. G1 is never unlinked or corrupted while serving live pagination.
5. **Live Publication Verification:** For the requested page slice (e.g. ranks 21–40), server queries live PostgreSQL for `status = 'published' AND deleted_at IS NULL`.
6. **Prune Without Backfill:** If candidate #25 was unpublished, Page 2 returns 19 items. The server does not backfill candidate #41, preserving candidate rank boundaries and eliminating cross-page duplicate risks.
7. **Count Semantics:**
   - Lexical BM25: Returns `snapshot_total: <int>` (exact index matches at snapshot time) and `is_approximate_total: false`.
   - Semantic / Hybrid: Evaluated over a finite candidate window (\(K=100\) or \(K=200\)). Returns `snapshot_total: null`, `snapshot_candidate_count: 100`, and `is_approximate_total: true`.
   - Paging indicator: `has_more: boolean` determined by `(page * page_size) < snapshot_candidate_count`.
8. **Date Filters:** Operates on `Document.created_at` in UTC (`date_from 00:00:00 UTC` to `date_to 23:59:59.999999 UTC`), ensuring behavioral alignment with `/api/v1/documents`.
9. **Taxonomy & Error Semantics:**
   - Unknown category UUID or tag UUID: Returns HTTP `200 OK` with `items: []`, `snapshot_total: 0`, `has_more: false`.
   - Malformed UUID string: Returns HTTP `422 Unprocessable Entity`.
   - `date_from > date_to`: Returns HTTP `422 Unprocessable Entity` with code `INVALID_DATE_RANGE`.
10. **Deterministic Tie-Breaker:** Primary `score DESC`, strict secondary `Document.id ASC` (lexicographical string comparison).
11. **Freshness Targets:** \(\le 60\)s for create/update index synchronization under demo load; 0s (instantaneous) for unpublish and soft-delete via live relational verification.

---

## 5. Walkthrough Scenarios Included in Contract

1. **Scenario 1: Generation Swap during Pagination (G1 -> G2):**
   - Reader requests Page 1 on G1; context `ctx-001` created on G1.
   - Admin imports documents; worker swaps active generation to G2; G1 enters `draining`.
   - Reader requests Page 2 with `ctx-001`.
   - Server reads slice 21–40 from G1 snapshot, verifies live PostgreSQL, returns stable Page 2.
2. **Scenario 2: Expired Context (TTL 15m Exceeded):**
   - Reader requests Page 2 after 16 minutes.
   - Server returns HTTP `410 Gone` (`code: SEARCH_CONTEXT_EXPIRED`, `reissue_search: true`).
   - Frontend safely restarts query from Page 1 without UI crash.
3. **Scenario 3: Mid-Context Document Unpublication (Prune Without Backfill):**
   - Document #25 unpublished after Page 1 served.
   - Reader requests Page 2 (ranks 21–40).
   - Live DB check filters out #25. Page 2 returns 19 items, `has_more: true`.
   - Page 3 subsequently serves ranks 41–50 without duplication or item skips.
4. **Scenario 4: Semantic Search with Limited Candidate Window:**
   - Semantic query retrieves top \(K=100\) candidates.
   - Context created with `snapshot_candidate_count = 100`, `snapshot_total = null`, `is_approximate_total = true`.
   - Page 5 returns items 81–100 with `has_more = false`.
   - Client clearly knows candidate window is exhausted.

---

## 6. Alembic Migration Chain Status

- **Correction of Legacy Reference:** Historical documents referenced "2 Alembic heads".
- **Verified Codebase Reality:** Exactly **one (1) single linear Alembic chain**:
  - Head revision: `20261031_click_unique` (`alembic/versions/20261031_click_idempotency_unique.py`).
  - Base revision: `efeaa3d84c9b` (`alembic/versions/efeaa3d84c9b_initial_folio_schema.py`).
- **Chain Continuity:**
  - Milestone **R04** will append the shared rate-limiting table migration to `20261031_click_unique`.
  - Milestone **P03** will use the post-R04 head as its `down_revision`.

---

## 7. Cross-Milestone Ownership Matrix

| Task | Component | Responsibility | Status |
| :--- | :--- | :--- | :--- |
| **R03** | Search Contract | Formulate and freeze Search Contract v2.1.0, canonical UUID definition, Search Context pagination invariants, count semantics, and acceptance matrix. Zero code. | **COMPLETE** |
| **P03** | Index Platform | Ingestion pipeline (preserve 103 fixture IDs), transactional outbox table & worker, index generation schema, atomic swap, generation retention lease enforcement (no GC of leased generations). | Pending R01/R02/R04 |
| **P04** | Information Retrieval | Preprocessor, tokenizer, inverted index postings, Okapi BM25 scoring algorithm, candidate retrieval interface for P05. | Pending P03 |
| **P05** | Search API | Public search endpoint (`/api/v1/search`), Search Context storage & manager (`search_contexts` table/cache), context parameter validation, live PostgreSQL verification, prune without backfill, click logging integration. | Pending P03, P04 |

---

## 8. Finalized Inputs for P03 Index Lifecycle Engineer

When the P03 engineer initiates Milestone M3, they must strictly follow these locked inputs:

1. **Worktree & Ref:** Must operate in `F:/dpl13.10/WikiSearchEngine-ia-fix` on branch `codex/integration-a-remediation`.
2. **Canonical Document IDs:**
   - Inverted index, outbox, and posting lists MUST use the existing Folio Document ID (`documents.id`, `String(36)`).
   - Ingestion importer MUST preserve all 103 existing fixture document IDs (`UUIDv5`), mapping `source_url -> Document.id` idempotently.
   - Do NOT validate or reject IDs using `uuid.UUID.version == 4`.
   - Do NOT attempt to migrate fixture IDs to v4.
3. **Generation Retention Lease Contract:**
   - The index generation model/table must include state tracking (e.g. `active`, `draining`, `retired`) and an active context lease indicator / timestamp.
   - When a new generation G2 is promoted to `active`, G1 is marked `draining`.
   - The P03 background GC worker MUST NOT delete or unlink generation G1 files while unexpired search context leases exist (`TTL = 15 minutes`).
   - P03 must provide a thread-safe reader interface allowing P04/P05 to read posting lists for a specific generation ID.
4. **Transactional Outbox Sync:**
   - Ingestion of mutations (create, update, publish, unpublish, soft-delete, taxonomy) must emit outbox records in the same transaction as PostgreSQL mutations.
5. **Alembic Down Revision:**
   - Single linear chain head `20261031_click_unique` (or the updated head after R04 shared rate-limiter migration).
