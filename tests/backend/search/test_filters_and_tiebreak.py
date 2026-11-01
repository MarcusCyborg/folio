"""
Unit and Contract tests for Search Filters, Tie-Breaking, and Edge Cases (P04).

Verifies:
1. Category filtering (exact UUID match, unknown UUID yields empty results)
2. Tag filtering (strict AND semantics across multiple tags)
3. Date range filtering (inclusive boundaries on created_at UTC)
4. Invalid date range (date_from > date_to raises ValueError)
5. Status / publication filtering (drafts excluded by default)
6. Stable deterministic tie-breaking (score DESC, doc_id ASC)
7. Empty corpus handling (N=0, no division by zero)
8. Unknown terms handling (unknown vocabulary yields 0 matches without crash)
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.backend.search.analyzer import TextAnalyzer
from src.backend.search.index import InvertedIndex
from src.backend.search.engine import SearchEngine, SearchQuery


@pytest.fixture
def populated_index() -> InvertedIndex:
    """Fixture creating an index with rich taxonomy and date attributes."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="filter-test-gen", analyzer=analyzer)

    base_time = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)

    # Doc 1: AI, tags [ml, deep-learning], published, created 2026-10-31 10:00
    index.upsert_document(
        doc_id="11111111-1111-1111-1111-111111111111",
        text="neural networks in artificial intelligence",
        title="Doc 1",
        category_id="cat-ai-uuid",
        tag_ids=["tag-ml-uuid", "tag-dl-uuid"],
        created_at=(base_time).isoformat(),
        status="published",
    )

    # Doc 2: AI, tags [ml], published, created 2026-10-31 12:00
    index.upsert_document(
        doc_id="22222222-2222-2222-2222-222222222222",
        text="neural networks in robotics",
        title="Doc 2",
        category_id="cat-ai-uuid",
        tag_ids=["tag-ml-uuid"],
        created_at=(base_time + timedelta(hours=2)).isoformat(),
        status="published",
    )

    # Doc 3: Biology, tags [bio, ml], published, created 2026-10-31 14:00
    index.upsert_document(
        doc_id="33333333-3333-3333-3333-333333333333",
        text="neural networks in biology",
        title="Doc 3",
        category_id="cat-bio-uuid",
        tag_ids=["tag-bio-uuid", "tag-ml-uuid"],
        created_at=(base_time + timedelta(hours=4)).isoformat(),
        status="published",
    )

    # Doc 4: AI, tags [ml], DRAFT, created 2026-10-31 16:00
    index.upsert_document(
        doc_id="44444444-4444-4444-4444-444444444444",
        text="neural networks draft study",
        title="Doc 4 Draft",
        category_id="cat-ai-uuid",
        tag_ids=["tag-ml-uuid"],
        created_at=(base_time + timedelta(hours=6)).isoformat(),
        status="draft",
    )

    return index


def test_category_filtering(populated_index: InvertedIndex):
    """Requirement 4: Category filter retains only documents matching category_id."""
    engine = SearchEngine(analyzer=TextAnalyzer(filter_stopwords=False))

    # Search with category_id = AI
    resp_ai = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            category_id="cat-ai-uuid",
        ),
        index=populated_index,
    )
    # Docs 1 and 2 match; Doc 3 is bio; Doc 4 is draft
    assert resp_ai.total_matches == 2
    matched_ids = {c.doc_id for c in resp_ai.candidates}
    assert matched_ids == {
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    }

    # Search with category_id = Biology
    resp_bio = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            category_id="cat-bio-uuid",
        ),
        index=populated_index,
    )
    assert resp_bio.total_matches == 1
    assert resp_bio.candidates[0].doc_id == "33333333-3333-3333-3333-333333333333"

    # Search with unknown category UUID -> 0 results
    resp_unknown = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            category_id="cat-unknown-uuid",
        ),
        index=populated_index,
    )
    assert resp_unknown.total_matches == 0
    assert resp_unknown.candidates == []


def test_tag_filtering_and_semantics(populated_index: InvertedIndex):
    """Requirement 4: Tag filter applies strict AND semantics."""
    engine = SearchEngine(analyzer=TextAnalyzer(filter_stopwords=False))

    # Single tag: tag-ml-uuid (Doc 1, Doc 2, Doc 3 have tag-ml)
    resp_single = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            tag_ids=["tag-ml-uuid"],
        ),
        index=populated_index,
    )
    assert resp_single.total_matches == 3

    # Multiple tags (AND): tag-ml-uuid AND tag-dl-uuid (Only Doc 1 has both)
    resp_multi = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            tag_ids=["tag-ml-uuid", "tag-dl-uuid"],
        ),
        index=populated_index,
    )
    assert resp_multi.total_matches == 1
    assert resp_multi.candidates[0].doc_id == "11111111-1111-1111-1111-111111111111"

    # Non-overlapping tags (AND): tag-dl-uuid AND tag-bio-uuid (No document has both)
    resp_none = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            tag_ids=["tag-dl-uuid", "tag-bio-uuid"],
        ),
        index=populated_index,
    )
    assert resp_none.total_matches == 0


def test_date_range_filtering(populated_index: InvertedIndex):
    """Requirement 4: Date range filter on created_at UTC."""
    engine = SearchEngine(analyzer=TextAnalyzer(filter_stopwords=False))

    base_time = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)

    # Filter window: 11:00 to 13:00 (Only Doc 2 created at 12:00 matches)
    resp_window = engine.search(
        SearchQuery(
            query="neural networks",
            generation_id=populated_index.generation_id,
            date_from=base_time + timedelta(hours=1),
            date_to=base_time + timedelta(hours=3),
        ),
        index=populated_index,
    )
    assert resp_window.total_matches == 1
    assert resp_window.candidates[0].doc_id == "22222222-2222-2222-2222-222222222222"

    # Invalid range: date_from > date_to raises ValueError
    with pytest.raises(ValueError) as exc_info:
        engine.search(
            SearchQuery(
                query="neural networks",
                generation_id=populated_index.generation_id,
                date_from=base_time + timedelta(hours=5),
                date_to=base_time + timedelta(hours=1),
            ),
            index=populated_index,
        )
    assert "date_from must not be greater than date_to" in str(exc_info.value)


def test_status_filter_excludes_drafts(populated_index: InvertedIndex):
    """Requirement 4: Status filter excludes draft documents."""
    engine = SearchEngine(analyzer=TextAnalyzer(filter_stopwords=False))

    # Query matching draft doc 4
    resp = engine.search(
        SearchQuery(
            query="study",  # only in draft Doc 4
            generation_id=populated_index.generation_id,
            status_filter="published",
        ),
        index=populated_index,
    )
    assert resp.total_matches == 0
    assert resp.candidates == []


def test_stable_tie_breaking():
    """Requirement 4: Stable tie-breaking: score DESC, doc_id ASC."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="tie-break-gen", analyzer=analyzer)

    # Create 3 documents with IDENTICAL text and identical length
    # IDs are purposely inserted out of alphabetical order: Z, A, M
    index.upsert_document("zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", "identical text content", "Z Title")
    index.upsert_document("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "identical text content", "A Title")
    index.upsert_document("mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm", "identical text content", "M Title")

    engine = SearchEngine(analyzer=analyzer)
    resp = engine.search(
        SearchQuery(query="identical text", generation_id="tie-break-gen"),
        index=index,
    )

    assert resp.total_matches == 3
    # Scores must all be identical
    scores = [c.score for c in resp.candidates]
    assert scores[0] == scores[1] == scores[2]

    # Tie-break MUST sort lexicographically by doc_id ASC: A, M, Z
    result_ids = [c.doc_id for c in resp.candidates]
    assert result_ids == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm",
        "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    ]


def test_empty_corpus_handling():
    """Requirement 4: Empty corpus (N=0) returns empty candidate set without ZeroDivisionError."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    empty_index = InvertedIndex(generation_id="empty-gen", analyzer=analyzer)

    engine = SearchEngine(analyzer=analyzer)
    resp = engine.search(
        SearchQuery(query="deep learning", generation_id="empty-gen"),
        index=empty_index,
    )

    assert resp.total_matches == 0
    assert resp.candidates == []
    assert resp.corpus_stats["total_docs"] == 0
    assert resp.corpus_stats["avg_doc_len"] == 0.0


def test_unknown_terms_handling():
    """Requirement 4: Query with unknown vocabulary returns empty results without crashing."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="known-gen", analyzer=analyzer)
    index.upsert_document("doc-1", "regular computer software", "Software")

    engine = SearchEngine(analyzer=analyzer)
    resp = engine.search(
        SearchQuery(query="completely_unheard_of_cryptic_term_987", generation_id="known-gen"),
        index=index,
    )

    assert resp.total_matches == 0
    assert resp.candidates == []
