"""
Unit tests for Folio IR Evaluation Scientist Metrics (P06).
Verifies mathematical accuracy of Precision@K, Recall@K, MAP@K, MRR@K, nDCG@K.
"""

import math
import pytest
from evaluate.run_eval import (
    compute_precision_at_k,
    compute_recall_at_k,
    compute_average_precision_at_k,
    compute_reciprocal_rank_at_k,
    compute_dcg_at_k,
    compute_idcg_at_k,
    compute_ndcg_at_k,
)


def test_precision_at_k():
    qrels = {"d1": 1, "d2": 1, "d3": 1}

    # All relevant
    assert compute_precision_at_k(["d1", "d2", "d3", "d4", "d5"], qrels, k=3) == 1.0
    # 2 out of 5 relevant
    assert compute_precision_at_k(["d1", "d4", "d2", "d5", "d6"], qrels, k=5) == 2.0 / 5.0
    # 0 relevant in top 2
    assert compute_precision_at_k(["d4", "d5", "d1"], qrels, k=2) == 0.0
    # Edge case: k=0
    assert compute_precision_at_k(["d1"], qrels, k=0) == 0.0


def test_recall_at_k():
    qrels = {"d1": 1, "d2": 1, "d3": 1, "d4": 1} # Total 4 relevant

    # Retrieved 2 out of 4 in top 5
    assert compute_recall_at_k(["d1", "x1", "d2", "x2", "x3"], qrels, k=5) == 2.0 / 4.0
    # Retrieved all 4 in top 5
    assert compute_recall_at_k(["d1", "d2", "d3", "d4", "x1"], qrels, k=5) == 1.0
    # None retrieved in top 3
    assert compute_recall_at_k(["x1", "x2", "x3", "d1"], qrels, k=3) == 0.0


def test_average_precision_at_k():
    qrels = {"d1": 1, "d2": 1, "d3": 1} # Total 3 relevant

    # Perfect ranking: ranks 1, 2, 3 -> AP = (1/1 + 2/2 + 3/3) / 3 = 1.0
    retrieved_perfect = ["d1", "d2", "d3", "d4", "d5"]
    assert pytest.approx(compute_average_precision_at_k(retrieved_perfect, qrels, k=5), 1e-6) == 1.0

    # Ranks 1 and 3 relevant out of 3:
    # rank 1: hit 1, P@1 = 1/1
    # rank 2: miss
    # rank 3: hit 2, P@3 = 2/3
    # AP@5 = (1/1 + 2/3) / 3 = (5/3) / 3 = 5/9 ≈ 0.555556
    retrieved_partial = ["d1", "x1", "d2", "x2", "x3"]
    assert pytest.approx(compute_average_precision_at_k(retrieved_partial, qrels, k=5), 1e-6) == 5.0 / 9.0

    # Zero hits
    assert compute_average_precision_at_k(["x1", "x2"], qrels, k=5) == 0.0


def test_reciprocal_rank_at_k():
    qrels = {"d1": 1, "d2": 1}

    # First hit at rank 1 -> RR = 1.0
    assert compute_reciprocal_rank_at_k(["d1", "x1"], qrels, k=5) == 1.0
    # First hit at rank 2 -> RR = 0.5
    assert compute_reciprocal_rank_at_k(["x1", "d2", "d1"], qrels, k=5) == 0.5
    # First hit at rank 4 -> RR = 0.25
    assert compute_reciprocal_rank_at_k(["x1", "x2", "x3", "d1"], qrels, k=5) == 0.25
    # First hit beyond k -> RR = 0.0
    assert compute_reciprocal_rank_at_k(["x1", "x2", "d1"], qrels, k=2) == 0.0


def test_ndcg_graded_relevance():
    # Graded qrels: d1 has grade 2, d2 has grade 1
    qrels = {"d1": 2, "d2": 1}

    # Perfect ranking: ["d1", "d2"]
    # DCG = (2^2 - 1)/log2(2) + (2^1 - 1)/log2(3) = 3/1 + 1/1.58496 = 3.63093
    # IDCG = DCG
    # nDCG = 1.0
    assert pytest.approx(compute_ndcg_at_k(["d1", "d2", "x1"], qrels, k=3), 1e-6) == 1.0

    # Inverted ranking: ["d2", "d1"]
    # DCG = (2^1 - 1)/log2(2) + (2^2 - 1)/log2(3) = 1/1 + 3/1.58496 = 1 + 1.89279 = 2.89279
    # nDCG = 2.89279 / 3.63093 ≈ 0.7967
    ndcg_inverted = compute_ndcg_at_k(["d2", "d1", "x1"], qrels, k=3)
    assert 0.79 < ndcg_inverted < 0.81

    # Completely non-relevant: ["x1", "x2"]
    assert compute_ndcg_at_k(["x1", "x2"], qrels, k=3) == 0.0


def test_negative_queries_handling():
    # Negative query has empty qrels: {}
    empty_qrels = {}

    # Empty retrieval is correct behavior (P=1.0, Recall=1.0, nDCG=1.0)
    assert compute_precision_at_k([], empty_qrels, k=10) == 1.0
    assert compute_recall_at_k([], empty_qrels, k=10) == 1.0
    assert compute_ndcg_at_k([], empty_qrels, k=10) == 1.0
    assert compute_average_precision_at_k([], empty_qrels, k=10) == 0.0
    assert compute_reciprocal_rank_at_k([], empty_qrels, k=10) == 0.0

    # False positive retrieval for negative query should result in 0 precision and 0 recall
    assert compute_precision_at_k(["doc_unexpected"], empty_qrels, k=10) == 0.0
    assert compute_recall_at_k(["doc_unexpected"], empty_qrels, k=10) == 0.0
    assert compute_ndcg_at_k(["doc_unexpected"], empty_qrels, k=10) == 0.0
