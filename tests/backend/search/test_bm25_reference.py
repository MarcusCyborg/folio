"""
Reference and Ground Truth Tests for Okapi BM25 (P04).

Contains:
1. Exact hand-calculated step-by-step verification on a small 3-document fixture
2. Brute-force reference scorer comparison (verifying index vs brute-force equivalence)
3. Parameter sensitivity tests (varying k1, b)
4. Title boost separation and formula verification
5. TF-IDF baseline scorer verification
"""

import math
from typing import List, Dict, Tuple
import pytest

from src.backend.search.analyzer import TextAnalyzer
from src.backend.search.index import InvertedIndex
from src.backend.search.bm25 import BM25Scorer
from src.backend.search.tfidf import TfIdfScorer
from src.backend.search.engine import SearchEngine, SearchQuery


class BruteForceBM25:
    """
    Reference brute-force Okapi BM25 implementation.
    Does NOT use an inverted index; scans documents directly to provide
    a ground-truth oracle for testing index equivalence.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75, analyzer: TextAnalyzer = None):
        self.k1 = k1
        self.b = b
        self.analyzer = analyzer or TextAnalyzer(filter_stopwords=False)

    def score_corpus(
        self,
        corpus: List[Dict[str, str]],
        query: str,
    ) -> List[Tuple[str, float]]:
        """
        Calculates BM25 scores for all documents in corpus via direct linear scan.
        """
        N = len(corpus)
        if N == 0:
            return []

        doc_tokens = {doc["id"]: self.analyzer.tokenize(doc["text"]) for doc in corpus}
        doc_lengths = {doc_id: len(tokens) for doc_id, tokens in doc_tokens.items()}
        total_tokens = sum(doc_lengths.values())
        avgdl = total_tokens / N if N > 0 else 0.0

        query_terms = self.analyzer.tokenize(query)
        if not query_terms:
            return []

        # Document frequency df(t)
        df: Dict[str, int] = {}
        for term in set(query_terms):
            df[term] = sum(1 for tokens in doc_tokens.values() if term in tokens)

        # IDF
        idf: Dict[str, float] = {}
        for term in set(query_terms):
            n_t = df.get(term, 0)
            if n_t > 0:
                idf[term] = math.log(1.0 + (N - n_t + 0.5) / (n_t + 0.5))
            else:
                idf[term] = 0.0

        # Score documents
        results = []
        for doc in corpus:
            doc_id = doc["id"]
            tokens = doc_tokens[doc_id]
            dl = doc_lengths[doc_id]
            k_factor = self.k1 * (1.0 - self.b + self.b * (dl / avgdl))

            # Term frequency
            from collections import Counter
            tf_map = Counter(tokens)

            doc_score = 0.0
            for term in query_terms:
                tf = tf_map.get(term, 0)
                if tf > 0:
                    tf_norm = (tf * (self.k1 + 1.0)) / (tf + k_factor)
                    doc_score += idf[term] * tf_norm

            if doc_score > 0.0:
                results.append((doc_id, round(doc_score, 6)))

        # Deterministic sort: score DESC, doc_id ASC
        results.sort(key=lambda x: (-x[1], x[0]))
        return results


def test_hand_calculated_bm25_example():
    """
    Requirement 6: Step-by-step verification of hand-calculated Okapi BM25 values.
    
    Setup:
      N = 3 documents:
        D1 ("doc-1"): "quantum computing neural" (|D1| = 3)
        D2 ("doc-2"): "neural networks deep learning practice" (|D2| = 5)
        D3 ("doc-3"): "deep learning neural networks" (|D3| = 4)
      Total tokens = 12, avgdl = 4.0
      k1 = 1.5, b = 0.75
      Query = "deep neural" -> ['deep', 'neural']
      
      df("deep") = 2 (in D2, D3)
      df("neural") = 3 (in D1, D2, D3)
      
      IDF("deep")   = ln(1 + (3 - 2 + 0.5)/(2 + 0.5)) = ln(1.6) ≈ 0.4700036
      IDF("neural") = ln(1 + (3 - 3 + 0.5)/(3 + 0.5)) = ln(8/7) ≈ 0.1335314
      
      Length normalization factor K(d) = 1.5 * (0.25 + 0.1875 * |d|):
        K(D1) = 1.21875
        K(D2) = 1.78125
        K(D3) = 1.50000
        
      Expected scores:
        D3: 0.4700036 + 0.1335314 = 0.603535 (Rank 1)
        D2: 0.4224752 + 0.1200282 = 0.542503 (Rank 2)
        D1: 0.0000000 + 0.1504579 = 0.150458 (Rank 3)
    """
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="hand-calc-gen", analyzer=analyzer)

    index.upsert_document("doc-1", "quantum computing neural", "Doc 1")
    index.upsert_document("doc-2", "neural networks deep learning practice", "Doc 2")
    index.upsert_document("doc-3", "deep learning neural networks", "Doc 3")

    scorer = BM25Scorer(k1=1.5, b=0.75, analyzer=analyzer)

    # 1. Verify IDF values
    idf_deep = scorer.compute_idf(df=2, total_docs=3)
    expected_idf_deep = math.log(1.6)
    assert abs(idf_deep - expected_idf_deep) < 1e-6
    assert abs(idf_deep - 0.4700036) < 1e-6

    idf_neural = scorer.compute_idf(df=3, total_docs=3)
    expected_idf_neural = math.log(8.0 / 7.0)
    assert abs(idf_neural - expected_idf_neural) < 1e-6
    assert abs(idf_neural - 0.1335314) < 1e-6

    # 2. Score doc-1
    tfs_1 = analyzer.analyze("quantum computing neural").term_frequencies
    score_1 = scorer.score_candidate("doc-1", tfs_1, index, ["deep", "neural"])
    assert abs(score_1.raw_bm25 - 0.150458) < 1e-5

    # 3. Score doc-2
    tfs_2 = analyzer.analyze("neural networks deep learning practice").term_frequencies
    score_2 = scorer.score_candidate("doc-2", tfs_2, index, ["deep", "neural"])
    assert abs(score_2.raw_bm25 - 0.542503) < 1e-5

    # 4. Score doc-3
    tfs_3 = analyzer.analyze("deep learning neural networks").term_frequencies
    score_3 = scorer.score_candidate("doc-3", tfs_3, index, ["deep", "neural"])
    assert abs(score_3.raw_bm25 - 0.603535) < 1e-5

    # 5. Search via SearchEngine and verify complete ranking order
    engine = SearchEngine(analyzer=analyzer)
    response = engine.search(
        SearchQuery(query="deep neural", generation_id="hand-calc-gen", k1=1.5, b=0.75),
        index=index,
    )

    assert response.total_matches == 3
    assert [c.doc_id for c in response.candidates] == ["doc-3", "doc-2", "doc-1"]
    assert response.candidates[0].rank == 1
    assert response.candidates[1].rank == 2
    assert response.candidates[2].rank == 3
    assert abs(response.candidates[0].score - 0.603535) < 1e-5
    assert abs(response.candidates[1].score - 0.542503) < 1e-5
    assert abs(response.candidates[2].score - 0.150458) < 1e-5


def test_index_vs_brute_force_reference_equality():
    """
    Requirement 6: Inverted index retrieval produces EXACT same scores and ranks
    as brute-force linear reference scan across multiple queries.
    """
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="bf-test-gen", analyzer=analyzer)

    corpus = [
        {"id": "doc-a", "title": "AI Intro", "text": "artificial intelligence and machine learning"},
        {"id": "doc-b", "title": "Quantum", "text": "quantum computing with superconducting qubits"},
        {"id": "doc-c", "title": "Deep Nets", "text": "deep neural networks and artificial intelligence practice"},
        {"id": "doc-d", "title": "Reinforcement", "text": "reinforcement learning in robotics and artificial intelligence"},
        {"id": "doc-e", "title": "Biology", "text": "computational biology using machine learning algorithms"},
    ]

    for d in corpus:
        index.upsert_document(d["id"], d["text"], d["title"])

    bf_scorer = BruteForceBM25(k1=1.5, b=0.75, analyzer=analyzer)
    engine = SearchEngine(analyzer=analyzer)

    test_queries = [
        "artificial intelligence",
        "machine learning",
        "quantum computing",
        "robotics intelligence",
        "deep neural networks learning",
    ]

    for q in test_queries:
        # 1. Oracle ground truth from brute-force scanner
        bf_results = bf_scorer.score_corpus(corpus, q)

        # 2. Results from inverted index search engine
        idx_resp = engine.search(
            SearchQuery(query=q, generation_id="bf-test-gen", k1=1.5, b=0.75),
            index=index,
        )

        assert idx_resp.total_matches == len(bf_results), f"Count mismatch for query '{q}'"
        for rank_idx, (bf_id, bf_score) in enumerate(bf_results):
            hit = idx_resp.candidates[rank_idx]
            assert hit.doc_id == bf_id, f"Rank {rank_idx+1} mismatch for query '{q}': {hit.doc_id} != {bf_id}"
            assert abs(hit.score - bf_score) < 1e-5, f"Score mismatch for doc {bf_id} on query '{q}'"


def test_parameter_sensitivity_k1_and_b():
    """Requirement 3: Okapi BM25 respects variations in k1 and b parameters."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="param-gen", analyzer=analyzer)

    # Short doc vs long doc containing same term frequency
    index.upsert_document("short", "apple apple", "Short")
    index.upsert_document("long", "apple apple " + "orange " * 50, "Long")

    engine = SearchEngine(analyzer=analyzer)

    # When b = 0.0 (no length normalization), length should NOT penalize the long document!
    resp_b0 = engine.search(
        SearchQuery(query="apple", generation_id="param-gen", k1=1.5, b=0.0),
        index=index,
    )
    score_short_b0 = next(c.score for c in resp_b0.candidates if c.doc_id == "short")
    score_long_b0 = next(c.score for c in resp_b0.candidates if c.doc_id == "long")
    assert abs(score_short_b0 - score_long_b0) < 1e-5

    # When b = 0.75 (standard length normalization), short document should score strictly higher!
    resp_b75 = engine.search(
        SearchQuery(query="apple", generation_id="param-gen", k1=1.5, b=0.75),
        index=index,
    )
    score_short_b75 = next(c.score for c in resp_b75.candidates if c.doc_id == "short")
    score_long_b75 = next(c.score for c in resp_b75.candidates if c.doc_id == "long")
    assert score_short_b75 > score_long_b75


def test_title_boost_separation():
    """Requirement 3: Title boost is strictly separated and documented."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="tb-gen", analyzer=analyzer)

    # Doc 1 has query in title and content, Doc 2 has query only in content
    index.upsert_document("doc-title", "Deep Learning Foundations and applications", "Deep Learning Foundations")
    index.upsert_document("doc-body", "foundations and applications of deep learning", "Unrelated Title")

    engine = SearchEngine(analyzer=analyzer)

    # Without title boost (title_weight = 0.0)
    resp_pure = engine.search(
        SearchQuery(query="deep learning", generation_id="tb-gen", enable_title_boost=False),
        index=index,
    )
    for c in resp_pure.candidates:
        assert c.title_boost == 1.0
        assert c.score == c.raw_bm25

    # With title boost (title_weight = 0.5)
    resp_boosted = engine.search(
        SearchQuery(
            query="deep learning",
            generation_id="tb-gen",
            enable_title_boost=True,
            title_weight=0.5,
        ),
        index=index,
    )
    hit_title = next(c for c in resp_boosted.candidates if c.doc_id == "doc-title")
    # Title coverage: 'deep' and 'learning' are both in title -> coverage = 1.0 -> boost = 1.0 + 0.5 * 1.0 = 1.5
    assert hit_title.title_boost == 1.5
    assert abs(hit_title.score - round(hit_title.raw_bm25 * 1.5, 6)) < 1e-5


def test_tfidf_baseline_scorer():
    """Requirement 3: TF-IDF baseline scorer evaluates candidates cleanly."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    index = InvertedIndex(generation_id="tfidf-gen", analyzer=analyzer)

    index.upsert_document("d1", "neural network neural", "Title 1")
    index.upsert_document("d2", "quantum network", "Title 2")

    scorer = TfIdfScorer(normalize_length=True)
    tfs_d1 = analyzer.analyze("neural network neural").term_frequencies
    score_d1 = scorer.score_candidate("d1", tfs_d1, index, ["neural", "network"])
    assert score_d1 > 0.0
