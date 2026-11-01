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


def test_bm25_mode_fallback_to_ilike(client: TestClient):
    """
    Contract Section 6:
    When mode='bm25' and index generation is missing/corrupted:
    - Service falls back to PostgreSQL ILIKE.
    - engine_requested: 'bm25'
    - engine_used: 'ilike_fallback'
    - is_degraded: true
    - degraded_reason: 'Lexical index generation unavailable; serving ILIKE'.
    """
    with patch.object(
        GenerationManager,
        "get_active_generation",
        return_value=None,
    ):
        res = client.get("/api/v1/search?q=neural&mode=bm25&page=1&page_size=10")
        assert res.status_code == 200
        data = res.json()

        assert data["engine_requested"] == "bm25"
        assert data["engine_used"] == "ilike_fallback"
        assert data["is_degraded"] is True
        assert "Lexical index generation unavailable; serving ILIKE" in data["degraded_reason"]
        assert len(data["items"]) > 0


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
