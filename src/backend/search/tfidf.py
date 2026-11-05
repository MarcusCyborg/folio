"""
TF-IDF Baseline Scorer for Folio.

Provides an optional classic Information Retrieval baseline for comparative evaluation:
- Log-scaled Term Frequency: TF(t, d) = 1 + ln(tf(t, d)) if tf > 0 else 0
- Standard Inverse Document Frequency: IDF(t) = ln(1 + (N / df(t)))
- Sublinear length normalization option: score / sqrt(|d| + 1)
"""

import math
from typing import Dict, List, Optional
from src.backend.search.index import InvertedIndex


class TfIdfScorer:
    """Classic TF-IDF retrieval baseline."""

    def __init__(self, normalize_length: bool = True):
        self.normalize_length = normalize_length

    def compute_idf(self, df: int, total_docs: int) -> float:
        if total_docs <= 0 or df <= 0:
            return 0.0
        return math.log(1.0 + (total_docs / df))

    def score_candidate(
        self,
        doc_id: str,
        term_freqs: Dict[str, int],
        index: InvertedIndex,
        query_terms: List[str],
    ) -> float:
        doc_meta = index.documents.get(doc_id)
        if not doc_meta or index.total_docs == 0:
            return 0.0

        score = 0.0
        for term in query_terms:
            tf = term_freqs.get(term, 0)
            if tf <= 0:
                continue

            df = index.df.get(term, 0)
            idf = self.compute_idf(df, index.total_docs)
            tf_log = 1.0 + math.log(tf)
            score += tf_log * idf

        if self.normalize_length and doc_meta.doc_len > 0:
            score = score / math.sqrt(doc_meta.doc_len + 1.0)

        return score
