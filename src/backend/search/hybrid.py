import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from src.backend.core.config import settings
from src.backend.search.engine import CandidateHit
from src.backend.search.semantic import SemanticCandidateHit

# Pinned IR Versions
HYBRID_ANALYZER_VERSION = "1.0.0"
HYBRID_MODEL_VERSION = "all-MiniLM-L6-v2"


def fuse_candidates_rrf(
    bm25_candidates: List[CandidateHit],
    semantic_candidates: List[SemanticCandidateHit],
    top_k: int = 100,
    rrf_k: Optional[int] = None,
    w_sparse: Optional[float] = None,
    w_dense: Optional[float] = None,
) -> List[CandidateHit]:
    """
    Executes Reciprocal Rank Fusion (RRF) between lexical BM25 and dense vector candidates.
    - Pinned model & analyzer version declared in metadata.
    - Operates entirely on canonical Folio Document IDs (no legacy URL/JSON dependency).
    - Applies deterministic tie-breaking: score DESC, doc_id ASC.
    - Returns standard CandidateHit instances for hydration.
    """
    k = rrf_k if rrf_k is not None else settings.RRF_K
    sparse_weight = w_sparse if w_sparse is not None else settings.W_SPARSE_HIGH
    dense_weight = w_dense if w_dense is not None else settings.W_DENSE_HIGH

    # Map candidate ranks
    bm25_ranks: Dict[str, int] = {hit.doc_id: hit.rank for hit in bm25_candidates}
    bm25_raw_scores: Dict[str, float] = {hit.doc_id: hit.raw_bm25 for hit in bm25_candidates}
    semantic_ranks: Dict[str, int] = {hit.doc_id: hit.rank for hit in semantic_candidates}

    all_doc_ids: Set[str] = set(bm25_ranks.keys()).union(set(semantic_ranks.keys()))

    scored_items: List[CandidateHit] = []

    for doc_id in all_doc_ids:
        rrf_score = 0.0

        if doc_id in semantic_ranks:
            rank_dense = semantic_ranks[doc_id]
            rrf_score += dense_weight * (1.0 / (k + rank_dense))

        if doc_id in bm25_ranks:
            rank_sparse = bm25_ranks[doc_id]
            rrf_score += sparse_weight * (1.0 / (k + rank_sparse))

        raw_bm25 = bm25_raw_scores.get(doc_id, 0.0)

        scored_items.append(
            CandidateHit(
                doc_id=doc_id,
                score=round(rrf_score, 8),
                rank=0,  # Assigned after sorting
                raw_bm25=raw_bm25,
                title_boost=1.0,
            )
        )

    # Deterministic Tie-Breaking: Primary sort = score DESC, Secondary sort = doc_id ASC
    scored_items.sort(key=lambda hit: (-hit.score, hit.doc_id))

    ranked_hits: List[CandidateHit] = []
    for rank_idx, hit in enumerate(scored_items[:top_k], start=1):
        ranked_hits.append(
            CandidateHit(
                doc_id=hit.doc_id,
                score=hit.score,
                rank=rank_idx,
                raw_bm25=hit.raw_bm25,
                title_boost=hit.title_boost,
            )
        )

    return ranked_hits
