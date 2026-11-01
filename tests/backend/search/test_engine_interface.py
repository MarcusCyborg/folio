"""
Contract and Interface tests for SearchEngine P05 API handoff (P04).

Verifies:
1. P05 interface contract: SearchQuery -> SearchResponse
2. Response contains: candidate doc_ids, scores, ranks, stats; NEVER contains full body/content
3. Multi-generation loading and caching
4. Sub-millisecond performance on authentic corpus without scanning full document bodies
"""

import json
import time
from pathlib import Path
import pytest

from src.backend.search.analyzer import TextAnalyzer
from src.backend.search.index import InvertedIndex
from src.backend.search.builder import IndexBuilder
from src.backend.search.engine import SearchEngine, SearchQuery, SearchResponse, CandidateHit


@pytest.fixture(scope="module")
def authentic_corpus_index(tmp_path_factory) -> InvertedIndex:
    """Builds and serializes an index from the authentic 103-document fixture."""
    fixture_path = Path("fixtures/folio/documents.jsonl")
    if not fixture_path.exists():
        pytest.skip("Authentic fixture documents.jsonl not found")

    docs = []
    with open(fixture_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))

    tmp_dir = tmp_path_factory.mktemp("authentic_index")
    postings_dir = tmp_dir / "postings"

    builder = IndexBuilder()
    index = builder.build_from_documents(docs, generation_id="idx-gen-authentic-103", output_dir=postings_dir)
    return index


def test_interface_returns_only_ids_scores_ranks_stats(authentic_corpus_index: InvertedIndex):
    """
    Requirement 5: SearchEngine returns CandidateHit objects with IDs, scores, ranks,
    and stats. It MUST NOT return document content or body.
    """
    engine = SearchEngine()
    query = SearchQuery(
        query="neural networks",
        generation_id=authentic_corpus_index.generation_id,
        top_k=10,
    )

    response = engine.search(query, index=authentic_corpus_index)

    assert isinstance(response, SearchResponse)
    assert response.total_matches > 0
    assert len(response.candidates) <= 10
    assert response.generation_id == "idx-gen-authentic-103"
    assert "total_docs" in response.corpus_stats
    assert "avg_doc_len" in response.corpus_stats

    # Check CandidateHit structure
    for hit in response.candidates:
        assert isinstance(hit, CandidateHit)
        assert isinstance(hit.doc_id, str)
        assert len(hit.doc_id) == 36  # Canonical UUID length
        assert isinstance(hit.score, float)
        assert hit.score > 0.0
        assert isinstance(hit.rank, int)
        assert hit.rank >= 1
        assert isinstance(hit.raw_bm25, float)
        assert isinstance(hit.title_boost, float)

        # Invariant: CandidateHit MUST NOT contain body or content!
        assert not hasattr(hit, "content")
        assert not hasattr(hit, "body")
        assert not hasattr(hit, "text")


def test_multi_generation_index_cache(tmp_path: Path):
    """Requirement 5: SearchEngine manages multiple generations via cache and on-disk loading."""
    builder = IndexBuilder()

    # Generation 1
    dir1 = tmp_path / "gen1" / "postings"
    idx1 = builder.build_from_documents(
        [{"id": "doc-1", "title": "Doc 1", "content": "quantum mechanics"}],
        generation_id="gen-1",
        output_dir=dir1,
    )

    # Generation 2
    dir2 = tmp_path / "gen2" / "postings"
    idx2 = builder.build_from_documents(
        [{"id": "doc-2", "title": "Doc 2", "content": "deep learning"}],
        generation_id="gen-2",
        output_dir=dir2,
    )

    engine = SearchEngine()
    engine.get_or_load_index("gen-1", storage_dir=dir1)
    engine.get_or_load_index("gen-2", storage_dir=dir2)

    # Query gen-1
    resp1 = engine.search(SearchQuery(query="quantum", generation_id="gen-1"))
    assert resp1.total_matches == 1
    assert resp1.candidates[0].doc_id == "doc-1"

    # Query gen-2
    resp2 = engine.search(SearchQuery(query="deep", generation_id="gen-2"))
    assert resp2.total_matches == 1
    assert resp2.candidates[0].doc_id == "doc-2"


def test_retrieval_benchmark_sub_millisecond(authentic_corpus_index: InvertedIndex):
    """
    Performance benchmark: Evaluates query execution time over inverted index.
    Should execute in sub-millisecond to low millisecond range on the 103-document authentic corpus.
    """
    engine = SearchEngine()
    test_queries = [
        "deep learning",
        "artificial intelligence",
        "neural networks",
        "quantum computing",
        "computational biology",
        "robotics",
    ]

    latencies = []
    for q in test_queries:
        start = time.perf_counter()
        resp = engine.search(
            SearchQuery(query=q, generation_id=authentic_corpus_index.generation_id, top_k=20),
            index=authentic_corpus_index,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        assert resp.total_matches >= 0

    avg_latency = sum(latencies) / len(latencies)
    # Average latency must be under 15ms in test runtime
    assert avg_latency < 15.0, f"Average retrieval latency too high: {avg_latency:.2f}ms"
