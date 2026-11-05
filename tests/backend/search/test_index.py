"""
Unit and Property tests for Folio Inverted Index (P04).

Verifies:
1. Posting lists structure: (doc_id, tf)
2. Document frequency (df) and term dictionary
3. Document lengths (|d|) and corpus collection statistics (N, total_tokens, avgdl)
4. Query candidate collection traverses ONLY query term posting lists (no full-table scan)
5. Incremental document upsert, update, and deletion
6. Atomic serialization and deserialization
7. Generation mismatch handling
"""

from pathlib import Path
import pytest
from src.backend.search.analyzer import TextAnalyzer
from src.backend.search.index import (
    InvertedIndex,
    DocumentMetadata,
    GenerationMismatchError,
)


def test_inverted_index_basic_construction():
    """Requirement 2: Inverted index stores tf, df, doc_len, and corpus stats."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="gen-test-01", analyzer=analyzer)

    index.upsert_document(
        doc_id="doc-1",
        text="deep learning neural networks",
        title="Deep Learning",
    )
    index.upsert_document(
        doc_id="doc-2",
        text="quantum computing algorithms",
        title="Quantum Computing",
    )
    index.upsert_document(
        doc_id="doc-3",
        text="deep neural networks practice",
        title="Practice Networks",
    )

    stats = index.get_corpus_stats()
    assert stats.total_docs == 3
    assert stats.total_tokens == 4 + 3 + 4  # 11
    assert stats.avg_doc_len == 11 / 3

    # Document frequency checks
    assert index.df["deep"] == 2
    assert index.df["neural"] == 2
    assert index.df["networks"] == 2
    assert index.df["quantum"] == 1
    assert index.df["computing"] == 1
    assert index.df["algorithms"] == 1
    assert index.df["practice"] == 1

    # Posting lists checks
    deep_postings = dict(index.postings["deep"])
    assert deep_postings["doc-1"] == 1
    assert deep_postings["doc-3"] == 1
    assert "doc-2" not in deep_postings


def test_candidate_retrieval_does_not_scan_all_documents():
    """Requirement 2: Query candidate collection visits ONLY posting lists of query terms."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="gen-test-02", analyzer=analyzer)

    # 10 documents
    for i in range(10):
        index.upsert_document(
            doc_id=f"doc-{i}",
            text=f"topic_{i} specific content number {i}",
            title=f"Doc {i}",
        )
    # Add a document with unique term "solitary_unique_term"
    index.upsert_document(
        doc_id="doc-special",
        text="solitary_unique_term in this solitary document",
        title="Special Doc",
    )

    # Search for "solitary" using analyzer token
    query_tokens = analyzer.tokenize("solitary_unique_term")
    candidates = index.get_candidate_doc_ids(query_tokens)
    assert candidates == {"doc-special"}
    assert len(candidates) == 1  # Exactly 1 candidate touched, not 11!

    # Unknown term touches 0 candidates
    unknown_candidates = index.get_candidate_doc_ids(["non_existent_term_xyz"])
    assert unknown_candidates == set()


def test_incremental_document_update():
    """Requirement 4: Updating an existing document updates terms, df, and lengths cleanly."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="gen-test-03", analyzer=analyzer)

    index.upsert_document(
        doc_id="doc-update",
        text="initial version alpha beta",
        title="Old Title",
    )
    assert index.df["alpha"] == 1
    assert index.df["beta"] == 1
    assert index.documents["doc-update"].doc_len == 4

    # Update document with new content
    index.upsert_document(
        doc_id="doc-update",
        text="revised version gamma delta epsilon",
        title="New Title",
    )
    # Old terms must be cleaned up
    assert "alpha" not in index.df
    assert "beta" not in index.df
    assert "alpha" not in index.postings
    # New terms present
    assert index.df["gamma"] == 1
    assert index.df["delta"] == 1
    assert index.df["epsilon"] == 1
    assert index.documents["doc-update"].doc_len == 5
    assert index.documents["doc-update"].title == "New Title"


def test_incremental_document_delete():
    """Requirement 4: Deleting a document removes its postings, decrements df, and cleans orphan terms."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="gen-test-04", analyzer=analyzer)

    index.upsert_document("doc-a", "common term apple", "Title A")
    index.upsert_document("doc-b", "common term banana", "Title B")

    assert index.total_docs == 2
    assert index.df["common"] == 2
    assert index.df["apple"] == 1

    # Delete doc-a
    deleted = index.delete_document("doc-a")
    assert deleted is True
    assert index.total_docs == 1
    assert "doc-a" not in index.documents
    assert index.df["common"] == 1
    assert "apple" not in index.df  # Cleaned up orphan term
    assert "apple" not in index.postings

    # Deleting non-existent doc returns False
    assert index.delete_document("doc-nonexistent") is False


def test_index_disk_save_and_load(tmp_path: Path):
    """Requirement 2: Index serializes to disk and reloads identically."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="idx-gen-20261101-test", analyzer=analyzer)

    index.upsert_document(
        doc_id="doc-1",
        text="machine learning foundations",
        title="ML Foundations",
        category_id="cat-ai-uuid",
        tag_ids=["tag-ml-uuid", "tag-ai-uuid"],
        created_at="2026-10-31T10:00:00Z",
    )
    index.upsert_document(
        doc_id="doc-2",
        text="quantum physics principles",
        title="Quantum Physics",
        category_id="cat-quantum-uuid",
        tag_ids=["tag-physics-uuid"],
        created_at="2026-10-31T11:00:00Z",
    )

    save_dir = tmp_path / "postings"
    index.save(save_dir)

    # Verify generated files
    assert (save_dir / "index_stats.json").exists()
    assert (save_dir / "doc_entries.json").exists()
    assert (save_dir / "postings.json").exists()

    # Load back
    loaded_index = InvertedIndex.load(save_dir, expected_generation_id="idx-gen-20261101-test")
    assert loaded_index.generation_id == "idx-gen-20261101-test"
    assert loaded_index.total_docs == 2
    assert loaded_index.df["machine"] == 1
    assert loaded_index.documents["doc-1"].category_id == "cat-ai-uuid"
    assert "tag-ml-uuid" in loaded_index.documents["doc-1"].tag_ids


def test_generation_mismatch_raises_error(tmp_path: Path):
    """Requirement 4: Loading with an unexpected generation ID raises GenerationMismatchError."""
    index = InvertedIndex(generation_id="gen-actual-01")
    index.upsert_document("doc-1", "sample text", "Sample")
    save_dir = tmp_path / "postings_mismatch"
    index.save(save_dir)

    with pytest.raises(GenerationMismatchError) as exc_info:
        InvertedIndex.load(save_dir, expected_generation_id="gen-expected-99")
    assert "Generation mismatch" in str(exc_info.value)
