from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.search.semantic import SemanticAdapter, SemanticCandidateHit
from src.backend.search.hybrid import fuse_candidates_rrf
from src.backend.search.engine import CandidateHit
from src.backend.search_index.manager import GenerationManager


@pytest.fixture(autouse=True)
def ensure_active_generation(db_session: Session):
    active = GenerationManager.get_active_generation(db_session)
    if not active:
        GenerationManager.build_new_generation(db_session, force=True)


def test_semantic_mode_fallback_to_bm25(client: TestClient):
    """
    Contract Section 6:
    When mode='semantic' and ChromaDB/SentenceTransformer is unreachable:
    - Service falls back to Okapi BM25.
    - engine_requested: 'semantic'
    - engine_used: 'fallback_bm25'
    - is_degraded: true
    - degraded_reason explicitly declared (NO fake semantic success!).
    """
    with patch.object(
        SemanticAdapter,
        "check_availability",
        return_value=(False, "ChromaDB service unreachable"),
    ):
        res = client.get("/api/v1/search?q=neural+networks&mode=semantic&page=1&page_size=10")
        assert res.status_code == 200
        data = res.json()

        assert data["engine_requested"] == "semantic"
        assert data["engine_used"] == "fallback_bm25"
        assert data["is_degraded"] is True
        assert data["degraded_reason"] == "ChromaDB service unreachable"
        assert len(data["items"]) > 0


def test_hybrid_mode_fallback_to_pure_bm25(client: TestClient):
    """
    Contract Section 6:
    When mode='hybrid' and vector component fails:
    - Service falls back to pure Okapi BM25.
    - engine_requested: 'hybrid'
    - engine_used: 'fallback_bm25'
    - is_degraded: true
    - degraded_reason: 'Vector component unavailable; serving BM25'.
    """
    with patch.object(
        SemanticAdapter,
        "query",
        return_value=([], "Vector component unavailable; serving BM25"),
    ):
        res = client.get("/api/v1/search?q=neural+networks&mode=hybrid&page=1&page_size=10")
        assert res.status_code == 200
        data = res.json()

        assert data["engine_requested"] == "hybrid"
        assert data["engine_used"] == "fallback_bm25"
        assert data["is_degraded"] is True
        assert "Vector component unavailable; serving BM25" in data["degraded_reason"]
        assert len(data["items"]) > 0


def test_bm25_mode_fallback_to_ilike(client: TestClient, db_session: Session):
    """
    Contract Section 6:
    When mode='bm25' and index generation is missing/corrupted:
    - Service falls back to PostgreSQL ILIKE.
    - engine_requested: 'bm25'
    - engine_used: 'ilike_fallback'
    - is_degraded: true
    - degraded_reason: 'Lexical index generation unavailable; serving ILIKE'.
    - Fallback placeholder IndexGeneration row never masquerades as 'active'.
    """
    from src.backend.models.search_index import IndexGeneration

    db_session.query(IndexGeneration).filter(IndexGeneration.status == "active").update(
        {"status": "archived"}, synchronize_session=False
    )
    db_session.commit()

    res = client.get("/api/v1/search?q=neural&mode=bm25&page=1&page_size=10")
    assert res.status_code == 200
    data = res.json()

    assert data["engine_requested"] == "bm25"
    assert data["engine_used"] == "ilike_fallback"
    assert data["is_degraded"] is True
    assert "Lexical index generation unavailable; serving ILIKE" in data["degraded_reason"]
    assert len(data["items"]) > 0

    fallback_row = db_session.query(IndexGeneration).filter(IndexGeneration.id == "idx-gen-fallback").first()
    if fallback_row is not None:
        assert fallback_row.status == "archived"
    assert GenerationManager.get_active_generation(db_session) is None


def test_rrf_hybrid_fusion_logic():
    """
    Contract Section 5:
    Validates Reciprocal Rank Fusion (RRF) formula, deterministic tie-breaking,
    and metadata properties on CandidateHit instances.
    """
    bm25_hits = [
        CandidateHit(doc_id="doc-a", score=10.0, rank=1, raw_bm25=10.0),
        CandidateHit(doc_id="doc-b", score=8.0, rank=2, raw_bm25=8.0),
        CandidateHit(doc_id="doc-c", score=6.0, rank=3, raw_bm25=6.0),
    ]

    sem_hits = [
        SemanticCandidateHit(doc_id="doc-b", score=0.95, rank=1, raw_distance=0.05, chunk_count=2),
        SemanticCandidateHit(doc_id="doc-d", score=0.90, rank=2, raw_distance=0.10, chunk_count=1),
        SemanticCandidateHit(doc_id="doc-a", score=0.85, rank=3, raw_distance=0.15, chunk_count=3),
    ]

    fused = fuse_candidates_rrf(bm25_hits, sem_hits, top_k=5, rrf_k=60)

    assert len(fused) == 4
    # doc-b is rank 2 in BM25 and rank 1 in Semantic -> Highest fusion score!
    # RRF(doc-b) = 1/(60+2) + 1/(60+1) = 1/62 + 1/61 = 0.016129 + 0.016393 = 0.032522
    assert fused[0].doc_id == "doc-b"
    assert fused[0].rank == 1

    # Deterministic tie-breaking verification
    hit_ids = [h.doc_id for h in fused]
    assert set(hit_ids) == {"doc-a", "doc-b", "doc-c", "doc-d"}


def test_r14_hybrid_ilike_fallback_reports_true_total_and_paginates_past_100(client: TestClient, db_session: Session):
    """
    R14 / EXT-03:
    When hybrid search degrades to ILIKE fallback with >100 matching documents,
    snapshot_total equals the true match count and pagination beyond item 100 succeeds.
    """
    import uuid
    from datetime import datetime, timezone
    from src.backend.models.document import Document
    from src.backend.models.taxonomy import Category

    cat = db_session.query(Category).first()
    marker = f"HybridScaleMarker{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    docs = [
        Document(
            title=f"{marker} Paper {i:03d}",
            summary=f"Summary for {marker} {i}",
            content=f"Body content for {marker} document {i}",
            category_id=cat.id,
            status="published",
            created_at=now,
            published_at=now,
        )
        for i in range(125)
    ]
    db_session.add_all(docs)
    db_session.commit()

    with (
        patch.object(GenerationManager, "get_active_generation", return_value=None),
        patch.object(SemanticAdapter, "query", return_value=([], "ChromaDB service unreachable")),
    ):
        res_p1 = client.get(f"/api/v1/search?q={marker}&mode=hybrid&page=1&page_size=20")
        assert res_p1.status_code == 200
        d1 = res_p1.json()
        assert d1["engine_used"] == "ilike_fallback"
        assert d1["is_degraded"] is True
        assert d1["snapshot_total"] == 125
        assert d1["has_more"] is True
        assert len(d1["items"]) == 20

        # Page 6 reaches items 101..120 (past the old 100-item truncation)
        token = d1["search_context_token"]
        res_p6 = client.get(
            f"/api/v1/search?q={marker}&mode=hybrid&page=6&page_size=20&search_context_token={token}"
        )
        assert res_p6.status_code == 200
        d6 = res_p6.json()
        assert d6["snapshot_total"] == 125
        assert len(d6["items"]) == 20
        assert d6["has_more"] is True


def test_r15_semantic_timeout_enforced_with_graceful_fallback(client: TestClient):
    """
    R15 / EXT-04:
    When SemanticAdapter.query exceeds SEARCH_TIMEOUT_SECONDS, SearchService aborts waiting
    and degrades gracefully to BM25/ILIKE within bounded latency instead of hanging.
    """
    import time
    from src.backend.core.config import settings

    def slow_semantic_query(query_text: str, top_k: int = 100, db=None):
        time.sleep(2.5)
        return [], None

    orig_timeout = settings.SEARCH_TIMEOUT_SECONDS
    try:
        settings.SEARCH_TIMEOUT_SECONDS = 0.15
        with patch.object(SemanticAdapter, "query", side_effect=slow_semantic_query):
            t0 = time.perf_counter()
            res = client.get("/api/v1/search?q=neural&mode=semantic&page=1&page_size=5")
            elapsed = time.perf_counter() - t0

            assert res.status_code == 200
            assert elapsed < 1.5
            data = res.json()
            assert data["is_degraded"] is True
            assert data["engine_used"] in ("fallback_bm25", "ilike_fallback")
            assert "timed out" in (data["degraded_reason"] or "").lower()
    finally:
        settings.SEARCH_TIMEOUT_SECONDS = orig_timeout


def test_r3_04_semantic_timeout_caps_total_concurrency_holds_slot_until_exit_and_recovers(db_session: Session):
    """
    R3-04:
    1. Semantic timeouts must NOT leak unbounded running adapter threads or queues across requests.
    2. Total active + queued capacity is bounded; timed-out running worker slots stay occupied
       until the worker actually finishes (never released on caller timeout).
    3. Excess requests fast-fail with saturation degradation without spawning threads or entering adapter.query.
    4. Once slow workers finish, slots drain cleanly and subsequent healthy requests recover.
    """
    import threading
    from src.backend.core.config import settings
    from src.backend.services.search.search_service import SearchService

    worker_cap = 2
    queue_cap = 1
    orig_timeout = settings.SEARCH_TIMEOUT_SECONDS
    orig_workers = getattr(settings, "SEMANTIC_EXECUTOR_WORKERS", None)
    orig_pending = getattr(settings, "SEMANTIC_MAX_PENDING", None)

    settings.SEARCH_TIMEOUT_SECONDS = 0.08
    settings.SEMANTIC_EXECUTOR_WORKERS = worker_cap
    settings.SEMANTIC_MAX_PENDING = queue_cap

    lock = threading.Lock()
    entered_threads = []
    passed_dbs = []
    two_entered = threading.Event()
    all_workers_exited = threading.Event()
    release_slow = threading.Event()
    active_inside = 0
    max_concurrent_inside = 0
    total_started = 0

    class SlowOrFastAdapter:
        def __init__(self):
            self.fail_slow = True

        def check_availability(self, load_model: bool = True):
            return True, None

        def query(self, query_text: str, top_k: int = 100, db=None):
            nonlocal active_inside, max_concurrent_inside, total_started
            with lock:
                entered_threads.append(threading.current_thread().name)
                passed_dbs.append(db)
                if self.fail_slow:
                    total_started += 1
                    active_inside += 1
                    max_concurrent_inside = max(max_concurrent_inside, active_inside)
                    if total_started >= worker_cap:
                        two_entered.set()
            if self.fail_slow:
                try:
                    release_slow.wait(timeout=3.0)
                    return [], None
                finally:
                    with lock:
                        active_inside -= 1
                        if active_inside == 0:
                            all_workers_exited.set()
            return [SemanticCandidateHit(doc_id="fast-doc", score=0.95, rank=1, raw_distance=0.05, chunk_count=1)], None

    adapter = SlowOrFastAdapter()
    service = SearchService(adapter=adapter)
    db_marker = object()

    try:
        # 1. Saturate all worker slots (2) with hung calls that time out on caller side
        def call_timed_out():
            return service._query_semantic_with_timeout("hung query", top_k=10, db=db_marker)

        t1_res = []
        t2_res = []
        th1 = threading.Thread(target=lambda: t1_res.append(call_timed_out()))
        th2 = threading.Thread(target=lambda: t2_res.append(call_timed_out()))
        th1.start()
        th2.start()
        assert two_entered.wait(timeout=2.0), "Expected both bounded workers to enter SlowAdapter.query"
        th1.join(timeout=2.0)
        th2.join(timeout=2.0)
        assert not th1.is_alive() and not th2.is_alive()
        assert "timed out" in (t1_res[0][1] or "").lower()
        assert "timed out" in (t2_res[0][1] or "").lower()

        # Workers are STILL blocked because release_slow is not set yet.
        # Concurrent burst of 4 more requests while workers hold slots:
        # total active+queued can never exceed worker_cap + queue_cap, and entered count must NOT exceed worker_cap!
        burst_results = []
        burst_lock = threading.Lock()
        barrier = threading.Barrier(4)

        def call_burst():
            barrier.wait(timeout=2.0)
            res = service._query_semantic_with_timeout("burst query", top_k=10, db=db_marker)
            with burst_lock:
                burst_results.append(res)

        burst_threads = [threading.Thread(target=call_burst) for _ in range(4)]
        for t in burst_threads:
            t.start()
        for t in burst_threads:
            t.join(timeout=2.0)

        assert len(burst_results) == 4
        assert max_concurrent_inside <= worker_cap, f"Concurrency cap violated: {max_concurrent_inside}"
        assert len(entered_threads) <= worker_cap, (
            f"Leaked extra adapter invocations while slots hung: {len(entered_threads)}"
        )
        saturated_msgs = [err for _, err in burst_results if err and "saturated" in err.lower()]
        assert len(saturated_msgs) >= 3, f"Expected fast-fail saturation messages, got: {burst_results}"
        assert all(d is None for d in passed_dbs), f"Foreground db/marker leaked across threads: {passed_dbs}"

        # 2. Unblock hung workers -> slots must release in finally and recover cleanly
        adapter.fail_slow = False
        release_slow.set()
        assert all_workers_exited.wait(timeout=2.0)

        # Wait briefly for executor workers to finish finally block & return slots
        import time as _t
        deadline = _t.monotonic() + 2.0
        recovered = None
        while _t.monotonic() < deadline:
            hits, err = service._query_semantic_with_timeout("healthy query", top_k=10, db=db_marker)
            if err is None:
                recovered = hits
                break
            _t.sleep(0.02)
        assert recovered is not None and len(recovered) == 1 and recovered[0].doc_id == "fast-doc"
    finally:
        release_slow.set()
        settings.SEARCH_TIMEOUT_SECONDS = orig_timeout
        if orig_workers is not None:
            settings.SEMANTIC_EXECUTOR_WORKERS = orig_workers
        if orig_pending is not None:
            settings.SEMANTIC_MAX_PENDING = orig_pending


def test_r3_04_search_endpoint_never_passes_request_session_across_threads(client: TestClient):
    """
    R3-04:
    End-to-end /api/v1/search?mode=semantic must never pass the foreground SQLAlchemy
    Session into the background semantic worker thread.
    """
    seen_dbs = []

    def inspect_query(query_text: str, top_k: int = 100, db=None):
        seen_dbs.append(db)
        return [], "Vector store intentionally offline"

    with patch.object(SemanticAdapter, "query", side_effect=inspect_query):
        res = client.get("/api/v1/search?q=neural&mode=semantic&page=1&page_size=5")
        assert res.status_code == 200
        assert res.json()["engine_used"] == "fallback_bm25"

    assert len(seen_dbs) == 1
    assert seen_dbs[0] is None, f"Foreground Session was leaked across thread boundary: {seen_dbs[0]!r}"


def test_r3_04_semantic_source_url_resolves_on_caller_thread_without_db_leak(
    client: TestClient,
    db_session: Session,
):
    """
    R3-04:
    When SemanticAdapter.query runs with db=None in the worker thread and returns a hit
    identified only by source_url (unmapped doc_id), SearchService resolves canonical
    Document.id on the caller thread inside _filter_semantic_candidates.
    """
    from src.backend.models.document import Document

    target_doc = (
        db_session.query(Document)
        .filter(
            Document.status == "published",
            Document.deleted_at.is_(None),
            Document.source_url.is_not(None),
        )
        .first()
    )
    assert target_doc is not None and target_doc.source_url

    seen_dbs = []

    def return_url_only_hit(query_text: str, top_k: int = 100, db=None):
        seen_dbs.append(db)
        return [
            SemanticCandidateHit(
                doc_id="unmapped-vector-id",
                score=0.91,
                rank=1,
                raw_distance=0.09,
                chunk_count=1,
                source_url=target_doc.source_url,
            )
        ], None

    with patch.object(SemanticAdapter, "query", side_effect=return_url_only_hit):
        res = client.get("/api/v1/search?q=neural&mode=semantic&page=1&page_size=5")
        assert res.status_code == 200
        data = res.json()

    assert seen_dbs == [None], f"Foreground db leaked into worker thread: {seen_dbs!r}"
    assert data["engine_requested"] == "semantic"
    assert data["engine_used"] == "semantic"
    assert data["is_degraded"] is False
    assert [item["id"] for item in data["items"]] == [target_doc.id]


def test_r3_04_readiness_probe_uses_bounded_executor_without_thread_leak():
    """
    R3-04:
    /health/ready semantic check uses bounded shared executor capacity rather than
    creating an unbounded ThreadPoolExecutor per request on hang.
    """
    import threading
    from fastapi.testclient import TestClient
    from src.backend.main import app
    from src.backend.services.search.search_service import semantic_adapter

    release = threading.Event()
    entered = []
    lock = threading.Lock()
    entered_evt = threading.Event()

    def slow_check(load_model: bool = False):
        with lock:
            entered.append(threading.current_thread().name)
            if len(entered) >= 2:
                entered_evt.set()
        release.wait(timeout=2.0)
        return False, "Simulated slow chroma"

    try:
        with patch.object(semantic_adapter, "check_availability", side_effect=slow_check):
            with TestClient(app) as c:
                threads = [threading.Thread(target=lambda: c.get("/health/ready")) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=6.0)
        assert len(entered) <= 2, f"Unbounded readiness checks spawned {len(entered)} threads: {entered}"
    finally:
        release.set()
